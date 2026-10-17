#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "먼저 설치하기.command 를 실행해 주세요."; read -r -p "Enter" _; exit 1
fi
exec .venv/bin/python -m clipora_shorts.gui "$@"
