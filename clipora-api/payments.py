"""토스페이먼츠 결제 승인. https://docs.tosspayments.com/reference#결제-승인"""

import base64
import os

import httpx

CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"


class PaymentError(Exception):
    def __init__(self, message: str, code: str = "PAYMENT_FAILED"):
        super().__init__(message)
        self.code = code


def secret_key() -> str:
    return os.environ.get("TOSS_SECRET_KEY", "")


def confirm(payment_key: str, order_id: str, amount: int) -> dict:
    key = secret_key()
    if not key:
        raise PaymentError("결제 설정이 되어 있지 않아요 (TOSS_SECRET_KEY)", "NOT_CONFIGURED")
    auth = base64.b64encode(f"{key}:".encode()).decode()
    try:
        res = httpx.post(
            CONFIRM_URL,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
            timeout=30,
        )
    except httpx.HTTPError as e:
        raise PaymentError("결제사에 연결하지 못했어요", "NETWORK") from e
    data = res.json() if res.content else {}
    if res.status_code != 200:
        raise PaymentError(data.get("message", "결제 승인에 실패했어요"), data.get("code", "PAYMENT_FAILED"))
    return data
