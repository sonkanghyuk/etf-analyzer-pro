"""설치 확인용 샘플: 영상(ffmpeg로 생성)과 자막을 만들어 인터넷·API 키 없이 전체 과정을 돌려 봅니다."""

import json
from pathlib import Path

from . import media

LINES = [
    "안녕하세요 여러분 오늘 강의 시작하겠습니다", "앞에서 말씀드린 내용 잠깐 정리하고요",
    "공부를 오래 하는 사람과 잘하는 사람은 다릅니다", "제가 10년 동안 학생들을 가르치면서 깨달은 건 딱 하나예요",
    "결국 매일 30분이라도 꾸준히 하는 사람이 이깁니다", "하루 열 시간 몰아서 하는 건 오래 못 가요",
    "그럼 어떻게 꾸준히 할 수 있을까요?", "첫 번째 방법은 시작 시간을 고정하는 겁니다",
    "의지가 아니라 습관으로 만드는 거죠", "두 번째는 기록이에요 공부한 시간을 적어 보세요",
    "숫자가 쌓이면 그만두기 아까워집니다", "질문 하나 받아 볼게요", "슬럼프가 오면 어떻게 하냐고 많이 물어보세요",
    "저는 그럴 때 양을 절반으로 줄입니다", "멈추는 것보다 줄이는 게 훨씬 낫거든요",
    "이것만 기억하셔도 오늘 강의는 충분합니다", "다음 시간에는 시험 전략을 이야기해 볼게요", "감사합니다",
]
PAUSE_AFTER = {1, 6, 11, 15}


def transcript() -> dict:
    segs, t = [], 1.0
    for i, line in enumerate(LINES):
        words = line.split()
        dur = max(2.5, len(line.replace(" ", "")) * 0.22)
        total = sum(len(w) for w in words)
        tt, ws = t, []
        for w in words:
            d = dur * len(w) / total
            ws.append({"start": round(tt, 2), "end": round(tt + d * 0.92, 2), "word": w})
            tt += d
        segs.append({"id": i, "start": round(t, 2), "end": round(t + dur, 2), "text": line, "words": ws})
        t += dur + (1.6 if i in PAUSE_AFTER else 0.5)
    return {"language": "ko", "duration": round(t + 2, 2), "segments": segs}


def create(folder: Path) -> tuple[Path, Path]:
    """샘플 영상과 transcript.json을 만들고 경로를 돌려줍니다."""
    folder.mkdir(parents=True, exist_ok=True)
    data = transcript()
    video = folder / "샘플_강의.mp4"
    if not video.exists():
        dur = data["duration"]
        media.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30:d={dur}",
            "-f", "lavfi", "-i", f"sine=f=220:d={dur}",
            "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", str(video),
        ])
    tr = folder / "샘플_자막.json"
    tr.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return video, tr
