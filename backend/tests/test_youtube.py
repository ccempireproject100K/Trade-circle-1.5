"""YouTube auto-posting against a fake Google: connect, confirm, queue, post.

The member's refresh token is the sensitive thing here: it must be encrypted in
the database and never appear in any API response.
"""
import asyncio
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import secrets, youtube
from app.deps import now
from app.main import create_app
from conftest import TODAY
from fakeyoutube import CHANNEL, REFRESH_TOKEN, YOUTUBE_SETTINGS, FakeYouTube


@pytest.fixture
def fake():
    return FakeYouTube()


@pytest.fixture
def yt_settings(settings):
    return replace(settings, **YOUTUBE_SETTINGS)


@pytest.fixture
def yt_client(yt_settings, db, fake):
    app = create_app(yt_settings, db=db, today=lambda: TODAY)
    app.state.youtube_transport = fake.transport()
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def run(coro_fn):
    return asyncio.run(coro_fn())


def _member(c, email="sparky@example.com", tier=None, db=None):
    res = c.post("/api/auth/signup", json={"email": email, "password": "correct horse battery", "business_name": "Bright Spark Electric", "trade": "electrician", "city": "Austin"})
    assert res.status_code == 201, res.text
    user = res.json()["user"]
    if tier:
        c.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": tier}})
    return {"Authorization": f"Bearer {res.json()['token']}"}, user


def _clip(c, db, settings, user_id, clip_id="clip1"):
    key = f"videos/{user_id}/{clip_id}.mp4"
    path = Path(settings.media_dir) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake mp4 bytes")
    doc = {"_id": clip_id, "owner_id": user_id, "type": "video", "video_url": f"/media/{key}", "thumb_url": "/media/poster.jpg",
           "image_url": "/media/poster.jpg", "duration": 12.0, "has_audio": True,
           "media_keys": [key, f"videos/{user_id}/{clip_id}-poster.jpg"], "created_at": now()}
    c.portal.call(db.uploads.insert_one, doc)
    return doc


