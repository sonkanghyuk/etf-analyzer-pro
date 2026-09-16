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
.block-container {padding-top: 1.0rem; padding-bottom: 3rem;}
[data-testid="stMetricValue"] {font-size: 1.55rem;}
[data-testid="stMetricLabel"] {font-size: 0.9rem;}
@media (max-width: 700px) {
  .block-container {padding-left: 0.8rem; padding-right: 0.8rem; padding-top: 0.6rem;}
  h1 {font-size: 2rem !important;}
  h2 {font-size: 1.55rem !important;}
  h3 {font-size: 1.25rem !important;}
  [data-testid="stMetricValue"] {font-size: 1.25rem;}
}
</style>
""", unsafe_allow_html=True)


def normalize_ticker(text: str) -> str:
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


def _clean_name(s: str) -> str:
    return re.sub(r"[\s·ㆍ\-_&()/]+", "", str(s)).upper()


@st.cache_data(ttl="24h", show_spinner=False)
def get_korean_etf_master() -> pd.DataFrame:
    try:
        import FinanceDataReader as fdr
        try:
            df = fdr.EtfListing("KR")
        except Exception:
            df = fdr.StockListing("ETF/KR")

        if df is None or df.empty:
            return pd.DataFrame(columns=["Symbol", "Name"])

        cols = {str(c).lower(): c for c in df.columns}
        symbol_col = cols.get("symbol")
        name_col = cols.get("name")
        if symbol_col is None or name_col is None:
            return pd.DataFrame(columns=["Symbol", "Name"])

        out = df[[symbol_col, name_col]].copy()
        out.columns = ["Symbol", "Name"]
        out["Symbol"] = out["Symbol"].astype(str).str.extract(r"(\d{6})", expand=False)
        out["Name"] = out["Name"].astype(str).str.strip()
        out = out.dropna(subset=["Symbol"])
        out = out[(out["Name"] != "") & (out["Symbol"] != "")]
        out["검색키"] = out["Name"].map(_clean_name)
        out["label"] = out["Name"] + " (" + out["Symbol"] + ")"
        return out.drop_duplicates("Symbol").sort_values("Name").reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["Symbol", "Name", "검색키", "label"])


def resolve_korean_name(text: str, master: pd.DataFrame) -> tuple[str | None, list[str]]:
    raw = str(text).strip()
    if not raw or master.empty:
        return None, []
    key = _clean_name(raw)
    exact = master[master["검색키"] == key]
    if len(exact) == 1:
        return f"{exact.iloc[0]['Symbol']}.KS", []
    contains = master[master["검색키"].str.contains(re.escape(key), na=False)]
    if len(contains) == 1:
        return f"{contains.iloc[0]['Symbol']}.KS", []
    if len(contains) > 1:
        return None, contains.head(12)["label"].tolist()
    return None, []


def parse_direct_inputs(text: str, master: pd.DataFrame) -> tuple[list[str], dict[str, list[str]], list[str]]:
    tickers = []
    ambiguous = {}
    unresolved = []
    for token in re.split(r"[\n,]+", text):
        raw = token.strip()
        if not raw:
            continue
        if re.fullmatch(r"\d{6}", raw):
            resolved = f"{raw}.KS"
        elif raw.upper().endswith(".KS") and re.fullmatch(r"\d{6}\.KS", raw.upper()):
            resolved = raw.upper()
        elif re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-^=]*", raw):
            resolved = raw.upper()
        else:
            resolved, candidates = resolve_korean_name(raw, master)
            if resolved is None:
                if candidates:
                    ambiguous[raw] = candidates
                else:
                    unresolved.append(raw)
                continue
        if resolved not in tickers:
            tickers.append(resolved)
    return tickers, ambiguous, unresolved


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
    w = out["weight"].astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False).str.strip()
    out["weight"] = pd.to_numeric(w, errors="coerce")
    valid = out["weight"].dropna()
    if not valid.empty and valid.max() <= 1.0 and valid.sum() <= 1.5:
        out["weight"] *= 100
    for col in ["shares", "market_value"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col].astype(str).str.replace(",", "", regex=False), errors="coerce")
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

mode = st.sidebar.radio("분석 모드", ["① 티커 자동분석", "② CSV 정밀분석"], index=0)
st.sidebar.caption("자동분석: 미국·국내 ETF 성과 비교 · CSV 정밀분석: 구성종목 중복도/집중도 분석")

if mode == "① 티커 자동분석":
    master = get_korean_etf_master()

    st.subheader("🔎 ETF 검색")
    st.caption("스마트폰에서도 여기서 바로 검색할 수 있습니다. 국내 ETF는 한글명으로 검색하고, 미국 ETF는 티커를 직접 입력하세요.")

    selected_kr_labels = []
    if not master.empty:
        selected_kr_labels = st.multiselect(
            "🇰🇷 국내 상장 ETF 검색",
            options=master["label"].tolist(),
            placeholder="예: TIGER 미국S&P500",
            help="검색창에 ETF 이름 일부를 입력한 뒤 원하는 ETF를 선택하세요.",
        )
    else:
        st.warning("국내 ETF 목록을 불러오지 못했습니다. 6자리 종목코드는 직접 입력할 수 있습니다.")

    direct_text = st.text_area(
        "미국 ETF 티커 / 국내 6자리 코드 / 한글 ETF명 직접 입력",
        value="QQQ, SCHD, SPY",
        height=84,
        placeholder="QQQ, SCHD, TIGER 미국S&P500, 360750",
        help="쉼표 또는 줄바꿈으로 여러 종목을 입력할 수 있습니다.",
    )

    direct_tickers, ambiguous, unresolved = parse_direct_inputs(direct_text, master)
    selected_tickers = []
    if selected_kr_labels and not master.empty:
        chosen = master[master["label"].isin(selected_kr_labels)]
        selected_tickers = [f"{s}.KS" for s in chosen["Symbol"].tolist()]

    tickers = []
    for t in selected_tickers + direct_tickers:
        if t not in tickers:
            tickers.append(t)

    if ambiguous:
        for query, candidates in ambiguous.items():
            st.warning(f"'{query}'와 비슷한 ETF가 여러 개 있습니다: " + " · ".join(candidates[:8]))
    if unresolved:
        st.warning("찾지 못한 입력: " + ", ".join(unresolved))
    if tickers:
        st.caption("분석 대상: " + " · ".join(display_ticker(t) for t in tickers))

    with st.sidebar:
        st.header("자동분석 설정")
        period = st.selectbox("분석 기간", ["1개월", "3개월", "6개월", "YTD", "1년", "3년", "5년", "10년"], index=6)
        today = date.today()
        start, end = resolve_dates(period, today)
        risk_free = st.number_input("무위험수익률(연 %)", 0.0, 20.0, 0.0, 0.25)
        st.divider()
        st.subheader("구성종목 CSV (선택)")
        files = st.file_uploader("운용사 CSV 업로드", type=["csv"], accept_multiple_files=True, key="auto_holdings_files")
        run = st.button("🔄 데이터 새로고침", use_container_width=True)

    if not tickers:
        st.info("위 검색창에서 ETF를 선택하거나 티커/종목코드를 입력하세요.")
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
        st.error("가격 데이터를 불러오는 중 오류가 발생했습니다.")
        st.code(str(e))
        st.stop()

    if prices.empty:
        st.error("가격 데이터를 불러오지 못했습니다. 티커/종목코드를 확인하거나 잠시 뒤 다시 시도하세요.")
        st.stop()

    available = [t for t in tickers if t in prices.columns and prices[t].notna().sum() >= 2]
    missing = [t for t in tickers if t not in available]
    if missing:
        st.warning("가격 데이터 부족/미지원: " + ", ".join(display_ticker(x) for x in missing))
    if not available:
        st.stop()

    prices = prices[available]
    closes = closes[[c for c in available if c in closes.columns]]

    snapshots, yields = {}, {}
    progress = st.progress(0, text="ETF 상세정보 불러오는 중...")
    for idx, t in enumerate(available, start=1):
        try:
            snapshots[t] = get_snapshot(t)
        except Exception as e:
            snapshots[t] = {"ticker": t, "name": t, "expense_ratio_pct": None, "aum": None, "category": None, "holdings": pd.DataFrame(columns=["etf", "holding", "weight"]), "sectors": {}, "holdings_scope": "없음", "error": str(e)}
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
            scope[t] = "업로드 CSV"
        elif not auto.empty and t in set(auto["etf"]):
            holding_parts.append(auto[auto["etf"] == t])
            scope[t] = snapshots[t].get("holdings_scope") or "자동 수집"
        else:
            scope[t] = "구성종목 데이터 없음"
    holdings = pd.concat(holding_parts, ignore_index=True) if holding_parts else pd.DataFrame(columns=["etf", "holding", "weight"])

    kr_name_map = {}
    if not master.empty:
        kr_name_map = {f"{r.Symbol}.KS": r.Name for r in master.itertuples(index=False)}

    rows = []
    for t in available:
        m = performance_metrics(prices[t], risk_free / 100)
        _, dist_yield = yields[t]
        s = snapshots[t]
        rows.append({
            "티커": display_ticker(t),
            "Yahoo티커": t,
            "ETF명": kr_name_map.get(t) or s.get("name") or t,
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
    st.caption("※ 12M 실분배율 = 최근 12개월 실제 분배금 합계 ÷ 최신 종가. SEC Yield와는 다른 지표입니다.")

    t0, t1, t2, t3, t4, t5 = st.tabs(["🎬 한 장 요약", "종합 요약", "수익률·MDD", "상관관계", "구성종목·중복도", "섹터"])

    with t0:
        st.subheader(f"🎬 ETF 비교 한 장 요약 · {period}")
        yt_cols = ["티커", "ETF명", "기간수익률(%)", "CAGR(%)", "MDD(%)", "연변동성(%)", "12M실분배율(%)", "총보수추정(%)"]
        st.dataframe(summary[yt_cols].style.format({"기간수익률(%)": "{:.2f}", "CAGR(%)": "{:.2f}", "MDD(%)": "{:.2f}", "연변동성(%)": "{:.2f}", "12M실분배율(%)": "{:.2f}", "총보수추정(%)": "{:.3f}"}, na_rep="-"), use_container_width=True, hide_index=True)
        st.markdown("#### 누적 성과 · 시작값 100")
        st.line_chart(normalized_prices(prices).rename(columns={t: display_ticker(t) for t in prices.columns}), use_container_width=True)
        if len(summary) >= 2:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 기간 수익률 비교")
                st.bar_chart(summary.set_index("티커")["기간수익률(%)"].dropna().sort_values(), horizontal=True)
            with c2:
                st.markdown("#### MDD 비교")
                st.bar_chart(summary.set_index("티커")["MDD(%)"].dropna().sort_values(), horizontal=True)

    with t1:
        st.subheader("종합 성과 비교")
        fmt = {"기간수익률(%)": "{:.2f}", "CAGR(%)": "{:.2f}", "연변동성(%)": "{:.2f}", "MDD(%)": "{:.2f}", "Sharpe": "{:.2f}", "12M실분배율(%)": "{:.2f}", "총보수추정(%)": "{:.3f}", "AUM": "{:,.0f}"}
        cols = [c for c in summary.columns if c != "Yahoo티커"]
        st.dataframe(summary[cols].style.format(fmt, na_rep="-"), use_container_width=True, hide_index=True)

    with t2:
        st.subheader("누적 성과 (시작=100)")
        st.line_chart(normalized_prices(prices).rename(columns={t: display_ticker(t) for t in prices.columns}), use_container_width=True)
        st.subheader("Drawdown (%)")
        st.line_chart(drawdown_frame(prices).rename(columns={t: display_ticker(t) for t in prices.columns}), use_container_width=True)
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
        st.dataframe(corr.style.format("{:.2f}").background_gradient(axis=None, vmin=-1, vmax=1), use_container_width=True)

    with t4:
        if holdings.empty:
            st.info("자동 구성종목 데이터가 없으면 운용사 CSV를 업로드하세요.")
        else:
            for t in available:
                h = holdings[holdings["etf"] == t].sort_values("weight", ascending=False)
                if h.empty:
                    continue
                st.markdown(f"### {kr_name_map.get(t, display_ticker(t))}")
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
                st.dataframe(ov.style.format("{:.1f}%").background_gradient(axis=None, vmin=0, vmax=100), use_container_width=True)

    with t5:
        any_sector = False
        for t in available:
            h = holdings[holdings["etf"] == t] if not holdings.empty else pd.DataFrame()
            if not h.empty and "sector" in h.columns and h["sector"].replace("", np.nan).notna().any():
                sec = h.assign(sector=h["sector"].replace("", "미분류").fillna("미분류")).groupby("sector")["weight"].sum().sort_values(ascending=False)
                any_sector = True
                st.markdown(f"### {kr_name_map.get(t, display_ticker(t))} · CSV 기준")
                st.bar_chart(sec, horizontal=True)
                st.dataframe(sec.rename("비중(%)").reset_index(), use_container_width=True, hide_index=True)
            elif snapshots[t].get("sectors"):
                sec = pd.Series(snapshots[t]["sectors"]).sort_values(ascending=False)
                any_sector = True
                st.markdown(f"### {kr_name_map.get(t, display_ticker(t))} · Yahoo Fund Data")
                st.bar_chart(sec, horizontal=True)
                st.dataframe(sec.rename("비중(%)").reset_index(names="섹터"), use_container_width=True, hide_index=True)
        if not any_sector:
            st.info("섹터 데이터를 가져오지 못했습니다. sector/섹터 열이 포함된 구성종목 CSV를 업로드하세요.")

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("성과 요약 CSV", summary.drop(columns=["Yahoo티커"], errors="ignore").to_csv(index=False).encode("utf-8-sig"), "etf_performance_summary.csv", "text/csv", use_container_width=True)
    with c2:
        st.download_button("가격 데이터 CSV", prices.rename(columns={t: display_ticker(t) for t in prices.columns}).to_csv().encode("utf-8-sig"), "etf_prices.csv", "text/csv", use_container_width=True)
    with c3:
        st.download_button("상관계수 CSV", prices.pct_change().corr().to_csv().encode("utf-8-sig"), "etf_correlation.csv", "text/csv", use_container_width=True)

else:
    with st.sidebar:
        st.header("CSV 정밀분석 설정")
        top_n = st.slider("Top N 구성종목", 5, 30, 10)
        min_weight = st.number_input("표시 최소 비중(%)", min_value=0.0, value=0.0, step=0.1)

    st.subheader("📁 운용사 구성종목 CSV 정밀분석")
    st.caption("여러 ETF 파일을 한 번에 올려 집중도·섹터·국가·중복도를 비교할 수 있습니다.")

    with st.expander("CSV 형식 / 인식 가능한 열 보기"):
        st.markdown("""
