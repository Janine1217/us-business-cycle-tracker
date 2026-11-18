"""股市多轉空風險分數：用領先型金融指標估計 S&P 500 未來出現大跌的風險。

和景氣四階段分開計算，不影響階段判定。設定在 config.yaml 的 market_risk。
- 每月逐項判斷條件是否成立（只用當時已公布的資料：月資料延後 1 個月，市場與週資料不延後）
- 分數＝成立的權重 ÷ 有資料的權重 × 100，再取 smooth_months 個月平均
- S&P 500 已從高點跌 ≥ bear_gate% 時，視為「空頭進行中」，不再發出多轉空警示
- 回測：對照之後 forward_months 個月內是否下跌 ≥ forward_drop%，以及各次空頭（≥ 15%）的提前月數
"""
from __future__ import annotations

from . import charts, transform as tf
from .criteria import month_range, mnum, shift

LEVEL_ZH = {"watch": "🟡 觀察", "warn": "🟠 警示", "confirm": "🔴 確認"}
TYPE_ZH = {"lead": "領先型", "confirm": "確認型"}


def _mo(rows) -> dict[str, float]:
    return {d[:7]: v for d, v in rows}


class Series:
    """月資料＋發布延遲：at(m) 取 m 當時已公布的最新值（超過 max_age 個月沒更新視為缺漏）。"""

    def __init__(self, rows, lag: int, max_age: int):
        self.d = _mo(rows)
        self.keys = sorted(self.d)
        self.lag, self.max_age = lag, max_age

    def at(self, m: str):
        cut = shift(m, -self.lag)
        for k in range(self.max_age + 1):
            x = shift(cut, -k)
            if x in self.d:
                return x, self.d[x]
        return None, None

    def win(self, m: str, n: int) -> list[float]:
        cut = shift(m, -self.lag)
        return [self.d[shift(cut, -k)] for k in range(n) if shift(cut, -k) in self.d]


def _data(max_age: int) -> dict[str, Series]:
    S, M = charts.S, charts.M
    sp = tf.extend(S("SHILLER_SP500"), M("SP500"))
    return {
        "yc": Series(M("T10Y3M"), 0, max_age),
        "fed": Series(tf.splice(M("DFEDTAR", "last"), M("DFEDTARU", "last"), "2008-12-01"), 0, max_age),
        "baa": Series(M("BAA10Y"), 0, max_age),
        "nfci": Series(M("NFCI"), 0, max_age),
        "wti": Series(tf.splice(S("WTISPLC"), M("DCOILWTICO"), "1986-01-01"), 0, max_age),
        "claims": Series(M("IC4WSA"), 0, max_age),
        "sahm": Series(S("SAHMREALTIME"), 1, max_age),
        "sp": Series(sp, 0, max_age),
        "um": Series(tf.ma(S("UMCSENT"), 3), 1, max_age),
    }


def _f(v, unit=""):
    return "—" if v is None else f"{v:,.2f}{unit}"


