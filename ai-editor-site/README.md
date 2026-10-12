# Clipora — AI 숏폼 자동 제작 사이트 (데모)

강의·강연·인터뷰 촬영본을 올리면 AI가 하이라이트를 골라 템플릿을 입힌 9:16 숏폼으로 만들어 주는 서비스의 정적 사이트입니다. 빌드 없이 바로 열 수 있어요.

| 페이지 | 파일 | 내용 |
|---|---|---|
| 홈 | `index.html` | 파일 업로드 / 영상 링크 입력, 사용 방법, 기능, 활용 사례 |
| 템플릿 | `template.html`, `templates.js` | 템플릿 8종 갤러리, 카테고리 필터, 검색, 제목·자막을 바꿔 보는 크게 보기, 선택한 템플릿으로 바로 만들기 |
| 숏폼 만들기 | `editor.html`, `editor.js` | 촬영본 업로드, 구간 지정, AI 하이라이트 선별, 9:16 미리보기, 제목·자막 수정, 숏폼 내보내기 |
| 내 콘텐츠 | `contents.html`, `contents.js` | 만든 숏폼 목록, 재생, 다운로드, 공유, 삭제, 검색·정렬, 남은 무료 시간 |
| 요금제 | `pricing.html`, `pricing.js` | Free(가입 시 90분) · 라이트 · 스탠다드 · 프로, 분량 계산기, 비교표, FAQ, 결제 창(데모) |
| 로그인 | `login.html` | 로그인 / 회원가입 (백엔드 연결 시) |
| 결제 결과 | `payment-success.html`, `payment-fail.html` | 토스 결제 후 서버 승인 · 결과 안내 |
| 공통 | `style.css`, `app.js`, `store.js`, `stt.js`, `config.js` | 스타일, 로그인 상태·API 호출, 저장소, 브라우저 음성인식, 배포 설정 |

## 실행

```bash
cd ai-editor-site
python3 -m http.server 8000   # http://localhost:8000
```

GitHub Pages, Netlify, Vercel 같은 정적 호스팅에 폴더째 올려도 됩니다. 내보내기는 Chrome/Edge에서 가장 잘 동작합니다.

## 두 가지 모드

`config.js`의 `apiBase`가 비어 있으면 **브라우저 단독 모드**, 채우면 **서비스 모드**입니다.

| 기능 | 브라우저 단독 | 서비스 모드 (`clipora-api` 연결) |
|---|---|---|
| 하이라이트 선별 | ✅ Web Audio 분석 | ✅ 동일 |
| 자막 | ✅ 브라우저 Whisper 음성인식 | ✅ 동일 |
| 제목 | 자막에서 핵심 문장 고르기 | ✅ Claude가 자막을 읽고 작성 |
| 사용 시간 | 이 브라우저에만 기록 | ✅ 계정별 서버 관리 |
| 로그인 · 결제 | — | ✅ 이메일 가입, 토스페이먼츠 결제 → 플랜 30일 + 시간 지급 + 워터마크 제거 |
| 숏폼 내보내기 · 내 콘텐츠 | ✅ WebM, IndexedDB | ✅ 동일 |

**음성인식(stt.js)**: transformers.js로 `whisper-base` 모델을 브라우저에서 돌립니다. 처음 한 번 약 80MB를 내려받고 이후엔 캐시를 씁니다. 영상·음성은 서버로 가지 않습니다. 모델을 못 불러오면 빈 자막 칸을 만들어 직접 입력하게 합니다. 더 정확한 인식이 필요하면 `config.js`의 `whisperModel`을 `onnx-community/whisper-small`로 바꾸세요(다운로드가 더 큽니다).

**하이라이트 선별**: 0.1초 단위 음량으로 발화 구간을 찾고 "말이 이어지는 비율 60% + 목소리 에너지 40%"로 점수를 매긴 뒤 문장 경계에 맞춰 자릅니다.

**내보내기**: 템플릿을 입힌 720×1280 캔버스를 원본 소리와 함께 MediaRecorder로 녹화합니다(클립 길이만큼 실시간). Chrome·Edge 권장.

## 배포

`.github/workflows/pages.yml`이 `main` 브랜치에 푸시될 때 이 폴더를 GitHub Pages로 배포합니다.
1. 저장소 Settings → Pages → Source를 **GitHub Actions**로 설정 (한 번만)
2. (선택) Settings → Secrets and variables → Actions → **Variables**에 `CLIPORA_API_BASE`, `TOSS_CLIENT_KEY` 추가 → 배포 시 `config.js`가 자동 생성됩니다

## 수정 포인트
- 요금·플랜: `pricing.js`의 `PLANS` / `COMPARE`
- 템플릿 추가: `templates.js`의 `TEMPLATES`에 항목 하나 추가하면 갤러리·에디터·내보내기에 모두 반영됩니다.
- 무료 시간: `store.js`의 `FREE_MINUTES` (서버 모드는 `clipora-api/plans.py`)
- 요금은 프론트 `pricing.js`와 백엔드 `clipora-api/plans.py`를 함께 바꿔 주세요.
