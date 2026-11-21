"""월가이슈 › 📅 일정 탭 (Streamlit)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from events import combine, market_calendar

SOURCES = ["영상 요약", "시장 규칙", "직접 입력"]


def _user_events(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.dropna(subset=["날짜", "이벤트"]).copy()
    df = df[df["이벤트"].astype(str).str.strip() != ""]
    if df.empty:
        return pd.DataFrame()
    df["날짜"] = pd.to_datetime(df["날짜"]).dt.date
    df["표기"] = [d.isoformat() for d in df["날짜"]]
    df["관련"] = df.get("관련", "").fillna("") if "관련" in df else ""
    df["출처"], df["근사"], df["문장"] = "직접 입력", False, ""
    return df[["날짜", "표기", "이벤트", "관련", "출처", "근사", "문장"]]


def _highlight(row):
    n = row["_days"]
    if 0 <= n <= 7:
        return ["background-color: rgba(255, 75, 75, 0.12)"] * len(row)
    return [""] * len(row)


def render_calendar_tab() -> None:
    st.markdown("#### 📅 다가오는 일정")
    st.caption("영상 요약에서 뽑은 일정, 날짜 규칙으로 계산한 미국 시장 일정, 직접 추가한 일정을 한 표로 봅니다.")
    today = date.today()
    c1, c2 = st.columns(2)
    horizon = c1.select_slider("기간", options=[30, 60, 90, 180, 365, 730], value=90, format_func=lambda x: f"{x}일", key="cal_h")
    shown = c2.multiselect("출처", SOURCES, default=SOURCES, key="cal_src")

    with st.expander("✏️ 직접 일정 추가 · CSV 저장/불러오기"):
        up = st.file_uploader("일정 CSV 불러오기 (날짜, 이벤트, 관련)", type=["csv"], key="cal_csv")
        base = pd.DataFrame({"날짜": pd.Series(dtype="object"), "이벤트": pd.Series(dtype="str"), "관련": pd.Series(dtype="str")})
        if up is not None:
            try:
                raw = pd.read_csv(up, encoding="utf-8-sig")
                raw = raw[[c for c in ["날짜", "이벤트", "관련"] if c in raw.columns]]
                raw["날짜"] = pd.to_datetime(raw["날짜"], errors="coerce").dt.date
                base = raw.dropna(subset=["날짜"])
            except Exception as e:
                st.error(f"CSV를 읽지 못했습니다: {e}")
        edited = st.data_editor(
            base,
            num_rows="dynamic",
            width="stretch",
            key=f"cal_editor_{getattr(up, 'file_id', 'none')}",
            column_config={
                "날짜": st.column_config.DateColumn("날짜", format="YYYY-MM-DD"),
                "이벤트": st.column_config.TextColumn("이벤트"),
                "관련": st.column_config.TextColumn("관련 종목/ETF"),
            },
        )
        st.caption("Streamlit Cloud는 입력을 저장하지 않으니, 아래 'CSV로 저장'으로 내려받아 두었다가 다음에 불러오세요.")

    frames = []
    video = st.session_state.get("ws_video_events")
    if "영상 요약" in shown and isinstance(video, pd.DataFrame) and not video.empty:
        frames.append(video)
    if "시장 규칙" in shown:
        frames.append(market_calendar(today, today + timedelta(days=horizon)))
    user = _user_events(edited)
    if "직접 입력" in shown and not user.empty:
        frames.append(user)

    df = combine(frames, today)
    if not df.empty:
        df = df[(df["날짜"] >= today) & (df["날짜"] <= today + timedelta(days=horizon))].reset_index(drop=True)
    if df.empty:
        st.info("표시할 일정이 없습니다. '📝 영상 요약 검산' 탭에 요약을 붙여넣으면 영상 속 일정이 여기에 함께 나옵니다.")
        return

    week = df[[0 <= (d - today).days <= 7 for d in df["날짜"]]]
    m1, m2, m3 = st.columns(3)
    m1.metric("이번 주(7일) 일정", len(week))
    m2.metric("영상에서 뽑은 일정", int((df["출처"] == "영상 요약").sum()))
    nxt = df.iloc[0]
    m3.metric("가장 가까운 일정", nxt["D-day"], nxt["이벤트"][:18], delta_color="off")

    view = df.copy()
    view["_days"] = [(d - today).days for d in view["날짜"]]
    cols = ["날짜", "요일", "D-day", "이벤트", "관련", "출처", "문장"]
    st.dataframe(
        view[cols + ["_days"]].style.apply(_highlight, axis=1).hide(axis="columns", subset=["_days"]),
        width="stretch",
        hide_index=True,
        column_config={"문장": st.column_config.TextColumn("근거 문장", width="large")},
    )
    if video is None or (isinstance(video, pd.DataFrame) and video.empty):
        st.caption("영상 요약을 붙여넣으면 영상 속 일정(지수 편입, 보호예수 해제 등)이 함께 표시됩니다.")
    st.caption(
        "빨간 줄은 7일 이내 일정입니다. '~D-n'은 '11월 말', '내년 2월' 같은 월 단위 표현이라 날짜가 근사치입니다. "
        "FOMC는 연준이 공개한 2026년 일정만 넣었고, 고용보고서는 통상 첫째 금요일 기준이라 실제 발표일을 확인하세요."
    )
    out = df.drop(columns=["요일"]).copy()
    st.download_button("📥 CSV로 저장", out.to_csv(index=False).encode("utf-8-sig"), "wallstreet_calendar.csv", "text/csv")
