"""월가이슈: 시장 대시보드 · 섹터 히트맵 · 과거 비교 계산 로직.

화면(app.py)과 분리해 순수 함수로 두어, 가격 데이터만 있으면 테스트할 수 있게 했다.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

# (표시명, Yahoo 티커, 종류) — 종류: index / rate / fx / commodity / crypto / vol
MARKET_DASHBOARD: list[tuple[str, str, str]] = [
    ("다우존스", "^DJI", "index"),
    ("S&P 500", "^GSPC", "index"),
    ("나스닥 종합", "^IXIC", "index"),
    ("나스닥 100", "^NDX", "index"),
    ("러셀 2000", "^RUT", "index"),
    ("필라델피아 반도체", "^SOX", "index"),
    ("VIX 공포지수", "^VIX", "vol"),
    ("미국채 10년 금리", "^TNX", "rate"),
    ("미국채 2년 금리", "2YY=F", "rate"),
    ("달러 인덱스", "DX-Y.NYB", "fx"),
    ("원/달러 환율", "KRW=X", "fx"),
    ("WTI 유가", "CL=F", "commodity"),
    ("금", "GC=F", "commodity"),
    ("비트코인", "BTC-USD", "crypto"),
]

SECTOR_ETFS: list[tuple[str, str]] = [
    ("기술", "XLK"),
    ("커뮤니케이션", "XLC"),
    ("임의소비재", "XLY"),
    ("금융", "XLF"),
    ("헬스케어", "XLV"),
    ("필수소비재", "XLP"),
    ("에너지", "XLE"),
    ("산업재", "XLI"),
    ("소재", "XLB"),
    ("유틸리티", "XLU"),
    ("부동산", "XLRE"),
    ("반도체", "SOXX"),
    ("반도체 3배(SOXL)", "SOXL"),
    ("나스닥100(QQQ)", "QQQ"),
    ("미국채 20년+(TLT)", "TLT"),
    ("금(GLD)", "GLD"),
]

HISTORY_INDEXES: list[tuple[str, str]] = [
    ("나스닥 종합", "^IXIC"),
    ("S&P 500", "^GSPC"),
    ("다우존스", "^DJI"),
    ("나스닥 100", "^NDX"),
    ("필라델피아 반도체", "^SOX"),
]


def dashboard_start(today: date) -> date:
    """연초 대비·52주 고점 계산에 충분한 시작일."""
    return min(today - timedelta(days=400), date(today.year - 1, 12, 1))


def _last_before(s: pd.Series, ts: pd.Timestamp) -> float | None:
    """ts 이전(미포함) 마지막 값."""
    sub = s[s.index < ts]
    return float(sub.iloc[-1]) if not sub.empty else None


def _last_on_or_before(s: pd.Series, ts: pd.Timestamp) -> float | None:
    sub = s[s.index <= ts]
    return float(sub.iloc[-1]) if not sub.empty else None


def _pct(now: float | None, base: float | None) -> float | None:
    if now is None or base is None or base == 0 or pd.isna(now) or pd.isna(base):
        return None
    return (now / base - 1.0) * 100.0


def _bp(now: float | None, base: float | None) -> float | None:
    if now is None or base is None or pd.isna(now) or pd.isna(base):
        return None
    return (now - base) * 100.0


def streak(s: pd.Series) -> int:
    """연속 상승(+n) / 하락(-n) 거래일 수. 보합이 끼면 끊긴다."""
    d = np.sign(s.dropna().diff().dropna().to_numpy())
    if d.size == 0 or d[-1] == 0:
        return 0
    last = d[-1]
    n = 0
    for v in d[::-1]:
        if v != last:
            break
        n += 1
    return int(n * last)


def _runs(s: pd.Series) -> list[tuple[int, int, pd.Timestamp]]:
    """(부호, 길이, 마지막 날짜) 목록 — 시간순."""
    s = s.dropna()
    d = np.sign(s.diff().dropna())
    runs: list[tuple[int, int, pd.Timestamp]] = []
    for ts, v in d.items():
        v = int(v)
        if runs and runs[-1][0] == v and v != 0:
            sign, n, _ = runs[-1]
            runs[-1] = (sign, n + 1, ts)
        else:
            runs.append((v, 1, ts))
    return runs


def streak_record(s: pd.Series) -> dict:
    """현재 연속 상승/하락이 언제 이후 최장인지."""
    runs = _runs(s)
    if not runs or runs[-1][0] == 0:
        return {"streak": 0, "since": None, "longest_in_data": False}
    sign, n, _ = runs[-1]
    for r_sign, r_n, r_end in reversed(runs[:-1]):
        if r_sign == sign and r_n >= n:
            return {"streak": sign * n, "since": r_end, "since_len": r_n, "longest_in_data": False}
    return {"streak": sign * n, "since": None, "longest_in_data": True}


def snapshot_row(label: str, ticker: str, kind: str, s: pd.Series) -> dict | None:
    """한 자산의 대시보드 한 줄."""
    s = s.dropna()
    if len(s) < 2:
        return None
    asof = s.index[-1]
    last = float(s.iloc[-1])
    prev = float(s.iloc[-2])
    week = _last_on_or_before(s, asof - pd.Timedelta(days=7))
    month_start = pd.Timestamp(asof.year, asof.month, 1, tz=asof.tz)
    year_start = pd.Timestamp(asof.year, 1, 1, tz=asof.tz)
    mtd_base = _last_before(s, month_start)
    ytd_base = _last_before(s, year_start)
    window = s[s.index > asof - pd.Timedelta(days=365)]
    high = float(window.max())
    high_date = window.idxmax()

    change = _bp if kind == "rate" else _pct
    dd = None if kind in ("rate", "vol") else _pct(last, high)
    recovery = None
    if dd is not None and dd < 0:
        recovery = (1.0 / (1.0 + dd / 100.0) - 1.0) * 100.0
    return {
        "구분": label,
        "티커": ticker,
        "종류": kind,
        "기준일": asof.date() if hasattr(asof, "date") else asof,
        "현재값": last,
        "1일": change(last, prev),
        "1주": change(last, week),
        "월초대비": change(last, mtd_base),
        "연초대비": change(last, ytd_base),
        "52주고점대비(%)": dd,
        "52주고점일": high_date.date() if hasattr(high_date, "date") else high_date,
        "회복필요상승률(%)": recovery,
        "연속(일)": streak(s),
    }


def market_snapshot(closes: pd.DataFrame, assets: list[tuple[str, str, str]]) -> pd.DataFrame:
    rows = []
    for label, ticker, kind in assets:
        if ticker not in closes.columns:
            continue
        row = snapshot_row(label, ticker, kind, closes[ticker])
        if row:
            rows.append(row)
    return pd.DataFrame(rows)


def monthly_history(s: pd.Series) -> pd.DataFrame:
    """월별 수익률(%) — 마지막 행은 진행 중인 달일 수 있다."""
    s = s.dropna()
    if s.empty:
        return pd.DataFrame(columns=["월", "수익률(%)", "진행중"])
    m = s.resample("ME").last()
    r = m.pct_change().dropna() * 100.0
    out = pd.DataFrame({"월": r.index.strftime("%Y-%m"), "수익률(%)": r.to_numpy()})
    out["진행중"] = False
    if len(out):
        last_ts = s.index[-1]
        month_end = (pd.Timestamp(last_ts.year, last_ts.month, 1) + pd.offsets.MonthEnd(0)).date()
        out.loc[out.index[-1], "진행중"] = last_ts.date() < month_end
    return out


def month_rank(s: pd.Series, top: int = 10) -> dict:
    """이번 달 수익률이 역사적으로 몇 번째인지, 마지막으로 이보다 나빴/좋았던 달."""
    hist = monthly_history(s)
    if hist.empty:
        return {}
    cur = hist.iloc[-1]
    cur_ret = float(cur["수익률(%)"])
    past = hist.iloc[:-1]
    worse_rank = int((hist["수익률(%)"] < cur_ret).sum()) + 1  # 1 = 가장 나쁨
    better_rank = int((hist["수익률(%)"] > cur_ret).sum()) + 1
    if cur_ret < 0:
        hit = past[past["수익률(%)"] <= cur_ret]
    else:
        hit = past[past["수익률(%)"] >= cur_ret]
    since = hit.iloc[-1] if not hit.empty else None
    worst = hist.nsmallest(top, "수익률(%)").copy()
    best = hist.nlargest(top, "수익률(%)").copy()
    return {
        "month": cur["월"],
        "partial": bool(cur["진행중"]),
        "return": cur_ret,
        "worse_rank": worse_rank,
        "better_rank": better_rank,
        "total": len(hist),
        "first_month": hist.iloc[0]["월"],
        "since_month": None if since is None else since["월"],
        "since_return": None if since is None else float(since["수익률(%)"]),
        "worst": worst,
        "best": best,
    }


def ytd_same_day(s: pd.Series) -> pd.DataFrame:
    """해마다 '같은 날짜까지의' 연초 대비 수익률."""
    s = s.dropna()
    if s.empty:
        return pd.DataFrame(columns=["연도", "연초대비(%)", "올해"])
    asof = s.index[-1]
    rows = []
    for y in range(s.index[0].year + 1, asof.year + 1):
        tz = asof.tz
        base = _last_before(s, pd.Timestamp(y, 1, 1, tz=tz))
        day = min(asof.day, 28) if asof.month == 2 else asof.day
        now = _last_on_or_before(s, pd.Timestamp(y, asof.month, day, 23, 59, tz=tz))
        r = _pct(now, base)
        if r is not None:
            rows.append({"연도": y, "연초대비(%)": r, "올해": y == asof.year})
    return pd.DataFrame(rows)


def required_recovery(drawdown_pct: float) -> float:
    """-X% 하락 후 원금 회복에 필요한 상승률(%)."""
    if drawdown_pct <= -100:
        return float("inf")
    return (1.0 / (1.0 + drawdown_pct / 100.0) - 1.0) * 100.0


def _fmt_change(v: float | None, kind: str) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{v:+.1f}bp" if kind == "rate" else f"{v:+.2f}%"


def headline_lines(snap: pd.DataFrame, rank: dict | None = None, rank_label: str = "") -> list[str]:
    """쇼츠·메모용 '오늘의 월가 3줄'."""
    if snap.empty:
        return []
    by = snap.set_index("티커")
    lines = []
    idx = [t for t in ("^DJI", "^GSPC", "^IXIC") if t in by.index]
    if idx:
        asof = by.loc[idx[0], "기준일"]
        parts = [f"{by.loc[t, '구분']} {_fmt_change(by.loc[t, '1일'], 'index')}" for t in idx]
        lines.append(f"[{asof}] " + " · ".join(parts))
    risk = []
    for t in ("^VIX", "^TNX", "DX-Y.NYB", "GC=F", "BTC-USD"):
        if t in by.index:
            r = by.loc[t]
            risk.append(f"{r['구분']} {r['현재값']:,.2f}({_fmt_change(r['1일'], r['종류'])})")
    if risk:
        lines.append(" · ".join(risk))
    if rank:
        tag = "진행 중" if rank.get("partial") else "확정"
        word = "최악" if rank["return"] < 0 else "최고"
        if rank.get("since_month"):
            tail = f"{rank['since_month']}({rank['since_return']:+.2f}%) 이후 {word}"
        else:
            tail = f"{rank['first_month']} 데이터 시작 이후 {word}"
        n = rank["worse_rank"] if rank["return"] < 0 else rank["better_rank"]
        lines.append(
            f"{rank_label} {rank['month']}({tag}) {rank['return']:+.2f}% → {tail}, "
            f"{rank['total']}개월 중 {'하위' if rank['return'] < 0 else '상위'} {n}위"
        )
    return lines
