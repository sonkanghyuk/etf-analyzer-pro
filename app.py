from __future__ import annotations

from datetime import date, timedelta
import re
import numpy as np
import pandas as pd
import streamlit as st

from analytics import (
    performance_metrics,
    normalized_prices,
    drawdown_frame,
    overlap_matrix,
    hhi,
    concentration_label,
    monthly_returns,
    annual_returns,
)
from data_sources import (
    download_prices,
    trailing_12m_distribution_yield,
    fetch_fund_snapshot,
    normalize_holdings_csv,
)

st.set_page_config(page_title="ETF Analyzer Pro", page_icon="📊", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.25rem; padding-bottom: 3rem;}
[data-testid="stMetricValue"] {font-size: 1.65rem;}
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


PRECISION_ALIASES = {
    "etf": ["etf", "ticker", "fund", "fund_ticker", "etf명", "etf이름", "종목코드"],
    "holding": ["holding", "security", "name", "company", "holding_name", "구성종목", "종목명", "보유종목"],
    "weight": ["weight", "weight_pct", "weight_percent", "비중", "비중(%)", "편입비중", "보유비중"],
    "sector": ["sector", "industry", "섹터", "업종"],
    "country": ["country", "nation", "국가", "지역"],
    "shares": ["shares", "quantity", "수량", "보유수량"],
    "market_value": ["market_value", "market value", "value", "평가금액", "시장가치"],
}


def _norm_col(s):
    return re.sub(r"\s+", "_", str(s).strip().lower())


def normalize_precision_csv(df: pd.DataFrame, fallback_etf: str) -> pd.DataFrame:
    normalized = {_norm_col(c): c for c in df.columns}
    rename = {}
    for standard, aliases in PRECISION_ALIASES.items():
        for alias in aliases:
            k = _norm_col(alias)
            if k in normalized:
                rename[normalized[k]] = standard
                break

    out = df.rename(columns=rename).copy()

    if "holding" not in out.columns or "weight" not in out.columns:
        raise ValueError("필수 열을 찾지 못했습니다. 최소 '구성종목(holding)'과 '비중(weight)' 열이 필요합니다.")

    if "etf" not in out.columns:
        out["etf"] = fallback_etf

    out["etf"] = out["etf"].astype(str).str.strip()
    out["holding"] = out["holding"].astype(str).str.strip()

    w = (
        out["weight"].astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
    )
    out["weight"] = pd.to_numeric(w, errors="coerce")
    valid = out["weight"].dropna()
    if not valid.empty and valid.max() <= 1.0 and valid.sum() <= 1.5:
        out["weight"] *= 100

    for col in ["shares", "market_value"]:
        if col in out.columns:
            out[col] = pd.to_numeric(
                out[col].astype(str).str.replace(",", "", regex=False),
                errors="coerce",
            )

    keep = [c for c in ["etf", "holding", "weight", "sector", "country", "shares", "market_value"] if c in out.columns]
    out = out[keep].dropna(subset=["weight"])
    out = out[(out["etf"] != "") & (out["holding"] != "")]

    agg = {"weight": "sum"}
    for c in ["sector", "country"]:
        if c in out.columns:
            agg[c] = lambda x: x.dropna().astype(str).iloc[0] if len(x.dropna()) else ""
    for c in ["shares", "market_value"]:
        if c in out.columns:
            agg[c] = "sum"

    return out.groupby(["etf", "holding"], as_index=False).agg(agg)


def precision_overlap_score(a: pd.DataFrame, b: pd.DataFrame) -> float:
    aa = a[["holding", "weight"]].copy()
    bb = b[["holding", "weight"]].copy()
    aa["key"] = aa["holding"].astype(str).str.strip().str.upper()
    bb["key"] = bb["holding"].astype(str).str.strip().str.upper()
    merged = aa.merge(bb, on="key", how="inner", suffixes=("_a", "_b"))
    if merged.empty:
        return 0.0
    return float(np.minimum(merged["weight_a"], merged["weight_b"]).sum())


