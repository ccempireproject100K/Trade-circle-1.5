import pytest
from fastapi.testclient import TestClient

from app.ratelimit import RateLimiter
from app.security import hash_password, verify_password


def test_passwords_are_hashed_with_argon2(client, signup, db):
    signup(email="hash@example.com")
    user = client.portal.call(db.users.find_one, {"email": "hash@example.com"})
    assert user["password_hash"].startswith("$argon2id$")
    assert "correct horse battery" not in user["password_hash"]


def test_verify_password():
    stored = hash_password("s3cret-password")
    assert verify_password(stored, "s3cret-password")
    assert not verify_password(stored, "wrong")
    assert not verify_password(None, "s3cret-password")
    assert not verify_password("not-a-hash", "s3cret-password")


def test_login_and_me(client, signup):
    signup(email="me@example.com")
    res = client.post("/api/auth/login", json={"email": "ME@example.com", "password": "correct horse battery"})
    assert res.status_code == 200
    token = res.json()["token"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "me@example.com"
    assert me.json()["role"] == "contractor"
    assert me.json()["tier"] == "free"


def test_wrong_password_and_unknown_email_look_the_same(client, signup):
    signup(email="known@example.com")
    wrong = client.post("/api/auth/login", json={"email": "known@example.com", "password": "nope"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_duplicate_email_rejected(client, signup):
    signup(email="dup@example.com")
    res = client.post(
        "/api/auth/signup",
        json={"email": "dup@example.com", "password": "another password", "business_name": "X", "trade": "plumber", "city": "Waco"},
    )
    assert res.status_code == 409


def test_bad_or_missing_token_rejected(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_login_rate_limited_per_account(client, signup):
    signup(email="target@example.com")
    codes = [
        client.post("/api/auth/login", json={"email": "target@example.com", "password": f"guess{i}"}).status_code
        for i in range(6)
    ]
    # Signup used one of the five slots for this IP.
    assert codes[:4] == [401] * 4
    assert codes[4] == 429
    res = client.post("/api/auth/login", json={"email": "target@example.com", "password": "correct horse battery"})
    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) >= 1


def test_rate_limiter_window_expires():
    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0])
    limiter.check("k")
    limiter.check("k")
    with pytest.raises(Exception):
        limiter.check("k")
    now[0] = 10.5
    limiter.check("k")


def test_http_redirects_to_https(settings, db):
    from app.main import create_app

    app = create_app(settings, db=db)
    with TestClient(app, base_url="http://testserver") as c:
        res = c.get("/health", follow_redirects=False)
    assert res.status_code == 308
    assert res.headers["location"].startswith("https://")


def test_https_responses_carry_hsts(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert "max-age" in res.headers["Strict-Transport-Security"]


def test_admin_route_requires_admin_role(client, signup):
    headers, _ = signup()
    res = client.post("/api/admin/profiles/anything/insurance/verify", headers=headers)
    assert res.status_code == 403
