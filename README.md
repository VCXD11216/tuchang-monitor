# 土場邊坡監測網站（靜態版 / GitHub Pages）

原本跑在伺服器上的 Django + MySQL 監測網站，改成**不需要任何伺服器**的架構：
GitHub Actions 每小時自動抓資料 → 產生靜態 JSON → GitHub Pages 直接呈現。

原伺服器壞掉後，這個版本完全不依賴它——三種資料全部從外部來源重新抓取。

---

## 一、運作方式

```
GitHub Actions（每小時排程）
   │  scripts/build_data.py
   ├─ GNSS 位移 ← rmdgnss.com 遠端 MySQL（算日平均，含 HMove 校正）
   ├─ 時雨量   ← 白蘭站歷史 CSV 打底 + CWA 開放資料 API 續抓
   ├─ 地震     ← USGS Earthquake API（篩選會影響土場的事件）
   └─ 產生 data/*.json → commit 回 repo
        │
        ▼
GitHub Pages（靜態網站）
   index.html（Chart.js）讀 data/*.json 畫圖
```

- **有效累積雨量 (ECR)** 和**地震震度估算**都是前端 JavaScript 即時計算，不需要後端。
- 時雨量的歷史資料存在 `data/rainfall_hourly.json`（由 `土場雨量資料/` 的 CODIS CSV 打底），
  之後每小時由 CWA API 累加。CSV 也一併保存在 repo，隨時可重建歷史。

## 二、檔案結構

```
土場邊坡監測網站/
├── index.html                  前端儀表板（Chart.js，讀靜態 JSON）
├── data/                       ← Actions 自動產生並 commit
│   ├── gnss.json               GNSS 日平均位移
│   ├── rainfall_hourly.json    白蘭站時雨量（歷史 + 續抓）
│   ├── rainfall.json           白蘭站日雨量
│   ├── earthquake.json         地震事件
│   └── summary.json            摘要卡片
├── scripts/build_data.py       資料產生器
├── 土場雨量資料/               歷史雨量 CSV（時雨量打底來源）
├── requirements.txt            Python 套件
├── .github/workflows/update.yml  每小時排程
├── .nojekyll                   讓 Pages 原樣輸出
└── README.md
```

---

## 三、第一次部署（做一次就好）

### 1. 建立 GitHub repo 並上傳
在這個資料夾開終端機（PowerShell），把 `你的帳號` / `repo名稱` 換成實際的：

```bash
git init
git add .
git commit -m "土場邊坡監測靜態網站初版"
git branch -M main
git remote add origin https://github.com/你的帳號/repo名稱.git
git push -u origin main
```
> repo 請設為 **public**（免費帳號的 GitHub Pages 需要 public）。

### 2. 設定密鑰（Secrets）
GitHub repo 頁面 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，
新增兩個：

| Name | Value |
|------|-------|
| `RMDGNSS_PASSWORD` | rmdgnss.com 的 GNSS 資料庫密碼 |
| `CWA_API_KEY` | 中央氣象署開放資料平台 API Key |

> 密碼**只**放在這裡（加密），程式碼裡沒有明碼。就算 repo 公開也看不到。

### 3. 開啟 GitHub Pages
**Settings** → **Pages** → Source 選 **Deploy from a branch** → Branch 選 **main** / **/(root)** → Save。
幾分鐘後網站會上線於：`https://你的帳號.github.io/repo名稱/`

### 4. 手動跑一次確認
**Actions** 分頁 → 左邊「更新監測資料」→ **Run workflow**。
綠色勾勾代表成功；此時 `data/` 會被更新並自動部署。

---

## 四、日常維護

- **完全自動**：之後每小時自動更新，不用管。
- **改網頁外觀 / 圖表**：改 `index.html`，push 上去即可（改圖表設定改 `SOURCES` 那段）。
- **改資料抓取邏輯**：改 `scripts/build_data.py`。
- **本機測試**：
  ```bash
  # PowerShell：設環境變數後產生 JSON
  $env:RMDGNSS_PASSWORD="密碼"; $env:CWA_API_KEY="金鑰"
  python scripts/build_data.py
  # 起本地伺服器預覽（不能直接雙擊 index.html，fetch 會被瀏覽器擋）
  python -m http.server 8000
  # 開 http://localhost:8000
  ```

## 五、注意事項

- **排程休眠**：GitHub 規定 repo 若 60 天沒有「人為」活動，排程會自動暫停。
  久久沒動時，到 Actions 手動 Run 一次，或隨便 push 一個小改動即可喚醒。
- **日雨量**由時雨量逐時加總得出（與 CODIS 日報表可能有極小差異，不影響判讀）。
- **時間**一律換算台灣時間（Actions runner 是 UTC，程式已固定 +8）。
