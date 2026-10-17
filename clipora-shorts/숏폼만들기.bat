@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
rem 경로가 길면(바탕화면 압축 풀기 등) 설치가 깨질 수 있어 실행 환경은 짧은 경로에 둡니다
set "VENV=%LOCALAPPDATA%\Clipora\venv"
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"
if not exist "%VENV%\Scripts\pythonw.exe" (
  echo 아직 설치가 안 됐어요. 먼저 설치하기.bat 를 더블클릭해 주세요.
  pause
  exit /b 1
)
start "" "%VENV%\Scripts\pythonw.exe" -m clipora_shorts.gui %*
