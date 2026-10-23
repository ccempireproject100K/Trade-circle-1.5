"""Daily summary for paid plans, weekly update for the free plan.

Once a day (from DIGEST_HOUR local time) each paid-plan member who has
something new gets one email: community activity since the last summary
(message requests, messages, meetup changes) and follow-ups due today or
overdue. Handoff notices already go out as they happen, so they aren't repeated.

Texts follow the per-plan daily budget (tiers.SMS_DAILY_BUDGET, decided
2026-10-23): the rundown is also queued as a text for paid members who
turned texts on, and it takes the first text of the day. Instant alert texts
(app.notify) hold one slot back for it, and the afternoon follow-up text
(from FOLLOW_UP_TEXT_HOUR, when follow-ups due today or overdue are still
open) only goes out while the day's allowance lasts.

Free-plan members get the same summary as one email a week instead: Monday
from DIGEST_HOUR local time, over the last 7 days of activity, only when
there's something new. No texts on the free plan, ever. A member is on
exactly one cadence: free is weekly, paid is daily.
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pymongo.errors import DuplicateKeyError

from .deps import now
from .notify import _message, claim_sms
from .tiers import ALERTS_TIER, TIER_ORDER, sms_budget

log = logging.getLogger("trade_circle.digest")

DIGEST_HOUR = 7
FOLLOW_UP_TEXT_HOUR = 14
WEEKLY_WEEKDAY = 0  # Monday
OPEN = ["waiting", "followed_up"]


def due(local_now: datetime) -> bool:
    return local_now.hour >= DIGEST_HOUR


async def _claim_day(db, day: str, job: str = "daily_digest") -> bool:
    """Only one worker runs each day's job: the first to move the marker to today wins."""
    try:
        await db.job_state.update_one({"_id": job, "day": {"$ne": day}}, {"$set": {"day": day, "started_at": now()}}, upsert=True)
    except DuplicateKeyError:
        return False  # the marker already says today
    return True


def compose(name: str, notes: list[dict], due_today: list[dict], overdue: list[dict], public_url: str, weekly: bool = False) -> tuple[str, str]:
    lines = [f"Good morning, {name}. Here's your Trade Circle {'week' if weekly else 'summary'}.", ""]
    if due_today or overdue:
        lines.append("Follow-ups")
        for e in overdue[:10]:
            lines.append(f"  - Overdue since {e['follow_up_on']}: {e['name']}")
        for e in due_today[:10]:
            lines.append(f"  - Due today: {e['name']}")
        lines += [f"  {public_url}/app/inbox", ""]
    if notes:
        lines.append("Community")
        for n in notes[:15]:
            lines.append(f"  - {n['text']}")
        if len(notes) > 15:
            lines.append(f"  - and {len(notes) - 15} more")
        lines += [f"  {public_url}/app/", ""]
    cadence = "once a week on the free plan" if weekly else "once a day on your plan"
    lines.append(f"You get this {cadence}. Turn it off in Settings: {public_url}/app/settings")
    parts = []
    if due_today or overdue:
        parts.append(f"{len(due_today) + len(overdue)} follow-up{'s' if len(due_today) + len(overdue) != 1 else ''}")
    if notes:
        parts.append(f"{len(notes)} update{'s' if len(notes) != 1 else ''}")
    return f"Trade Circle: {' and '.join(parts)}", "\n".join(lines)


async def send_daily(db, settings, local_now: datetime) -> int:
    """Queue today's summaries. Returns how many were queued; 0 if not due or already done."""
    if not due(local_now):
        return 0
    day = local_now.date().isoformat()
    if not await _claim_day(db, day):
        return 0
    queued = 0
    # One cutoff, taken before reading, becomes the next run's starting point. Anything newer waits for
    # tomorrow instead of falling between two runs. MongoDB keeps milliseconds, so step back one.
    stamp = now()
    cutoff = stamp.replace(microsecond=stamp.microsecond // 1000 * 1000) - timedelta(milliseconds=1)
    async for user in db.users.find({"tier": {"$in": _paid_tiers()}, "disabled": {"$ne": True}, "digest_email": {"$ne": False}}):
        since = user.get("digest_last_at") or user.get("created_at")
        query = {"user_id": user["_id"], "read": False, "kind": {"$not": {"$regex": "^handoff"}}, "created_at": {"$lte": cutoff}}
        if since:
            query["created_at"]["$gt"] = since
        notes = await db.notifications.find(query).sort("created_at", 1).to_list(200)
        entries = await db.quotes.find({"owner_id": user["_id"], "status": {"$in": OPEN}, "follow_up_on": {"$lte": day, "$ne": None}}).sort("follow_up_on", 1).to_list(100)
        due_today = [e for e in entries if e["follow_up_on"] == day]
        overdue = [e for e in entries if e["follow_up_on"] < day]
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"digest_last_at": cutoff}})
        if not (notes or due_today or overdue):
            continue
        profile = await db.profiles.find_one({"owner_id": user["_id"]}, {"business_name": 1})
        subject, body = compose(profile["business_name"] if profile else "there", notes, due_today, overdue, settings.public_url)
        await db.outbox.insert_one(_message(user["_id"], "email", user["email"], body, f"digest:{day}", subject=subject, kind="daily_digest"))
        # The rundown is also the day's first text for members who turned texts on.
        sms = user.get("alert_sms") or {}
        if sms.get("phone") and sms.get("active") and await claim_sms(db, user["_id"], day, sms_budget(user), rundown=True):
            text = f"{subject}. {settings.public_url}/app/ Reply STOP to opt out."
            await db.outbox.insert_one(_message(user["_id"], "sms", sms["phone"], text, f"digest:{day}", kind="daily_digest"))
        queued += 1
    log.info("daily summary %s: %d queued", day, queued)
    return queued


