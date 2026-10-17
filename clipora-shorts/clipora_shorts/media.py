"""ffmpeg / ffprobe 호출."""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# 자막을 입히려면 libass가 포함된 ffmpeg가 필요합니다.
# macOS Homebrew의 기본 ffmpeg(9.x~)에는 빠져 있어 ffmpeg-full을 우선 찾습니다.
EXTRA_DIRS = [
    "/opt/homebrew/opt/ffmpeg-full/bin",
    "/usr/local/opt/ffmpeg-full/bin",
]

INSTALL_HINT = (
    "ffmpeg를 찾을 수 없어요. 설치 후 다시 실행해 주세요.\n"
    "  Windows: winget install Gyan.FFmpeg\n"
    "  macOS:   brew install ffmpeg-full\n"
    "  Ubuntu:  sudo apt install ffmpeg"
)


class MediaError(Exception):
    pass


@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int
    has_audio: bool


_tools: dict[str, str] = {}


def tool(name: str) -> str:
    """ffmpeg/ffprobe 실행 파일 경로. CLIPORA_FFMPEG_DIR > ffmpeg-full > PATH 순서."""
    if name not in _tools:
        dirs = [os.environ.get("CLIPORA_FFMPEG_DIR", "")] + EXTRA_DIRS
        names = [name + ".exe", name] if sys.platform.startswith("win") else [name]
        found = next((str(Path(d) / n) for d in dirs if d for n in names if (Path(d) / n).is_file()), None)
        _tools[name] = found or shutil.which(name) or name
    return _tools[name]


def require_tools() -> None:
    if not shutil.which(tool("ffmpeg")) or not shutil.which(tool("ffprobe")):
        raise MediaError(INSTALL_HINT)
    filters = subprocess.run([tool("ffmpeg"), "-hide_banner", "-filters"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
    if not any(line.split()[1:2] == ["ass"] for line in filters.splitlines() if line.strip()):
        hint = "brew install ffmpeg-full" if sys.platform == "darwin" else "libass가 포함된 ffmpeg 빌드를 설치해 주세요 (Windows: winget install Gyan.FFmpeg)"
        raise MediaError(f"지금 ffmpeg({tool('ffmpeg')})에는 자막 기능(libass)이 없어요.\n  {hint}")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    if cmd and cmd[0] in ("ffmpeg", "ffprobe"):
        cmd = [tool(cmd[0])] + cmd[1:]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise MediaError(f"ffmpeg 실행 실패:\n{tail}")


def probe(path: Path) -> VideoInfo:
    proc = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise MediaError(f"영상 정보를 읽지 못했어요: {path}\n{proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if not video:
        raise MediaError("영상 트랙이 없는 파일이에요")
    width, height = int(video["width"]), int(video["height"])
    # 세로로 찍은 휴대폰 영상은 회전 정보만 붙어 있는 경우가 많습니다.
    rotation = abs(int(video.get("tags", {}).get("rotate", 0) or 0))
    for side in video.get("side_data_list", []):
        rotation = abs(int(side.get("rotation", rotation) or 0))
    if rotation in (90, 270):
        width, height = height, width
    return VideoInfo(
        duration=float(data["format"].get("duration") or video.get("duration") or 0),
        width=width,
        height=height,
        has_audio=any(s.get("codec_type") == "audio" for s in data["streams"]),
    )


def extract_audio(src: Path, dst: Path, start: float = 0.0, end: float | None = None) -> None:
    """Whisper 입력용 16kHz 모노 WAV."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}"]
    if end is not None:
        cmd += ["-to", f"{end:.3f}"]
    cmd += ["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    run(cmd)
