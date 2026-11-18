"""轉折點 Email 提醒（需求文件第 9 節）與資料抓取異常通知。

每日流程：抓資料 → 產生儀表板 → python run.py notify
- 只在有變化時寄信：新訊號、等級升級／降級、進入新階段、特殊訊號、訊號解除
- 變化由 tracker/stage.py 的 record_live 比對前一天狀態後，存在 data/signal_state.json 的 unsent；
  寄出後清空，所以同一個訊號持續、等級不變時不會重複寄
- 寄信失敗（例如還沒設定 Secrets）時保留，下次一起寄；超過 keep_days 天的舊變化不再寄
"""
from __future__ import annotations

import html
import json
from datetime import datetime

from . import mailer
from .settings import DATA_DIR, ROOT, load_config, stamp
from .stage import LEVEL_ZH, RANK, STATE_FILE

ZH = {"recovery": "復甦期", "growth": "成長期", "boom": "榮景期", "recession": "衰退期"}
KEY = {v: k for k, v in ZH.items()}
LEVEL_KEY = {v: k for k, v in LEVEL_ZH.items()}
KIND_ZH = {"stage": "進入新階段", "new": "新訊號", "upgrade": "等級升級", "downgrade": "等級降級", "cleared": "訊號解除"}
SPECIAL = {
    "extension": "初領失業救濟金持續創新低，榮景期可能延長（3.3 節依據 3-1）。",
    "a1_obs": "實質消費年增率出現第 1 次陡降；若之後再出現第 2 次陡降，確立衰退的機率升高（3.4 節 A1）。",
    "bottom": "景氣可能已經落底，進入復甦倒數（3.4 節 B 組）。",
    "top": "榮景期觸頂訊號增加，可能即將進入衰退期。",
}
PREVIEW = ROOT / "cache" / "email_preview.html"
e = html.escape


def _payload() -> dict:
    f = ROOT / "site" / "data.js"
    if not f.exists():
        raise RuntimeError("找不到 site/data.js，請先執行 python run.py build")
    t = f.read_text(encoding="utf-8")
    return json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))


def _groups_for(change: dict, cfg: dict) -> list[str]:
    k = change["key"]
    enter = cfg["stage_rules"]["enter"]
    if change["kind"] == "stage":
        return list(enter.get(KEY.get(change["to"], ""), []))
    if k.startswith("enter_"):
        return list(enter.get(k[6:], []))
    return {"top": ["top"], "bottom": ["bottom"], "a1_obs": ["recession"]}.get(k, [])


def _priority(c: dict) -> tuple:
    if c["kind"] == "stage":
        return (0, 0)
    if c["kind"] in ("new", "upgrade"):
        return (1, -RANK.get(LEVEL_KEY.get(c["to"]), 0))
    return (2 if c["kind"] == "downgrade" else 3, 0)


def subject(changes: list[dict], date: str, test: bool = False) -> str:
    top = sorted(changes, key=_priority)[0]
    if top["kind"] == "stage":
        mid, name = "進入新階段", f"{top['from']} → {top['to']}"
    elif top["kind"] == "cleared":
        mid, name = "訊號解除", top["name"]
    else:
        mid, name = top["to"], top["name"]
    more = f"（另有 {len(changes) - 1} 項變化）" if len(changes) > 1 else ""
    return f"{'[測試] ' if test else ''}[景氣轉折提醒] {date}｜{mid}｜{name}{more}"


def _icon(it: dict) -> str:
    return "—" if it["met"] is None else "✓" if it["met"] else "△" if it.get("near") else "✕"


def _change_line(c: dict) -> str:
    if c["kind"] == "stage":
        return f"{c['from']} → {c['to']}"
    if c["kind"] == "cleared":
        return f"{c['name']}：{c['from']} → 解除"
    return f"{c['name']}：{c['from'] or '無'} → {c['to']}"


