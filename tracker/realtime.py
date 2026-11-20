"""即時資料回測（ALFRED：FRED 歷史版本資料庫）。

每個月月底，只用「當時已公布的版本」重跑整個階段判定，取當月結果，再和現行回測（修正後資料）比較。
  realtime：有 ALFRED 版本就用當時數值，沒有就用目前數值（ALFRED 存檔前的期間無法還原）
  strict  ：同上，但 NFCI 等指數在首次公布前當作不存在

輸出 data/realtime_backtest.json（儀表板用）與 docs/即時回測.md。
版本資料暫存在 cache/alfred/（不上傳）。
"""
from __future__ import annotations

import calendar
import json
import os
import time
from collections import defaultdict

from . import criteria as cr
from .backtest import evaluate, nber_turns
from .settings import DATA_DIR, DOCS_DIR, ROOT, load_config, stamp
from .sources import FRED_BASE, _get
from .stage import run_stage

CACHE = ROOT / "cache" / "alfred"
OUT_JSON = DATA_DIR / "realtime_backtest.json"
OUT_MD = DOCS_DIR / "即時回測.md"
ZH = {"recession": "衰退期", "recovery": "復甦期", "growth": "成長期", "boom": "榮景期"}
VARIANTS = {"realtime": "當時公布的數值", "strict": "當時數值＋NFCI 公布前不存在"}


# ── 下載 ────────────────────────────────────────────
def _obs(params: dict, key: str) -> list[dict]:
    r = _get(f"{FRED_BASE}/series/observations", params | {"api_key": key, "file_type": "json"}, tries=5, timeout=120)
    return r.json().get("observations", [])


def download(cfg: dict, key: str, max_age_days: float = 20) -> None:
    """完整版本（output_type=1：每筆數值的有效期間）；snapshot 類只抓每月月底版本。快取 max_age_days 天。"""
    rc = cfg["realtime_backtest"]
    CACHE.mkdir(parents=True, exist_ok=True)
    fresh = lambda f: f.exists() and time.time() - f.stat().st_mtime < max_age_days * 86400  # noqa: E731
    for s in rc["series"]:
        f = CACHE / f"{s}.json"
        if fresh(f):
            continue
        rows, off = [], 0
        while True:
            obs = _obs({"series_id": s, "realtime_start": "1776-07-04", "realtime_end": "9999-12-31",
                        "observation_start": "1970-01-01", "output_type": 1, "limit": 100000, "offset": off}, key)
            rows += [(o["realtime_start"], o["realtime_end"], o["date"], o["value"]) for o in obs]
            off += len(obs)
            if len(obs) < 100000:
                break
        f.write_text(json.dumps(rows), encoding="utf-8")
        time.sleep(0.6)
    today = time.strftime("%Y-%m-%d")
    for s in rc["snapshot"]:
        f = CACHE / f"{s}_snap.json"
        snaps = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        first = rc["not_published_before"][s]
        for m in cr.month_range(first, today[:7]):
            d = _month_end(m)
            if d >= today or (m in snaps and m < cr.shift(today[:7], -2)):  # 最近 2 個月每次重抓
                continue
            snaps[m] = [(o["date"], o["value"]) for o in _obs(
                {"series_id": s, "realtime_start": d, "realtime_end": d, "observation_start": "1970-01-01"}, key)]
            time.sleep(0.5)
        f.write_text(json.dumps(snaps), encoding="utf-8")


