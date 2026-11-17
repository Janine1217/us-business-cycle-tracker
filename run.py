"""命令列入口。

  python run.py verify   用 FRED API 查證所有代碼，輸出 docs/series_metadata.md
  python run.py fetch    抓取所有序列，更新 data/series/*.csv 與 data/status.json
  python run.py build    產生儀表板 site/index.html（可直接用瀏覽器開啟）
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


def cmd_build() -> None:
    import os

    from tracker.build import run_build
    # 只有雲端每日執行才寫入訊號紀錄（data/signal_log.csv），本機測試不影響紀錄
    res = run_build(record=bool(os.environ.get("GITHUB_ACTIONS")))
    print(f"儀表板已產生：site/index.html（{res['charts']} 張圖，資料 {res['size_kb']} KB）")
    print(f"目前景氣階段：{res['stage']}")
    for s in res["signals"]:
        print(f"  {s}")
    for c in res["changes"]:
        print(f"  訊號變化：{c['name']} {c['from'] or '無'} → {c['to'] or '解除'}")


if __name__ == "__main__":
    commands = {"verify": cmd_verify, "fetch": cmd_fetch, "build": cmd_build}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(__doc__)
        sys.exit(2)
    commands[sys.argv[1]]()
