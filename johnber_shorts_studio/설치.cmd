@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo [존버나드 쇼츠 스튜디오] 설치를 시작합니다.

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [오류] Python 3.10 이상이 필요합니다.
  echo   https://www.python.org/downloads/windows/ 에서 설치하고 "Add python.exe to PATH"를 체크하세요.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo 가상환경을 만듭니다...
  %PY% -m venv .venv || (echo [오류] 가상환경 생성 실패 & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo [오류] 패키지 설치 실패 - 인터넷 연결을 확인하세요 & pause & exit /b 1)

if not exist ".env" copy ".env.example" ".env" >nul

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo.
  echo [안내] FFmpeg가 없습니다. 아래 중 하나로 설치한 뒤 새 창에서 실행.cmd를 실행하세요.
  echo   1^) PowerShell 또는 명령 프롬프트: winget install --id Gyan.FFmpeg
  echo   2^) https://www.gyan.dev/ffmpeg/builds/ 에서 받아 압축을 풀고 .env의 JSS_FFMPEG / JSS_FFPROBE에 경로 지정
) else (
  echo FFmpeg 확인 완료.
)
echo.
echo 설치가 끝났습니다. 실행.cmd 를 더블클릭하세요.
pause
