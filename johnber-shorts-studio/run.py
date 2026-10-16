from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env():
    # Small .env reader: no shell execution, no interpolation, never print values.
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key,value = line.split('=',1)
            if key.strip().startswith('JOHNBER_'):
                os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))


def main():
    load_env()
    missing = [n for n in ('fastapi','uvicorn','PIL','multipart') if importlib.util.find_spec(n) is None]
    if missing:
        print('필수 Python 패키지가 없습니다. 설치.cmd 또는 pip install -r requirements.txt 실행:', ', '.join(missing))
        return 1
    for program in ('ffmpeg','ffprobe'):
        if not shutil.which(program):
            print(f'{program}가 없습니다. https://ffmpeg.org/download.html 에서 설치 후 PATH에 bin 폴더를 추가해 주세요.')
            return 1
    port = int(os.environ.get('JOHNBER_PORT','8765'))
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1',port))
        except OSError:
            print(f'{port} 포트가 사용 중입니다. 기존 앱을 종료하거나 .env의 JOHNBER_PORT를 변경하세요.')
            return 1
    print(f'존버나드 쇼츠 스튜디오: http://127.0.0.1:{port}  |  종료: Ctrl+C')
    import uvicorn
    uvicorn.run('studio.app:app',host='127.0.0.1',port=port,log_level='info',access_log=False)
    return 0


if __name__=='__main__':
    sys.exit(main())
