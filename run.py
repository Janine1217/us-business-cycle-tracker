"""命令列入口。

  python run.py verify   用 FRED API 查證所有代碼，輸出 docs/series_metadata.md
  python run.py fetch    抓取所有序列，更新 data/series/*.csv 與 data/status.json
"""
from __future__ import annotations

import sys

from tracker.fetch import run_fetch, run_verify
from tracker.settings import DOCS_DIR, load_config, stamp

FREQ_ZH = {"Daily": "日", "Weekly": "週", "Monthly": "月", "Quarterly": "季"}


def cmd_verify() -> None:
    rows = run_verify()
    lines = [
        "# FRED 代碼查證結果（自動產生）", "",
        f"> 產生時間：{stamp(load_config())}（台灣時間）  ",
        "> 資料來源：FRED API `fred/series`（https://fred.stlouisfed.org/docs/api/fred/series.html）", "",
        "| 代碼 | 中文名稱 | FRED 名稱 | 頻率 | 單位 | 季調 | 起始日 | 最新日期 | 最後更新 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if not r["exists"]:
            lines.append(f"| `{r['id']}` | {r['name_zh']} | ❌ 不存在或查詢失敗：{r['error']} | | | | | | |")
            continue
        freq = r["frequency"] or ""
        freq_zh = next((v for k, v in FREQ_ZH.items() if freq.startswith(k)), freq)
        lines.append(
            f"| [`{r['id']}`](https://fred.stlouisfed.org/series/{r['id']}) | {r['name_zh']} | {r['title']} | "
            f"{freq_zh} | {r['units']} | {r['seasonal_adjustment']} | {r['observation_start']} | "
            f"{r['observation_end']} | {(r['last_updated'] or '')[:10]} |")
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "series_metadata.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    bad = [r["id"] for r in rows if not r["exists"]]
    print(f"查證 {len(rows)} 個 FRED 代碼，不存在：{bad or '無'}；結果寫入 docs/series_metadata.md")


def cmd_fetch() -> None:
    res = run_fetch(sys.argv[2:] or None)
    print(f"抓取 {res['total']} 個序列，失敗 {len(res['failed'])} 個")
    for k, v in res["failed"].items():
        print(f"  ✗ {k}: {v}")
    if res["run_failed"]:
        sys.exit(1)


if __name__ == "__main__":
    commands = {"verify": cmd_verify, "fetch": cmd_fetch}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(__doc__)
        sys.exit(2)
    commands[sys.argv[1]]()
