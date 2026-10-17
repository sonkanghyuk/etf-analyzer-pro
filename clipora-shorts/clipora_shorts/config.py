"""사용자 설정(Claude API 키, 최근 옵션)을 사용자 폴더에 저장합니다.

Windows: %APPDATA%\\Clipora\\config.json / macOS·Linux: ~/.config/clipora/config.json
"""

import json
import os
import sys
from pathlib import Path


def path() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Clipora"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "clipora"
    return base / "config.json"


def load() -> dict:
    try:
        return json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)  # API 키가 들어 있으니 본인만 읽게
    except OSError:
        pass


def apply_api_key() -> None:
    """환경 변수에 키가 없으면 저장해 둔 키를 씁니다."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        key = load().get("anthropic_api_key", "").strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
