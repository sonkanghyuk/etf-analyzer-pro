"""FFmpeg/ffprobe 호출. 모든 명령은 인자 배열로 실행한다(셸 문자열 연결 금지)."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable

from . import config
from .errors import StudioError

_popen_kwargs: dict = {}
if hasattr(subprocess, "CREATE_NO_WINDOW"):
    _popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]


def require_ffmpeg() -> tuple[str, str]:
    ff, fp = config.ffmpeg_path(), config.ffprobe_path()
    if not ff or not fp:
        raise StudioError("FFMPEG_MISSING")
    return ff, fp


def ffmpeg_version() -> str | None:
    ff = config.ffmpeg_path()
    if not ff:
        return None
    try:
        out = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=10, **_popen_kwargs)
        return out.stdout.splitlines()[0] if out.stdout else None
    except Exception:
        return None


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _parse_rate(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            return float(num) / float(den) if float(den) else None
        except ValueError:
            return None
    try:
        return float(rate)
    except ValueError:
        return None


def probe(path: Path) -> dict:
    """실제 미디어를 검사한다. 확장자는 신뢰하지 않는다."""
    _, fp = require_ffmpeg()
    cmd = [fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace", **_popen_kwargs)
    except subprocess.TimeoutExpired as e:
        raise StudioError("TIMEOUT", "ffprobe") from e
    if out.returncode != 0:
        raise StudioError("MEDIA_INVALID", out.stderr.strip()[-300:])
    try:
        data = json.loads(out.stdout or "{}")
    except json.JSONDecodeError as e:
        raise StudioError("MEDIA_INVALID", "ffprobe JSON") from e
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    duration = None
    for candidate in (fmt.get("duration"), (video or {}).get("duration")):
        try:
            if candidate is not None:
                duration = float(candidate)
                break
        except ValueError:
            pass
    info = {
        "has_video": video is not None,
        "has_audio": audio is not None,
        "duration_ms": int(round(duration * 1000)) if duration else None,
        "width": int(video["width"]) if video and video.get("width") else None,
        "height": int(video["height"]) if video and video.get("height") else None,
        "fps": _parse_rate((video or {}).get("avg_frame_rate")) or _parse_rate((video or {}).get("r_frame_rate")),
        "vcodec": (video or {}).get("codec_name"),
        "acodec": (audio or {}).get("codec_name"),
        "pix_fmt": (video or {}).get("pix_fmt"),
        "audio_sample_rate": int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        "format_name": fmt.get("format_name"),
        "size": int(fmt["size"]) if fmt.get("size") else None,
        "rotation": None,
    }
    if video:
        for sd in video.get("side_data_list", []) or []:
            if "rotation" in sd:
                info["rotation"] = sd["rotation"]
        tags = video.get("tags") or {}
        if "rotate" in tags:
            info["rotation"] = tags["rotate"]
    return info


def validate_source(info: dict) -> None:
    if not info.get("has_video"):
        raise StudioError("MEDIA_NO_VIDEO")
    if not info.get("duration_ms") or not info.get("width"):
        raise StudioError("MEDIA_INVALID", "길이 또는 해상도 없음")
    if info["duration_ms"] > config.MAX_SOURCE_MINUTES * 60_000:
        raise StudioError("MEDIA_TOO_LONG")


def decode_check(path: Path, seconds: float = 2.0) -> None:
    """앞부분을 실제로 디코딩해 손상 여부를 확인한다."""
    ff, _ = require_ffmpeg()
    cmd = [ff, "-v", "error", "-xerror", "-t", str(seconds), "-i", str(path), "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace", **_popen_kwargs)
    if out.returncode != 0:
        raise StudioError("MEDIA_INVALID", out.stderr.strip()[-300:])


def thumbnail(path: Path, out_path: Path, at_ms: int, width: int = 480) -> Path | None:
    ff, _ = require_ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ff, "-y", "-v", "error", "-ss", f"{at_ms / 1000:.3f}", "-i", str(path), "-frames:v", "1",
           "-vf", f"scale={width}:-2", str(out_path)]
    out = subprocess.run(cmd, capture_output=True, timeout=60, **_popen_kwargs)
    return out_path if out.returncode == 0 and out_path.exists() else None


def extract_frame(path: Path, out_path: Path, at_s: float) -> Path:
    ff, _ = require_ffmpeg()
    cmd = [ff, "-y", "-v", "error", "-ss", f"{at_s:.3f}", "-i", str(path), "-frames:v", "1", str(out_path)]
    subprocess.run(cmd, capture_output=True, timeout=60, check=True, **_popen_kwargs)
    return out_path


_SIL_START = re.compile(r"silence_start: (-?[0-9.]+)")
_SIL_END = re.compile(r"silence_end: (-?[0-9.]+)")


def detect_silence(path: Path, start_ms: int, end_ms: int, noise_db: float, min_ms: int) -> list[tuple[int, int]]:
    """원본 시간(ms) 기준 무음 구간 목록."""
    ff, _ = require_ffmpeg()
    dur = (end_ms - start_ms) / 1000
    cmd = [ff, "-v", "info", "-ss", f"{start_ms / 1000:.3f}", "-t", f"{dur:.3f}", "-i", str(path), "-vn",
           "-af", f"silencedetect=noise={noise_db}dB:d={min_ms / 1000:.3f}", "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace", **_popen_kwargs)
    ranges: list[tuple[int, int]] = []
    current: float | None = None
    for line in out.stderr.splitlines():
        m = _SIL_START.search(line)
        if m:
            current = max(0.0, float(m.group(1)))
            continue
        m = _SIL_END.search(line)
        if m and current is not None:
            ranges.append((start_ms + int(round(current * 1000)), start_ms + int(round(float(m.group(1)) * 1000))))
            current = None
    if current is not None:
        ranges.append((start_ms + int(round(current * 1000)), end_ms))
    return [(max(start_ms, a), min(end_ms, b)) for a, b in ranges if b > a]


class ProcessHandle:
    """취소 가능한 FFmpeg 프로세스 실행기."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.canceled = threading.Event()

    def cancel(self) -> None:
        self.canceled.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass


def run_ffmpeg(args: list[str], expected_out_ms: int | None, on_progress: Callable[[float], None] | None,
               handle: ProcessHandle | None = None, log_lines: list[str] | None = None) -> int:
    """-progress 출력으로 실제 진행률을 보고한다. 반환값은 종료 코드."""
    ff, _ = require_ffmpeg()
    cmd = [ff, "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"] + args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **_popen_kwargs)
    if handle:
        handle.proc = proc
        if handle.canceled.is_set():
            handle.cancel()
    stderr_tail: list[str] = []

    def _drain_err() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line.rstrip())
            if len(stderr_tail) > 200:
                del stderr_tail[:50]

    t = threading.Thread(target=_drain_err, daemon=True)
    t.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                us = int(line.split("=", 1)[1])
            except ValueError:
                continue
            if expected_out_ms and on_progress:
                on_progress(max(0.0, min(0.999, (us / 1000) / expected_out_ms)))
    proc.wait()
    t.join(timeout=5)
    if log_lines is not None:
        log_lines.extend(stderr_tail[-60:])
    return proc.returncode
