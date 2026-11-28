# 존버나드TV 롱폼 자동 제작 파이프라인 — 설계 초안

> 목표: **대본과 데이터만 넣으면** [`supetv_editing_bible.md`](supetv_editing_bible.md) 규격의 슬라이드 이미지, 자막, 최종 영상이 나오게 한다.
> 이 문서는 설계 초안이다. 코드는 아직 없고, 설계의 핵심 가정 두 가지(규격 레이아웃 재현, 고정 폭 자막 바)는 프로토타입으로 검증했다(§7-3).

---

## 0. 범위

| 구분 | 내용 |
|---|---|
| **입력** | ① 대본 `episode.md`(장면 표시 포함) ② 데이터(자동 수집 또는 CSV) ③ 내레이션 음성 `voice.wav`(직접 녹음 권장, TTS 선택) ④ 에셋(채널 로고, 진행자 컷아웃, B-roll 클립, BGM) |
| **출력** | `final.mp4`(1920×1080, 30fps, H.264/AAC), `subtitles.srt`(업로드용, 번인 자막과 같은 청크), `chapters.txt`(설명란 타임스탬프), `slides/*.png`(장면 상태별 정지 이미지), `qa_report.json` + 컨택트시트, (선택) `thumbnail.png` |
| **v1에서 하지 않는 것** | B-roll 자동 검색·생성, 대본 자동 작성, TradingView·finviz 화면 자동 캡처(라이선스 문제로 직접 그린 차트로 대체) |

---

## 1. 기술 선택: Python + FFmpeg (v1) / Remotion (v2 선택)

| 기준 | **Python(Pillow·Matplotlib) + FFmpeg** | Remotion(React) |
|---|---|---|
| 이 저장소와의 연결 | ✅ 그대로 재사용: 나눔 폰트(`johnber_shorts_studio/fonts`), SRT 파서(`app/subtitles.py`), 로컬 음성 인식 faster-whisper(`app/transcribe.py`), 시황 데이터(`wallstreet.py`, `events.py`) | 데이터 수집은 Python, 렌더는 Node로 이원화 |
| 설치(Windows PC) | Python + ffmpeg만 | Node + Chromium + npm 패키지 |
| 레이아웃 정밀도 | ✅ 픽셀 좌표로 그림. 바이블 수치와 겹침 검증 완료(§7-3) | CSS 레이아웃이라 픽셀 맞춤에 손이 더 감 |
| 빌드 애니메이션(막대 성장, 선 그리기) | 짧은 PNG 시퀀스(0.5초 = 15프레임)로 충분 | ✅ 가장 강함(스프링·보간) |
| 렌더 속도·재렌더 | 장면별 mp4 캐시 → 바뀐 장면만 다시 렌더 | 전체 재렌더가 기본 |
| 라이선스 | 무료(OFL 폰트, LGPL/GPL ffmpeg) | 개인·소규모 팀 무료, 그 이상 회사 라이선스 필요(도입 전 확인) |

**결정: v1은 Python + FFmpeg.** 레퍼런스 모션은 "하드컷 + 단순 빌드"(바이블 §8-2)라 Remotion의 장점이 크지 않다. 장면 명세(JSON)를 렌더러와 분리해 두므로, 나중에 템플릿 일부만 Remotion 컴포넌트로 바꿀 수 있다.

---

## 2. 전체 흐름

```
episode.md ─┐
data/*.csv ─┤  ①parse      ②data        ③align           ④cues              ⑤render          ⑥timeline     ⑦compose        ⑧QA
voice.wav ──┤ ─────────▶ scenes.json ─▶ (자동 채움) ─▶ 단어 타임스탬프 ─▶ 자막 청크·빌드 시점 ─▶ 상태별 PNG ─▶ edl.json ─▶ final.mp4 ─▶ qa_report
assets/ ────┘                                (faster-whisper)    (≤24자 규칙)        (+애니 PNG 시퀀스)            (FFmpeg+libass)   + 컨택트시트
                                                                                                                       ⑨package: srt · chapters · thumbnail
```

