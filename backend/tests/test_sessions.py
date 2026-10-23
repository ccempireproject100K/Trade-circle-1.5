from fastapi.testclient import TestClient

from app.main import create_app
from app.security import SESSION_COOKIE

PASSWORD = "correct horse battery"
CSRF = {"X-TC-CSRF": "1"}


def _signup(client, email="cookie@example.com"):
    return client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "business_name": "Cookie Co", "trade": "painter", "city": "Waco"},
    )


def test_signup_sets_secure_httponly_cookie(client):
    res = _signup(client)
    cookie = res.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag in cookie


def test_cookie_session_reads_without_header(client):
    _signup(client)
    assert client.get("/api/me").json()["email"] == "cookie@example.com"


def test_cookie_writes_need_csrf_header(client):
    _signup(client)
    assert client.post("/api/jobs", json={"title": "No header"}).status_code == 403
    assert client.post("/api/jobs", json={"title": "With header"}, headers=CSRF).status_code == 201


def test_bearer_writes_need_no_csrf_header(client):
    token = _signup(client).json()["token"]
    client.cookies.clear()
    res = client.post("/api/jobs", json={"title": "API"}, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 201


def test_logout_clears_cookie(client):
    _signup(client)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_logout_everywhere_clears_cookie_and_revokes(client):
    token = _signup(client).json()["token"]
    assert client.post("/api/auth/logout-everywhere", headers=CSRF).status_code == 204
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_cookie_not_secure_in_local_dev(settings, db):
    from dataclasses import replace

    app = create_app(replace(settings, enforce_https=False), db=db)
    with TestClient(app) as c:
        assert "Secure" not in _signup(c).headers["set-cookie"]


def test_dashboard_routes_serve_app_shell(settings, db, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    app = create_app(settings, db=db, dashboard_dist=tmp_path)
    with TestClient(app, base_url="https://testserver") as c:
        for path in ("/app", "/app/inbox", "/app/jobs/123"):
            res = c.get(path)
            assert res.status_code == 200 and "root" in res.text
            assert "script-src 'self'" in res.headers["content-security-policy"]
        asset = c.get("/app/assets/app-abc123.js")
        assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
        # Path tricks fall back to the app shell instead of reading other files.
        assert "root" in c.get("/app/..%2F..%2Fapp%2Fmain.py").text


def test_dashboard_missing_build_is_explained(settings, db, tmp_path):
    app = create_app(settings, db=db, dashboard_dist=tmp_path / "missing")
    with TestClient(app, base_url="https://testserver") as c:
        assert c.get("/app").status_code == 503
