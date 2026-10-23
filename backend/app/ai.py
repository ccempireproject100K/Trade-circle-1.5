"""Allowances and spending limits for paid AI features (the contractor helper and photo part lookup).

Nothing here calls a provider until the owner configures a model, its current
prices and a monthly budget. Every request then goes through the same steps:

1. Take one of the member's allowance slots (per day and per calendar month,
   in Settings.timezone). Counters are changed atomically, so simultaneous
   requests can't go over.
2. Reserve the most the request could cost from the shared monthly budget.
   If the budget can't cover it, release the member's slot and stop.
3. Call the provider with bounded input, output and retries, and no tools.
4. Reconcile: replace the reservation with the actual cost from the provider's
   usage report. A failed request gives the member's slot back, but whatever
   the provider charged still counts against the budget.

Only counts, token usage and cost are stored. Questions and answers aren't.
"""
import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .deps import now

log = logging.getLogger("trade_circle.ai")

# Rough characters per token, set low on purpose so reservations are never too small.
CHARS_PER_TOKEN = 2
# Image input is billed by size; this is a generous bound for one resized photo.
IMAGE_TOKENS = 5000


@dataclass(frozen=True)
class Feature:
    key: str  # "helper" or "parts"
    model: str
    input_price: float  # USD per million input tokens
    output_price: float  # USD per million output tokens
    monthly_budget: float  # USD shared by all members
    daily_limit: int
    monthly_limit: int
    max_output_tokens: int

    @property
    def ready(self) -> bool:
        return bool(self.model and self.input_price > 0 and self.output_price > 0 and self.monthly_budget > 0 and self.daily_limit > 0 and self.monthly_limit > 0)

    def cost_micros(self, input_tokens: int, output_tokens: int) -> int:
        """Cost in millionths of a dollar, rounded up."""
        return math.ceil(input_tokens * self.input_price + output_tokens * self.output_price)


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


class ProviderFailed(Exception):
    """The provider didn't produce a usable answer. `usage` is set when it reported what it charged;
    `unknown_cost` when it may have charged but we can't tell (a timeout)."""

    def __init__(self, message: str, usage: Usage | None = None, unknown_cost: bool = False):
        super().__init__(message)
        self.usage = usage
        self.unknown_cost = unknown_cost


# --- reset dates ---


def next_day(today: date) -> date:
    return today + timedelta(days=1)


def next_month(today: date) -> date:
    return date(today.year + (today.month == 12), today.month % 12 + 1, 1)


# --- member allowance ---


async def _take(db, key: str, limit: int) -> bool:
    try:
        doc = await db.ai_allowance.find_one_and_update(
            {"_id": key, "count": {"$lt": limit}}, {"$inc": {"count": 1}, "$set": {"updated_at": now()}}, upsert=True, return_document=ReturnDocument.AFTER
        )
    except DuplicateKeyError:
        return False  # the counter exists and is already at the limit
    return doc is not None


async def _give_back(db, key: str) -> None:
    await db.ai_allowance.update_one({"_id": key, "count": {"$gt": 0}}, {"$inc": {"count": -1}})


def _keys(feature: Feature, user_id: str, today: date) -> tuple[str, str]:
    return f"{feature.key}:{user_id}:{today.isoformat()}", f"{feature.key}:{user_id}:{today.isoformat()[:7]}"


async def allowance(db, feature: Feature, user_id: str, today: date) -> dict:
    day_key, month_key = _keys(feature, user_id, today)
    found = {d["_id"]: d["count"] async for d in db.ai_allowance.find({"_id": {"$in": [day_key, month_key]}})}
    day_left = max(0, feature.daily_limit - found.get(day_key, 0))
    month_left = max(0, feature.monthly_limit - found.get(month_key, 0))
    return {
        "daily_limit": feature.daily_limit,
        "monthly_limit": feature.monthly_limit,
        "remaining_today": min(day_left, month_left),
        "remaining_this_month": month_left,
        "day_resets_on": next_day(today).isoformat(),
        "month_resets_on": next_month(today).isoformat(),
        # When the member can ask again if they're out: the month's reset wins when the month is used up.
        "refreshes_on": (next_month(today) if month_left == 0 else next_day(today)).isoformat(),
    }


