"""Outgoing notifications.

Messages are queued in the `outbox` collection when the event happens, so a
lead is never lost if Twilio is briefly down. `app.outbox` delivers them.
Alerts are a paid-plan feature: free-plan contractors log in to see leads.
Text alerts go only to paid contractors who opted in with their alert number.
Email alerts are queued for the email sender (not built yet); anything left
queued past its expiry is dropped rather than sent late.
"""
import uuid
from datetime import timedelta

from .deps import now
from .tiers import ALERTS_TIER, has_tier

ALERT_TTL = timedelta(hours=24)


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


async def queue_alert(db, user_id: str, *, kind: str, subject: str, text: str, link: str, record_id: str) -> None:
    """Email (and text, if opted in) a paid-plan member. Free-plan members see it when they log in."""
    user = await db.users.find_one({"_id": user_id}, {"email": 1, "alert_sms": 1, "tier": 1})
    if user is None or not has_tier(user, ALERTS_TIER):
        return
    messages = [_message(user_id, "email", user["email"], f"{text} {link}", record_id, subject=subject, kind=kind)]
    sms = user.get("alert_sms") or {}
    if sms.get("phone") and sms.get("active"):
        messages.append(_message(user_id, "sms", sms["phone"], f"Trade Circle: {text} {link} Reply STOP to opt out.", record_id, kind=kind))
    await db.outbox.insert_many(messages)


async def queue_lead_alert(db, owner_id: str, quote: dict, public_url: str) -> None:
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
    )
