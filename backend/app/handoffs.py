"""Rules for vacations and job handoffs.

Trade Circle is for networking, not job brokering, so handoffs are limited:
- up to WEEKLY_LIMIT outgoing handoffs per week (Monday to Sunday, local time),
- of which at most PER_RECIPIENT_LIMIT to the same member.
Declined or withdrawn proposals give their slot back; proposed, accepted and
completed ones count. After acceptance, a reversal by the recipient gives the
slot back; a cancellation the sender asked for (and the recipient agreed to)
keeps it used.

A vacation lifts those limits while it runs. One vacation lasts at most
VACATION_MAX_DAYS days, and entries that overlap or touch are treated as one
continuous vacation, which also may not exceed VACATION_MAX_DAYS. Separate
vacations need at least VACATION_MIN_GAP_DAYS between them. Handoffs sent
during a vacation don't count toward the normal weekly limits, so the limits
come back unchanged the day after it ends.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

WEEKLY_LIMIT = 3
PER_RECIPIENT_LIMIT = 2
VACATION_MAX_DAYS = 14
# Vacations are rare: a separate one must start at least this many days (about 3 months) after the last ends.
VACATION_MIN_GAP_DAYS = 90

OPEN_STATUSES = ("proposed", "accepted")


# --- weeks ---


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def resets_at(day: date, timezone: str) -> datetime:
    """When this week's allowance resets: next Monday at midnight, local time."""
    return datetime.combine(week_start(day) + timedelta(days=7), time.min, ZoneInfo(timezone))


# --- vacations ---


def vacation_days(start: date, end: date) -> int:
    return (end - start).days + 1


def continuous_span(existing: list[tuple[date, date]], new: tuple[date, date]) -> tuple[date, date]:
    """The unbroken stretch of vacation days that `new` would join, counting overlapping and back-to-back entries."""
    start, end = new
    pending = list(existing)
    grew = True
    while grew:
        grew = False
        for other in list(pending):
            if other[0] <= end + timedelta(days=1) and other[1] >= start - timedelta(days=1):
                start, end = min(start, other[0]), max(end, other[1])
                pending.remove(other)
                grew = True
    return start, end


def check_vacation(start: date, end: date, today: date, existing: list[tuple[date, date]]) -> None:
    if end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The end date must be on or after the start date.")
    if end < today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That vacation is already over.")
    if vacation_days(start, end) > VACATION_MAX_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"A vacation can be at most {VACATION_MAX_DAYS} days. Arrange longer coverage outside Trade Circle.",
        )
    span_start, span_end = continuous_span(existing, (start, end))
    if vacation_days(span_start, span_end) > VACATION_MAX_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"This would join another vacation and run {vacation_days(span_start, span_end)} days in a row "
            f"({span_start} to {span_end}). The limit is {VACATION_MAX_DAYS} days; arrange longer coverage outside Trade Circle.",
        )
    gap = timedelta(days=VACATION_MIN_GAP_DAYS)
    for other_start, other_end in existing:
        if span_start <= other_start and other_end <= span_end:
            continue  # part of the same continuous vacation
        if other_end < span_start and span_start - other_end <= gap:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Vacations need about 3 months ({VACATION_MIN_GAP_DAYS} days) between them. Your last one ended "
                f"{other_end}, so the next can start on {other_end + gap + timedelta(days=1)} or later.",
            )
        if other_start > span_end and other_start - span_end <= gap:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Vacations need about 3 months ({VACATION_MIN_GAP_DAYS} days) between them, and you have one starting "
                f"{other_start}. This one would need to end by {other_start - gap - timedelta(days=1)}.",
            )


async def active_vacation(db, user_id: str, today: date) -> dict | None:
    day = today.isoformat()
    return await db.vacations.find_one({"owner_id": user_id, "start_on": {"$lte": day}, "end_on": {"$gte": day}})


async def vacation_ranges(db, user_id: str, exclude_id: str | None = None) -> list[tuple[date, date]]:
    entries = await db.vacations.find({"owner_id": user_id}).to_list(500)
    return [
        (date.fromisoformat(v["start_on"]), date.fromisoformat(v["end_on"]))
        for v in entries
        if v["_id"] != exclude_id
    ]


