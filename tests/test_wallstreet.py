import numpy as np
import pandas as pd
import pytest

from wallstreet import (
    headline_lines,
    market_snapshot,
    month_rank,
    required_recovery,
    snapshot_row,
    streak,
    streak_record,
    ytd_same_day,
)


def bdays(start, values):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_streak_down_and_up():
    assert streak(bdays("2026-01-01", [10, 11, 10, 9, 8])) == -3
    assert streak(bdays("2026-01-01", [10, 9, 10, 11])) == 2
    assert streak(bdays("2026-01-01", [10, 11, 11])) == 0


def test_streak_record_since():
    # 4일 하락 → 반등 → 3일 하락: 현재 3일은 이전 4일 하락 이후 최장
    s = bdays("2026-01-01", [10, 9, 8, 7, 6, 7, 6, 5, 4])
    r = streak_record(s)
    assert r["streak"] == -3
    assert r["since_len"] == 4
    assert not r["longest_in_data"]
    # 데이터 내 최장
    r2 = streak_record(bdays("2026-01-01", [10, 11, 10, 9, 8, 7]))
    assert r2["longest_in_data"] and r2["streak"] == -4


def test_required_recovery():
    assert required_recovery(-50) == pytest.approx(100.0)
    assert required_recovery(-89.73) == pytest.approx(30.077 / 3.0877 * 100 - 100, rel=1e-2)


def test_snapshot_periods_and_rate_bp():
    idx = pd.bdate_range("2025-12-01", "2026-11-20")
    s = pd.Series(np.linspace(100, 120, len(idx)), index=idx)
    s.loc["2026-11-20"] = 90.0  # 마지막 날 급락
    row = snapshot_row("테스트", "T", "index", s)
    prev_year_end = s[s.index < "2026-01-01"].iloc[-1]
    assert row["연초대비"] == pytest.approx((90 / prev_year_end - 1) * 100)
    oct_end = s[s.index < "2026-11-01"].iloc[-1]
    assert row["월초대비"] == pytest.approx((90 / oct_end - 1) * 100)
    assert row["52주고점대비(%)"] < -20
    assert row["회복필요상승률(%)"] == pytest.approx(required_recovery(row["52주고점대비(%)"]))
    assert row["연속(일)"] == -1

    rate = pd.Series([4.10, 4.25], index=pd.bdate_range("2026-11-19", periods=2))
    r = snapshot_row("10년", "^TNX", "rate", rate)
    assert r["1일"] == pytest.approx(15.0)  # bp
    assert r["52주고점대비(%)"] is None


def test_month_rank_finds_last_worse_month():
    # 월말 값을 직접 만든다: 2008-10 -17%, 2022-04 -13%, 현재(2026-11 진행중) -11%
    months = pd.date_range("2008-01-31", "2026-10-31", freq="ME")
    rets = pd.Series(0.01, index=months)
    rets.loc["2008-10-31"] = -0.17
    rets.loc["2022-04-30"] = -0.13
    level = 100 * (1 + rets).cumprod()
    cur = pd.Series([level.iloc[-1] * 0.89], index=[pd.Timestamp("2026-11-20")])
    s = pd.concat([level, cur])
    r = month_rank(s)
    assert r["month"] == "2026-11"
    assert r["partial"] is True
    assert r["return"] == pytest.approx(-11.0)
    assert r["worse_rank"] == 3
    assert r["since_month"] == "2022-04"


def test_ytd_same_day_and_headline():
    idx = pd.bdate_range("2023-12-01", "2026-11-20")
    s = pd.Series(np.linspace(100, 130, len(idx)), index=idx)
    t = ytd_same_day(s)
    assert list(t["연도"]) == [2024, 2025, 2026]
    assert bool(t.iloc[-1]["올해"])

    closes = pd.DataFrame({"^GSPC": s, "^IXIC": s * 3, "^VIX": s / 5})
    snap = market_snapshot(closes, [("S&P 500", "^GSPC", "index"), ("나스닥 종합", "^IXIC", "index"), ("VIX", "^VIX", "vol"), ("없음", "NOPE", "index")])
    assert len(snap) == 3
    lines = headline_lines(snap, month_rank(s), "S&P 500")
    assert len(lines) == 3 and "S&P 500" in lines[0]
