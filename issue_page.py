"""월가이슈 › 📝 영상 요약 검산 탭 (Streamlit)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import data_sources
from events import extract_events
from issue_parser import (
    best_verification,
    entity_info,
    exposure,
    extract_claims,
    internal_checks,
    mention_table,
    parse_ref_date,
    price_window,
    ticker_label_issues,
)

SAMPLE = """# 월가 마감 시황 · 2026.11.20
1. 다우지수는 1.93% 내렸고, S&P 500은 3.7% 하락했다. 나스닥은 22,617로 5.28% 하락했다.
2. 나스닥의 연초 대비 수익률은 전날까지 약 2% 상승이었지만, 이날 급락으로 -2.69%가 됐다.
3. 엔비디아는 13.8% 하락했다. 마이크론은 13.86%, AMD는 13.26% 내렸다.
4. 앤트로픽 주가는 9.13% 하락해 88.3달러로 마감했다. 공모가는 83달러, 시초가는 111.5달러였다.
   전날 종가 97.17달러는 공모가보다 약 17% 높은 수준이었다.
   앤트로픽은 이날 88.91달러로 마감했다. 공모가 83달러보다는 약 7% 높지만, 시초가 111.5달러보다 약 20% 낮다.
5. SOXL은 10월 6일 300.77달러까지 올랐지만, 방송 당일 30.88달러까지 떨어졌다. 고점 대비 약 90% 하락했다.
6. 앤트로픽은 12월 21일 나스닥 100에 조기 편입될 예정이다. 내년 2월까지 16억 주가 나올 수 있다.
"""


@st.cache_data(ttl="15m", show_spinner=False)
def _closes(tickers: tuple[str, ...], start_iso: str, end_iso: str) -> pd.DataFrame:
    _, closes = data_sources.download_prices(list(tickers), start_iso, end_iso)
    return closes


@st.cache_data(ttl="6h", show_spinner=False)
def _holdings(etf: str) -> tuple[pd.DataFrame, str, str | None]:
    snap = data_sources.fetch_fund_snapshot(etf)
    h = snap.get("holdings")
    if not isinstance(h, pd.DataFrame):
        h = pd.DataFrame(columns=["etf", "holding", "weight"])
    return h, snap.get("holdings_scope") or "없음", snap.get("error")


def _verdict_color(v: str) -> str:
    if str(v).startswith("⚠️"):
        return "background-color: rgba(255, 75, 75, 0.15)"
    if str(v).startswith("✅"):
        return "background-color: rgba(33, 195, 84, 0.12)"
    if str(v).startswith("🟡"):
        return "background-color: rgba(255, 200, 0, 0.18)"
    return ""


def _show_checks(df: pd.DataFrame) -> None:
    st.dataframe(df.style.map(_verdict_color, subset=["판정"]), width="stretch", hide_index=True)


def render_issue_tab() -> None:
    st.markdown("#### 📝 영상 요약·대본 붙여넣기")
    st.caption(
        "유튜브 시황 요약이나 대본을 붙여넣으면 ① 언급된 종목·지수를 뽑고 ② 영상 속 숫자끼리 산수가 맞는지 "
        "③ 실제 시세와 맞는지 ④ 내 ETF가 그 종목들에 얼마나 노출돼 있는지 보여줍니다."
    )
    if st.button("예시 불러오기", key="ii_sample"):
        st.session_state["ii_text"] = SAMPLE
    text = st.text_area(
        "요약 / 대본",
        key="ii_text",
        height=260,
        placeholder="여기에 영상 요약을 붙여넣으세요. 예) 엔비디아는 13.8% 하락했다. 앤트로픽 주가는 9.13% 하락해 88.3달러로 마감했다...",
    )
    if not text.strip():
        st.session_state["ws_video_events"] = None
        st.info("요약문을 붙여넣거나 '예시 불러오기'를 눌러 보세요.")
        return

    guessed = parse_ref_date(text, date.today())
    d = st.date_input(
        "기준일 (미국 장 날짜)",
        value=guessed,
        key=f"ii_date_{guessed.isoformat()}",
        help="본문에서 날짜를 찾아 자동으로 채웁니다. 한국 아침 방송이면 전날 미국 장을 다루므로, 실제 시세 대조 때 직전 거래일도 함께 시도합니다.",
    )
    mentions, claims = extract_claims(text, d)
    if not mentions:
        st.warning("인식한 종목·지수가 없습니다. 종목명 뒤에 (NVDA)처럼 티커를 괄호로 적으면 새 종목도 인식합니다.")
        return

    # ① 언급된 종목
    st.markdown("##### 🔎 ① 언급된 종목·지수")
    mt = mention_table(mentions, claims)
    st.dataframe(mt, width="stretch", hide_index=True)
    st.caption("사전에 없는 종목은 '회사명(TICKER)'처럼 괄호로 티커를 적으면 인식합니다. 주어가 생략된 문장은 앞 문장·소제목의 종목으로 추정합니다.")
    labels = ticker_label_issues(text)
    if not labels.empty:
        st.warning("요약문에 적힌 티커가 실제와 다릅니다. 이 티커로 매매·검색하면 다른 종목이 나올 수 있습니다.")
        st.dataframe(labels, width="stretch", hide_index=True)

    # ② 내부 검산
    st.markdown("##### 🧮 ② 영상 속 숫자끼리 검산")
    ic = internal_checks(claims)
    if ic.empty:
        st.info("서로 대조할 수 있는 숫자 묶음(전날 종가+등락률+종가, 기준가 대비, 고점 대비 등)이 없습니다.")
    else:
        bad = int(ic["판정"].str.startswith("⚠️").sum())
        approx = int(ic["판정"].str.startswith("🟡").sum())
        good = int(ic["판정"].str.startswith("✅").sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("✅ 일치", good)
        c2.metric("🟡 근사", approx)
        c3.metric("⚠️ 불일치", bad)
        _show_checks(ic)

    # ③ 실제 시세 대조
    st.markdown("##### 📡 ③ 실제 시세와 대조")
    targets = sorted({c.ticker for c in claims if (c.kind == "pct" and c.period in ("daily", "week", "ytd", "ytd_prev", "month", "high"))
                      or (c.kind == "price" and c.period == "close") or c.kind == "level"})
    if not targets:
        st.info("실제 시세와 대조할 숫자(등락률·종가 등)가 없습니다.")
    else:
        start, end = price_window(claims, d)
        with st.spinner("시세를 불러와 대조하는 중..."):
            try:
                closes = _closes(tuple(targets), start.isoformat(), end.isoformat())
            except Exception as e:
                closes = pd.DataFrame()
                st.warning(f"시세를 불러오지 못했습니다: {e}")
        if closes is None or closes.empty:
            st.warning("시세 데이터를 받지 못해 대조할 수 없습니다. 잠시 후 다시 시도하세요.")
        else:
            vt, used, note = best_verification(claims, closes, d)
            if note:
                st.info(note)
            missing = [t for t in targets if t not in closes.columns or closes[t].dropna().empty]
            if not vt.empty:
                _show_checks(vt)
            if missing:
                st.caption("시세를 찾지 못한 티커: " + ", ".join(f"{entity_info(t).name}({t})" for t in missing))
            st.caption(
                "종가 기준으로 대조합니다. '고점 대비'는 장중 고가 기준일 수 있어 오차를 넉넉히 봅니다. "
                "'약', '넘게', '10~20%' 같은 표현은 범위가 넓거나 대조에서 제외됩니다."
            )

    # ⑤ 영상 속 일정: ④가 중간에 끝날 수 있어 자리를 먼저 잡고 아래에 그린다
    events = extract_events(text, d)
    st.session_state["ws_video_events"] = events
    exposure_box = st.container()
    st.markdown("##### 📅 ⑤ 영상 속 일정")
    if events.empty:
        st.info("영상 속에서 앞으로의 날짜가 붙은 일정(편입, 발표, 보호예수 해제 등)을 찾지 못했습니다.")
    else:
        st.dataframe(events[["표기", "이벤트", "관련", "문장"]].rename(columns={"표기": "날짜", "문장": "근거 문장"}),
                     width="stretch", hide_index=True)
        st.caption("이 일정은 '📅 일정' 탭에 시장 일정과 함께 D-day로 표시됩니다.")
    with exposure_box:
        _render_exposure(mentions, d)


def _render_exposure(mentions, d) -> None:

    # ④ 내 ETF 노출도
    st.markdown("##### 💼 ④ 내 ETF 노출도")
    stock_tickers = list(dict.fromkeys(m.ticker for m in mentions if entity_info(m.ticker).kind in ("stock", "unknown")))
    if not stock_tickers:
        st.info("개별 종목 언급이 없어 노출도를 계산하지 않습니다.")
        return
    st.caption("보유 ETF와 금액(선택)을 적으면, 영상에 나온 종목이 내 ETF에 얼마나 들어 있는지 계산합니다.")
    default = pd.DataFrame({"ETF": ["QQQ", "SPY", "SOXX"], "보유금액(만원)": [None, None, None]})
    port = st.data_editor(
        default,
        num_rows="dynamic",
        key="ii_port",
        width="stretch",
        column_config={
            "ETF": st.column_config.TextColumn("ETF", help="미국 티커, 국내 6자리 코드 또는 한글 ETF명"),
            "보유금액(만원)": st.column_config.NumberColumn("보유금액(만원)", min_value=0, step=10),
        },
    )
    files = st.file_uploader("운용사 구성종목 CSV (선택, 전체 구성종목으로 정확히 계산)", type=["csv"],
                             accept_multiple_files=True, key="ii_holdings_csv")

    etfs = [str(x).strip() for x in port["ETF"].dropna().tolist() if str(x).strip()]
    amounts = {}
    for _, r in port.iterrows():
        if pd.notna(r.get("ETF")) and str(r["ETF"]).strip() and pd.notna(r.get("보유금액(만원)")):
            amounts[str(r["ETF"]).strip().upper()] = float(r["보유금액(만원)"])
    if not etfs:
        st.info("ETF를 1개 이상 입력하세요.")
        return

    parts, scopes, csv_etfs = [], {}, set()
    for f in files or []:
        try:
            try:
                raw = pd.read_csv(f, encoding="utf-8-sig")
            except UnicodeDecodeError:
                f.seek(0)
                raw = pd.read_csv(f, encoding="cp949")
            part = data_sources.normalize_holdings_csv(raw, f.name.rsplit(".", 1)[0])
            parts.append(part)
            for e in part["etf"].unique():
                csv_etfs.add(str(e).upper())
                scopes[str(e).upper()] = "업로드 CSV(전체)"
        except Exception as e:
            st.error(f"{f.name}: {e}")
    with st.spinner("ETF 구성종목을 불러오는 중..."):
        for etf in etfs:
            if etf.upper() in csv_etfs:
                continue
            try:
                h, scope, err = _holdings(etf)
            except Exception as e:
                h, scope, err = pd.DataFrame(), "없음", str(e)
            if h is not None and not h.empty:
                parts.append(h)
                scopes[etf.upper()] = scope
            else:
                scopes[etf.upper()] = "없음" + (f" ({err})" if err else "")
    holdings = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["etf", "holding", "weight"])
    if not holdings.empty:
        holdings["etf"] = holdings["etf"].astype(str).str.strip().str.upper()

    st.caption("구성종목 출처: " + " · ".join(f"{k}: {v}" for k, v in scopes.items()))
    if holdings.empty:
        st.warning("구성종목을 불러오지 못했습니다. 국내 ETF는 운용사 CSV를 올려 주세요.")
        return

    mat, money = exposure(holdings, stock_tickers, amounts)
    if mat.empty or mat.shape[1] <= 1:
        st.info("입력한 ETF의 (확인 가능한) 구성종목에 영상 속 종목이 없습니다.")
    else:
        st.markdown("**ETF별 비중(%)**")
        st.dataframe(mat.style.format("{:.2f}").background_gradient(cmap="Reds", axis=None),
                     width="stretch")
        if not money.empty:
            st.markdown("**종목별 내 노출 금액(만원)**")
            st.dataframe(money.style.format({"노출 금액": "{:,.0f}"}), width="stretch", hide_index=True)
            total = sum(amounts.get(e, 0) for e in mat.index)
            if total:
                exp_total = float(money["노출 금액"].sum())
                st.markdown(f"보유 ETF {total:,.0f}만원 중 영상 속 종목에 **{exp_total:,.0f}만원**({exp_total / total * 100:.1f}%)이 노출돼 있습니다.")
    absent = [entity_info(t).name for t in stock_tickers if entity_info(t).name not in mat.columns]
    if absent:
        st.caption("구성종목에서 찾지 못한 종목: " + ", ".join(absent)
                   + " — Yahoo는 상위 10개 종목만 주므로, 정확히 보려면 운용사 전체 구성종목 CSV를 올리세요. "
                   "갓 상장했거나 지수 편입 전인 종목은 아직 ETF에 없을 수 있습니다.")
