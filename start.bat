@echo off
rem Zuplan を起動します(ダブルクリックで実行)。文字コードは Shift_JIS(日本語版Windowsの標準)。
rem ブラウザが自動で開きます。
rem 止めるときは、この黒い画面で Ctrl+C を押すか、画面を閉じてください。
rem 引数はそのまま渡します。例: start.bat --port 8080 / start.bat examples\ai_agent.fc
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo [Zuplan] uv が見つかりません。次のページの手順でインストールしてから、もう一度実行してください。
  echo          https://docs.astral.sh/uv/getting-started/installation/
  pause
  exit /b 1
)

rem 引数なしで、すでに起動している場合は、画面を開くだけにする
if "%~1"=="" (
  netstat -ano | findstr /r /c:"127.0.0.1:8000 .*LISTENING" /c:"0.0.0.0:8000 .*LISTENING" >nul
  if not errorlevel 1 (
    echo [Zuplan] すでに起動しています。ブラウザで開きます: http://127.0.0.1:8000/
    start "" "http://127.0.0.1:8000/"
    exit /b 0
  )
)

title Zuplan
echo [Zuplan] 起動しています... 止めるときは Ctrl+C を押してください。
uv run zuplan --serve %*
if errorlevel 1 (
  echo.
  echo [Zuplan] 起動できませんでした。上のメッセージを確認してください。
  pause
)
