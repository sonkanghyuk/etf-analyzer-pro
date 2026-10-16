"""숏폼 템플릿. 화면 구성(layout/bg)과 ASS 자막 스타일을 정의합니다.

ASS 색상은 &HAABBGGRR (AA=투명도, 00이 불투명) 순서입니다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    desc: str
    layout: str  # "fit": 원본 비율 그대로 가운데 / "fill": 9:16 화면을 꽉 채우게 자르기
    bg: str  # "blur" 또는 ffmpeg 색상 이름/hex (fit일 때만)
    title: dict | None
    caption: dict


WHITE, BLACK, YELLOW, PINK = "&H00FFFFFF", "&H00000000", "&H0033D4FF", "&H008A5CFF"

TEMPLATES = {
    t.id: t
    for t in [
        Template(
            "clean", "강의 · 클린", "검은 배경, 위 제목, 아래 자막. 가장 무난한 강의용",
            layout="fit", bg="black",
            title={"size": 80, "color": WHITE, "outline": 0, "margin_v": 300},
            caption={"size": 72, "color": WHITE, "outline": 6, "margin_v": 520},
        ),
        Template(
            "blur", "강연 · 블러", "흐린 원본 배경 위에 영상, 핵심어 노란색 강조",
            layout="fit", bg="blur",
            title={"size": 78, "color": WHITE, "outline": 5, "margin_v": 300},
            caption={"size": 76, "color": WHITE, "outline": 7, "highlight": YELLOW, "margin_v": 500},
        ),
        Template(
            "talk", "인터뷰 · 토크", "화면을 꽉 채우고 위에 빨간 제목 띠, 아래 박스 자막",
            layout="fill", bg="black",
            title={"size": 70, "color": WHITE, "box": "&H003131E0", "margin_v": 200},
            caption={"size": 66, "color": WHITE, "box": "&H40000000", "margin_v": 420},
        ),
        Template(
            "pop", "예능 · 팝", "꽉 채운 화면, 두꺼운 테두리 노란 자막과 핑크 강조",
            layout="fill", bg="black",
            title={"size": 84, "color": WHITE, "outline": 8, "margin_v": 220},
            caption={"size": 86, "color": YELLOW, "outline": 9, "highlight": PINK, "margin_v": 440},
        ),
        Template(
            "minimal", "미니멀", "제목 없이 영상과 작은 자막만",
            layout="fill", bg="black",
            title=None,
            caption={"size": 60, "color": WHITE, "outline": 0, "shadow": 4, "margin_v": 380},
        ),
    ]
}


def get(template_id: str) -> Template:
    if template_id not in TEMPLATES:
        raise KeyError(f"없는 템플릿이에요: {template_id} (사용 가능: {', '.join(TEMPLATES)})")
    return TEMPLATES[template_id]
