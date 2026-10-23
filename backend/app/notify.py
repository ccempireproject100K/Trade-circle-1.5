"""Outgoing notifications.

Messages are queued in the `outbox` collection when the event happens, so a
lead is never lost if Twilio is briefly down. `app.outbox` delivers them.
Alerts are a paid-plan feature: free-plan contractors log in to see leads.
Text alerts go only to paid contractors who opted in with their alert number.
Email alerts are queued for the email sender (not built yet); anything left
queued past its expiry is dropped rather than sent late.

Texts are capped per member per day by plan (see tiers.SMS_DAILY_BUDGET):
Starter gets 1, Full gets 2, free gets none. The morning rundown takes the
first text of the day, so an instant text here is claimed against the budget
with one slot held back for the rundown — in practice only Full members get
instant texts, as their second text of the day. Emails are never capped.
"""
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .deps import now
from .tiers import ALERTS_TIER, has_tier, sms_budget

ALERT_TTL = timedelta(hours=24)


def sms_day(settings) -> str:
    """The current TC_TIMEZONE calendar day, which text budgets are counted on."""
    return datetime.now(ZoneInfo(settings.timezone)).date().isoformat()


async def claim_sms(db, user_id: str, day: str, limit: int, *, reserve: int = 0, rundown: bool = False) -> bool:
    """Atomically take one of a member's texts for the day. False when the allowance is spent.

    With reserve=1 the claim also fails while the day's last slot is still
    being held back for the morning rundown; the hold is released once the
    rundown has gone out (the counter is marked rundown=True). The peek at the
    counter can race the rundown itself, but only towards sending less: the
    final claim is always atomic against the day's limit.
    """
    if limit <= 0:
        return False
    if reserve:
        counter = await db.sms_allowance.find_one({"_id": f"{user_id}:{day}"}, {"rundown": 1})
        if not (counter and counter.get("rundown")):
            limit -= reserve
            if limit <= 0:
                return False
    update = {"$inc": {"count": 1}, "$set": {"day": day, "user_id": user_id, "updated_at": now()}}
    if rundown:
        update["$set"]["rundown"] = True
    try:
        doc = await db.sms_allowance.find_one_and_update(
            {"_id": f"{user_id}:{day}", "count": {"$lt": limit}},
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return False  # the counter exists and is already at the limit
    return doc is not None


def _message(owner_id: str, channel: str, to: str, body: str, record_id: str, subject: str = "", kind: str = "new_lead") -> dict:
    created = now()
    return {
        "_id": uuid.uuid4().hex,
        "user_id": owner_id,
        "kind": kind,
        "channel": channel,
        "to": to,
        "subject": subject,
        "body": body,
        "record_id": record_id,
        "status": "queued",
        "attempts": 0,
        "next_attempt_at": created,
        "expires_at": created + ALERT_TTL,
        "created_at": created,
    }


async def queue_alert(db, user_id: str, *, kind: str, subject: str, text: str, link: str, record_id: str, day: str) -> None:
    """Email (and text, if opted in and the day's text allowance allows) a paid-plan member.

    Free-plan members see it when they log in. The email is always queued; the
    instant text is claimed with one slot of the day's budget held back for the
    morning rundown, so it only ever goes out as a Full member's second text.
    """
    user = await db.users.find_one({"_id": user_id}, {"email": 1, "alert_sms": 1, "tier": 1})
    if user is None or not has_tier(user, ALERTS_TIER):
        return
    messages = [_message(user_id, "email", user["email"], f"{text} {link}", record_id, subject=subject, kind=kind)]
    sms = user.get("alert_sms") or {}
    if sms.get("phone") and sms.get("active") and await claim_sms(db, user_id, day, sms_budget(user), reserve=1):
        messages.append(_message(user_id, "sms", sms["phone"], f"Trade Circle: {text} {link} Reply STOP to opt out.", record_id, kind=kind))
    await db.outbox.insert_many(messages)


async def queue_lead_alert(db, owner_id: str, quote: dict, public_url: str, *, day: str) -> None:
    # Name only: the lead's phone and email stay inside the signed-in inbox.
    name = quote["name"]
    await queue_alert(
        db,
        owner_id,
        kind="new_lead",
        subject=f"New quote request from {name}",
        text=f"New quote request from {name}.",
        link=f"{public_url}/app/inbox",
        record_id=quote["_id"],
        day=day,
    )