def precision_overlap_matrix(df: pd.DataFrame, etfs: list[str]) -> pd.DataFrame:
    m = pd.DataFrame(index=etfs, columns=etfs, dtype=float)
    groups = {e: df[df["etf"] == e] for e in etfs}
    for a in etfs:
        for b in etfs:
            m.loc[a, b] = 100.0 if a == b else precision_overlap_score(groups[a], groups[b])
    return m


st.title("📊 ETF Analyzer Pro")
st.caption("티커 자동분석 + 운용사 CSV 정밀분석을 한 곳에서 사용할 수 있습니다.")

mode = st.sidebar.radio(
    "분석 모드",
    ["① 티커 자동분석", "② CSV 정밀분석"],
    index=0,
)
st.sidebar.caption("티커 자동분석: 미국·국내 ETF 가격/성과 분석 · CSV 정밀분석: 구성종목 파일 기반 중복도/집중도 분석")


if mode == "① 티커 자동분석":
    with st.sidebar:
        st.header("자동분석 설정")
        ticker_text = st.text_area(
            "ETF 티커 / 국내 종목코드",
            "QQQ, SCHD, SPY",
            height=100,
            help="미국 ETF: QQQ, SCHD / 국내 ETF: 360750, 379800처럼 6자리 코드만 입력",
        )

        tickers = []
        for x in ticker_text.replace("\n", ",").split(","):
            raw = x.strip()
            if not raw:
                continue
            resolved = normalize_ticker(raw)
            if resolved not in tickers:
                tickers.append(resolved)

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
            key="auto_holdings_files",
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
                "ticker": t,
                "name": t,
                "expense_ratio_pct": None,
                "aum": None,
                "category": None,
                "holdings": pd.DataFrame(columns=["etf", "holding", "weight"]),
                "sectors": {},
                "holdings_scope": "없음",
                "error": str(e),
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
    auto = (
        pd.concat(auto_parts, ignore_index=True)
        if auto_parts
        else pd.DataFrame(columns=["etf", "holding", "weight"])
    )

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

    holdings = (
        pd.concat(holding_parts, ignore_index=True)
        if holding_parts
        else pd.DataFrame(columns=["etf", "holding", "weight"])
    )

    rows = []
    for t in available:
        m = performance_metrics(prices[t], risk_free / 100)
        _, dist_yield = yields[t]
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
        st.info(
            "🇰🇷 국내 ETF는 가격·수익률·MDD·변동성·상관관계 분석이 가능합니다. "
            "총보수·구성종목·섹터가 공란이면 운용사 CSV로 보완하세요."
        )

    st.caption("※ 12M 실분배율 = 최근 12개월 실제 분배금 합계 ÷ 최신 종가. SEC Yield와는 다른 지표입니다.")

    t0, t1, t2, t3, t4, t5 = st.tabs([
        "🎬 한 장 요약",
        "종합 요약",
        "수익률·MDD",
        "상관관계",
        "구성종목·중복도",
        "섹터",
    ])

    with t0:
        st.subheader(f"🎬 ETF 비교 한 장 요약 · {period}")
        st.caption("유튜브 촬영/캡처용 핵심 비교 화면입니다.")

        yt_cols = [
            "티커", "ETF명", "기간수익률(%)", "CAGR(%)", "MDD(%)",
            "연변동성(%)", "12M실분배율(%)", "총보수추정(%)",
        ]
        st.dataframe(
            summary[yt_cols].style.format({
                "기간수익률(%)": "{:.2f}",
                "CAGR(%)": "{:.2f}",
                "MDD(%)": "{:.2f}",
                "연변동성(%)": "{:.2f}",
                "12M실분배율(%)": "{:.2f}",
                "총보수추정(%)": "{:.3f}",
            }, na_rep="-"),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("#### 누적 성과 · 시작값 100")
        chart_prices = normalized_prices(prices).rename(
            columns={t: display_ticker(t) for t in prices.columns}
        )
        st.line_chart(chart_prices, use_container_width=True)

        if len(summary) >= 2:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 기간 수익률 비교")
                rbar = summary.set_index("티커")["기간수익률(%)"].dropna().sort_values()
                st.bar_chart(rbar, horizontal=True)
            with c2:
                st.markdown("#### MDD 비교")
                mbar = summary.set_index("티커")["MDD(%)"].dropna().sort_values()
                st.bar_chart(mbar, horizontal=True)

    with t1:
        st.subheader("종합 성과 비교")
        fmt = {
            "기간수익률(%)": "{:.2f}",
            "CAGR(%)": "{:.2f}",
            "연변동성(%)": "{:.2f}",
            "MDD(%)": "{:.2f}",
            "Sharpe": "{:.2f}",
            "12M실분배율(%)": "{:.2f}",
            "총보수추정(%)": "{:.3f}",
            "AUM": "{:,.0f}",
        }
        table_cols = [c for c in summary.columns if c != "Yahoo티커"]
        st.dataframe(
            summary[table_cols].style.format(fmt, na_rep="-"),
            use_container_width=True,
            hide_index=True,
        )

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
            st.caption(f"구성종목 데이터: {scope.get(actual, '없음')}")

    with t2:
        st.subheader("누적 성과 (시작=100)")
        st.line_chart(
            normalized_prices(prices).rename(columns={t: display_ticker(t) for t in prices.columns}),
            use_container_width=True,
        )

        st.subheader("Drawdown (%)")
        st.line_chart(
            drawdown_frame(prices).rename(columns={t: display_ticker(t) for t in prices.columns}),
            use_container_width=True,
        )

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 연도별 수익률")
            ann = annual_returns(prices).rename(columns={t: display_ticker(t) for t in prices.columns})
            st.dataframe(ann.style.format("{:.2f}", na_rep="-"), use_container_width=True)
        with c2:
            st.markdown("#### 최근 월별 수익률")
            mon = monthly_returns(prices).tail(24).rename(columns={t: display_ticker(t) for t in prices.columns})
            st.dataframe(mon.style.format("{:.2f}", na_rep="-"), use_container_width=True)

    with t3:
        st.subheader("일간 수익률 상관관계")
        corr = prices.pct_change().corr()
        corr.index = [display_ticker(x) for x in corr.index]
        corr.columns = [display_ticker(x) for x in corr.columns]
        st.dataframe(
            corr.style.format("{:.2f}").background_gradient(axis=None, vmin=-1, vmax=1),
            use_container_width=True,
        )

    with t4:
        if holdings.empty:
            st.info("자동 구성종목 데이터가 없으면 운용사 CSV를 업로드하세요.")
        else:
            for t in available:
                h = holdings[holdings["etf"] == t].sort_values("weight", ascending=False)
                if h.empty:
                    continue
                st.markdown(f"### {display_ticker(t)}")
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
                ov.index = [display_ticker(x) for x in ov.index]
                ov.columns = [display_ticker(x) for x in ov.columns]
                st.dataframe(
                    ov.style.format("{:.1f}%").background_gradient(axis=None, vmin=0, vmax=100),
                    use_container_width=True,
                )
                st.caption("자동 수집 구성종목이 Top Holdings뿐이면 중복도 역시 확보된 종목 기준입니다.")

    with t5:
        any_sector = False
        for t in available:
            h = holdings[holdings["etf"] == t] if not holdings.empty else pd.DataFrame()
            if not h.empty and "sector" in h.columns and h["sector"].replace("", np.nan).notna().any():
                sec = (
                    h.assign(sector=h["sector"].replace("", "미분류").fillna("미분류"))
                    .groupby("sector")["weight"]
                    .sum()
                    .sort_values(ascending=False)
                )
                any_sector = True
                st.markdown(f"### {display_ticker(t)} · CSV 기준")
                st.bar_chart(sec, horizontal=True)
                st.dataframe(sec.rename("비중(%)").reset_index(), use_container_width=True, hide_index=True)
            elif snapshots[t].get("sectors"):
                sec = pd.Series(snapshots[t]["sectors"]).sort_values(ascending=False)
                any_sector = True
                st.markdown(f"### {display_ticker(t)} · Yahoo Fund Data")
                st.bar_chart(sec, horizontal=True)
                st.dataframe(sec.rename("비중(%)").reset_index(names="섹터"), use_container_width=True, hide_index=True)

        if not any_sector:
            st.info("섹터 데이터를 가져오지 못했습니다. sector/섹터 열이 포함된 구성종목 CSV를 업로드하세요.")

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "성과 요약 CSV",
            summary.drop(columns=["Yahoo티커"], errors="ignore").to_csv(index=False).encode("utf-8-sig"),
            "etf_performance_summary.csv",
            "text/csv",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "가격 데이터 CSV",
            prices.rename(columns={t: display_ticker(t) for t in prices.columns}).to_csv().encode("utf-8-sig"),
            "etf_prices.csv",
            "text/csv",
            use_container_width=True,
        )
    with c3:
        st.download_button(
            "상관계수 CSV",
            prices.pct_change().corr().to_csv().encode("utf-8-sig"),
            "etf_correlation.csv",
            "text/csv",
            use_container_width=True,
        )


