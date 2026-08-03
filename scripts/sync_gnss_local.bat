@echo off
chcp 65001 >nul
setlocal
rem ============================================================
rem  土場 GNSS 每日同步 (在台灣/校園網路的電腦上執行)
rem  只更新 gnss.json + summary.json 並推上 GitHub。
rem  雨量/地震由 GitHub Actions 每小時自動更新,這裡不碰。
rem ============================================================

rem 切到 repo 根目錄 (本 bat 位於 scripts\ 底下,用相對路徑避免中文路徑問題)
cd /d "%~dp0.."

rem 載入本機密鑰 (scripts\secrets.local.bat,已被 .gitignore 排除,不會上傳)
if exist "%~dp0secrets.local.bat" (
  call "%~dp0secrets.local.bat"
) else (
  echo [錯誤] 找不到 scripts\secrets.local.bat
  echo 請複製 secrets.local.bat.範本 為 secrets.local.bat 並填入密碼
  exit /b 1
)

rem 先同步遠端,避免和 GitHub Actions 的自動 commit 衝突
git pull --rebase --autostash origin main

rem 只抓 GNSS (需台灣網路),產生 gnss.json + summary.json
python "%~dp0build_data.py" gnss
if errorlevel 1 (
  echo [略過] GNSS 抓取失敗 (可能目前不在校園網路),本次不推送
  exit /b 1
)

git add data/gnss.json data/summary.json
git diff --cached --quiet && ( echo 無變更,結束 & exit /b 0 )
git commit -m "chore: 本地 GNSS 每日同步"
git push
echo [完成] GNSS 已更新並推送到 GitHub
endlocal
