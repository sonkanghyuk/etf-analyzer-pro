from __future__ import annotations
from datetime import date, timedelta
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
st.title("📊 ETF Analyzer Pro")
st.caption("ETF 티커를 입력하면 수익률·MDD·변동성·분배율·보수·상관관계·구성종목·중복도를 한 번에 비교합니다.")

with st.sidebar:
    st.header("분석 설정")
    ticker_text = st.text_area("ETF 티커", "QQQ, SCHD, SPY", height=90)
    tickers = []
    for x in ticker_text.replace("\n", ",").split(","):
        x = x.strip().upper()
        if x and x not in tickers:
            tickers.append(x)

    period = st.selectbox("분석 기간", ["1년", "3년", "5년", "10년"], index=2)
    years = {"1년": 1, "3년": 3, "5년": 5, "10년": 10}[period]
    end = date.today()
    start = end - timedelta(days=int(365.25 * years))
    risk_free = st.number_input("무위험수익률(연 %)", 0.0, 20.0, 0.0, 0.25)

    st.divider()
    st.subheader("구성종목 CSV (선택)")
    files = st.file_uploader("운용사 CSV 업로드", type=["csv"], accept_multiple_files=True)
    run = st.button("🚀 분석 실행", type="primary", use_container_width=True)

if not tickers:
    st.info("왼쪽에 ETF 티커를 입력하세요.")
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

with st.spinner("시장 데이터 불러오는 중..."):
    prices, closes = get_prices(tuple(tickers), str(start), str(end + timedelta(days=1)))

if prices.empty:
    st.error("가격 데이터를 불러오지 못했습니다. 티커 형식을 확인하세요.")
    st.stop()

available = [t for t in tickers if t in prices.columns and prices[t].notna().sum() >= 2]
missing = [t for t in tickers if t not in available]
if missing:
    st.warning("데이터 부족 티커: " + ", ".join(missing))
if not available:
    st.stop()

prices = prices[available]
closes = closes[[c for c in available if c in closes.columns]]

snapshots = {}
yields = {}
for t in available:
    snapshots[t] = get_snapshot(t)
    close = float(closes[t].dropna().iloc[-1]) if t in closes.columns and not closes[t].dropna().empty else None
    yields[t] = get_yield(t, close)

uploaded = []
if files:
    for f in files:
        try:
            try:
                raw = pd.read_csv(f, encoding="utf-8-sig")
            except UnicodeDecodeError:
                f.seek(0)
                raw = pd.read_csv(f, encoding="cp949")
            uploaded.append(normalize_holdings_csv(raw, f.name.rsplit(".", 1)[0].upper()))
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
        scope[t] = "업로드 CSV"
    elif not auto.empty and t in set(auto["etf"]):
        holding_parts.append(auto[auto["etf"] == t])
        scope[t] = snapshots[t].get("holdings_scope") or "자동 수집"
    else:
        scope[t] = "없음"
holdings = pd.concat(holding_parts, ignore_index=True) if holding_parts else pd.DataFrame(columns=["etf", "holding", "weight"])

rows = []
for t in available:
    m = performance_metrics(prices[t], risk_free / 100)
    dist_amt, dist_yield = yields[t]
    s = snapshots[t]
    rows.append({
        "티커": t,
        "ETF명": s.get("name") or t,
        "누적수익률(%)": m["return_pct"],
        "CAGR(%)": m["cagr_pct"],
        "연변동성(%)": m["volatility_pct"],
        "MDD(%)": m["mdd_pct"],
        "Sharpe": m["sharpe"],
        "12개월분배율(%)": dist_yield,
        "총보수추정(%)": s.get("expense_ratio_pct"),
        "AUM": s.get("aum"),
    })
summary = pd.DataFrame(rows)

t1, t2, t3, t4, t5 = st.tabs(["종합 요약", "수익률·MDD", "상관관계", "구성종목·중복도", "섹터"])

