"""Clipora API — 회원, 사용 시간, AI 제목, 결제.

실행: uvicorn app:app --reload
"""

import hashlib
import hmac
import os
import re
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import db
import payments
import titles
from plans import FREE_SECONDS, PLAN_DAYS, PLANS

SESSION_DAYS = 30
TITLE_DAILY_LIMIT = int(os.environ.get("TITLE_DAILY_LIMIT", "100"))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

@asynccontextmanager
async def lifespan(_app):
    db.init()
    yield


app = FastAPI(title="Clipora API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:8000").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------- 인증 ----------

def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt_hex)).split("$")[2], digest_hex)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (token_hash(token), user_id, int(time.time()) + SESSION_DAYS * 86400),
    )
    return token


def current_user(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "로그인이 필요해요")
    with db.tx() as conn:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
            (token_hash(token), int(time.time())),
        ).fetchone()
    if not row:
        raise HTTPException(401, "로그인이 만료되었어요. 다시 로그인해 주세요")
    return dict(row)


def public_user(u: dict) -> dict:
    now = int(time.time())
    active = u["plan"] != "free" and (u["plan_expires_at"] or 0) > now
    return {
        "email": u["email"],
        "plan": u["plan"] if active else "free",
        "planName": PLANS[u["plan"]]["name"] if active else "Free",
        "planExpiresAt": u["plan_expires_at"] if active else None,
        "balanceSec": round(u["balance_sec"], 1),
        "watermark": not active,
    }


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)


@app.post("/api/auth/signup")
def signup(body: Credentials):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "이메일 형식을 확인해 주세요")
    with db.tx() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise HTTPException(409, "이미 가입된 이메일이에요")
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, balance_sec, created_at) VALUES (?, ?, ?, ?)",
            (email, hash_password(body.password), FREE_SECONDS, int(time.time())),
        )
        token = new_session(conn, cur.lastrowid)
        user = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"token": token, "user": public_user(dict(user))}


@app.post("/api/auth/login")
def login(body: Credentials):
    email = body.email.strip().lower()
    with db.tx() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not verify_password(body.password, user["password_hash"]):
            raise HTTPException(401, "이메일 또는 비밀번호가 맞지 않아요")
        token = new_session(conn, user["id"])
    return {"token": token, "user": public_user(dict(user))}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    if token:
        with db.tx() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return public_user(user)


# ---------- 사용 시간 ----------

class UsageIn(BaseModel):
    seconds: float = Field(gt=0, le=6 * 3600)


@app.post("/api/usage")
def use_time(body: UsageIn, user: dict = Depends(current_user)):
    with db.tx() as conn:
        row = conn.execute("SELECT balance_sec FROM users WHERE id = ?", (user["id"],)).fetchone()
        if row["balance_sec"] < body.seconds:
            raise HTTPException(402, "남은 시간이 부족해요. 구간을 줄이거나 플랜을 업그레이드해 주세요")
        conn.execute("UPDATE users SET balance_sec = balance_sec - ? WHERE id = ?", (body.seconds, user["id"]))
        conn.execute(
            "INSERT INTO usage_log (user_id, kind, amount, created_at) VALUES (?, 'analyze', ?, ?)",
            (user["id"], body.seconds, int(time.time())),
        )
        updated = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return public_user(dict(updated))


# ---------- AI 제목 ----------

class TitlesIn(BaseModel):
    transcripts: list[str] = Field(min_length=1, max_length=10)
    persona: str = Field(default="", max_length=500)


@app.post("/api/titles")
def make_titles(body: TitlesIn, user: dict = Depends(current_user)):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(503, "AI 제목 기능이 설정되지 않았어요 (ANTHROPIC_API_KEY)")
    since = int(time.time()) - 86400
    with db.tx() as conn:
        used = conn.execute(
            "SELECT COUNT(*) FROM usage_log WHERE user_id = ? AND kind = 'titles' AND created_at > ?",
            (user["id"], since),
        ).fetchone()[0]
        if used >= TITLE_DAILY_LIMIT:
            raise HTTPException(429, "오늘 AI 제목 생성 한도를 다 썼어요")
        conn.execute(
            "INSERT INTO usage_log (user_id, kind, amount, created_at) VALUES (?, 'titles', 1, ?)",
            (user["id"], int(time.time())),
        )
    transcripts = [t[:4000] for t in body.transcripts]
    try:
        return {"titles": titles.generate_titles(transcripts, body.persona)}
    except titles.TitleError as e:
        raise HTTPException(502, str(e)) from e


