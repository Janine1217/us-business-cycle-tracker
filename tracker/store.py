"""歷史資料庫：每個序列一個 CSV（date,value），另以 status.json 記錄抓取狀態。

採 CSV 而非 SQLite：GitHub 上可直接看到每天的數值變化（git diff），也方便用 Excel 開啟。
"""
from __future__ import annotations

import csv
import json

from .settings import SERIES_DIR, STATUS_FILE


def write_series(series_id: str, rows: list[tuple[str, float]]) -> None:
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    with open(SERIES_DIR / f"{series_id}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "value"])
        for d, v in rows:
            w.writerow([d, repr(v) if isinstance(v, float) else v])


def read_series(series_id: str) -> list[tuple[str, float]]:
    path = SERIES_DIR / f"{series_id}.csv"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [(r["date"], float(r["value"])) for r in csv.DictReader(f)]


def load_status() -> dict:
    if STATUS_FILE.exists():
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    return {"series": {}, "runs": [], "consecutive_failed_runs": 0}


def save_status(status: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    status["runs"] = status["runs"][-60:]  # 只保留最近 60 次執行紀錄
    STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
