# Clipora API (백엔드)

회원가입·로그인, 사용 시간(분) 차감, Claude로 숏폼 제목 생성, 토스페이먼츠 결제 승인을 담당하는 FastAPI 서버입니다. 프론트엔드(`ai-editor-site/`)는 GitHub Pages 같은 정적 호스팅에, 이 서버는 Render·Fly.io·Railway 같은 곳에 따로 올립니다.

## 로컬 실행

```bash
cd clipora-api
pip install -r requirements.txt
cp .env.example .env   # 값 채우기
export $(grep -v '^#' .env | xargs)
uvicorn app:app --reload --port 8080
```

프론트엔드 `ai-editor-site/config.js`의 `apiBase`를 `http://localhost:8080`으로 바꾸면 연결됩니다.

## 환경 변수

| 이름 | 설명 |
|---|---|
| `ALLOWED_ORIGINS` | 프론트엔드 주소(CORS). 예: `https://sonkanghyuk.github.io` |
| `ANTHROPIC_API_KEY` | AI 제목 생성용. 없으면 프론트가 자막에서 제목을 고릅니다 |
| `CLAUDE_MODEL` | 기본 `claude-opus-5-5` |
| `TOSS_SECRET_KEY` | 토스페이먼츠 시크릿 키. 개발자센터 가입 즉시 받는 `test_sk_...`로 실제 돈 없이 테스트 |
| `DATABASE_PATH` | SQLite 파일 경로(영구 디스크) |
| `TITLE_DAILY_LIMIT` | 사용자당 하루 AI 제목 요청 수 (기본 100) |

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/auth/signup`, `/api/auth/login` | `{email, password}` → `{token, user}` (가입 시 90분 지급) |
| POST | `/api/auth/logout` | 토큰 폐기 |
| GET | `/api/me` | 플랜, 남은 시간, 워터마크 여부 |
| POST | `/api/usage` | `{seconds}` 차감, 부족하면 402 |
| POST | `/api/titles` | `{transcripts: [...], persona?}` → `{titles: [...]}` |
| POST | `/api/payments/orders` | `{plan}` → 토스 결제창에 넘길 주문 |
| POST | `/api/payments/confirm` | `{paymentKey, orderId, amount}` 승인 → 플랜 30일 + 시간 지급 |
| GET | `/api/payments` | 결제 내역 |

결제 금액은 서버에 저장한 주문 금액과 비교한 뒤에만 토스에 승인 요청을 보내고, 같은 주문을 두 번 승인해도 시간이 중복 지급되지 않습니다. 인증은 `Authorization: Bearer <token>` 헤더이고, 비밀번호는 scrypt로 해시합니다.

## 배포 (Render 예시)

저장소 루트의 `render.yaml`로 Render 대시보드에서 **New → Blueprint**를 선택하면 `clipora-api/`가 Docker로 배포되고 1GB 디스크가 붙습니다. `ANTHROPIC_API_KEY`, `TOSS_SECRET_KEY`는 대시보드에서 입력하세요.

## 테스트

```bash
pip install pytest
pytest tests
```
