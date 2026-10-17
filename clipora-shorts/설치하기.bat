@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Clipora Shorts 설치
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"

echo.
echo ================================================
echo    Clipora Shorts 설치 - 처음 한 번만 하면 돼요
echo ================================================
echo.

call :findpy
if not defined PY (
  echo [1/5] Python 설치 중입니다. 몇 분 걸릴 수 있어요...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  call :findpy
)
if not defined PY (
  echo.
  echo Python을 자동으로 설치하지 못했어요.
  echo https://www.python.org/downloads/ 에서 설치한 뒤 이 파일을 다시 실행해 주세요.
  echo 설치 화면에서 Add python.exe to PATH 를 꼭 체크해 주세요.
  goto :fail
)
echo [1/5] Python 확인: !PY!

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [2/5] ffmpeg 설치 중입니다...
  winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo.
  echo ffmpeg를 찾지 못했어요. 이 창을 닫고 설치하기.bat 를 한 번 더 실행해 주세요.
  goto :fail
)
echo [2/5] ffmpeg 확인

if not exist ".venv\Scripts\python.exe" (
  echo [3/5] 실행 환경 만드는 중...
  "!PY!" -m venv .venv
  if errorlevel 1 goto :fail
)
echo [4/5] 필요한 프로그램 설치 중입니다. 처음엔 5분 정도 걸려요...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install ".[face]" --quiet --disable-pip-version-check
if errorlevel 1 goto :fail

if not defined CLIPORA_NONINTERACTIVE (
  echo.
  echo Claude API 키가 있으면 붙여넣고 Enter 를 누르세요.
  echo 없으면 그냥 Enter - 나중에 프로그램 창에서 넣어도 돼요.
  set "KEY="
  set /p "KEY=API 키: "
  if defined KEY ".venv\Scripts\python.exe" -c "import sys; from clipora_shorts import config; d = config.load(); d['anthropic_api_key'] = sys.argv[1].strip(); config.save(d)" "!KEY!"
)

echo.
echo [5/5] 샘플 영상으로 잘 되는지 확인하는 중...
".venv\Scripts\python.exe" -m clipora_shorts --demo --quality fast
if errorlevel 1 goto :fail

echo.
echo ================================================
echo    설치 완료!  숏폼만들기.bat 를 더블클릭하세요.
echo    영상 파일을 숏폼만들기.bat 위로 끌어다 놓아도 돼요.
echo ================================================
if not defined CLIPORA_NONINTERACTIVE pause
exit /b 0

:fail
echo.
echo 설치 중 문제가 생겼어요. 위 메시지를 캡처해서 알려 주세요.
if not defined CLIPORA_NONINTERACTIVE pause
exit /b 1

:findpy
set "PY="
for %%V in (314 313 312 311 310) do (
  if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
  if not defined PY if exist "%ProgramFiles%\Python%%V\python.exe" set "PY=%ProgramFiles%\Python%%V\python.exe"
)
if defined PY goto :eof
for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2^>nul') do set "PY=%%i"
if defined PY goto :eof
for /f "delims=" %%i in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do (
  if not defined PY "%%i" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=%%i"
)
goto :eof