def _component(key: str, p: dict, D: dict, m: str) -> dict:
    """回傳 {met: True/False/None, value: 說明數值, rule: 條件說明}。"""
    if key == "yc_inverted":
        w = D["yc"].win(m, p["months"])
        _, v = D["yc"].at(m)
        return {"name": "殖利率曲線倒掛", "rule": f"10 年期減 3 個月期利差近 {p['months']} 個月內曾 < 0",
                "met": None if not w else min(w) < 0, "value": f"目前 {_f(v, ' 百分點')}；近 {p['months']} 個月最低 {_f(min(w) if w else None, ' 百分點')}"}
    if key == "yc_resteep":
        w, lw = D["yc"].win(m, p["months"]), D["yc"].win(m, p["low_months"])
        _, v = D["yc"].at(m)
        met = None if v is None or not lw else (min(w) < 0 and v - min(lw) >= p["rise"])
        return {"name": "倒掛後轉陡", "rule": f"近 {p['months']} 個月曾倒掛，且利差比近 {p['low_months']} 個月低點回升 ≥ {p['rise']} 個百分點",
                "met": met, "value": f"目前 {_f(v, ' 百分點')}；近 {p['low_months']} 個月低點 {_f(min(lw) if lw else None, ' 百分點')}"}
    if key == "first_cut":
        w, r = D["fed"].win(m, p["months"]), D["fed"].win(m, p["recent"])
        _, v = D["fed"].at(m)
        met = None if v is None or not w else (max(w) - min(w) >= p["hike"] and v < max(r) and max(w) - v < p["max_cut"])
        return {"name": "升息後開始降息", "rule": f"近 {p['months']} 個月升息 ≥ {p['hike']} 個百分點後，近 {p['recent']} 個月開始降息（累計降幅 < {p['max_cut']}）",
                "met": met, "value": f"目標利率 {_f(v, '%')}；近 {p['months']} 個月高點 {_f(max(w) if w else None, '%')}"}
    if key == "credit":
        w = D["baa"].win(m, p["months"])
        _, v = D["baa"].at(m)
        return {"name": "信用利差擴大", "rule": f"Baa 公司債利差比近 {p['months']} 個月低點擴大 ≥ {p['rise']} 個百分點",
                "met": None if v is None or not w else v - min(w) >= p["rise"], "value": f"目前 {_f(v, ' 百分點')}；低點 {_f(min(w) if w else None, ' 百分點')}"}
    if key == "nfci":
        w = D["nfci"].win(m, p["months"])
        _, v = D["nfci"].at(m)
        return {"name": "金融情勢轉緊", "rule": f"芝加哥聯準銀行金融情勢指數比近 {p['months']} 個月低點上升 ≥ {p['rise']}",
                "met": None if v is None or not w else v - min(w) >= p["rise"], "value": f"目前 {_f(v)}；低點 {_f(min(w) if w else None)}"}
    if key == "oil":
        d, v = D["wti"].at(m)
        _, v0 = D["wti"].at(shift(m, -12)) if d else (None, None)
        yoy = (v / v0 - 1) * 100 if v and v0 else None
        return {"name": "油價急漲", "rule": f"WTI 油價年增率 ≥ {p['yoy']}%", "met": None if yoy is None else yoy >= p["yoy"],
                "value": f"年增率 {_f(yoy, '%')}"}
    if key == "claims":
        w = D["claims"].win(m, p["months"])
        _, v = D["claims"].at(m)
        rise = (v / min(w) - 1) * 100 if v and w else None
        return {"name": "初領失業救濟金回升", "rule": f"4 週平均比近 {p['months']} 個月低點上升 ≥ {p['rise_pct']}%",
                "met": None if rise is None else rise >= p["rise_pct"], "value": f"比低點 {_f(rise, '%')}"}
    if key == "sahm":
        d, v = D["sahm"].at(m)
        return {"name": "薩姆規則升溫", "rule": f"即時薩姆規則指標 ≥ {p['min']}（≥ 0.5 通常代表衰退已開始）",
                "met": None if v is None else v >= p["min"], "value": f"{_f(v, ' 百分點')}（{d or '—'}）"}
    if key == "trend":
        w = D["sp"].win(m, p["ma_months"])
        _, v = D["sp"].at(m)
        ma = sum(w) / len(w) if len(w) == p["ma_months"] else None
        return {"name": "S&P 500 跌破長期均線", "rule": f"S&P 500 月平均 < {p['ma_months']} 個月移動平均",
                "met": None if v is None or ma is None else v < ma, "value": f"{_f(v)}；均線 {_f(ma)}"}
    if key == "sentiment":
        w = D["um"].win(m, p["months"])
        d, v = D["um"].at(m)
        drop = (v / max(w) - 1) * 100 if v and w else None
        return {"name": "消費者信心急降", "rule": f"密西根信心指數（3 個月平均）比近 {p['months']} 個月高點低 ≥ {p['drop_pct']}%",
                "met": None if drop is None else drop <= -p["drop_pct"], "value": f"比高點 {_f(drop, '%')}（{d or '—'}）"}
    raise KeyError(f"未知的風險條件：{key}")


