# 진행 상황과 다음 세션 인계

기준일: 2026-10-16. 이 문서는 실제 검증 범위와 구현 상태를 분리해 갱신합니다. 구현 파일이 있다는 이유만으로 실제 한국어 전사나 외부 AI 연결을 완료 처리하지 않습니다.

## 조사와 결정

- `/workspace`에는 기존 `etf-analyzer-pro`가 있었고 Johnber Shorts Studio와 AGENTS.md는 없었습니다. 기존 앱을 수정·삭제하지 않고 `/workspace/johnber-shorts-studio`에 별도 앱을 추가했습니다.
- 첨부 `Johnber_Shorts_Codex_Full_Instructions.txt`의 통합 명세·A01–A17을 읽었습니다. 별도 `01_BUILD_SPEC.md`, `02_REFERENCE_MAP.md`, `03_ACCEPTANCE_TESTS.md`, `04_AGENT_GUIDANCE.md`, `reference_screens/`는 실제 작업 폴더에 없었습니다. 접근하지 못한 참고 녹화를 관찰했다고 주장하지 않습니다. 참고 영상은 제작 원본이나 배경으로 쓰지 않습니다.
- 로컬 1인 사용을 위해 FastAPI + 정적 HTML/CSS/JavaScript를 선택했습니다. Node 빌드, Redis, 회원·결제·공개 배포를 필수로 두지 않습니다. Python 3.12, CPU FFmpeg 경로를 기준으로 합니다.
- 원본은 해시 기반 별도 사본으로 보존합니다. 버전 1 프로젝트 JSON, 영속 단일 작업 큐, 원자적 저장을 사용합니다. 전체 데이터는 기본 `.local/data/`에 둡니다.
- 공통 EDL로 영상·음성·자막 시간을 매핑하고 Pillow PNG 레이어를 확정 미리보기와 MP4에 공유합니다. 상세는 `docs/TIMELINE.md`에 기록합니다.
- AI 기능은 수동/SRT 제작 경로와 분리했습니다. 키 미설정을 오류 없는 가짜 AI 결과로 대체하지 않습니다. 규칙 기반 후보는 AI와 구분하고, 외부 전송·모델 다운로드는 각각 동의가 필요합니다.
- ENLIT 브랜드·로고·이미지·폰트를 복제하지 않습니다. 시스템에 설치된 Windows 맑은 고딕/바탕 또는 Linux Noto CJK를 사용하며 글꼴 파일을 포함하지 않습니다.

## 구현 파일과 책임

| 파일 | 역할 |
| --- | --- |
| `run.py`, `설치.cmd`, `실행.cmd` | 가상환경·의존성·도구 검사와 localhost 실행 |
| `requirements.txt`, `requirements.lock`, `requirements-ai.txt`, `requirements-test.txt`, `requirements-test.lock` | 기본 고정 의존성, 선택적 로컬 ASR 및 테스트 의존성 |
| `.env.example`, `.gitignore` | 환경 설정 예시, 키·로컬 데이터·가상환경 제외 |
| `studio/app.py` | 업로드·프로젝트·템플릿·미리보기·작업·다운로드 API |
| `studio/storage.py` | 데이터 경로, 원자적 JSON, 리비전·스냅샷 |
| `studio/subtitles.py`, `studio/validation.py` | SRT/VTT·시간·편집 데이터 검사 |
| `studio/timeline.py` | 원본 기준 cuts, 배속, 자막의 공통 시간 매핑 |
| `studio/media.py` | 실제 FFmpeg 출력, 공유 텍스트 렌더, 무음 감지 |
| `studio/jobs.py` | 단일 영속 작업 큐, 취소·복구·중복 방지·결과 |
| `studio/ai.py` | 선택적 로컬/외부 STT, 실제 제공자 추천, 규칙 후보·캐시·검증 |
| `studio/static/` | 프로젝트·편집·템플릿·작업·완성본 로컬 UI |
| `IMPLEMENTATION_PLAN.md`, `README.md`, `docs/TIMELINE.md`, `PROGRESS.md` | 설계·실행·시간 규칙·검증 범위와 인계 |

