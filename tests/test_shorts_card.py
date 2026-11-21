from datetime import date

import numpy as np
import pandas as pd

from events import combine, market_calendar
from shorts_card import _short, make_card
from wallstreet import MARKET_DASHBOARD, SECTOR_ETFS, market_snapshot


def test_card_renders_png_1080x1920():
    idx = pd.bdate_range("2025-11-01", "2026-11-20")
    cols = [t for _, t, _ in MARKET_DASHBOARD] + [t for _, t in SECTOR_ETFS]
    closes = pd.DataFrame({t: np.linspace(100, 90 + i, len(idx)) for i, t in enumerate(cols)}, index=idx)
    snap = market_snapshot(closes, MARKET_DASHBOARD)
    sectors = market_snapshot(closes, [(l, t, "index") for l, t in SECTOR_ETFS])
    ev = combine([market_calendar(date(2026, 11, 21), date(2026, 12, 31))], date(2026, 11, 21))
    png = make_card(snap, sectors, "나스닥 종합 이번 달 -11.1% · 2022-04 이후 최악", ev)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(png)).size == (1080, 1920)


def test_short_labels():
    assert _short("반도체 3배(SOXL)") == "SOXL"
    assert _short("미국채 20년+(TLT)") == "TLT"
    assert _short("헬스케어") == "헬스케어"
