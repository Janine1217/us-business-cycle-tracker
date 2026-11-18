"""產生靜態儀表板：site/index.html（版面）＋ site/data.js（資料）。

site/ 資料夾直接部署到 GitHub Pages；本機也可以直接用瀏覽器開啟 site/index.html。
"""
from __future__ import annotations

import json
import shutil

from . import store
from .charts import build_charts
from .criteria import indicator_trends
from .settings import ROOT, load_config, stamp
from .backtest import run_backtest, write_report
from .stage import record_live, run_stage

SITE = ROOT / "site"
TEMPLATE = ROOT / "web"
STAGE_ZH = {"recovery": "復甦期", "growth": "成長期", "boom": "榮景期", "recession": "衰退期"}


def _round(v: float) -> float:
    a = abs(v)
    return round(v, 4 if a < 10 else 2 if a < 10000 else 0)


def _recessions(start: str) -> list[list[str]]:
    out, cur = [], None
    for d, v in store.read_series("USREC"):
        if v >= 1 and cur is None:
            cur = d
        elif v < 1 and cur is not None:
            out.append([cur, d])
            cur = None
    if cur:
        out.append([cur, None])
    return [r for r in out if (r[1] or "9999") >= start]


def _source_info(sid: str, cfg: dict, status: dict) -> dict:
    sc = cfg["series"][sid]
    st = status["series"].get(sid, {})
    if sc["source"] == "fred":
        url = f"https://fred.stlouisfed.org/series/{sid}"
        org = "FRED（聖路易聯邦準備銀行）"
    else:
        url = st.get("source_url") or cfg["settings"]["shiller"]["page"]
        org = "Robert Shiller 美股資料"
    return {"id": sid, "name": sc["name"], "org": org, "url": url,
            "freq": sc["freq"], "failed": bool(st.get("failed")),
            "error": st.get("last_error"), "last_success": st.get("last_success"),
            "last_obs": st.get("last_obs_date")}


def run_build(record: bool = True) -> dict:
    cfg = load_config()
    status = store.load_status()
    start = cfg["settings"]["backtest_start"]
    indicators = {i["id"]: i for i in cfg["indicators"]}
    now = stamp(cfg)

    # 階段判定與訊號
    st = run_stage(cfg, now[:10])
    bt = run_backtest(cfg, now[:10], st)
    write_report(bt, cfg, now, st["timeline"])
    crits = st.pop("_crits")
    st.pop("_extra")
    changes = record_live(st, now) if record else []
    trends = indicator_trends(cfg)
    ind_state: dict[str, str] = {}
    for c in crits:
        met, near, _ = c.at(st["asof"])
        for iid in c.indicators:
            cur = ind_state.get(iid)
            if met:
                ind_state[iid] = "met"
            elif near and cur != "met":
                ind_state[iid] = "near"
    stage_zh_timeline = [[a, b, STAGE_ZH[s]] for a, b, s in st["timeline"]]

    charts_out, table = [], []
    for ch in build_charts(cfg):
        ind = indicators.get(ch["id"], {})
        sources = [_source_info(s, cfg, status) for s in ch["sources"]]
        notes = list(ch.get("notes", []))
        if ind.get("note") and ind["note"] not in notes:
            notes.append(ind["note"])
        views = []
        for v in ch["views"]:
            traces = []
            for t in v["traces"]:
                data = [(d, y) for d, y in t["data"] if d >= start]
                if not data:
                    continue
                if data[0][0] > f"{start[:4]}-12-31" and "估計" not in t["name"]:
                    msg = f"{t['name']}：本資料自 {data[0][0][:4]} 年起提供"
                    if msg not in notes:
                        notes.append(msg)
                traces.append({"name": t["name"], "unit": t["unit"], "axis": t["axis"], "dash": t["dash"],
                               "x": [d for d, _ in data], "y": [_round(y) for _, y in data]})
            views.append({k: v[k] for k in ("name", "y_title", "y2_title", "hlines", "vlines", "log_ok")}
                         | {"traces": traces, "marks": []})
        # 特殊型態標註（畫在第一個檢視）
        if views and views[0]["traces"] and st["marks"].get(ch["id"]):
            t0 = views[0]["traces"][0]
            lookup = dict(zip(t0["x"], t0["y"]))
            for mk in st["marks"][ch["id"]]:
                y = mk.get("y")
                if y is None:
                    y = lookup.get(mk["x"])
                if y is not None and mk["x"] >= start:
                    views[0]["marks"].append({"x": mk["x"], "y": _round(y), "text": mk["text"]})
        stages = [STAGE_ZH[s] for s in ind.get("stages", [])] + (["額外參考"] if ind.get("ref") else [])
        charts_out.append({"id": ch["id"], "title": ch["title"], "stages": stages,
                           "sources": sources, "notes": notes, "views": views})

        # 指標總表：以第一個檢視的第一條線為代表值
        head = ch["views"][0]["traces"][0]
        data = head["data"]
        if data:
            last, prev = data[-1], data[-2] if len(data) > 1 else None
            chg = None
            if prev:
                chg = (last[1] - prev[1]) if head["chg"] in ("pp", "pt") else \
                      ((last[1] / prev[1] - 1) * 100 if prev[1] else None)
            failed = [s for s in sources if s["failed"]]
            table.append({"id": ch["id"], "name": ch["title"], "metric": head["name"], "stages": stages,
                          "value": _round(last[1]), "unit": head["unit"], "date": last[0],
                          "prev": _round(prev[1]) if prev else None, "prev_date": prev[0] if prev else None,
                          "chg": _round(chg) if chg is not None else None,
                          "chg_unit": {"pp": "百分點", "pt": "點", "pct": "%"}[head["chg"]],
                          "failed": [{"id": s["id"], "last_success": s["last_success"]} for s in failed],
                          "trend": trends.get(ch["id"]), "state": ind_state.get(ch["id"])})

    payload = {
        "generated": now, "last_run": status.get("last_run"),
        "start": start, "recessions": _recessions(start),
        "charts": charts_out, "table": table,
        "stimulus": cfg.get("stimulus", []),
        "stage": st | {"timeline": stage_zh_timeline},
        "backtest": {k: bt[k] for k in ("turns", "current", "spec", "criteria")},
    }
    SITE.mkdir(exist_ok=True)
    for f in TEMPLATE.iterdir():
        if f.is_file():
            shutil.copy2(f, SITE / f.name)
    (SITE / "data.js").write_text("window.DASHBOARD = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
                                  encoding="utf-8")
    return {"charts": len(charts_out), "size_kb": (SITE / "data.js").stat().st_size // 1024,
            "stage": st["stage"]["name"], "signals": [f"{s['level_zh']} {s['name']}" for s in st["signals"]],
            "changes": changes}
