"""景氣階段判定與轉折訊號（需求文件第 3.0、7 節）。

從 1985-01（初始＝成長期）逐月往後推：
- 每個月計算各組判斷依據的成立比例與訊號等級（🟡 觀察 ≥ 1/3、🟠 警示 ≥ 1/2、🔴 確認 ≥ 2/3）
- 依「復甦 → 成長 → 榮景 → 衰退 → 復甦」順序，只轉入下一個階段；
  例外：「確立衰退」成立時，任何階段都可以直接轉入衰退期
- 記錄每次階段轉換與訊號等級變化（回測歷史），以及每日實際執行時的訊號紀錄（data/signal_log.csv）
"""
from __future__ import annotations

import csv
import json

from .criteria import Crit, build_criteria, month_range, months_between
from .settings import DATA_DIR

ORDER = ["recovery", "growth", "boom", "recession"]
ZH = {"recovery": "復甦期", "growth": "成長期", "boom": "榮景期", "recession": "衰退期"}
GROUPS = {
    "recovery": "復甦期判斷依據（景氣落底的訊號）",
    "growth": "成長期判斷依據（穩定擴張的訊號）",
    "boom_entry": "進入榮景期（特徵 E1–E4）",
    "top": "榮景期觸頂訊號",
    "recession": "確立衰退期到來（A 組）",
    "bottom": "判斷景氣落底（B 組）",
}
LEVEL_ZH = {"watch": "🟡 觀察", "warn": "🟠 警示", "confirm": "🔴 確認"}
RANK = {None: 0, "watch": 1, "warn": 2, "confirm": 3}
STATE_FILE = DATA_DIR / "signal_state.json"
LOG_FILE = DATA_DIR / "signal_log.csv"


def ratio_level(met: int, avail: int, lv: dict) -> str | None:
    if not avail or not met:
        return None
    r = met / avail
    for k in ("confirm", "warn", "watch"):
        if r >= lv[k] - 1e-9:
            return k
    return None


