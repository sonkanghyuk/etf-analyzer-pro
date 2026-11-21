from datetime import date

import pandas as pd
import pytest

from issue_page import SAMPLE
from issue_parser import (
    best_verification,
    exposure,
    extract_claims,
    find_mentions,
    internal_checks,
    mention_table,
    parse_ref_date,
)

D = date(2026, 11, 20)


def claims_of(text, ticker=None):
    _, cs = extract_claims(text, D)
    return [c for c in cs if ticker is None or c.ticker == ticker]


def test_mentions_korean_names_tickers_and_particles():
    ms = find_mentions("나스닥 100도 밀렸고 나스닥은 급락, VIX는 40. 엔비디아(NVDA)와 서클(CRCL), 다운로드 수는 무관.")
    tks = [m.ticker for m in ms]
    assert tks[:3] == ["^NDX", "^IXIC", "^VIX"]
    assert "NVDA" in tks and "CRCL" in tks
    assert "^DJI" not in tks  # '다운로드'는 다우가 아님


def test_parse_date():
    assert parse_ref_date("매경 · 2026.11.20 · 35:36", date(2000, 1, 1)) == D
    assert parse_ref_date("날짜 없음", date(2000, 1, 1)) == date(2000, 1, 1)


def test_periods_signs_and_ranges():
    cs = claims_of(
        "나스닥은 22,617로 5.28% 하락했다. 11월 나스닥 하락률은 11.08%로 제시된다. "
        "나스닥의 연초 대비 수익률은 전날까지 약 2% 상승이었지만, 이날 급락으로 -2.69%가 됐다. "
        "나스닥 100도 고점에서 10~20%가량 되돌림. 다만 올해는 나스닥이 11% 넘게 하락하고 있다. "
        "2008년 10월에는 나스닥이 17.35% 하락했다.", None)
    by = {(c.period, round(c.value, 2)) for c in cs if c.kind == "pct"}
    assert ("daily", -5.28) in by
    assert ("month", -11.08) in by          # '하락률' → 음수
    assert ("ytd_prev", 2.0) in by
    assert ("ytd", -2.69) in by            # '이날' 이 '전날' 뒤에 오면 당일 값
    assert ("skip", 20.0) in by            # 범위
    assert ("skip", -11.0) in by           # '넘게'
    hist = [c for c in cs if c.period == "month" and c.month == (2008, 10)]
    assert hist and hist[0].value == pytest.approx(-17.35)
    lv = [c for c in cs if c.kind == "level"]
    assert lv and lv[0].value == 22617


def test_internal_checks_on_sample():
    _, cs = extract_claims(SAMPLE, D)
    ic = internal_checks(cs)
    rows = {(r["검산 항목"], r["판정"]) for _, r in ic.iterrows()}
    # 앤트로픽 종가 88.3 vs 88.91 충돌, 88.91은 전날 종가×등락률과 불일치
    assert ("종가 일관성", "⚠️ 불일치") in rows
    anth = ic[(ic["종목"] == "앤트로픽") & (ic["검산 항목"] == "전날 종가 × 등락률 = 종가")]
    assert set(anth["판정"]) == {"✅ 일치", "⚠️ 불일치"}
    assert "$88.30" in anth["계산"].iloc[0]
    # 공모가 대비 +17%(전날 종가), 시초가 대비 -20%
    assert ic[(ic["검산 항목"] == "공모가 대비") & ic["영상 주장"].str.contains("97.17")]["판정"].iloc[0] == "✅ 일치"
    # SOXL 300.77 → 30.88 = -89.7% (약 90%)
    soxl = ic[ic["종목"] == "SOXL"]
    assert soxl["판정"].iloc[0] == "✅ 일치" and "+874%" in soxl["설명"].iloc[0]
    # 나스닥 연초대비: 2% × -5.28% ≠ -2.69% (어림값으로만 맞음)
    ndq = ic[ic["검산 항목"] == "연초대비 산수"]
    assert ndq["판정"].iloc[0] == "🟡 근사" and "-3.39%" in ndq["계산"].iloc[0]