# --- shared budget ---


async def _reserve(db, feature: Feature, month: str, micros: int) -> bool:
    limit = round(feature.monthly_budget * 1_000_000)
    if micros > limit:
        return False
    try:
        doc = await db.ai_budget.find_one_and_update(
            {"_id": f"{feature.key}:{month}", "committed": {"$lte": limit - micros}},
            {"$inc": {"committed": micros}, "$setOnInsert": {"spent": 0}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return False
    return doc is not None


async def _reconcile(db, feature: Feature, month: str, reserved: int, actual: int) -> None:
    await db.ai_budget.update_one({"_id": f"{feature.key}:{month}"}, {"$inc": {"committed": actual - reserved, "spent": actual}})


async def budget_status(db, feature: Feature, today: date) -> dict:
    doc = await db.ai_budget.find_one({"_id": f"{feature.key}:{today.isoformat()[:7]}"}) or {}
    return {"budget_usd": feature.monthly_budget, "spent_usd": doc.get("spent", 0) / 1_000_000, "committed_usd": doc.get("committed", 0) / 1_000_000}


# --- running a request ---


class Refused(Exception):
    """Why a request wasn't sent. `who` is "member" (their own allowance) or "community" (shared budget or not set up)."""

    def __init__(self, who: str, message: str):
        super().__init__(message)
        self.who = who


def member_message(refreshes_on: date) -> str:
    return f"Your free AI questions refresh on {refreshes_on.strftime('%B')} {refreshes_on.day}."


def community_message(reset_on: date | None) -> str:
    if reset_on is None:
        return "Community AI is temporarily unavailable."
    return f"Community AI is temporarily unavailable. Please try again {reset_on.strftime('%B')} {reset_on.day}."


async def run(db, feature: Feature, user_id: str, today: date, input_chars: int, call, images: int = 0):
    """Run `call()` (which returns (result, Usage) or raises ProviderFailed) inside the allowance and budget."""
    if not feature.ready:
        raise Refused("community", community_message(None))
    day_key, month_key = _keys(feature, user_id, today)
    if not await _take(db, month_key, feature.monthly_limit):
        raise Refused("member", member_message(next_month(today)))
    if not await _take(db, day_key, feature.daily_limit):
        await _give_back(db, month_key)
        raise Refused("member", member_message(next_day(today)))
    month = today.isoformat()[:7]
    reserved = feature.cost_micros(input_chars // CHARS_PER_TOKEN + 1 + images * IMAGE_TOKENS, feature.max_output_tokens)
    if not await _reserve(db, feature, month, reserved):
        await _give_back(db, day_key)
        await _give_back(db, month_key)
        # The budget renews on the first of next month, so that time is known.
        raise Refused("community", community_message(next_month(today)))
    outcome, usage = "failed", None
    try:
        result, usage = await call()
        outcome = "answered"
        return result
    except ProviderFailed as exc:
        usage = exc.usage
        if exc.unknown_cost:
            outcome = "failed_unknown_cost"
        raise
    finally:
        if outcome == "answered" or usage is not None:
            actual = feature.cost_micros(usage.input_tokens, usage.output_tokens)
        else:
            # No usage report: keep the whole reservation if the provider may have charged, else nothing.
            actual = reserved if outcome == "failed_unknown_cost" else 0
        await _reconcile(db, feature, month, reserved, actual)
        if outcome != "answered":
            await _give_back(db, day_key)
            await _give_back(db, month_key)
        await db.ai_usage.insert_one(
            {"feature": feature.key, "user_id": user_id, "day": today.isoformat(), "outcome": outcome, "input_tokens": usage.input_tokens if usage else None,
             "output_tokens": usage.output_tokens if usage else None, "cost_micros": actual, "reserved_micros": reserved, "at": now()}
        )