def render(changes: list[dict], data: dict, cfg: dict, test: bool = False) -> tuple[str, str, str]:
    st = data["stage"]
    date = data["generated"][:10]
    url = cfg.get("email", {}).get("dashboard_url", "")
    only_cleared = all(c["kind"] == "cleared" for c in changes)
    groups = {g["key"]: g for g in st["groups"]}
    sigs = {s["key"]: s for s in st["signals"]}
    H, T = [], []

    if test:
        H.append('<p style="background:#fff4d6;padding:8px 12px;border-radius:8px">這是測試信：以目前所有訊號當作「新訊號」示範內容。</p>')
    # 1. 訊號等級與可能的轉折方向
    H.append('<h2 style="font-size:16px;margin:16px 0 6px">1. 這次的變化</h2><ul style="padding-left:20px;margin:0">')
    T.append("【這次的變化】")
    for c in sorted(changes, key=_priority):
        s = sigs.get(c["key"], {})
        extra = f"（成立 {s['met']}/{s['avail']} 項）" if s.get("avail") and c["kind"] != "cleared" else ""
        note = SPECIAL.get(c["key"], "")
        H.append(f"<li style=\"margin:4px 0\"><b>{e(KIND_ZH[c['kind']])}</b>｜{e(_change_line(c))}{e(extra)}"
                 + (f"<br><span style=\"color:#555\">{e(note)}</span>" if note and c["kind"] != "cleared" else "") + "</li>")
        T.append(f"- {KIND_ZH[c['kind']]}｜{_change_line(c)}{extra}")
    H.append("</ul>")

    if not only_cleared:
        # 2. 判斷依據逐項
        keys = list(dict.fromkeys(g for c in changes if c["kind"] != "cleared" for g in _groups_for(c, cfg)))
        if keys:
            H.append('<h2 style="font-size:16px;margin:20px 0 6px">2. 判斷依據成立狀況</h2>'
                     '<p style="font-size:12px;color:#777;margin:0 0 6px">✓ 成立｜△ 接近｜✕ 未成立｜— 資料缺漏（從分母扣除）</p>')
            T.append("\n【判斷依據成立狀況】")
        for k in keys:
            g = groups.get(k)
            if not g:
                continue
            H.append(f'<h3 style="font-size:15px;margin:12px 0 4px">{e(g["label"])}：成立 {g["met"]}/{g["avail"]} 項'
                     f'{" " + e(g["level_zh"]) if g.get("level_zh") else ""}</h3><table style="width:100%;border-collapse:collapse;font-size:14px">')
            T.append(f"{g['label']}：成立 {g['met']}/{g['avail']} 項")
            for it in g["items"]:
                vals = "；".join(dict.fromkeys(f"{p['label']} {p['value']}（{(p['date'] or '')[:7]}）"
                                               for p in it["parts"] if p.get("value") not in (None, "", "—")))
                color = "#1a7f37" if it["met"] else "#777"
                H.append(f'<tr><td style="vertical-align:top;padding:4px 6px 4px 0;color:{color};font-weight:700;width:18px">{_icon(it)}</td>'
                         f'<td style="padding:4px 0;border-bottom:1px solid #eee"><b>{e(it["no"])}</b> {e(it["label"])}'
                         + (f'<br><span style="font-size:13px;color:#555">{e(vals)}</span>' if vals else "") + "</td></tr>")
                T.append(f"  {_icon(it)} {it['no']} {it['label']}" + (f"｜{vals}" if vals else ""))
            H.append("</table>")
        # 3. 投資方向
        cur = st["stage"]
        H.append(f'<h2 style="font-size:16px;margin:20px 0 6px">3. {e(cur["name"])}的投資方向</h2>'
                 f'<p style="margin:0 0 4px;color:#555">目前階段：{e(cur["name"])}（{e(cur["since"])} 起，第 {cur["months"] + 1} 個月）</p><ul style="padding-left:20px;margin:0">')
        T.append(f"\n【{cur['name']}的投資方向】（{cur['since']} 起）")
        inv = list(cur.get("invest", []))
        if cur.get("equity_floor") is not None:
            inv.insert(0, f"榮景期第 {cur['boom_year']} 年：股票部位不低於 {cur['equity_floor']}%")
        for x in inv:
            H.append(f"<li>{e(x)}</li>")
            T.append(f"- {x}")
        H.append("</ul>")
        if st.get("caveat"):
            H.append(f'<p style="font-size:13px;color:#777;margin:12px 0 0">{e(st["caveat"])}</p>')

    # 目前所有訊號
    if st["signals"]:
        H.append('<h2 style="font-size:16px;margin:20px 0 6px">目前所有訊號</h2><ul style="padding-left:20px;margin:0">'
                 + "".join(f"<li>{e(s['level_zh'])} {e(s['name'])}（{e(s['since'])} 起）</li>" for s in st["signals"]) + "</ul>")
    else:
        H.append('<p style="margin:16px 0 0">目前沒有任何訊號。</p>')
    T.append(f"\n儀表板：{url}\n僅供參考，非投資建議。")
    title = "訊號解除通知" if only_cleared else "景氣轉折提醒"
    return subject(changes, date, test), mailer.page(title, "".join(H), url), "\n".join(T)


