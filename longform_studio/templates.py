"""화면 템플릿 — 바이블 §7 카탈로그를 brand.yaml 좌표·색으로 그린다.

모든 템플릿: kind("slide" 전체 화면 | "overlay" 원본 영상 위에 얹음), n_items(p), render(p, visible, prog) → Image
- visible: 지금 보이는 항목 수(빌드 단계). 장면의 cues 마다 1씩 늘어난다.
- prog: 막 나타난 항목의 등장 진행도 0~1 (막대 성장·링 채움 애니메이션)
"""
from __future__ import annotations

import functools
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .brand import PKG, brand, color, font

W, H = 1920, 1080


# ───────────────────────── 공통 ─────────────────────────
@functools.lru_cache(maxsize=1)
def paper() -> Image.Image:
    """구겨진 종이 질감(바이블 §5). assets/paper_bg.png 가 있으면 그것을 쓴다."""
    custom = PKG / "assets" / "paper_bg.png"
    if custom.exists():
        return Image.open(custom).convert("RGB").resize((W, H))
    rng = np.random.default_rng(7)
    base = np.full((H, W), float(color("paper")[0]))
    low = rng.normal(0, 1, (H // 60 + 2, W // 60 + 2))
    low = np.asarray(Image.fromarray(((low - low.min()) / np.ptp(low) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), float)
    base += (low - 128) / 128 * 6
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(26):
        x0, y0 = rng.integers(-200, W), rng.integers(-200, H)
        ang, ln = rng.uniform(0, np.pi), rng.integers(300, 1100)
        x1, y1 = x0 + ln * np.cos(ang), y0 + ln * np.sin(ang)
        d.line([(x0, y0), (x1, y1)], fill=(255, 255, 255, 70), width=3)
        d.line([(x0 + 3, y0 + 3), (x1 + 3, y1 + 3)], fill=(150, 150, 150, 40), width=2)
    return img.filter(ImageFilter.GaussianBlur(1.2))


@functools.lru_cache(maxsize=8)
def sized(role: str, glyph_h: int):
    """글자 높이(한글 기준)로 폰트 크기를 맞춘다 — 서체가 바뀌어도 화면 밀도 유지(바이블 §4)."""
    for px in range(int(glyph_h * 0.9), int(glyph_h * 1.6)):
        b = font(role, px).getbbox("한글")
        if b[3] - b[1] >= glyph_h:
            return font(role, px)
    return font(role, glyph_h)


def canvas(p: dict) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = paper().copy()
    d = ImageDraw.Draw(img)
    if p.get("title"):
        L = brand()["layout"]["title"]
        title = norm(p["title"])
        f = sized("title", 72)
        while f.getlength(title) > 1400 and f.size > 40:
            f = font("title", f.size - 4)
        d.text((L["cx"], L["cy"]), title, font=f, fill=color("ink"), anchor="mm")
    return img, d


def credit(d: ImageDraw.ImageDraw, text: str | None) -> None:
    if text:
        C = brand()["layout"]["credit"]
        d.text((C["right"], C["y"]), text if text.startswith("출처") else f"출처: {text}",
               font=font("regular", C["px"]), fill=color("credit"), anchor="ra")


HANJA = {"美": "미", "中": "중", "日": "일", "韓": "한", "英": "영", "北": "북", "與": "여", "野": "야",
         "株": "주", "銀": "은", "獨": "독", "佛": "불", "露": "러", "伊": "이", "加": "캐", "印": "인", "對": "대"}


def norm(text: str) -> str:
    """나눔 폰트에 없는 헤드라인 약어 한자를 한글로(美 → 미)."""
    return "".join(HANJA.get(ch, ch) for ch in str(text))


def fit(d, text, role, px, max_w, min_px=24):
    f = font(role, px)
    while f.getlength(text) > max_w and px > min_px:
        px -= 2
        f = font(role, px)
    return f


def items(p: dict, key: str = "data") -> list[dict]:
    """'라벨:값!|라벨:값' → [{label, value, hi}] ('!' = 레드 강조). 값이 없으면 문자열 항목."""
    out = []
    for raw in [x.strip() for x in str(p.get(key, "")).split("|") if x.strip()]:
        hi = raw.endswith("!")
        raw = raw.rstrip("!").strip()
        if ":" in raw:
            lab, val = raw.rsplit(":", 1)
            try:
                v = float(val.replace(",", "").replace("%", "").replace("+", ""))
            except ValueError:
                v = None
            out.append({"label": norm(lab.strip()), "value": v, "raw": val.strip(), "hi": hi})
        else:
            out.append({"label": norm(raw), "value": None, "raw": "", "hi": hi})
    return out


def fmt(v: float, unit: str = "%", sign: bool = False) -> str:
    s = f"{v:+.1f}" if sign else (f"{v:,.1f}" if abs(v) < 1000 else f"{v:,.0f}")
    return f"{s}{unit}"


def ease(t: float) -> float:
    return 1 - (1 - max(0.0, min(1.0, t))) ** 3


# ───────────────────────── 템플릿 ─────────────────────────
class Tpl:
    kind = "slide"
    animated = False

    def n_items(self, p):
        return 1

    def credit(self, p):
        return p.get("credit")


class Paper(Tpl):
    """제목(+본문 한 줄) 슬라이드. 오디오 전용 원본의 기본 화면."""

    def render(self, p, visible, prog):
        img, d = canvas(p)
        if p.get("text"):
            lines = str(p["text"]).split("|")
            y0 = 540 - (len(lines) - 1) * 60
            for i, ln in enumerate(lines):
                d.text((960, y0 + i * 120), ln, font=fit(d, ln, "bold", 72, 1600), fill=color("ink"), anchor="mm")
        credit(d, self.credit(p))
        return img


class Hub(Tpl):
    """T10 중요 이슈 N가지 — 흰 헤드라인 박스 누적."""

    def n_items(self, p):
        return len(items(p, "items"))

    def render(self, p, visible, prog):
        its = items(p, "items")
        p = {**p, "title": p.get("title") or f"중요 이슈 {len(its)}가지"}
        img, d = canvas(p)
        ov = Image.new("L", (W, H), 0)  # 오른쪽 아래를 살짝 어둡게(신문 더미 자리)
        ImageDraw.Draw(ov).ellipse((900, 500, 2600, 1500), fill=60)
        img = Image.composite(Image.new("RGB", (W, H), (205, 205, 205)), img, ov.filter(ImageFilter.GaussianBlur(160)))
        d = ImageDraw.Draw(img)
        show = int(p.get("show", visible))
        y = 210
        for k, it in enumerate(its[:show]):
            f = fit(d, it["label"], "bold", 50, 1500)
            w = f.getlength(it["label"])
            d.rectangle((150 + 6, y + 6, 150 + w + 64 + 6, y + 86 + 6), fill=(165, 165, 165))
            d.rectangle((150, y, 150 + w + 64, y + 86), fill=(255, 255, 255),
                        outline=color("alert_red") if k == show - 1 and p.get("mark_last") else None, width=4)
            d.text((182, y + 43), it["label"], font=f, fill=color("ink"), anchor="lm")
            y += 112
        return img


class HBar(Tpl):
    """T12 가로 비교 막대 — 회색 라벨 칩 + 네이비 막대, '!' 항목은 레드."""
    animated = True

    def n_items(self, p):
        return len(items(p))

    def render(self, p, visible, prog):
        img, d = canvas(p)
        its = items(p)
        unit = p.get("unit", "%")
        mx = float(p.get("max", max(abs(i["value"] or 0) for i in its) or 1))
        pitch = min(150, 700 // max(1, len(its)))
        y0 = 550 - (len(its) - 1) * pitch / 2
        for k, it in enumerate(its[:visible]):
            g = ease(prog) if k == visible - 1 else 1
            y = y0 + k * pitch
            d.rounded_rectangle((260, y - 40, 560, y + 40), 8, fill=color("label_gray"))
            d.text((410, y), it["label"], font=fit(d, it["label"], "bold", 38, 270), fill=(255, 255, 255), anchor="mm")
            L = 1080 * abs(it["value"] or 0) / mx * g
            d.rectangle((580, y - 40, 580 + max(L, 6), y + 40), fill=color("alert_red" if it["hi"] else "navy"))
            txt = it["raw"] if it["raw"] and not re.match(r"^[+\-]?[\d.,]+$", it["raw"]) else fmt(it["value"] or 0, unit)
            f = font("number", 46)
            if L > f.getlength(txt) + 50:
                d.text((580 + L - 22, y), txt, font=f, fill=(255, 255, 255), anchor="rm")
            else:
                d.text((580 + L + 18, y), txt, font=f, fill=color("ink"), anchor="lm")
        credit(d, self.credit(p))
        return img


class VBar(Tpl):
    """T13 세로 막대 — 기준선 y=775, 주인공('!')은 레드."""
    animated = True

    def n_items(self, p):
        return len(items(p))

    def render(self, p, visible, prog):
        img, d = canvas(p)
        its = items(p)
        unit = p.get("unit", "%")
        base = brand()["layout"]["baseline"]
        vals = [i["value"] or 0 for i in its]
        mx = float(p.get("max", max(abs(v) for v in vals) or 1))
        neg = all(v <= 0 for v in vals)
        n = len(its)
        bw = min(340, 1300 // max(1, n) - 60)
        gap = (1500 - n * bw) / max(1, n)
        top = 300 if neg else base
        d.line((210, top, 1710, top), fill=color("ink"), width=6)
        for k, it in enumerate(its[:visible]):
            g = ease(prog) if k == visible - 1 else 1
            cx = 210 + gap / 2 + bw / 2 + k * (bw + gap)
            h = (520 if not neg else 430) * abs(vals[k]) / mx * g
            col = color("alert_red" if it["hi"] else "navy")
            txt = it["raw"] if it["raw"] and not re.match(r"^[+\-]?[\d.,]+$", it["raw"]) else fmt(vals[k], unit)
            fl = fit(d, it["label"], "bold", 34, bw + gap - 20)
            if neg:
                d.rectangle((cx - bw / 2, top, cx + bw / 2, top + h), fill=col)
                d.text((cx, top + h + 40), txt, font=font("number", 50), fill=col if it["hi"] else color("ink"), anchor="mm")
                d.text((cx, top - 36), it["label"], font=fl, fill=color("axis_label"), anchor="mm")
            else:
                d.rectangle((cx - bw / 2, top - h, cx + bw / 2, top), fill=col)
                d.text((cx, top - h - 44), txt, font=font("number", 60), fill=col if it["hi"] else color("ink"), anchor="mm")
                d.text((cx, top + 24), it["label"], font=fl, fill=color("axis_label"), anchor="ma")
        credit(d, self.credit(p))
        return img


def ring(d: ImageDraw.ImageDraw, cx, cy, diam, value, scale, label, filled, g, sign=True, unit="%"):
    r = diam / 2
    d.ellipse((cx - r - 14, cy - r - 14, cx + r + 14, cy + r + 14), fill=(58, 58, 58))
    d.ellipse((cx - r + 8, cy - r + 8, cx + r - 8, cy + r - 8), fill=(17, 17, 17))
    if filled and value is not None:
        col = color("up" if value >= 0 else "down")
        ext = 360 * min(1.0, abs(value) / scale) * g
        if ext > 0.5:
            d.arc((cx - r - 14, cy - r - 14, cx + r + 14, cy + r + 14), -90, -90 + ext, fill=col, width=22)
        d.text((cx, cy), fmt(value, unit, sign), font=font("number", 64 if len(fmt(value, unit, sign)) < 7 else 52),
               fill=(255, 255, 255), anchor="mm")
    if label:
        d.text((cx, cy + r + 58), label, font=fit(d, label, "bold", 38, 380), fill=color("ink"), anchor="mm")


class Rings(Tpl):
    """T01 지수 링 — 지름 288, 간격 408, 중심 y 510. start=0 이면 빈 원판부터."""
    animated = True

    def n_items(self, p):
        return len(items(p)) + (1 if str(p.get("start", "")) == "0" else 0)

    def render(self, p, visible, prog):
        img, d = canvas(p)
        its = items(p)
        if str(p.get("start", "")) == "0":
            visible -= 1
        scale = float(p.get("scale", max(abs(i["value"] or 0) for i in its) * 1.25 or 1))
        n = len(its)
        for k, it in enumerate(its):
            cx = 960 + (k - (n - 1) / 2) * 408
            ring(d, cx, 510, 288, it["value"], scale, it["label"], k < visible,
                 ease(prog) if k == visible - 1 else 1, unit=p.get("unit", "%"))
        credit(d, self.credit(p))
        return img


class Equation(Tpl):
    """T07 주가 + 환율 = 계좌 (링 3개, 중심 x 426/960/1506)."""
    animated = True

    def n_items(self, p):
        return 3

    def render(self, p, visible, prog):
        img, d = canvas({**p, "title": p.get("title", "주가 & 환율")})
        its = items(p)[:3]
        if len(its) == 2:  # 계좌 = (1+a)(1+b)-1 자동 계산
            a, b = its[0]["value"] or 0, its[1]["value"] or 0
            its.append({"label": "계좌", "value": round(((1 + a / 100) * (1 + b / 100) - 1) * 100, 1), "raw": "", "hi": False})
        scale = max(abs(i["value"] or 0) for i in its) * 1.25 or 1
        for k, (it, cx) in enumerate(zip(its, (426, 960, 1506))):
            ring(d, cx, 516, 300, it["value"], scale, it["label"], k < visible, ease(prog) if k == visible - 1 else 1)
        f = font("number", 110)
        d.text((693, 516), "+", font=f, fill=(150, 150, 150), anchor="mm")
        d.text((1233, 516), "=", font=f, fill=(150, 150, 150), anchor="mm")
        credit(d, self.credit(p))
        return img


class BigNumber(Tpl):
    """T21 큰 숫자 — 원본 영상을 어둡게 하고 가운데 라벨 + 큰 숫자."""
    kind = "overlay"

    def render(self, p, visible, prog):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((960, 430), p.get("label", ""), font=sized("bold", 62), fill=(255, 255, 255), anchor="mm")
        d.text((960, 590), p.get("value", ""), font=sized("number", 130),
               fill=color("alert_red") if p.get("red") else (255, 255, 255), anchor="mm")
        return img


class Quote(Tpl):
    """T18 명언 — 흰 굵은 글자 2줄(글자 높이 98, 줄 간격 116) + -이름-."""
    kind = "overlay"

    def n_items(self, p):
        return len(str(p.get("quote", "")).split("|")) + (1 if p.get("by") else 0)

    def render(self, p, visible, prog):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        lines = norm(p.get("quote", "")).split("|")
        f = sized("bold", 84)
        for ln in lines:
            f = min(f, fit(d, ln, "bold", f.size, 1700), key=lambda x: x.size)
        y0 = 540 - (len(lines) - 1) * 58 - 40
        for k, ln in enumerate(lines[:visible]):
            d.text((960, y0 + k * 116), ln, font=f, fill=(255, 255, 255), anchor="mm")
        if p.get("by") and visible > len(lines):
            d.text((960, y0 + len(lines) * 116 - 20), f"-{p['by']}-", font=sized("bold", 36), fill=(255, 255, 255), anchor="mm")
        return img


class Bullets(Tpl):
    """T14 글머리표(아이콘 대신 레드 사각 표지) — 항목 순차 등장."""

    def n_items(self, p):
        return len(items(p, "items"))

    def render(self, p, visible, prog):
        img, d = canvas(p)
        its = items(p, "items")
        pitch = min(120, 680 // max(1, len(its)))
        y0 = 540 - (len(its) - 1) * pitch / 2
        for k, it in enumerate(its[:visible]):
            y = y0 + k * pitch
            d.rectangle((250, y - 14, 278, y + 14), fill=color("alert_red" if it["hi"] else "navy"))
            d.text((310, y), it["label"], font=fit(d, it["label"], "bold", 52, 1350), fill=color("ink"), anchor="lm")
        credit(d, self.credit(p))
        return img


class ImageSlide(Tpl):
    """기사·공시 캡처 등 이미지를 본문 영역에 맞춰 그림자와 함께."""

    def render(self, p, visible, prog):
        img, d = canvas(p)
        src = Image.open(p["_dir"] / p["file"]).convert("RGB")
        x0, y0, x1, y1 = (96, 180, 1824, 920) if p.get("title") else (96, 60, 1824, 920)
        s = min((x1 - x0) / src.width, (y1 - y0) / src.height)
        im = src.resize((int(src.width * s), int(src.height * s)), Image.LANCZOS)
        x, y = (W - im.width) // 2, y0 + ((y1 - y0) - im.height) // 2
        sh = Image.new("RGBA", (im.width + 40, im.height + 40), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle((20, 20, im.width + 20, im.height + 20), fill=(0, 0, 0, 90))
        img.paste(sh.filter(ImageFilter.GaussianBlur(10)), (x - 12, y - 8), sh.filter(ImageFilter.GaussianBlur(10)))
        img.paste(im, (x, y))
        credit(d, self.credit(p))
        return img


class PriceChart(Tpl):
    """T06 종목 차트 — yfinance 데이터로 직접 그림(흰 배경, 상승 up/하락 down 캔들).
    marks='circle:2026-10-14|box:2026-11-01~2026-11-27|tag:2026-11-17:11/17' 순서대로 빌드."""

    @staticmethod
    def marks(p) -> list[tuple[str, str]]:
        return [m.strip().partition(":")[::2] for m in str(p.get("marks", "")).split("|") if m.strip()]

    def n_items(self, p):
        return 1 + len(self.marks(p))

    @staticmethod
    @functools.lru_cache(maxsize=16)
    def _data(ticker: str, period: str, csv: str | None):
        import pandas as pd
        if csv:
            df = pd.read_csv(csv, parse_dates=[0], index_col=0)
        else:
            import yfinance as yf
            df = yf.download(ticker, period=period, interval="1d", auto_adjust=False, progress=False)
            if hasattr(df.columns, "levels"):
                df.columns = df.columns.get_level_values(0)
        if df.empty:
            raise RuntimeError(f"{ticker} 시세를 받지 못했습니다(네트워크 또는 티커 확인).")
        return df[["Open", "High", "Low", "Close"]].dropna()

    def credit(self, p):
        return p.get("credit", "Yahoo Finance")

    def render(self, p, visible, prog):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from matplotlib.patches import Ellipse, Rectangle

        from .brand import font_path
        fp = str(font_path("bold"))
        font_manager.fontManager.addfont(fp)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        plt.rcParams["axes.unicode_minus"] = False

        csv = str(p["_dir"] / p["csv"]) if p.get("csv") else None
        df = self._data(p.get("ticker", ""), p.get("period", "1y"), csv)
        img, d = canvas({**p, "title": p.get("title", p.get("ticker"))})
        fig = plt.figure(figsize=(18.4, 7.3), dpi=100)
        ax = fig.add_axes([0.01, 0.06, 0.93, 0.92])
        x = mdates.date2num(df.index.to_pydatetime())
        o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
        style = p.get("style", "candle")
        up, dn = [tuple(v / 255 for v in color(k)) for k in ("up", "down")]
        if style == "area":
            ax.fill_between(x, c, c.min() * 0.97, color=tuple(v / 255 for v in color("steel")), lw=0)
            ax.set_ylim(c.min() * 0.97, c.max() * 1.03)
        else:
            wbar = (x[1] - x[0]) * 0.6 if len(x) > 1 else 0.6
            for xi, oi, hi_, li, ci in zip(x, o, h, l, c):
                col = up if ci >= oi else dn
                ax.vlines(xi, li, hi_, color=col, lw=1.2)
                ax.add_patch(Rectangle((xi - wbar / 2, min(oi, ci)), wbar, max(abs(ci - oi), (hi_ - li) * 0.01 + 1e-9), color=col, lw=0))
            ax.set_ylim(l.min() * 0.97, h.max() * 1.03)
        ax.set_xlim(x[0] - 1, x[-1] + 3)
        ax.yaxis.tick_right()
        for s in ("top", "left", "right"):
            ax.spines[s].set_visible(False)
        ax.tick_params(labelsize=14, colors="#555555")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%y.%m"))
        ax.grid(axis="y", color="#E6E6E6", lw=1)
        ax.text(x[-1] + 2.5, c[-1], f" {c[-1]:,.2f}", fontsize=16, va="center", ha="left",
                color="white", bbox=dict(boxstyle="square,pad=0.25", fc=up if c[-1] >= o[-1] else dn, ec="none"))
        y0, y1 = ax.get_ylim()
        for kind, spec in self.marks(p)[: max(0, visible - 1)]:
            if kind == "circle":
                t = mdates.datestr2num(spec.split(":")[0])
                i = int(np.argmin(abs(x - t)))
                ax.add_patch(Ellipse((x[i], c[i]), (x[-1] - x[0]) * 0.045, (y1 - y0) * 0.11,
                                     color=tuple(v / 255 for v in color("alert_red")), alpha=0.55, lw=0))
            elif kind == "box":
                a, b = [mdates.datestr2num(s) for s in spec.split("~")]
                sel = (x >= a) & (x <= b)
                lo, hi2 = l[sel].min(), h[sel].max()
                ax.add_patch(Rectangle((a - 1, lo - (y1 - y0) * 0.03), b - a + 2, hi2 - lo + (y1 - y0) * 0.06,
                                       fill=False, ec="black", lw=4))
            elif kind == "tag":
                date, _, text = spec.partition(":")
                t = mdates.datestr2num(date)
                i = int(np.argmin(abs(x - t)))
                ax.annotate(text or date, (x[i], h[i]), xytext=(0, 60), textcoords="offset points", ha="center",
                            fontsize=22, color="white", fontweight="bold",
                            bbox=dict(boxstyle="round,pad=0.35", fc="#1D1D1D"), arrowprops=dict(arrowstyle="-", color="#1D1D1D", lw=2))
        fig.canvas.draw()
        chart = Image.frombuffer("RGBA", fig.canvas.get_width_height(), fig.canvas.buffer_rgba()).convert("RGB")
        plt.close(fig)
        img.paste(chart, (40, 182))
        d = ImageDraw.Draw(img)
        credit(d, self.credit(p))
        return img


REGISTRY: dict[str, Tpl] = {
    "paper": Paper(), "hub": Hub(), "T10": Hub(), "hbar": HBar(), "T12": HBar(), "vbar": VBar(), "T13": VBar(),
    "rings": Rings(), "T01": Rings(), "equation": Equation(), "T07": Equation(), "bignum": BigNumber(), "T21": BigNumber(),
    "quote": Quote(), "T18": Quote(), "bullets": Bullets(), "T14": Bullets(), "image": ImageSlide(), "T11": ImageSlide(),
    "chart": PriceChart(), "T06": PriceChart(),
}
MEDIA_KINDS = {"video", "broll"}


def get(name: str) -> Tpl:
    if name not in REGISTRY:
        raise KeyError(f"모르는 템플릿 '{name}'. 사용 가능: {', '.join(sorted(set(REGISTRY) | MEDIA_KINDS))}")
    return REGISTRY[name]
