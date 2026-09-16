from __future__ import annotations
from datetime import date, timedelta
import re
import numpy as np
import pandas as pd
import streamlit as st

from analytics import (
    performance_metrics, normalized_prices, drawdown_frame,
    overlap_matrix, hhi, concentration_label, monthly_returns, annual_returns,
)
from data_sources import (
    download_prices, trailing_12m_distribution_yield,
    fetch_fund_snapshot, normalize_holdings_csv,
)

st.set_page_config(page_title="ETF Analyzer Pro", page_icon="📊", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.35rem; padding-bottom: 3rem;}
[data-testid="stMetricValue"] {font-size: 1.7rem;}
[data-testid="stMetricLabel"] {font-size: 0.92rem;}
</style>
""", unsafe_allow_html=True)


def normalize_ticker(text: str) -> str:
    """한국 6자리 종목코드는 Yahoo Finance KSE 형식(.KS)으로 자동 변환."""
    x = str(text).strip().upper()
    x = x.replace("KRX:", "").replace("KSE:", "")
    if re.fullmatch(r"\d{6}", x):
        return f"{x}.KS"
    return x


def display_ticker(ticker: str) -> str:
    if ticker.endswith(".KS") and ticker[:-3].isdigit():
        return ticker[:-3]
    return ticker


def resolve_dates(period: str, today: date) -> tuple[date, date]:
    if period == "1개월":
        return today - timedelta(days=35), today
    if period == "3개월":
        return today - timedelta(days=100), today
    if period == "6개월":
        return today - timedelta(days=190), today
    if period == "YTD":
        return date(today.year, 1, 1), today
    years = {"1년": 1, "3년": 3, "5년": 5, "10년": 10}.get(period, 5)
    return today - timedelta(days=int(365.25 * years)), today


st.title("📊 ETF Analyzer Pro")
st.caption("미국 ETF와 국내 상장 ETF를 함께 비교합니다. 국내 ETF는 6자리 종목코드만 입력해도 됩니다.")

with st.sidebar:
    st.header("분석 설정")
    ticker_text = st.text_area(
        "ETF 티커 / 국내 종목코드",
        "QQQ, SCHD, SPY",
        height=100,
        help="미국 ETF: QQQ, SCHD / 국내 ETF: 360750, 379800처럼 6자리 코드만 입력",
    )

    tickers = []
    original_map = {}
    for x in ticker_text.replace("\n", ",").split(","):
        raw = x.strip()
        if not raw:
            continue
        resolved = normalize_ticker(raw)
        if resolved not in tickers:
            tickers.append(resolved)
            original_map[resolved] = raw.upper()

    st.caption("🇰🇷 국내 ETF 예: 360750(TIGER 미국S&P500), 379800(KODEX 미국S&P500), 133690(TIGER 미국나스닥100)")

    period = st.selectbox(
        "분석 기간",
        ["1개월", "3개월", "6개월", "YTD", "1년", "3년", "5년", "10년"],
        index=6,
    )
    today = date.today()
    start, end = resolve_dates(period, today)

    risk_free = st.number_input("무위험수익률(연 %)", 0.0, 20.0, 0.0, 0.25)

    st.divider()
    st.subheader("구성종목 CSV (선택)")
    files = st.file_uploader(
        "운용사 CSV 업로드",
        type=["csv"],
        accept_multiple_files=True,
        help="국내 ETF는 Yahoo에서 구성종목/섹터가 비어 있을 수 있어 운용사 CSV 업로드를 권장합니다.",
    )
    run = st.button("🚀 분석 실행", type="primary", use_container_width=True)

if not tickers:
    st.info("왼쪽에 ETF 티커 또는 국내 6자리 종목코드를 입력하세요.")
    st.stop()

@st.cache_data(ttl="30m", show_spinner=False)
def get_prices(tickers_tuple, start_iso, end_iso):
    return download_prices(list(tickers_tuple), start_iso, end_iso)

@st.cache_data(ttl="6h", show_spinner=False)
def get_snapshot(ticker):
    return fetch_fund_snapshot(ticker)

@st.cache_data(ttl="6h", show_spinner=False)
def get_yield(ticker, close):
    return trailing_12m_distribution_yield(ticker, close)

if run:
    st.cache_data.clear()

try:
    with st.spinner("시장 데이터 불러오는 중..."):
        prices, closes = get_prices(tuple(tickers), str(start), str(end + timedelta(days=1)))
except Exception as e:
    st.error("Yahoo Finance 가격 데이터를 불러오는 중 오류가 발생했습니다.")
    st.code(str(e))
    st.info("미국 ETF는 QQQ처럼, 국내 ETF는 360750처럼 6자리 코드만 입력해 보세요.")
    st.stop()

if prices.empty:
    st.error("가격 데이터를 불러오지 못했습니다. 티커 또는 국내 종목코드를 확인하거나 잠시 뒤 다시 시도하세요.")
    st.stop()

available = [t for t in tickers if t in prices.columns and prices[t].notna().sum() >= 2]
missing = [t for t in tickers if t not in available]
if missing:
    st.warning("데이터 부족/미지원 종목: " + ", ".join(display_ticker(x) for x in missing))
if not available:
    st.stop()

prices = prices[available]
closes = closes[[c for c in available if c in closes.columns]]

snapshots = {}
yields = {}
progress = st.progress(0, text="ETF 상세정보 불러오는 중...")
for idx, t in enumerate(available, start=1):
    try:
        snapshots[t] = get_snapshot(t)
    except Exception as e:
        snapshots[t] = {
            "ticker": t, "name": t, "expense_ratio_pct": None,
            "aum": None, "category": None,
            "holdings": pd.DataFrame(columns=["etf", "holding", "weight"]),
            "sectors": {}, "holdings_scope": "없음", "error": str(e),
        }
    close = float(closes[t].dropna().iloc[-1]) if t in closes.columns and not closes[t].dropna().empty else None
    try:
        yields[t] = get_yield(t, close)
    except Exception:
        yields[t] = (None, None)
    progress.progress(idx / len(available), text=f"{display_ticker(t)} 정보 확인 중...")
progress.empty()

uploaded = []
if files:
    for f in files:
        try:
            try:
                raw = pd.read_csv(f, encoding="utf-8-sig")
            except UnicodeDecodeError:
                f.seek(0)
                raw = pd.read_csv(f, encoding="cp949")
            fallback = normalize_ticker(f.name.rsplit(".", 1)[0].upper())
            part = normalize_holdings_csv(raw, fallback)
            if "etf" in part.columns:
                part["etf"] = part["etf"].map(normalize_ticker)
            uploaded.append(part)
        except Exception as e:
            st.warning(f"{f.name}: {e}")
manual = pd.concat(uploaded, ignore_index=True) if uploaded else pd.DataFrame()

auto_parts = []
for t in available:
    h = snapshots[t].get("holdings")
    if isinstance(h, pd.DataFrame) and not h.empty:
        auto_parts.append(h)
auto = pd.concat(auto_parts, ignore_index=True) if auto_parts else pd.DataFrame(columns=["etf", "holding", "weight"])

holding_parts, scope = [], {}
for t in available:
    if not manual.empty and t in set(manual["etf"]):
        holding_parts.append(manual[manual["etf"] == t])
        scope[t] = "업로드 CSV (전체 구성종목 분석 가능)"
    elif not auto.empty and t in set(auto["etf"]):
        holding_parts.append(auto[auto["etf"] == t])
        scope[t] = snapshots[t].get("holdings_scope") or "자동 수집"
    else:
        scope[t] = "구성종목 데이터 없음"
holdings = pd.concat(holding_parts, ignore_index=True) if holding_parts else pd.DataFrame(columns=["etf", "holding", "weight"])

rows = []
for t in available:
    m = performance_metrics(prices[t], risk_free / 100)
    dist_amt, dist_yield = yields[t]
    s = snapshots[t]
    rows.append({
        "티커": display_ticker(t),
        "Yahoo티커": t,
        "ETF명": s.get("name") or t,
        "기간수익률(%)": m["return_pct"],
        "CAGR(%)": m["cagr_pct"],
        "연변동성(%)": m["volatility_pct"],
        "MDD(%)": m["mdd_pct"],
        "Sharpe": m["sharpe"],
        "12M실분배율(%)": dist_yield,
        "총보수추정(%)": s.get("expense_ratio_pct"),
        "AUM": s.get("aum"),
    })
summary = pd.DataFrame(rows)

st.success("가격 데이터 로딩 완료: " + ", ".join(display_ticker(x) for x in available))

if any(t.endswith(".KS") for t in available):
    st.info("🇰🇷 국내 ETF는 가격·수익률·MDD·변동성·상관관계 분석이 가능합니다. 다만 총보수·구성종목·섹터는 Yahoo 제공 범위가 제한될 수 있어 공란이면 운용사 CSV로 보완하세요.")

st.caption("※ 12M 실분배율 = 최근 12개월 실제 분배금 합계 ÷ 최신 종가. SEC Yield와는 다른 지표입니다.")

t0, t1, t2, t3, t4, t5 = st.tabs([
    "🎬 한 장 요약", "종합 요약", "수익률·MDD", "상관관계", "구성종목·중복도", "섹터"
])

with t0:
    st.subheader(f"🎬 ETF 비교 한 장 요약 · {period}")
    st.caption("유튜브 촬영/캡처용 화면입니다. 비교 대상의 핵심 성과와 위험 지표를 한 화면에서 확인할 수 있습니다.")

    yt_cols = ["티커", "ETF명", "기간수익률(%)", "CAGR(%)", "MDD(%)", "연변동성(%)", "12M실분배율(%)", "총보수추정(%)"]
    yt = summary[yt_cols].copy()
    st.dataframe(
        yt.style.format({
            "기간수익률(%)": "{:.2f}", "CAGR(%)": "{:.2f}", "MDD(%)": "{:.2f}",
            "연변동성(%)": "{:.2f}", "12M실분배율(%)": "{:.2f}", "총보수추정(%)": "{:.3f}",
        }, na_rep="-"),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### 누적 성과 · 시작값 100")
    chart_prices = normalized_prices(prices).rename(columns={t: display_ticker(t) for t in prices.columns})
    st.line_chart(chart_prices, use_container_width=True)

    if len(summary) >= 2:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 기간 수익률 비교")
            rbar = summary.set_index("티커")["기간수익률(%)"].dropna().sort_values(ascending=True)
            st.bar_chart(rbar, horizontal=True)
        with c2:
            st.markdown("#### MDD 비교")
            mbar = summary.set_index("티커")["MDD(%)"].dropna().sort_values(ascending=True)
            st.bar_chart(mbar, horizontal=True)

with t1:
    st.subheader("종합 성과 비교")
    fmt = {
        "기간수익률(%)": "{:.2f}", "CAGR(%)": "{:.2f}",
        "연변동성(%)": "{:.2f}", "MDD(%)": "{:.2f}",
        "Sharpe": "{:.2f}", "12M실분배율(%)": "{:.2f}",
        "총보수추정(%)": "{:.3f}", "AUM": "{:,.0f}",
    }
    table_cols = [c for c in summary.columns if c != "Yahoo티커"]
    st.dataframe(summary[table_cols].style.format(fmt, na_rep="-"), use_container_width=True, hide_index=True)

    for _, r in summary.iterrows():
        actual = r["Yahoo티커"]
        st.markdown(f"### {r['티커']} · {r['ETF명']}")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric(f"{period} 수익률", "-" if pd.isna(r["기간수익률(%)"]) else f"{r['기간수익률(%)']:.2f}%")
        c2.metric("CAGR", "-" if pd.isna(r["CAGR(%)"]) else f"{r['CAGR(%)']:.2f}%")
        c3.metric("MDD", "-" if pd.isna(r["MDD(%)"]) else f"{r['MDD(%)']:.2f}%")
        c4.metric("변동성", "-" if pd.isna(r["연변동성(%)"]) else f"{r['연변동성(%)']:.2f}%")
        c5.metric("12M 실분배율", "-" if pd.isna(r["12M실분배율(%)"]) else f"{r['12M실분배율(%)']:.2f}%")
        c6.metric("총보수", "-" if pd.isna(r["총보수추정(%)"]) else f"{r['총보수추정(%)']:.3f}%")
        st.caption(f"구성종목 데이터: {scope[actual]}")

with t2:
    st.subheader("누적 성과 (시작=100)")
    st.line_chart(normalized_prices(prices).rename(columns={t: display_ticker(t) for t in prices.columns}), use_container_width=True)
    st.subheader("Drawdown (%)")
    st.line_chart(drawdown_frame(prices).rename(columns={t: display_ticker(t) for t in prices.columns}), use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 연도별 수익률")
        annual = annual_returns(prices).rename(columns={t: display_ticker(t) for t in prices.columns})
        st.dataframe(annual.style.format("{:.2f}", na_rep="-"), use_container_width=True)
    with c2:
        st.markdown("#### 최근 월별 수익률")
        monthly = monthly_returns(prices).tail(24).rename(columns={t: display_ticker(t) for t in prices.columns})
        st.dataframe(monthly.style.format("{:.2f}", na_rep="-"), use_container_width=True)

with t3:
    st.subheader("일간 수익률 상관관계")
    corr = prices.pct_change().corr().rename(
        index={t: display_ticker(t) for t in prices.columns},
        columns={t: display_ticker(t) for t in prices.columns},
    )
    st.dataframe(corr.style.format("{:.2f}").background_gradient(axis=None, vmin=-1, vmax=1), use_container_width=True)
    st.caption("1에 가까울수록 같은 방향으로 움직이는 경향이 강하고, 0에 가까울수록 일간 움직임의 선형 관계가 약합니다.")

with t4:
    if holdings.empty:
        st.info("자동 구성종목 데이터가 없으면 운용사 CSV를 업로드하세요. 특히 국내 ETF는 CSV 업로드 방식이 더 정확합니다.")
    else:
        for t in available:
            h = holdings[holdings["etf"] == t].sort_values("weight", ascending=False)
            if h.empty:
                continue
            st.markdown(f"### {display_ticker(t)}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("확보 종목", len(h))
            c2.metric("확보 비중", f"{h['weight'].sum():.2f}%")
            c3.metric("Top10 집중도", f"{h.head(10)['weight'].sum():.2f}%")
            hv = hhi(h["weight"])
            c4.metric("HHI", f"{hv:,.0f}", concentration_label(hv))
            st.caption(scope[t])
            st.bar_chart(h.head(15).set_index("holding")["weight"], horizontal=True)
            show_cols = [c for c in ["holding", "weight", "sector", "country"] if c in h.columns]
            st.dataframe(h[show_cols].head(30), use_container_width=True, hide_index=True)

        eligible = [t for t in available if not holdings[holdings["etf"] == t].empty]
        if len(eligible) >= 2:
            st.subheader("가중 구성종목 중복도")
            ov = overlap_matrix(holdings, eligible)
            ov = ov.rename(
                index={t: display_ticker(t) for t in eligible},
                columns={t: display_ticker(t) for t in eligible},
            )
            st.dataframe(ov.style.format("{:.1f}%").background_gradient(axis=None, vmin=0, vmax=100), use_container_width=True)
            st.caption("자동 Top Holdings만 확보된 경우에는 전체 포트폴리오가 아니라 확보된 종목 기준 중복도입니다.")

with t5:
    any_sector = False
    for t in available:
        sec = snapshots[t].get("sectors") or {}
        h = holdings[holdings["etf"] == t] if not holdings.empty else pd.DataFrame()

        if not h.empty and "sector" in h.columns and h["sector"].replace("", np.nan).notna().any():
            any_sector = True
            s = h.assign(sector=h["sector"].replace("", "미분류").fillna("미분류")).groupby("sector")["weight"].sum().sort_values(ascending=False)
            st.markdown(f"### {display_ticker(t)} · CSV 기준")
            st.bar_chart(s, horizontal=True)
            st.dataframe(s.rename("비중(%)").reset_index(), use_container_width=True, hide_index=True)
        elif sec:
            any_sector = True
            s = pd.Series(sec).sort_values(ascending=False)
            st.markdown(f"### {display_ticker(t)} · Yahoo Fund Data")
            st.bar_chart(s, horizontal=True)
            st.dataframe(s.rename("비중(%)").reset_index(names="섹터"), use_container_width=True, hide_index=True)

    if not any_sector:
        st.info("섹터 데이터가 제공되지 않습니다. 국내 ETF는 운용사 CSV에 sector/섹터 열을 넣어 업로드하면 분석할 수 있습니다.")

st.divider()
export_summary = summary.drop(columns=["Yahoo티커"], errors="ignore")
st.download_button(
    "성과 요약 CSV 다운로드",
    export_summary.to_csv(index=False).encode("utf-8-sig"),
    "etf_performance_summary.csv",
    "text/csv",
)
st.caption("데이터: Yahoo Finance(yfinance) + 사용자가 업로드한 운용사 CSV. 자동 구성종목은 Top Holdings 수준일 수 있습니다. 국내 ETF 가격 데이터도 Yahoo 지원 범위 내에서 제공됩니다.")
