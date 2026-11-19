"""回測（需求文件第 6 節）：1985 年至今，對照 NBER 衰退期間。

- 階段時間軸 vs NBER：每次衰退的開始（高峰後）與結束（谷底），系統判定提前／落後幾個月、有沒有誤判
- 每一項判斷依據：在各次轉折點附近第一次成立的時間（提前為負、落後為正），以及窗口外的誤判比例
- 規則比較：需求文件原始規則 vs 目前 config.yaml 的設定
⚠️ 使用修正後的資料（不是當時的初值），已考慮大致的發布延遲；只有 4 次衰退，參數容易過度貼合歷史
"""
from __future__ import annotations

import copy

from . import store
from .criteria import Crit, month_range, mnum
from .settings import DOCS_DIR
from .stage import ZH, run_stage

# 轉折點前後的觀察窗口（月）
WIN_PEAK = (-24, 6)     # 觸頂、確立衰退：衰退開始前 24 個月到開始後 6 個月
WIN_TROUGH = (-12, 18)  # 復甦、落底：谷底前 12 個月到谷底後 18 個月
MATCH = 12              # 系統判定的轉折在 NBER 日期前後 12 個月內，才算抓到


def nber_turns(start: str) -> list[dict]:
    rec = store.read_series("USREC")
    out, cur = [], None
    for i in range(1, len(rec)):
        d, v = rec[i]
        if v == 1 and rec[i - 1][1] == 0:
            cur = {"peak": d[:7]}
        elif v == 0 and rec[i - 1][1] == 1 and cur:
            cur["trough"] = rec[i - 1][0][:7]
            out.append(cur)
            cur = None
    return [t for t in out if t["peak"] >= start[:7]]


def spec_rules(cfg: dict) -> dict:
    """需求文件原始規則（去掉第 5 階段的調整）。"""
    c = copy.deepcopy(cfg)
    r = c["stage_rules"]
    r["memory_months"] = 1
    r["min_stage_months"] = 0
    r.pop("enter_levels", None)
    r["recession"] = {"rule": "spec"}
    return c


def evaluate(timeline: list, turns: list[dict], today: str) -> dict:
    entries = [(a, s) for a, _, s in timeline]
    rec_in = [mnum(a) for a, s in entries if s == "recession"]
    rcv_in = [mnum(a) for a, s in entries if s == "recovery"]
    used, rows = set(), []
    for t in turns:
        P, T = mnum(t["peak"]), mnum(t["trough"])
        e = next((x for x in rec_in if -MATCH <= x - P <= MATCH), None)
        r = next((x for x in rcv_in if -6 <= x - T <= 24), None)
        if e is not None:
            used.add(e)
        rows.append({"peak": t["peak"], "trough": t["trough"],
                     "enter": _ym(e), "enter_lag": None if e is None else e - P,
                     "recover": _ym(r), "recover_lag": None if r is None else r - T})
    false = [_ym(x) for x in rec_in if x not in used]
    # 誤判衰退的總月數（前後 12／18 個月都沒有 NBER 衰退）
    near = set()
    for t in turns:
        near |= set(range(mnum(t["peak"]) - 12, mnum(t["trough"]) + 19))
    false_months = 0
    for k, (a, b, s) in enumerate(timeline):
        if s == "recession":
            end = mnum(b) if b else mnum(today[:7])
            false_months += sum(1 for x in range(mnum(a), end) if x not in near)
    durations = {}
    for a, b, s in timeline:
        durations.setdefault(ZH[s], []).append(mnum(b or today[:7]) - mnum(a))
    return {"rows": rows, "false": false, "false_months": false_months,
            "caught": sum(1 for r in rows if r["enter"]), "recovered": sum(1 for r in rows if r["recover"]),
            "avg_months": {k: round(sum(v) / len(v), 1) for k, v in durations.items()},
            "stages": len(timeline)}


def _ym(n):
    return None if n is None else f"{n // 12:04d}-{n % 12 + 1:02d}"


def criteria_stats(crits: list[Crit], turns: list[dict], today: str) -> list[dict]:
    months = month_range("1985-01", today[:7])
    out = []
    for c in crits:
        if c.group in ("recovery", "bottom"):
            refs, (lo, hi), kind = [t["trough"] for t in turns], WIN_TROUGH, "谷底"
        elif c.group in ("top", "recession"):
            refs, (lo, hi), kind = [t["peak"] for t in turns], WIN_PEAK, "衰退開始"
        else:
            refs, kind = [], "擴張期"
        vals = {m: c.at(m)[0] for m in months}
        met = [m for m, v in vals.items() if v]
        avail = [m for m, v in vals.items() if v is not None]
        row = {"key": c.key, "no": c.no, "group": c.group, "label": c.label, "ref": kind,
               "met_months": len(met), "avail_months": len(avail), "timing": []}
        if refs:
            inwin = set()
            for r in refs:
                R = mnum(r)
                hit = next((mnum(m) for m in met if lo <= mnum(m) - R <= hi), None)
                row["timing"].append(None if hit is None else hit - R)
                inwin |= set(range(R + lo, R + hi + 1))
            outside = sum(1 for m in met if mnum(m) not in inwin)
            row["false_ratio"] = round(outside / len(met) * 100) if met else None
        else:
            rec = set()
            for t in turns:
                rec |= set(range(mnum(t["peak"]), mnum(t["trough"]) + 1))
            exp = [m for m in avail if mnum(m) not in rec]
            row["expansion_ratio"] = round(sum(1 for m in met if mnum(m) not in rec) / len(exp) * 100) if exp else None
        out.append(row)
    return out


