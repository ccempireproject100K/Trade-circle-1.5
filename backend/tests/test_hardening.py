import mongomock

from app import cli
from app.routers import auth as auth_router

QUOTE = {"name": "Dana Homeowner", "phone": "+15125550199", "message": "Need a panel upgrade"}
PASSWORD = "correct horse battery"


def _slug(client, headers):
    return client.get("/api/me/profile", headers=headers).json()["slug"]


def test_honeypot_quotes_queue_no_alert(client, signup, db):
    headers, user = signup()
    # Paid plan, so a real quote would queue an alert.
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": "starter"}})
    client.post(f"/api/p/{_slug(client, headers)}/quote", json={**QUOTE, "website": "x"})
    assert client.portal.call(lambda: db.outbox.count_documents({})) == 0


def test_optional_profile_fields_can_be_cleared(client, signup):
    headers, _ = signup()
    client.put("/api/me/profile", headers=headers, json={"phone": "+15125550100", "tagline": "Fast"})
    res = client.put("/api/me/profile", headers=headers, json={"phone": None})
    assert res.status_code == 200
    assert "phone" not in res.json() and res.json()["tagline"] == "Fast"
    assert client.get(f"/api/p/{_slug(client, headers)}").json()["call"] == {}


def test_required_profile_fields_cannot_be_cleared(client, signup):
    headers, _ = signup()
    res = client.put("/api/me/profile", headers=headers, json={"business_name": None})
    assert res.status_code == 422
    assert "business_name" in res.text


def test_job_fields_can_be_cleared(client, signup):
    headers, _ = signup()
    job_id = client.post("/api/jobs", headers=headers, json={"title": "Deck", "scheduled_on": "2026-11-02"}).json()["id"]
    res = client.patch(f"/api/jobs/{job_id}", headers=headers, json={"scheduled_on": None})
    assert res.status_code == 200 and "scheduled_on" not in res.json()
    assert client.patch(f"/api/jobs/{job_id}", headers=headers, json={"title": None}).status_code == 422


def test_unpublished_profile_is_hidden_and_takes_no_quotes(client, signup):
    headers, _ = signup()
    slug = _slug(client, headers)
    client.put("/api/me/profile", headers=headers, json={"published": False})
    assert client.get(f"/api/p/{slug}").status_code == 404
    assert client.get(f"/api/p/{slug}/full").status_code == 404
    assert client.post(f"/api/p/{slug}/quote", json=QUOTE).status_code == 404
    client.put("/api/me/profile", headers=headers, json={"published": True})
    assert client.get(f"/api/p/{slug}").status_code == 200


def test_disabled_account_profile_is_hidden(client, signup, db):
    headers, user = signup()
    slug = _slug(client, headers)
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"disabled": True}})
    assert client.get(f"/api/p/{slug}").status_code == 404


def test_logout_everywhere_revokes_existing_tokens(client, signup):
    headers, _ = signup(email="multi@example.com")
    other_device = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"email": "multi@example.com", "password": PASSWORD}
    ).json()["token"]}
    assert client.post("/api/auth/logout-everywhere", headers=headers).status_code == 204
    assert client.get("/api/me", headers=headers).status_code == 401
    assert client.get("/api/me", headers=other_device).status_code == 401


def test_password_change_signs_out_other_devices(client, signup):
    headers, _ = signup(email="pw@example.com")
    res = client.post("/api/auth/password", headers=headers, json={"current_password": "wrong", "new_password": "a brand new password"})
    assert res.status_code == 401
    res = client.post("/api/auth/password", headers=headers, json={"current_password": PASSWORD, "new_password": "a brand new password"})
    assert res.status_code == 200
    assert client.get("/api/me", headers=headers).status_code == 401
    fresh = {"Authorization": f"Bearer {res.json()['token']}"}
    assert client.get("/api/me", headers=fresh).status_code == 200
    login = client.post("/api/auth/login", json={"email": "pw@example.com", "password": "a brand new password"})
    assert login.status_code == 200


def test_quote_flood_from_many_addresses_is_capped_per_contractor(client, signup):
    headers, _ = signup()
    slug = _slug(client, headers)
    limiters = client.app.state.limiters
    # Simulate many senders: lift the per-address limit, keep the per-contractor one.
    limiters["quote"].limit = 10_000
    limiters["quote_profile"].limit = 3
    codes = [client.post(f"/api/p/{slug}/quote", json=QUOTE).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]


def test_signup_retries_on_slug_collision(client, db, monkeypatch):
    calls = {"n": 0}
    real_unique_slug = auth_router.unique_slug

    async def colliding(db_, name):
        calls["n"] += 1
        # First attempt returns a slug that is already taken, as if another signup won the race.
        return "taken" if calls["n"] == 1 else await real_unique_slug(db_, name)

    client.portal.call(db.profiles.insert_one, {"_id": "x", "owner_id": "someone", "slug": "taken"})
    monkeypatch.setattr(auth_router, "unique_slug", colliding)
    res = client.post("/api/auth/signup", json={"email": "race@example.com", "password": PASSWORD, "business_name": "Race Co", "trade": "mason", "city": "Waco"})
    assert res.status_code == 201
    assert calls["n"] == 2


def test_signup_removes_account_if_profile_cannot_be_created(client, db, monkeypatch):
    async def always_taken(db_, name):
        return "taken"

    client.portal.call(db.profiles.insert_one, {"_id": "x", "owner_id": "someone", "slug": "taken"})
    monkeypatch.setattr(auth_router, "unique_slug", always_taken)
    try:
        client.post("/api/auth/signup", json={"email": "orphan@example.com", "password": PASSWORD, "business_name": "Orphan", "trade": "mason", "city": "Waco"})
    except RuntimeError:
        pass
    assert client.portal.call(db.users.find_one, {"email": "orphan@example.com"}) is None


def test_cli_make_admin_and_disable():
    db = mongomock.MongoClient()["cli_test"]
    db.users.insert_one({"_id": "u1", "email": "boss@example.com", "role": "contractor", "token_version": 0})
    assert cli.run(db, "make-admin", "BOSS@example.com") == (True, "make-admin: done for BOSS@example.com")
    assert db.users.find_one({"_id": "u1"})["role"] == "admin"
    cli.run(db, "disable", "boss@example.com")
    user = db.users.find_one({"_id": "u1"})
    assert user["disabled"] is True and user["token_version"] == 1
    assert cli.run(db, "make-admin", "nobody@example.com")[0] is False
    assert [e["action"] for e in db.audit_log.find({})] == ["CLI make-admin", "CLI disable"]