## 검증 기록

상세 명령·증거·A01–A17 상태는 [docs/ACCEPTANCE_RESULTS.md](docs/ACCEPTANCE_RESULTS.md)를 기준으로 합니다. Linux에서 실제 MP4를 생성하고 ffprobe·프레임·PCM을 확인했습니다. 실제 서버 프로세스 강제 종료·재시작·중단 작업 재시도, 사용자 이미지 최종 MP4와 Chromium UI도 검증했습니다. A01–A17 전체 PASS 또는 AI 전체 완료로 보고하지 않습니다.

| 범위 | 상태 | 근거 / 다음 확인 |
| --- | --- | --- |
| 수동/SRT → 제목·자막 포함 실제 MP4 | PASS | 실제 H.264/AAC·1080×1920·30fps·yuv420p·6.400초. 키 없는 경로와 가장자리 4색 확인 |
| cuts + 배속 + 자막·음향·영상 동기화 | PASS | 4~6초 삭제 후 1.25배 → 6.400초. 이벤트 0.8/2.4/4.0/5.6초 모두 디코드 측정 해상도 내 일치 |
| 확정 미리보기와 최종 프레임 일치 | PASS | 5시점 제목·자막 평균 RGB 오차 1.000~1.293/255, 글리프 좌표 차이 5px 이하 |
| 프로젝트·템플릿·일괄 ZIP·취소 | PASS (API/렌더 검증) | 스타일·전사·EDL 저장/복원, 템플릿 버전 보존, 세 MP4 ZIP, 실제 인코더 취소·원본/직전 성공본 보존 |
| 실제 서버 프로세스 재시작 A13 | PASS (Linux) | 테스트 Uvicorn 프로세스 그룹 SIGKILL → 재시작 → interrupted·저장 프로젝트 보존 → 재시도 실제 MP4 성공 |
| 사용자 이미지 로고·배경 | PASS (API/렌더 검증) | 이미지 업로드·ID 저장·경로 주입 제거·확정 프레임 픽셀과 실제 MP4 색상 검증 |
| 실제 브라우저 화면·조작 A16 | PASS (기록 범위) | Chromium 1920×1080·1366×768·모바일 폭390 화면. 문장별 스타일 자동 저장·템플릿 생성/v2·색상만 적용·규칙 후보 실제 작업·이미지 등록·드래그·키보드 이동·새로고침 복원. JS 오류 없음 |
| 실제 한국어 음성 자동 전사 A03 | BLOCKED | 실제 한국어 음성 자료 없음. Hugging Face 모델 요청 HTTP 403으로 다운로드/실행 확인 불가 |
| 인증된 실제 외부 AI 추천 A04 | BLOCKED | 사용 가능한 제공자 키/권한과 사용자 외부 전송·비용 동의 필요 |
| Windows 실기 A17 | NOT RUN | 현재 검증 머신은 Linux; Windows에서 설치·경로·한글 글꼴·출력 확인 필요 |

최종 전체 회귀 명령은 `JOHNBER_LIVE_TESTS=1 .venv/bin/python -m unittest discover -s tests -v`이며 **38 tests / 45.116초 / OK, 건너뛴 검사 없음**이었습니다. AI 어댑터 13개·핵심 데이터/시간/보안 검사 9개·실제 렌더/API 통합 검사 10개·타이포그래피 검사 4개·사용자 이미지 검사 1개·실제 프로세스 복구 검사 1개를 포함합니다. 전체 로그는 `.local/sample-output/final-test-run.log`입니다. AI 검사는 모의 제공자 계약 테스트이며 실키·실모델을 사용한 자동 AI 검증과 구분합니다. 기본 명령에서 `JOHNBER_LIVE_TESTS`를 지정하지 않으면 실제 프로세스 강제 종료 검사는 건너뜁니다. Python compileall·JavaScript 구문 검사와 설치된 의존성 40개 호환성 검사도 통과했습니다.

