"""資料來源：FRED API 與席勒（Robert Shiller）美股資料。"""
from __future__ import annotations

import io
import re
import time

import requests
import xlrd

FRED_BASE = "https://api.stlouisfed.org/fred"
UA = {"User-Agent": "us-business-cycle-tracker/1.0"}


class SourceError(Exception):
    pass


def _get(url: str, params: dict | None = None, tries: int = 3, timeout: int = 60) -> requests.Response:
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 429:  # FRED 限流：每分鐘 120 次
                time.sleep(20)
                continue
            if 400 <= r.status_code < 500:  # 參數或金鑰錯誤：重試也沒用，直接回報 FRED 的說明
                try:
                    detail = r.json().get("error_message", "")
                except ValueError:
                    detail = r.text[:200]
                raise SourceError(f"HTTP {r.status_code}：{detail or r.reason}")
            r.raise_for_status()
            return r
        except SourceError:
            raise
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (i + 1))
    # 錯誤訊息不能帶出 API 金鑰
    msg = re.sub(r"api_key=[^&\s]+", "api_key=***", str(last))
    raise SourceError(msg)


# ── FRED ────────────────────────────────────────────────
def fred_observations(series_id: str, api_key: str, start: str) -> list[tuple[str, float]]:
    """回傳 [(YYYY-MM-DD, 數值), ...]；FRED 以 "." 表示缺值，略過。"""
    r = _get(f"{FRED_BASE}/series/observations", {
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "observation_start": start,
    })
    rows = []
    for o in r.json().get("observations", []):
        if o["value"] not in (".", ""):
            rows.append((o["date"], float(o["value"])))
    if not rows:
        raise SourceError(f"{series_id} 沒有資料")
    return rows


def fred_series_info(series_id: str, api_key: str) -> dict:
    r = _get(f"{FRED_BASE}/series", {"series_id": series_id, "api_key": api_key, "file_type": "json"})
    s = r.json()["seriess"][0]
    return {k: s.get(k) for k in (
        "id", "title", "frequency", "units", "seasonal_adjustment",
        "observation_start", "observation_end", "last_updated", "notes")}


# ── 席勒資料 ────────────────────────────────────────────
def shiller_workbook_url(page: str, fallback: str) -> str:
    """shillerdata.com 的檔案網址含變動的 ID，每次從首頁找最新連結。"""
    try:
        html = _get(page, tries=2).text
        m = re.search(r'(?:https?:)?//[^"\'\s>]+/ie_data\.xls[^"\'\s>]*', html)
        if m:
            url = m.group(0)
            return "https:" + url if url.startswith("//") else url
    except SourceError:
        pass
    return fallback


def shiller_monthly(page: str, fallback: str) -> tuple[str, dict[str, list[tuple[str, float]]]]:
    """回傳 (實際使用的網址, {欄位名稱: [(YYYY-MM-01, 數值), ...]})。"""
    url = shiller_workbook_url(page, fallback)
    content = _get(url, timeout=120).content
    try:
        sheet = xlrd.open_workbook(file_contents=content).sheet_by_name("Data")
    except Exception as e:  # 檔案格式改變
        raise SourceError(f"席勒資料檔無法解析：{e}")

    header_row = None
    for i in range(min(20, sheet.nrows)):
        if sheet.cell_value(i, 0) == "Date":
            header_row = i
            break
    if header_row is None:
        raise SourceError("席勒資料檔找不到 Date 欄位")
    headers = [str(h).strip() for h in sheet.row_values(header_row)]

    out: dict[str, list[tuple[str, float]]] = {h: [] for h in headers if h}
    for i in range(header_row + 1, sheet.nrows):
        row = sheet.row_values(i)
        d = row[0]
        if not isinstance(d, float):
            continue
        # 日期格式 1871.01；十月寫成 1871.1，所以要四捨五入到兩位小數
        year = int(d)
        month = int(round((d - year) * 100))
        if not 1 <= month <= 12:
            continue
        date = f"{year:04d}-{month:02d}-01"
        for h, v in zip(headers, row):
            if h and h != "Date" and isinstance(v, float):
                out[h].append((date, v))
    return url, out
