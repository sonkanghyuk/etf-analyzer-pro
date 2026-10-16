"""검수용 테스트 영상·자막을 만든다(자체 제작 자료, 실제 강의 아님).

영상: 1920x1080 30fps, 네 모서리 색 표식, 중앙 시각 표시, 동기화용 흰색 섬광.
음성: 낮은 220Hz 기준음 + 섬광과 동시에 울리는 880Hz 비프. 지정한 구간은 완전 무음.

사용:  python tools/make_test_media.py <출력폴더> [--duration 10] [--silence 4-6]
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "fonts" / "NanumGothicBold.ttf"


def _esc_path(p: Path) -> str:
    # drawtext fontfile 경로 이스케이프(Windows 드라이브 콜론 포함)
    return str(p).replace("\\", "/").replace(":", "\\:")


def make_video(out: Path, duration: float, silence: tuple[float, float] | None, beeps: list[float], with_audio: bool = True) -> None:
    ff = shutil.which("ffmpeg")
    if not ff:
        sys.exit("ffmpeg가 필요합니다")
    flash_expr = "+".join(f"between(t,{b:.3f},{b + 0.1:.3f})" for b in beeps) or "0"
    font = _esc_path(FONT)
    vf = ",".join([
        "drawbox=x=0:y=0:w=120:h=120:color=red:t=fill",
        "drawbox=x=1800:y=0:w=120:h=120:color=lime:t=fill",
        "drawbox=x=0:y=960:w=120:h=120:color=blue:t=fill",
        "drawbox=x=1800:y=960:w=120:h=120:color=yellow:t=fill",
        "drawbox=x=0:y=0:w=1920:h=1080:color=white@0.9:t=6",
        f"drawbox=x=760:y=380:w=400:h=320:color=white:t=fill:enable='{flash_expr}'",
        f"drawtext=fontfile='{font}':text='%{{pts\\:hms}}':x=(w-tw)/2:y=160:fontsize=72:fontcolor=white",
        f"drawtext=fontfile='{font}':text='표 가장자리 표식 테스트 1,000,000원 3.07%':x=180:y=880:fontsize=44:fontcolor=0xA0E0FF:expansion=none",
    ])
    cmd = [ff, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x203040:s=1920x1080:r=30:d={duration}"]
    if with_audio:
        beep = "+".join(f"between(t,{b:.3f},{b + 0.1:.3f})" for b in beeps) or "0"
        sil = f"between(t,{silence[0]},{silence[1]})" if silence else "0"
        expr = f"if({sil},0,0.05*sin(2*PI*220*t)+0.8*sin(2*PI*880*t)*({beep}))"
        cmd += ["-f", "lavfi", "-i", f"aevalsrc=exprs='{expr}|{expr}':s=48000:d={duration}"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-b:a", "160k"]
    cmd += ["-shortest", str(out)]
    subprocess.run(cmd, check=True)


SAMPLE_LINES = [
    "안녕하세요, 오늘은 테스트 영상으로 쇼츠 제작 경로를 확인합니다.",
    "SOXL · TQQQ · SCHD / 3.07% / 0.1%p / 1,000,000원 / 길이가 긴 한글 테스트 문장",
    "이 문장은 줄바꿈과 글꼴 렌더링을 확인하기 위한 문자열입니다.",
    "화면 네 모서리의 색 표식이 모두 보여야 합니다.",
    "수동 줄바꿈 테스트\n두 번째 줄입니다.",
    "English ticker mix: SOXX SMH 엔비디아 커버드콜 분배금",
    "여기까지가 첫 번째 구간의 마지막 문장입니다.",
    "두 번째 구간은 여기서 시작합니다.",
    "숫자와 소수점 표기: 0.75배, 1.25배, 2.0배",
    "마지막 문장입니다. 감사합니다.",
]


def make_srt(out: Path, duration: float, step: float = 3.0) -> None:
    from_sub = []
    t, i = 0.5, 0
    while t + step - 0.3 <= duration:
        text = SAMPLE_LINES[i % len(SAMPLE_LINES)]
        from_sub.append((t, t + step - 0.3, text))
        t += step
        i += 1

    def tc(x: float) -> str:
        ms = int(round(x * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    body = "\n".join(f"{n}\n{tc(a)} --> {tc(b)}\n{txt}\n" for n, (a, b, txt) in enumerate(from_sub, 1))
    out.write_text(body, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--duration", type=float, default=10)
    ap.add_argument("--silence", default="4-6")
    ap.add_argument("--name", default="sync_test")
    ap.add_argument("--no-audio", action="store_true")
    args = ap.parse_args()
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    sil = tuple(float(x) for x in args.silence.split("-")) if args.silence else None
    beeps = [b for b in (1.0, 3.0, 7.0, 9.0) if b < args.duration] if args.duration <= 12 else \
        [float(x) for x in range(1, int(args.duration), 5)]
    if sil:
        beeps = [b for b in beeps if not (sil[0] - 0.2 <= b <= sil[1])]
    mp4 = out / f"{args.name}.mp4"
    make_video(mp4, args.duration, sil, beeps, with_audio=not args.no_audio)  # type: ignore[arg-type]
    make_srt(out / f"{args.name}.srt", args.duration)
    print(mp4)


if __name__ == "__main__":
    main()