def _connect(c, h):
    url = c.get("/api/youtube/connect", headers=h).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    res = c.get("/api/youtube/callback", params={"code": "auth-code", "state": state}, headers=h, follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"] == "/app/settings?youtube=connected", res.text
    return state


def _user(c, db, user_id):
    return c.portal.call(lambda: db.users.find_one({"_id": user_id}))


def _upload(c, db, clip_id):
    return c.portal.call(lambda: db.uploads.find_one({"_id": clip_id}))


def test_off_until_the_site_is_configured(client, signup, db, settings):
    h, user = signup()
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": "starter"}})
    body = client.get("/api/youtube/status", headers=h).json()
    assert body["configured"] is False and body["connected"] is False
    assert client.get("/api/youtube/connect", headers=h).status_code == 503
    _clip(client, db, settings, user["id"])
    res = client.post("/api/youtube/posts", headers=h, json={"clip_id": "clip1", "title": "Panel swap", "visibility": "unlisted"})
    assert res.status_code == 503


def test_free_plan_cannot_connect_or_post(yt_client, db, yt_settings):
    h, user = _member(yt_client)  # free plan
    assert yt_client.get("/api/youtube/connect", headers=h).status_code == 402
    _clip(yt_client, db, yt_settings, user["id"])
    res = yt_client.post("/api/youtube/posts", headers=h, json={"clip_id": "clip1", "title": "Panel swap"})
    assert res.status_code == 402
    body = yt_client.get("/api/youtube/status", headers=h).json()
    assert body["configured"] is True and body["plan_includes"] is False


def test_connect_stores_an_encrypted_token_and_never_shows_it(yt_client, db, yt_settings):
    h, user = _member(yt_client, tier="starter", db=db)
    url = yt_client.get("/api/youtube/connect", headers=h).json()["url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    query = parse_qs(urlparse(url).query)
    assert "youtube.upload" in query["scope"][0] and "youtube.readonly" in query["scope"][0]
    assert query["access_type"] == ["offline"]

    state = _connect(yt_client, h)
    stored = _user(yt_client, db, user["id"])["youtube"]
    assert stored["channel_id"] == CHANNEL["id"] and stored["channel_title"] == CHANNEL["title"]
    assert stored["refresh_token"] != REFRESH_TOKEN  # encrypted at rest, not the plain token
    assert secrets.decrypt(yt_settings, stored["refresh_token"]) == REFRESH_TOKEN

    body = yt_client.get("/api/youtube/status", headers=h).json()
    assert body["connected"] is True and body["channel"] == CHANNEL
    # Neither the plain token nor its stored ciphertext appears in any response.
    for res in (yt_client.get("/api/youtube/status", headers=h), yt_client.get("/api/youtube/posts", headers=h)):
        assert REFRESH_TOKEN not in res.text and stored["refresh_token"] not in res.text
    assert state  # the state token was required, not decoration


def test_callback_with_a_foreign_state_stores_nothing(yt_client, db):
    h, user = _member(yt_client, tier="starter", db=db)
    other, _ = _member(yt_client, email="other@example.com", tier="starter", db=db)
    foreign = parse_qs(urlparse(yt_client.get("/api/youtube/connect", headers=other).json()["url"]).query)["state"][0]
    res = yt_client.get("/api/youtube/callback", params={"code": "auth-code", "state": foreign}, headers=h, follow_redirects=False)
    assert res.headers["location"] == "/app/settings?youtube=error"
    assert "youtube" not in (_user(yt_client, db, user["id"]) or {})


def test_disconnect_revokes_and_forgets(yt_client, db, fake):
    h, user = _member(yt_client, tier="full", db=db)
    _connect(yt_client, h)
    assert yt_client.delete("/api/youtube/connect", headers=h).status_code == 204
    assert fake.revoked == [REFRESH_TOKEN]
    assert "youtube" not in (_user(yt_client, db, user["id"]) or {})
    assert yt_client.get("/api/youtube/status", headers=h).json()["connected"] is False


def _queue_and_run(yt_client, db, yt_settings, fake, h, user, clip_id="clip1", title="Panel swap, start to finish"):
    res = yt_client.post("/api/youtube/posts", headers=h, json={"clip_id": clip_id, "title": title, "description": "A tidy panel swap.", "visibility": "unlisted"})
    assert res.status_code == 201, res.text
    posted = run(lambda: youtube.deliver_due(db, yt_settings, fake.transport()))
    return res, posted


def test_confirmed_post_uploads_and_records_the_video(yt_client, db, yt_settings, fake):
    h, user = _member(yt_client, tier="starter", db=db)
    _connect(yt_client, h)
    _clip(yt_client, db, yt_settings, user["id"])
    res, posted = _queue_and_run(yt_client, db, yt_settings, fake, h, user)
    assert res.json()["status"] == "queued" and posted == 1

    clip = _upload(yt_client, db, "clip1")
    assert clip["youtube"]["status"] == "posted"
    assert clip["youtube"]["url"] == f"https://www.youtube.com/watch?v={clip['youtube']['video_id']}"
    assert fake.uploads[0]["metadata"]["snippet"] == {"title": "Panel swap, start to finish", "description": "A tidy panel swap."}
    assert fake.uploads[0]["metadata"]["status"]["privacyStatus"] == "unlisted"
    assert fake.uploads[0]["bytes"] == len(b"fake mp4 bytes")
    listed = yt_client.get("/api/youtube/posts", headers=h).json()
    assert listed[0]["status"] == "posted" and listed[0]["url"] == clip["youtube"]["url"]
    # A second post of the same clip is refused.
    assert yt_client.post("/api/youtube/posts", headers=h, json={"clip_id": "clip1", "title": "Again"}).status_code == 409


def test_posting_requires_a_connection_and_an_owned_clip(yt_client, db, yt_settings):
    h, user = _member(yt_client, tier="starter", db=db)
    _clip(yt_client, db, yt_settings, user["id"])
    assert yt_client.post("/api/youtube/posts", headers=h, json={"clip_id": "clip1", "title": "Panel swap"}).status_code == 409  # not connected yet
    _connect(yt_client, h)
    other, other_user = _member(yt_client, email="rival@example.com", tier="starter", db=db)
    _clip(yt_client, db, yt_settings, other_user["id"], "clip2")
    assert yt_client.post("/api/youtube/posts", headers=h, json={"clip_id": "clip2", "title": "Not mine"}).status_code == 404
    assert yt_client.post("/api/youtube/posts", headers=h, json={"clip_id": "nope", "title": "Ghost"}).status_code == 404


def test_failed_upload_retries_with_backoff_then_posts(yt_client, db, yt_settings, fake):
    h, user = _member(yt_client, tier="starter", db=db)
    _connect(yt_client, h)
    _clip(yt_client, db, yt_settings, user["id"])
    yt_client.post("/api/youtube/posts", headers=h, json={"clip_id": "clip1", "title": "Panel swap"})
    fake.fail_uploads = 1
    assert run(lambda: youtube.deliver_due(db, yt_settings, fake.transport())) == 0
    job = yt_client.portal.call(lambda: db.youtube_jobs.find_one({"clip_id": "clip1"}))
    assert job["status"] == "queued" and job["attempts"] == 1 and "backend exploded" in job["last_error"]
    assert _upload(yt_client, db, "clip1")["youtube"]["status"] == "queued"  # the clip itself is untouched and safe
    yt_client.portal.call(db.youtube_jobs.update_one, {"_id": job["_id"]}, {"$set": {"next_attempt_at": now()}})
    assert run(lambda: youtube.deliver_due(db, yt_settings, fake.transport())) == 1
    assert _upload(yt_client, db, "clip1")["youtube"]["status"] == "posted"


def test_revoked_token_fails_the_job_and_asks_for_a_reconnect(yt_client, db, yt_settings, fake):
    h, user = _member(yt_client, tier="starter", db=db)
    _connect(yt_client, h)
    _clip(yt_client, db, yt_settings, user["id"])
    yt_client.post("/api/youtube/posts", headers=h, json={"clip_id": "clip1", "title": "Panel swap"})
    # The stored token no longer matches anything Google will refresh (revoked at Google).
    yt_client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"youtube.refresh_token": secrets.encrypt(yt_settings, "someone-elses-token")}})
    assert run(lambda: youtube.deliver_due(db, yt_settings, fake.transport())) == 0
    job = yt_client.portal.call(lambda: db.youtube_jobs.find_one({"clip_id": "clip1"}))
    assert job["status"] == "failed"
    clip = _upload(yt_client, db, "clip1")
    assert clip["youtube"]["status"] == "failed" and "Reconnect" in clip["youtube"]["error"]
    assert _user(yt_client, db, user["id"])["youtube"]["needs_reconnect"] is True


