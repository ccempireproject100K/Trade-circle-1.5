"""The per-plan daily text budget (decided 2026-10-23) and the free weekly update.

Starter gets 1 text a day and it is the morning rundown; Full gets 2 (the
rundown plus one more); free gets none, and a weekly update email instead.
Emails are never capped. See app/tiers.py SMS_DAILY_BUDGET and app/notify.py.
"""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.digest import send_daily, send_follow_up_texts, send_weekly
from app.notify import claim_sms, queue_alert, sms_day
from app.tiers import sms_budget

CHI = ZoneInfo("America/Chicago")
SETTINGS = Settings(jwt_secret="t" * 40)
DAY = "2026-10-23"  # a Friday, the conftest "today"
SMS = {"phone": "+15125550100", "active": True}


def fri(day, hour=8):
    return datetime(2026, 10, day, hour, 0, tzinfo=CHI)


# --- the budget itself ---


def test_budgets_by_tier():
    assert sms_budget({"tier": "free"}) == 0
    assert sms_budget({"tier": "starter"}) == 1
    assert sms_budget({"tier": "full"}) == 2
    assert sms_budget({}) == 0


def test_sms_day_is_the_platform_timezone_day():
    assert sms_day(SETTINGS) == datetime.now(CHI).date().isoformat()


def test_claim_sms_enforces_the_limit_and_rolls_over(db):
    async def go(db):
        assert await claim_sms(db, "u1", DAY, 0) is False
        assert await claim_sms(db, "u1", DAY, 1) is True
        assert await claim_sms(db, "u1", DAY, 1) is False  # spent
        assert await claim_sms(db, "u1", "2026-10-24", 1) is True  # a new day starts empty
        assert await claim_sms(db, "u2", DAY, 2) is True
        assert await claim_sms(db, "u2", DAY, 2) is True
        assert await claim_sms(db, "u2", DAY, 2) is False
        doc = await db.sms_allowance.find_one({"_id": f"u2:{DAY}"})
        return doc["count"]

    assert asyncio.run(go(db)) == 2


# --- instant alert texts through the API ---

QUOTE = {"name": "Dana Homeowner", "phone": "+15125550199", "message": "Need a panel upgrade"}


def _slug(client, headers):
    return client.get("/api/me/profile", headers=headers).json()["slug"]


def _set_tier(client, db, user_id, tier):
    client.portal.call(db.users.update_one, {"_id": user_id}, {"$set": {"tier": tier}})


def _outbox(client, db, user_id):
    return client.portal.call(lambda: db.outbox.find({"user_id": user_id}).sort("channel", 1).to_list(50))


def _opt_in(client, headers):
    res = client.put("/api/me/alerts/sms", headers=headers, json={"phone": "(512) 555-0100", "consent": True})
    assert res.status_code == 200, res.text


def test_starter_lead_arrives_by_email_only(client, signup, db):
    headers, user = signup(email="starter@example.com")
    _set_tier(client, db, user["id"], "starter")
    _opt_in(client, headers)
    client.post(f"/api/p/{_slug(client, headers)}/quote", json=QUOTE)
    # Starter's one text is the morning rundown, so a lead never texts instantly.
    assert [m["channel"] for m in _outbox(client, db, user["id"])] == ["email"]
    assert client.portal.call(lambda: db.sms_allowance.find_one({"_id": f"{user['id']}:{DAY}"})) is None


def test_full_lead_gets_one_instant_text_then_the_budget_is_spent(client, signup, db):
    headers, user = signup(email="full@example.com")
    _set_tier(client, db, user["id"], "full")
    _opt_in(client, headers)
    slug = _slug(client, headers)
    client.post(f"/api/p/{slug}/quote", json=QUOTE)
    assert [m["channel"] for m in _outbox(client, db, user["id"])] == ["email", "sms"]
    client.post(f"/api/p/{slug}/quote", json={**QUOTE, "name": "Second Lead"})
    messages = _outbox(client, db, user["id"])
    # The second lead still emails; the text allowance (rundown + one) is spent.
    assert [m["channel"] for m in messages] == ["email", "email", "sms"]
    counter = client.portal.call(lambda: db.sms_allowance.find_one({"_id": f"{user['id']}:{DAY}"}))
    assert counter["count"] == 1  # instant texts claim against budget - 1 (rundown slot held back)


def test_free_plan_is_never_texted_even_with_a_number_on_file(client, signup, db):
    headers, user = signup()
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"alert_sms": SMS}})
    client.post(f"/api/p/{_slug(client, headers)}/quote", json=QUOTE)
    assert _outbox(client, db, user["id"]) == []