def run_backtest(cfg: dict, today: str, current: dict | None = None) -> dict:
    turns = nber_turns(cfg["settings"]["backtest_start"])
    cur = current or run_stage(cfg, today)
    crits = cur.get("_crits")
    base = run_stage(spec_rules(cfg), today)
    if crits is None:
        crits = base["_crits"]
    res = {
        "turns": turns,
        "current": evaluate(cur["timeline"], turns, today),
        "spec": evaluate(base["timeline"], turns, today) | {"timeline": [[a, b, ZH[s]] for a, b, s in base["timeline"]]},
        "criteria": criteria_stats(crits, turns, today),
        "u_shape": cur.get("_extra", {}).get("u_shape", {}).get("events", []),
        "second_surge": cur.get("_extra", {}).get("second_surge", {}).get("episodes", []),
        "drops": cur.get("_extra", {}).get("drops", {}).get("events", []),
    }
    return res


# ── 報告 ────────────────────────────────────────────────
def _cell(d, v):
    return "—（沒抓到）" if d is None else f"{d}（{v:+d} 個月）"


def write_report(bt: dict, cfg: dict, now: str, timeline: list) -> None:
    c, s = bt["current"], bt["spec"]
    r = cfg["stage_rules"]
    L = [
        "# 回測報告（自動產生）", "",
        f"> 產生時間：{now}（台灣時間）｜回測期間：1985-01 至今｜對照：NBER 衰退期間（FRED `USREC`，https://fred.stlouisfed.org/series/USREC）",
        "> ⚠️ 使用修正後的資料（不是當時公布的初值），已依 config.yaml `release_lag` 粗略考慮發布延遲；只有 4 次衰退，參數容易過度貼合歷史。", "",
        "## 結論", "",
        f"- 目前設定：抓到 {c['caught']}/{len(bt['turns'])} 次衰退、{c['recovered']}/{len(bt['turns'])} 次復甦；"
        f"誤判衰退 {len(c['false'])} 次（{'、'.join(c['false']) or '無'}），共 {c['false_months']} 個月",
        f"- 需求文件原始規則：抓到 {s['caught']}/{len(bt['turns'])} 次衰退、{s['recovered']}/{len(bt['turns'])} 次復甦；"
        f"誤判衰退 {len(s['false'])} 次，共 {s['false_months']} 個月", "",
        "## 1. 階段判定 vs NBER", "",
        "提前為負、落後為正。「進入衰退」對照 NBER 衰退開始月；「進入復甦」對照 NBER 谷底月。", "",
        "| NBER 衰退 | 目前設定：進入衰退 | 進入復甦 | 原始規則：進入衰退 | 進入復甦 |", "|---|---|---|---|---|",
    ]
    for a, b in zip(c["rows"], s["rows"]):
        L.append(f"| {a['peak']} – {a['trough']} | {_cell(a['enter'], a['enter_lag'])} | {_cell(a['recover'], a['recover_lag'])} | "
                 f"{_cell(b['enter'], b['enter_lag'])} | {_cell(b['recover'], b['recover_lag'])} |")
    L += ["", "各階段平均持續月數（目前設定）：" + "、".join(f"{k} {v}" for k, v in c["avg_months"].items()), "",
          "### 目前設定的階段時間軸", "", "| 期間 | 階段 |", "|---|---|"]
    L += [f"| {a} – {b or '至今'} | {ZH[st]} |" for a, b, st in timeline]
    L += ["", "### 原始規則的階段時間軸", "", "| 期間 | 階段 |", "|---|---|"]
    L += [f"| {a} – {b or '至今'} | {st} |" for a, b, st in s["timeline"]]
    L += ["", "## 2. 每一項判斷依據的提前／落後", "",
          "第一次成立的月份 − NBER 轉折月（觸頂、確立衰退看衰退開始，窗口 −24～+6 個月；復甦、落底看谷底，窗口 −12～+18 個月）。",
          "「窗口外比例」＝成立的月份中，落在所有轉折窗口之外的比例，愈高代表誤判愈多。成長、榮景類沒有官方日期可對照，改列「擴張期成立比例」。", "",
          "| 依據 | 對照 | " + " | ".join(t["peak"][:4] for t in bt["turns"]) + " | 成立月數 | 窗口外比例／擴張期成立比例 |",
          "|---|---|" + "---|" * len(bt["turns"]) + "---|---|"]
    for x in bt["criteria"]:
        tm = " | ".join("—" if v is None else f"{v:+d}" for v in x["timing"]) if x["timing"] else " | ".join("" for _ in bt["turns"])
        ratio = f"{x['false_ratio']}%" if x.get("false_ratio") is not None else \
            f"擴張期 {x['expansion_ratio']}%" if x.get("expansion_ratio") is not None else "—"
        L.append(f"| {x['no']} {x['label']} | {x['ref']} | {tm} | {x['met_months']} | {ratio} |")
    L += ["", "## 3. 特殊型態（請檢查是否合理）", "", "**初領失業救濟金 U 型結構確立（觸頂依據 3）**", ""]
    L += [f"- 本輪低點 {e['low_date']}（{e['low']:,.0f} 人）→ {e['confirm_date']} 確立" for e in bt["u_shape"] if e["confirm_date"] >= "1985"] or ["- 無"]
    L += ["", "**耐久財訂單（不含運輸）二度衝高（觸頂依據 8）**", ""]
    L += [f"- 第一波 {e['wave1'][:7]}" + (f" → 第二波 {e['wave2'][:7]}" if e["wave2"] else "（沒有第二波）") for e in bt["second_surge"]] or ["- 無"]
    L += ["", "**2 次消費陡降（衰退 A1）**", ""]
    L += [f"- 頂點 {e['peak_date'][:7]}（{e['peak']:.1f}%）→ 第 1 次陡降 {e['first_drop'][:7]}（{e['low']:.1f}%）→ "
          + (f"第 2 次 {e['second'][:7]}" if e.get("second") else f"解除 {e['cleared'][:7]}" if e.get("cleared") else "觀察中")
          for e in bt["drops"] if e["first_drop"] >= "1984"]
    L += ["", "## 4. 第 5 階段的參數調整（已寫入 config.yaml，可改回原始規則）", "",
          f"1. **確立衰退需要佐證**（`stage_rules.recession.rule: {r.get('recession', {}).get('rule')}`）：原始規則 A1 一成立就進入衰退期，但 A1 在沒有衰退的年份也多次成立（見第 3 節）。"
          "改為「A1＋近 6 個月 A2 或 U 型結構確立」或「A2＋U 型結構確立」，而且近 12 個月觸頂 10 項中 ≥ 60% 曾成立。",
          f"2. **近 {r.get('memory_months', 1)} 個月內曾成立就計入**（`memory_months`）：各項依據很少在同一個月同時成立，原始規則下「進入復甦期」1985 年以來幾乎不曾確認。",
          f"3. **每個階段至少停留 {r.get('min_stage_months', 0)} 個月**（`min_stage_months`）：避免一個月內連跳好幾個階段（「確立衰退」不受限制）。",
          f"4. **轉入門檻**（`enter_levels`）：{', '.join(f'{ZH[k]} {v:.0%}' for k, v in r.get('enter_levels', {}).items())}。",
          "5. **2 次消費陡降**（`drop_min_pp`、`drop_tolerance_pp`）：依使用者圖二，第 1 次陡降容許單季持平或小幅反彈。",
          "6. **資料發布延遲**（`release_lag`）：月資料延後 1 個月、季資料延後 1 個月、違約率延後 2 個月才計入，避免回測用到當時還沒公布的資料。",
          f"7. **金融情勢轉緊可佐證衰退**（2026-11 加入，`stage_rules.recession.fin: {r.get('recession', {}).get('fin')}`）：A3 金融情勢指數 NFCI ≥ "
          f"{cfg['params'].get('nfci_min', 0)} 時，可作為 A1、A2 的佐證，也可取代「觸頂訊號 ≥ 60%」門檻。"
          "加入前 2008 年進入衰退落後 11 個月（卡在觸頂訊號只有 5/10）、2020 年落後 4 個月；加入後分別為 3 個月、0 個月，其他衰退與誤判不變。"
          "注意：NFCI 的歷史數值每週都會重新估計，回測用的是修正後數值。", "",
          "## 5. 仍待改善（依本次回測結果自動列出）", ""]
    issues = [f"- {d} 誤判進入衰退期" for d in c["false"]]
    issues += [f"- {x['peak']} 的衰退，進入衰退期落後 {x['enter_lag']} 個月" for x in c["rows"] if x["enter_lag"] and x["enter_lag"] > 6]
    issues += [f"- {x['peak']} 的衰退沒有抓到" for x in c["rows"] if x["enter"] is None]
    issues += [f"- {x['trough']} 的谷底，進入復甦期落後 {x['recover_lag']} 個月" for x in c["rows"] if x["recover_lag"] and x["recover_lag"] > 12]
    L += issues or ["- 無"]
    L += ["- 只有 4 次衰退可供驗證，任何參數都可能只是貼合歷史；建議把結果當作參考，搭配人工判斷。"]
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "回測報告.md").write_text("\n".join(L) + "\n", encoding="utf-8")
