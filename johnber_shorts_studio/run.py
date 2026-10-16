"""존버나드 쇼츠 스튜디오 실행기: 의존성·FFmpeg·포트를 확인하고 서버를 연다."""
from __future__ import annotations

import socket
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def check() -> bool:
    ok = True
    try:
        import fastapi, uvicorn, PIL, fontTools  # noqa: F401
    except ImportError as e:
        print(f"[오류] 필요한 파이썬 패키지가 없습니다: {e.name}. 설치.cmd를 먼저 실행하세요.")
        return False
    from app import config, transcribe

    if not (config.ffmpeg_path() and config.ffprobe_path()):
        print("[오류] FFmpeg를 찾을 수 없습니다.")
        print("  - Windows: winget install --id Gyan.FFmpeg  (또는 https://www.gyan.dev/ffmpeg/builds/ 에서 받아 압축 해제)")
        print("  - 설치 후 새 창에서 다시 실행하거나, .env에 JSS_FFMPEG / JSS_FFPROBE 경로를 지정하세요.")
        ok = False
    st = transcribe.status()
    print(f"[전사] {'설치됨' if st['installed'] else '미설치'} · 모델 {st['model']} — {st['label']}")
    print(f"[AI 추천] {'연결됨(키 설정)' if config.anthropic_key_present() else '미연결(.env에 ANTHROPIC_API_KEY 없으면 수동 경로만 사용)'}")
    return ok


def port_free(host: str, port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex((host, port)) != 0


def main() -> None:
    if not check():
        input("엔터를 누르면 종료합니다...") if sys.stdin and sys.stdin.isatty() else None
        sys.exit(1)
    from app import config
    import uvicorn

    port = config.PORT
    while not port_free(config.HOST, port):
        print(f"[알림] 포트 {port}이(가) 사용 중입니다. 다음 포트를 확인합니다.")
        port += 1
        if port > config.PORT + 20:
            print("[오류] 사용할 수 있는 포트가 없습니다. .env의 JSS_PORT를 바꾸세요.")
            sys.exit(1)
    url = f"http://{config.HOST}:{port}/"
    print(f"\n{config.APP_NAME} 실행 중: {url}\n데이터 폴더: {config.DATA_DIR}\n종료하려면 이 창에서 Ctrl+C\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=config.HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
