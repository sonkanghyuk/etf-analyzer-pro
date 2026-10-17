@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"
if not exist ".venv\Scripts\pythonw.exe" (
  echo 아직 설치가 안 됐어요. 먼저 설치하기.bat 를 더블클릭해 주세요.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m clipora_shorts.gui %*