# ---------- 요금제 · 결제 ----------

@app.get("/api/plans")
def list_plans():
    return {"free": {"minutes": FREE_SECONDS // 60}, "plans": PLANS, "days": PLAN_DAYS}


class OrderIn(BaseModel):
    plan: str


@app.post("/api/payments/orders")
def create_order(body: OrderIn, user: dict = Depends(current_user)):
    plan = PLANS.get(body.plan)
    if not plan:
        raise HTTPException(400, "없는 요금제예요")
    order_id = "clp_" + secrets.token_urlsafe(16)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO orders (order_id, user_id, plan, amount, created_at) VALUES (?, ?, ?, ?, ?)",
            (order_id, user["id"], body.plan, plan["price"], int(time.time())),
        )
    return {
        "orderId": order_id,
        "amount": plan["price"],
        "orderName": f"Clipora {plan['name']} 플랜 ({PLAN_DAYS}일)",
        "customerEmail": user["email"],
        "customerKey": f"user_{user['id']}_{hashlib.sha256(user['email'].encode()).hexdigest()[:12]}",
    }


class ConfirmIn(BaseModel):
    paymentKey: str = Field(max_length=200)
    orderId: str = Field(max_length=64)
    amount: int


@app.post("/api/payments/confirm")
def confirm_payment(body: ConfirmIn, user: dict = Depends(current_user)):
    with db.tx() as conn:
        order = conn.execute(
            "SELECT * FROM orders WHERE order_id = ? AND user_id = ?", (body.orderId, user["id"])
        ).fetchone()
    if not order:
        raise HTTPException(404, "주문을 찾을 수 없어요")
    if order["status"] == "paid":  # 새로고침 등으로 다시 들어온 경우
        return {"status": "paid", "user": public_user(current_user_by_id(user["id"]))}
    # 금액은 반드시 서버에 저장된 주문 금액과 비교합니다 (클라이언트 값 위조 방지).
    if body.amount != order["amount"]:
        raise HTTPException(400, "결제 금액이 주문과 달라요")

    try:
        payments.confirm(body.paymentKey, body.orderId, body.amount)
    except payments.PaymentError as e:
        with db.tx() as conn:
            conn.execute("UPDATE orders SET status = 'failed' WHERE order_id = ? AND status = 'pending'", (body.orderId,))
        raise HTTPException(503 if e.code == "NOT_CONFIGURED" else 400, str(e)) from e

    plan = PLANS[order["plan"]]
    now = int(time.time())
    with db.tx() as conn:
        updated = conn.execute(
            "UPDATE orders SET status = 'paid', payment_key = ?, paid_at = ? WHERE order_id = ? AND status != 'paid'",
            (body.paymentKey, now, body.orderId),
        ).rowcount
        if updated:
            # 이미 유료 기간이 남아 있으면 그 뒤로 30일을 이어 붙입니다.
            u = conn.execute("SELECT plan_expires_at FROM users WHERE id = ?", (user["id"],)).fetchone()
            start = max(now, u["plan_expires_at"] or 0)
            conn.execute(
                "UPDATE users SET plan = ?, plan_expires_at = ?, balance_sec = balance_sec + ? WHERE id = ?",
                (order["plan"], start + PLAN_DAYS * 86400, plan["minutes"] * 60, user["id"]),
            )
    return {"status": "paid", "user": public_user(current_user_by_id(user["id"]))}


def current_user_by_id(user_id: int) -> dict:
    with db.tx() as conn:
        return dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


@app.get("/api/payments")
def payment_history(user: dict = Depends(current_user)):
    with db.tx() as conn:
        rows = conn.execute(
            "SELECT order_id, plan, amount, status, created_at, paid_at FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
            (user["id"],),
        ).fetchall()
    return {"orders": [dict(r) for r in rows]}


@app.get("/api/health")
def health():
    return {"ok": True, "titles": bool(os.environ.get("ANTHROPIC_API_KEY")), "payments": bool(payments.secret_key())}
