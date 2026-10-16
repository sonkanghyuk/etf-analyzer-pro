# 구현 계획·설계 기록

## 0. 시작 시점 조사 결과 (2026-10-16)

- 저장소 `sonkanghyuk/etf-analyzer-pro`에는 **ETF Analyzer Pro(Streamlit)** 만 있었고, 기존 Johnber Shorts Studio 코드·`AGENTS.md`·실행 스크립트는 없었습니다.
- 전달받은 자료는 `Johnber_Shorts_Codex_Full_Instructions.txt` 한 파일(01_BUILD_SPEC + 03_ACCEPTANCE_TESTS 내용 포함)입니다.
  `02_REFERENCE_MAP.md`, `reference_screens/`, `04_AGENT_GUIDANCE.md`, 참고 화면녹화는 **받지 못했습니다**. 따라서 UI는 명세의 문장 설명만 보고 독립적으로 설계했습니다.
- 결정: 기존 ETF 앱을 건드리지 않고 하위 폴더 `johnber_shorts_studio/`에 새 로컬 웹앱으로 시작.

## 1. 기술 구성과 이유

| 영역 | 선택 | 이유 |
|---|---|---|
| 서버 | Python FastAPI + uvicorn, `127.0.0.1` 바인딩 | Windows에서 설치가 단순, FFmpeg·전사 엔진과 같은 언어 |
| 프런트 | 빌드 없는 바닐라 JS(ES 모듈) | Node 설치 불필요, 설치 실패 지점 감소 |
| 저장 | SQLite(WAL) + 파일 폴더 분리 | 1인 로컬 사용, 영속 작업 큐 겸용 |
| 영상 | FFmpeg(인자 배열 실행, 셸 문자열 연결 없음) | CPU 경로 우선, H.264/AAC/yuv420p/faststart |
| 글자 렌더링 | **Pillow 단일 렌더러 → PNG** | 미리보기·출력이 같은 PNG를 써서 줄바꿈·글꼴·위치 일치 |
| 전사 | faster-whisper(로컬) | 외부 요금 없음, 단어 시각 제공 |
| AI 추천 | Anthropic Claude API(공식 SDK), 구조화 출력(JSON Schema) | 스키마 강제 + 서버 측 재검증 |

Redis·클라우드 스토리지·회원 시스템은 만들지 않았습니다.

## 2. 데이터 개념 ↔ 구현

| 명세 개념 | 구현 |
|---|---|
| Project / SourceAsset | `projects`, `sources`(해시·길이·해상도·fps·음성·썸네일·프록시) |
| TranscriptRevision | `transcripts`(kind=original/working, version, content_hash) |
| Clip / EditDecisionList / SubtitleCue / StyledTextSpan | `clips.data_json` = `range`, `cuts[]`, `speed`, `cues[]`(+`emphasis` 글자 범위, `style_override`, `deleted_speech`) |
| TemplateVersion | `templates` + `template_versions`(불변 버전). 클립은 `{id, version}`을 기록 |
| RenderJob | `jobs`(상태·진행률·단계·오류 코드·재시도 가능·로그·dedupe_key) |
| ExportArtifact | `artifacts`(ffprobe 결과·썸네일·SRT·적용 템플릿·당시 클립 수정 시각) |
| 캐시 | `transcribe_cache`(원본 해시+엔진+모델+언어+설정+사전), `recommendations.cache_key`(전사 해시+모델+effort+프롬프트 버전+설정) |
| 편집 이력 | `clip_history`(undo/redo 스택, 클립당 100개) |

스키마 버전은 `meta.schema_version`, 순차 마이그레이션은 `app/db.py`의 `MIGRATIONS`(v1 초기, v2 프록시 열).

## 3. 시간 모델(EDL) — 내부 단위와 반올림 규칙

- 내부 단위는 **정수 ms**. 계산 중 float, 외부 표기 시 반올림.
- 원본 시간 → (삭제 구간 제외) 편집 시간 → (÷배속) 출력 시간. 영상·음성·자막·강조가 `app/edl.py` 하나의 매핑을 사용.
- 남길 구간 길이는 **출력 프레임 격자(1000/30 ms)에 맞춰 반올림**하고, 렌더러는 같은 길이로 영상 프레임 수(`trim=end_frame`)와 오디오 샘플 수(`atrim=end_sample`)를 맞춥니다 → 구간이 많아도 영상·음성 누적 오차 없음.
- 1프레임 미만 조각은 버림. 구간 경계에서 300ms 미만만 남는 자막 조각은 클립에 가져오지 않음.
- 배속은 연결 후 `setpts=PTS/s` + `atempo`(음높이 보존). 미리보기는 같은 세그먼트 표로 원본 재생 위치를 건너뛰고 `playbackRate`를 적용.

## 4. 미리보기 = 출력 보장 방식

1. 서버가 장면을 계산: 배경 PNG, 전경 PNG(가리기 영역·제목·고정문구·로고), 영상 배치(크롭·크기·위치), 자막마다 PNG와 좌표.
2. 브라우저는 이 PNG를 그대로 축소해 겹치고, `<video>`만 직접 배치(같은 좌표).
3. FFmpeg는 같은 PNG를 같은 좌표에 `overlay`(자막은 `enable=between(t,…)`).
4. 검증: `tests/ui_preview_match.py`가 브라우저 화면과 MP4 프레임의 글자 경계를 비교(목표 0.5% 이내).

## 5. 단계별 진행과 검수 조건

| 단계 | 내용 | 검수 조건 | 상태 |
|---|---|---|---|
| M1 | 영상 등록·SRT/수동 자막·수동 구간·기본 세로 레이아웃·제목/자막·저장·MP4 1개 | A01·A02·A05·A11 | 완료(Linux 검증) |
| M2 | 로컬 전사, AI 추천(검증·캐시·비용 확인), 규칙 후보 | A03·A04·A15 | **코드 완료 / 실제 제공자·실제 한국어 음성 검증은 BLOCKED** |
| M3 | 템플릿 3종·버전·일괄 적용, 강조, 배치 편집, 배속·무음 제거, 큐·일괄 ZIP, 복구·취소 | A06~A10·A12~A14·A16 | 완료(Linux 검증) |
| 후순위 | YouTube 가져오기, 추가 템플릿 2종, 강조 애니메이션, 배경음악·전환, 모자이크, 게시 | — | ‘준비 중’ 표시만 |

## 6. 막힌 의존성

- 이 개발 환경에서 Hugging Face·OpenAI 등은 네트워크 정책상 차단 → 전사 모델을 받을 수 없어 실제 한국어 인식 미검증.
- 사용자 Anthropic API 키 없음 → 실제 추천 품질·응답 미검증(잘못된 키로 실제 API 호출해 인증 오류 처리만 확인).
- Windows 실기 없음 → `설치.cmd`/`실행.cmd`·Windows 경로·맑은 고딕 자동 인식 미검증.