def run_stage(cfg: dict, today: str) -> dict:
    crits, extra = build_criteria(cfg, today)
    rules = cfg["stage_rules"]
    lv = rules["levels"]
    by_group: dict[str, list[Crit]] = {}
    for c in crits:
        by_group.setdefault(c.group, []).append(c)
    a1 = next(c for c in crits if c.key == "A1")
    a2 = next(c for c in crits if c.key == "A2")

    months = month_range(rules["initial"]["month"], today[:7])
    N = rules.get("memory_months", 1)
    rr = rules.get("recession", {"rule": "spec"})
    enter_lv = rules.get("enter_levels", {})
    # 先算好每一項每個月的成立狀態
    raw = {c.key: [c.at(m)[0] for m in months] for c in crits}

    def window(key: str, i: int, n: int):
        """近 n 個月內：曾成立 → True；都沒資料 → None；否則 False。"""
        vals = [v for v in raw[key][max(0, i - n + 1):i + 1] if v is not None]
        return None if not vals else any(vals)

    def recession_state(i: int) -> dict:
        a1m, a2m = raw["A1"][i], raw["A2"][i]
        if rr.get("rule") == "corroborated":
            p3 = window("P3", i, rr["p3_within"])
            a2w = window("A2", i, rr["a2_within"])
            tops = [window(c.key, i, rr["top_within"]) for c in by_group["top"]]
            ta = [t for t in tops if t is not None]
            top_ok = bool(ta) and sum(ta) / len(ta) >= rr["top_min"] - 1e-9
            fk = rr.get("fin")  # 金融情勢轉緊（A3）：可佐證 A1/A2，也可取代觸頂門檻
            fin = bool(fk and raw.get(fk) and raw[fk][i])
            core = (a1m and (a2w or p3 or fin)) or (a2m and (p3 or fin))
            confirm = bool(core and (top_ok or fin))
            why = []
            if a1m: why.append("A1 2 次消費陡降")
            if a2w: why.append(f"A2 民間投資急降（近 {rr['a2_within']} 個月）")
            if p3: why.append("觸頂依據 3 U 型結構確立")
            if top_ok: why.append(f"近 {rr['top_within']} 個月觸頂訊號 {sum(ta)}/{len(ta)} 項成立")
            if fin: why.append("A3 金融情勢轉緊")
        else:
            confirm, why = bool(a1m), (["A1 2 次消費陡降"] if a1m else [])
            if a2m: why.append("A2 民間投資急降")
        level = "confirm" if confirm else "warn" if (a1m or a2m) else None
        return {"level": level, "why": why}

    def group_state(i: int) -> dict:
        out = {}
        for g, cs in by_group.items():
            n = 1 if g == "recession" else N
            res = [(c, window(c.key, i, n)) for c in cs]
            avail = [r for r in res if r[1] is not None]
            met = [r for r in avail if r[1]]
            out[g] = {"met": len(met), "avail": len(avail), "total": len(cs),
                      "met_labels": [f"{r[0].no} {r[0].label}" for r in met]}
            if g == "recession":
                rs = recession_state(i)
                out[g]["level"] = rs["level"]
                out[g]["why"] = rs["why"]
            elif g == "bottom":
                out[g]["level"] = "warn" if len(met) >= 2 else None
            else:
                out[g]["level"] = ratio_level(len(met), len(avail), lv)
        return out

    def entry(target: str, gs: dict) -> dict:
        names = rules["enter"][target]
        if names == ["recession"]:
            return {"level": gs["recession"]["level"], "met": gs["recession"]["met"], "avail": gs["recession"]["avail"],
                    "met_labels": gs["recession"]["met_labels"]}
        met = sum(gs[n]["met"] for n in names)
        avail = sum(gs[n]["avail"] for n in names)
        labels = [x for n in names for x in gs[n]["met_labels"]]
        level = ratio_level(met, avail, lv)
        if target in enter_lv and avail and met / avail >= enter_lv[target] - 1e-9:
            level = "confirm"
        return {"level": level, "met": met, "avail": avail, "met_labels": labels}

    stage, since = rules["initial"]["stage"], months[0]
    reason = f"{months[0]} 依 NBER 景氣循環日期設定為初始階段（1985 年屬於擴張期）"
    timeline = [[months[0], None, stage]]
    events = [{"date": months[0], "type": "stage", "to": ZH[stage], "text": reason}]
    rec_confirm_since = None
    sig_prev: dict[str, str | None] = {}
    sig_since: dict[str, str] = {}
    gs = {}
    monitored = {}

    stay = rules.get("min_stage_months", 0)
    for i, m in enumerate(months):
        gs = group_state(i)
        rec = gs["recession"]
        if rec["level"] == "confirm":
            rec_confirm_since = rec_confirm_since or m
        else:
            rec_confirm_since = None

        # 階段轉換
        nxt = ORDER[(ORDER.index(stage) + 1) % 4]
        new, why = None, None
        if stage != "recession" and rec_confirm_since and rec_confirm_since >= since and m != since:
            new = "recession"
            why = f"「確立衰退」成立：{'、'.join(rec['why'])}"
        elif nxt != "recession" and months_between(since, m) >= stay:
            e = entry(nxt, gs)
            if e["level"] == "confirm":
                new = nxt
                thr = enter_lv.get(nxt, lv["confirm"])
                why = f"{ZH[nxt]}判斷依據 {e['met']}/{e['avail']} 項成立（門檻 {thr:.0%}{f'，近 {N} 個月內曾成立即計入' if N > 1 else ''}）"
        if new:
            timeline[-1][1] = m
            timeline.append([m, None, new])
            events.append({"date": m, "type": "stage", "from": ZH[stage], "to": ZH[new], "text": why})
            stage, since, reason = new, m, f"{m} 起{why}，判定進入{ZH[new]}"

        # 目前階段要監看的訊號
        nxt = ORDER[(ORDER.index(stage) + 1) % 4]
        monitored = {}
        if nxt != "recession":
            e = entry(nxt, gs)
            monitored[f"enter_{nxt}"] = {"name": f"{ZH[stage]} → {ZH[nxt]}", **e}
        if stage != "recession":
            monitored["enter_recession"] = {"name": f"{ZH[stage]} → 衰退期（確立衰退）", **entry("recession", gs)}
        if stage == "boom":
            monitored["top"] = {"name": "榮景期觸頂警示（可能即將進入衰退期）", **gs["top"]}
            ext = extra["extension"].at(m)[0]
            monitored["extension"] = {"name": "榮景期延長（初領失業救濟金持續創新低）", "level": "watch" if ext else None,
                                      "met": int(bool(ext)), "avail": 1, "met_labels": ["3-1 持續創新低"] if ext else []}
        if stage == "recession":
            monitored["bottom"] = {"name": "景氣落底，復甦倒數", **gs["bottom"]}
        if stage != "recession" and extra["a1_obs"].at(m)[0] and not a1.at(m)[0]:
            monitored["a1_obs"] = {"name": "第 1 次消費陡降（觀察中）", "level": "watch", "met": 1, "avail": 1,
                                   "met_labels": ["A1 第 1 次消費陡降"]}
        for k in set(sig_prev) | set(monitored):
            cur = monitored.get(k, {}).get("level")
            if cur != sig_prev.get(k):
                if cur:
                    sig_since[k] = m
                prev_name = monitored.get(k, {}).get("name") or k
                events.append({"date": m, "type": "signal", "key": k, "name": prev_name,
                               "from": LEVEL_ZH.get(sig_prev.get(k)), "to": LEVEL_ZH.get(cur),
                               "text": "、".join(monitored.get(k, {}).get("met_labels", [])) or "訊號解除"})
            sig_prev[k] = cur
        sig_prev = {k: v for k, v in sig_prev.items() if v}

    # ── 目前狀態 ──
    m = months[-1]
    groups = []
    for g, cs in by_group.items():
        items = [c.describe(m) for c in cs]
        n = 1 if g == "recession" else N
        for it in items:
            it["recent"] = bool(not it["met"] and window(it["key"], len(months) - 1, n))
        groups.append({"key": g, "why": gs[g].get("why"), "label": GROUPS[g], "met": gs[g]["met"], "avail": gs[g]["avail"], "total": gs[g]["total"],
                       "level": gs[g]["level"], "level_zh": LEVEL_ZH.get(gs[g]["level"]),
                       "excluded": [f"{i['no']} {i['label']}" for i in items if i["met"] is None],
                       "items": items})
    signals = []
    for k, s in monitored.items():
        if s.get("level"):
            st = sig_since.get(k, m)
            signals.append({"key": k, "name": s["name"], "level": s["level"], "level_zh": LEVEL_ZH[s["level"]],
                            "since": st, "met": s["met"], "avail": s["avail"], "met_labels": s["met_labels"]})
    pending = [{"key": k, "name": s["name"], "met": s["met"], "avail": s["avail"]} for k, s in monitored.items()]

    sc = cfg["stages"][stage]
    months_in = months_between(since, m)
    cur = {"key": stage, "name": ZH[stage], "since": since, "months": months_in, "reason": reason,
           "trait": sc.get("trait"), "invest": sc.get("invest", [])}
    if stage == "boom":
        floors = sc.get("equity_floor", [70, 50, 30])
        year = months_in // 12 + 1
        cur["boom_year"] = year
        cur["equity_floor"] = floors[min(year, len(floors)) - 1]

    u = extra["u_shape"]["state"]
    special = {"u_shape": {**u, "jolts_reversal": bool(extra["jolts_reversal"].at(m)[0])},
               "fed": extra["fed"].get(m) or {},
               "drops": extra["drops"]["events"][-1] if extra["drops"]["events"] else None,
               "surge": extra["second_surge"]["episodes"][-1] if extra["second_surge"]["episodes"] else None}
    marks = {"5": [{"x": e["low_date"], "y": e["low"], "text": "U 型底部"} for e in extra["u_shape"]["events"]]
                  + ([{"x": u["low_date"], "y": u["low"], "text": "本輪低點"}] if u else []),
             "16": [x for e in extra["second_surge"]["episodes"] if e["wave2"]
                    for x in ({"x": e["wave1"], "text": "第一波"}, {"x": e["wave2"], "text": "第二波"})]}
    return {"asof": m, "stage": cur, "caveat": rules.get("caveat"), "groups": groups, "signals": signals, "pending": pending, "special": special,
            "timeline": timeline, "events": events, "marks": marks, "_crits": crits, "_extra": extra}


