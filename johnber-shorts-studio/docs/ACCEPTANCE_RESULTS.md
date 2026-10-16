# 존버나드 쇼츠 스튜디오 검수 기록

검수일: 2026-10-16 (Asia/Seoul). 자동 검수 환경: Linux x86_64, Python 3.12.14, FFmpeg/ffprobe 7.1.5, FastAPI 0.141.1, Pillow 12.3.0. **로컬 제작 경로의 검증과 AI 실연결·Windows 실기 검증은 별개이다.**

## 실행한 자동 검사

```bash
.venv/bin/python -m unittest discover -s tests -v
```

실제 서버 중단·복구 검사를 포함하려면 POSIX 환경에서 다음과 같이 실행한다. 기본 명령에서는 이 한 검사가 `SKIP`되며, Windows에서는 해당 POSIX 강제 종료 검사가 적용되지 않는다.

```bash
JOHNBER_LIVE_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
```

최종 전체 실행 결과: **38 tests / 45.116 seconds / OK / SKIP 0개**. 실제 실행 명령은 위 `JOHNBER_LIVE_TESTS=1` 명령이며 로그는 `.local/sample-output/final-test-run.log`에 보존했다. 구성은 AI 어댑터 13, 시간축·자막·스타일·추천·보안 계약 9, 실제 제작 통합 10, 숫자 기준선 회귀 4, 사용자 에셋 실제 출력 1, 실제 서버 중단·복구 1개이다. 외부 API 호출은 하지 않았고 제공자 오류는 모의 응답으로 검증했다. Windows 기본 명령은 `.venv\Scripts\python.exe -m unittest discover -s tests -v`이다.

전체 검사 이후 UI 입력 범위와 공통 렌더러의 범위를 맞추는 작은 수정(자간 -5~40 허용, 외곽선 0~20, 최소 글자 10px, 최소 행간 0.6)을 반영했다. 기존 스타일 검사에 음수 자간·10px 실제 글꼴 선택·행간 0.6 확인을 추가하고, 영향받는 제작 경로를 다시 검사했다. 최종 명령 `.venv/bin/python -m unittest tests.test_core tests.test_typography tests.test_assets tests.test_integration -v`의 결과는 **24 tests / 19.145 seconds / OK**이며 `.local/sample-output/final-targeted-test-run.log`에 보존했다. 38개 전체 검사는 이 좁은 수정 직전에 실행한 것이고, 마지막 수정 후 검사는 이 24개이다.

별도 선행 검수로 `JOHNBER_LIVE_TESTS=1 .venv/bin/python -m unittest tests.test_live_recovery -v` **1/1 PASS, 4.488초**, `.venv/bin/python -m unittest tests.test_assets -v` **1/1 PASS, 2.018초**도 확인했다. 전자는 독립 테스트 서버의 프로세스 그룹만 강제 종료하고 실제 Uvicorn 재실행→중단 상태→저장 프로젝트 복원→재시도 MP4 성공을 확인한다. 후자는 사용자가 올린 로고/배경 이미지의 API→미리보기→실제 MP4 픽셀을 확인한다. 보안 검사에서는 자막/클립 ID의 따옴표·태그·경로·과도한 길이를 거부하고 사용자 JSON의 직접 로고/배경 파일 경로를 제거한다.

클라우드 샌드박스의 로컬 socketpair 제한 때문에 TestClient 통합 검사는 승인된 로컬 실행 컨텍스트에서 실행했다. 공개 배포·외부 데이터 전송·관리자 권한 변경은 하지 않았다.

## 자료와 실제 출력

참고 UI 녹화나 참고 서비스의 배경·로고를 원본으로 사용하지 않았다. 테스트가 자체 생성한 10초, 640×360, 30fps MP4를 사용했다. 가장자리 빨강·초록·파랑·노랑 표식, 원본 타임코드, 장면 변화, 1/3/7/9초의 흰색 플래시와 880Hz 음향 표식, 4~6초 무음을 넣었다. 음향은 결정적인 합성 테스트 신호이며 한국어 발화가 아니다. 수동 SRT에는 한글, SOXL/TQQQ/SCHD, `3.07%`, `0.1%p`, `1,000,000원`, 수동 줄바꿈을 넣었다.

