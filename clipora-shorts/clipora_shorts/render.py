"""ffmpeg로 9:16 숏폼 MP4를 만듭니다."""

import sys
from pathlib import Path

from . import media
from .captions import PLAY_H, PLAY_W
from .media import VideoInfo
from .templates import Template


def default_font() -> str:
    if sys.platform.startswith("win"):
        return "Malgun Gothic"
    if sys.platform == "darwin":
        return "Apple SD Gothic Neo"
    return "Noto Sans CJK KR"


def _even(x: float) -> int:
    return int(round(x / 2)) * 2


def build_filter(info: VideoInfo, tpl: Template, face_x: float | None, ass_name: str, fontsdir: str | None) -> str:
    """원본 → 1080x1920 + 자막. 세로 원본이면 fit 템플릿도 fill로 처리합니다."""
    w, h = info.width, info.height
    layout = tpl.layout if w / h > 0.8 else "fill"
    cover = max(PLAY_W / w, PLAY_H / h)
    cw, ch = max(PLAY_W, _even(w * cover)), max(PLAY_H, _even(h * cover))

    if layout == "fill":
        cx = face_x if face_x is not None else 0.5
        x = int(min(max(cx * cw - PLAY_W / 2, 0), cw - PLAY_W))
        y = (ch - PLAY_H) // 2
        graph = f"[0:v]scale={cw}:{ch},crop={PLAY_W}:{PLAY_H}:{x}:{y},setsar=1[base]"
    else:
        fh = _even(h * PLAY_W / w)
        oy = max(0, int(PLAY_H * 0.45 - fh / 2))
        if tpl.bg == "blur":
            graph = (
                f"[0:v]split=2[a][b];"
                f"[a]scale={cw}:{ch},crop={PLAY_W}:{PLAY_H},boxblur=30:3,eq=brightness=-0.12[bg];"
                f"[b]scale={PLAY_W}:{fh},setsar=1[fg];[bg][fg]overlay=0:{oy}[base]"
            )
        else:
            graph = (
                f"color=c={tpl.bg}:s={PLAY_W}x{PLAY_H}:r=30[bg];"
                f"[0:v]scale={PLAY_W}:{fh},setsar=1[fg];[bg][fg]overlay=0:{oy}:shortest=1[base]"
            )
    ass = f"ass={ass_name}" + (f":fontsdir='{_escape(fontsdir)}'" if fontsdir else "")
    return graph + f";[base]fps=30,{ass},format=yuv420p[v]"


def _escape(path: str) -> str:
    # ffmpeg 필터 인자 안의 경로: 역슬래시·콜론·작은따옴표 이스케이프 (Windows 경로 대응)
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def render_clip(
    src: Path,
    info: VideoInfo,
    start: float,
    end: float,
    tpl: Template,
    ass_path: Path,
    out_path: Path,
    face_x: float | None = None,
    fontsdir: str | None = None,
    quality: str = "normal",
    loudnorm: bool = True,
) -> None:
    # ass 필터 경로 이스케이프를 피하려고 자막 파일이 있는 폴더에서 실행합니다.
    graph = build_filter(info, tpl, face_x, ass_path.name, fontsdir)
    preset, crf = {"fast": ("veryfast", 23), "normal": ("medium", 20), "high": ("slow", 18)}[quality]
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src.resolve()),
           "-filter_complex", graph, "-map", "[v]"]
    if info.has_audio:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
        if loudnorm:
            cmd += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]  # 숏폼 플랫폼 기준 음량
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-movflags", "+faststart", str(out_path.resolve())]
    media.run(cmd, cwd=ass_path.parent)


def thumbnail(video: Path, out_path: Path, at: float = 1.0) -> None:
    media.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(video.resolve()),
               "-frames:v", "1", "-q:v", "3", str(out_path.resolve())])