| 단계 | 모듈 | 하는 일 | 재사용 |
|---|---|---|---|
| ① parse | `pipeline/parse.py` | `episode.md` → 장면 목록(템플릿 ID, 파라미터, 내레이션 문장, `@cue` 위치) | — |
| ② data | `pipeline/data.py` | `source=auto` 장면에 시세·등락률·낙폭·일정 채움, CSV 읽기, 숫자 포맷 통일 | `wallstreet.py`, `events.py`, yfinance, FinanceDataReader |
| ③ align | `pipeline/align.py` | 음성 → 단어 타임스탬프 → 대본 단어와 정렬(음절 단위 difflib). TTS면 TTS가 준 타이밍 사용 | `johnber_shorts_studio/app/transcribe.py` |
| ④ cues | `pipeline/cues.py` | 자막 청크(바이블 §6-2), 장면 시작·끝, 빌드 전환 시각 | — |
| ⑤ render | `templates/*.py` | 장면 상태마다 1920×1080 PNG. 막대 성장 등은 15프레임 시퀀스 | `tools/reference_analysis/spec_preview.py`의 종이 질감·좌표 |
| ⑥ timeline | `pipeline/timeline.py` | 장면·상태·B-roll·로고 스팅 배치, 20초 이상 정지 구간 경고 | `johnber_shorts_studio/app/edl.py` 개념 |
| ⑦ compose | `pipeline/compose.py` | 장면별 mp4 → concat → 로고·자막(ASS)·오디오(덕킹·라우드니스) | `johnber_shorts_studio/app/render.py`의 ffmpeg 실행·검증 |
| ⑧ QA | `pipeline/qa.py` | 규격 자동 검사(§8), 컨택트시트 | `tools/reference_analysis/contact_sheet.py`, `script_stats.py` |

---

## 3. 디렉터리 구조

```
longform_studio/                 # 새 패키지 (johnber_shorts_studio와 나란히)
  brand.yaml                     # 바이블 수치를 옮긴 디자인 토큰 (§5)
  cli.py                         # python -m longform_studio build episodes/2026-11-28_weekly
  pipeline/  parse.py data.py align.py cues.py render.py timeline.py compose.py qa.py
  templates/                     # 템플릿 1개 = 모듈 1개
    base.py                      # 공통: 종이 배경, 제목, 출처, 안전 영역, 색 규칙
    t01_index_rings.py  t02_area_delta.py  t04_theme_barometer.py  t05_drawdown_table.py
    t06_price_chart.py  t07_equation_rings.py  t08_flow_top10.py  t09_etf_top_worst.py
    t10_issue_hub.py  t11_news_capture.py  t12_hbar_compare.py  t13_vbar_compare.py
    t14_icon_checklist.py  t15_snake_timeline.py  t16_week_calendar.py  t17_dividend_calendar.py
    t18_quote_card.py  t19_dark_bullets.py  t20_split_up_down.py  t21_big_number.py
    t22_pie_split.py  t23_buy_sell_buttons.py  t24_portfolio_summary.py  t25_speech_bubbles.py
    t26_waffle_100.py  t27_rank_slider.py  t28_outro_host.py  broll.py  logo_sting.py
  assets/
    logo.png                     # 존버나드TV 로고(투명 PNG, 252×120 안에 맞춤)
    paper_bg.png                 # 구겨진 종이 1920×1080 (생성 스크립트 또는 직접 촬영 스캔)
    newspaper_bg.jpg             # 이슈 허브 배경
    sting.mp4                    # 로고 스팅 약 2초(효과음 포함)
    host_cutout.png  icons/  bgm/
  tests/                         # 청크 규칙, 템플릿 좌표 스냅샷, 타이밍 테스트
episodes/
  2026-11-28_weekly/
    episode.md  voice.wav  data/*.csv  broll/*.mp4
    out/  final.mp4  subtitles.srt  chapters.txt  slides/  qa_report.json  contact_*.jpg
```

