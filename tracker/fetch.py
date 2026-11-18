"""抓取所有序列並更新歷史資料庫。

單一序列失敗時保留舊資料、記錄錯誤，其他序列照常更新（需求文件第 2 節錯誤處理）。
"""
from __future__ import annotations

import json
import time

from . import sources, store
from .settings import METADATA_FILE, env, load_config, stamp


def run_fetch(only: list[str] | None = None) -> dict:
    cfg = load_config()
    st = cfg["settings"]
    start = st["observation_start"]
    api_key = (env("FRED_API_KEY") or "").strip().strip("\"'").strip()  # 容忍貼上時多出的空白、換行、引號
    status = store.load_status()
    now = stamp(cfg)

    series_cfg = {k: v for k, v in cfg["series"].items() if not only or k in only}
    results: dict[str, str | None] = {}

    def ok(sid: str, rows: list[tuple[str, float]], src_url: str) -> None:
        rows = [r for r in rows if r[0] >= start]
        store.write_series(sid, rows)
        s = status["series"].setdefault(sid, {})
        s.update(last_attempt=now, last_success=now, last_error=None, failed=False,
                 last_obs_date=rows[-1][0], last_obs_value=rows[-1][1], count=len(rows), source_url=src_url)
        results[sid] = None

    def fail(sid: str, err: str) -> None:
        s = status["series"].setdefault(sid, {})
        s.update(last_attempt=now, last_error=err, failed=True)
        results[sid] = err

    # FRED
    fred_ids = [k for k, v in series_cfg.items() if v["source"] == "fred"]
    key_problem = None
    if not api_key:
        key_problem = "沒有設定 FRED_API_KEY"
    elif not (len(api_key) == 32 and api_key.isalnum() and api_key == api_key.lower()):
        key_problem = f"FRED_API_KEY 格式不對（應為 32 個小寫英數字，目前長度 {len(api_key)}）"
    if fred_ids and key_problem:
        print("✗", key_problem)
        for sid in fred_ids:
            fail(sid, key_problem)
    else:
        for sid in fred_ids:
            try:
                ok(sid, sources.fred_observations(sid, api_key, start),
                   f"https://fred.stlouisfed.org/series/{sid}")
            except Exception as e:  # noqa: BLE001 — 任何錯誤都不能中斷其他序列
                fail(sid, str(e)[:300])
            time.sleep(0.6)  # FRED 限流：每分鐘 120 次

    # 席勒資料（一次下載，拆成多個序列）
    shiller_ids = [k for k, v in series_cfg.items() if v["source"] == "shiller"]
    if shiller_ids:
        sh = st["shiller"]
        try:
            url, cols = sources.shiller_monthly(sh["page"], sh["fallback_url"])
            for sid in shiller_ids:
                field = series_cfg[sid]["field"]
                if cols.get(field):
                    ok(sid, cols[field], url)
                else:
                    fail(sid, f"席勒資料檔沒有 {field} 欄位")
        except Exception as e:  # noqa: BLE001
            for sid in shiller_ids:
                fail(sid, str(e)[:300])

    # Yahoo Finance（費半等 FRED 沒有的指數）
    for sid in [k for k, v in series_cfg.items() if v["source"] == "yahoo"]:
        try:
            url, rows = sources.yahoo_daily(series_cfg[sid]["symbol"])
            ok(sid, rows, url)
        except Exception as e:  # noqa: BLE001
            fail(sid, str(e)[:300])

    failed = [k for k, v in results.items() if v]
    run_failed = bool(results) and len(failed) / len(results) > st["run_failure_ratio"]
    status["consecutive_failed_runs"] = status.get("consecutive_failed_runs", 0) + 1 if run_failed else 0
    status["runs"].append({"time": now, "total": len(results), "failed": failed, "run_failed": run_failed})
    status["last_run"] = now
    store.save_status(status)
    return {"total": len(results), "failed": {k: results[k] for k in failed}, "run_failed": run_failed}


def run_verify() -> list[dict]:
    """用 FRED API 查證每個代碼的名稱、頻率、單位、起訖日（需求文件第 2 節）。"""
    cfg = load_config()
    api_key = env("FRED_API_KEY")
    if not api_key:
        raise SystemExit("請先在 .env 設定 FRED_API_KEY")
    out = []
    for sid, sc in cfg["series"].items():
        if sc["source"] != "fred":
            continue
        try:
            info = sources.fred_series_info(sid, api_key)
            info["exists"] = True
        except Exception as e:  # noqa: BLE001
            info = {"id": sid, "exists": False, "error": str(e)[:200]}
        info["name_zh"] = sc["name"]
        out.append(info)
        time.sleep(0.6)
    METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    METADATA_FILE.write_text(json.dumps({"checked": stamp(cfg), "series": out}, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    return out
