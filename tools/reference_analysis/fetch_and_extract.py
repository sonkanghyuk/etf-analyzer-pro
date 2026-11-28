"""레퍼런스 영상 수집 + 장면 전환 검출 + 대표 프레임 추출 (내 PC에서 실행용).

클라우드 컨테이너에서는 YouTube가 데이터센터 IP를 막아 영상 본편을 받을 수 없으므로,
이 스크립트는 집/사무실 PC(Windows/Mac/Linux)에서 돌리는 것을 전제로 한다.

준비:
    pip install -U "yt-dlp[default]"     # yt-dlp
    ffmpeg 설치 (Windows: winget install Gyan.FFmpeg / Mac: brew install ffmpeg)

사용:
    python tools/reference_analysis/fetch_and_extract.py                # 기본 4편
    python tools/reference_analysis/fetch_and_extract.py URL [URL ...]  # 임의 영상
    python tools/reference_analysis/fetch_and_extract.py --local a.mp4  # 이미 받은 파일만 분석
옵션:
    --out reference_videos   저장 폴더
    --every 20               대표 프레임 간격(초)
    --scene 0.30             장면 전환 임계값(0~1, 낮을수록 민감; 같은 배경 슬라이드 교체까지 잡으려면 0.12~0.18)
    --cookies-from-browser chrome   봇 확인이 뜰 때 브라우저 로그인 쿠키 사용

결과:
    reference_videos/<날짜>_<id>.mp4 / .ko.vtt / .info.json / .jpg(썸네일)
    reference_videos/frames/<id>/every20s/f_0000_t00m00s.jpg ...
    reference_videos/frames/<id>/scenes/s_0000_t00m04s.jpg ...
    reference_videos/frames/<id>/scenes.csv  (time_s,timecode,scene_score)
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_URLS = [
    "https://youtu.be/KwszEJgVhOE",
    "https://youtu.be/TmsRsVabats",
    "https://youtu.be/EG4p2UoM4bo",
    "https://youtu.be/QMg65Y0FpM8",
]


def need(tool: str) -> None:
    if shutil.which(tool) is None:
        sys.exit(f"[중단] {tool} 이(가) 없습니다. 파일 맨 위 '준비' 안내대로 설치한 뒤 다시 실행하세요.")


def tc(t: float) -> str:
    return f"{int(t // 60):02d}m{int(t % 60):02d}s"


def download(urls: list[str], out: Path, cookies: str | None) -> list[Path]:
    need("yt-dlp")
    cmd = [
        "yt-dlp",
        "-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]",
        "--merge-output-format", "mp4",
        "--write-info-json", "--write-thumbnail", "--convert-thumbnails", "jpg",
        "--write-subs", "--write-auto-subs", "--sub-langs", "ko.*,ko", "--sub-format", "vtt/srt/best",
        "-o", str(out / "%(upload_date)s_%(id)s.%(ext)s"),
    ]
    if cookies:
        cmd += ["--cookies-from-browser", cookies]
    subprocess.run(cmd + urls, check=True)
    return sorted(out.glob("*_*.mp4"))


def duration(mp4: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def every_n(mp4: Path, dst: Path, every: int) -> int:
    dst.mkdir(parents=True, exist_ok=True)
    tmp = dst / "_tmp_%04d.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-vf", f"fps=1/{every}", "-q:v", "3", str(tmp)],
                   check=True)
    n = 0
    for i, p in enumerate(sorted(dst.glob("_tmp_*.jpg"))):
        p.rename(dst / f"f_{i:04d}_t{tc(i * every)}.jpg")
        n += 1
    return n


def scenes(mp4: Path, dst: Path, thr: float) -> list[tuple[float, float]]:
    """ffmpeg select=gt(scene,thr) 로 전환 시점을 찾고, 그 시점 프레임을 저장한다."""
    dst.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(mp4), "-vf", f"select='gt(scene,{thr})',metadata=print",
         "-vsync", "vfr", "-q:v", "3", str(dst / "_s_%04d.jpg")],
        capture_output=True, text=True,
    )
    # metadata=print 출력: "frame:N pts:.. pts_time:T" 다음 줄에 "lavfi.scene_score=S"
    pairs = [(float(t), float(s)) for t, s in
             re.findall(r"pts_time:([\d.]+)[^\n]*\n[^\n]*lavfi\.scene_score=([\d.]+)", r.stderr)]
    for (t, _), p in zip(pairs, sorted(dst.glob("_s_*.jpg"))):
        p.rename(dst / f"s_{len(list(dst.glob('s_*.jpg'))):04d}_t{tc(t)}.jpg")
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--out", default="reference_videos")
    ap.add_argument("--every", type=int, default=20)
    ap.add_argument("--scene", type=float, default=0.30)
    ap.add_argument("--local", nargs="*", help="이미 있는 mp4만 분석(다운로드 생략)")
    ap.add_argument("--cookies-from-browser", dest="cookies")
    a = ap.parse_args()
    need("ffmpeg")
    need("ffprobe")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    mp4s = [Path(p) for p in a.local] if a.local else download(a.urls or DEFAULT_URLS, out, a.cookies)
    for mp4 in mp4s:
        vid = mp4.stem.split("_", 1)[-1]
        base = out / "frames" / vid
        d = duration(mp4)
        n = every_n(mp4, base / f"every{a.every}s", a.every)
        pairs = scenes(mp4, base / "scenes", a.scene)
        with open(base / "scenes.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "timecode", "scene_score"])
            for t, s in pairs:
                w.writerow([f"{t:.2f}", f"{int(t // 60):02d}:{t % 60:05.2f}", f"{s:.3f}"])
        gaps = [b - a_ for a_, b in zip([0.0] + [t for t, _ in pairs], [t for t, _ in pairs] + [d])]
        print(f"{mp4.name}: {d / 60:.1f}분, {a.every}초 프레임 {n}장, 장면 전환 {len(pairs)}회 "
              f"(분당 {len(pairs) / (d / 60):.2f}회, 평균 {sum(gaps) / len(gaps):.1f}초 유지)")


if __name__ == "__main__":
    main()