def test_alerts_view_describes_each_plans_texts(client, signup, db):
    free, _ = signup()
    view = client.get("/api/me/alerts", headers=free).json()
    assert "weekly update email" in view["sms_policy"]
    headers, user = signup("Starter Co", email="s2@example.com")
    _set_tier(client, db, user["id"], "starter")
    assert "One text a day" in client.get("/api/me/alerts", headers=headers).json()["sms_policy"]
    _set_tier(client, db, user["id"], "full")
    assert "two texts a day" in client.get("/api/me/alerts", headers=headers).json()["sms_policy"]


# --- the rundown and the afternoon text share the budget ---


async def _digest_setup(db):
    users = [
        {"_id": "starter", "email": "starter@example.com", "tier": "starter", "alert_sms": dict(SMS)},
        {"_id": "full", "email": "full@example.com", "tier": "full", "alert_sms": dict(SMS)},
        {"_id": "muted", "email": "muted@example.com", "tier": "starter", "alert_sms": dict(SMS), "digest_email": False},
    ]
    await db.users.insert_many(users)
    await db.profiles.insert_many([{"owner_id": u["_id"], "business_name": f"{u['_id'].title()} Co"} for u in users])
    for uid in ("starter", "full"):
        await db.notifications.insert_one({"_id": f"n-{uid}", "user_id": uid, "kind": "message_request", "text": "Alpha asked to message you.", "link": "/messages", "read": False, "created_at": datetime(2026, 10, 22, 12, tzinfo=CHI)})
    await db.quotes.insert_many([
        {"_id": "q-full", "owner_id": "full", "name": "Sam", "status": "waiting", "follow_up_on": DAY},
        {"_id": "q-muted", "owner_id": "muted", "name": "Pat", "status": "waiting", "follow_up_on": DAY},
        {"_id": "q-starter", "owner_id": "starter", "name": "Jo", "status": "waiting", "follow_up_on": "2026-10-24"},
    ])


def _texts(db, user_id):
    return lambda: db.outbox.find({"user_id": user_id, "channel": "sms"}).sort("created_at", 1).to_list(20)


def test_rundown_takes_the_first_text_and_the_afternoon_text_respects_the_budget(db):
    async def go(db):
        await _digest_setup(db)
        assert await send_daily(db, SETTINGS, fri(23)) == 2
        texts = {uid: await _texts(db, uid)() for uid in ("starter", "full")}
        counts = {uid: (await db.sms_allowance.find_one({"_id": f"{uid}:{DAY}"}))["count"] for uid in ("starter", "full")}
        follow = await send_follow_up_texts(db, SETTINGS, fri(23, hour=14))
        full_texts = await _texts(db, "full")()
        follow_ids = {m["user_id"] async for m in db.outbox.find({"kind": "follow_up_text"})}
        return texts, counts, follow, full_texts, follow_ids

    texts, counts, follow, full_texts, follow_ids = asyncio.run(go(db))
    assert [t["kind"] for t in texts["starter"]] == ["daily_digest"]  # the rundown, as a text
    assert "1 update" in texts["starter"][0]["body"] and "Reply STOP" in texts["starter"][0]["body"]
    assert [t["kind"] for t in texts["full"]] == ["daily_digest"]
    assert counts == {"starter": 1, "full": 1}
    # Afternoon: Starter's only text is spent on the rundown, so no follow-up
    # text for them. Full has one slot left, and "muted" (summary off, so no
    # rundown claimed) still has the day's text to spend.
    assert follow == 2 and follow_ids == {"full", "muted"}
    assert [t["kind"] for t in full_texts] == ["daily_digest", "follow_up_text"]


def test_instant_texts_after_the_rundown_only_fill_fulls_second_slot(db):
    async def go(db):
        await _digest_setup(db)
        await send_daily(db, SETTINGS, fri(23))
        for uid in ("starter", "full"):
            await queue_alert(db, uid, kind="new_lead", subject="New quote request", text="New quote request.", link="https://x/app/inbox", record_id="lead-1", day=DAY)
            await queue_alert(db, uid, kind="new_lead", subject="New quote request", text="New quote request.", link="https://x/app/inbox", record_id="lead-2", day=DAY)
        out = {}
        for uid in ("starter", "full"):
            msgs = [m async for m in db.outbox.find({"user_id": uid})]
            out[uid] = {
                "emails": sum(1 for m in msgs if m["channel"] == "email"),
                "text_kinds": sorted(m["kind"] for m in msgs if m["channel"] == "sms"),
            }
        return out

    out = asyncio.run(go(db))
    # Starter: the rundown text only; both leads still arrived by email.
    assert out["starter"] == {"emails": 3, "text_kinds": ["daily_digest"]}
    # Full: the rundown text and one instant lead text, then the budget is spent.
    assert out["full"] == {"emails": 3, "text_kinds": ["daily_digest", "new_lead"]}


