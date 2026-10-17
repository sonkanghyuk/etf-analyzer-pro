@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"
if not exist ".venv\Scripts\pythonw.exe" (
  echo 아직 설치가 안 됐어요. 먼저 설치하기.bat 를 더블클릭해 주세요.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m clipora_shorts.gui %*