def _paid_tiers() -> list[str]:
    return [t for t, rank in TIER_ORDER.items() if rank >= TIER_ORDER[ALERTS_TIER]]


async def send_weekly(db, settings, local_now: datetime) -> int:
    """Queue Monday's weekly update for free-plan members. Returns how many were queued.

    The free plan's one outside update: an email (never a text) covering the
    last 7 days of community activity and follow-ups due or overdue, only when
    there's something new. Paid members are not on this cadence — they get the
    daily summary instead. The week is claimed like the daily jobs, keyed by
    its Monday, so a restart or a second worker can't send it twice.
    """
    if local_now.weekday() != WEEKLY_WEEKDAY or not due(local_now):
        return 0
    monday = (local_now.date() - timedelta(days=local_now.weekday())).isoformat()
    if not await _claim_day(db, monday, "weekly_digest"):
        return 0
    day = local_now.date().isoformat()
    queued = 0
    # Same cutoff discipline as the daily run: one stamp, taken before reading.
    stamp = now()
    cutoff = stamp.replace(microsecond=stamp.microsecond // 1000 * 1000) - timedelta(milliseconds=1)
    async for user in db.users.find({"tier": "free", "disabled": {"$ne": True}, "digest_email": {"$ne": False}}):
        since = user.get("weekly_last_at") or user.get("created_at")
        query = {"user_id": user["_id"], "read": False, "kind": {"$not": {"$regex": "^handoff"}}, "created_at": {"$lte": cutoff}}
        if since:
            query["created_at"]["$gt"] = since
        notes = await db.notifications.find(query).sort("created_at", 1).to_list(200)
        entries = await db.quotes.find({"owner_id": user["_id"], "status": {"$in": OPEN}, "follow_up_on": {"$lte": day, "$ne": None}}).sort("follow_up_on", 1).to_list(100)
        due_today = [e for e in entries if e["follow_up_on"] == day]
        overdue = [e for e in entries if e["follow_up_on"] < day]
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"weekly_last_at": cutoff}})
        if not (notes or due_today or overdue):
            continue
        profile = await db.profiles.find_one({"owner_id": user["_id"]}, {"business_name": 1})
        subject, body = compose(profile["business_name"] if profile else "there", notes, due_today, overdue, settings.public_url, weekly=True)
        await db.outbox.insert_one(_message(user["_id"], "email", user["email"], body, f"weekly:{monday}", subject=subject, kind="weekly_digest"))
        queued += 1
    log.info("weekly update %s: %d queued", monday, queued)
    return queued


async def send_follow_up_texts(db, settings, local_now: datetime) -> int:
    """One afternoon text, if follow-ups due today or overdue are still open and the day's text allowance lasts. Returns how many were queued."""
    if local_now.hour < FOLLOW_UP_TEXT_HOUR:
        return 0
    day = local_now.date().isoformat()
    if not await _claim_day(db, day, "follow_up_texts"):
        return 0
    queued = 0
    async for user in db.users.find({"tier": {"$in": _paid_tiers()}, "disabled": {"$ne": True}, "alert_sms.active": True}):
        entries = await db.quotes.find({"owner_id": user["_id"], "status": {"$in": OPEN}, "follow_up_on": {"$lte": day, "$ne": None}}).sort("follow_up_on", 1).to_list(20)
        if not entries:
            continue
        if not await claim_sms(db, user["_id"], day, sms_budget(user)):
            continue  # the day's texts are spent (the rundown, an instant text)
        names = ", ".join(e["name"] for e in entries[:3]) + (f" and {len(entries) - 3} more" if len(entries) > 3 else "")
        count = f"{len(entries)} follow-up{'s' if len(entries) != 1 else ''}"
        body = f"Trade Circle: {count} still due ({names}). {settings.public_url}/app/inbox Reply STOP to opt out."
        await db.outbox.insert_one(_message(user["_id"], "sms", user["alert_sms"]["phone"], body, f"follow-ups:{day}", kind="follow_up_text"))
        queued += 1
    log.info("follow-up texts %s: %d queued", day, queued)
    return queued


def local_now(settings) -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))

