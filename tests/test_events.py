from datetime import date

from events import combine, easter, extract_events, market_calendar, nth_weekday, us_market_holidays

REF = date(2026, 11, 20)

TEXT = """## 6. 앤트로픽 IPO와 상장 후 주가 부담
1. **주요 지수 조기 편입은 수요 요인이 될 수 있다.**
   1. 앤트로픽은 11월 말 MSCI에 조기 편입되고, 12월 11일 러셀 1000, 12월 21일 나스닥 100에 조기 편입될 예정이라고 설명한다.
   2. S&P 500 편입은 그 다음 해 11월로, 약 1년 뒤라고 설명한다.
   3. 상장 첫날 약 3억 주가 풀렸고, 내년 2월까지 16억 주가 나올 수 있다고 설명한다.
   4. 10월 6일 고점 이후 하락했다. 과거 중간선거 해에는 11월 증시가 좋았다.
"""


def test_extract_future_events_only():
    ev = extract_events(TEXT, REF)
    got = {(d.isoformat(), t) for d, t in zip(ev["날짜"], ev["이벤트"])}
    assert ("2026-11-30", "MSCI에 조기 편입") in got
    assert ("2026-12-11", "러셀 1000 편입") in got
    assert ("2026-12-21", "나스닥 100에 조기 편입") in got
    assert ("2027-11-30", "S&P 500 편입") in got
    assert ("2027-02-28", "16억 주 물량 출회") in got
    assert all(d >= REF for d in ev["날짜"])           # 10월 6일 같은 지난 날짜 제외
    assert not ev["문장"].str.contains("중간선거").any()  # 이번 달 이야기는 일정 아님
    assert set(ev.loc[ev["이벤트"] == "러셀 1000 편입", "관련"].iloc[0].split(", ")) >= {"앤트로픽"}
    assert ev.loc[ev["이벤트"] == "S&P 500 편입", "관련"].iloc[0].startswith("앤트로픽")  # 소제목 종목


def test_calendar_rules():
    assert easter(2026) == date(2026, 4, 5) and easter(2027) == date(2027, 3, 28)
    assert nth_weekday(2026, 11, 3, 4) == date(2026, 11, 26)   # 추수감사절
    assert nth_weekday(2026, 5, 0, -1) == date(2026, 5, 25)    # 메모리얼 데이
    hol = dict(us_market_holidays(2027))
    assert hol[date(2027, 7, 5)] == "독립기념일"  # 7/4 일요일 → 월요일 대체
    assert hol[date(2027, 12, 24)] == "크리스마스"  # 토요일 → 금요일
    mc = market_calendar(REF, date(2027, 1, 31))
    rows = dict(zip(mc["날짜"], mc["이벤트"]))
    assert rows[date(2026, 12, 18)].startswith("쿼드러플 위칭")
    assert rows[date(2026, 12, 21)] == "나스닥 100 연례 종목 변경 적용"
    assert rows[date(2026, 12, 9)] == "FOMC 금리 결정 발표"
    jobs = [d for d, t in zip(mc["날짜"], mc["이벤트"]) if t.startswith("미국 고용보고서")]
    assert date(2027, 1, 1) not in jobs and date(2027, 1, 8) in jobs  # 신정 휴장과 겹치면 한 주 뒤


def test_combine_dday():
    ev = extract_events(TEXT, REF)
    mc = market_calendar(REF, date(2026, 12, 31))
    df = combine([ev, mc], REF)
    row = df[df["이벤트"] == "러셀 1000 편입"].iloc[0]
    assert row["D-day"] == "D-21" and row["요일"] == "금"
    assert df[df["이벤트"] == "MSCI에 조기 편입"].iloc[0]["D-day"] == "~D-10"
    assert list(df["날짜"]) == sorted(df["날짜"])