---

## 4. 입력 형식 — `episode.md`

마크다운 한 파일에 메타 정보, 장면, 내레이션을 함께 쓴다. 규칙은 세 가지다.
- `## 블록명` — 챕터(설명란 타임스탬프로 나간다)
- `::: 템플릿ID key=value ...` — 새 장면. 다음 `:::`까지의 문장이 이 장면의 내레이션
- `@이름` — 문장 안에 넣으면 **그 단어를 말하는 순간** 다음 빌드 상태로 넘어간다(바이블 §8-3)

````markdown
---
format: weekly            # weekly | strategy | portfolio  (바이블 §9 포맷 A/B-1/B-2)
date: 2026-11-28
week: 48W
title: 나스닥 -4% 급락, 다음 주 PCE가 분수령
voice: voice.wav          # 없으면 tts: clova:nara 같은 식으로 지정
color_convention: us      # us(상승 초록) | kr(상승 빨강)
---

## 인트로
::: broll clip=broll/earth.mp4
이번 주는 계좌를 열어보기가 무서운 한 주였죠.
오르면 놓칠까 조급하고 떨어지면 팔아야 하나 고민됩니다.
::: broll clip=broll/phone.mp4
시작 전에 구독과 좋아요 부탁드립니다.
::: logo_sting

## 이번 주 시황
::: T01 source=auto period=1w
미국 4대 지수 현황을 체크해 보겠습니다.
다우존스는 이번 주 1.2% @dow 하락했고 S&P 500은 2.4% @spx 빠졌습니다.
나스닥 100은 4.1%로 @ndx 가장 크게 내려왔고요. 장기 채권은 반대로 1.0% @tlt 올랐습니다.
::: T02 ticker=CL=F title="WTI 선물" range=6mo delta=1w
WTI 선물을 보면 82.4달러에서 79.8달러로 @delta 내려왔습니다.
::: T07 source=auto
주가와 환율을 함께 놓고 볼게요.
S&P 500이 2.4% 하락했고 @ring1 환율은 0.9% 올랐습니다. @ring2
우리 주식 계좌는 1.5% 하락하는 한 주였습니다. @ring3

## 중요 이슈 5가지
::: T10 add="PCE 0.3% 상승, 12월 인상 확률 91%"
우리 주식 계좌에 중요한 이슈가 되는 이번 주 기사 다섯 가지를 보겠습니다.
첫 번째는 물가 이야기입니다.
::: T12 title="12월 기준금리 전망" data=data/fomc_prob.csv credit="CME FedWatch, 2026.11.27"
지난주에 없던 빅스텝 가능성이 @row2 14.5%까지 올라왔는데요.
::: T06 ticker=O title="리얼티인컴(O)" range=1y circle=2026-10-14 box=2026-11-01:2026-11-27
금리에 민감한 리얼티인컴 주가를 보면 @circle 10월 저점 이후 꾸준히 반등했습니다. @box
...

## 다음 주
::: T17 data=data/dividends.csv
::: T16 source=auto
::: T18 clip=broll/lynch.mp4 quote="수익 난 종목을 팔고 손실 난 종목을 보유하는 것은|꽃을 꺾고 잡초에 물을 주는 것과 같다" by="Peter Lynch"

## 아웃트로
::: T28
````

**데이터 CSV 예** (`data/fomc_prob.csv`): `label,value,highlight` / `금리 동결,0,` / `0.25%↑,85.5,` / `0.50%↑,14.5,true`

---

## 5. 디자인 토큰 — `brand.yaml`

바이블 수치를 그대로 옮긴다. 템플릿 코드에는 숫자를 직접 쓰지 않고 이 파일만 참조한다.

