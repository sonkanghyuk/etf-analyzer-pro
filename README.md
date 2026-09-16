# ETF Analyzer Pro

티커를 입력하면 ETF의 **성과·위험·분배금·보수·구성종목·섹터·중복도·상관관계**를 한 번에 비교하는 Streamlit 앱입니다.

## 핵심 기능

- 티커 자동 가격 수집
- 누적수익률 / CAGR
- 연환산 변동성
- MDD(Max Drawdown)
- Sharpe Ratio
- 최근 12개월 분배금 및 단순 분배율
- 총보수(best-effort, Yahoo fund data에서 제공되는 경우)
- 정규화 누적 성과 차트
- Drawdown 차트
- 연도별 / 월별 수익률
- 일간 수익률 상관계수
- ETF Top Holdings 자동 수집(지원되는 ETF)
- 구성종목 집중도 / HHI
- ETF 간 가중 구성종목 중복도
- 섹터 비중
- 운용사 구성종목 CSV 업로드로 자동 데이터 보완
- 결과 CSV 다운로드

## Streamlit Cloud 배포

- Repository: `sonkanghyuk/etf-analyzer-pro`
- Main file: `app.py`
- Python dependencies: `requirements.txt`

## 직접 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 티커 예시

미국 ETF:
- QQQ
- SCHD
- SPY
- SOXX
- GLD

한국 상장 ETF는 Yahoo Finance에서 지원되는 경우 종목코드 뒤에 `.KS`를 붙이는 방식이 일반적입니다. 예: `360750.KS`

## 구성종목 CSV 형식

최소 필수 열:
- ETF 또는 ticker
- 구성종목 또는 holding
- 비중 또는 weight

선택 열:
- sector / 섹터
- country / 국가

자동 구성종목 데이터가 없거나 전체 구성종목 기준 중복도를 원한다면 운용사 CSV를 사용하세요.

## 중요한 데이터 제한

`yfinance`의 Fund Data가 제공하는 구성종목은 ETF에 따라 **Top Holdings** 수준일 수 있습니다. 따라서 자동 수집 상태의 중복도는 전체 포트폴리오 중복도가 아니라 확보된 구성종목 기준일 수 있습니다.

정밀 비교가 필요하면 각 운용사의 전체 구성종목 CSV를 업로드하세요.
