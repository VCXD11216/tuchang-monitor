# 土場邊坡監測網站（靜態版 / GitHub Pages）

原本跑在伺服器上的 Django + MySQL 監測網站，改成**不需要任何伺服器**的架構：
GitHub Actions 每小時自動抓資料 → 產生靜態 JSON → GitHub Pages 直接呈現。

原伺服器壞掉後，這個版本完全不依賴它——三種資料全部從外部來源重新抓取。

---

## 一、運作方式（混合架構）

GNSS 來源 `rmdgnss.com` 只允許**台灣/校園網路**連入，GitHub 的國外雲端 IP 連不到，
因此拆成兩半：雨量/地震在雲端全自動，GNSS 由台灣端電腦每天同步一次（GNSS 是日資料，一天一次就夠）。

```
☁️ GitHub Actions（每小時，公開 API，免機器）
   │  build_data.py rainfall earthquake
   ├─ 時雨量 ← 白蘭站歷史 CSV 打底 + CWA 開放資料 API 續抓
   ├─ 地震   ← USGS Earthquake API
   └─ 更新 data/rainfall*.json、earthquake.json → push

💻 台灣網路的電腦（每天一次，跑 scripts/sync_gnss_local.bat）
   │  build_data.py gnss
   ├─ GNSS ← rmdgnss.com 遠端 MySQL（日平均，含 HMove 校正）
   └─ 更新 data/gnss.json、summary.json → push
        │
        ▼
🌐 GitHub Pages（靜態網站，24 小時在線）
   index.html（Chart.js）讀 data/*.json 畫圖
```

> 兩邊各自只動自己的 JSON 檔，用 `git pull --rebase` 交錯不衝突。
> 某天電腦沒開，GNSS 就那天不更新，隔天開機自動補上（每次抓完整歷史）。

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

## 三之二、設定 GNSS 每日同步（在台灣網路的電腦上，做一次）

1. **裝 Git 與 Python**（若還沒），並把這個 repo clone 或複製到該電腦。
2. 在 `scripts\` 底下，複製 `secrets.local.bat.範本` → 改名為 `secrets.local.bat`，
   填入 `RMDGNSS_PASSWORD`（`secrets.local.bat` 已被 .gitignore 排除，不會上傳）。
3. 先手動雙擊 `scripts\sync_gnss_local.bat` 測一次，看到「已更新並推送」或「無變更」即成功。
4. 設成自動：用**工作排程器**每天（或每次登入）跑一次。PowerShell 一行搞定：
   ```powershell
   schtasks /Create /SC ONLOGON /TN "土場GNSS同步" /TR "\"完整路徑\scripts\sync_gnss_local.bat\"" /F
   ```
   （`/SC ONLOGON` = 每次登入就同步；也可用 `/SC DAILY /ST 09:00` 改成每天 9 點）

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