def _data_failure(cfg: dict) -> tuple[str, str, str] | None:
    """抓資料的步驟有超過一半序列失敗、且連續達到門檻次數時，寄系統異常通知（只在剛好達到門檻時寄一次）。"""
    status = json.loads((DATA_DIR / "status.json").read_text(encoding="utf-8"))
    n = cfg["settings"]["failure_alert_after_runs"]
    streak = status.get("consecutive_failed_runs", 0)
    if streak != n:
        return None
    last = status["runs"][-1] if status.get("runs") else {}
    failed = last.get("failed", [])
    errs = {k: v.get("last_error") for k, v in status["series"].items() if k in failed}
    sample = "；".join(dict.fromkeys(x for x in errs.values() if x))[:300]
    url = cfg.get("email", {}).get("dashboard_url", "")
    body = (f"<p>每日抓資料已<b>連續 {streak} 次</b>有超過一半的序列失敗（最近一次 {len(failed)}/{last.get('total', '?')} 個）。</p>"
            f"<p>錯誤訊息：{e(sample or '無')}</p>"
            "<p style=\"color:#555\">常見原因：FRED 金鑰失效、GitHub Secrets 被刪除、FRED 網站暫時無法連線。儀表板會繼續顯示最後一次成功的資料。</p>")
    return (f"[景氣儀表板｜系統異常] 抓取資料連續失敗 {streak} 次", mailer.page("系統異常通知", body, url),
            f"每日抓資料連續 {streak} 次失敗。錯誤：{sample}")


def run_notify(dry_run: bool = False, test: bool = False) -> list[str]:
    cfg = load_config()
    keep = cfg.get("email", {}).get("keep_days", 7)
    data = _payload()
    msgs, log = [], []

    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    if test:
        changes = [{"kind": "new", "key": s["key"], "name": s["name"], "from": None, "to": s["level_zh"]} for s in data["stage"]["signals"]] \
                  or [{"kind": "stage", "key": "stage", "name": "景氣階段", "from": "（測試）", "to": data["stage"]["stage"]["name"]}]
    else:
        today = datetime.strptime(stamp(cfg)[:10], "%Y-%m-%d")
        unsent = state.get("unsent", [])
        changes = [c for c in unsent if (today - datetime.strptime(c["time"][:10], "%Y-%m-%d")).days <= keep]
        if len(changes) < len(unsent):
            log.append(f"略過 {len(unsent) - len(changes)} 項超過 {keep} 天的舊變化")
    if changes:
        msgs.append(("signal", *render(changes, data, cfg, test)))
    if not test:
        fail = _data_failure(cfg)
        if fail:
            msgs.append(("failure", *fail))

    if not msgs:
        return log + ["沒有新的轉折變化，不寄信"]
    if dry_run:
        PREVIEW.parent.mkdir(exist_ok=True)
        PREVIEW.write_text(msgs[0][2], encoding="utf-8")
        return log + [f"（預覽，未寄出）主旨：{m[1]}" for m in msgs] + [f"信件預覽：{PREVIEW}"]
    problem = mailer.ready()
    if problem:
        return log + [f"⚠ {problem}，提醒信沒有寄出（變化會保留，設定好後下次一起寄）"] + [f"  待寄：{m[1]}" for m in msgs]
    for kind, subj, body, text in msgs:
        try:
            to = mailer.send(subj, body, text)
            log.append(f"已寄出：{subj}（{len(to)} 位收件人）")
            if kind == "signal" and not test:
                state["unsent"] = []
                STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as ex:  # noqa: BLE001 — 寄信失敗不能讓整個排程失敗
            log.append(f"⚠ 寄信失敗：{subj}｜{str(ex)[:200]}")
    return log