샘플은 자체 제작 10초 영상과 한국어 수동 SRT로 생성했습니다. 소수점·쉼표가 윗줄로 올라가는 문제를 실제 프레임에서 찾아 공유 글리프 기준선을 수정하고, 검수 MP4와 PNG를 재생성했습니다. 사람이 확인한 정지 프레임과 디코딩한 음향 이벤트를 기록했습니다. Chromium의 실제 MP4 재생 시작도 1080×1920·6.4초·readyState 4·21프레임·오류 없음으로 확인했습니다. 사람이 전체 영상을 연속 재생하거나 음성을 청취한 검수는 수행하지 않았습니다.

| 결과 | 프로젝트 루트 기준 실제 경로 |
| --- | --- |
| 단일 MP4 | `.local/sample-output/존버나드_수동제작_6.4초.mp4` |
| 프로젝트 JSON | `.local/sample-output/sample-project.json` |
| 세 MP4 ZIP | `.local/sample-output/three-shorts.zip` |
| 한글·숫자·4개 모서리 확인 프레임 | `.local/sample-output/contain-four-corners.png` |
| 5시점 미리보기/디코딩 프레임 | `.local/sample-output/preview-*.png`, `render-*.png` |
| 측정 원자료 | `.local/sample-output/automated-metrics.json` |
| 실제 서버 강제 종료·재시작·재시도 근거 | `.local/sample-output/live-recovery-result.json` |
| 사용자 로고·배경 실제 MP4 | `.local/sample-output/user-assets-verified.mp4` |
| Chromium 조작 기록 | `.local/ui-evidence/browser-extended.json` |
| Chromium 실제 MP4 재생·새로고침 상태 | `.local/ui-evidence/browser-playback.json` |
| UI 화면 증거 | `.local/ui-evidence/editor-1920.png`, `editor-final-1366.png`, `editor-mobile.png`, `candidates-1920.png` |
| 샘플 원본 / 수동 자막 | `.local/sample-input/한글 공백 동기화 원본.mp4`, `수동 테스트 자막.srt` |

배포 가능한 샘플 사본은 `samples/demo-source.mp4`, `demo-subtitles.srt`, `demo-project.json`, `demo-export.mp4`입니다. 패키징 대상은 `/workspace/Johnber_Shorts_Studio.zip`이며 Windows 사용자가 가상환경이나 검증용 `.local/` 폴더 없이도 시작할 수 있도록 코드·문서·테스트·샘플을 포함합니다. 가상환경·사용자 데이터·`.env`·키는 배포 ZIP에서 제외합니다.

## 남은 범위와 제약

마지막 스타일 입력 범위 조정 뒤 관련 core·타이포그래피·이미지·영상 통합 검사 **24개 / 19.145초 / OK**를 재실행했습니다. 로그: `.local/sample-output/final-targeted-test-run.log`. 브라우저의 저장 응답을 1300ms 늦추고 연속 입력한 뒤 저장 큐를 비우는 검사에서도 로컬·서버가 모두 최종 입력으로 일치하고 미저장 상태가 남지 않았습니다(`.local/ui-evidence/browser-save-race.json`).

