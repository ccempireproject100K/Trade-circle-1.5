import asyncio
from datetime import timedelta

import httpx
import pytest

from app import outbox
from app.config import Settings
from app.deps import now

QUOTE = {"name": "Dana Homeowner", "phone": "+15125550199", "message": "Need a panel upgrade"}


def _slug(client, headers):
    return client.get("/api/me/profile", headers=headers).json()["slug"]


def _set_tier(client, db, user_id, tier):
    client.portal.call(db.users.update_one, {"_id": user_id}, {"$set": {"tier": tier}})


def _outbox(client, db):
    return client.portal.call(lambda: db.outbox.find({}).sort("channel", 1).to_list(50))


def test_free_plan_gets_no_alerts(client, signup, db):
    headers, _ = signup()
    client.post(f"/api/p/{_slug(client, headers)}/quote", json=QUOTE)
    assert _outbox(client, db) == []
    # The lead is still waiting in the inbox.
    assert len(client.get("/api/inbox", headers=headers).json()) == 1


def test_free_plan_cannot_turn_on_text_alerts(client, signup):
    headers, _ = signup()
    res = client.put("/api/me/alerts/sms", headers=headers, json={"phone": "(512) 555-0100", "consent": True})
    assert res.status_code == 402
    assert client.get("/api/me/alerts", headers=headers).json()["available"] is False


def test_paid_plan_gets_email_and_opted_in_text(client, signup, db):
    headers, user = signup(email="paid@example.com")
    _set_tier(client, db, user["id"], "starter")
    assert client.put("/api/me/alerts/sms", headers=headers, json={"phone": "(512) 555-0100"}).status_code == 422
    res = client.put("/api/me/alerts/sms", headers=headers, json={"phone": "(512) 555-0100", "consent": True})
    assert res.json()["sms"] == {"phone": "+15125550100", "active": True}

    client.post(f"/api/p/{_slug(client, headers)}/quote", json=QUOTE)
    email, sms = _outbox(client, db)
    assert (email["channel"], email["to"]) == ("email", "paid@example.com")
    assert (sms["channel"], sms["to"], sms["status"]) == ("sms", "+15125550100", "queued")
    assert "Dana Homeowner" in sms["body"] and "STOP" in sms["body"]
    assert "+15125550199" not in sms["body"] + email["body"]


def test_paid_plan_without_text_opt_in_gets_email_only(client, signup, db):
    headers, user = signup()
    _set_tier(client, db, user["id"], "full")
    client.put("/api/me/alerts/sms", headers=headers, json={"phone": "+15125550100", "consent": True})
    assert client.delete("/api/me/alerts/sms", headers=headers).status_code == 204
    client.post(f"/api/p/{_slug(client, headers)}/quote", json=QUOTE)
    assert [m["channel"] for m in _outbox(client, db)] == ["email"]


# --- delivery ---


def _settings(**overrides):
    base = dict(jwt_secret="t" * 40, twilio_account_sid="AC123", twilio_auth_token="tok", twilio_messaging_sid="MG456")
    return Settings(**{**base, **overrides})


def _twilio(handler):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    return outbox.TwilioSMS(_settings(), transport=httpx.MockTransport(record)), requests


async def _queue(db, **fields):
    from app.notify import _message

    msg = {**_message("u1", "sms", "+15125550100", "hello", "q1"), **fields}
    await db.outbox.insert_one(msg)
    return msg["_id"]


@pytest.fixture
def adb(db):
    """Delivery tests are async functions taking the database, run on one event loop."""
    return lambda test: asyncio.run(test(db))


def test_delivery_sends_via_messaging_service(adb):
    async def test(db):
        sms, requests = _twilio(lambda r: httpx.Response(201, json={"sid": "SM1", "status": "queued"}))
        msg_id = await _queue(db)
        assert await outbox.deliver_due(db, sms) == 1
        form = dict(httpx.QueryParams(requests[0].content.decode()))
        assert requests[0].url.path == "/2010-04-01/Accounts/AC123/Messages.json"
        assert form == {"To": "+15125550100", "Body": "hello", "MessagingServiceSid": "MG456"}
        stored = await db.outbox.find_one({"_id": msg_id})
        assert (stored["status"], stored["provider_id"]) == ("sent", "SM1")
        # Nothing left to send: a second pass sends nothing, so no double texts.
        assert await outbox.deliver_due(db, sms) == 0

    adb(test)


def test_server_error_retries_later(adb):
    async def test(db):
        sms, _ = _twilio(lambda r: httpx.Response(503, text="down"))
        msg_id = await _queue(db)
        await outbox.deliver_due(db, sms)
        stored = await db.outbox.find_one({"_id": msg_id})
        assert stored["status"] == "queued" and stored["attempts"] == 1

    adb(test)


