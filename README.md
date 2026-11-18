# 美國景氣循環儀表板

每天台灣時間早上 8:00 自動抓取美國景氣指標，更新網頁儀表板，電腦和手機都能看。

- 儀表板網址：https://janine1217.github.io/us-business-cycle-tracker/
- 需求文件：`Intelligence/05. 美國景氣追蹤/us_business_cycle_tracker_prompt.md`
- 資料查證報告：[docs/資料查證報告.md](docs/資料查證報告.md)
- 回測報告：[docs/回測報告.md](docs/回測報告.md)
- 待調整事項：[docs/待調整事項.md](docs/待調整事項.md)

> 僅供參考，非投資建議。

## 開發進度

| 階段 | 內容 | 狀態 |
|---|---|---|
| 1 | 資料查證、抓取、歷史資料庫 | ✅ 完成 |
| 2 | 儀表板（指標總表＋趨勢圖）、每日自動更新 | ✅ 完成 |
| 3 | 趨勢判斷（T1–T7）、特殊型態、階段判定、轉折訊號 | ✅ 完成（規則待第 5 階段回測調整） |
| 4 | Email 提醒、系統異常通知 | ✅ 完成 |
| 5 | 回測與參數調整 | ✅ 完成（報告：[docs/回測報告.md](docs/回測報告.md)，每日自動更新） |

## 第一次設定（只需做一次）

### 1. 把 FRED 金鑰放進 GitHub Secrets
1. 打開 https://github.com/Janine1217/us-business-cycle-tracker
2. 上方 **Settings** → 左側 **Secrets and variables** → **Actions**
3. 按 **New repository secret**
   - Name：`FRED_API_KEY`
   - Secret：貼上 FRED 金鑰（和電腦上 `.env` 檔裡的一樣）
4. 按 **Add secret**

### 1-2. 設定 Email 提醒（同一個頁面，再新增 2 個 Secret）
| Name | Secret |
|---|---|
| `SMTP_USER` | 寄信用的 Gmail 地址 |
| `SMTP_PASSWORD` | Gmail「應用程式密碼」（16 碼，不是登入密碼） |
| `MAIL_TO`（選填） | 收件人，多個用逗號分隔；不加就寄給 `SMTP_USER` 自己 |

取得 Gmail 應用程式密碼：Google 帳戶 → **安全性** → 開啟**兩步驟驗證** → 搜尋「**應用程式密碼**」→ 建立一組 → 複製 16 碼。

什麼時候會收到信：
- 轉折提醒：新訊號、訊號等級升級或降級、進入新階段、特殊訊號、訊號解除。同一個訊號持續、等級不變時不重複寄。
- 系統異常：每日排程連續失敗 2 次，或抓資料連續 2 次有超過一半失敗（次數在 `config.yaml` 的 `failure_alert_after_runs`）。
- 寄信失敗（例如 Secret 還沒設定）時，變化會保留，設定好後下次排程一起寄；超過 7 天的舊變化不再補寄。

### 2. 開啟 GitHub Pages
1. 同一個 **Settings** → 左側 **Pages**
2. **Build and deployment** 的 **Source** 選 **GitHub Actions**

### 3. 上傳程式
用 GitHub Desktop：左下角輸入說明 → **Commit to main** → 上方 **Push origin**。
上傳後會自動執行一次更新，大約 2–3 分鐘後儀表板網址就能開啟。

### 4. 加到手機主畫面
- iPhone（Safari）：開啟儀表板網址 → 下方「分享」按鈕 → **加入主畫面**
- Android（Chrome）：開啟儀表板網址 → 右上角 ⋮ → **加到主畫面**

## 日常使用

- **不用做任何事**：每天 8:00 自動更新。
- **手動更新一次**：GitHub 網頁 → **Actions** → 左側「每日更新儀表板」→ **Run workflow**。
- **測試 Email 設定**：同上按 **Run workflow** 時，勾選「寄一封測試提醒信」再按綠色的 **Run workflow**。幾分鐘內收到主旨開頭為「[測試]」的信就代表設定正確；沒寄出時這次執行會顯示紅色 ✕。
- **在 GitHub Desktop 修改之前**：先按上方 **Fetch origin** / **Pull origin**，因為系統每天會自動存入新資料。
- **登記政府刺激措施**：編輯 `config.yaml` 最下方的 `stimulus:`，照範例格式加一行，Commit 並 Push。
- **調整參數或門檻**：都在 `config.yaml`，不需要改程式。

## 在自己電腦上執行（選用）

```
pip install -r requirements.txt
python run.py verify   # 查證所有 FRED 代碼
python run.py fetch    # 抓資料
python run.py build    # 產生 site/index.html
python run.py preview-email   # 產生示範提醒信 cache/email_preview.html（不寄出）
python run.py test-email      # 寄一封測試提醒信
```

本機需在 `.env` 填入 `FRED_API_KEY`；要寄信再填 `SMTP_USER`、`SMTP_PASSWORD`（參考 `.env.example`）。

## 資料夾說明

| 位置 | 內容 |
|---|---|
| `config.yaml` | 指標、參數、門檻、Email 設定、刺激措施登記 |
| `data/series/` | 每個指標的歷史資料（CSV，可用 Excel 開啟） |
| `data/status.json` | 每個指標最後成功更新的時間、錯誤紀錄 |
| `data/signal_state.json`、`data/signal_log.csv` | 每日執行時的景氣階段與轉折訊號紀錄（只有雲端執行會寫入） |
| `tracker/` | 程式 |
| `web/` | 儀表板版面 |
| `docs/` | 查證報告、回測報告（回測報告每天隨資料自動更新） |
