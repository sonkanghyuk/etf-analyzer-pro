# Clipora — AI 숏폼 자동 제작 사이트 (데모)

강의·강연·인터뷰 촬영본을 올리면 AI가 하이라이트를 골라 템플릿을 입힌 9:16 숏폼으로 만들어 주는 서비스의 정적 사이트입니다. 빌드 없이 바로 열 수 있어요.

| 페이지 | 파일 | 내용 |
|---|---|---|
| 홈 | `index.html` | 파일 업로드 / 영상 링크 입력, 사용 방법, 기능, 활용 사례 |
| 템플릿 | `template.html`, `templates.js` | 템플릿 8종 갤러리, 카테고리 필터, 검색, 제목·자막을 바꿔 보는 크게 보기, 선택한 템플릿으로 바로 만들기 |
| 숏폼 만들기 | `editor.html`, `editor.js` | 촬영본 업로드, 구간 지정, AI 하이라이트 선별, 9:16 미리보기, 제목·자막 수정, 숏폼 내보내기 |
| 내 콘텐츠 | `contents.html`, `contents.js` | 만든 숏폼 목록, 재생, 다운로드, 공유, 삭제, 검색·정렬, 남은 무료 시간 |
| 요금제 | `pricing.html`, `pricing.js` | Free(가입 시 90분) · 라이트 · 스탠다드 · 프로, 분량 계산기, 비교표, FAQ, 결제 창(데모) |
| 공통 | `style.css`, `app.js`, `store.js` | 스타일, 모바일 메뉴·토스트, 저장소(IndexedDB/localStorage) |

## 실행

```bash
cd ai-editor-site
python3 -m http.server 8000   # http://localhost:8000
```

GitHub Pages, Netlify, Vercel 같은 정적 호스팅에 폴더째 올려도 됩니다. 내보내기는 Chrome/Edge에서 가장 잘 동작합니다.

## 실제 동작 vs 데모

**실제로 동작**
- 하이라이트 선별: Web Audio로 0.1초 단위 음량을 분석해 발화 구간을 찾고, "말이 이어지는 비율 60% + 목소리 에너지 40%"로 구간 점수를 매겨 상위 구간을 고릅니다. 문장 중간에서 끊기지 않도록 발화 경계에 맞춥니다.
- 숏폼 내보내기: 템플릿(배경·제목·자막·워터마크)을 입힌 720×1280 캔버스를 원본 소리와 함께 MediaRecorder로 녹화해 실제 WebM 파일을 만듭니다(클립 길이만큼 실시간 렌더링).
- 내 콘텐츠: 만든 영상은 이 브라우저의 IndexedDB에 저장됩니다. 서버로 업로드되지 않습니다.

**데모 (서버 필요)**
- 자막 *문장*과 숏폼 *제목*은 예시 문장입니다. `editor.js`의 `transcribe()`는 STT(Whisper 등), `suggestTitle()`은 LLM API 호출로 바꾸면 됩니다.
- 영상 링크 가져오기, 로그인, 결제, SNS 자동 업로드, 커스텀 페르소나.

## 수정 포인트
- 요금·플랜: `pricing.js`의 `PLANS` / `COMPARE`
- 템플릿 추가: `templates.js`의 `TEMPLATES`에 항목 하나 추가하면 갤러리·에디터·내보내기에 모두 반영됩니다.
- 무료 시간: `store.js`의 `FREE_MINUTES`