```yaml
canvas: {width: 1920, height: 1080, fps: 30}
color_convention: us            # kr이면 up/down 토큰만 맞바꿈 (alert_red 강조 규칙은 유지)
colors:
  paper: "#EAEAEA"
  ink: "#1D1D1D"
  navy: "#15314A"
  alert_red: "#DC0A0F"
  label_gray: "#A9A8A8"
  steel: "#4E7A9E"
  up: "#3F9A5F"                 # kr: "#DC0A0F"
  down: "#881722"               # kr: "#1F5FBF"
  buy: "#3DD27F"
  sell: "#B50D11"
  table_bar: ["#E78B9B", "#9E2533"]
  black_box: "#000000"
  dark_slide: "#4A4A4A"
  credit: "#6E6E6E"
  accent: ["#4AB6B2", "#CF6281"]
layout:
  logo: {x0: 1646, y0: 32, x1: 1898, y1: 152}
  title: {cx: 960, cy: 108, glyph_h: 72}
  content: {x0: 96, y0: 180, x1: 1824, y1: 920, baseline: 775}
  subtitle_bar: {x0: 280, y0: 950, x1: 1638, y1: 1034, radius: 10, color: "#000000", opacity: 0.71}
  subtitle_bar_with_sponsor_banner: {dy: -40}
  credit: {right: 1900, y: 1050, size: 18}
fonts:
  subtitle: {file: NanumSquareB.ttf, px: 56, ass_fontsize: 62}   # libass 크기 보정값(§7-3 실측)
  title: {file: GmarketSansBold.ttf, px: 88, fallback: {file: NanumSquareB.ttf, px: 80}}
  number: {file: GmarketSansBold.ttf, px: 96}
  label: {file: NanumSquareB.ttf, px: 30}
  body: {file: NanumSquareR.ttf, px: 30}
subtitle_rules:
  max_chars: 24                 # 공백 포함
  min_duration: 0.8
  hold_gap_max: 0.6             # 문장 사이 쉼이 이보다 길면 0.3초 뒤 끔
  drop_trailing_period: true
  no_break: ['\d[\d,.]*\s*(%|%p|달러|원|억|조|만|배|bp|주)', 'S&P\s?500', '나스닥\s?100']
  prefer_break_after: ['는데', '하고', '면서', '지만', '니까', '으면', '면', ',']
pace:
  max_static_s: 20              # 이보다 길게 같은 화면이면 QA 경고
  target_mean_change_s: 10
motion:
  build_grow_s: 0.5             # 막대 성장·선 그리기
  element_in_s: 0.25            # 페이드 + 위로 12px
  cut: hard
```

---

## 6. 템플릿 규격

모든 템플릿은 같은 인터페이스를 따른다.

```python
class Template:
    id = "T13"
    def states(self, params, data) -> list[str]: ...          # 빌드 상태 이름: ["axis", "bars", "delta"]
    def render(self, state, params, data, brand) -> Image: ... # 1920×1080 RGB
    def animate(self, state) -> AnimSpec | None: ...          # 성장 애니가 필요한 상태면 프레임 수·보간
    def credit(self, params, data) -> str | None: ...         # 데이터 템플릿은 None이면 QA 실패
    def red_count(self, state) -> int: ...                    # 화면당 레드 강조 수(QA ≤ 2)
```

`base.py`가 종이 배경, 제목, 출처, 안전 영역 밖 그리기 금지, 숫자 포맷(`+2.6%`, `-12.8%`, `4,281억 원`)을 공통으로 처리한다. 상승/하락 색은 `brand.colors.up/down`만 쓴다.

### 6-1. v1 우선 템플릿 (주간 정리 시황 블록 + 이슈 블록 필수 요소)

