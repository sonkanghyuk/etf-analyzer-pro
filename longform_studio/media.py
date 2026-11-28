"""ffmpeg 호출, 원본 정보, 긴 무음 줄이기."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .brand import brand


def need(tool: str = "ffmpeg") -> None:
    if not shutil.which(tool):
        raise SystemExit(f"{tool} 이(가) 없습니다. Windows: winget install Gyan.FFmpeg / Mac: brew install ffmpeg")


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {' '.join(args[:6])} …\n{r.stderr[-2500:]}")
    return r


def ffmpeg_major() -> int:
    """ffmpeg 주 버전(개발 빌드처럼 숫자가 없으면 최신으로 간주)."""
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
    m = re.search(r"ffmpeg version n?(\d+)\.", out)
    return int(m.group(1)) if m else 99


def probe(path: Path) -> dict:
    need("ffprobe")
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
             "-of", "json", str(path)])
    j = json.loads(r.stdout)
    v = [s for s in j.get("streams", []) if s.get("codec_type") == "video" and s.get("width")]
    a = [s for s in j.get("streams", []) if s.get("codec_type") == "audio"]
    return {"duration": float(j["format"]["duration"]), "has_video": bool(v), "has_audio": bool(a),
            "width": v[0]["width"] if v else None, "height": v[0]["height"] if v else None}


def silences(path: Path) -> list[tuple[float, float]]:
    t = brand()["trim"]
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                        f"silencedetect=noise={t['noise_db']}dB:d={t['min_silence']}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(starts, ends))


def keep_ranges(duration: float, sil: list[tuple[float, float]]) -> list[tuple[float, float]]:
    t = brand()["trim"]
    half = t["keep_silence"] / 2
    keep, cur = [], 0.0
    for s, e in sil:
        if e - s < t["min_silence"]:
            continue
        a, b = s + half, e - half
        if b - a > 0.05:
            if a > cur:
                keep.append((round(cur, 3), round(a, 3)))
            cur = b
    if duration - cur > 0.05:
        keep.append((round(cur, 3), round(duration, 3)))
    return keep


def map_time(t: float, keep: list[tuple[float, float]]) -> float:
    """원본 시각 → 줄인 뒤 시각."""
    acc = 0.0
    for a, b in keep:
        if t < a:
            return acc
        if t <= b:
            return acc + (t - a)
        acc += b - a
    return acc


def trim(src: Path, out: Path, keep: list[tuple[float, float]], has_video: bool) -> None:
    fps = brand()["canvas"]["fps"]
    parts, labels = [], []
    for i, (a, b) in enumerate(keep):
        if has_video:
            parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]")
            labels.append(f"[v{i}]")
        parts.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]")
    parts.append("".join(labels) + f"concat=n={len(keep)}:v={1 if has_video else 0}:a=1" + ("[v][a]" if has_video else "[a]"))
    script = out.with_suffix(".filter.txt")
    script.write_text(";\n".join(parts), encoding="utf-8")
    # 7.0부터 -filter_complex_script 는 폐지 예정 → 파일에서 읽는 -/filter_complex 사용
    opt = ["-/filter_complex", str(script)] if ffmpeg_major() >= 7 else ["-filter_complex_script", str(script)]
    args = ["ffmpeg", "-y", "-i", str(src), *opt]
    if has_video:
        args += ["-map", "[v]", "-map", "[a]", "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                 "-pix_fmt", "yuv420p"]
    else:
        args += ["-map", "[a]"]
    run(args + ["-c:a", "aac", "-b:a", "192k", str(out)])
    script.unlink(missing_ok=True)