with t1:
    st.subheader("종합 성과 비교")
    fmt = {
        "누적수익률(%)": "{:.2f}", "CAGR(%)": "{:.2f}",
        "연변동성(%)": "{:.2f}", "MDD(%)": "{:.2f}",
        "Sharpe": "{:.2f}", "12개월분배율(%)": "{:.2f}",
        "총보수추정(%)": "{:.3f}", "AUM": "{:,.0f}",
    }
    st.dataframe(summary.style.format(fmt, na_rep="-"), use_container_width=True, hide_index=True)
    for _, r in summary.iterrows():
        st.markdown(f"### {r['티커']} · {r['ETF명']}")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("CAGR", "-" if pd.isna(r["CAGR(%)"]) else f"{r['CAGR(%)']:.2f}%")
        c2.metric("MDD", "-" if pd.isna(r["MDD(%)"]) else f"{r['MDD(%)']:.2f}%")
        c3.metric("변동성", "-" if pd.isna(r["연변동성(%)"]) else f"{r['연변동성(%)']:.2f}%")
        c4.metric("12M 분배율", "-" if pd.isna(r["12개월분배율(%)"]) else f"{r['12개월분배율(%)']:.2f}%")
        c5.metric("총보수", "-" if pd.isna(r["총보수추정(%)"]) else f"{r['총보수추정(%)']:.3f}%")
        st.caption(f"구성종목 데이터: {scope[r['티커']]}")

with t2:
    st.subheader("누적 성과 (시작=100)")
    st.line_chart(normalized_prices(prices), use_container_width=True)
    st.subheader("Drawdown (%)")
    st.line_chart(drawdown_frame(prices), use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 연도별 수익률")
        st.dataframe(annual_returns(prices).style.format("{:.2f}", na_rep="-"), use_container_width=True)
    with c2:
        st.markdown("#### 최근 월별 수익률")
        st.dataframe(monthly_returns(prices).tail(24).style.format("{:.2f}", na_rep="-"), use_container_width=True)

with t3:
    st.subheader("일간 수익률 상관관계")
    corr = prices.pct_change().corr()
    st.dataframe(corr.style.format("{:.2f}").background_gradient(axis=None, vmin=-1, vmax=1), use_container_width=True)

with t4:
    if holdings.empty:
        st.info("자동 구성종목 데이터가 없으면 운용사 CSV를 업로드하세요.")
    else:
        for t in available:
            h = holdings[holdings["etf"] == t].sort_values("weight", ascending=False)
            if h.empty:
                continue
            st.markdown(f"### {t}")
            c1, c2, c3 = st.columns(3)
            c1.metric("확보 종목", len(h))
            c2.metric("Top10 집중도", f"{h.head(10)['weight'].sum():.2f}%")
            hv = hhi(h["weight"])
            c3.metric("HHI", f"{hv:,.0f}", concentration_label(hv))
            st.bar_chart(h.head(15).set_index("holding")["weight"], horizontal=True)
            st.dataframe(h.head(30), use_container_width=True, hide_index=True)

        eligible = [t for t in available if not holdings[holdings["etf"] == t].empty]
        if len(eligible) >= 2:
            st.subheader("가중 구성종목 중복도")
            ov = overlap_matrix(holdings, eligible)
            st.dataframe(ov.style.format("{:.1f}%").background_gradient(axis=None, vmin=0, vmax=100), use_container_width=True)

with t5:
    any_sector = False
    for t in available:
        sec = snapshots[t].get("sectors") or {}
        if sec:
            any_sector = True
            s = pd.Series(sec).sort_values(ascending=False)
            st.markdown(f"### {t}")
            st.bar_chart(s, horizontal=True)
            st.dataframe(s.rename("비중(%)").reset_index(names="섹터"), use_container_width=True, hide_index=True)
    if not any_sector:
        st.info("섹터 데이터가 제공되지 않는 ETF가 있습니다. sector/섹터 열이 포함된 CSV로 보완할 수 있습니다.")

st.divider()
st.download_button("성과 요약 CSV 다운로드", summary.to_csv(index=False).encode("utf-8-sig"), "etf_performance_summary.csv", "text/csv")
st.caption("데이터: Yahoo Finance(yfinance) + 사용자가 업로드한 운용사 CSV. 자동 구성종목은 Top Holdings 수준일 수 있습니다.")
