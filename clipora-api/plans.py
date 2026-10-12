"""요금제. 프론트엔드 ai-editor-site/pricing.js의 PLANS와 값을 맞춰 두세요."""

FREE_SECONDS = 90 * 60
PLAN_DAYS = 30

PLANS = {
    "lite": {"name": "라이트", "price": 9900, "minutes": 150},
    "standard": {"name": "스탠다드", "price": 19900, "minutes": 300},
    "pro": {"name": "프로", "price": 39900, "minutes": 600},
}
