# 존버나드TV 롱폼 편집기 (`longform_studio`)

녹화·녹음 파일 하나를 [`docs/supetv_editing_bible.md`](../docs/supetv_editing_bible.md) 규격으로 편집한다.
- 긴 무음 줄이기
- 받아쓰기
- 수페TV식 데이터 화면 삽입
- 고정 폭 반투명 자막 바
- 우상단 로고
- −14 LUFS 음량 맞춤
- 자동 품질 검사

## 설치 (PC에서 한 번)

```powershell
winget install Gyan.FFmpeg          # Mac: brew install ffmpeg
pip install -r longform_studio/requirements.txt
```
- 받아쓰기용 `faster-whisper`는 첫 실행 때 음성 모델을 내려받는다(large-v3 약 3GB). NVIDIA GPU가 있으면 훨씬 빠르다.
- 제목 폰트로 G마켓 산스 Bold를 쓰려면 `GmarketSansTTFBold.ttf`를 `longform_studio/fonts/`에 넣는다. 없으면 나눔스퀘어로 그린다.
- 채널 로고는 투명 PNG를 `longform_studio/assets/logo.png`로 넣는다. 없으면 임시 텍스트 로고가 들어간다.

## Claude에게 시키는 법

Claude Code를 **이 저장소 폴더에서 PC로** 열고 이렇게 말하면 된다.

> `D:\녹화\2026-11-27 20-02-24_내보내기.mp4` 를 수페TV 스타일로 편집해줘

Claude가 하는 일:
1. `prepare`로 무음을 줄이고 받아쓴다.
2. `transcript.txt`를 읽고 `plan.md`에 장면을 넣는다. 지수를 말하는 구간에는 링, 수치 비교에는 막대, 종목 이야기에는 차트, 핵심 문장에는 큰 숫자·명언을 넣고, 말하는 순간에 맞춰 빌드한다.
3. `render` 결과와 컨택트시트를 보여 준다.
4. "3분 20초 차트 빼줘", "엔비디아 차트에 11/17 표시"처럼 말하면 `plan.md`를 고쳐 다시 렌더한다. 바뀐 장면만 다시 만든다.

## 직접 실행

```bash
python -m longform_studio prepare "D:/녹화/2026-11-27 20-02-24_내보내기.mp4" --name 1127 --prompt "엔비디아 SOXL QQQ 젠슨 황"
#   → episodes/1127/ : trimmed.mp4, words.json, transcript.txt, plan.md(뼈대)
python -m longform_studio check  episodes/1127            # 자막·장면 규격만 검사
python -m longform_studio render episodes/1127 --preview  # 빠른 저화질
python -m longform_studio render episodes/1127            # 최종
#   → episodes/1127/out/ : final.mp4, subtitles.srt, chapters.txt, qa_report.json, contact_*.jpg
```

옵션:
- `--srt 자막.srt`: 받아쓰기 대신 기존 자막을 쓴다(원본 기준 시각, 무음을 줄이면 시각을 자동으로 옮긴다).
- `--no-trim`: 무음을 줄이지 않는다.

## 녹화 화면(화면 녹화·카메라) 편집 팁

- `prepare`가 원본을 10초 간격으로 찍은 `preview/source_*.jpg`를 만든다. 장면을 고를 때 이 시트로 화면 내용을 확인한다.
- 원본이 16:9가 아니면(세로 폰 화면, 4:3, 울트라와이드) 자르지 않고 종이 배경 위에 그림자와 함께 통째로 얹는다. `fit=cover`로 꽉 채울 수도 있다.
- 작은 글씨·차트는 `zoom="x,y,w,h"`로 그 부분만 크게 보여 준다. 원본 픽셀이나 %로 쓴다. 예: `zoom="0,0,100%,40%"`는 위쪽 40%만 크게.
- 레퍼런스처럼 원본(실사)과 데이터 화면이 약 5:5(기획편)~2:8(주간 정리)이 되도록, 숫자·비교가 나오는 문장마다 데이터 화면을 끼운다.

## plan.md 장면 문법

```markdown
---
source: trimmed.mp4
title: 영상 제목
color_convention: us          # us: 상승 초록·하락 빨강 / kr: 상승 빨강·하락 파랑
---
## 이번 주 시황                  ← 챕터(설명란 타임스탬프)
::: video at=00:00             ← 원본 화면
::: rings at=00:41 title="미국 4대 지수 현황" data="다우존스:+2.1|S&P500:+2.6|나스닥100:+3.6|장기채권:-3.1" start=0 cues=00:43,00:46,00:48,00:51 credit="Yahoo Finance"
::: video at=01:05
```
- 장면은 `at`부터 다음 장면 `at`까지 이어진다.
- `cues`는 항목이 하나씩 나타나는 시각이다. 말하는 순간에 맞춘다(바이블 §8-3).
- `data`의 `!`는 레드 강조다(화면당 1~2개).

| 이름 | 화면 | 주요 값 |
|---|---|---|
| `video` | 원본 화면(음성만 있는 원본이면 종이 배경 + 챕터 제목) | `zoom="x,y,w,h"` `fit=cover\|contain` `title` `credit` |
| `broll` | 다른 영상 클립 | `clip=파일 from=초` |
| `paper` | 제목(+큰 글자) | `title text="줄1\|줄2"` |
| `rings` (T01) | 지수 링 | `data start=0 scale unit` |
| `equation` (T07) | 주가 + 환율 = 계좌 | `data="S&P500:-2.4\|환율:+0.9"` (계좌 자동 계산) |
| `vbar` (T13) | 세로 막대 | `data unit max` |
| `hbar` (T12) | 가로 막대 | `data unit max` |
| `chart` (T06) | 종목 차트(Yahoo 시세로 직접 그림) | `ticker period=6mo style=candle\|area marks="circle:날짜\|box:날짜~날짜\|tag:날짜:글자" csv=파일` |
| `hub` (T10) | 중요 이슈 N가지 | `items="헤드라인1\|헤드라인2" show=2` |
| `bullets` (T14) | 글머리표 | `items` |
| `image` (T11) | 기사·공시 캡처 | `file=이미지 title credit` |
| `bignum` (T21) | 원본을 어둡게 + 큰 숫자 | `label value red=1` |
| `quote` (T18) | 명언 | `quote="줄1\|줄2" by=이름` |

공통 값: `title`, `credit`(우하단 출처). 데이터 화면에 출처가 없으면 품질 검사에서 경고한다.

## 품질 검사 (`qa_report.json`)
| 구분 | 항목 |
|---|---|
| 오류 | 자막 25자 초과, 자막 겹침, 숫자·단위 분리, 출력 규격(1920×1080·30fps) |
| 경고 | 0.8초 미만 자막, 20초 넘게 그대로인 슬라이드, 출처 없는 데이터 화면, 라우드니스 −14±1.5 LUFS 벗어남 |

## 테스트
```bash
python -m pytest longform_studio/tests
```
