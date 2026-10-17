#!/bin/bash
# Clipora Shorts 설치 (macOS) — 더블클릭하면 터미널에서 실행됩니다.
cd "$(dirname "$0")" || exit 1
set -e
echo "=== Clipora Shorts 설치 (처음 한 번만) ==="
if ! command -v brew >/dev/null; then
  echo "Homebrew가 필요해요. https://brew.sh 의 안내대로 설치한 뒤 다시 실행해 주세요."
  read -r -p "Enter를 누르면 닫혀요" _; exit 1
fi
# 기본 ffmpeg에는 자막(libass)이 빠져 있어 ffmpeg-full을 씁니다.
if [ ! -x "$(brew --prefix)/opt/ffmpeg-full/bin/ffmpeg" ]; then
  echo "[1/4] ffmpeg-full 설치 중..."
  brew install ffmpeg-full || true
fi
[ -x "$(brew --prefix)/opt/ffmpeg-full/bin/ffmpeg" ] || { echo "ffmpeg-full 설치에 실패했어요."; exit 1; }
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null && "$c" -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  echo "[2/4] Python 설치 중..."
  brew install python@3.12 python-tk@3.12
  PY="$(brew --prefix)/bin/python3.12"
fi
echo "[2/4] Python: $PY"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
echo "[3/4] 필요한 프로그램 설치 중 (처음엔 5분 정도)..."
.venv/bin/python -m pip install --quiet --disable-pip-version-check --upgrade pip
.venv/bin/python -m pip install --quiet --disable-pip-version-check ".[face]"
if [ -z "$CLIPORA_NONINTERACTIVE" ]; then
  read -r -p "Claude API 키 (없으면 Enter): " KEY
  if [ -n "$KEY" ]; then
    .venv/bin/python -c "import sys; from clipora_shorts import config; d = config.load(); d['anthropic_api_key'] = sys.argv[1].strip(); config.save(d)" "$KEY"
  fi
fi
echo "[4/4] 샘플 영상으로 확인 중..."
.venv/bin/python -m clipora_shorts --demo --quality fast
echo "설치 완료! 숏폼만들기.command 를 더블클릭하세요."
[ -n "$CLIPORA_NONINTERACTIVE" ] || read -r -p "Enter를 누르면 닫혀요" _
