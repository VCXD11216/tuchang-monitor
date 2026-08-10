# 土場邊坡監測網站 — 開發紀錄

## 2026-08-03/04 — 從壞掉的伺服器重建為靜態網站

### 背景
原本的監測網站是 Django + MySQL,跑在一台 HP ProLiant 伺服器（IP 140.115.61.224,
資料夾 `E:\監測儀錶板\`）。該伺服器硬體壞掉,決定**不再維護那台機器**,
把網站重建成不依賴任何自有伺服器的架構。

### 決策
- 只保留**邊坡監測**（GNSS 位移 + 雨量 + 地震）。
- 放棄 ESP32 環境感測器（ccc、database_1 的溫濕度/土壤/加速度）——那些即時 MQTT
  資料只存在壞掉的 MySQL,已無法復原,且非目前重點。
- 改用 **GitHub Actions（定時抓資料）+ GitHub Pages（靜態呈現）**,免伺服器、免費、
  24 小時在線、自帶 HTTPS,順便解決舊系統「校外連不進來」的問題。

### 關鍵發現
- 前端 `dashboard.html` 本來就是純 Chart.js,只是去 `fetch('/api/...')` 拿 JSON。
  → Django 那層只做「MySQL→JSON」,可以用「預先產生的靜態 JSON」取代,前端幾乎不用改。
- GNSS 不是手動匯入 CSV,而是 `sync_gnss.py` 從**遠端 MySQL `rmdgnss.com`**（表 g1）
  抓原始資料算日平均。→ 三種資料全部可從外部重抓,不依賴舊伺服器。
- ECR 有效累積雨量、地震震度估算**本來就是前端 JS 算的**,不需後端。

### 最終架構（混合）
`rmdgnss.com` 的 MySQL 只允許台灣/校園網路連入,GitHub 國外 IP 連不到,因此拆兩半:

- **☁️ GitHub Actions（每小時）**：抓雨量（CWA API）+ 地震（USGS API），公開 API 免機器。
  `python scripts/build_data.py rainfall earthquake`
- **💻 台灣網路的電腦（每次登入）**：抓 GNSS（rmdgnss 日平均，含 HMove 校正）。
  `scripts/sync_gnss_local.bat` → Windows 排程「土場GNSS同步」（ONLOGON）
- 兩邊各動各的 JSON 檔,用 `git pull --rebase` 交錯不衝突。
- **🌐 GitHub Pages** 讀 `data/*.json` 呈現。

### 資料來源
| 資料 | 來源 | 更新 |
|------|------|------|
| GNSS 位移 | rmdgnss.com 遠端 MySQL（表 g1，日平均） | 登入時同步 |
| 時雨量 | 白蘭站 CODIS 歷史 CSV + CWA O-A0002-001 API | 每小時 |
| 地震 | USGS Earthquake API（dist≤100km 或 M5.5+ 且 ≤200km） | 每小時 |

### 部署
- GitHub repo：`VCXD11216/tuchang-monitor`（public）
- 網站：https://vcxd11216.github.io/tuchang-monitor/
- Secrets：`RMDGNSS_PASSWORD`、`CWA_API_KEY`（加密,不進程式碼）
- 本機密鑰：`scripts/secrets.local.bat`（.gitignore,不上傳）

### 過程中解決的問題

**1. GitHub Actions 連不到 rmdgnss.com（timed out）**
→ rmdgnss 擋國外 IP。改成混合架構:GNSS 由台灣端電腦每日同步,GitHub 只跑雨量+地震。

**2. ECR「有效累積雨量」沒顯示完全（右側約 3.5 個月空白）**
→ 時雨量在 2026-05~08 初有斷層。那段原本只在壞掉伺服器的 MySQL,CSV 只到 2026-04。
→ 逆向 CODIS API 寫了 `scripts/backfill_rainfall.py`,把缺的月份補回（POST
  `codis.cwa.gov.tw/api/station`, type=report_date, stn_type=auto_C1, 站號 C1D410）。
  補完 17824 筆,ECR 顯示完整到最近。

**3. Excel 散佈圖與網頁不同**
→ 網頁有最新資料（最近位移較大、跑到更外側,軸自動放大到 ±35），Excel 是較舊的資料。

**4. 散佈圖新功能**
→ G1 Average Day 散佈圖,最近 N 天的點標紅色,加下拉選單（1/3/7/14/21/30 天），
  圖例文字隨選擇更新。

### 日常維護
- 平常全自動,不用管。
- 改網頁：改 `index.html` → `git push`，幾分鐘生效。
- 雨量又有斷層：`python scripts/backfill_rainfall.py`（自動補到本月）。
- 排程休眠：repo 60 天沒有人為 push,GitHub 會暫停自動排程,到 Actions 手動 Run 一次即可。
- 完整操作說明見 `README.md`。

## 2026-08-10 — 修正 GNSS 排程 6 天沒更新

**症狀**：GNSS 資料停在 8/4,網頁新鮮度顯示「6 天前」。排程有跑、回報成功(0x0),但資料沒更新。

**根因**：`sync_gnss_local.bat` 是 **LF(Unix)換行**(用編輯器產生的)。cmd.exe 執行 LF 換行的 .bat 會靜默失敗(尤其 `if (...)` 括號區塊),所以排程「跑了但什麼都沒做」。之前的手動更新都是直接跑 python+git、沒經過 bat,才會成功而沒察覺。

**修正**：
- 把 `scripts/*.bat` 轉成 CRLF。
- 新增 `.gitattributes`:`*.bat text eol=crlf`,確保之後 clone/checkout 永遠是 CRLF。
- bat 加上 `scripts/sync_gnss.log` 詳細記錄(已 gitignore),日後可直接看每步結果排錯。
- 診斷指令:`Get-ScheduledTaskInfo -TaskName "土場GNSS同步"` 看 LastRunTime/LastTaskResult;`schtasks` 或 `Start-ScheduledTask` 觸發後看 `scripts/sync_gnss.log`。