| ID | 파라미터 | 빌드 상태 | 자동 데이터 | 기본 출처 문구 |
|---|---|---|---|---|
| T01 INDEX_RINGS | `period=1w` | `empty` → `dow` → `spx` → `ndx` → `tlt` | `wallstreet.market_snapshot`(^DJI ^GSPC ^NDX TLT) | Yahoo Finance, 기준일 종가 |
| T02 AREA_DELTA | `ticker range delta` | `chart` → `delta` | yfinance 종가 | Yahoo Finance |
| T04 THEME_BAROMETER | `groups=` 기본 5묶음 | `table` → 행 강조(@티커) | 섹터 ETF(XLK…XLRE), 가치/성장(IWD/IWF·IWP), 배당(SCHD VIG DGRO), 성장(QQQ SOXX), 혁신(ARKK BTC-USD) | Yahoo Finance |
| T05 DRAWDOWN_TABLE | `left= right=` 티커 목록 | `table` → 행 강조 | 52주 고점 대비 낙폭(`wallstreet.snapshot_row`) | Yahoo Finance |
| T06 PRICE_CHART | `ticker range style=candle·line` + 주석 `trend= box= circle= tag=` | `chart` → 주석마다 1상태 | yfinance OHLC → Matplotlib 캔들(흰 배경, 상승 초록/하락 빨강) | Yahoo Finance |
| T07 EQUATION_RINGS | `source=auto` | `ring1` → `ring2` → `ring3` | S&P500 1주 등락, USDKRW 1주 등락, 계좌 = (1+a)(1+b)−1 | Yahoo Finance |
| T09 ETF_TOP_WORST | `data=` | `table` | CSV(또는 FinanceDataReader KRX ETF 수익률) | 한국거래소 |
| T10 ISSUE_HUB | `add=` 헤드라인 | 누적 n줄 | 에피소드 안의 이전 T10 상태를 이어 받음 | — |
| T12 HBAR_COMPARE | `data=` label,value,highlight | 행 순차 | CSV | 필수 입력 |
| T13 VBAR_COMPARE | `data=` | `axis` → `bars`(성장 애니) → `delta` | CSV | 필수 입력 |
| T16 WEEK_CALENDAR | `source=auto` | `table` → 날짜 강조 | `events.market_calendar` + 에피소드 일정 | — |
| T18 QUOTE_CARD | `clip quote by` | 1줄 → 2줄 → 이름 | — | — |
| broll / logo_sting / T28 | `clip=` | — | — | 영상 출처(있으면) |

### 6-2. v2 템플릿
T03 히트맵(시총·등락 데이터로 직접 squarify 트리맵), T08 해외 종목 매매 TOP10(예탁결제원 데이터 CSV), T11 기사 캡처(이미지 + 형광 띠 좌표), T14·T15·T17·T19~T27.

### 6-3. 차트를 직접 그리는 이유
레퍼런스는 트레이딩 차트·히트맵 화면을 캡처해 쓰지만, 캡처는 서비스 이용약관 문제가 생길 수 있고 자동화하기도 어렵다. v1은 **원 데이터로 같은 모양의 차트를 직접 그린다**: 흰 배경, 오른쪽 가격축, 캔들 상승 `up`·하락 `down`, 거래량 막대는 하단 15% 높이의 연한 회색. 캡처 이미지를 쓸 때는 `T11`로 넣고 출처를 반드시 적는다.

---

## 7. 타이밍, 자막, 합성

### 7-1. 음성 → 타이밍
1. **녹음(권장):** 대본을 읽어 `voice.wav`로 녹음 → faster-whisper(`large-v3`, 한국어)로 단어 타임스탬프 → 대본 단어열과 음절 단위로 정렬. 정렬되지 않은 구간은 앞뒤 단어 시간으로 보간하고, QA에 "대본과 다른 발화" 목록으로 남긴다.
2. **TTS(선택):** 문장 단위로 합성하고 문장 길이를 실측해 이어 붙인다. 말 속도는 레퍼런스 기준 **분당 340~410음절** 안에 들게 조정한다(바이블 §9-6).
3. 장면 시작 = 그 장면 첫 단어 시작 − 0.15초. 장면 끝 = 다음 장면 시작.
4. `@cue` 빌드 = 표시 바로 앞 단어의 시작 시각(바이블 §8-3: 말하는 순간 0~2초 안).
5. 로고 스팅은 음성 트랙에 2초 공백을 넣고 그 자리에 둔다(스팅 효과음 사용).