| 증거 | 경로 (프로젝트 루트 기준) |
| --- | --- |
| 자체 제작 원본 | `.local/sample-input/한글 공백 동기화 원본.mp4` |
| 수동 한국어 SRT | `.local/sample-input/수동 테스트 자막.srt` |
| 실제 단일 MP4 | `.local/sample-output/존버나드_수동제작_6.4초.mp4` |
| 편집 프로젝트 | `.local/sample-output/sample-project.json` |
| 출력 SRT / 텍스트 | `.local/sample-output/sample-output.srt`, `sample-output.txt` |
| 세 MP4 ZIP / 압축 해제본 | `.local/sample-output/three-shorts.zip`, `.local/sample-output/batch/` |
| 모서리·한글·숫자 검수 프레임 | `.local/sample-output/contain-four-corners.png` |
| 같은 시점의 미리보기 / MP4 디코딩 프레임 | `.local/sample-output/preview-*.png`, `render-*.png` |
| 측정 원자료 | `.local/sample-output/automated-metrics.json` |
| 영속 프로젝트·작업 데이터 | `.local/acceptance-data/` |
| 실제 프로세스 종료·복구·재시도 | `.local/sample-output/live-recovery-result.json`, `live-recovery-server.log` |
| 사용자 로고·배경 이미지 실제 MP4 | `.local/sample-output/user-assets-verified.mp4` |
| Chromium UI 동작 기록 | `.local/ui-evidence/browser-workflow.json`, `browser-extended.json` |
| Chromium 실제 MP4 재생·새로고침 | `.local/ui-evidence/browser-playback.json`, `actual-mp4-browser-playback.png`, `job-browser-refresh.png` |
| Chromium 검수 스크립트 | `.local/ui-evidence/johnber-browser-frontend.py`, `johnber-browser-workflow.py`, `johnber-browser-extended.py`, `johnber-browser-playback.py` |
| 1920/1366/모바일 편집 화면 | `.local/ui-evidence/editor-1920.png`, `editor-final-1366.png`, `editor-mobile.png` |
| 저장소에 포함한 재현 샘플 | `samples/demo-source.mp4`, `demo-subtitles.srt`, `demo-project.json`, `demo-export.mp4` |

샘플 JSON은 원본 영상을 포함하지 않는다. 새 기본 데이터 폴더에서 열려면 샘플 원본을 먼저 업로드하고 JSON을 가져온다. `.local/`은 Git에서 제외하며 테스트를 재실행하면 샘플을 다시 생성한다. 샘플 JSON은 검수용 클립 하나를 포함하고 실제 일괄 출력은 별도로 저장된다.

## 실제 측정

출력: **H.264 / AAC / yuv420p / 1080×1920 / 30fps / 6.400초**, 디코딩한 음성도 **6.400초**. 기대 길이는 `(10-2)/1.25 = 6.4초`이다. 무음 감지 결과는 원본 **3.999667~6.000354초**였다. 생성 테스트의 소수점·쉼표 기준선 오류를 실제 프레임 육안 검사에서 발견하여 공통 텍스트 렌더러를 수정한 뒤 MP4와 모든 비교 프레임을 재생성했다. 최종 프레임에서 한글 글리프, `3.07%`, `0.1%p`, `1,000,000원`, 4개 모서리 표식을 직접 확인했다.

| 원본 이벤트 | EDL 기대 출력 시각 | 디코딩 음향 시작 | 디코딩 영상 플래시 | 디코딩 자막 시작 |
| --- | --- | --- | --- | --- |
| 1초 | 0.800 | 0.800 | 0.800 | 0.800 |
| 3초 | 2.400 | 2.400 | 2.400 | 2.400 |
| 7초 | 4.000 | 4.000 | 4.000 | 4.000 |
| 9초 | 5.600 | 5.600 | 5.600 | 5.600 |

이 표의 오차는 오디오 RMS 10ms 창과 영상 1/30초 프레임 해상도 내 0ms이다. 실제 한국어 ASR 단어 타이밍 정확도에 대한 주장이 아니다. 자막 경계는 1/30초 격자에서 올림하며 EDL 내부는 초 단위 부동소수점으로 한 번 계산한다.

0.0/0.4/2.5/4.1/6.1초의 제목·자막 영역 비교에서 평균 RGB 절댓값 오차는 **1.000~1.293/255**이고 밝은 글리프의 외곽 좌표 차이는 각 축 **5px 이하**였다. 이는 가로 캔버스 0.5%(5.4px) 안이다. 강조가 켜진 시점과 긴 숫자·수동 줄바꿈 시점이 포함된다. 오디오를 사람이 청취하거나 전체 영상을 사람이 연속 재생한 검수는 하지 않았으며, 프레임과 PCM 디코딩 검수를 구분한다.

