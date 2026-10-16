@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [오류] 먼저 설치.cmd 를 실행하세요.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py
pause
