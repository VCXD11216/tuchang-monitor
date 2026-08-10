@echo off
chcp 65001 >nul
setlocal
rem ============================================================
rem  土場 GNSS 每日同步 (在台灣/校園網路的電腦上執行)
rem  只更新 gnss.json + summary.json 並推上 GitHub。
rem  每次執行的詳細記錄寫在 scripts\sync_gnss.log,方便排錯。
rem ============================================================
set "LOG=%~dp0sync_gnss.log"
echo ============================================================> "%LOG%"
echo 執行時間: %date% %time%>> "%LOG%"

rem 切到 repo 根目錄 (用相對路徑避免中文路徑問題)
cd /d "%~dp0.."
echo 工作目錄: %cd%>> "%LOG%"

rem 載入本機密鑰 (scripts\secrets.local.bat,已被 .gitignore 排除)
if exist "%~dp0secrets.local.bat" (
  call "%~dp0secrets.local.bat"
  echo secrets.local.bat: 已載入>> "%LOG%"
) else (
  echo [錯誤] 找不到 scripts\secrets.local.bat>> "%LOG%"
  exit /b 1
)
if defined RMDGNSS_PASSWORD (echo RMDGNSS_PASSWORD: 已設定>> "%LOG%") else (echo RMDGNSS_PASSWORD: 未設定 ^!^!>> "%LOG%")

rem 確認 python / git 可用
where python >> "%LOG%" 2>&1
where git >> "%LOG%" 2>&1

echo --- git pull --->> "%LOG%"
git pull --rebase --autostash origin main >> "%LOG%" 2>&1

echo --- build_data.py gnss --->> "%LOG%"
python "%~dp0build_data.py" gnss >> "%LOG%" 2>&1
set "BUILD_RC=%errorlevel%"
echo build 結束代碼: %BUILD_RC%>> "%LOG%"
if not "%BUILD_RC%"=="0" (
  echo [略過] GNSS 抓取失敗,本次不推送>> "%LOG%"
  exit /b 1
)

git add data/gnss.json data/summary.json >> "%LOG%" 2>&1
git diff --cached --quiet && (
  echo 無變更,結束>> "%LOG%"
  exit /b 0
)
echo --- commit ^& push --->> "%LOG%"
git commit -m "chore: 本地 GNSS 每日同步" >> "%LOG%" 2>&1
git push >> "%LOG%" 2>&1
echo push 結束代碼: %errorlevel%>> "%LOG%"
echo [完成] GNSS 已更新並推送>> "%LOG%"
endlocal