실제 Chromium에서 출력 MP4의 재생도 확인했다. 최종 증거의 값은 `videoWidth=1080`, `videoHeight=1920`, `duration=6.4`, `readyState=4`, `currentTime=0.542916`, `paused=false`, `error=null`, 디코딩 프레임 20개이다. 이는 브라우저가 실제 파일을 디코딩하며 시간이 진행함을 확인한 검사이며 사람의 청취나 전체 연속 재생 검수는 아니다. 새 렌더 작업 ID를 지정해 `1/2 영상 출력 중 · 처리 중 0%`인 상태에서 브라우저를 새로고침한 뒤 같은 작업·상태가 복원되는 것도 확인했다. UI 검수 스크립트는 이 클라우드의 `/usr/bin/chromium`과 `http://127.0.0.1:8765`를 대상으로 실행했으며 Windows/다른 경로에서는 실행 경로를 조정해야 한다.

## 인수 기준별 결과

`PASS`는 아래 명시한 실행 범위만 의미한다. 기준의 일부만 실행했으면 `NOT RUN`을 함께 기록하며 전체 인수 완료로 집계하지 않는다.

| ID | 상태 | 실행·예상·실제 결과와 증거 | 남은 범위 |
| --- | --- | --- | --- |
| A01 영상 등록 | PASS | `test_01`: 한글/공백 MP4 업로드, 실제 10초/640×360/음성 있음 확인. 이름만 MP4인 손상 파일을 한국어 400 오류로 거부. | 장시간·대용량 실사용 성능은 미측정. |
| A02 API 없는 제작 | PASS | `test_02`: 키를 빈 값으로 격리하고 SRT·수동 구간·제목·자막 MP4 생성. AI 상태 remote_key=false. 중복 클릭은 같은 실행 중 작업 ID. | 실제 AI 사용 가능 상태를 의미하지 않는다. |
| A03 한국어 전사 | BLOCKED | 실제 한국어 음성 원본·다운로드된 ASR 모델이 없어 실측하지 않음. 자동 전사 어댑터의 모의 응답/캐시/오류 검사는 별도. | 한국어 원음으로 인식·교정·사전 품질 확인 필요. |
| A04 AI 추천 | BLOCKED | 연결된 제공자 키가 없어 실제 추천·의미 완결성 검수하지 않음. `test_core`는 역전/음수/범위 밖/없는 근거/새 숫자/과도 중복을 거부하는 계약 검사 통과. | 실제 제공자·모델·비용 동의 후 실호출 필요. |
| A05 강의 화면 보존 | PASS | `test_03`: 디코딩 프레임의 모서리 4색 모두 검출. `contain-four-corners.png` 직접 열어 전체 원본 비율·제목/자막 분리 확인. | 사용자 지정 크롭은 추가 사용자 검수 필요. |
| A06 스타일·자막 저장 | PASS | `test_04`, `test_core`: 텍스트·줄바꿈·일반/강조 색·크기·배경·좌표의 저장·재읽기, EDL 불변 확인. 실제 Chromium에서 문장 스타일 자동 저장·드래그·키보드 좌표 조정·프로젝트 새로고침 복원을 확인. 실제 서버 재시작 후 저장 프로젝트 복원도 확인. 최종 한글·숫자 프레임 육안 확인. | 모든 사용자 글꼴·긴 문장 조합을 전수 검사한 것은 아님. |
| A07 비파괴 삭제 | PASS | 4~6초 삭제를 EDL과 실제 MP4에 반영. 역사 스냅샷의 이전 자막/클립으로 복원. 원본 SHA-256 `1af9108797b32cebdd9b58ad97496d4e9f0f45494243092b3952debcc584bae1` 유지. | UI 실행 취소 버튼 동작은 별도 UI 검수. |
| A08 무음·배속·동기화 | PASS | `test_05`: 실제 무음 감지, 출력 길이와 시작/중간/끝 음향·영상·자막 이벤트 모두 위 표의 기대값 일치. | 실제 강의의 첫/끝 음절 검수·ASR 타임코드는 미실행. |
| A09 미리보기 일치 | PASS | `test_06`: 공통 렌더러의 5시점 PNG와 실제 MP4 디코딩 프레임 비교. RGB 오차·글리프 좌표 확인, 증거 PNG 보존. | 모든 글꼴·외부 사용자 자산 조합을 검수한 것은 아님. |
| A10 템플릿 버전 | PASS | `test_07`: 버전1 스타일 스냅샷은 템플릿 버전2 수정 후에도 보존, 다른 클립에 버전2 사용. 실제 Chromium에서 템플릿 생성→버전2 수정→색상만 적용 범위를 확인. | 모든 조합의 일괄 적용/사용자 수정 덮어쓰기를 전수 검사한 것은 아님. |
| A11 실제 MP4 | PASS / 일부 NOT RUN | 실제 ffprobe 코덱·픽셀·FPS·해상도·길이와 여러 시점 영상/PCM 디코딩 확인. 제목·한글·숫자는 디코딩 프레임을 직접 확인. 실제 Chromium MP4 재생에서 1080×1920, 6.4초, 재생 시간 진행·20프레임 디코딩·error=null 확인 (`browser-playback.json`). | 사람이 전체 연속 재생·음성 청취한 검수는 NOT RUN. |
| A12 개별/일괄 출력 | PASS | `test_07`: MP4 3개+ZIP 실제 생성. 동일 제목, 긴 제목, Windows 금지문자 정리·순번으로 중복 회피. ZIP을 풀어 각 MP4 메타데이터·프레임 디코딩 성공. | 파일명 길이는 Windows 금지문자와 제한을 검사했으며 Windows 실기는 미검증. |
| A13 재시작 복구 | PASS | `test_live_recovery`: 자기 테스트 Uvicorn 프로세스 그룹만 실제 강제 종료, 서버 재실행, 작업 interrupted, 저장 프로젝트 복원, 실제 MP4 재시도 성공. `test_08`은 이전 성공본·원본 보존 확인. Chromium에서 프로젝트·편집 시각·선택 패널 복원과 실제 실행 중인 동일 작업의 새로고침 후 상태 복원도 확인. 근거 `live-recovery-result.json`, `browser-extended.json`, `browser-playback.json`. | 이 강제 종료 검사는 POSIX 전용. Windows 프로세스 종료 동작은 미검증. |
| A14 취소·실패 | PASS (실행 범위) | `test_09/10`: 실제 FFmpeg 인코더 실행 후 취소·종료 확인, 이전 성공 MP4·원본 해시 유지. API 취소 상태 영속화, 디스크 부족/FFmpeg 누락/키 누락/401/429/500/네트워크 실패를 격리 모의 검사. 비밀키·응답 본문 오류 노출 없음. | 실제 디스크를 고갈하거나 실계정 요금 한도를 소진하지 않음. |
| A15 캐시·비용 | PASS (오프라인 계약) | `test_core`: 스타일만 변경하면 추천 공급자 모의 함수 1회 유지, 전사 텍스트/모델 변경 시 3회로 증가. 미동의/키 없음이면 HTTP 연결 객체 자체를 생성하지 않음. 전사 캐시 검사는 `test_ai_adapters.py`. | 실제 제공자 과금·네트워크 계측은 BLOCKED. |
| A16 화면·접근성 | PASS (기록된 범위) | 실제 Chromium 1920×1080/1366×768/390px 모바일 화면 검사. 독립 패널 스크롤, 주요 컨트롤 접근, 가로 넘침 없음, 실제 드래그 저장·Shift+방향키 10px 조정·프로젝트 새로고침 복원 확인. 규칙 기반 후보 작업→클립 적용, 로고 업로드·설정 모달 자동 저장도 검수. 브라우저 JS 오류 0개. 증거 `.local/ui-evidence/`. | 스크린리더·모든 키보드 경로 및 다른 브라우저는 미검증. |
| A17 Windows | NOT RUN | Linux에서만 실행. Windows 설치·실행 스크립트가 있다는 사실을 실기 통과로 취급하지 않음. | Windows PC에서 설치·실행·한글 경로·FFmpeg·글꼴 검증. |

## 재검수할 때

실제 한국어 발화 파일을 별도로 제공받아 A03을 실행한다. 선택한 제공자와 모델, 외부로 보낼 음성/전사문, 비용을 확인한 뒤 환경 설정에 키를 안전하게 넣고 A04의 실제 연결을 검수한다. `tests/test_ai_adapters.py`의 모의 응답 성공은 AI 연결 성공이 아니다. Windows·장시간 강의·사람의 음성 청취와 전체 재생은 아직 별도 검수 범위로 남겨 둔다.
