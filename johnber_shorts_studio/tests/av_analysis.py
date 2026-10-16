"""출력 MP4의 실제 오디오·영상 이벤트를 측정한다(테스트 전용)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np


def audio_samples(path: Path, rate: int = 48000) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def audio_onsets(path: Path, threshold: float = 0.4, min_gap_s: float = 0.3, rate: int = 48000) -> list[float]:
    x = np.abs(audio_samples(path, rate))
    idx = np.nonzero(x > threshold)[0]
    onsets: list[float] = []
    last = -1e9
    for i in idx:
        t = i / rate
        if t - last > min_gap_s:
            onsets.append(t)
        last = t
    return onsets


def region_series(path: Path, x: int, y: int, w: int, h: int, fps: int = 30) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-an", "-vf", f"crop={w}:{h}:{x}:{y},scale=8:8,format=gray",
                          "-r", str(fps), "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    frames = np.frombuffer(out, dtype=np.uint8).reshape(-1, 64)
    return frames.mean(axis=1)


def flash_onsets(path: Path, x: int, y: int, w: int, h: int, fps: int = 30, threshold: float = 180) -> list[float]:
    s = region_series(path, x, y, w, h, fps)
    on = s > threshold
    return [i / fps for i in range(len(on)) if on[i] and (i == 0 or not on[i - 1])]


def frame_rgb(path: Path, t: float) -> np.ndarray:
    from PIL import Image
    import io

    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", "-f", "image2", "-c:v", "png", "-"],
                         capture_output=True, check=True).stdout
    return np.asarray(Image.open(io.BytesIO(out)).convert("RGB"))