def _level(score: float | None, lv: dict) -> str | None:
    if score is None:
        return None
    for k in ("confirm", "warn", "watch"):
        if score >= lv[k] - 1e-9:
            return k
    return None


def run_market_risk(cfg: dict, today: str) -> dict:
    R = cfg["market_risk"]
    D = _data(R["max_age_months"])
    months = month_range(cfg["settings"]["backtest_start"][:7], today[:7])
    sp = D["sp"].d
    hist, raw, peak = [], [], float("-inf")
    for i, m in enumerate(months):
        comps = [_component(c["key"], c, D, m) | {"key": c["key"], "type": c["type"], "weight": c["weight"]}
                 for c in R["components"]]
        avail = sum(c["weight"] for c in comps if c["met"] is not None)
        got = sum(c["weight"] for c in comps if c["met"])
        raw.append(got / avail * 100 if avail else None)
        w = [x for x in raw[-R["smooth_months"]:] if x is not None]
        score = sum(w) / len(w) if w else None
        _, v = D["sp"].at(m)
        if v is not None:
            peak = max(peak, v)
        dd = (v / peak - 1) * 100 if v is not None else None
        bear = dd is not None and dd <= -R["bear_gate"]
        hist.append({"m": m, "raw": raw[-1], "score": score, "dd": dd, "bear": bear,
                     "level": None if bear else _level(score, R["levels"]), "comps": comps})
    cur = hist[-1]
    return {"hist": hist, "current": cur, "levels": R["levels"], "sp": sp, "months": months}