def test_stop_reply_switches_off_text_alerts(adb):
    async def test(db):
        await db.users.insert_one({"_id": "u1", "alert_sms": {"phone": "+15125550100", "active": True}})
        sms, _ = _twilio(lambda r: httpx.Response(400, json={"code": 21610, "message": "Attempt to send to unsubscribed recipient"}))
        msg_id = await _queue(db)
        await outbox.deliver_due(db, sms)
        assert (await db.outbox.find_one({"_id": msg_id}))["status"] == "opted_out"
        assert (await db.users.find_one({"_id": "u1"}))["alert_sms"]["active"] is False

    adb(test)


def test_permanent_error_is_not_retried(adb):
    async def test(db):
        sms, _ = _twilio(lambda r: httpx.Response(400, json={"code": 21211, "message": "Invalid To number"}))
        msg_id = await _queue(db)
        await outbox.deliver_due(db, sms)
        assert (await db.outbox.find_one({"_id": msg_id}))["status"] == "failed"

    adb(test)


def test_stale_alerts_expire_instead_of_sending_late(adb):
    async def test(db):
        sms, requests = _twilio(lambda r: httpx.Response(201, json={"sid": "SM1"}))
        msg_id = await _queue(db, expires_at=now() - timedelta(minutes=1))
        assert await outbox.deliver_due(db, sms) == 0
        assert requests == []
        assert (await db.outbox.find_one({"_id": msg_id}))["status"] == "expired"

    adb(test)


def test_twilio_ready_needs_sender():
    assert _settings().twilio_ready
    assert not _settings(twilio_messaging_sid="").twilio_ready
    assert _settings(twilio_messaging_sid="", twilio_from_number="+15125550000").twilio_ready


# --- email through Resend ---


def _resend(handler, **overrides):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    settings = _settings(resend_api_key="re_test", resend_from_email="alerts@mindateasesolutions.com", **overrides)
    return outbox.ResendEmail(settings, transport=httpx.MockTransport(record)), requests


async def _queue_email(db):
    from app.notify import _message

    msg = _message("u1", "email", "pro@example.com", "<b>Dana</b> asked for a quote. https://x/app/inbox", "q1", subject="New quote request from <b>Dana</b>")
    await db.outbox.insert_one(msg)
    return msg["_id"]


def test_email_sends_plain_text_through_resend(adb):
    async def test(db):
        email, requests = _resend(lambda r: httpx.Response(200, json={"id": "em_1"}), email_reply_to="help@mindateasesolutions.com")
        msg_id = await _queue_email(db)
        assert await outbox.deliver_due(db, None, email) == 1
        import json

        sent = json.loads(requests[0].content)
        assert requests[0].url.path == "/emails" and requests[0].headers["authorization"] == "Bearer re_test"
        assert sent["from"] == "Trade Circle <alerts@mindateasesolutions.com>"
        assert sent["to"] == ["pro@example.com"] and sent["reply_to"] == "help@mindateasesolutions.com"
        # Text only, never HTML: the lead's name comes from a public form.
        assert "html" not in sent and sent["text"].startswith("<b>Dana</b>")
        stored = await db.outbox.find_one({"_id": msg_id})
        assert (stored["status"], stored["provider_id"]) == ("sent", "em_1")

    adb(test)


def test_email_errors_retry_or_fail(adb):
    async def test(db):
        down, _ = _resend(lambda r: httpx.Response(503, text="down"))
        first = await _queue_email(db)
        await outbox.deliver_due(db, None, down)
        assert (await db.outbox.find_one({"_id": first}))["status"] == "queued"
        bad, _ = _resend(lambda r: httpx.Response(422, json={"message": "Invalid to address"}))
        second = await _queue_email(db)
        await db.outbox.update_one({"_id": first}, {"$set": {"status": "sent"}})
        await outbox.deliver_due(db, None, bad)
        assert (await db.outbox.find_one({"_id": second}))["status"] == "failed"

    adb(test)


def test_unconfigured_channel_stays_queued(adb):
    async def test(db):
        msg_id = await _queue_email(db)
        sms, _ = _twilio(lambda r: httpx.Response(201, json={"sid": "SM1"}))
        await outbox.deliver_due(db, sms, None)  # only texts configured
        assert (await db.outbox.find_one({"_id": msg_id}))["status"] == "queued"

    adb(test)


def test_email_ready_needs_key_and_sender():
    assert not _settings().email_ready
    assert not _settings(resend_api_key="re_x").email_ready
    assert _settings(resend_api_key="re_x", resend_from_email="a@b.com").email_ready