- **실제 AI 검증 미완료:** 어댑터와 모의 제공자 기반 계약/오류 테스트는 실제 제공자 연결, 실제 한국어 인식 품질을 대체하지 않습니다. 키는 `.env`나 환경 설정에만 입력하며 채팅·프로젝트·Git에 넣지 않습니다.
- **Windows 실기 미검증:** `설치.cmd`는 Python 3.12 실행기와 FFmpeg `PATH`가 필요합니다. OS 간 시스템 글꼴이 다르므로 최종 제작 PC에서 확정 프레임·MP4를 확인해야 합니다.
- **성능 미측정:** 업로드 4096MB·원본 14400초 한도는 설정값입니다. 10~60분 실사용 영상의 시간·메모리·디스크 성능을 측정했다고 주장하지 않습니다. 작업은 한 번에 하나씩 처리합니다.
- **취소 지연:** FFmpeg는 해당 프로세스를 정리하지만, 로컬 모델 로딩·추론 또는 이미 외부에 전달된 요청은 즉시 철회되지 않을 수 있습니다. 외부 비용은 제공자 정책에 따릅니다.
- **미디어 포함 이식 미지원:** 프로젝트 JSON만으로 영상·이미지가 이동하지 않습니다. 동일 해시 원본을 먼저 업로드하고 로고·배경을 다시 등록하거나 전체 데이터 폴더를 백업·복원해야 합니다.
- **실행 취소 범위:** 프런트엔드 현재 세션의 undo/redo와 저장 시 영속 프로젝트 스냅샷은 별도입니다. 서버 재시작 후 무제한 UI 되돌리기를 보장하지 않습니다.
- **자막 분리 시간:** 글자 위치 비율로 초기 시각을 나누며 단어 강제 정렬은 아닙니다. 원음과 비교해 분리한 자막의 시각을 확인·수정해야 합니다.
- **문장별 스타일 범위:** 전사 문장에 보관하므로 같은 문장을 사용하는 다른 클립에도 반영됩니다. 클립마다 독립적인 디자인은 클립 범위 설정을 사용합니다. UI에 이 범위를 명시합니다.
- **현재 자산 범위:** 텍스트 로고, 사용자 PNG/JPEG/WEBP 로고·배경 등록과 최종 MP4 합성을 검증했습니다. BGM, 애니메이션, 모자이크 추적, YouTube 원본 가져오기, 플랫폼 게시·예약은 미구현 범위이며 완료된 기능으로 표시하지 않습니다.

## 다음 세션 순서

최종 소스·Windows 실행 도구·테스트·자체 제작 샘플·검수 증거를 `/workspace/Johnber_Shorts_Studio.zip`으로 패키징하고 ZIP 무결성을 확인했습니다. 사용자 데이터, 가상환경, `.env`, 실제 API 키는 포함하지 않습니다. 원본 ETF 저장소의 tracked/untracked 변경은 없습니다.

1. `README.md`와 검증 기록을 읽고 저장 프로젝트·샘플을 그대로 활용합니다. 기존 파일을 삭제하거나 통째로 재작성하지 않습니다.
2. 현재 수동/SRT 제작 경로의 검증 결과와 실제 샘플 경로를 먼저 확인합니다. 실패한 항목이 있으면 해당 로그·프레임을 근거로 수정합니다.
3. 사용자가 권한을 가진 실제 한국어 강의 원본을 준비하고 선택적 로컬 ASR을 확인합니다. 모델 다운로드는 UI 동의 후 수행하고 A03을 실측합니다. 숫자·티커·고유명사를 원음과 대조합니다.
4. 사용자가 외부 AI를 원하면 서버 환경 설정의 키 존재 여부만 확인합니다. 제공자·전송 범위·미확인 비용을 알린 뒤 앱의 명시적 동의를 통해 실제 A04를 실행합니다. 실패 시 SRT/수동 경로를 유지합니다.
5. Windows에서 `설치.cmd` → `실행.cmd` → 실제 MP4 출력까지 A17을 검수합니다. 공백·한글 경로, 포트 충돌, FFmpeg 누락, 시스템 글꼴을 포함합니다.
6. 실제 10~60분 자료로 성능과 장시간 동기화를 측정한 뒤 후순위 자산·음악·추가 효과를 확장합니다. 결제·외부 게시·공개 배포·관리자 권한 변경은 임의로 수행하지 않습니다.


## GitHub 전달 준비 — 2026-10-16

사용자가 새 브랜치 업로드를 명시적으로 승인했습니다. 기존 ETF 파일을 변경하지 않고 저장소 하위 독립 폴더에 소스와 샘플을 포함했습니다. GitHub 전달 브랜치: `codex/johnber-shorts-studio`. 다운로드 패키지: 저장소 루트 `downloads/Johnber_Shorts_Studio.zip`. Windows 설치 스크립트는 FFmpeg/ffprobe 누락을 성공으로 표시하지 않고 설치 전에 명확히 중단하도록 정리했습니다. Windows 실기 검증 상태는 여전히 NOT RUN입니다.
