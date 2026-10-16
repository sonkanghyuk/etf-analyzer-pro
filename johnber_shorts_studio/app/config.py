"""앱 전역 설정. 환경변수(.env)에서 읽고, 비밀값은 로그·응답에 노출하지 않는다."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "존버나드 쇼츠 스튜디오"
APP_NAME_EN = "Johnber Shorts Studio"
SCHEMA_VERSION = 2


def _load_dotenv() -> None:
    env_path = APP_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def env_float(name: str) -> float | None:
    value = env(name)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


DATA_DIR = Path(env("JSS_DATA_DIR", str(APP_ROOT / "data"))).resolve()
SOURCES_DIR = DATA_DIR / "sources"       # 업로드된 원본 보존본 (수정 금지)
CACHE_DIR = DATA_DIR / "cache"           # 전사용 오디오·썸네일·오버레이 PNG
OUTPUT_DIR = DATA_DIR / "outputs"        # 완성 MP4
TMP_DIR = DATA_DIR / "tmp"               # 렌더링 임시 파일
ASSETS_DIR = DATA_DIR / "assets"         # 사용자 로고·배경
FONTS_USER_DIR = DATA_DIR / "fonts"      # 사용자가 추가한 글꼴
DB_PATH = DATA_DIR / "studio.sqlite3"
BUNDLED_FONTS_DIR = APP_ROOT / "fonts"

HOST = env("JSS_HOST", "127.0.0.1")
PORT = int(env("JSS_PORT", "8765"))

MAX_UPLOAD_BYTES = int(float(env("JSS_MAX_UPLOAD_GB", "8")) * 1024**3)
MAX_SOURCE_MINUTES = float(env("JSS_MAX_SOURCE_MINUTES", "180"))

# 전사(로컬)
WHISPER_MODEL = env("JSS_WHISPER_MODEL", "small")  # 모델 이름 또는 로컬 폴더 경로
WHISPER_DEVICE = env("JSS_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = env("JSS_WHISPER_COMPUTE", "int8")

# AI 추천(외부 API) — 키가 없으면 '미연결'
ANTHROPIC_MODEL = env("JSS_ANTHROPIC_MODEL", "claude-opus-5-5")
ANTHROPIC_EFFORT = env("JSS_ANTHROPIC_EFFORT", "medium")
# 요금은 사용자가 공식 요금표를 확인해 넣는다. 비어 있으면 '비용 미확인'.
PRICE_INPUT_PER_MTOK = env_float("JSS_PRICE_INPUT_PER_MTOK")
PRICE_OUTPUT_PER_MTOK = env_float("JSS_PRICE_OUTPUT_PER_MTOK")


def anthropic_key_present() -> bool:
    return bool(env("ANTHROPIC_API_KEY"))


def _tool(env_name: str, exe: str) -> str | None:
    custom = env(env_name)
    if custom:
        return custom if Path(custom).is_file() else None
    return shutil.which(exe)


def ffmpeg_path() -> str | None:
    return _tool("JSS_FFMPEG", "ffmpeg")


def ffprobe_path() -> str | None:
    return _tool("JSS_FFPROBE", "ffprobe")


def ensure_dirs() -> None:
    for d in (DATA_DIR, SOURCES_DIR, CACHE_DIR, OUTPUT_DIR, TMP_DIR, ASSETS_DIR, FONTS_USER_DIR):
        d.mkdir(parents=True, exist_ok=True)


def redact(text: str) -> str:
    """로그·오류 메시지에서 API 키를 가린다."""
    key = env("ANTHROPIC_API_KEY")
    if key and key in text:
        text = text.replace(key, "***")
    import re

    return re.sub(r"sk-ant-[A-Za-z0-9_\-]{8,}", "sk-ant-***", text)
