"""通用趨勢判斷 T1–T7（需求文件第 5 節）。

輸入：判斷用的數列 [(日期, 數值)]，頻率 M（月）或 Q（季），變化單位 pp／pct／pt。
輸出：每一期的 (成立, 接近)。成立為 None 表示資料不足、無法判斷。
「接近」：條件只成立 1 期、還差「連續 2 期」，或數值落在門檻的 2 倍範圍內。

所有判斷都只用「當期以前」的資料，回測時不會用到未來的資料。
"""
from __future__ import annotations

from . import transform as tf

Rows = list[tuple[str, float]]
Flags = list[tuple[str, bool | None, bool]]   # (日期, 成立, 接近)


def smooth(rows: Rows, freq: str, p: dict) -> Rows:
    n = p["smooth"].get(freq, 1)
    return tf.ma(rows, n) if n > 1 else rows


def _diff(a: float, b: float, unit: str) -> float:
    """a 相對 b 的變化：pp、pt 為差值；pct 為百分比。"""
    if unit == "pct":
        return (a / b - 1) * 100 if b else 0.0
    return a - b


def _band(ref: float, unit: str, band: dict) -> float:
    return band["pp"] if unit == "pp" else abs(ref) * band[unit] / 100


def t1_down(s: Rows, unit: str, p: dict) -> Flags:
    """T1 下滑：3 期平均 < 6 期前，且連續 2 期。"""
    L, k = p["lag"], p["consecutive"]
    out = []
    for i, (d, v) in enumerate(s):
        if i < L + k - 1:
            out.append((d, None, False)); continue
        hits = [s[i - j][1] < s[i - j - L][1] for j in range(k)]
        out.append((d, all(hits), hits[0] and not all(hits)))
    return out


def t6_up(s: Rows, unit: str, p: dict) -> Flags:
    """T6 上揚：3 期平均比 6 期前高 ≥ 門檻，且連續 2 期。"""
    L, k = p["lag"], p["consecutive"]
    thr = p["rise"][unit]
    out = []
    for i, (d, v) in enumerate(s):
        if i < L + k - 1:
            out.append((d, None, False)); continue
        hits = [_diff(s[i - j][1], s[i - j - L][1], unit) >= thr for j in range(k)]
        near = hits[0] and not all(hits) or (not hits[0] and _diff(v, s[i - L][1], unit) >= thr / 2)
        out.append((d, all(hits), near))
    return out


def t2_trough(s: Rows, unit: str, p: dict) -> Flags:
    """T2 谷底：落在過去 24 期最低點往上 10%（百分點類 +0.5pp）以內。"""
    W = p["window"]
    out = []
    for i, (d, v) in enumerate(s):
        if i < W - 1:
            out.append((d, None, False)); continue
        lo = min(x for _, x in s[i - W + 1:i + 1])
        b = _band(lo, unit, p["band"])
        out.append((d, v <= lo + b, lo + b < v <= lo + 2 * b))
    return out


def t3_peak(s: Rows, unit: str, p: dict) -> Flags:
    """T3 高峰：落在過去 24 期最高點往下 10%（百分點類 −0.5pp）以內。"""
    W = p["window"]
    out = []
    for i, (d, v) in enumerate(s):
        if i < W - 1:
            out.append((d, None, False)); continue
        hi = max(x for _, x in s[i - W + 1:i + 1])
        b = _band(hi, unit, p["band"])
        out.append((d, v >= hi - b, hi - 2 * b <= v < hi - b))
    return out


def _turn(s: Rows, unit: str, p: dict, low: bool) -> Flags:
    W, R, k = p["window"], p["recent"], p["consecutive"]
    thr = p["rebound"][unit]
    sign = 1 if low else -1
    out = []
    for i, (d, v) in enumerate(s):
        if i < W - 1:
            out.append((d, None, False)); continue
        win = s[i - W + 1:i + 1]
        vals = [x for _, x in win]
        ext = min(vals) if low else max(vals)
        j = i - W + 1 + len(vals) - 1 - vals[::-1].index(ext)   # 最近一次出現的位置
        recent = j >= i - R + 1
        moves = [sign * (s[i - m][1] - s[i - m - 1][1]) > 0 for m in range(k)]  # 之後連續 k 期上升（下降）
        after = i - k >= j
        dist = sign * _diff(v, ext, unit)
        met = recent and after and all(moves) and dist >= thr
        near = recent and not met and moves[0] and (dist >= thr / 2)
        out.append((d, met, near))
    return out


def t4_rebound(s: Rows, unit: str, p: dict) -> Flags:
    """T4 落底反彈：過去 12 期內出現 24 期最低點，之後連續 2 期上升，且比最低點高 ≥ 門檻。"""
    return _turn(s, unit, p, low=True)


def t5_reversal(s: Rows, unit: str, p: dict) -> Flags:
    """T5 高點反轉：過去 12 期內出現 24 期最高點，之後連續 2 期下降，且比最高點低 ≥ 門檻。"""
    return _turn(s, unit, p, low=False)


def t7_pctile(s: Rows, start: str, min_years: int, min_span: float = 0) -> list[tuple[str, float]]:
    """T7 歷史分位：目前數值在「1985 年（或資料起點）至當期」分布中的百分位（0–100）。

    1985 年初樣本太少，至少回看 min_years 年（可用到 1985 年以前的資料，但不會用到未來）。
    min_span：序列開始後未滿這麼多年，不計算百分位（避免 1992 年 VIX 只有 2.5 年樣本就被算成「極低」）。
    """
    out = []
    y0, m0 = (int(s[0][0][:4]), int(s[0][0][5:7])) if s else (0, 0)
    for i, (d, v) in enumerate(s):
        if min_span and (int(d[:4]) - y0) + (int(d[5:7]) - m0) / 12 < min_span:
            continue
        lo = min(start, f"{int(d[:4]) - min_years:04d}{d[4:]}")
        sample = [x for dd, x in s[:i + 1] if dd >= lo]
        if len(sample) < 24:
            continue
        below = sum(1 for x in sample if x < v)
        equal = sum(1 for x in sample if x == v)
        out.append((d, (below + 0.5 * equal) / len(sample) * 100))
    return out


RULES = {"T1": t1_down, "T2": t2_trough, "T3": t3_peak, "T4": t4_rebound, "T5": t5_reversal, "T6": t6_up}
RULE_ZH = {"T1": "下滑", "T2": "谷底", "T3": "高峰", "T4": "落底反彈", "T5": "高點反轉", "T6": "上揚", "T7": "歷史分位"}


def all_rules(s: Rows, unit: str, p: dict) -> dict[str, Flags]:
    return {k: f(s, unit, p) for k, f in RULES.items()}