# ── 每日實際執行的訊號紀錄（給第 4 階段 Email 比對用）───────────────
def record_live(result: dict, now: str) -> list[dict]:
    """和上次執行的狀態比較，有變化就寫入 data/signal_log.csv，回傳變化清單。"""
    prev = {}
    if STATE_FILE.exists():
        prev = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    cur = {"stage": result["stage"]["name"], "signals": {s["key"]: s["level"] for s in result["signals"]}}
    names = {s["key"]: s["name"] for s in result["signals"]}
    changes = []
    if prev.get("stage") and prev["stage"] != cur["stage"]:
        changes.append({"kind": "stage", "key": "stage", "name": "景氣階段", "from": prev["stage"], "to": cur["stage"]})
    ps = prev.get("signals", {})
    for k in set(ps) | set(cur["signals"]):
        a, b = ps.get(k), cur["signals"].get(k)
        if a != b:
            kind = "new" if not a else "cleared" if not b else "upgrade" if RANK[b] > RANK[a] else "downgrade"
            changes.append({"kind": kind, "key": k, "name": names.get(k) or prev.get("names", {}).get(k, k),
                            "from": LEVEL_ZH.get(a), "to": LEVEL_ZH.get(b)})
    sig = {s["key"]: s for s in result["signals"]}
    new_file = not LOG_FILE.exists()
    if changes or new_file:
        with LOG_FILE.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["time", "stage", "kind", "signal", "from", "to", "met", "items"])
            for c in changes:
                s = sig.get(c["key"], {})
                w.writerow([now, cur["stage"], c["kind"], c["name"], c["from"] or "", c["to"] or "",
                            f"{s.get('met', '')}/{s.get('avail', '')}" if s else "", "、".join(s.get("met_labels", []))])
    cur["names"] = names
    cur["time"] = now
    # 尚未寄出提醒信的變化（寄信失敗時保留，下次一起寄）；由 tracker/notify.py 寄出後清空
    cur["unsent"] = (prev.get("unsent", []) + [c | {"time": now} for c in changes])[-50:]
    STATE_FILE.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    return changes