def test_afternoon_text_uses_the_days_text_when_no_rundown_went_out(db):
    async def go(db):
        await _digest_setup(db)
        await send_daily(db, SETTINGS, fri(23))  # "muted" turned the summary off: no rundown, no claim
        sent = await send_follow_up_texts(db, SETTINGS, fri(23, hour=14))
        texts = [m async for m in db.outbox.find({"kind": "follow_up_text"})]
        return sent, texts

    sent, texts = asyncio.run(go(db))
    assert sent == 2  # full (second slot) and muted (the day's one text, unused by a rundown)
    assert {t["user_id"] for t in texts} == {"full", "muted"}


def test_a_new_day_starts_with_a_fresh_allowance(db):
    async def go(db):
        await _digest_setup(db)
        await send_daily(db, SETTINGS, fri(23))
        await send_daily(db, SETTINGS, fri(24))
        doc = await db.sms_allowance.find_one({"_id": "starter:2026-10-24"})
        return doc["count"]

    assert asyncio.run(go(db)) == 1


# --- the free plan's weekly update ---


async def _weekly_setup(db):
    users = [
        {"_id": "free_act", "email": "act@example.com", "tier": "free", "created_at": datetime(2026, 10, 1, tzinfo=CHI), "alert_sms": dict(SMS)},
        {"_id": "free_follow", "email": "follow@example.com", "tier": "free", "created_at": datetime(2026, 10, 1, tzinfo=CHI)},
        {"_id": "free_quiet", "email": "quiet@example.com", "tier": "free", "created_at": datetime(2026, 10, 1, tzinfo=CHI)},
        {"_id": "free_off", "email": "off@example.com", "tier": "free", "digest_email": False, "created_at": datetime(2026, 10, 1, tzinfo=CHI)},
        {"_id": "paid_act", "email": "paid@example.com", "tier": "starter", "created_at": datetime(2026, 10, 1, tzinfo=CHI)},
    ]
    await db.users.insert_many(users)
    await db.profiles.insert_many([{"owner_id": u["_id"], "business_name": f"{u['_id'].title()} Co"} for u in users])
    for uid in ("free_act", "free_off", "paid_act"):
        await db.notifications.insert_one({"_id": f"n-{uid}", "user_id": uid, "kind": "message_request", "text": "Alpha asked to message you.", "link": "/messages", "read": False, "created_at": datetime(2026, 10, 22, 12, tzinfo=CHI)})
    await db.quotes.insert_one({"_id": "q-free", "owner_id": "free_follow", "name": "Sam", "status": "waiting", "follow_up_on": "2026-10-25"})


def test_free_members_get_one_weekly_update_email_and_no_texts(db):
    async def go(db):
        await _weekly_setup(db)
        monday = datetime(2026, 10, 26, 8, 0, tzinfo=CHI)
        assert await send_weekly(db, SETTINGS, datetime(2026, 10, 25, 8, 0, tzinfo=CHI)) == 0  # Sunday: not the day
        first = await send_weekly(db, SETTINGS, monday)
        again = await send_weekly(db, SETTINGS, datetime(2026, 10, 26, 15, 0, tzinfo=CHI))
        mails = [m async for m in db.outbox.find({"kind": "weekly_digest"})]
        texts = [m async for m in db.outbox.find({"channel": "sms"})]
        return first, again, mails, texts

    first, again, mails, texts = asyncio.run(go(db))
    assert (first, again) == (2, 0)  # activity and follow-ups; never twice in a week
    assert {m["to"] for m in mails} == {"act@example.com", "follow@example.com"}  # not quiet, not opted out, not paid
    assert all(m["channel"] == "email" for m in mails)
    assert texts == []  # the free plan gets no texts, even with a number on file
    act = next(m for m in mails if m["to"] == "act@example.com")
    assert "Alpha asked to message you." in act["body"] and "once a week on the free plan" in act["body"]


def test_weekly_update_next_week_only_carries_what_is_still_open(db):
    async def go(db):
        await _weekly_setup(db)
        await send_weekly(db, SETTINGS, datetime(2026, 10, 26, 8, 0, tzinfo=CHI))
        # A week later: the community note is old news, the follow-up is still due.
        second = await send_weekly(db, SETTINGS, datetime(2026, 11, 2, 8, 0, tzinfo=CHI))
        mails = [m async for m in db.outbox.find({"kind": "weekly_digest", "record_id": "weekly:2026-11-02"})]
        return second, mails

    second, mails = asyncio.run(go(db))
    assert second == 1
    assert [m["to"] for m in mails] == ["follow@example.com"]