# ── 組出某一天的資料版本 ─────────────────────────────
def _month_end(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    return f"{m}-{calendar.monthrange(y, mo)[1]:02d}"


class Vintages:
    def __init__(self, cfg: dict):
        rc = cfg["realtime_backtest"]
        self.by_date: dict[str, dict] = {}
        self.first: dict[str, str] = {}
        for s in rc["series"]:
            d = defaultdict(list)
            for rs, re_, dt, v in json.loads((CACHE / f"{s}.json").read_text(encoding="utf-8")):
                d[dt].append((rs, re_, v))
            self.by_date[s] = d
            self.first[s] = min(rs for ivs in d.values() for rs, _, _ in ivs)
        self.snaps = {s: json.loads((CACHE / f"{s}_snap.json").read_text(encoding="utf-8")) for s in rc["snapshot"]}
        self.unpub = rc["not_published_before"]

    def series_at(self, s: str, T: str) -> list[tuple[str, float]]:
        out = []
        for dt, ivs in self.by_date[s].items():
            for rs, re_, v in ivs:
                if rs <= T <= re_:
                    if v not in (".", ""):
                        out.append((dt, float(v)))
                    break
        return sorted(out)

    def value(self, s: str, dt: str, T: str):
        for rs, re_, v in self.by_date[s].get(dt, []):
            if rs <= T <= re_ and v not in (".", ""):
                return float(v)
        return None

    def install(self, T: str, strict: bool) -> None:
        """把 T 當天的版本放進 criteria 的序列快取；沒有版本的序列由 criteria 自動讀目前數值。"""
        cr._cache.clear()
        for s in self.by_date:
            if T >= self.first[s]:
                v = self.series_at(s, T)
                if v:
                    cr._cache[s] = v
        for s, sn in self.snaps.items():
            if T[:7] in sn:
                cr._cache[s] = [(d, float(v)) for d, v in sn[T[:7]] if v not in (".", "")]
            elif strict and T[:7] < self.unpub[s]:
                cr._cache[s] = []


# ── 模擬與評估 ──────────────────────────────────────
def _collapse(seq: list[tuple[str, str]]) -> list[list]:
    tl: list[list] = []
    for m, st in seq:
        if not tl or tl[-1][2] != st:
            if tl:
                tl[-1][1] = m
            tl.append([m, None, st])
    return tl


def _expand(tl: list, last: str) -> dict[str, str]:
    out = {}
    for a, b, s in tl:
        for m in cr.month_range(a, b or last):
            if b is None or m < b:
                out[m] = s
    return out


def _summary(tl: list, turns: list, today: str) -> dict:
    ev = evaluate(tl, turns, today)
    return {"rows": ev["rows"], "false": ev["false"], "false_months": ev["false_months"],
            "caught": ev["caught"], "recovered": ev["recovered"], "switches": len(tl) - 1,
            "timeline": [[a, b, ZH[s]] for a, b, s in tl]}


def _diff_runs(base: dict, seq: list) -> list[dict]:
    runs: list[dict] = []
    for m, s in seq:
        b = base.get(m)
        if b == s:
            continue
        if runs and runs[-1]["to"] == ZH[s] and runs[-1]["from"] == ZH.get(b, b) and cr.shift(runs[-1]["end"], 1) == m:
            runs[-1]["end"] = m
        else:
            runs.append({"start": m, "end": m, "from": ZH.get(b, b), "to": ZH[s]})
    return runs


def revision_table(cfg: dict, V: Vintages) -> list[dict]:
    """初值（第一次公布）vs 目前數值：只算 ALFRED 有存到第一次公布的觀測值。"""
    recs = [(cr.shift(t["peak"], -6), cr.shift(t["trough"], 6)) for t in nber_turns(cfg["settings"]["backtest_start"])]
    out = []
    for sid, name, k, ann in cfg["realtime_backtest"]["revision_table"]:
        d = V.by_date.get(sid)
        if not d:
            continue
        rows = []
        for dt in sorted(d):
            if dt < "1985-01-01":
                continue
            rs0 = min(rs for rs, _, _ in d[dt])
            if rs0[:7] > cr.shift(dt[:7], 9):  # ALFRED 開始存檔前的觀測值，不是真正初值
                continue
            p = cr.shift(dt[:7], -k) + "-01"
            a, b = V.value(sid, dt, rs0), V.value(sid, p, rs0)
            c, e = V.value(sid, dt, "9999-12-30"), V.value(sid, p, "9999-12-30")
            if None in (a, b, c, e) or not b or not e:
                continue
            g = (lambda x, y: ((x / y) ** ann - 1) * 100) if ann else (lambda x, y: (x / y - 1) * 100)
            rows.append((dt[:7], g(a, b), g(c, e)))
        if not rows:
            continue
        diff = [abs(x - y) for _, x, y in rows]
        near = [abs(x - y) for m, x, y in rows if any(a <= m <= b for a, b in recs)]
        flips = [(m, x, y) for m, x, y in rows if (x < 0) != (y < 0)]
        big = sorted((f for f in flips if any(a <= f[0] <= b for a, b in recs)), key=lambda f: -abs(f[1] - f[2]))[:3]
        out.append({"id": sid, "name": name, "since": min(m for m, _, _ in rows), "n": len(rows),
                    "mean": round(sum(diff) / len(diff), 2), "near": round(sum(near) / len(near), 2) if near else None,
                    "max": round(max(diff), 1), "flips": len(flips),
                    "examples": [{"month": m, "first": round(x, 1), "now": round(y, 1)} for m, x, y in sorted(big)]})
    return out


def run_realtime(download_first: bool = True) -> dict:
    cfg = load_config()
    today = time.strftime("%Y-%m-%d")
    if download_first:
        download(cfg, os.environ["FRED_API_KEY"])
    V = Vintages(cfg)
    turns = nber_turns(cfg["settings"]["backtest_start"])
    start = max(cfg["stage_rules"]["initial"]["month"], "1986-01")
    last = cr.shift(today[:7], -1)
    months = cr.month_range(start, last)

    cr._cache.clear()
    base_tl = run_stage(cfg, _month_end(last))["timeline"]
    base = _expand(base_tl, cr.shift(last, 1))
    result = {"generated": stamp(cfg), "through": last, "first_vintage": dict(sorted(V.first.items(), key=lambda x: x[1])),
              "revised": _summary(base_tl, turns, _month_end(last)), "variants": {}}
    for key, strict in (("realtime", False), ("strict", True)):
        seq = []
        for m in months:
            V.install(_month_end(m), strict)
            seq.append((m, run_stage(cfg, _month_end(m))["timeline"][-1][2]))
        r = _summary(_collapse(seq), turns, _month_end(last))
        r["name"] = VARIANTS[key]
        r["diff_months"] = sum(1 for m, s in seq if base.get(m) != s)
        r["months"] = len(seq)
        r["diff_runs"] = _diff_runs(base, seq)
        r["current"] = ZH[seq[-1][1]]
        result["variants"][key] = r
    cr._cache.clear()
    result["revisions"] = revision_table(cfg, V)
    DATA_DIR.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    write_report(result)
    return result


def _lag(r: dict, k: str) -> str:
    return "沒抓到" if r[k] is None else f"{r[k]}（{r[k + '_lag']:+d}）"


def write_report(R: dict) -> None:
    rv, rt, st = R["revised"], R["variants"]["realtime"], R["variants"]["strict"]
    L = ["# 即時資料回測（ALFRED）", "",
         f"> 產生時間：{R['generated']}（台灣時間）；模擬到 {R['through']}  ",
         "> 資料來源：ALFRED（FRED 歷史版本資料庫），FRED API `fred/series/observations` 的 realtime 參數"
         "（https://fred.stlouisfed.org/docs/api/fred/series_observations.html）  ",
         "> 本檔由 `python run.py realtime` 自動產生（每月 1 日），請勿手動修改。", "",
         "## 做法", "",
         "- 每個月月底，只用「當時已公布的版本」重跑整個階段判定，取當月的判定結果，串成即時時間軸。",
         "- 有 ALFRED 版本的序列換成當時數值；ALFRED 開始存檔前的期間沒有版本，只能沿用目前數值（見最下方各序列起始日）。",
         "- 市場價格類（利率、油價、股價、VIX）與 Shiller 資料不會被修正，沿用目前數值。",
         "- 嚴格版：NFCI（A3 金融情勢）在 2011-05 首次出現在 ALFRED 之前當作不存在。", "",
         "## 結果（正數＝比 NBER 落後的月數）", "",
         f"| NBER 衰退 | 修正後資料 進入衰退 | 當時數值 | 嚴格版 | 修正後資料 進入復甦 | 當時數值 | 嚴格版 |",
         "|---|---|---|---|---|---|---|"]
    for i, a in enumerate(rv["rows"]):
        b, c = rt["rows"][i], st["rows"][i]
        L.append(f"| {a['peak']} – {a['trough']} | {_lag(a, 'enter')} | {_lag(b, 'enter')} | {_lag(c, 'enter')} | "
                 f"{_lag(a, 'recover')} | {_lag(b, 'recover')} | {_lag(c, 'recover')} |")
    f = lambda x: f"{len(x['false'])} 次（{'、'.join(x['false']) or '無'}，共 {x['false_months']} 個月）"  # noqa: E731
    L += ["", "| | 修正後資料 | 當時數值 | 嚴格版 |", "|---|---|---|---|",
          f"| 誤判衰退 | {f(rv)} | {f(rt)} | {f(st)} |",
          f"| 階段切換次數 | {rv['switches']} | {rt['switches']} | {st['switches']} |",
          f"| 和修正後資料不同的月份 | — | {rt['diff_months']}/{rt['months']} | {st['diff_months']}/{st['months']} |",
          f"| 最新月份判定 | {rv['timeline'][-1][2]} | {rt['current']} | {st['current']} |", "",
          "## 判定不同的期間（當時數值）", ""]
    L += [f"- {r['start']}" + (f" ~ {r['end']}" if r["end"] != r["start"] else "") + f"：修正後 {r['from']} → 當時 {r['to']}"
          for r in rt["diff_runs"]] or ["- 無"]
    L += ["", "## 時間軸", "",
          "- 修正後資料：" + " → ".join(f"{a} {s}" for a, _, s in rv["timeline"]),
          "- 當時數值：" + " → ".join(f"{a} {s}" for a, _, s in rt["timeline"]),
          "- 嚴格版：" + " → ".join(f"{a} {s}" for a, _, s in st["timeline"]), "",
          "## 初值 vs 目前數值（百分點）", "",
          "只計算 ALFRED 有存到第一次公布的觀測值。衰退前後＝NBER 衰退開始前 6 個月到結束後 6 個月。", "",
          "| 序列 | 起 | 筆數 | 平均差 | 衰退前後平均差 | 最大差 | 正負號翻轉 | 衰退前後翻轉例子（初值→目前） |",
          "|---|---|---|---|---|---|---|---|"]
    for r in R["revisions"]:
        ex = "；".join(f"{e['month']} {e['first']}→{e['now']}" for e in r["examples"]) or "—"
        L.append(f"| {r['name']}（`{r['id']}`） | {r['since']} | {r['n']} | {r['mean']} | {r['near'] if r['near'] is not None else '—'} | "
                 f"{r['max']} | {r['flips']} 次 | {ex} |")
    L += ["", "## 各序列 ALFRED 最早版本日", "",
          "早於此日期的期間沒有當時數值，回測沿用目前數值，所以愈早的衰退（尤其 1990 年）愈接近修正後資料的結果，可信度較低。", "",
          "| 序列 | 最早版本 |", "|---|---|"]
    L += [f"| `{s}` | {d} |" for s, d in R["first_vintage"].items()]
    DOCS_DIR.mkdir(exist_ok=True)
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def load() -> dict | None:
    if not OUT_JSON.exists():
        return None
    R = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    return {k: R[k] for k in ("generated", "through", "revised", "variants", "revisions")} | {
        "first_vintage": R["first_vintage"]}
