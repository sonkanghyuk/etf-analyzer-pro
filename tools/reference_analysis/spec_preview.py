"""편집 바이블의 수치(docs/supetv_editing_bible.md)만으로 1920x1080 규격 프레임을 그린다.

용도: (1) 바이블 좌표·색·폰트 크기가 서로 맞는지 눈으로 검증
      (2) 파이프라인 템플릿 구현 전 레이아웃 시안
사용: python -I tools/reference_analysis/spec_preview.py out.png [--grid] [--overlay ref.jpg]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONT_B = ROOT / "johnber_shorts_studio" / "fonts" / "NanumSquareB.ttf"
FONT_R = ROOT / "johnber_shorts_studio" / "fonts" / "NanumSquareR.ttf"

W, H = 1920, 1080
TOK = {  # 바이블 §3 팔레트 토큰
    "paper": (234, 234, 234), "ink": (29, 29, 29), "navy": (21, 49, 74), "alert_red": (220, 10, 15),
    "label_gray": (169, 168, 168), "steel": (78, 122, 158), "up": (63, 154, 95), "down": (136, 23, 34),
}
LAYOUT = {  # 바이블 §2 좌표 (px @1920x1080)
    "logo": (1646, 32, 1898, 152), "title_cy": 108, "content": (96, 180, 1824, 920),
    "sub_bar": (280, 950, 1638, 1034), "sub_radius": 10, "sub_alpha": 0.71, "sub_font": 56,
    "credit_right": 1900, "credit_y": 1050, "credit_font": 18, "title_font": 76,
}


def paper(seed: int = 7) -> Image.Image:
    """구겨진 종이 질감: 저주파 노이즈 + 무작위 주름선(밝은/어두운 쌍)."""
    rng = np.random.default_rng(seed)
    base = np.full((H, W), 234.0)
    low = rng.normal(0, 1, (H // 60 + 2, W // 60 + 2))
    low = np.asarray(Image.fromarray(((low - low.min()) / np.ptp(low) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), float)
    base += (low - 128) / 128 * 6
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(26):
        x0, y0 = rng.integers(-200, W), rng.integers(-200, H)
        ang = rng.uniform(0, np.pi)
        ln = rng.integers(300, 1100)
        x1, y1 = x0 + ln * np.cos(ang), y0 + ln * np.sin(ang)
        d.line([(x0, y0), (x1, y1)], fill=(255, 255, 255, 70), width=3)
        d.line([(x0 + 3, y0 + 3), (x1 + 3, y1 + 3)], fill=(150, 150, 150, 40), width=2)
    return img.filter(ImageFilter.GaussianBlur(1.2))


def subtitle(img: Image.Image, text: str) -> None:
    x0, y0, x1, y1 = LAYOUT["sub_bar"]
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle((x0, y0, x1, y1), LAYOUT["sub_radius"], fill=(0, 0, 0, int(255 * LAYOUT["sub_alpha"])))
    img.paste(Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB"))
    f = ImageFont.truetype(str(FONT_B), LAYOUT["sub_font"])
    ImageDraw.Draw(img).text(((x0 + x1) / 2, (y0 + y1) / 2), text, font=f, fill=(255, 255, 255), anchor="mm")


def frame(grid: bool) -> Image.Image:
    img = paper()
    d = ImageDraw.Draw(img)
    fb = lambda s: ImageFont.truetype(str(FONT_B), s)  # noqa: E731
    # 제목
    d.text((W / 2, LAYOUT["title_cy"]), "헤지펀드의 기술주 쏠림", font=fb(LAYOUT["title_font"]), fill=TOK["ink"], anchor="mm")
    # 로고 자리(존버나드TV 로고 PNG로 교체)
    lx0, ly0, lx1, ly1 = LAYOUT["logo"]
    d.rounded_rectangle(LAYOUT["logo"], 14, outline=TOK["ink"], width=4)
    d.text(((lx0 + lx1) / 2, (ly0 + ly1) / 2), "존버나드TV", font=fb(40), fill=TOK["ink"], anchor="mm")
    # 본문: 세로 막대 2개(네이비 기준 + 레드 강조) — T13 VBAR_COMPARE
    base_y = 775  # 본문 기준선: 자막 바(950)와 라벨이 겹치지 않도록 y≈775
    d.line((250, base_y, 1670, base_y), fill=TOK["ink"], width=6)
    for cx, val, top_red, lab in [(610, 27.0, 0, "통상 10년\n평균 비중"), (1310, 40.0, 13.0, "2026년\n최근 비중")]:
        hpx = val / 45 * 520
        d.rectangle((cx - 170, base_y - hpx, cx + 170, base_y), fill=TOK["navy"])
        if top_red:
            rp = top_red / 45 * 520
            d.rectangle((cx - 170, base_y - hpx, cx + 170, base_y - hpx + rp), fill=TOK["alert_red"])
        color = TOK["alert_red"] if top_red else TOK["ink"]
        d.text((cx, base_y - hpx - 44), f"{val:.1f}%" if not top_red else "40% 이상", font=fb(64), fill=color, anchor="mm")
        d.multiline_text((cx, base_y + 22), lab, font=fb(30), fill=(90, 90, 90), anchor="ma", align="center", spacing=6)
    d.line((830, 400, 1080, 300), fill=TOK["ink"], width=10)
    d.polygon([(1100, 292), (1060, 290), (1078, 322)], fill=TOK["ink"])
    d.text((960, 400), "+13%p", font=fb(40), fill=TOK["ink"], anchor="mm")
    # 출처
    d.text((LAYOUT["credit_right"], LAYOUT["credit_y"]), "출처: Goldman Sachs Prime Book, 2026.11",
           font=ImageFont.truetype(str(FONT_R), LAYOUT["credit_font"]), fill=(110, 110, 110), anchor="ra")
    subtitle(img, "통상 20% 후반대를 유지하던 기술주 비중이")
    if grid:
        g = ImageDraw.Draw(img, "RGBA")
        for (x0, y0, x1, y1), col in [(LAYOUT["content"], (0, 160, 255, 255)), (LAYOUT["sub_bar"], (255, 0, 200, 255)),
                                      (LAYOUT["logo"], (255, 140, 0, 255)), ((480, 72, 1440, 144), (0, 200, 0, 255))]:
            g.rectangle((x0, y0, x1, y1), outline=col, width=3)
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--overlay", help="레퍼런스 프레임(아무 해상도)을 50% 겹쳐 정렬 확인")
    a = ap.parse_args()
    img = frame(a.grid)
    if a.overlay:
        ref = Image.open(a.overlay).convert("RGB").resize((W, H), Image.LANCZOS)
        img = Image.blend(img, ref, 0.5)
    img.save(a.out)
    print(a.out)


if __name__ == "__main__":
    main()
