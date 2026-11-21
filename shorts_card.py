"""월가이슈 → 쇼츠용 세로 카드(1080×1920 PNG)."""
from __future__ import annotations

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

FONT_DIR = Path(__file__).resolve().parent / "johnber_shorts_studio" / "fonts"
BG = "#0f172a"
PANEL = "#1e293b"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
UP = "#ff5a5a"     # 한국식: 상승 빨강
DOWN = "#4da3ff"   # 하락 파랑


def _font(bold: bool = False) -> font_manager.FontProperties | None:
    name = "NanumGothicBold.ttf" if bold else "NanumGothic.ttf"
    path = FONT_DIR / name
    return font_manager.FontProperties(fname=str(path)) if path.exists() else None


def _chg(v, kind: str) -> tuple[str, str]:
    if v is None or pd.isna(v):
        return "-", MUTED
    color = UP if v > 0 else DOWN if v < 0 else MUTED
    text = f"{v:+.1f}bp" if kind == "rate" else f"{v:+.2f}%"
    return text, color


def _val(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:,.0f}" if abs(v) >= 10000 else f"{v:,.2f}"
    return f"{v:,.2f}"


def _short(label: str) -> str:
    """'반도체 3배(SOXL)' → 'SOXL' 처럼 카드에 들어갈 짧은 이름."""
    if "(" in label and label.endswith(")"):
        return label[label.index("(") + 1:-1]
    return label[:9]


def make_card(snap: pd.DataFrame, sectors: pd.DataFrame | None = None, rank_line: str | None = None,
              events: pd.DataFrame | None = None, title: str = "오늘의 월가") -> bytes:
    """대시보드 표(snap)로 세로 카드를 만들어 PNG 바이트로 돌려준다."""
    fb, fr = _font(True), _font(False)
    fig = plt.figure(figsize=(10.8, 19.2), dpi=100)
    fig.patch.set_facecolor(BG)
    t = lambda x, y, s, size, color=TEXT, bold=False, ha="left": fig.text(  # noqa: E731
        x, y, s, fontsize=size, color=color, ha=ha, va="center", fontproperties=fb if bold else fr)

    by = snap.set_index("티커") if not snap.empty else pd.DataFrame()
    asof = str(by["기준일"].iloc[0]) if not by.empty else ""
    t(0.07, 0.955, title, 46, bold=True)
    t(0.07, 0.925, f"{asof} 미국 증시 마감", 22, MUTED)

    # 주요 지수
    y = 0.87
    for tk in ("^DJI", "^GSPC", "^IXIC", "^SOX"):
        if tk not in by.index:
            continue
        r = by.loc[tk]
        fig.patches.append(plt.Rectangle((0.05, y - 0.027), 0.90, 0.054, transform=fig.transFigure, color=PANEL, zorder=-1))
        chg, col = _chg(r["1일"], r["종류"])
        t(0.08, y, r["구분"], 30, bold=True)
        t(0.60, y, _val(r["현재값"]), 28, ha="right")
        t(0.92, y, chg, 34, col, bold=True, ha="right")
        y -= 0.062

    # 위험지표
    y -= 0.01
    t(0.07, y, "위험 지표", 24, MUTED, bold=True)
    y -= 0.04
    items = [tk for tk in ("^VIX", "^TNX", "DX-Y.NYB", "KRW=X", "GC=F", "CL=F", "BTC-USD") if tk in by.index]
    for i, tk in enumerate(items):
        r = by.loc[tk]
        col_x = 0.07 if i % 2 == 0 else 0.53
        if i and i % 2 == 0:
            y -= 0.04
        chg, col = _chg(r["1일"], r["종류"])
        label = r["구분"].replace(" 공포지수", "").replace(" 금리", "")
        if r["종류"] in ("vol", "rate"):  # VIX·금리는 수준이 중요
            label = f"{label} {r['현재값']:.2f}{'%' if r['종류'] == 'rate' else ''}"
        t(col_x, y, label, 22)
        t(col_x + 0.40, y, chg, 22, col, bold=True, ha="right")
    y -= 0.05

    # 이번 달 역사적 위치
    if rank_line:
        fig.patches.append(plt.Rectangle((0.05, y - 0.035), 0.90, 0.065, transform=fig.transFigure, color="#3b0d0d", zorder=-1))
        t(0.08, y, rank_line[:34], 24, TEXT, bold=True)
        y -= 0.07

    # 섹터 상·하위
    if sectors is not None and not sectors.empty:
        s = sectors.dropna(subset=["1일"]).sort_values("1일")
        if len(s) >= 2:
            t(0.07, y, "섹터·ETF 1일 등락", 24, MUTED, bold=True)
            y -= 0.04
            worst, best = s.head(3), s.tail(3).iloc[::-1]
            for (_, b), (_, w) in zip(best.iterrows(), worst.iterrows()):
                bc, bcol = _chg(b["1일"], "index")
                wc, wcol = _chg(w["1일"], "index")
                t(0.07, y, _short(b["구분"]), 21)
                t(0.47, y, bc, 21, bcol, bold=True, ha="right")
                t(0.53, y, _short(w["구분"]), 21)
                t(0.93, y, wc, 21, wcol, bold=True, ha="right")
                y -= 0.036
            y -= 0.015

    # 다가오는 일정
    if events is not None and not events.empty:
        t(0.07, y, "다가오는 일정", 24, MUTED, bold=True)
        y -= 0.04
        # 카드에는 덜 중요한 일정(조기 폐장, 통상 고용보고서)은 빼고 3개만
        ev = events[~events["이벤트"].astype(str).str.contains("조기 폐장|고용보고서")]
        for _, e in ev.head(3).iterrows():
            if y < 0.05:
                break
            d = e["날짜"]
            t(0.07, y, f"{d:%m/%d} {e['D-day']}", 21, "#fbbf24", bold=True)
            label = str(e["이벤트"]).replace("미국 증시 ", "")
            who = str(e.get("관련") or "").split(",")[0].strip()
            if e.get("출처") == "영상 요약" and who and who not in label:
                label = f"{who} · {label}"
            t(0.33, y, label[:22], 21)
            y -= 0.035

    t(0.07, 0.03, "데이터: Yahoo Finance · 투자 권유가 아닌 정보 제공용", 16, MUTED)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, dpi=100)
    plt.close(fig)
    return buf.getvalue()
