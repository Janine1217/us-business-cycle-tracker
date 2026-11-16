"""數列轉換（純 Python）：月平均、年增率、季增率、移動平均、拼接。

數列格式一律為 [(YYYY-MM-DD, 數值), ...]，依日期遞增。
"""
from __future__ import annotations

from collections import OrderedDict

Rows = list[tuple[str, float]]


def to_monthly(rows: Rows, how: str = "mean") -> Rows:
    """日、週資料轉月資料（mean 平均／last 月底值），日期記為該月 1 日。"""
    groups: "OrderedDict[str, list[float]]" = OrderedDict()
    for d, v in rows:
        groups.setdefault(d[:7], []).append(v)
    if how == "last":
        return [(f"{m}-01", vs[-1]) for m, vs in groups.items()]
    return [(f"{m}-01", sum(vs) / len(vs)) for m, vs in groups.items()]


def _shift_year(d: str, years: int = 1) -> str:
    return f"{int(d[:4]) - years:04d}{d[4:]}"


def yoy(rows: Rows, weekly: bool = False) -> Rows:
    """年增率（%）。月、季資料以同月對比；週資料以 52 週前對比。"""
    out = []
    if weekly:
        for i in range(52, len(rows)):
            base = rows[i - 52][1]
            if base:
                out.append((rows[i][0], (rows[i][1] / base - 1) * 100))
        return out
    idx = dict(rows)
    for d, v in rows:
        base = idx.get(_shift_year(d))
        if base:
            out.append((d, (v / base - 1) * 100))
    return out


def pct_change(rows: Rows) -> Rows:
    """與前一期相比的變化率（%），季資料即為季增率（未年化）。"""
    return [(rows[i][0], (rows[i][1] / rows[i - 1][1] - 1) * 100)
            for i in range(1, len(rows)) if rows[i - 1][1]]


def ma(rows: Rows, n: int) -> Rows:
    """n 期移動平均（需要連續 n 期才輸出）。"""
    out, s = [], 0.0
    for i, (d, v) in enumerate(rows):
        s += v
        if i >= n:
            s -= rows[i - n][1]
        if i >= n - 1:
            out.append((d, s / n))
    return out


def splice(early: Rows, late: Rows, cutoff: str) -> Rows:
    """cutoff 之前用 early，之後用 late。"""
    return [r for r in early if r[0] < cutoff] + [r for r in late if r[0] >= cutoff]


def extend(base: Rows, newer: Rows) -> Rows:
    """base 結束後，以 newer 補上更新的資料。"""
    if not base:
        return newer
    last = base[-1][0]
    return base + [r for r in newer if r[0] > last]


def drawdown(rows: Rows) -> Rows:
    """距離歷史高點的幅度（%，≤ 0）。"""
    out, peak = [], float("-inf")
    for d, v in rows:
        peak = max(peak, v)
        out.append((d, (v / peak - 1) * 100))
    return out


def since(rows: Rows, start: str) -> Rows:
    return [r for r in rows if r[0] >= start]


def before(rows: Rows, end: str) -> Rows:
    return [r for r in rows if r[0] < end]


def percentile(values: list[float], q: float) -> float:
    """線性內插百分位（q 介於 0–100）。"""
    s = sorted(values)
    if not s:
        return float("nan")
    k = (len(s) - 1) * q / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)
