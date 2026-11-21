"""월가이슈 3단계: 영상 요약/대본 → 종목 추출 → 숫자 검산 → 내 ETF 노출도.

모든 함수는 순수 함수다(네트워크 없음). 시세는 호출하는 쪽에서 넘겨준다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd


# ---------------------------------------------------------------------------
# 종목·지수 사전
# ---------------------------------------------------------------------------

def _t(sym: str) -> str:
    """영문 티커/약어용 경계. 한글 조사가 바로 붙어도(예: 'VIX는') 잡히도록 영숫자만 경계로 본다."""
    return rf"(?<![A-Za-z0-9]){re.escape(sym)}(?![A-Za-z0-9])"


@dataclass(frozen=True)
class EntityDef:
    ticker: str          # Yahoo 티커
    name: str            # 표시명
    kind: str            # stock / etf / index / macro
    patterns: tuple[str, ...]
    holding_names: tuple[str, ...] = ()  # 구성종목 목록에서 찾을 이름


ENTITY_DEFS: list[EntityDef] = [
    # 지수·거시
    EntityDef("^NDX", "나스닥 100", "index", (r"나스닥\s?100", _t("NDX"))),
    EntityDef("^IXIC", "나스닥 종합", "index", (r"나스닥(?!\s?100)", _t("IXIC"))),
    EntityDef("^GSPC", "S&P 500", "index", (r"S&P\s?500", r"에스앤피\s?500", _t("SPX"))),
    EntityDef("^DJI", "다우존스", "index", (r"다우(?:존스|지수)?(?!운)",)),
    EntityDef("^RUT", "러셀 2000", "index", (r"러셀\s?2000",)),
    EntityDef("^SOX", "필라델피아 반도체", "index", (r"필라델피아\s?반도체",)),
    EntityDef("^VIX", "VIX", "macro", (_t("VIX"), r"공포\s?지수")),
    EntityDef("^TNX", "미국채 10년 금리", "macro", (r"10년물", r"10년\s?(?:만기\s?)?국채")),
    EntityDef("DX-Y.NYB", "달러 인덱스", "macro", (r"달러\s?인덱스",)),
    EntityDef("BTC-USD", "비트코인", "macro", (r"비트코인", _t("BTC"))),
    EntityDef("CL=F", "WTI 유가", "macro", (_t("WTI"), r"유가")),
    EntityDef("GC=F", "금", "macro", (r"금값", r"금\s?가격", r"(?<![가-힣])금(?=과|은|이|도|값|\s?선물)")),
    # 개별 종목
    EntityDef("NVDA", "엔비디아", "stock", (r"엔비디아", _t("NVDA"), _t("NVIDIA")), ("NVIDIA",)),
    EntityDef("ANT", "앤트로픽", "stock", (r"앤트로픽", _t("ANT"), _t("Anthropic")), ("Anthropic",)),
    EntityDef("MU", "마이크론", "stock", (r"마이크론", _t("MU")), ("Micron",)),
    EntityDef("INTC", "인텔", "stock", (r"인텔", _t("INTC")), ("Intel",)),
    EntityDef("AMD", "AMD", "stock", (_t("AMD"),), ("Advanced Micro Devices", "AMD")),
    EntityDef("SKHY", "SK하이닉스 ADR", "stock", (r"SK\s?하이닉스\s?ADR", _t("SKHY")), ("SK hynix Inc ADR", "SKHY")),
    EntityDef("000660.KS", "SK하이닉스", "stock", (r"SK\s?하이닉스", _t("SK hynix")), ("SK hynix", "SK하이닉스", "SK Hynix")),
    EntityDef("005930.KS", "삼성전자", "stock", (r"삼성전자",), ("Samsung Electronics", "삼성전자")),
    EntityDef("TSM", "TSMC", "stock", (_t("TSMC"), _t("TSM")), ("Taiwan Semiconductor", "TSMC")),
    EntityDef("AVGO", "브로드컴", "stock", (r"브로드컴", _t("AVGO")), ("Broadcom",)),
    EntityDef("GOOGL", "알파벳", "stock", (r"알파벳", r"구글", _t("GOOGL"), _t("GOOG")), ("Alphabet",)),
    EntityDef("MSFT", "마이크로소프트", "stock", (r"마이크로소프트", _t("MSFT")), ("Microsoft",)),
    EntityDef("AAPL", "애플", "stock", (r"애플", _t("AAPL")), ("Apple",)),
    EntityDef("AMZN", "아마존", "stock", (r"아마존", _t("AMZN")), ("Amazon",)),
    EntityDef("META", "메타", "stock", (r"메타(?!버스)", _t("META")), ("Meta Platforms",)),
    EntityDef("TSLA", "테슬라", "stock", (r"테슬라", _t("TSLA")), ("Tesla",)),
    EntityDef("ORCL", "오라클", "stock", (r"오라클", _t("ORCL")), ("Oracle",)),
    EntityDef("PLTR", "팔란티어", "stock", (r"팔란티어", _t("PLTR")), ("Palantir",)),
    EntityDef("CRWV", "코어위브", "stock", (r"코어위브", _t("CRWV")), ("CoreWeave",)),
    EntityDef("NFLX", "넷플릭스", "stock", (r"넷플릭스", _t("NFLX")), ("Netflix",)),
    EntityDef("ASML", "ASML", "stock", (_t("ASML"),), ("ASML",)),
    EntityDef("QCOM", "퀄컴", "stock", (r"퀄컴", _t("QCOM")), ("Qualcomm",)),
    EntityDef("SMCI", "슈퍼마이크로", "stock", (r"슈퍼마이크로", _t("SMCI")), ("Super Micro",)),
    EntityDef("CVS", "CVS", "stock", (_t("CVS"),), ("CVS Health",)),
]

# 텍스트에 그대로 쓰이면 ETF로 인식할 티커
KNOWN_ETFS = [
    "SOXL", "SOXS", "SOXX", "SMH", "QQQ", "QQQM", "TQQQ", "SQQQ", "SPY", "VOO", "IVV", "VTI", "DIA", "IWM",
    "SCHD", "JEPI", "JEPQ", "TLT", "IEF", "SHY", "GLD", "IAU", "XLK", "XLC", "XLY", "XLF", "XLV", "XLP",
    "XLE", "XLI", "XLB", "XLU", "XLRE", "ARKK", "NVDL", "KORU", "UPRO", "SPXL", "TMF", "BITO", "IBIT",
]
ENTITY_DEFS += [EntityDef(t, t, "etf", (_t(t),)) for t in KNOWN_ETFS]

_BY_TICKER = {d.ticker: d for d in ENTITY_DEFS}

# 괄호 속 대문자라도 티커가 아닌 것
ACRONYM_STOP = {
    "AI", "IPO", "SEC", "ETF", "CEO", "CFO", "ADR", "BOA", "GDP", "CPI", "PCE", "PPI", "FOMC", "MSCI",
    "EPS", "PER", "PBR", "ROE", "USD", "KRW", "FED", "WSJ", "NYT", "JPM", "IMF", "OPEC", "LIVE", "AGI",
}


@dataclass
class Mention:
    ticker: str
    start: int
    end: int
    text: str


def find_mentions(text: str) -> list[Mention]:
    """텍스트 속 종목·지수 언급 (겹치면 긴 쪽 우선)."""
    found: list[Mention] = []
    for d in ENTITY_DEFS:
        for pat in d.patterns:
            for m in re.finditer(pat, text):
                found.append(Mention(d.ticker, m.start(), m.end(), m.group(0)))
    # 괄호 속 미등록 티커: 예) 코어위브(CRWV), 서클(CRCL)
    named_ends = {f.end for f in found}
    for m in re.finditer(r"\(([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\)", text):
        sym = m.group(1)
        if sym in ACRONYM_STOP or sym in _BY_TICKER or any(sym == d.ticker.lstrip("^") for d in ENTITY_DEFS):
            continue
        if m.start() in named_ends or m.start() - 1 in named_ends:
            continue  # '앤트로픽(ANTH)': 종목은 이름으로 인식, 표기 검사는 ticker_label_issues에서
        found.append(Mention(sym, m.start(1), m.end(1), sym))
    found.sort(key=lambda x: (x.start, -(x.end - x.start)))
    out: list[Mention] = []
    last_end = -1
    for f in found:
        if f.start >= last_end:
            out.append(f)
            last_end = f.end
    return out


_TICKER_ALIASES = {"NDX": "^NDX", "IXIC": "^IXIC", "SPX": "^GSPC", "GSPC": "^GSPC", "DJI": "^DJI", "VIX": "^VIX",
                   "SOX": "^SOX", "RUT": "^RUT", "TNX": "^TNX"}


def ticker_label_issues(text: str) -> pd.DataFrame:
    """'회사명(TICKER)' 표기에서 괄호 속 티커가 실제 티커와 다른 경우."""
    rows = []
    mentions = find_mentions(text)
    by_end = {}
    for mt in mentions:
        by_end.setdefault(mt.end, mt)
    seen = set()
    for m in re.finditer(r"\s?\(([A-Z0-9^.=\-]{1,10})\)", text):
        mt = by_end.get(m.start())
        if not mt:
            continue
        stated = m.group(1)
        e = entity_info(mt.ticker)
        actual = e.ticker
        stated_norm = _TICKER_ALIASES.get(stated, stated)
        if stated_norm.upper() == actual.upper() or (mt.ticker, stated) in seen:
            continue
        seen.add((mt.ticker, stated))
        other = _BY_TICKER.get(stated_norm)
        if other:
            note = f"{stated}는 '{other.name}'의 티커입니다. '{mt.text}' 표기가 보통 가리키는 것: {e.name}({actual})"
        else:
            note = f"Yahoo Finance 기준 {e.name}의 티커는 {actual}입니다. {stated}는 다른 종목이거나 없는 티커일 수 있습니다."
        rows.append({"표기": f"{mt.text}({stated})", "실제 티커": actual, "설명": note})
    return pd.DataFrame(rows, columns=["표기", "실제 티커", "설명"])


def entity_info(ticker: str) -> EntityDef:
    return _BY_TICKER.get(ticker) or EntityDef(ticker, ticker, "unknown", (_t(ticker),), (ticker,))


# ---------------------------------------------------------------------------
# 문장 분리 · 숫자 추출
# ---------------------------------------------------------------------------

def split_sentences(text: str) -> list[tuple[int, int]]:
    spans = []
    pos = 0
    for m in re.finditer(r"(?<=[^\d\s][.!?])\s+|(?<=[^\d\s][.!?]\*\*)\s+|\n+", text):
        if m.start() > pos:
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text)))
    return spans


DOWN = r"하락|내렸|내린|내려|내리|떨어|급락|빠졌|빠진|빠지|빠져|마이너스|감소|줄었|줄어|낮|밀려|밀렸|밀리|무너|손실"
UP = r"상승|올랐|오른|올라|오르|급등|높|증가|늘었|늘어|플러스|뛰|반등|웃돌"

PCT_RE = re.compile(r"([+\-−])?\s?(\d+(?:\.\d+)?)\s?%(?!\s?(?:포인트|p(?![a-z])|P(?![a-z])))")
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
PRICE_RE = re.compile(rf"({NUM})\s?(?:달러|불)")
LEVEL_AFTER_RE = re.compile(rf"^\s?(?:지수)?(?:은|는|이|가)?\s?(?:약\s?)?({NUM})\s?(?:로|으로)(?![가-힣]*\s?(?:잡|보|가정))")

PERIOD_KEYS = [
    ("ytd", re.compile(r"연초\s?대비|연초\s?이후|올해|YTD|연간\s?수익률")),
    ("week", re.compile(r"이번\s?주|한\s?주(?:\s?동안)?|주간")),
    ("high", re.compile(r"고점|최고치\s?대비")),
    ("skip", re.compile(r"확률|비중|금리|인플레|모기지|평균|가능성|점유율|지분|한\s?달|전망치|기대|손실")),
    ("month", re.compile(r"(?:(\d{4})년\s?)?(\d{1,2})월(?!\s?\d{1,2}일)")),
]
ROLE_BEFORE = [
    ("prev_close", re.compile(r"전날\s?종가|전일\s?종가|어제\s?종가")),
    ("ipo", re.compile(r"공모가")),
    ("open", re.compile(r"시초가")),
    ("high", re.compile(r"고점|최고치|사상\s?최고")),
    ("intraday", re.compile(r"장중")),
]
ROLE_AFTER = [
    ("close", re.compile(r"^(?:으로|로|에)?\s?(?:장을\s?)?마감")),
    ("high", re.compile(r"^(?:까지)\s?(?:올|상승|오르|뛰)")),
    ("low", re.compile(r"^(?:까지)\s?(?:하락|떨어|내려|밀려|내리|빠)")),
    ("level", re.compile(r"^\s?(?:아래|위|선|대|도\s?무너|붕괴|지지|돌파|이\s?무너)")),
]
REL_RE = re.compile(r"(공모가|시초가|전날\s?종가|전일\s?종가)(?:는|은)?\s?(?:(" + NUM + r")\s?(?:달러|불)\s?)?(?:보다|대비)(?:는|도|은)?\s?(?:약\s?)?$")
REL_ROLE = {"공모가": "ipo", "시초가": "open", "고점": "high", "전날종가": "prev_close", "전일종가": "prev_close"}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


@dataclass
class Claim:
    ticker: str
    kind: str            # pct / price / level
    value: float         # pct는 부호 포함(부호 불명이면 양수)
    sign_known: bool
    approx: bool
    decimals: int
    period: str          # pct: daily/ytd/ytd_prev/week/high/month/relative/skip, price: role
    sentence: int
    snippet: str
    carried: bool = False
    month: tuple[int, int] | None = None
    ref_role: str | None = None
    ref_price: float | None = None
    subject_role: str | None = None
    extra: dict = field(default_factory=dict)


def _nearest_before(mentions: list[Mention], pos: int) -> Mention | None:
    cand = [m for m in mentions if m.end <= pos]
    return cand[-1] if cand else None


def _direction(after: str, before: str) -> int:
    if re.search(r"마이너스\s?$", before):
        return -1
    d = re.search(DOWN, after)
    u = re.search(UP, after)
    if d and (not u or d.start() < u.start()):
        return -1
    if u:
        return 1
    return 0


def _period(sentence: str, pos: int, ref_year: int, ref_month: int) -> tuple[str, tuple[int, int] | None]:
    best = None  # (end_pos, label, match)
    head = sentence[:pos]
    if dict(PERIOD_KEYS)["skip"].search(head):
        return "skip", None
    for label, rx in PERIOD_KEYS:
        for m in rx.finditer(head):
            if best is None or m.end() > best[0]:
                best = (m.end(), label, m)
    if best is None:
        if re.search(r"\d{4}년", head):
            return "skip", None
        return "daily", None
    _, label, m = best
    if label == "ytd":
        tail = head[m.end():]
        prev = [x.end() for x in re.finditer(r"전날|어제|전일", tail)]
        today = [x.end() for x in re.finditer(r"이날|오늘|당일|현재|지금", tail)]
        if prev and (not today or prev[-1] > today[-1]):
            return "ytd_prev", None
    if label == "month":
        y = int(m.group(1)) if m.group(1) else None
        mo = int(m.group(2))
        if not 1 <= mo <= 12:
            return "skip", None
        if y is None:
            if re.search(r"\d{4}년\s?$", head[: m.start()]):
                return "skip", None
            y = ref_year if mo <= ref_month else ref_year - 1
        return "month", (y, mo)
    return label, None


def extract_claims(text: str, ref_date: date) -> tuple[list[Mention], list[Claim]]:
    mentions = find_mentions(text)
    claims: list[Claim] = []
    recent: list[tuple[int, str]] = []  # (문장 번호, 주어) — 같은 문단에서 2문장 이내만 이어받음
    h_section: str | None = None        # '#' 제목에 나온 종목
    section: str | None = None          # 굵은 소제목에 나온 종목(없으면 '#' 제목 것)
    prev_end = 0
    for si, (a, b) in enumerate(split_sentences(text)):
        sent = text[a:b]
        ms = [Mention(m.ticker, m.start - a, m.end - a, m.text) for m in mentions if a <= m.start < b]
        if re.search(r"\n\s*\n", text[prev_end:a]):
            recent = []
        prev_end = b
        body = re.sub(r"^\s*(?:\d+\.\s*)?", "", sent)
        if sent.lstrip().startswith("#"):
            h_section = section = ms[0].ticker if ms else None
            recent = []
        elif body.startswith("**"):
            section = ms[0].ticker if ms else h_section
            recent = []
        carried_from = None
        if not ms:
            near = [t for i, t in recent if si - i <= 2]
            tk_ctx = near[-1] if near else section
            carried_from = Mention(tk_ctx, 0, 0, "") if tk_ctx else None

        def owner(pos: int) -> tuple[str | None, bool]:
            m = _nearest_before(ms, pos)
            if m:
                return m.ticker, False
            if ms:
                return ms[0].ticker, False
            if carried_from:
                return carried_from.ticker, True
            return None, False

        # 퍼센트
        for m in PCT_RE.finditer(sent):
            tk, carried = owner(m.start())
            if tk is None:
                continue
            before = sent[max(0, m.start() - 8): m.start()]
            after = sent[m.end(): m.end() + 30]
            nxt = PCT_RE.search(after)
            after_dir = after[: nxt.start()] if nxt and re.search(DOWN + "|" + UP, after[: nxt.start()]) else sent[m.end():]
            head = sent[: m.start()]
            is_range = bool(re.search(r"\d\s?%?\s?~\s?$", head)) or (m.group(1) in ("-", "−") and bool(re.search(r"\d\s?$", head)))
            sign = -1 if m.group(1) in ("-", "−") and not is_range else (1 if m.group(1) == "+" else _direction(after_dir[:40], before))
            if sign == 0:
                if re.search(r"하락률|하락폭|낙폭|하락세", head[-24:]):
                    sign = -1
                elif re.search(r"상승률|상승폭|상승세", head[-24:]):
                    sign = 1
            val = _num(m.group(2))
            approx = bool(re.search(r"약\s?$|대략\s?$|거의\s?$", before)) or bool(re.search(r"^\s?(?:가량|정도|안팎|내외)", after))
            c = Claim(tk, "pct", val * (sign or 1), sign != 0, approx, _decimals(m.group(2)), "daily", si,
                      sent.strip()[:160], carried)
            rel = REL_RE.search(sent[: m.start()])
            if rel:
                c.period = "relative"
                c.ref_role = REL_ROLE.get(re.sub(r"\s", "", rel.group(1)))
                c.ref_price = _num(rel.group(2)) if rel.group(2) else None
                c.subject_role = "prev_close" if re.search(r"전날\s?종가|전일\s?종가", sent[: rel.start()]) and c.ref_role != "prev_close" else "close"
            else:
                c.period, c.month = _period(sent, m.start(), ref_date.year, ref_date.month)
                if c.period == "daily" and re.search(r"장중", sent[: m.start()][-12:]):
                    c.period = "skip"
            if is_range or re.search(r"^\s?(?:를|을|이|가)?\s?(?:넘게|넘어|넘는|넘었|이상|이하|미만|가까이|안팎|내외|대)", sent[m.end():m.end() + 8]):
                c.period = "skip"
            claims.append(c)

        # 가격(달러)
        for m in PRICE_RE.finditer(sent):
            before_full = sent[: m.start()]
            if re.search(r"\d\s?(?:만|억|조)\s?$", before_full) or re.search(r"[~\-]$", before_full):
                continue
            tk, carried = owner(m.start())
            if tk is None:
                continue
            after = sent[m.end(): m.end() + 14]
            role = "price"
            for r, rx in ROLE_AFTER:
                if rx.search(after):
                    role = r
                    break
            window = before_full[-12:]
            best = None
            for r, rx in ROLE_BEFORE:
                for mm in rx.finditer(window):
                    if best is None or mm.end() > best[0]:
                        best = (mm.end(), r)
            if best and not (role in ("close", "high", "low") and best[1] in ("high",)):
                if best[1] == "intraday":
                    role = "intraday_" + role
                elif role in ("price", "level"):
                    role = best[1]
            claims.append(Claim(tk, "price", _num(m.group(1)), True, bool(re.search(r"약\s?$", before_full)),
                                _decimals(m.group(1)), role, si, sent.strip()[:160], carried))

        # 지수 수준 (예: '나스닥은 22,617로')
        for mt in ms:
            if entity_info(mt.ticker).kind not in ("index", "macro"):
                continue
            lm = LEVEL_AFTER_RE.search(sent[mt.end: mt.end + 24])
            if lm and "%" not in sent[mt.end: mt.end + lm.end()]:
                claims.append(Claim(mt.ticker, "level", _num(lm.group(1)), True, False, _decimals(lm.group(1)),
                                    "close", si, sent.strip()[:160]))
        if ms:
            recent = (recent + [(si, ms[-1].ticker)])[-2:]
    return mentions, claims


def parse_ref_date(text: str, default: date) -> date:
    m = re.search(r"(20\d{2})\s?[.\-/년]\s?(\d{1,2})\s?[.\-/월]\s?(\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return default


# ---------------------------------------------------------------------------
# 요약 표
# ---------------------------------------------------------------------------

PERIOD_LABEL = {
    "daily": "1일", "ytd": "연초대비", "ytd_prev": "연초대비(전날)", "week": "1주", "high": "고점대비",
    "month": "월간", "relative": "기준가 대비", "skip": "기타",
}
ROLE_LABEL = {
    "close": "종가", "prev_close": "전날 종가", "ipo": "공모가", "open": "시초가", "high": "고점", "low": "저점",
    "price": "가격", "level": "수준", "intraday_low": "장중 저점", "intraday_price": "장중", "intraday_close": "장중",
    "intraday_high": "장중 고점", "intraday_level": "장중",
}


def _fmt_claim(c: Claim) -> str:
    if c.kind == "pct":
        v = f"{c.value:+.{c.decimals}f}%" if c.sign_known else f"{abs(c.value):.{c.decimals}f}%"
        lab = PERIOD_LABEL.get(c.period, c.period)
        if c.period == "month" and c.month:
            lab = f"{c.month[0]}-{c.month[1]:02d}"
        return f"{'약 ' if c.approx else ''}{v}({lab})"
    if c.kind == "level":
        return f"{c.value:,.{c.decimals}f}(종가)"
    return f"{ROLE_LABEL.get(c.period, c.period)} ${c.value:,.{c.decimals}f}"


def mention_table(mentions: list[Mention], claims: list[Claim]) -> pd.DataFrame:
    rows = []
    order = list(dict.fromkeys(m.ticker for m in mentions))
    for tk in order:
        e = entity_info(tk)
        cs = [c for c in claims if c.ticker == tk and c.period != "skip"]
        rows.append({
            "이름": e.name,
            "티커": tk,
            "종류": {"stock": "종목", "etf": "ETF", "index": "지수", "macro": "거시", "unknown": "미등록"}[e.kind],
            "언급": sum(1 for m in mentions if m.ticker == tk),
            "영상 속 숫자": " · ".join(dict.fromkeys(_fmt_claim(c) for c in cs)) or "-",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 검산 1: 영상 내부 일관성 (시세 없이)
# ---------------------------------------------------------------------------

def _tol(c: Claim) -> float:
    """퍼센트 포인트 허용 오차."""
    if c.approx or c.decimals == 0:
        return max(1.0, abs(c.value) * 0.1)
    return 0.5 * 10 ** (-c.decimals) + 0.06


def _pct(a: float, b: float) -> float:
    return (a / b - 1.0) * 100.0


def _same(x: float, y: float, rel: float = 0.003) -> bool:
    return abs(x - y) <= abs(y) * rel


def _cmp(claim: Claim, actual: float) -> bool:
    if claim.sign_known:
        return abs(claim.value - actual) <= _tol(claim)
    return abs(abs(claim.value) - abs(actual)) <= _tol(claim)


def internal_checks(claims: list[Claim]) -> pd.DataFrame:
    rows = []

    def add(tk, item, said, calc, ok, note=""):
        verdict = ok if isinstance(ok, str) else ("✅ 일치" if ok else "⚠️ 불일치")
        rows.append({"종목": entity_info(tk).name, "검산 항목": item, "영상 주장": said, "계산": calc,
                     "판정": verdict, "설명": note})

    tickers = list(dict.fromkeys(c.ticker for c in claims))
    for tk in tickers:
        cs = [c for c in claims if c.ticker == tk]
        prices = [c for c in cs if c.kind == "price"]
        closes = [c for c in cs if (c.kind == "price" and c.period == "close") or c.kind == "level"]
        close_vals = list(dict.fromkeys(round(c.value, 4) for c in closes))
        prevs = [c for c in prices if c.period == "prev_close"]
        dailies = [c for c in cs if c.kind == "pct" and c.period == "daily" and not c.carried]
        if dailies:
            top = max(c.decimals for c in dailies)
            dailies = [c for c in dailies if c.decimals == top]

        # I1 같은 날 종가가 여러 개
        distinct = []
        for v in close_vals:
            if not any(_same(v, d) for d in distinct):
                distinct.append(v)
        if len(distinct) >= 2:
            add(tk, "종가 일관성", " vs ".join(f"{v:,g}" for v in distinct), "-", False,
                "같은 종목의 종가가 서로 다른 값으로 나옵니다. 한쪽은 오기일 가능성이 큽니다.")

        # I2 전날 종가 × (1+등락률) = 종가
        for p in prevs:
            for d in dailies:
                implied = p.value * (1 + d.value / 100)
                for v in distinct or [None]:
                    if v is None:
                        add(tk, "전날 종가 × 등락률", f"${p.value:,g} {_fmt_claim(d)}", f"계산상 종가 ${implied:,.2f}", True,
                            "종가 언급이 없어 계산값만 표시합니다.")
                        continue
                    ok = _same(implied, v, 0.004)
                    add(tk, "전날 종가 × 등락률 = 종가", f"${p.value:,g} → {_fmt_claim(d)} → 종가 ${v:,g}",
                        f"${implied:,.2f}", ok, "" if ok else f"전날 종가와 등락률로 계산하면 종가는 ${implied:,.2f}입니다.")

        # I3 한 문장 안의 두 가격 + 퍼센트 (A→B, X%)
        for si in sorted({c.sentence for c in cs}):
            ps = [c for c in prices if c.sentence == si
                  and c.period in ("price", "close", "high", "low", "intraday_low")]
            pcts = [c for c in cs if c.kind == "pct" and c.sentence == si and c.period in ("daily", "high")]
            if len(ps) >= 2 and pcts:
                a, b = ps[0].value, ps[-1].value
                actual = _pct(b, a)
                for c in pcts:
                    ok = _cmp(c, actual)
                    add(tk, "가격 변화율", f"${a:,g} → ${b:,g}, {_fmt_claim(c)}", f"{actual:+.2f}%", ok)
                    c.extra["checked"] = True

        # I3b 고점 대비 (문장이 나뉜 경우)
        highs = [c for c in prices if c.period == "high"]
        lows = [c for c in prices if c.period in ("low", "close", "intraday_low")]
        for c in cs:
            if c.kind == "pct" and c.period == "high" and not c.extra.get("checked") and highs and lows:
                h = max(x.value for x in highs)
                l = lows[-1].value
                actual = _pct(l, h)
                ok = _cmp(c, actual)
                add(tk, "고점 대비 하락률", f"고점 ${h:,g} → ${l:,g}, {_fmt_claim(c)}", f"{actual:+.2f}%", ok,
                    f"원금 회복에 {(h / l - 1) * 100:+.0f}% 상승 필요" if l < h else "")

        # I4 기준가 대비 (공모가/시초가/전날 종가보다 X% 높/낮)
        role_price = {}
        for c in prices:
            role_price.setdefault(c.period, c.value)
        for c in cs:
            if c.kind != "pct" or c.period != "relative":
                continue
            ref = c.ref_price if c.ref_price is not None else role_price.get(c.ref_role)
            if ref is None:
                continue
            subjects = [role_price["prev_close"]] if c.subject_role == "prev_close" and "prev_close" in role_price else distinct
            for s in subjects:
                actual = _pct(s, ref)
                ok = _cmp(c, actual)
                add(tk, f"{ROLE_LABEL.get(c.ref_role, c.ref_role)} 대비", f"${s:,g} vs {ROLE_LABEL.get(c.ref_role, '')} ${ref:,g}, {_fmt_claim(c)}",
                    f"{actual:+.2f}%", ok)

        # I5 연초대비(전날) × 1일 = 연초대비
        yp = [c for c in cs if c.kind == "pct" and c.period == "ytd_prev"]
        yn = [c for c in cs if c.kind == "pct" and c.period == "ytd"]
        if yp and yn and dailies:
            p, n, d = yp[0], yn[-1], dailies[0]
            calc = ((1 + p.value / 100) * (1 + d.value / 100) - 1) * 100
            ok = abs(calc - n.value) <= max(_tol(n), 0.15)
            implied_prev = ((1 + n.value / 100) / (1 + d.value / 100) - 1) * 100
            note = "" if ok else f"당일 등락률과 맞추려면 전날 연초대비가 {implied_prev:+.2f}%여야 합니다."
            if not ok and p.approx and abs(implied_prev - p.value) <= _tol(p):
                ok = "🟡 근사"
                note += f" '{_fmt_claim(p)}'를 {implied_prev:+.2f}%의 어림값으로 보면 맞지만, 그대로 계산하면 {calc:+.2f}%입니다."
            add(tk, "연초대비 산수", f"전날 {_fmt_claim(p)} → 당일 {_fmt_claim(d)} → {_fmt_claim(n)}", f"{calc:+.2f}%", ok, note)
    return pd.DataFrame(rows, columns=["종목", "검산 항목", "영상 주장", "계산", "판정", "설명"])


# ---------------------------------------------------------------------------
# 검산 2: 실제 시세와 대조
# ---------------------------------------------------------------------------

def _last_before(s: pd.Series, ts: pd.Timestamp) -> float | None:
    sub = s[s.index < ts]
    return float(sub.iloc[-1]) if not sub.empty else None


def actual_value(s: pd.Series, c: Claim, d: date) -> tuple[float | None, date | None]:
    """주장에 대응하는 실제 값과 사용한 거래일."""
    s = s.dropna()
    if s.empty:
        return None, None
    end = pd.Timestamp(d) + pd.Timedelta(hours=23, minutes=59)
    upto = s[s.index <= end]
    if upto.empty:
        return None, None
    day = upto.index[-1]
    if day.date() != d:  # 해당 날짜에 거래가 없으면 대조하지 않는다
        return None, day.date()
    now = float(upto.iloc[-1])
    if c.kind in ("level",) or (c.kind == "price" and c.period == "close"):
        return now, d
    if c.kind != "pct":
        return None, d
    if c.period == "daily":
        prev = upto.iloc[-2] if len(upto) >= 2 else None
        return (None if prev is None else _pct(now, float(prev))), d
    if c.period == "week":
        base = s[s.index <= end - pd.Timedelta(days=7)]
        return (None if base.empty else _pct(now, float(base.iloc[-1]))), d
    if c.period == "ytd":
        base = _last_before(s, pd.Timestamp(d.year, 1, 1))
        return (None if base is None else _pct(now, base)), d
    if c.period == "ytd_prev":
        base = _last_before(s, pd.Timestamp(d.year, 1, 1))
        prev = float(upto.iloc[-2]) if len(upto) >= 2 else None
        return (None if base is None or prev is None else _pct(prev, base)), d
    if c.period == "month" and c.month:
        y, mo = c.month
        start = pd.Timestamp(y, mo, 1)
        nxt = start + pd.offsets.MonthBegin(1)
        base = _last_before(s, start)
        last = _last_before(s, min(nxt, end + pd.Timedelta(minutes=1)))
        return (None if base is None or last is None else _pct(last, base)), d
    if c.period == "high":
        win = upto[upto.index > end - pd.Timedelta(days=365)]
        return _pct(now, float(win.max())), d
    return None, d


VERIFIABLE = {"daily", "week", "ytd", "ytd_prev", "month", "high"}


def verify_against_prices(claims: list[Claim], closes: pd.DataFrame, d: date) -> pd.DataFrame:
    rows = []
    seen = set()
    for c in claims:
        if c.ticker not in closes.columns:
            continue
        if c.kind == "pct" and c.period not in VERIFIABLE:
            continue
        if c.kind == "price" and c.period != "close":
            continue
        key = (c.ticker, c.kind, c.period, round(c.value, 4), c.month)
        if key in seen:
            continue
        seen.add(key)
        actual, used = actual_value(closes[c.ticker], c, d)
        if actual is None:
            verdict, shown = "❓ 데이터 없음", "-"
        else:
            near = False
            if c.kind == "pct":
                ok = _cmp(c, actual)
                if c.period == "high" and not ok:  # 고점은 장중 고가 기준일 수 있음
                    ok = abs(abs(c.value) - abs(actual)) <= max(_tol(c), 3.0)
                diff = abs(c.value - actual) if c.sign_known else abs(abs(c.value) - abs(actual))
                near = not ok and diff <= max(0.5, abs(actual) * 0.05)
                shown = f"{actual:+.2f}%"
            else:
                ok = _same(c.value, actual, 0.002)
                near = not ok and _same(c.value, actual, 0.005)
                shown = f"{actual:,.2f}"
            verdict = "✅ 일치" if ok else ("🟡 근사" if near else "⚠️ 불일치")
        rows.append({"종목": entity_info(c.ticker).name, "티커": c.ticker, "영상 주장": _fmt_claim(c), "실제": shown,
                     "기준일": used, "판정": verdict, "문장": c.snippet + (" (앞 문장 주어로 추정)" if c.carried else "")})
    return pd.DataFrame(rows, columns=["종목", "티커", "영상 주장", "실제", "기준일", "판정", "문장"])


def best_verification(claims: list[Claim], closes: pd.DataFrame, d: date) -> tuple[pd.DataFrame, date, str]:
    """한국 아침 방송은 전날 미국 장을 다루므로 기준일과 직전 거래일을 모두 시도해 더 잘 맞는 쪽을 고른다."""
    candidates = [d]
    idx = closes.dropna(how="all").index
    prev = idx[idx < pd.Timestamp(d)]
    if len(prev):
        candidates.append(prev[-1].date())
    best = None
    for cd in candidates:
        t = verify_against_prices(claims, closes, cd)
        score = (int((t["판정"] == "✅ 일치").sum()), -int((t["판정"] == "❓ 데이터 없음").sum()))
        if best is None or score > best[0]:
            best = (score, t, cd)
    _, table, used = best
    note = "" if used == d else f"입력한 날짜({d})보다 직전 거래일({used}) 기준으로 더 잘 맞아 그 날짜로 대조했습니다."
    return table, used, note


def price_window(claims: list[Claim], d: date) -> tuple[date, date]:
    """검산에 필요한 시세 구간."""
    start = date(d.year - 1, 12, 1)
    for c in claims:
        if c.kind == "pct" and c.period == "month" and c.month:
            start = min(start, date(c.month[0], c.month[1], 1) - pd.Timedelta(days=10))
        if c.kind == "pct" and c.period == "high":
            start = min(start, d - pd.Timedelta(days=400))
    return start, d + pd.Timedelta(days=5)


# ---------------------------------------------------------------------------
# 내 ETF 노출도
# ---------------------------------------------------------------------------

def _holding_match(e: EntityDef, row_holding: str, row_symbol: str | None) -> bool:
    base = e.ticker.split(".")[0].lstrip("^").upper()
    if row_symbol and str(row_symbol).upper() not in ("", "NAN", "NONE"):
        sym = str(row_symbol).upper().split(".")[0]
        if sym == base or str(row_symbol).upper() == e.ticker.upper():
            return True
    h = str(row_holding)
    if h.strip().upper() in (base, e.ticker.upper()):
        return True
    for n in e.holding_names + (e.name,):
        if n and re.search(rf"(?<![A-Za-z0-9가-힣]){re.escape(n)}(?![A-Za-z0-9])", h, flags=re.IGNORECASE):
            return True
    return False


def exposure(holdings: pd.DataFrame, tickers: list[str], amounts: dict[str, float] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """ETF × 언급 종목 비중(%) 표와, 보유금액이 있으면 종목별 노출 금액 표."""
    etfs = list(dict.fromkeys(holdings["etf"].astype(str))) if not holdings.empty else []
    stocks = [t for t in tickers if entity_info(t).kind in ("stock", "unknown", "etf")]
    mat = pd.DataFrame(0.0, index=etfs, columns=[entity_info(t).name for t in stocks])
    for etf in etfs:
        g = holdings[holdings["etf"].astype(str) == etf]
        for t in stocks:
            e = entity_info(t)
            hit = g[[_holding_match(e, r["holding"], r.get("symbol")) for _, r in g.iterrows()]]
            mat.loc[etf, e.name] = float(hit["weight"].sum()) if not hit.empty else 0.0
    mat = mat.loc[:, (mat > 0).any(axis=0)] if not mat.empty else mat
    if not mat.empty:
        mat["언급 종목 합계"] = mat.sum(axis=1)
    money = pd.DataFrame()
    if amounts and not mat.empty:
        rows = []
        for col in [c for c in mat.columns if c != "언급 종목 합계"]:
            total = sum(amounts.get(etf, 0.0) * mat.loc[etf, col] / 100 for etf in mat.index)
            if total > 0:
                rows.append({"종목": col, "노출 금액": total,
                             "내역": " + ".join(f"{etf} {amounts.get(etf, 0) * mat.loc[etf, col] / 100:,.0f}"
                                               for etf in mat.index if amounts.get(etf, 0) and mat.loc[etf, col] > 0)})
        money = pd.DataFrame(rows).sort_values("노출 금액", ascending=False) if rows else pd.DataFrame()
    return mat, money
