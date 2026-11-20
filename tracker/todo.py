"""讀取 docs/待調整事項.md，轉成儀表板「待調整」分頁的資料。

格式：每個「## 標題」下面一張 Markdown 表格；「狀態」欄以 ✅ 開頭或含「已解決」視為已解決。
「## 調整紀錄」那張表另外存成 log（空白列略過）。
"""
from __future__ import annotations

import re

from .settings import DOCS_DIR

TODO_FILE = DOCS_DIR / "待調整事項.md"


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def load_todo() -> dict:
    if not TODO_FILE.exists():
        return {"sections": [], "log": [], "open": 0, "done": 0}
    sections, log, cur, head = [], [], None, None
    updated = None
    for line in TODO_FILE.read_text(encoding="utf-8").splitlines():
        m = re.search(r"最後整理日期\s*(\d{4}-\d{2}-\d{2})", line)
        if m:
            updated = m.group(1)
        if line.startswith("## "):
            cur = {"title": line[3:].strip(), "items": []}
            head = None
            if cur["title"] != "調整紀錄":
                sections.append(cur)
            continue
        if cur is None or not line.lstrip().startswith("|"):
            continue
        cells = _cells(line)
        if head is None:
            head = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):  # 分隔列 |---|---|
            continue
        row = dict(zip(head, cells))
        if not any(row.values()):
            continue
        if cur["title"] == "調整紀錄":
            log.append(row)
            continue
        status = row.get("狀態", "") or "待處理"
        cur["items"].append({
            "id": row.get("#", ""), "title": row.get("問題", ""), "now": row.get("目前狀況", ""),
            "idea": next((v for k, v in row.items() if k.startswith("可能方向")), ""),
            "config": row.get("相關設定", ""), "status": status,
            "done": status.startswith("✅") or "已解決" in status,
        })
    items = [i for s in sections for i in s["items"]]
    return {"sections": [s for s in sections if s["items"]], "log": log, "updated": updated,
            "open": sum(not i["done"] for i in items), "done": sum(i["done"] for i in items)}