def test_context_carry_stops_at_new_section():
    text = (
        "## 3. 반도체\n1. **엔비디아도 큰 폭으로 하락했다.**\n   1. 엔비디아는 13.8% 하락했다.\n\n"
        "2. **중간선거 해 11월의 강세라는 계절성도 맞지 않았다.**\n   1. 예시로 2022년 11월 5.3% 상승을 언급한다.\n"
        "## 6. 앤트로픽 IPO\n2. **유통 물량 부담도 남아 있다.**\n   1. 전날 종가 97.17달러 기준으로는 약 1.75조 달러다.\n"
    )
    cs = claims_of(text)
    assert not [c for c in cs if c.ticker == "NVDA" and c.month == (2022, 11)]
    assert [c for c in cs if c.ticker == "ANTH" and c.kind == "price" and c.period == "prev_close" and c.value == 97.17]


def _closes():
    idx = pd.bdate_range("2025-12-01", "2026-11-20")
    s = pd.Series(100.0, index=idx)
    s.loc["2025-12-31"] = 100.0
    s.loc["2026-11-19"] = 102.73  # 전날: 연초대비 +2.73%
    s.loc["2026-11-20"] = 102.73 * (1 - 0.0528)
    nv = pd.Series(150.0, index=idx)
    nv.loc["2026-11-20"] = 150 * (1 - 0.20)  # 실제 -20%: 영상 -13.8%와 불일치
    return pd.DataFrame({"^IXIC": s, "NVDA": nv})


def test_verify_against_prices_and_date_fallback():
    text = "2026.11.20 나스닥은 5.28% 하락했다. 나스닥의 연초 대비 수익률은 이날 -2.69%가 됐다. 엔비디아는 13.8% 하락했다."
    _, cs = extract_claims(text, D)
    vt, used, note = best_verification(cs, _closes(), D)
    assert used == D and note == ""
    got = dict(zip(vt["영상 주장"], vt["판정"]))
    assert got["-5.28%(1일)"] == "✅ 일치"
    assert got["-2.69%(연초대비)"] == "✅ 일치"
    assert got["-13.8%(1일)"] == "⚠️ 불일치"

    # 한국 날짜(다음 날)로 들어와도 직전 거래일로 맞춰 본다
    vt2, used2, note2 = best_verification(cs, _closes(), date(2026, 11, 21))
    assert used2 == D and "직전 거래일" in note2


def test_exposure_by_symbol_and_name():
    holdings = pd.DataFrame({
        "etf": ["QQQ", "QQQ", "QQQ", "SOXX", "SOXX", "KR1"],
        "holding": ["NVIDIA Corp", "Apple Inc", "Advanced Micro Devices Inc", "Micron Technology", "NVIDIA Corp", "엔비디아"],
        "weight": [9.0, 8.0, 2.0, 5.0, 8.5, 20.0],
        "symbol": ["NVDA", "AAPL", "AMD", None, None, None],
    })
    mat, money = exposure(holdings, ["NVDA", "AMD", "MU", "ANTH"], {"QQQ": 1000, "SOXX": 500, "KR1": 0})
    assert mat.loc["QQQ", "엔비디아"] == 9.0
    assert mat.loc["SOXX", "마이크론"] == 5.0
    assert mat.loc["KR1", "엔비디아"] == 20.0
    assert "앤트로픽" not in mat.columns  # 보유 ETF 없음
    assert mat.loc["QQQ", "언급 종목 합계"] == pytest.approx(11.0)
    nv = money.set_index("종목").loc["엔비디아", "노출 금액"]
    assert nv == pytest.approx(1000 * 0.09 + 500 * 0.085)


def test_mention_table_lists_claims():
    ms, cs = extract_claims(SAMPLE, D)
    t = mention_table(ms, cs).set_index("티커")
    assert "종가 $88.3" in t.loc["ANTH", "영상 속 숫자"]
    assert t.loc["SOXL", "종류"] == "ETF"
