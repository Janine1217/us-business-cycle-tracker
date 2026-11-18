"""寄信（SMTP）與「整個排程失敗」通知。

本檔只用 Python 內建模組：排程連安裝套件都失敗時，仍能寄出系統異常通知。
  python -m tracker.mailer crash   由 GitHub Actions 在排程失敗時呼叫
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import sys
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    """先讀環境變數（GitHub Secrets），本機再讀 .env。"""
    v = os.environ.get(name, "").strip()
    if v:
        return v
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return default


def _config_value(key: str, default: str = "") -> str:
    """不依賴 YAML 套件，從 config.yaml 讀單一設定值。"""
    text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    m = re.search(rf"^\s*{key}:\s*(.+?)\s*(#.*)?$", text, re.M)
    return m.group(1).strip("\"'") if m else default


def recipients() -> list[str]:
    """收件人：config.yaml 的 email.recipients ＋ Secret MAIL_TO（逗號分隔）；都沒有就寄給 SMTP_USER 自己。"""
    raw = _config_value("recipients", "[]")
    out = [x.strip().strip("\"'") for x in raw.strip("[]").split(",") if x.strip().strip("\"'")]
    out += [x.strip() for x in _env("MAIL_TO").split(",") if x.strip()]
    if not out and _env("SMTP_USER"):
        out = [_env("SMTP_USER")]
    return list(dict.fromkeys(out))


def ready() -> str | None:
    """回傳缺少的設定（None 表示可以寄信）。"""
    miss = [k for k in ("SMTP_USER", "SMTP_PASSWORD") if not _env(k)]
    return f"沒有設定 {'、'.join(miss)}" if miss else None


def send(subject: str, html: str, text: str) -> list[str]:
    problem = ready()
    if problem:
        raise RuntimeError(problem)
    to = recipients()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("景氣儀表板", _env("SMTP_USER")))
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    host, port = _env("SMTP_HOST", "smtp.gmail.com"), int(_env("SMTP_PORT", "465"))
    # Gmail 應用程式密碼常被貼成「abcd efgh ijkl mnop」，空白要拿掉
    password = _env("SMTP_PASSWORD").replace(" ", "")
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
            s.login(_env("SMTP_USER"), password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(_env("SMTP_USER"), password)
            s.send_message(msg)
    return to


def page(title: str, body: str, url: str) -> str:
    """手機好讀的 HTML 信件外框（單欄、行內樣式）。"""
    link = f'<p style="margin:24px 0 8px"><a href="{url}" style="display:inline-block;background:#1f6feb;color:#fff;text-decoration:none;padding:10px 18px;border-radius:8px;font-weight:600">開啟儀表板</a></p>' if url else ""
    return f"""<!doctype html><html lang="zh-Hant-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#f4f4f2;padding:12px">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;padding:20px;font-family:-apple-system,'Segoe UI','Noto Sans TC','Microsoft JhengHei',sans-serif;font-size:15px;line-height:1.6;color:#1a1a19">
<h1 style="font-size:19px;margin:0 0 12px">{title}</h1>
{body}
{link}
<p style="margin:16px 0 0;font-size:12px;color:#777">僅供參考，非投資建議。本信由每日排程自動寄出。</p>
</div></body></html>"""


# ── 整個排程失敗（GitHub Actions 在任何步驟失敗時呼叫）──────────────
def _previous_conclusions() -> list[str]:
    """查 GitHub 上本流程最近幾次「已完成」執行的結果（新到舊，不含這一次）。"""
    repo, token, run_id = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_RUN_ID")
    if not (repo and token):
        return []
    url = f"https://api.github.com/repos/{repo}/actions/workflows/daily.yml/runs?status=completed&per_page=10"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                               "User-Agent": "us-business-cycle-tracker"})
    with urllib.request.urlopen(req, timeout=30) as r:
        runs = json.load(r).get("workflow_runs", [])
    return [x["conclusion"] for x in runs if str(x["id"]) != run_id]


def crash() -> None:
    n = int(_config_value("failure_alert_after_runs", "2"))
    try:
        prev = _previous_conclusions()
    except Exception as e:  # noqa: BLE001
        print("查詢過去執行紀錄失敗：", e)
        prev = []
    streak = 1
    for c in prev:
        if c != "failure":
            break
        streak += 1
    print(f"排程連續失敗 {streak} 次（門檻 {n} 次）")
    if streak != n:  # 只在剛好達到門檻時寄一次，之後持續失敗不重複寄
        return
    repo, run_id = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}" if repo else ""
    body = (f"<p>每日更新排程已<b>連續失敗 {streak} 次</b>，儀表板資料可能沒有更新。</p>"
            f"<p>請到 GitHub 查看這次執行的錯誤訊息：<br><a href=\"{run_url}\">{run_url}</a></p>"
            "<p style=\"color:#555\">常見原因：FRED 金鑰失效、GitHub Secrets 被刪除、資料來源網站暫時無法連線。</p>")
    subject = f"[景氣儀表板｜系統異常] 每日排程連續失敗 {streak} 次"
    try:
        to = send(subject, page("系統異常通知", body, _config_value("dashboard_url")),
                  f"每日更新排程已連續失敗 {streak} 次。請查看：{run_url}")
        print("已寄出系統異常通知給", len(to), "位收件人")
    except Exception as e:  # noqa: BLE001
        print("系統異常通知寄送失敗：", e)


if __name__ == "__main__":
    if sys.argv[1:] == ["crash"]:
        crash()
    else:
        print(__doc__)