# --- weekly allowance ---


def _quota_key(user_id: str, week: date) -> str:
    return f"{user_id}:{week.isoformat()}"


class LimitReached(HTTPException):
    def __init__(self, message: str):
        super().__init__(status.HTTP_409_CONFLICT, message)


async def reserve_slot(db, user_id: str, recipient_id: str, today: date, timezone: str) -> None:
    """Atomically take one of this week's slots, or raise LimitReached.

    The check and the increment happen in one database operation, so two
    handoffs sent at the same moment can't both squeeze past the limit.
    """
    week = week_start(today)
    key = _quota_key(user_id, week)
    field = f"recipients.{recipient_id}"
    for _ in range(3):
        taken = await db.handoff_quota.find_one_and_update(
            {
                "_id": key,
                "total": {"$lt": WEEKLY_LIMIT},
                "$or": [{field: {"$exists": False}}, {field: {"$lt": PER_RECIPIENT_LIMIT}}],
            },
            {"$inc": {"total": 1, field: 1}},
            return_document=ReturnDocument.AFTER,
        )
        if taken is not None:
            return
        quota = await db.handoff_quota.find_one({"_id": key})
        if quota is None:
            try:
                await db.handoff_quota.insert_one(
                    {"_id": key, "user_id": user_id, "week_start": week.isoformat(), "total": 1, "recipients": {recipient_id: 1}}
                )
                return
            except DuplicateKeyError:
                continue  # Another request created it first; try the increment again.
        reset = resets_at(today, timezone).strftime("%A %B %-d at %-I:%M %p %Z")
        if quota["total"] >= WEEKLY_LIMIT:
            raise LimitReached(
                f"You've used all {WEEKLY_LIMIT} handoffs for this week. Your allowance resets {reset}. "
                "Until then you can arrange extra coverage outside Trade Circle."
            )
        raise LimitReached(
            f"You've already sent {PER_RECIPIENT_LIMIT} handoffs to this member this week. "
            f"Choose another member, or wait until {reset}."
        )
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Please try again.")


async def release_slot(db, handoff: dict) -> None:
    """Give a slot back when a counted proposal is declined or withdrawn."""
    if not handoff.get("counted"):
        return
    key = f"{handoff['sender_id']}:{handoff['week_start']}"
    await db.handoff_quota.update_one(
        {"_id": key, "total": {"$gt": 0}},
        {"$inc": {"total": -1, f"recipients.{handoff['recipient_id']}": -1}},
    )


async def allowance(db, user_id: str, today: date, timezone: str) -> dict:
    week = week_start(today)
    quota = await db.handoff_quota.find_one({"_id": _quota_key(user_id, week)}) or {"total": 0, "recipients": {}}
    vacation = await active_vacation(db, user_id, today)
    by_recipient = {rid: n for rid, n in quota.get("recipients", {}).items() if n > 0}
    names = {}
    if by_recipient:
        async for profile in db.profiles.find({"owner_id": {"$in": list(by_recipient)}}, {"owner_id": 1, "slug": 1, "business_name": 1}):
            names[profile["owner_id"]] = profile
    return {
        "week_start": week.isoformat(),
        "resets_at": resets_at(today, timezone).isoformat(),
        "timezone": timezone,
        "weekly_limit": WEEKLY_LIMIT,
        "per_recipient_limit": PER_RECIPIENT_LIMIT,
        "used": quota["total"],
        "remaining": max(WEEKLY_LIMIT - quota["total"], 0),
        "by_recipient": [
            {"slug": names.get(rid, {}).get("slug"), "business_name": names.get(rid, {}).get("business_name"), "count": n}
            for rid, n in by_recipient.items()
        ],
        "vacation": (
            {"id": vacation["_id"], "start_on": vacation["start_on"], "end_on": vacation["end_on"], "note": vacation["note"]}
            if vacation
            else None
        ),
        "limits_lifted": vacation is not None,
        "at_limit": vacation is None and quota["total"] >= WEEKLY_LIMIT,
    }
