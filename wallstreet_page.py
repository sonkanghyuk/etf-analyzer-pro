"""③ 월가이슈 화면 (Streamlit)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

import data_sources
from issue_page import render_issue_tab
from wallstreet import (
    HISTORY_INDEXES,
    MARKET_DASHBOARD,
    SECTOR_ETFS,
    dashboard_start,
    headline_lines,
    market_snapshot,
    month_rank,
    required_recovery,
    streak_record,
    ytd_same_day,
)

KIND_LABEL = {"index": "지수", "rate": "금리", "fx": "환율·달러", "commodity": "원자재", "crypto": "코인", "vol": "변동성"}


@st.cache_data(ttl="15m", show_spinner=False)
def _closes(tickers: tuple[str, ...], start_iso: str, end_iso: str) -> pd.DataFrame:
    _, closes = data_sources.download_prices(list(tickers), start_iso, end_iso)
    return closes


def _color(v):
    if v is None or pd.isna(v):
        return ""
    if v > 0:
        return "color: #d62728"  # 한국식: 상승 빨강
    if v < 0:
        return "color: #1f62c9"  # 하락 파랑
    return ""


def _style_snapshot(df: pd.DataFrame):
    chg = ["1일", "1주", "월초대비", "연초대비"]
    fmt = {
        "현재값": "{:,.2f}",
        "52주고점대비(%)": "{:+.2f}",
        "회복필요상승률(%)": "{:+.1f}",
        "연속(일)": "{:+d}",
    }
    for c in chg:
        fmt[c] = "{:+.2f}"
    return df.style.format(fmt, na_rep="-").map(_color, subset=chg + ["52주고점대비(%)", "연속(일)"])


def _fetch_dashboard(today: date) -> pd.DataFrame:
    start = dashboard_start(today).isoformat()
    end = (today + timedelta(days=1)).isoformat()
    tickers = tuple(t for _, t, _ in MARKET_DASHBOARD) + tuple(t for _, t in SECTOR_ETFS)
    return _closes(tickers, start, end)


def render() -> None:
    st.subheader("🗽 월가이슈")
    st.caption("시황 방송에서 다루는 숫자(지수·금리·달러·유가·금·코인·VIX, 섹터 등락, 역사적 비교)를 자동으로 모으고, 영상 요약의 숫자를 검산합니다.")

    with st.sidebar:
        st.header("월가이슈 설정")
        hist_label = st.selectbox("과거 비교 지수", [l for l, _ in HISTORY_INDEXES], index=0)
        custom = st.text_input("또는 직접 입력한 티커로 과거 비교", placeholder="예: NVDA, SOXL, QQQ")
        if st.button("🔄 시세 새로고침", width="stretch", key="ws_refresh"):
            _closes.clear()

    t1, t4, t2, t3 = st.tabs(["📋 시장 대시보드", "📝 영상 요약 검산", "🌡️ 섹터 히트맵", "📜 과거 비교"])
    with t4:
        render_issue_tab()

    today = date.today()
    load_error = None
    with st.spinner("시세를 불러오는 중..."):
        try:
            closes = _fetch_dashboard(today)
        except Exception as e:  # 네트워크/야후 장애
            closes, load_error = pd.DataFrame(), f"시세를 불러오지 못했습니다: {e}"
    if load_error is None and (closes is None or closes.empty):
        load_error = "시세 데이터가 비어 있습니다. 잠시 후 새로고침해 주세요."
    if load_error:
        for tab in (t1, t2, t3):
            with tab:
                st.error(load_error)
        return

    snap = market_snapshot(closes, MARKET_DASHBOARD)
    sectors = market_snapshot(closes, [(l, t, "index") for l, t in SECTOR_ETFS])

    hist_ticker = custom.strip().upper() if custom.strip() else dict(HISTORY_INDEXES)[hist_label]
    hist_name = custom.strip().upper() if custom.strip() else hist_label
    with st.spinner(f"{hist_name} 장기 데이터를 불러오는 중..."):
        try:
            long = _closes((hist_ticker,), "1970-01-01", (today + timedelta(days=1)).isoformat())
            long_s = long[hist_ticker].dropna() if hist_ticker in long.columns else pd.Series(dtype=float)
        except Exception as e:
            st.warning(f"{hist_name} 장기 데이터를 불러오지 못했습니다: {e}")
            long_s = pd.Series(dtype=float)
    rank = month_rank(long_s) if len(long_s) > 40 else {}

    with t1:
        lines = headline_lines(snap, rank, hist_name)
        if lines:
            st.markdown("#### 오늘의 월가 3줄")
            st.code("\n".join(lines), language=None, wrap_lines=True)
        key = snap.set_index("티커")
        cols = st.columns(4)
        for i, t in enumerate(["^GSPC", "^IXIC", "^VIX", "^TNX"]):
            if t in key.index:
                r = key.loc[t]
                unit = "bp" if r["종류"] == "rate" else "%"
                delta = r["1일"]
                cols[i].metric(
                    r["구분"],
                    f"{r['현재값']:,.2f}",
                    None if pd.isna(delta) else (f"{delta:+.1f}bp" if unit == "bp" else f"{delta:+.2f}%"),
                    delta_color="off",  # 미국식 초록/빨강 대신 화살표로만 표시
                )
        st.markdown("#### 전체 지표")
        st.caption("금리(3개월·5년·10년)의 변화는 bp(0.01%p) 단위입니다. 연속(일): +는 연속 상승, -는 연속 하락 거래일 수.")
        view = snap.assign(종류=snap["종류"].map(KIND_LABEL)).drop(columns=["52주고점일"])
        st.dataframe(_style_snapshot(view), width="stretch", hide_index=True)

        deep = snap.dropna(subset=["52주고점대비(%)"])
        deep = deep[deep["52주고점대비(%)"] <= -10]
        if not deep.empty:
            st.markdown("#### ⚠️ 고점 대비 10% 이상 하락한 자산")
            for _, r in deep.iterrows():
                st.markdown(
                    f"- **{r['구분']}**: {r['52주고점대비(%)']:+.1f}% (고점 {r['52주고점일']}) "
                    f"→ 원금 회복에 **{r['회복필요상승률(%)']:+.1f}%** 상승 필요"
                )

        rec = []
        for label, ticker, kind in MARKET_DASHBOARD:
            if kind == "index" and ticker in closes.columns:
                sr = streak_record(closes[ticker])
                if abs(sr["streak"]) >= 3:
                    word = "연속 상승" if sr["streak"] > 0 else "연속 하락"
                    if sr["longest_in_data"]:
                        tail = "최근 1년여 데이터 중 최장"
                    else:
                        tail = f"{sr['since'].date()}({sr['since_len']}일) 이후 최장"
                    rec.append(f"- **{label}** {abs(sr['streak'])}거래일 {word} — {tail}")
        if rec:
            st.markdown("#### 연속 상승·하락 기록")
            st.markdown("\n".join(rec))

    with t2:
        if sectors.empty:
            st.info("섹터 ETF 데이터를 불러오지 못했습니다.")
        else:
            basis = st.radio("기준", ["1일", "1주", "월초대비", "연초대비"], horizontal=True, key="ws_basis")
            s = sectors.set_index("구분")[basis].dropna().sort_values()
            st.bar_chart(s, horizontal=True)
            heat = sectors[["구분", "티커", "현재값", "1일", "1주", "월초대비", "연초대비", "52주고점대비(%)"]]
            st.dataframe(
                heat.style.format(
                    {"현재값": "{:,.2f}", **{c: "{:+.2f}" for c in ["1일", "1주", "월초대비", "연초대비", "52주고점대비(%)"]}},
                    na_rep="-",
                ).background_gradient(cmap="RdBu_r", subset=["1일", "1주", "월초대비", "연초대비"], vmin=-10, vmax=10),
                width="stretch",
                hide_index=True,
            )
            st.caption("빨강=상승, 파랑=하락(±10% 기준 색상). 방어 섹터(헬스케어·필수소비재·유틸리티)와 기술·반도체를 비교해 보세요.")

    with t3:
        if not rank:
            st.info(f"{hist_name}의 장기 데이터가 부족해 과거 비교를 할 수 없습니다.")
        else:
            tag = " (진행 중)" if rank["partial"] else ""
            c1, c2, c3 = st.columns(3)
            c1.metric(f"{rank['month']}{tag} 수익률", f"{rank['return']:+.2f}%")
            c2.metric("나쁜 순위", f"{rank['worse_rank']} / {rank['total']}")
            if rank["since_month"]:
                word = "이후 최악" if rank["return"] < 0 else "이후 최고"
                c3.metric("마지막으로 이 정도였던 달", rank["since_month"], f"{rank['since_return']:+.2f}% {word}", delta_color="off")
            else:
                c3.metric("비교", f"{rank['first_month']} 이후", "데이터 시작 이후 기록", delta_color="off")
            st.caption(f"{rank['first_month']}부터 월말 종가 기준. 진행 중인 달은 월말에 바뀔 수 있습니다.")

            a, b = st.columns(2)
            with a:
                st.markdown("#### 역대 최악의 달 Top 10")
                st.dataframe(rank["worst"].style.format({"수익률(%)": "{:+.2f}"}), width="stretch", hide_index=True)
            with b:
                st.markdown("#### 역대 최고의 달 Top 10")
                st.dataframe(rank["best"].style.format({"수익률(%)": "{:+.2f}"}), width="stretch", hide_index=True)

            ytd = ytd_same_day(long_s)
            if not ytd.empty:
                st.markdown(f"#### 해마다 같은 날짜까지의 연초 대비 수익률 ({long_s.index[-1]:%m-%d} 기준)")
                cur = ytd[ytd["올해"]]
                if not cur.empty:
                    v = float(cur["연초대비(%)"].iloc[0])
                    n = int((ytd["연초대비(%)"] < v).sum()) + 1
                    st.markdown(f"올해 **{v:+.2f}%** → {len(ytd)}개 연도 중 낮은 순으로 **{n}위**")
                st.bar_chart(ytd.set_index("연도")["연초대비(%)"])

            sr = streak_record(long_s)
            if sr["streak"]:
                word = "연속 상승" if sr["streak"] > 0 else "연속 하락"
                tail = "데이터 시작 이후 최장" if sr["longest_in_data"] else f"{sr['since'].date()}({sr['since_len']}일) 이후 최장"
                st.markdown(f"#### 연속 기록\n**{abs(sr['streak'])}거래일 {word}** — {tail}")

        st.divider()
        st.markdown("#### 🧮 하락률 → 원금 회복 필요 상승률")
        dd = st.slider("하락률(%)", -95, -5, -50, 5)
        st.markdown(f"**{dd}%** 하락하면 원금 회복에 **{required_recovery(dd):+.1f}%** 상승이 필요합니다.")
        st.caption("예: SOXL 300.77→30.88달러(약 -90%)는 원금 회복에 약 +870%가 필요합니다. 레버리지 ETF는 하락장에서 이 비대칭이 커집니다.")
