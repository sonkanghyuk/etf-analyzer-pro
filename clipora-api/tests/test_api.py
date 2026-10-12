import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    for mod in ("db", "app", "payments", "titles", "plans"):
        sys.modules.pop(mod, None)
    import app as app_module
    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as c:
        c.app_module = app_module
        yield c


def signup(client, email="a@test.com", password="password123"):
    r = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_signup_gives_free_minutes_and_login_works(client):
    h = signup(client)
    me = client.get("/api/me", headers=h).json()
    assert me["plan"] == "free" and me["balanceSec"] == 90 * 60 and me["watermark"] is True

    assert client.post("/api/auth/signup", json={"email": "A@test.com", "password": "password123"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "a@test.com", "password": "wrongpass1"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@test.com", "password": "password123"}).status_code == 200


def test_requires_auth_and_logout_revokes(client):
    assert client.get("/api/me").status_code == 401
    h = signup(client)
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/me", headers=h).status_code == 401


def test_usage_is_deducted_and_limited(client):
    h = signup(client)
    r = client.post("/api/usage", json={"seconds": 600}, headers=h)
    assert r.status_code == 200 and r.json()["balanceSec"] == 80 * 60
    assert client.post("/api/usage", json={"seconds": 81 * 60}, headers=h).status_code == 402


def test_payment_flow_upgrades_plan(client, monkeypatch):
    h = signup(client)
    order = client.post("/api/payments/orders", json={"plan": "standard"}, headers=h).json()
    assert order["amount"] == 19900

    calls = []
    monkeypatch.setattr(client.app_module.payments, "confirm", lambda *a: calls.append(a) or {"status": "DONE"})

    # 금액 위조는 거절
    bad = client.post("/api/payments/confirm", json={"paymentKey": "pk", "orderId": order["orderId"], "amount": 100}, headers=h)
    assert bad.status_code == 400 and not calls

    ok = client.post("/api/payments/confirm", json={"paymentKey": "pk", "orderId": order["orderId"], "amount": 19900}, headers=h)
    assert ok.status_code == 200, ok.text
    user = ok.json()["user"]
    assert user["plan"] == "standard" and user["watermark"] is False
    assert user["balanceSec"] == 90 * 60 + 300 * 60

    # 같은 주문을 다시 승인해도 시간이 두 번 붙지 않음
    again = client.post("/api/payments/confirm", json={"paymentKey": "pk", "orderId": order["orderId"], "amount": 19900}, headers=h)
    assert again.json()["user"]["balanceSec"] == 90 * 60 + 300 * 60 and len(calls) == 1


def test_other_users_order_is_not_found(client, monkeypatch):
    h1 = signup(client, "a@test.com")
    h2 = signup(client, "b@test.com")
    order = client.post("/api/payments/orders", json={"plan": "lite"}, headers=h1).json()
    monkeypatch.setattr(client.app_module.payments, "confirm", lambda *a: {})
    r = client.post("/api/payments/confirm", json={"paymentKey": "pk", "orderId": order["orderId"], "amount": 9900}, headers=h2)
    assert r.status_code == 404


def test_payment_not_configured(client, monkeypatch):
    monkeypatch.delenv("TOSS_SECRET_KEY", raising=False)
    h = signup(client)
    order = client.post("/api/payments/orders", json={"plan": "lite"}, headers=h).json()
    r = client.post("/api/payments/confirm", json={"paymentKey": "pk", "orderId": order["orderId"], "amount": 9900}, headers=h)
    assert r.status_code == 503


def test_titles_calls_claude_with_structured_output(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    h = signup(client)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps({"titles": ["공부는 꾸준함이 전부", "질문 1위의 답"]}))],
        )

    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=fake_create)))
    monkeypatch.setattr(client.app_module.titles, "client", lambda: fake)

    r = client.post("/api/titles", json={"transcripts": ["결국 중요한 건 꾸준함", "가장 많이 받은 질문", "세 번째"]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["titles"] == ["공부는 꾸준함이 전부", "질문 1위의 답", ""]
    assert captured["model"] == "claude-opus-5-5"
    assert captured["fallbacks"] == "default"
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert "꾸준함" in captured["messages"][0]["content"]


def test_titles_refusal_and_missing_key(client, monkeypatch):
    h = signup(client)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.post("/api/titles", json={"transcripts": ["x"]}, headers=h).status_code == 503

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        create=lambda **k: SimpleNamespace(stop_reason="refusal", content=[]))))
    monkeypatch.setattr(client.app_module.titles, "client", lambda: fake)
    assert client.post("/api/titles", json={"transcripts": ["x"]}, headers=h).status_code == 502
