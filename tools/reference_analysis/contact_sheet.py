"""스토리보드/프레임 폴더 → 타임스탬프 라벨이 붙은 컨택트시트(5x4, 타일 320x180).

사용: python -I contact_sheet.py <frames_dir> <out_dir> [font.ttf]
파일명 규칙: *_tMMmSSs.jpg
"""
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COLS, ROWS, TW, TH = 5, 4, 320, 180


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    font = ImageFont.truetype(sys.argv[3], 20) if len(sys.argv) > 3 else ImageFont.load_default()
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in src.glob("*.jpg") if re.search(r"_t\d\dm\d\ds", p.name))
    per = COLS * ROWS
    for s in range(0, len(files), per):
        sheet = Image.new("RGB", (COLS * TW, ROWS * TH), "black")
        d = ImageDraw.Draw(sheet)
        for k, p in enumerate(files[s:s + per]):
            im = Image.open(p).convert("RGB").resize((TW, TH), Image.LANCZOS)
            x, y = (k % COLS) * TW, (k // COLS) * TH
            sheet.paste(im, (x, y))
            m = re.search(r"_t(\d\d)m(\d\d)s", p.name)
            label = f"{m.group(1)}:{m.group(2)}"
            d.rectangle([x, y, x + 64, y + 24], fill=(255, 230, 0))
            d.text((x + 4, y + 1), label, fill="black", font=font)
        name = out / f"contact_{s // per:02d}.jpg"
        sheet.save(name, quality=90)
        print(name)


if __name__ == "__main__":
    main()
