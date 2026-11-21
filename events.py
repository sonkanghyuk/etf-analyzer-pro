"""월가이슈 4단계: 일정표.

- 영상 요약에서 앞으로의 일정(지수 편입, 보호예수 해제, 금리 결정 등)을 뽑는다.
- 날짜 규칙으로 계산되는 미국 시장 일정(쿼드러플 위칭, 나스닥100 정기변경, 휴장일)을 만든다.
- FOMC 일정은 연준이 공개한 2026년 일정만 넣는다(이후 연도는 공개 일정을 확인해 직접 추가).
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

import pandas as pd

from issue_parser import entity_info, sentence_contexts

EVENT_WORDS = re.compile(
    r"편입|발표|회의|FOMC|실적|보호예수|락업|오버행|만기|상장|취임|인상|인하|선거|배당|리밸런싱|청문회|연설|"
    r"출회|해제|풀리|나올|나오|결정|마감|시행|발효|부과"
)
DATE_RE = re.compile(
    r"(?:(\d{4})년\s?|(내년|다음\s?해|이듬해|올해|올\s?)\s?)?(?<!\d)(\d{1,2})월(?!\s?물)\s?(?:(\d{1,2})일|(말|초|중순|하순|상순))?"
)
PART_DAY = {"초": 5, "상순": 5, "중순": 15, "하순": 25}
TAIL_CLEAN = [
    r"\s?(?:될|할|하는|되는)?\s?예정.*$", r"(?:이)?라고\s.*$", r"다고\s.*$", r"\s?수\s?있.*$", r"(?:했|됐|한)다.*$",
    r"[\s,·]+$",
]
HEAD_CLEAN = r"^(?:에는|에도|에서|에|은|는|이|가|로|으로|부터|까지|쯤|경|께|,|\s)+"
CUT = re.compile(r"[,.;|]|되고\s|하고\s|이며\s|으며\s|며\s|지만\s")
ENDING = r"(?:되고|하고|되며|하며|될|되는|된|할|한|하는|을|를|은|는|이|가|에|의|으로|로|도)$"
RELEASE = {"나올": "물량 출회", "나오": "물량 출회", "풀리": "물량 출회", "풀릴": "물량 출회", "출회": "물량 출회"}


def _focus(title: str, before: str) -> str:
    """제목을 이벤트 단어가 들어간 어절에서 끊고, 너무 짧으면 앞 구절 몇 어절을 붙인다."""
    m = EVENT_WORDS.search(title)
    if not m:
        return title
    end = m.end()
    while end < len(title) and not title[end].isspace():
        end += 1
    words = title[:end].split()
    last = re.sub(ENDING, "", words[-1]) or words[-1]
    kw = m.group(0)
    if kw in RELEASE:
        prev = [re.sub(ENDING, "", w) for w in words[:-1]]
        core = " ".join(prev + [RELEASE[kw]]).strip()
    else:
        core = " ".join(words[:-1] + [last]).strip()
    if len(core) < 6:
        extra = [w for w in re.sub(r"\*\*", "", before).split() if not re.match(r"^\d+\.$", w)][-3:]
        core = (" ".join(extra) + " " + core).strip()
    return core

FOMC_2026 = [  # 연준 공개 일정의 성명 발표일(회의 둘째 날)
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
]
WEEKDAY = "월화수목금토일"


def _resolve_year(year: str | None, rel: str | None, month: int, ref: date) -> int:
    if year:
        return int(year)
    if rel and re.match(r"내년|다음|이듬", rel):
        return ref.year + 1
    if rel:
        return ref.year
    # 연도 없이 지난달 근처(3개월 이내)면 지나간 이야기, 더 앞선 달이면 내년 일정으로 본다
    if month < ref.month:
        return ref.year if ref.month - month <= 3 else ref.year + 1
    return ref.year


def _clean_title(t: str) -> str:
    t = re.sub(HEAD_CLEAN, "", t.strip())
    for rx in TAIL_CLEAN:
        t = re.sub(rx, "", t)
    t = re.sub(r"\*\*", "", t).strip()
    return t[:40]


def extract_events(text: str, ref: date) -> pd.DataFrame:
    """영상 요약 속 '앞으로의' 일정."""
    _, contexts = sentence_contexts(text)
    rows = []
    for sc in contexts:
        sent = sc.text
        if not EVENT_WORDS.search(sent):
            continue
        for m in DATE_RE.finditer(sent):
            year_s, rel, mon_s, day_s, part = m.groups()
            mon = int(mon_s)
            if not 1 <= mon <= 12:
                continue
            if not (year_s or rel or day_s or part) and mon == ref.month:
                continue  # '11월 증시는…' 같은 이번 달 이야기는 일정이 아님
            y = _resolve_year(year_s, rel, mon, ref)
            last = calendar.monthrange(y, mon)[1]
            approx = False
            if day_s:
                day = int(day_s)
                if not 1 <= day <= last:
                    continue
            elif part == "말":
                day, approx = last, True
            elif part:
                day, approx = PART_DAY[part], True
            else:
                day, approx = last, True  # 월 단위 일정은 월말로 정렬
            d = date(y, mon, day)
            if d < ref:
                continue
            # 제목: 날짜 뒤 구절 → 없으면 날짜 앞 구절 → 없으면 문장 앞부분
            after = sent[m.end():]
            cut = CUT.search(after)
            seg = _clean_title(after[: cut.start()] if cut else after)
            before = sent[: m.start()]
            bcut = list(CUT.finditer(before))
            pre = _clean_title(re.sub(r"(?:은|는|이|가)?\s?(?:그\s?)?$", "", before[bcut[-1].end():] if bcut else before))
            pre = re.sub(r"^\s*\d+\.\s*", "", pre)
            kw = EVENT_WORDS.search(sent)
            if len(seg) >= 2 and EVENT_WORDS.search(seg):
                title = _focus(seg, pre)
            elif len(pre) >= 2 and EVENT_WORDS.search(pre):
                title = _focus(pre, "")
            elif len(seg) >= 2:
                title = f"{seg} {kw.group(0)}" if kw and kw.group(0) not in seg else seg
            else:
                title = re.sub(r"^\s*\d+\.\s*", "", sent.strip())[:40]
            mentioned = [mt.ticker for mt in sc.mentions]
            stocks = [t for t in mentioned if entity_info(t).kind in ("stock", "etf", "unknown")]
            if not stocks:
                for cand in (sc.context_stock, sc.context_ticker, sc.section_ticker):
                    if cand and entity_info(cand).kind in ("stock", "etf", "unknown"):
                        stocks = [cand]
                        break
            names = list(dict.fromkeys(entity_info(t).name for t in stocks + [t for t in mentioned if t not in stocks]))
            when = d.isoformat() if not approx else (
                f"{y}-{mon:02d} {part}" if part else f"{y}-{mon:02d} (월중)")
            rows.append({
                "날짜": d, "표기": when, "이벤트": title, "관련": ", ".join(names[:3]), "출처": "영상 요약",
                "근사": approx, "문장": re.sub(r"\s+", " ", sent.strip())[:160],
            })
    df = pd.DataFrame(rows, columns=["날짜", "표기", "이벤트", "관련", "출처", "근사", "문장"])
    if not df.empty:
        df = df.drop_duplicates(subset=["날짜", "이벤트"]).sort_values("날짜").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 규칙으로 계산되는 시장 일정
# ---------------------------------------------------------------------------

def nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    """n번째 요일(weekday: 월=0). n=-1이면 마지막."""
    if n > 0:
        d = date(y, m, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(y, m, calendar.monthrange(y, m)[1])
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def us_market_holidays(y: int) -> list[tuple[date, str]]:
    out = []
    ny = date(y, 1, 1)
    if ny.weekday() != 5:  # 토요일 신정은 대체 휴장 없음
        out.append((_observed(ny), "신정"))
    out += [
        (nth_weekday(y, 1, 0, 3), "마틴 루터 킹 데이"),
        (nth_weekday(y, 2, 0, 3), "대통령의 날"),
        (easter(y) - timedelta(days=2), "성금요일"),
        (nth_weekday(y, 5, 0, -1), "메모리얼 데이"),
        (_observed(date(y, 6, 19)), "준틴스 데이"),
        (_observed(date(y, 7, 4)), "독립기념일"),
        (nth_weekday(y, 9, 0, 1), "노동절"),
        (nth_weekday(y, 11, 3, 4), "추수감사절"),
        (_observed(date(y, 12, 25)), "크리스마스"),
    ]
    return out


def market_calendar(start: date, end: date) -> pd.DataFrame:
    rows = []

    def add(d: date, title: str, note: str = ""):
        if start <= d <= end:
            rows.append({"날짜": d, "표기": d.isoformat(), "이벤트": title, "관련": note, "출처": "시장 규칙", "근사": False, "문장": ""})

    for y in range(start.year, end.year + 1):
        for mon in (3, 6, 9, 12):
            tf = nth_weekday(y, mon, 4, 3)
            add(tf, "쿼드러플 위칭 · S&P 500 분기 리밸런싱(장 마감 후)", "선물·옵션 동시 만기, 지수 ETF 대량 거래")
        dec_tf = nth_weekday(y, 12, 4, 3)
        add(dec_tf + timedelta(days=3), "나스닥 100 연례 종목 변경 적용", "QQQ 등 추종 ETF 리밸런싱")
        for d, name in us_market_holidays(y):
            add(d, f"미국 증시 휴장 · {name}")
        tg = nth_weekday(y, 11, 3, 4)
        add(tg + timedelta(days=1), "미국 증시 조기 폐장(13시) · 블랙프라이데이")
        holidays = {d for d, _ in us_market_holidays(y)}
        for mon in range(1, 13):
            jf = nth_weekday(y, mon, 4, 1)
            if jf in holidays:
                jf += timedelta(days=7)
            add(jf, "미국 고용보고서 (통상 첫째 금요일, 날짜 확인 필요)", "금리 전망에 영향")
    for d in FOMC_2026:
        add(d, "FOMC 금리 결정 발표", "연준 공개 일정 기준")
    df = pd.DataFrame(rows, columns=["날짜", "표기", "이벤트", "관련", "출처", "근사", "문장"])
    return df.sort_values("날짜").reset_index(drop=True)


def combine(frames: list[pd.DataFrame], today: date) -> pd.DataFrame:
    parts = [f for f in frames if f is not None and not f.empty]
    if not parts:
        return pd.DataFrame(columns=["날짜", "요일", "D-day", "표기", "이벤트", "관련", "출처", "문장"])
    df = pd.concat(parts, ignore_index=True)
    df["날짜"] = pd.to_datetime(df["날짜"]).dt.date
    df = df.sort_values(["날짜", "출처"]).drop_duplicates(subset=["날짜", "이벤트"]).reset_index(drop=True)
    df["요일"] = [WEEKDAY[d.weekday()] for d in df["날짜"]]
    dd = [(d - today).days for d in df["날짜"]]
    df["D-day"] = [("~" if a else "") + ("D-day" if n == 0 else f"D-{n}" if n > 0 else f"D+{-n}")
                   for n, a in zip(dd, df.get("근사", [False] * len(df)).fillna(False))]
    return df[["날짜", "요일", "D-day", "표기", "이벤트", "관련", "출처", "문장"]]