**필수**
- `구성종목` / `holding`
- `비중` / `weight`

**선택**
- `ETF` / `ticker` — 없으면 파일명을 ETF명으로 사용
- `sector` / `섹터`
- `country` / `국가`
- `shares` / `수량`
- `market_value` / `평가금액`
        """)

    precision_files = st.file_uploader("ETF 구성종목 CSV를 1개 이상 업로드", type=["csv"], accept_multiple_files=True, key="precision_files")
    if not precision_files:
        sample = pd.DataFrame({"ETF": ["ALPHA"] * 3 + ["BETA"] * 3, "구성종목": ["NVIDIA", "Microsoft", "Apple", "NVIDIA", "Microsoft", "TSMC"], "비중": [20, 15, 12, 18, 11, 10], "섹터": ["반도체", "소프트웨어", "하드웨어", "반도체", "소프트웨어", "반도체"], "국가": ["미국", "미국", "미국", "미국", "미국", "대만"]})
        st.info("CSV 파일을 올리면 분석이 시작됩니다.")
        st.download_button("샘플 CSV 다운로드", sample.to_csv(index=False).encode("utf-8-sig"), "sample_etf_holdings.csv", "text/csv")
        st.stop()

    frames, errors = [], []
    for f in precision_files:
        try:
            try:
                raw = pd.read_csv(f, encoding="utf-8-sig")
            except UnicodeDecodeError:
                f.seek(0)
                raw = pd.read_csv(f, encoding="cp949")
            frames.append(normalize_precision_csv(raw, f.name.rsplit(".", 1)[0]))
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

    p1, p2, p3, p4, p5 = st.tabs(["요약", "구성종목", "섹터·국가", "ETF 중복도", "데이터 내보내기"])
    with p1:
        rows = []
        for etf in selected:
            g = view[view["etf"] == etf].sort_values("weight", ascending=False)
            hv = hhi(g["weight"])
            rows.append({"ETF": etf, "구성종목 수": len(g), "비중 합계(%)": g["weight"].sum(), "Top10 집중도(%)": g.head(10)["weight"].sum(), "최대 종목 비중(%)": g["weight"].max(), "HHI": hv, "집중도": concentration_label(hv)})
        summary_csv = pd.DataFrame(rows)
        st.dataframe(summary_csv.style.format({"비중 합계(%)": "{:.2f}", "Top10 집중도(%)": "{:.2f}", "최대 종목 비중(%)": "{:.2f}", "HHI": "{:.0f}"}), use_container_width=True, hide_index=True)

    with p2:
        for etf in selected:
            g = view[(view["etf"] == etf) & (view["weight"] >= min_weight)].sort_values("weight", ascending=False).head(top_n)
            st.markdown(f"### {etf}")
            st.bar_chart(g.set_index("holding")["weight"], horizontal=True)
            cols = [c for c in ["holding", "weight", "sector", "country", "shares", "market_value"] if c in g.columns]
            st.dataframe(g[cols], use_container_width=True, hide_index=True)

    with p3:
        dimension = st.radio("분류 기준", ["sector", "country"], format_func=lambda x: "섹터" if x == "sector" else "국가", horizontal=True)
        label = "섹터" if dimension == "sector" else "국가"
        if dimension not in view.columns:
            st.info(f"업로드한 CSV에 {label} 열이 없습니다.")
        else:
            grouped = view.assign(**{dimension: view[dimension].replace("", "미분류").fillna("미분류")}).groupby(["etf", dimension], as_index=False)["weight"].sum()
            for etf in selected:
                g = grouped[grouped["etf"] == etf].sort_values("weight", ascending=False)
                st.markdown(f"### {etf}")
                st.bar_chart(g.set_index(dimension)["weight"], horizontal=True)
                st.dataframe(g[[dimension, "weight"]].rename(columns={dimension: label, "weight": "비중(%)"}), use_container_width=True, hide_index=True)

    with p4:
        if len(selected) < 2:
            st.info("ETF를 2개 이상 선택해야 중복도를 계산할 수 있습니다.")
        else:
            ov = precision_overlap_matrix(view, selected)
            st.dataframe(ov.style.format("{:.1f}%").background_gradient(axis=None, vmin=0, vmax=100), use_container_width=True)
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
                st.dataframe(common, use_container_width=True, hide_index=True)

    with p5:
        st.download_button("정규화된 구성종목 CSV", view.to_csv(index=False).encode("utf-8-sig"), "etf_holdings_normalized.csv", "text/csv")
        if len(selected) >= 2:
            ov = precision_overlap_matrix(view, selected)
            st.download_button("ETF 중복도 매트릭스 CSV", ov.to_csv().encode("utf-8-sig"), "etf_overlap_matrix.csv", "text/csv")

    st.divider()
    st.caption("CSV 정밀분석은 업로드한 구성종목 데이터만 사용합니다.")
