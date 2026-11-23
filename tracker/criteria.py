"""各階段判斷依據（需求文件第 3 節）：逐月計算每一項是否成立。

做法：
- 判斷日曆以「月」為單位，從 1985-01 到本月。
- 每個月只看「觀察期間 ≤ 該月」的資料（季資料以季末月份計，例如第 3 季記在 9 月）。
  ⚠️ 尚未考慮發布延遲與資料修正（例如 GDP 要到季後約 1 個月才公布），回測會略為提前，階段 5 再處理。
- 資料缺漏（尚未開始提供、或超過 max_age 個月沒更新）的項目，成立狀態為 None，從分母扣除。
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from . import charts, store
from . import transform as tf
from . import trend as tr

Rows = list[tuple[str, float]]
Cell = tuple[bool | None, bool]          # (成立, 接近)

_cache: dict[str, Rows] = {}


def S(sid: str) -> Rows:
    if sid not in _cache:
        _cache[sid] = store.read_series(sid)
    return _cache[sid]


def M(sid: str, how: str = "mean") -> Rows:
    return tf.to_monthly(S(sid), how)


def mkey(d: str, freq: str) -> str:
    """觀察日期 → 可使用的月份（YYYY-MM）。季資料移到季末月份。"""
    if freq == "Q":
        y, m = int(d[:4]), int(d[5:7]) + 2
        return f"{y:04d}-{m:02d}"
    return d[:7]


def mnum(k: str) -> int:
    return int(k[:4]) * 12 + int(k[5:7]) - 1


def shift(k: str, n: int) -> str:
    if not n:
        return k
    x = mnum(k) + n
    return f"{x // 12:04d}-{x % 12 + 1:02d}"


def months_between(a: str, b: str) -> int:
    """b − a（月數），a、b 為 YYYY-MM 或 YYYY-MM-DD。"""
    return mnum(b[:7]) - mnum(a[:7])


def month_range(start: str, end: str) -> list[str]:
    out, n = [], mnum(start)
    while n <= mnum(end):
        out.append(f"{n // 12:04d}-{n % 12 + 1:02d}")
        n += 1
    return out


def fmt(v: float | None, unit: str = "") -> str:
    if v is None:
        return "—"
    a = abs(v)
    s = f"{v:,.0f}" if a >= 1000 else f"{v:.2f}"
    return f"{s}{unit}"


def yq(d: str) -> str:
    return f"{d[:4]} 年第 {(int(d[5:7]) - 1) // 3 + 1} 季"


# ── 元件：一條數列＋一個判斷 ─────────────────────────────
@dataclass
class Comp:
    label: str                       # 例如「10 年期公債殖利率」
    rule: str                        # 例如「T1 下滑」
    freq: str                        # 日曆對齊用：W、M、Q
    flags: list                      # [(日期, 成立, 接近)]
    value: Rows                      # 顯示用的數值（判斷用的平滑後數值）
    unit: str = ""
    max_age: int = 6
    lag: int = 0                     # 發布延遲（月）：觀察期間結束後幾個月才能取得

    def __post_init__(self):
        self._keys = [shift(mkey(d, self.freq), self.lag) for d, _, _ in self.flags]
        self._vkeys = [shift(mkey(d, self.freq), self.lag) for d, _ in self.value]

    def at(self, m: str) -> Cell:
        i = bisect.bisect_right(self._keys, m) - 1
        if i < 0 or months_between(self._keys[i], m) > self.max_age:
            return (None, False)
        _, met, near = self.flags[i]
        return (met, near)

    def latest_value(self, m: str):
        i = bisect.bisect_right(self._vkeys, m) - 1
        if i < 0:
            return None, None
        return self.value[i]

    def describe(self, m: str) -> dict:
        d, v = self.latest_value(m)
        met, near = self.at(m)
        return {"label": self.label, "rule": self.rule, "value": fmt(v, self.unit),
                "date": d, "met": met, "near": near}


def _lag(freq: str, lag, P: dict) -> int:
    return P["release_lag"].get(freq, 0) if lag is None else lag


def comp(label, rows: Rows, freq: str, unit_kind: str, rule: str, P: dict, unit: str = "", lag=None) -> Comp:
    """套用 T1–T6：rows 為判斷用的原始數值（月資料會先取 3 個月平均）。

    lag：發布延遲（月），None 時依頻率用 config.yaml 的 release_lag；市場價格類（利率、油價、股價）傳 0。
    """
    s = tr.smooth(rows, freq, P["trend"])
    flags = tr.RULES[rule](s, unit_kind, P["trend"])
    return Comp(label, f"{rule} {tr.RULE_ZH[rule]}", freq, flags, s, unit, P["trend"]["max_age"][freq], _lag(freq, lag, P))


def custom(label, rule_text, freq, flags, value, unit, P, lag=None) -> Comp:
    return Comp(label, rule_text, freq, flags, value, unit, P["trend"]["max_age"][freq], _lag(freq, lag, P))


# ── 判斷依據（一項＝多個元件的組合）──────────────────────
@dataclass
class Crit:
    key: str
    group: str
    no: str                          # 需求文件中的編號（1、E1、A1…）
    label: str
    indicators: list[str]
    method: str                      # 判斷方法說明
    comps: list[Comp]
    combine: str = "all"             # all：都要成立；any：任一成立；count:k：至少 k 項
    manual: bool = False             # 人工登記類
    extra: dict = field(default_factory=dict)

    def at(self, m: str) -> tuple[bool | None, bool, bool]:
        """回傳 (成立, 接近, 部分資料缺漏)。"""
        cells = [c.at(m) for c in self.comps]
        avail = [c for c in cells if c[0] is not None]
        partial = 0 < len(avail) < len(cells)
        if not avail:
            return None, False, False
        hits = sum(1 for c in avail if c[0])
        near_any = any(c[1] for c in avail)
        if self.combine == "any":
            met = hits > 0
            return met, (not met and near_any), partial
        if self.combine.startswith("count:"):
            k = int(self.combine[6:])
            if len(avail) < k:
                return None, False, partial
            met = hits >= k
            return met, (not met and (hits == k - 1 or near_any)), partial
        met = hits == len(avail)
        return met, (not met and (hits > 0 or near_any)), partial

    def describe(self, m: str) -> dict:
        met, near, partial = self.at(m)
        return {"key": self.key, "no": self.no, "label": self.label, "indicators": self.indicators,
                "method": self.method, "met": met, "near": near, "partial": partial, "manual": self.manual,
                "parts": [c.describe(m) for c in self.comps], **self.extra}


# ── 特殊判斷 ───────────────────────────────────────────
def fed_low(P: dict) -> tuple[Comp, dict]:
    """復甦期依據 1：聯邦基金利率在本輪降息循環的低點。"""
    p = P["params"]
    daily = [r for r in S("DFEDTAR") if r[0] < "2008-12-16"] + [r for r in S("DFEDTARU") if r[0] >= "2008-12-16"]
    events = []  # (日期, 舊, 新)
    for i in range(1, len(daily)):
        if abs(daily[i][1] - daily[i - 1][1]) > 1e-9:
            events.append((daily[i][0], daily[i - 1][1], daily[i][1]))
    flags, info_by_month = [], {}
    months = month_range(daily[0][0][:7], P["_today"][:7])
    j = 0
    for m in months:
        while j < len(events) and events[j][0][:7] <= m:
            j += 1
        past = events[:j]
        cur = daily[bisect.bisect_right([d for d, _ in daily], f"{m}-31") - 1][1]
        cuts = []
        for e in reversed(past):          # 從最近往回數連續降息
            if e[2] < e[1]:
                cuts.append(e)
            else:
                break
        if not cuts or (past and past[-1][2] > past[-1][1]):
            flags.append((f"{m}-01", False, False))
            info_by_month[m] = {"cur": cur, "cycle": False}
            continue
        peak = cuts[-1][1]
        total = peak - cur
        hold = months_between(cuts[0][0], m)
        a = total >= p["fed_cut_total_min"] - 1e-9 or len(cuts) >= p["fed_cut_count_min"]
        b = hold >= p["fed_hold_months"]
        flags.append((f"{m}-01", a and b, a and not b))
        info_by_month[m] = {"cur": cur, "cycle": True, "start": cuts[-1][0], "peak": peak,
                            "total": total, "count": len(cuts), "last_cut": cuts[0][0], "hold": hold}
    value = [(f"{m}-01", info_by_month[m]["cur"]) for m in months]
    c = custom("聯邦基金目標利率（上限）", "條件 A 降息循環＋條件 B 已到低點", "M", flags, value, "%", P, lag=0)
    return c, info_by_month


def u_shape(P: dict) -> tuple[Comp, dict]:
    """觸頂依據 3：初領失業救濟金 4 週平均的 U 型結構（週資料）。"""
    p = P["params"]
    s = S("IC4WSA")
    weeks_back = int(p["u_lookback_months"] * 52 / 12)
    flags, events, state = [], [], {}
    confirmed_low = None
    for i, (d, v) in enumerate(s):
        if i < weeks_back:
            flags.append((d, None, False)); continue
        win = s[i - weeks_back + 1:i + 1]
        lo_i = min(range(len(win)), key=lambda k: (win[k][1], -k))
        lo_d, lo_v = win[lo_i]
        since = months_between(lo_d, d)
        rising = all(s[i - k][1] > s[i - k - 1][1] for k in range(p["u_rising_weeks"]))
        new = since < p["u_no_new_low_months"]
        up = (v / lo_v - 1) * 100
        cond = since >= p["u_no_new_low_months"] and up >= p["u_rise_pct"] and rising
        if confirmed_low == lo_d:            # U 型確立後維持，直到出現新的本輪低點
            met = True
        elif cond:
            met = True
            confirmed_low = lo_d
            events.append({"low_date": lo_d, "low": lo_v, "confirm_date": d})
        else:
            met = False
            if confirmed_low and lo_d != confirmed_low:
                confirmed_low = None
        near = not met and since >= p["u_no_new_low_months"] and up >= p["u_rise_pct"] / 2
        flags.append((d, met, near))
        state = {"low_date": lo_d, "low": lo_v, "since_months": since, "up_pct": up, "rising": rising,
                 "extend": months_between(lo_d, d) < p["u_new_low_months"], "date": d, "value": v}
    if state.get("extend"):
        y, m = int(state["low_date"][:4]), int(state["low_date"][5:7]) + 3 * p["u_extend_quarters"]
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        state["extend_to"] = yq(f"{y:04d}-{m:02d}-01")
    c = custom("初領失業救濟金（4 週平均）", "U 型結構確立（3-2）", "W", flags, s, "人", P)
    return c, {"state": state, "events": events}


def extension_flags(P: dict) -> list:
    """3-1：最近 3 個月內創下本輪新低 → 榮景期延長（逐週）。"""
    p = P["params"]
    s = S("IC4WSA")
    weeks_back = int(p["u_lookback_months"] * 52 / 12)
    out = []
    for i, (d, v) in enumerate(s):
        if i < weeks_back:
            out.append((d, None, False)); continue
        win = s[i - weeks_back + 1:i + 1]
        lo_d = min(win, key=lambda r: r[1])[0]
        out.append((d, months_between(lo_d, d) < p["u_new_low_months"], False))
    return out


def second_surge(P: dict) -> tuple[Comp, dict]:
    """觸頂依據 8：耐久財訂單（不含運輸）二度衝高。"""
    p = P["params"]
    s = tf.ma(S("ADXTNO"), 3)
    n6, n3 = p["surge_months"], 3
    flags, episodes = [], []
    state, w1, flat_run, flat_ok, hold_until = "none", None, 0, False, -1
    for i, (d, v) in enumerate(s):
        if i < n6:
            flags.append((d, None, False)); continue
        g6 = (v / s[i - n6][1] - 1) * 100
        c3 = abs((v / s[i - n3][1] - 1) * 100)
        surge = g6 >= p["surge_pct"]
        flat = c3 <= p["flat_pct"]
        if state != "none" and i - w1 > p["second_surge_within"]:
            state = "none"
        if state == "none":
            if surge:
                state, w1, flat_run, flat_ok = "wave1", i, 0, False
                episodes.append({"wave1": d, "wave2": None})
        elif state == "wave1":
            flat_run = flat_run + 1 if flat else 0
            if flat_run >= p["flat_months"]:
                state = "flat"
        elif state == "flat":
            if surge:
                episodes[-1]["wave2"] = d
                hold_until = i + p["second_surge_hold"] - 1
                state = "done"
        elif state == "done" and not surge:
            state = "none"
        met = i <= hold_until
        flags.append((d, met, state == "flat"))
    c = custom("耐久財訂單（不含運輸，3 個月平均）", "二度衝高", "M", flags, s, "百萬美元", P)
    return c, {"episodes": episodes, "state": state}


def consumption_drops(P: dict) -> tuple[Comp, Comp, dict]:
    """衰退期 A1：實質個人消費支出（季）年增率的 2 次消費陡降。回傳 (A1 成立, 第 1 次陡降觀察中, 資訊)。

    依使用者提供的圖二（1980、1990、2001、2008 年）：
    - 第 1 次陡降：年增率從頂點轉折向下，4 季內累計下降 ≥ drop_min_pp；
      容許中間 1 季小幅持平或反彈（≤ drop_tolerance_pp），因為 1990、2008 年的第 1 次陡降都不是嚴格的連續下降
    - 第 1 次陡降的「最低點」固定為那 4 季結束時的數值；之後 4 季內跌破它，就是第 2 次陡降，A1 成立
      （2001 年在修正後的資料中兩次陡降連在一起，沒有停頓，也算數）
    - 之後回升 ≥ drop_clear_pp，或 4 季內都沒跌破，就解除觀察
    """
    p = P["params"]
    x = tf.yoy(S("PCECC96"))
    q, tol, mn = p["drop_quarters"], p["drop_tolerance_pp"], p["drop_min_pp"]
    a1, obs, events = [], [], []
    state, low, start_i, hold_until = "normal", None, None, -1
    for i, (d, v) in enumerate(x):
        if i < q + 1:
            a1.append((d, None, False)); obs.append((d, None, False)); continue
        if state == "watch":
            if v < low:
                hold_until = i + p["a1_hold_quarters"] - 1
                events[-1]["second"] = d
                state = "normal"
            elif v >= low + p["drop_clear_pp"] or i - start_i > p["second_drop_within"]:
                events[-1]["cleared"] = d
                state = "normal"
        elif i > hold_until:
            steps = [x[i - k][1] - x[i - k - 1][1] for k in range(q)]
            peak = x[i - q][1]
            if peak >= x[i - q - 1][1] and all(st <= tol for st in steps) and v <= peak - mn:
                state, low, start_i = "watch", v, i
                events.append({"first_drop": d, "peak_date": x[i - q][0], "peak": peak, "low": v, "second": None})
        a1.append((d, i <= hold_until, state == "watch"))
        obs.append((d, state == "watch", False))
    ca = custom("實質個人消費支出（季）年增率", "2 次消費陡降", "Q", a1, x, "%", P)
    co = custom("實質個人消費支出（季）年增率", "第 1 次消費陡降（觀察中）", "Q", obs, x, "%", P)
    return ca, co, {"events": events, "state": state}


def gt_for(rows: Rows, n: int, other: Rows) -> list:
    """rows > other 連續 ≥ n 期（兩者日期對齊）。"""
    od = dict(other)
    out, run = [], 0
    for d, v in rows:
        if d not in od:
            continue
        run = run + 1 if v > od[d] else 0
        out.append((d, run >= n, 0 < run < n))
    return out


def threshold_flags(rows: Rows, test, near=None) -> list:
    return [(d, bool(test(i, rows)), bool(near(i, rows)) if near else False) for i, (d, _) in enumerate(rows)]


def pctile_flags(rows: Rows, q: float, below: bool, P: dict) -> tuple[list, Rows]:
    pr = tr.t7_pctile(rows, P["settings"]["backtest_start"], P["params"]["pctile_min_years"],
                      P["params"].get("pctile_min_span", 0))
    out = []
    for d, v in pr:
        met = v <= q if below else v >= q
        near = (not met) and (v <= q + 10 if below else v >= q - 10)
        out.append((d, met, near))
    return out, pr


# ── 建立全部判斷依據 ─────────────────────────────────────
def build_criteria(cfg: dict, today: str) -> tuple[list[Crit], dict]:
    P = dict(cfg)
    P["_today"] = today
    p = cfg["params"]
    yoy = tf.yoy
    ma3 = lambda r: tf.ma(r, 3)  # noqa: E731

    wti = tf.splice(S("WTISPLC"), M("DCOILWTICO"), "1986-01-01")
    rrsfs_yoy = yoy(S("RRSFS"))
    retail_yoy = tf.splice(yoy(S("DGDSRA3M086SBEA")), rrsfs_yoy, rrsfs_yoy[0][0])
    sp500 = tf.extend(S("SHILLER_SP500"), M("SP500"))
    extra: dict = {}

    def C(label, rows, freq, kind, rule, unit="", lag=None):
        return comp(label, rows, freq, kind, rule, P, unit, lag)

    crits: list[Crit] = []
    add = crits.append

    # ── 3.1 復甦期（景氣落底的判斷依據）──
    fed, fed_info = fed_low(P)
    extra["fed"] = fed_info
    add(Crit("R1", "recovery", "1", "聯邦基金利率經過連續降息後，已降到低點", ["1"],
             f"條件 A：從上一輪升息高點累計降息 ≥ {p['fed_cut_total_min']:.2f} 個百分點或連續降息 ≥ {p['fed_cut_count_min']} 次；"
             f"條件 B：連續 ≥ {p['fed_hold_months']} 個月沒有再調降", [fed]))
    add(Crit("R2", "recovery", "2", "10 年期公債殖利率、30 年房貸平均利率下滑", ["2", "3"], "兩者都符合 T1「下滑」",
             [C("10 年期公債殖利率", M("DGS10"), "M", "pp", "T1", "%", lag=0),
              C("30 年房貸平均利率", M("MORTGAGE30US"), "M", "pp", "T1", "%", lag=0)]))
    add(Crit("R3", "recovery", "3", "油價及原物料價格處於谷底", ["4a", "4b"], "兩者都符合 T2「谷底」",
             [C("WTI 原油", wti, "M", "pct", "T2", " 美元", lag=0),
              C("PPI 全部商品", S("PPIACO"), "M", "pct", "T2")]))
    add(Crit("R4", "recovery", "4", "初領失業救濟金人數達到高峰", ["5"], "符合 T3「高峰」或 T5「高點反轉」",
             [C("初領失業救濟金（月平均）", M("IC4WSA"), "M", "pct", "T3", " 人", lag=0),
              C("初領失業救濟金（月平均）", M("IC4WSA"), "M", "pct", "T5", " 人", lag=0)], combine="any"))
    add(Crit("R5", "recovery", "5", "短期失業人數（< 5 週）從高點反轉", ["6"], "符合 T5「高點反轉」",
             [C("短期失業人數", S("UEMPLT5"), "M", "pct", "T5", " 千人")]))
    add(Crit("R6", "recovery", "6", "實質零售銷售年增率落底反彈", ["7"], "符合 T4「落底反彈」",
             [C("實質零售銷售年增率", retail_yoy, "M", "pp", "T4", "%")]))
    add(Crit("R7", "recovery", "7", "私人非住宅固定投資、耐久財新訂單回升", ["8", "9"], "兩者的年增率都符合 T4「落底反彈」",
             [C("私人非住宅固定投資年增率（季）", yoy(S("PNFI")), "Q", "pp", "T4", "%"),
              C("耐久財新訂單年增率", yoy(S("DGORDER")), "M", "pp", "T4", "%")]))
    imp_m = C("進口金額年增率（月）", yoy(S("BOPTIMP")), "M", "pp", "T4", "%")
    imp_q = C("進口金額年增率（季，1992 年以前）", yoy(S("IMPGS")), "Q", "pp", "T4", "%")
    imp_start = mkey(imp_m.flags[0][0], "M") if imp_m.flags else "9999-12"
    imp_q.flags = [f for f in imp_q.flags if mkey(f[0], "Q") < imp_start] or imp_q.flags[:0]
    imp_q.__post_init__()
    add(Crit("R8", "recovery", "8", "進口金額年增率回升", ["10"], "符合 T4「落底反彈」（1992 年以前用季資料）",
             [imp_m, imp_q], combine="any"))
    stim = sorted(s["date"] for s in cfg.get("stimulus", []))
    sflags = []
    for m in month_range("1975-01", today[:7]):
        recent = [d for d in stim if 0 <= months_between(d, m) < p["stimulus_months"]]
        sflags.append((f"{m}-01", bool(recent), False))
    add(Crit("R9", "recovery", "9", "政府推出各項刺激經濟措施", ["23"],
             f"人工登記：過去 {p['stimulus_months']} 個月內，config.yaml 有登記的刺激措施",
             [custom("config.yaml 登記的刺激措施", "人工登記", "M", sflags,
                     [(f"{m}-01", float(sum(1 for d in stim if 0 <= months_between(d, m) < p['stimulus_months'])))
                      for m in month_range("1975-01", today[:7])], " 筆", P, lag=0)], manual=True))

    # ── 3.2 成長期 ──
    add(Crit("G1", "growth", "1", "可支配所得增速 > 消費支出增速", ["11"],
             f"個人可支配所得年增率 > 個人消費支出年增率（3 個月平均），連續 ≥ {p['consecutive_months']} 個月",
             [custom("可支配所得 vs 消費支出年增率", "所得 > 消費", "M",
                     gt_for(ma3(yoy(S("DSPI"))), p["consecutive_months"], ma3(yoy(S("PCE")))),
                     ma3(yoy(S("DSPI"))), "%", P)]))
    add(Crit("G2", "growth", "2", "初領失業救濟金人數下滑", ["5"], "符合 T1「下滑」",
             [C("初領失業救濟金（月平均）", M("IC4WSA"), "M", "pct", "T1", " 人", lag=0)]))
    gmin = p["investment_growth_min"]

    def growth_inv(label, rows):
        t6 = dict((d, m) for d, m, _ in tr.t6_up(rows, "pp", P["trend"]))
        fl = []
        for i, (d, v) in enumerate(rows):
            keep = i > 0 and rows[i - 1][1] >= gmin
            met = v >= gmin and (bool(t6.get(d)) or keep)
            fl.append((d, met, (not met) and v >= gmin * 0.6))
        return custom(label, f"年增率 ≥ {gmin}%，且 T6 上揚或維持在 {gmin}% 以上", "Q", fl, rows, "%", P)
    add(Crit("G3", "growth", "3", "私人非住宅固定投資、房地產投資顯著成長", ["12"],
             f"兩者的年增率都 ≥ {gmin}%，且符合 T6「上揚」或連續 2 季維持在 {gmin}% 以上",
             [growth_inv("非住宅固定投資年增率", yoy(S("PNFI"))), growth_inv("住宅固定投資年增率", yoy(S("PRFI")))]))
    lo, hi = p["core_cpi_band"]
    core = yoy(S("CPILFESL"))

    def core_test(i, r):
        v = r[i][1]
        if not lo <= v <= hi or i < 12:
            return False
        return v > r[i - 12][1] or all(lo <= x <= hi for _, x in r[i - 12:i + 1])
    add(Crit("G4", "growth", "4", "通膨回升至可持續增長的水準", ["13"],
             f"核心 CPI 年增率介於 {lo}%–{hi}%，且比 12 個月前回升，或過去 12 個月都在區間內",
             [custom("核心 CPI 年增率", f"{lo}%–{hi}% 且回升或穩定", "M",
                     threshold_flags(core, core_test, lambda i, r: lo - 0.3 <= r[i][1] <= hi + 0.3 and not core_test(i, r)),
                     core, "%", P)]))

    # ── 3.3 A 進入榮景期 E1–E4 ──
    gdp = yoy(S("GDPC1"))
    e1a = custom("實質 GDP 年增率", f"≥ {p['gdp_growth_min']}% 且高於 4 季前", "Q",
                 threshold_flags(gdp, lambda i, r: i >= 4 and r[i][1] >= p["gdp_growth_min"] and r[i][1] > r[i - 4][1],
                                 lambda i, r: r[i][1] >= p["gdp_growth_min"] - 0.5),
                 gdp, "%", P)
    cf = S("CFNAIMA3")
    e1b = custom("CFNAI（3 個月平均）", f"連續 ≥ 3 個月 ≥ +{p['cfnai_min']}", "M",
                 threshold_flags(cf, lambda i, r: i >= 2 and all(r[i - k][1] >= p["cfnai_min"] for k in range(3)),
                                 lambda i, r: r[i][1] >= p["cfnai_min"]),
                 cf, "", P)
    add(Crit("E1", "boom_entry", "E1", "景氣加速成長", ["24"],
             f"實質 GDP 年增率 ≥ {p['gdp_growth_min']}% 且高於 4 季前；或 CFNAI 3 個月平均連續 ≥ 3 個月 ≥ +{p['cfnai_min']}",
             [e1a, e1b], combine="any"))
    dd = dict(tf.drawdown(sp500))
    spy = yoy(sp500)
    e2a = custom("S&P 500 距高點／年增率", f"距高點 {p['sp500_near_high']}% 以內且年增率 ≥ {p['sp500_yoy_min']}%", "M",
                 [(d, dd.get(d, -100) >= -p["sp500_near_high"] and v >= p["sp500_yoy_min"],
                   dd.get(d, -100) >= -p["sp500_near_high"] and v >= p["sp500_yoy_min"] / 2) for d, v in spy],
                 spy, "%", P, lag=0)
    cape_f, cape_pr = pctile_flags(S("SHILLER_CAPE"), p["cape_pctile"], False, P)
    e2b = custom("席勒本益比 CAPE 百分位", f"≥ 第 {p['cape_pctile']} 百分位", "M", cape_f, cape_pr, "", P, lag=0)
    add(Crit("E2", "boom_entry", "E2", "資本市場熱絡", ["25", "26"],
             f"S&P 500 距歷史高點 {p['sp500_near_high']}% 以內且年增率 ≥ {p['sp500_yoy_min']}%；或 CAPE ≥ 第 {p['cape_pctile']} 百分位（只用當時以前的資料）",
             [e2a, e2b], combine="any"))
    um = ma3(S("UMCSENT"))
    um_f, um_pr = pctile_flags(um, p["sentiment_pctile"], False, P)
    # T3「高峰」只看是否接近 24 期高點；另外要求百分位 ≥ sentiment_peak_min_pctile，
    # 避免從谷底反彈、但仍偏低的信心指數也算「樂觀」（例：1992 年百分位只有 18.6）
    pk = p.get("sentiment_peak_min_pctile", 0)
    um_s = tr.smooth(S("UMCSENT"), "M", P["trend"])
    um_pm = dict(um_pr)
    um_t3 = [(d, None if met is None else bool(met and um_pm.get(d, -1) >= pk), near)
             for d, met, near in tr.RULES["T3"](um_s, "pct", P["trend"])]
    add(Crit("E3", "boom_entry", "E3", "市場樂觀情緒高昂", ["15"],
             f"密西根大學消費者信心指數（3 個月平均）≥ 第 {p['sentiment_pctile']} 百分位，"
             f"或符合 T3「高峰」且百分位 ≥ 第 {pk} 百分位",
             [custom("密西根信心指數百分位", f"≥ 第 {p['sentiment_pctile']} 百分位", "M", um_f, um_pr, "", P, lag=0),
              custom("密西根信心指數", f"T3 高峰且百分位 ≥ {pk}", "M", um_t3, um_s, "", P, lag=0)], combine="any"))
    rq = p["risk_pctile"]
    risk = []
    for label, rows in (("VIX 百分位", ma3(M("VIXCLS"))), ("Baa 利差百分位", ma3(M("BAA10Y"))),
                        ("NFCI 風險分項百分位", ma3(M("NFCIRISK")))):
        f, pr = pctile_flags(rows, rq, True, P)
        risk.append(custom(label, f"≤ 第 {rq} 百分位", "M", f, pr, "", P, lag=0))
    add(Crit("E4", "boom_entry", "E4", "風險意識極度低估", ["27", "28", "29"],
             f"VIX、Baa 利差、NFCI 風險分項（3 個月平均）中，至少 {p['risk_min_count']} 項 ≤ 第 {rq} 百分位",
             risk, combine=f"count:{p['risk_min_count']}"))

    # ── 3.3 B 觸頂（榮景期即將結束）──
    rpce, rdspi = ma3(yoy(S("DPCERA3M086SBEA"))), ma3(yoy(S("DSPIC96")))
    add(Crit("P1", "top", "1", "實質個人消費支出年增率 > 實質可支配所得年增率", ["14"],
             f"兩者都用 3 個月平均，前者 > 後者，連續 ≥ {p['consecutive_months']} 個月",
             [custom("實質消費 vs 實質所得年增率", "消費 > 所得", "M", gt_for(rpce, p["consecutive_months"], rdspi), rpce, "%", P)]))
    add(Crit("P2", "top", "2", "西德州原油價格上揚", ["4a"], "符合 T6「上揚」", [C("WTI 原油", wti, "M", "pct", "T6", " 美元", lag=0)]))
    u, u_info = u_shape(P)
    extra["u_shape"] = u_info
    jolts = C("新開職缺數", S("JTSJOL"), "M", "pct", "T5", " 千人")
    extra["jolts_reversal"] = jolts
    add(Crit("P3", "top", "3", "初領失業救濟金人數的 U 型結構確立", ["5", "22"],
             f"本輪低點（過去 {p['u_lookback_months']} 個月最低）後 ≥ {p['u_no_new_low_months']} 個月沒有再創新低、"
             f"比低點高 ≥ {p['u_rise_pct']}%、4 週平均連續 ≥ {p['u_rising_weeks']} 週上升", [u]))
    add(Crit("P4", "top", "4", "實質個人消費支出年增率從頂點轉折向下", ["14"], "符合 T5「高點反轉」",
             [C("實質個人消費支出年增率", yoy(S("DPCERA3M086SBEA")), "M", "pp", "T5", "%")]))
    add(Crit("P5", "top", "5", "實質可支配所得年增率從頂點轉折向下", ["14"], "符合 T5「高點反轉」",
             [C("實質可支配所得年增率", yoy(S("DSPIC96")), "M", "pp", "T5", "%")]))
    add(Crit("P6", "top", "6", "實質零售銷售年增率率先走弱", ["7"], "符合 T5「高點反轉」或 T1「下滑」",
             [C("實質零售銷售年增率", retail_yoy, "M", "pp", "T5", "%"),
              C("實質零售銷售年增率", retail_yoy, "M", "pp", "T1", "%")], combine="any"))
    add(Crit("P7", "top", "7", "消費者信心指數下降", ["15"], "密西根大學指數符合 T1「下滑」",
             [C("密西根信心指數", S("UMCSENT"), "M", "pt", "T1", lag=0)]))
    ss, ss_info = second_surge(P)
    extra["second_surge"] = ss_info
    add(Crit("P8", "top", "8", "耐久財訂單（不含運輸設備）出現「二度衝高」", ["16"],
             f"3 個月平均 {p['surge_months']} 個月累計成長 ≥ {p['surge_pct']}% 為衝高；之後連續 ≥ {p['flat_months']} 個月 3 個月變化在 ±{p['flat_pct']}% 以內為平緩；"
             f"第一波開始後 {p['second_surge_within']} 個月內再衝高即成立（成立後維持 {p['second_surge_hold']} 個月）", [ss]))
    add(Crit("P9", "top", "9", "州和地方政府支出高點轉向，聯邦與州地方政府收入下滑", ["17", "18"],
             "支出年增率符合 T5「高點反轉」，而且兩項收入年增率都符合 T1「下滑」",
             [C("州和地方政府支出年增率", yoy(S("SLEXPND")), "Q", "pp", "T5", "%"),
              C("聯邦政府收入年增率", yoy(S("FGRECPT")), "Q", "pp", "T1", "%"),
              C("州和地方政府收入年增率", yoy(S("W023RC1Q027SBEA")), "Q", "pp", "T1", "%")]))
    nlb = p["default_lookback_q"]

    def dr(label, sid):
        r = S(sid)
        t = lambda i, x: i >= nlb and x[i][1] > x[i - 1][1] > x[i - 2][1] and \
            x[i][1] - min(v for _, v in x[i - nlb:i + 1]) >= p["default_rise_pp"]  # noqa: E731
        n = lambda i, x: i >= 1 and x[i][1] > x[i - 1][1] and not t(i, x)  # noqa: E731
        return custom(label, f"連續 2 季上升且比 {nlb} 季低點高 ≥ {p['default_rise_pp']}pp", "Q", threshold_flags(r, t, n), r, "%", P, lag=2)
    add(Crit("P10", "top", "10", "消費性貸款違約率、企業貸款違約率上揚", ["19"],
             f"兩者都連續 2 季上升，且都比過去 {nlb} 季的低點高出 ≥ {p['default_rise_pp']} 個百分點",
             [dr("消費性貸款違約率", "DRCLACBS"), dr("企業貸款違約率", "DRBLACBS")]))

    # ── 3.4 A 確立衰退 ──
    a1, a1_obs, drop_info = consumption_drops(P)
    extra["drops"] = drop_info
    extra["a1_obs"] = a1_obs
    add(Crit("A1", "recession", "A1", "實質個人消費支出出現「2 次消費陡降」", ["14"],
             f"第 1 次：年增率從頂點轉折向下，{p['drop_quarters']} 季內累計下降 ≥ {p['drop_min_pp']} 個百分點（容許單季反彈 ≤ {p['drop_tolerance_pp']}）；第 2 次：之後 {p['second_drop_within']} 季內跌破第 1 次陡降結束時的數值"
             f"（回升 ≥ {p['drop_clear_pp']} 個百分點就解除）", [a1]))
    gp = yoy(S("GPDIC1"))
    add(Crit("A2", "recession", "A2", "民間投資年增率急降", ["20"],
             f"實質民間投資年增率 ≤ {p['invest_crash']}%，或年增率 < 0 且過去 2 季內下降 ≥ {p['invest_drop_pp']} 個百分點",
             [custom("實質民間投資年增率", "急降", "Q",
                     threshold_flags(gp, lambda i, r: r[i][1] <= p["invest_crash"] or
                                     (i >= 2 and r[i][1] < 0 and r[i - 2][1] - r[i][1] >= p["invest_drop_pp"]),
                                     lambda i, r: r[i][1] < 0), gp, "%", P)]))

    # A3（補充）：金融情勢轉緊，可取代 A1/A2 的佐證與觸頂門檻（第 5 階段後依回測加入，見 stage_rules.recession.fin）
    nf = M("NFCI")
    fmin = p.get("nfci_min", 0)
    add(Crit("A3", "recession", "A3", "金融情勢轉緊（補充依據）", ["29"],
             f"芝加哥聯準銀行金融情勢指數（NFCI，月平均）≥ {fmin}，代表金融情勢比歷史平均緊；"
             "可作為 A1、A2 的佐證，也可取代「近 12 個月觸頂訊號 ≥ 60%」的門檻",
             [custom("金融情勢指數 NFCI", f"≥ {fmin}", "M",
                     threshold_flags(nf, lambda i, r: r[i][1] >= fmin, lambda i, r: r[i][1] >= fmin - 0.2),
                     nf, "", P, lag=0)]))

    # A4（補充）：就業惡化，確立衰退的必要條件（2026-11 依回測加入，見 stage_rules.recession.employment）
    cr_pct, cr_n, smin = p.get("claims_rise_pct", 15), p.get("claims_lookback", 12), p.get("sahm_min", 0.3)
    c3 = tf.ma(M("IC4WSA"), 3)
    sahm = S("SAHMREALTIME")
    c3_rise = [(d, (v / min(x for _, x in c3[max(0, i - cr_n + 1):i + 1]) - 1) * 100) for i, (d, v) in enumerate(c3)]
    add(Crit("A4", "recession", "A4", "就業惡化（補充依據）", ["5"],
             f"初領失業救濟金（3 個月平均）比過去 {cr_n} 個月低點上升 ≥ {cr_pct}%，或即時薩姆規則 ≥ {smin}"
             "（任一成立）；確立衰退時必須成立，用來排除就業沒有轉差的誤判（例如 1987、2023 年）",
             [custom("初領失業救濟金比低點上升", f"≥ {cr_pct}%", "M",
                     threshold_flags(c3_rise, lambda i, r: r[i][1] >= cr_pct, lambda i, r: r[i][1] >= cr_pct * 0.6),
                     c3_rise, "%", P, lag=0),
              custom("薩姆規則（即時）", f"≥ {smin}", "M",
                     threshold_flags(sahm, lambda i, r: r[i][1] >= smin, lambda i, r: r[i][1] >= smin - 0.1),
                     sahm, " 百分點", P)],
             combine="any"))

    # ── 3.4 B 判斷落底 ──
    add(Crit("B1", "bottom", "B1", "實質民間投資季增率落底反轉", ["20"], "季增率符合 T4「落底反彈」",
             [C("實質民間投資季增率", tf.pct_change(S("GPDIC1")), "Q", "pp", "T4", "%")]))
    add(Crit("B2", "bottom", "B2", "實質零售銷售年增率落底反彈", ["7"], "符合 T4「落底反彈」",
             [C("實質零售銷售年增率", retail_yoy, "M", "pp", "T4", "%")]))
    add(Crit("B3", "bottom", "B3", "採購經理人指數觸底回升（以費城聯準銀行製造業調查代理）", ["21"],
             "符合 T4「落底反彈」（反彈 ≥ 3 點）",
             [C("費城聯準銀行製造業調查", S("GACDFSA066MSFRBPHI"), "M", "pt", "T4", lag=0)]))

    extra["extension"] = custom("初領失業救濟金（4 週平均）", "3-1 持續創新低", "W", extension_flags(P), S("IC4WSA"), "人", P)
    return crits, extra


# ── 指標總表用：每個指標的判斷值與 T1–T6 狀態 ─────────────────
def indicator_trends(cfg: dict) -> dict[str, dict]:
    P = cfg
    yoy = tf.yoy
    wti = tf.splice(S("WTISPLC"), M("DCOILWTICO"), "1986-01-01")
    rrsfs_yoy = yoy(S("RRSFS"))
    retail_yoy = tf.splice(yoy(S("DGDSRA3M086SBEA")), rrsfs_yoy, rrsfs_yoy[0][0])
    fed = tf.splice(M("DFEDTAR", "last"), M("DFEDTARU", "last"), "2008-12-01")
    sp500 = tf.extend(S("SHILLER_SP500"), M("SP500"))
    spec = {
        "1": (fed, "M", "pp"), "2": (M("DGS10"), "M", "pp"), "3": (M("MORTGAGE30US"), "M", "pp"),
        "4a": (wti, "M", "pct"), "4b": (S("PPIACO"), "M", "pct"), "5": (M("IC4WSA"), "M", "pct"),
        "6": (S("UEMPLT5"), "M", "pct"), "7": (retail_yoy, "M", "pp"), "8": (yoy(S("PNFI")), "Q", "pp"),
        "9": (yoy(S("DGORDER")), "M", "pp"), "10": (yoy(S("BOPTIMP")), "M", "pp"),
        "11": (yoy(S("DSPI")), "M", "pp"), "12": (yoy(S("PNFI")), "Q", "pp"), "13": (yoy(S("CPILFESL")), "M", "pp"),
        "14": (yoy(S("DPCERA3M086SBEA")), "M", "pp"), "15": (S("UMCSENT"), "M", "pt"), "16": (S("ADXTNO"), "M", "pct"),
        "17": (yoy(S("SLEXPND")), "Q", "pp"), "18": (yoy(S("FGRECPT")), "Q", "pp"), "19": (S("DRCLACBS"), "Q", "pp"),
        "20": (tf.pct_change(S("GPDIC1")), "Q", "pp"), "21": (S("GACDFSA066MSFRBPHI"), "M", "pt"),
        "22": (S("JTSJOL"), "M", "pct"), "23": (M("WALCL", "last"), "M", "pct"), "24": (yoy(S("GDPC1")), "Q", "pp"),
        "25": (sp500, "M", "pct"), "26": (S("SHILLER_CAPE"), "M", "pt"), "27": (M("VIXCLS"), "M", "pt"),
        "28": (M("BAA10Y"), "M", "pp"), "29": (M("NFCIRISK"), "M", "pt"),
        "30": (charts.buffett()[0], "Q", "pt"),
    }
    out = {}
    for iid, (rows, freq, kind) in spec.items():
        if len(rows) < 30:
            continue
        s = tr.smooth(rows, freq, P["trend"])
        res = {}
        for k, f in tr.RULES.items():
            fl = f(s, kind, P["trend"])
            _, met, near = fl[-1]
            res[k] = "met" if met else "near" if near else None
        out[iid] = {"rules": res, "basis": "3 個月平均" if freq == "M" else "季值", "asof": s[-1][0]}
    return out