# ── 回測 ───────────────────────────────────────────────
def backtest(res: dict, cfg: dict) -> dict:
    R = cfg["market_risk"]
    n, drop = R["forward_months"], R["forward_drop"]
    hist, sp = res["hist"], res["sp"]
    months = [h["m"] for h in hist]
    spv = [sp.get(m) for m in months]
    fwd = []
    for i in range(len(months)):
        nxt = [x for x in spv[i + 1:i + 1 + n] if x is not None]
        fwd.append((min(nxt) / spv[i] - 1) * 100 if spv[i] and len(nxt) == n else None)
    ok = [i for i in range(len(months)) if fwd[i] is not None and hist[i]["score"] is not None and not hist[i]["bear"]]
    base = sum(fwd[i] <= -drop for i in ok) / len(ok) * 100 if ok else None
    lv = R["levels"]
    buckets = []
    edges = [0, lv["watch"], lv["warn"], lv["confirm"], 101]
    names = ["低", LEVEL_ZH["watch"], LEVEL_ZH["warn"], LEVEL_ZH["confirm"]]
    for (lo, hi), name in zip(zip(edges, edges[1:]), names):
        ix = [i for i in ok if lo <= hist[i]["score"] < hi]
        rets = sorted((spv[i + 12] / spv[i] - 1) * 100 for i in ix if i + 12 < len(spv) and spv[i + 12])
        buckets.append({"name": name, "range": f"{lo}–{min(hi, 100)}", "months": len(ix),
                        "hit": round(sum(fwd[i] <= -drop for i in ix) / len(ix) * 100) if ix else None,
                        "ret12": round(rets[len(rets) // 2], 1) if rets else None})
    bears = [{"peak": b["peak"][:7], "trough": b["trough"][:7], "depth": round(b["depth"])}
             for b in charts.bear_markets([(m + "-01", v) for m, v in zip(months, spv) if v], drop)]
    # 每次空頭：高點前 12 個月到後 6 個月內，第一次達到各等級的月份
    for b in bears:
        for k in ("watch", "warn", "confirm"):
            f = next((h["m"] for h in hist if -12 <= mnum(h["m"]) - mnum(b["peak"]) <= 6
                      and h["score"] is not None and h["score"] >= lv[k] and not h["bear"]), None)
            b[k] = f
            b[k + "_lead"] = mnum(f) - mnum(b["peak"]) if f else None
    # 警示區段（達到 🟠 警示）：開始前 2 個月到開始後 12 個月內有 ≥ drop% 空頭的高點、或開始時仍在下跌途中 → 命中
    # （在空頭低點之後才亮的警示算誤報：對投資人而言是錯過反彈）
    eps, cur = [], None
    for h in hist:
        on = h["score"] is not None and h["score"] >= lv["warn"] and not h["bear"]
        if on:
            cur = cur or {"start": h["m"], "end": h["m"], "max": 0}
            cur["end"] = h["m"]
            cur["max"] = max(cur["max"], round(h["score"]))
        elif cur:
            eps.append(cur)
            cur = None
    if cur:
        eps.append(cur)
    for e in eps:
        s = mnum(e["start"])
        e["hit"] = any(-2 <= mnum(b["peak"]) - s <= n or mnum(b["peak"]) <= s <= mnum(b["trough"]) for b in bears)
        if not e["hit"] and s + n > mnum(months[-1]):
            e["hit"] = None  # 太近，還無法判斷
    return {"base": round(base) if base is not None else None, "buckets": buckets, "bears": bears, "episodes": eps,
            "forward_months": n, "forward_drop": drop}


def summary(res: dict, bt: dict, cfg: dict) -> dict:
    """給儀表板與 Email 用的精簡資料。"""
    cur = res["current"]
    R = cfg["market_risk"]
    return {
        "asof": cur["m"], "score": round(cur["score"]) if cur["score"] is not None else None,
        "raw": round(cur["raw"]) if cur["raw"] is not None else None,
        "level": cur["level"], "level_zh": LEVEL_ZH.get(cur["level"]), "bear": cur["bear"],
        "dd": round(cur["dd"], 1) if cur["dd"] is not None else None,
        "levels": R["levels"], "smooth": R["smooth_months"], "bear_gate": R["bear_gate"],
        "components": [{k: c[k] for k in ("key", "name", "rule", "met", "value", "type", "weight")} | {"type_zh": TYPE_ZH[c["type"]]}
                       for c in cur["comps"]],
        "history": {"x": [h["m"] + "-01" for h in res["hist"]],
                    "score": [round(h["score"], 1) if h["score"] is not None else None for h in res["hist"]]},
        "backtest": bt,
    }


def write_report(sm: dict, cfg: dict, now: str) -> None:
    from .settings import DOCS_DIR
    bt = sm["backtest"]
    L = ["# 股市多轉空風險分數：回測報告（自動產生）", "",
         f"> 產生時間：{now}（台灣時間）｜回測期間：{cfg['settings']['backtest_start'][:7]} 至今｜"
         "S&P 500：席勒月資料（月平均），最新月份以 FRED `SP500` 補上  ",
         "> ⚠️ 使用修正後資料；1985 年以來只有 5 次 ≥ 15% 的空頭（月平均），參數容易過度貼合歷史。僅供參考，非投資建議。", "",
         "## 結論", "",
         f"- 目前分數 **{sm['score']}**（{sm['asof']}，{sm['level_zh'] or '低'}；{sm['smooth']} 個月平均）",
         f"- 基準：任一月份之後 {bt['forward_months']} 個月內 S&P 500 跌 ≥ {bt['forward_drop']}% 的比例為 {bt['base']}%",
         "- 分數愈高，之後大跌的比例愈高；但多數在股市高點前後 0–3 個月才升高，屬於「早期確認」而非「提前半年預告」。", "",
         "## 1. 分數區間 vs 之後的表現", "",
         f"| 等級 | 分數 | 月數 | {bt['forward_months']} 個月內跌 ≥ {bt['forward_drop']}% | 之後 12 個月報酬中位數 |", "|---|---|---|---|---|"]
    for b in bt["buckets"]:
        L.append(f"| {b['name']} | {b['range']} | {b['months']} | {'—' if b['hit'] is None else str(b['hit']) + '%'} | {'—' if b['ret12'] is None else str(b['ret12']) + '%'} |")
    L += ["", "## 2. 各次空頭：高點前 12 個月到後 6 個月內，第一次達到各等級的時間（負數＝提前）", "",
          "| S&P 500 高點 → 低點 | 跌幅 | 🟡 觀察 | 🟠 警示 | 🔴 確認 |", "|---|---|---|---|---|"]
    cell = lambda d, v: "沒有" if not d else f"{d}（{v:+d}）"  # noqa: E731
    for b in bt["bears"]:
        L.append(f"| {b['peak']} → {b['trough']} | {b['depth']}% | {cell(b['watch'], b['watch_lead'])} | {cell(b['warn'], b['warn_lead'])} | {cell(b['confirm'], b['confirm_lead'])} |")
    L += ["", f"## 3. 🟠 警示區段（命中＝開始前 2 個月到之後 {bt['forward_months']} 個月內有 ≥ {bt['forward_drop']}% 空頭的高點，或開始時仍在下跌途中）", "",
          "| 期間 | 最高分 | 結果 |", "|---|---|---|"]
    for e in bt["episodes"]:
        L.append(f"| {e['start']} – {e['end']} | {e['max']} | {'✓ 命中' if e['hit'] else '— 尚無法判斷' if e['hit'] is None else '✕ 誤報'} |")
    L += ["", "## 4. 目前各條件", "", "| 類型 | 條件 | 成立 | 數值 |", "|---|---|---|---|"]
    for c in sm["components"]:
        L.append(f"| {c['type_zh']} | {c['name']}：{c['rule']} | {'—' if c['met'] is None else '✓' if c['met'] else '✕'} | {c['value']} |")
    L += ["", "資料來源：FRED `T10Y3M`、`DFEDTARU`/`DFEDTAR`、`BAA10Y`、`NFCI`、`DCOILWTICO`、`IC4WSA`、`SAHMREALTIME`、`UMCSENT`、`SP500`；Robert Shiller 美股資料。", ""]
    (DOCS_DIR / "股市風險回測.md").write_text("\n".join(L), encoding="utf-8")


def signal(res: dict) -> dict | None:
    """目前等級 ≥ 🟡 觀察時，回傳要放進轉折訊號的資料（record_live 會比對變化、寄 Email）。"""
    hist = res["hist"]
    cur = hist[-1]
    if not cur["level"]:
        return None
    since = cur["m"]
    for h in reversed(hist):
        if not h["level"]:
            break
        since = h["m"]
    met = [c for c in cur["comps"] if c["met"]]
    return {"key": "market_risk", "name": "股市多轉空風險升高", "level": cur["level"], "level_zh": LEVEL_ZH[cur["level"]],
            "since": since, "met": len(met), "avail": sum(1 for c in cur["comps"] if c["met"] is not None),
            "met_labels": [c["name"] for c in met]}


def chart(sm: dict, sp_rows: list) -> dict:
    """趨勢圖 #R：風險分數 vs S&P 500。"""
    lv = sm["levels"]
    rows = [(x, v) for x, v in zip(sm["history"]["x"], sm["history"]["score"]) if v is not None]
    return {"id": "R", "title": "股市多轉空風險分數 vs S&P 500", "stages_zh": ["額外參考"], "toggle": True, "no_table": True,
            "sources": ["T10Y3M", "BAA10Y", "NFCI", "IC4WSA", "SAHMREALTIME", "SHILLER_SP500"],
            "notes": [f"分數為 {sm['smooth']} 個月平均；S&P 500 從高點跌 ≥ {sm['bear_gate']}% 時視為空頭進行中，不發警示",
                      "水平線為 🟡 觀察、🟠 警示、🔴 確認門檻（config.yaml 的 market_risk.levels）",
                      "回測結果見「回測」分頁與 docs/股市風險回測.md"],
            "views": [charts.V("分數", [charts.T("風險分數", rows, "分", "pt"),
                                      charts.T("S&P 500", sp_rows, "點", "pct", axis="y2", dash=True)],
                               "風險分數（0–100）", "S&P 500",
                               hlines=[{"y": lv["watch"], "label": "觀察"}, {"y": lv["warn"], "label": "警示"},
                                       {"y": lv["confirm"], "label": "確認"}])]}
