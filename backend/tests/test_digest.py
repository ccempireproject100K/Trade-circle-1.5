import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import Settings
from app.digest import send_daily, send_follow_up_texts

CHI = ZoneInfo("America/Chicago")
SETTINGS = Settings(jwt_secret="t" * 40)


def at(day, hour=8):
    return datetime(2026, 10, day, hour, 0, tzinfo=CHI)


async def setup(db):
    users = [
        {"_id": "paid", "email": "paid@example.com", "tier": "starter"},
        {"_id": "full", "email": "full@example.com", "tier": "full"},
        {"_id": "free", "email": "free@example.com", "tier": "free"},
        {"_id": "off", "email": "off@example.com", "tier": "full", "digest_email": False},
        {"_id": "quiet", "email": "quiet@example.com", "tier": "starter"},
    ]
    await db.users.insert_many(users)
    await db.profiles.insert_many([{"owner_id": u["_id"], "business_name": f"{u['_id'].title()} Co"} for u in users])
    for uid in ("paid", "free", "off"):
        await db.notifications.insert_one({"_id": f"n-{uid}", "user_id": uid, "kind": "message_request", "text": "Alpha asked to message you.", "link": "/messages", "read": False, "created_at": datetime(2026, 10, 22, 12, tzinfo=CHI)})
    await db.notifications.insert_one({"_id": "n-handoff", "user_id": "paid", "kind": "handoff_reversed", "text": "Handed back", "link": "/handoffs", "read": False, "created_at": datetime(2026, 10, 22, 12, tzinfo=CHI)})
    await db.quotes.insert_many([
        {"_id": "q1", "owner_id": "full", "name": "Sam", "status": "waiting", "follow_up_on": "2026-10-23"},
        {"_id": "q2", "owner_id": "full", "name": "Lee", "status": "followed_up", "follow_up_on": "2026-10-20"},
        {"_id": "q3", "owner_id": "full", "name": "Won already", "status": "won", "follow_up_on": "2026-10-20"},
        {"_id": "q4", "owner_id": "free", "name": "Free lead", "status": "waiting", "follow_up_on": "2026-10-23"},
    ])


def run(db, coro_fn):
    return asyncio.run(coro_fn(db))


def test_paid_members_get_one_summary_a_day_free_members_none(db):
    async def go(db):
        await setup(db)
        assert await send_daily(db, SETTINGS, at(23, hour=6)) == 0  # before 7 AM
        assert await send_daily(db, SETTINGS, at(23)) == 2  # paid (community) and full (follow-ups)
        assert await send_daily(db, SETTINGS, at(23, hour=15)) == 0  # once a day
        mails = {m["to"]: m async for m in db.outbox.find({"kind": "daily_digest"})}
        return mails

    mails = run(db, go)
    assert set(mails) == {"paid@example.com", "full@example.com"}  # not free, not opted out, not quiet
    assert all(m["channel"] == "email" for m in mails.values())
    paid = mails["paid@example.com"]
    assert paid["subject"] == "Trade Circle: 1 update"
    assert "Alpha asked to message you." in paid["body"] and "Handed back" not in paid["body"]
    full = mails["full@example.com"]
    assert full["subject"] == "Trade Circle: 2 follow-ups"
    assert "Overdue since 2026-10-20: Lee" in full["body"] and "Due today: Sam" in full["body"]
    assert "Won already" not in full["body"]
    assert "Turn it off in Settings" in full["body"]


def test_next_day_only_has_new_activity(db, monkeypatch):
    from app import digest

    clock = {"t": datetime(2026, 10, 24, 12, 0, 0, 500, tzinfo=timezone.utc)}
    monkeypatch.setattr(digest, "now", lambda: clock["t"])

    async def go(db):
        await setup(db)
        await send_daily(db, SETTINGS, at(23))
        await db.quotes.update_many({}, {"$set": {"status": "won"}})
        first = await send_daily(db, SETTINGS, at(24))
        # Created in the same millisecond as that run, after it read: it must still reach the next summary.
        await db.notifications.insert_one({"_id": "new", "user_id": "paid", "kind": "meetup", "text": "Meetup moved", "link": "/x", "read": False, "created_at": clock["t"]})
        clock["t"] += timedelta(days=1)
        second = await send_daily(db, SETTINGS, at(25))
        bodies = [m["body"] async for m in db.outbox.find({"to": "paid@example.com"}).sort("created_at", 1)]
        return first, second, bodies

    first, second, bodies = run(db, go)
    assert first == 0  # nothing new the next day: no email
    assert second == 1 and "Meetup moved" in bodies[-1] and "Alpha asked" not in bodies[-1]


def test_summary_setting_can_be_turned_off_on_any_plan(client, signup, db):
    # The toggle drives the daily summary on paid plans and the weekly update
    # on the free plan, so every plan can turn its cadence off.
    free, _ = signup()
    assert client.get("/api/me/alerts", headers=free).json()["daily_summary"] is True
    assert client.put("/api/me/alerts/digest", headers=free, json={"on": False}).json()["daily_summary"] is False
    paid, user = signup("Paid Co", trade="plumber")
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": "starter"}})
    assert client.get("/api/me/alerts", headers=paid).json()["daily_summary"] is True
    assert client.put("/api/me/alerts/digest", headers=paid, json={"on": False}).json()["daily_summary"] is False


def test_one_afternoon_text_for_open_follow_ups(db):
    async def go(db):
        await setup(db)
        await db.users.update_many({"_id": {"$in": ["full", "free", "quiet"]}}, {"$set": {"alert_sms": {"phone": "+15125550100", "active": True}}})
        await db.quotes.insert_one({"_id": "q9", "owner_id": "quiet", "name": "Done", "status": "closed", "follow_up_on": "2026-10-20"})
        assert await send_follow_up_texts(db, SETTINGS, at(23, hour=13)) == 0  # too early
        sent = await send_follow_up_texts(db, SETTINGS, at(23, hour=14))
        again = await send_follow_up_texts(db, SETTINGS, at(23, hour=17))
        texts = [m async for m in db.outbox.find({"kind": "follow_up_text"})]
        return sent, again, texts

    sent, again, texts = run(db, go)
    assert (sent, again) == (1, 0)  # once a day
    assert [t["user_id"] for t in texts] == ["full"]  # paid with texts on and open follow-ups; not free, not closed-only
    assert texts[0]["channel"] == "sms" and texts[0]["body"].startswith("Trade Circle: 2 follow-ups still due (Lee, Sam).")
    assert "Reply STOP" in texts[0]["body"]
