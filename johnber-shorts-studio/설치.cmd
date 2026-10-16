@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.12가 필요합니다. https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 goto missing_ffmpeg
where ffprobe >nul 2>nul
if errorlevel 1 goto missing_ffmpeg
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements.lock
if errorlevel 1 goto failed
echo 설치 완료. 실행.cmd로 시작하세요. 선택적 AI 설치는 README를 확인하세요.
pause
exit /b 0
:missing_ffmpeg
echo FFmpeg 또는 ffprobe가 없습니다. https://ffmpeg.org/download.html 에서 설치 후 bin 폴더를 PATH에 추가하세요.
echo 새 명령 프롬프트에서 ffmpeg -version 과 ffprobe -version 을 확인하고 다시 실행하세요.
pause
exit /b 1
:failed
echo 설치에 실패했습니다. 위 오류와 README의 문제 해결을 확인하세요.
pause
exit /b 1