def test_daily_cap_holds_extra_posts_for_tomorrow(db, settings, fake):
    capped = replace(settings, **YOUTUBE_SETTINGS, youtube_daily_uploads=1)
    app = create_app(capped, db=db, today=lambda: TODAY)
    app.state.youtube_transport = fake.transport()
    with TestClient(app, base_url="https://testserver") as c:
        h, user = _member(c, tier="full", db=db)
        _connect(c, h)
        _clip(c, db, capped, user["id"], "clip1")
        _clip(c, db, capped, user["id"], "clip2")
        c.post("/api/youtube/posts", headers=h, json={"clip_id": "clip1", "title": "First"})
        c.post("/api/youtube/posts", headers=h, json={"clip_id": "clip2", "title": "Second"})
        assert run(lambda: youtube.deliver_due(db, capped, fake.transport())) == 1
        assert len(fake.uploads) == 1
        held = c.portal.call(lambda: db.youtube_jobs.find_one({"clip_id": "clip2"}))
        assert held["status"] == "queued" and "Daily upload limit" in held["last_error"]
        nxt = held["next_attempt_at"]  # Mongo hands datetimes back naive-UTC
        if nxt.tzinfo is None:
            from datetime import timezone

            nxt = nxt.replace(tzinfo=timezone.utc)
        assert nxt > now()  # tomorrow, not a failure
        assert _upload(c, db, "clip2")["youtube"]["status"] == "queued"
        assert c.get("/api/youtube/status", headers=h).json()["uploads_today"] == 1
