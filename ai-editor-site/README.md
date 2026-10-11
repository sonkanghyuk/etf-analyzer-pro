# Clipora — AI 영상 편집 사이트 (데모)

빌드 없이 바로 열 수 있는 정적 사이트입니다.

| 파일 | 내용 |
|---|---|
| `index.html` | 랜딩 페이지 (기능 소개, 사용 방법, CTA) |
| `pricing.html` / `pricing.js` | 요금제: 월간/연간 토글(30% 할인), 4개 플랜, 플랜 추천 계산기, 기능 비교표, FAQ, 결제 모달(데모) |
| `editor.html` / `editor.js` | 에디터 데모: 영상 업로드, AI 자막, AI 컷편집, 9:16 숏폼 보기, 자막 스타일, SRT 내보내기 |
| `style.css`, `app.js` | 공통 스타일, 모바일 메뉴와 토스트 |

## 실행

```bash
cd ai-editor-site
python3 -m http.server 8000   # http://localhost:8000
```

GitHub Pages, Netlify, Vercel 같은 정적 호스팅에 이 폴더를 그대로 올려도 됩니다.

## 실제 동작 vs 데모

- **실제로 동작:** 무음/발화 구간 감지(Web Audio RMS 분석), 무음 구간 건너뛰며 재생, 자막 편집·추가·삭제, SRT 파일 내보내기. 영상은 브라우저 밖으로 업로드되지 않습니다.
- **데모:** 자막 *텍스트*는 예시 문장입니다. `editor.js`의 `transcribe()`를 STT API(Whisper 등) 호출로 바꾸면 됩니다. 결제, 로그인, 영상 렌더링은 백엔드가 필요합니다.
- 요금, 플랜 한도, 비교표는 `pricing.js` 맨 위의 `PLANS` / `COMPARE`만 고치면 모든 곳에 반영됩니다.