### 7-2. 자막 청크 알고리즘 (`cues.py`)
```
for 문장 in 장면.문장들:
    어절들 = 문장.split()
    no_break 정규식에 걸리는 어절 묶음은 하나로 합침          # "12.8%", "S&P 500"
    탐욕적으로 24자 이하가 되도록 자르되,
      자를 후보 중 prefer_break_after 어미로 끝나는 위치를 우선,
      없으면 가장 균등하게 나뉘는 위치
    청크 시작 = 첫 어절 발화 시각, 끝 = 다음 청크 시작 (쉼 > 0.6초면 마지막 어절 끝 + 0.3초)
    0.8초 미만 청크는 앞 청크와 합침(합쳐도 24자 이하일 때), 아니면 경고
    마침표 제거, 쉼표·물음표 유지
```
산출물: 번인용 `subs.ass` + 업로드용 `subtitles.srt`(같은 청크).

### 7-3. 자막 렌더 방식 — 검증 완료
레퍼런스 자막 바는 **글자 길이와 무관한 고정 폭(1358px)**이라, ASS 기본 박스 스타일(`BorderStyle=3`, 글자에 맞춰 늘어남)로는 재현되지 않는다. 그래서 큐마다 **ASS 이벤트 두 개**를 같은 시간에 띄운다.
- Layer 0 `Bar`: `\p1` 벡터 도형으로 1358×84, 반경 10 라운드 사각형을 `\pos(280,950)`에 그림. 색 `&H4A000000`(= 검정, 투명도 0x4A → 불투명 71%)
- Layer 1 `Sub`: NanumSquare Bold, **Fontsize 62**, 흰색, `\pos(959,992)`, 가운데 정렬(`\an5`)

```
[Script Info]
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bar,NanumSquare,20,&H4A000000,&H4A000000,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Sub,NanumSquare,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.20,0:00:03.40,Bar,,0,0,0,,{\pos(280,950)\p1}m 10 0 l 1348 0 b 1353.5 0 1358 4.5 1358 10 l 1358 74 b 1358 79.5 1353.5 84 1348 84 l 10 84 b 4.5 84 0 79.5 0 74 l 0 10 b 0 4.5 4.5 0 10 0{\p0}
Dialogue: 1,0:00:01.20,0:00:03.40,Sub,,0,0,0,,{\pos(959,992)}통상 20% 후반대를 유지하던 기술주 비중이
```

**프로토타입 측정 결과**(이 저장소의 ffmpeg 6.1 + libass, `fontsdir=johnber_shorts_studio/fonts`):