else:
    with st.sidebar:
        st.header("CSV 정밀분석 설정")
        top_n = st.slider("Top N 구성종목", 5, 30, 10)
        min_weight = st.number_input("표시 최소 비중(%)", min_value=0.0, value=0.0, step=0.1)
        st.caption("가격 데이터 없이 운용사 구성종목 CSV만으로 분석합니다.")

    st.subheader("📁 운용사 구성종목 CSV 정밀분석")
    st.caption("처음 만든 ETF 분석기 기능을 그대로 통합했습니다. 여러 ETF 파일을 한 번에 올려 비교할 수 있습니다.")

    with st.expander("CSV 형식 / 인식 가능한 열 보기"):
        st.markdown("""
**필수**
- `ETF` / `ticker` — 없어도 됨. 없으면 파일명을 ETF명으로 사용
- `구성종목` / `holding`
- `비중` / `weight`

**선택**
- `sector` / `섹터`
- `country` / `국가`
- `shares` / `수량`
- `market_value` / `평가금액`

비중은 `7.5`, `7.5%`, 또는 파일 전체가 0~1 비율이면 `0.075` 형식도 자동 인식합니다.
        """)

    precision_files = st.file_uploader(
        "ETF 구성종목 CSV를 1개 이상 업로드",
        type=["csv"],
        accept_multiple_files=True,
        key="precision_files",
    )

    sample = pd.DataFrame({
        "ETF": ["ALPHA"] * 5 + ["BETA"] * 5,
        "구성종목": [
            "NVIDIA", "Microsoft", "Apple", "Broadcom", "Amazon",
            "NVIDIA", "Microsoft", "TSMC", "Meta", "Alphabet",
        ],
        "비중": [18, 15, 12, 10, 8, 20, 12, 11, 9, 8],
        "섹터": [
            "반도체", "소프트웨어", "하드웨어", "반도체", "인터넷",
            "반도체", "소프트웨어", "반도체", "인터넷", "인터넷",
        ],
        "국가": ["미국", "미국", "미국", "미국", "미국", "미국", "미국", "대만", "미국", "미국"],
    })

    if not precision_files:
        st.info("CSV 파일을 올리면 분석이 시작됩니다. 형식을 확인하려면 샘플 파일을 내려받아 보세요.")
        st.download_button(
            "샘플 CSV 다운로드",
            sample.to_csv(index=False).encode("utf-8-sig"),
            "sample_etf_holdings.csv",
            "text/csv",
        )
        st.stop()

    frames = []
    errors = []
    for f in precision_files:
        try:
            try:
                raw = pd.read_csv(f, encoding="utf-8-sig")
            except UnicodeDecodeError:
                f.seek(0)
                raw = pd.read_csv(f, encoding="cp949")

            fallback = f.name.rsplit(".", 1)[0]
            frames.append(normalize_precision_csv(raw, fallback))
        except Exception as e:
            errors.append(f"{f.name}: {e}")

    for err in errors:
        st.error(err)

    if not frames:
        st.stop()

    df = pd.concat(frames, ignore_index=True)
    etfs = sorted(df["etf"].astype(str).unique().tolist())

    selected = st.multiselect("비교할 ETF", etfs, default=etfs)
    if not selected:
        st.warning("분석할 ETF를 1개 이상 선택하세요.")
        st.stop()

    view = df[df["etf"].isin(selected)].copy()

    p1, p2, p3, p4, p5 = st.tabs([
        "요약",
        "구성종목",
        "섹터·국가",
        "ETF 중복도",
        "데이터 내보내기",
    ])

    with p1:
        st.subheader("ETF 요약")
        rows = []
        for etf in selected:
            g = view[view["etf"] == etf].sort_values("weight", ascending=False)
            hv = hhi(g["weight"])
            rows.append({
                "ETF": etf,
                "구성종목 수": len(g),
                "비중 합계(%)": g["weight"].sum(),
                "Top10 집중도(%)": g.head(10)["weight"].sum(),
                "최대 종목 비중(%)": g["weight"].max(),
                "HHI": hv,
                "집중도": concentration_label(hv),
            })

        summary_csv = pd.DataFrame(rows)
        st.dataframe(
            summary_csv.style.format({
                "비중 합계(%)": "{:.2f}",
                "Top10 집중도(%)": "{:.2f}",
                "최대 종목 비중(%)": "{:.2f}",
                "HHI": "{:.0f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        for etf in selected:
            g = view[view["etf"] == etf].sort_values("weight", ascending=False)
            total = g["weight"].sum()
            st.markdown(f"### {etf}")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("구성종목 수", f"{len(g):,}")
            c2.metric("비중 합계", f"{total:.2f}%")
            c3.metric("Top10 집중도", f"{g.head(10)['weight'].sum():.2f}%")
            c4.metric("최대 종목", f"{g['weight'].max():.2f}%")
            hv = hhi(g["weight"])
            c5.metric("HHI", f"{hv:,.0f}", concentration_label(hv))
            if abs(total - 100) > 3:
                st.caption("※ 비중 합계가 100%와 차이가 큽니다. 일부 종목만 포함됐거나 현금/기타 자산이 빠졌을 수 있습니다.")

    with p2:
        st.subheader("Top 구성종목")
        for etf in selected:
            g = (
                view[(view["etf"] == etf) & (view["weight"] >= min_weight)]
                .sort_values("weight", ascending=False)
                .head(top_n)
            )
            st.markdown(f"### {etf}")
            st.bar_chart(g.set_index("holding")["weight"], horizontal=True)
            cols = [c for c in ["holding", "weight", "sector", "country", "shares", "market_value"] if c in g.columns]
            rename = {
                "holding": "구성종목",
                "weight": "비중(%)",
                "sector": "섹터",
                "country": "국가",
                "shares": "수량",
                "market_value": "평가금액",
            }
            st.dataframe(g[cols].rename(columns=rename), use_container_width=True, hide_index=True)

    with p3:
        st.subheader("섹터·국가 비중")
        dimension = st.radio(
            "분류 기준",
            ["sector", "country"],
            format_func=lambda x: "섹터" if x == "sector" else "국가",
            horizontal=True,
        )
        label = "섹터" if dimension == "sector" else "국가"

        if dimension not in view.columns:
            st.info(f"업로드한 CSV에 {label} 열이 없습니다.")
        else:
            grouped = (
                view.assign(**{dimension: view[dimension].replace("", "미분류").fillna("미분류")})
                .groupby(["etf", dimension], as_index=False)["weight"]
                .sum()
            )
            for etf in selected:
                g = grouped[grouped["etf"] == etf].sort_values("weight", ascending=False)
                st.markdown(f"### {etf}")
                st.bar_chart(g.set_index(dimension)["weight"], horizontal=True)
                st.dataframe(
                    g[[dimension, "weight"]].rename(columns={dimension: label, "weight": "비중(%)"}),
                    use_container_width=True,
                    hide_index=True,
                )

    with p4:
        st.subheader("ETF 간 가중 구성종목 중복도")
        if len(selected) < 2:
            st.info("ETF를 2개 이상 선택해야 중복도를 계산할 수 있습니다.")
        else:
            ov = precision_overlap_matrix(view, selected)
            st.dataframe(
                ov.style.format("{:.1f}%").background_gradient(axis=None, vmin=0, vmax=100),
                use_container_width=True,
            )
            st.caption("중복도 = 동일 종목마다 min(ETF A 비중, ETF B 비중)을 합산. 전체 구성종목 CSV일수록 정확합니다.")

            pairs = []
            for i, a in enumerate(selected):
                for b in selected[i + 1:]:
                    pairs.append((a, b, float(ov.loc[a, b])))
            pairs.sort(key=lambda x: x[2], reverse=True)

            if pairs:
                labels = [f"{a} ↔ {b} · {score:.1f}%" for a, b, score in pairs]
                choice = st.selectbox("공통 종목 상세 보기", labels)
                a, b, _ = pairs[labels.index(choice)]

                ha = view[view["etf"] == a][["holding", "weight"]].copy()
                hb = view[view["etf"] == b][["holding", "weight"]].copy()
                ha["key"] = ha["holding"].str.strip().str.upper()
                hb["key"] = hb["holding"].str.strip().str.upper()
                common = ha.merge(hb, on="key", suffixes=(f"_{a}", f"_{b}"))
                common["공통노출(%)"] = np.minimum(common[f"weight_{a}"], common[f"weight_{b}"])
                common = common.sort_values("공통노출(%)", ascending=False)
                common = common.rename(columns={
                    f"holding_{a}": "구성종목",
                    f"weight_{a}": f"{a} 비중(%)",
                    f"weight_{b}": f"{b} 비중(%)",
                })
                show = ["구성종목", f"{a} 비중(%)", f"{b} 비중(%)", "공통노출(%)"]
                st.dataframe(common[show], use_container_width=True, hide_index=True)

    with p5:
        st.subheader("분석 데이터 내보내기")
        st.download_button(
            "정규화된 구성종목 CSV",
            view.to_csv(index=False).encode("utf-8-sig"),
            "etf_holdings_normalized.csv",
            "text/csv",
        )

        if len(selected) >= 2:
            ov = precision_overlap_matrix(view, selected)
            st.download_button(
                "ETF 중복도 매트릭스 CSV",
                ov.to_csv().encode("utf-8-sig"),
                "etf_overlap_matrix.csv",
                "text/csv",
            )

        summary_rows = []
        for etf in selected:
            g = view[view["etf"] == etf].sort_values("weight", ascending=False)
            hv = hhi(g["weight"])
            summary_rows.append({
                "ETF": etf,
                "구성종목수": len(g),
                "비중합계(%)": g["weight"].sum(),
                "Top10집중도(%)": g.head(10)["weight"].sum(),
                "최대종목비중(%)": g["weight"].max(),
                "HHI": hv,
                "집중도": concentration_label(hv),
            })
        st.download_button(
            "ETF 요약 CSV",
            pd.DataFrame(summary_rows).to_csv(index=False).encode("utf-8-sig"),
            "etf_precision_summary.csv",
            "text/csv",
        )

    st.divider()
    st.caption("CSV 정밀분석은 업로드한 구성종목 데이터만 사용합니다. 기준일과 현금/기타 자산 포함 여부는 운용사 원본 파일을 확인하세요.")
