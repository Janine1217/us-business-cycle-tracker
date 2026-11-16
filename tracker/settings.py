"""讀取 config.yaml 與 .env，提供共用路徑與時間工具。"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SERIES_DIR = DATA_DIR / "series"
STATUS_FILE = DATA_DIR / "status.json"
METADATA_FILE = DATA_DIR / "metadata.json"
DOCS_DIR = ROOT / "docs"

load_dotenv(ROOT / ".env")


def load_config() -> dict:
    yaml = YAML(typ="safe", pure=True)
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.load(f)


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value if value else default


def now_local(cfg: dict | None = None) -> datetime:
    """台灣時間（固定 UTC+8，台灣沒有日光節約時間）。"""
    hours = (cfg or {}).get("settings", {}).get("utc_offset_hours", 8)
    return datetime.now(timezone(timedelta(hours=hours)))


def stamp(cfg: dict | None = None) -> str:
    return now_local(cfg).strftime("%Y-%m-%d %H:%M")