| 항목 | 바이블 규격 | ASS 렌더 실측 |
|---|---|---|
| 바 좌·우 | 280 / 1638 | 279 / 1638 |
| 바 위·아래 | 950 / 1034 | 949 / 1034 |
| 종이(#EAEAEA) 위 바 색 | 234×0.29 ≈ 68 | 68 |
| 글자 높이·폭(같은 문장) | Pillow 56px: 53 / 996px | Fontsize 62: 54 / 994px |

→ libass는 폰트 크기를 em이 아니라 줄 높이 기준으로 해석하므로, **NanumSquare는 `ass_fontsize = px × 1.107`**(56px → 62)로 보정한다. 서체를 바꾸면 이 비율을 다시 잰다(같은 문장을 Pillow와 libass로 렌더해 폭 비교).

광고 하단 배너가 뜨는 구간은 Bar·Sub의 y를 40px 올린 별도 스타일을 쓴다.

### 7-4. 합성 순서 (`compose.py`)
1. **장면 세그먼트**: 상태 PNG를 상태 길이만큼 붙여 장면별 mp4로(정지 상태는 concat demuxer `duration`, 애니 상태는 PNG 시퀀스, B-roll은 1920×1080로 잘라 맞춤). 모두 `-r 30 -pix_fmt yuv420p -c:v libx264 -crf 16` 같은 파라미터로 만들어 스트림 복사 concat이 가능하게 한다. 바뀐 장면만 다시 만든다(파라미터 해시 캐시).
2. **영상 트랙**: `ffmpeg -f concat -safe 0 -i scenes.txt -c copy visuals.mp4`
3. **최종 합성**:
```bash
ffmpeg -i visuals.mp4 -i assets/logo.png -i voice_with_gaps.wav -i assets/bgm/track.mp3 -filter_complex "
  [0][1]overlay=x=1646+(252-overlay_w)/2:y=32+(120-overlay_h)/2:enable='not(between(t,STING_A,STING_B))'[v1];
  [v1]subtitles=subs.ass:fontsdir=longform_studio/assets/fonts[v];
  [2]asplit=2[vo][sc];
  [3]volume=0.15[bg];
  [bg][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[bgd];
  [vo][bgd]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
  -map "[v]" -map "[a]" -c:v libx264 -preset slow -crf 18 -r 30 -pix_fmt yuv420p
  -c:a aac -b:a 192k -movflags +faststart out/final.mp4
```
(로고는 로고 스팅 구간에서만 숨긴다. 출처 문구는 ⑤ 단계에서 슬라이드에 이미 그려져 있다. `loudnorm`은 내부적으로 샘플레이트를 올리므로 `aresample=48000`으로 되돌린다. 이 필터 그래프는 더미 입력으로 ffmpeg 6.1에서 실행해 1920×1080·30fps·H.264/AAC 출력을 확인했다.)

4. **부산물**: `subtitles.srt`, `chapters.txt`(`## 블록` 시작 시각, 첫 줄은 `00:00`), `slides/`(상태별 PNG — 썸네일·쇼츠 재활용).

---

## 8. 자동 QA (`qa.py`) — 바이블 §11 체크리스트를 코드로

| 검사 | 기준 | 실패 시 |
|---|---|---|
| 포맷 | 1920×1080, 30fps, H.264, AAC | 오류 |
| 라우드니스 | `ebur128` 통합 −14±1 LUFS, 트루피크 ≤ −1.5 dBTP | 경고 |
| 자막 길이 | 모든 청크 ≤24자, ≥0.8초, 겹침 없음, 마침표 없음 | 오류 |
| 숫자 분리 | 숫자+단위가 두 청크로 쪼개진 곳 없음 | 오류 |
| 화면 정지 | 같은 화면(상태) 20초 초과 구간 없음, 평균 변화 간격 ≤12초 | 경고 + 해당 문장에 `@cue` 추가 제안 |
| 레드 강조 | 상태마다 `red_count ≤ 2` | 경고 |
| 출처 | 데이터 템플릿에 `credit` 있음 | 오류 |
| 숫자 일치 | 장면 내레이션의 숫자(정규식)가 그 장면 데이터 라벨에 있음 | 경고(목록 출력) |
| 안전 영역 | 템플릿이 그린 bbox가 content/로고/자막 영역 규칙 안 | 오류 |
| 포맷 구성 | weekly: 시황 10항목·이슈 5개·다음 주·명언 블록 존재 | 경고 |
| 말 속도 | 340~410음절/분 | 경고 |
| 고유 문구 | 레퍼런스 고유 문구 금지어 목록(바이블 §9-7) 미포함 | 오류 |
| 육안 검수 | 5초 간격 컨택트시트 + 장면별 첫 프레임 | 사람 확인 |

---

## 9. 사용법 (목표 형태)

```bash
# 1) 에피소드 폴더 만들기 (포맷별 뼈대 episode.md 생성, 시황 블록은 데이터 자동 채움)
python -m longform_studio new weekly --date 2026-11-28
# 2) 대본 다듬고 녹음 → episodes/2026-11-28_weekly/voice.wav
# 3) 미리보기: 음성 없이 문장당 4.3초로 가상 타이밍, 540p 빠른 렌더
python -m longform_studio preview episodes/2026-11-28_weekly
# 4) 본 렌더 + QA
python -m longform_studio build episodes/2026-11-28_weekly
```

`new weekly`가 만드는 뼈대는 바이블 §9-1 순서를 그대로 따른다: 훅(공감형/고백형 중 선택) → 구독 요청 → 로고 스팅 → 시황 ⓐ~ⓙ(T01 T02 T03 T04 T05 T06×2 T07 T08 T06 T09) → 이슈 허브 + 이슈 5칸 → 다음 주(T17 T16) → 명언(T18) → 아웃트로(T28).

---

## 10. 마일스톤

| 단계 | 범위 | 완료 기준 |
|---|---|---|
| **M0 골격** | `brand.yaml`, `base.py`, T12·T13·T06, 청크 알고리즘, ASS 생성, 60초 샘플 합성 | 샘플 프레임을 레퍼런스 프레임과 겹쳐 로고·제목·자막 바·기준선 오차 ±4px 이내(`spec_preview.py --overlay` 방식). 청크 규칙 단위 테스트 통과 |
| **M1 시황 자동화** | T01 T02 T04 T05 T07 T09 + `wallstreet.py` 연결, QA 리포트 | 날짜만 넣으면 시황 블록 6장면이 데이터까지 채워져 렌더됨 |
| **M2 이슈·마무리** | T10 T11 T14 T15 T16 T17 T18 T28, B-roll·로고 스팅·광고 배너 | 실제 대본 1편(16분)으로 최종 mp4 + QA 오류 0 |
| **M3 부가** | TTS 옵션, 썸네일 생성(바이블 §10), chapters, 쇼츠용 슬라이드 내보내기 | — |
| **M4 선택** | 쇼츠 스튜디오 같은 로컬 웹 UI, Remotion 애니 템플릿 시험 | — |

---

## 11. 결정이 필요한 것 (기본값 제안)

| 항목 | 선택지 | 제안 |
|---|---|---|
| 내레이션 | 직접 녹음 / TTS | **직접 녹음.** 레퍼런스는 진행자 목소리이고, 말투 규칙(§9-6)이 목소리 연출에 기대는 부분이 크다 |
| 상승/하락 색 | 미국식 / 한국식 | **롱폼은 미국식**(바이블 §3-2). 쇼츠 카드(`shorts_card.py`)와 다르므로 채널 전체 통일 여부 결정 필요 |
| 제목 서체 | G마켓 산스 Bold / 나눔스퀘어 ExtraBold | G마켓 산스 Bold(무료) 설치 |
| 로고·로고 스팅·진행자 컷아웃 | 직접 제작 | 필수 에셋. 없으면 M0는 텍스트 로고로 진행 |
| 차트 | 직접 그림 / 캡처 | 직접 그림(§6-3) |
| 해외 종목 순매수 TOP10 | 수동 CSV / 자동 수집 | v1 수동 CSV |

---

## 12. 위험과 대응

| 위험 | 대응 |
|---|---|
| 음성 인식 정렬 실패(고유명사·숫자) | 대본 단어 기준 정렬 + 실패 구간 보간 + QA 목록. faster-whisper `initial_prompt`에 그 회차 티커·인명 목록 전달 |
| 폰트 누락 글리프(특수기호 `→`, `↑`) | `johnber_shorts_studio/app/fonts.py:missing_glyphs`로 렌더 전 검사, 대체 문자표 |
| 데이터 지연·결측(yfinance) | 장면에 `asof` 날짜를 출처에 박고, 결측은 `-` 표기 + QA 경고 |
| 저작권(외부 영상·캡처) | B-roll은 라이선스 있는 소스만, 인터뷰 클립은 짧게 + 출처, 레퍼런스 고유 요소 금지어 검사 |
| 렌더 시간(20분 영상) | 장면별 캐시, 미리보기 540p, 최종만 `-preset slow` |
