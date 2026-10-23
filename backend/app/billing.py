"""Subscription billing: keeps each member's plan in step with their Stripe subscription.

Stripe is the source of truth. Checkout and plan changes start in Trade Circle,
but a member's plan only changes when Stripe reports the subscription's state
(through a signed webhook, or the response to a change we just made):

- active or trialing: the plan they pay for.
- past_due: Stripe is retrying a failed payment. They keep the plan and see a
  notice to update their card.
- canceled, unpaid, incomplete_expired: back to Free. Their data stays; paid
  features stop (alerts aren't sent, time tracking becomes read-only).
- cancel_at_period_end: they keep the plan until the period ends.

Events can arrive out of order, so an event older than the last one applied
for that member is ignored.
"""
import logging

from .deps import now

log = logging.getLogger("trade_circle.billing")

KEEPS_PLAN = {"active", "trialing", "past_due"}
ENDS_PLAN = {"canceled", "unpaid", "incomplete_expired"}


def price_plans(settings) -> dict:
    return {p: k for k, p in (("starter", settings.stripe_price_starter), ("full", settings.stripe_price_full)) if p}


def ready(settings) -> bool:
    return bool(settings.stripe_secret_key and settings.stripe_webhook_secret and settings.stripe_price_starter and settings.stripe_price_full)


def stripe_client(app):
    from .stripe_api import Stripe

    return Stripe(app.state.settings.stripe_secret_key, getattr(app.state, "stripe_transport", None))


async def _user_for(db, sub: dict) -> dict | None:
    user_id = (sub.get("metadata") or {}).get("user_id")
    if user_id:
        user = await db.users.find_one({"_id": user_id})
        if user:
            return user
    return await db.users.find_one({"billing.customer_id": sub.get("customer")})


async def apply_subscription(db, settings, sub: dict, event_created: int) -> str | None:
    """Update a member's plan from a Stripe subscription object. Returns the plan they're on afterwards."""
    user = await _user_for(db, sub)
    if user is None:
        log.warning("subscription %s for unknown customer %s", sub.get("id"), sub.get("customer"))
        return None
    billing = user.get("billing") or {}
    if billing.get("event_at", 0) > event_created:
        return user.get("tier")  # a newer event already applied
    if billing.get("subscription_id") and billing["subscription_id"] != sub["id"] and sub["status"] in ENDS_PLAN:
        return user.get("tier")  # an old subscription ending doesn't touch the current one
    items = (sub.get("items") or {}).get("data") or []
    plan = price_plans(settings).get(items[0]["price"]["id"]) if items else None
    status = sub["status"]
    if status in KEEPS_PLAN and plan:
        tier = plan
    elif status in ENDS_PLAN:
        tier = "free"
    else:
        tier = user.get("tier", "free")  # incomplete: wait for the first payment to go through
    update = {
        "tier": tier,
        "billing.customer_id": sub.get("customer"),
        "billing.subscription_id": sub["id"] if status not in ENDS_PLAN else None,
        "billing.status": status,
        "billing.plan": plan if status not in ENDS_PLAN else None,
        "billing.current_period_end": sub.get("current_period_end") or (items[0].get("current_period_end") if items else None),
        "billing.cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
        "billing.payment_problem": status == "past_due",
        "billing.event_at": event_created,
        "billing.updated_at": now(),
    }
    await db.users.update_one({"_id": user["_id"]}, {"$set": update})
    if tier != user.get("tier"):
        log.info("plan %s -> %s for %s (%s)", user.get("tier"), tier, user["_id"], status)
    return tier


async def handle_event(db, settings, event: dict) -> None:
    kind, obj = event["type"], event["data"]["object"]
    if kind in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        await apply_subscription(db, settings, obj, event["created"])
    elif kind == "checkout.session.completed" and obj.get("mode") == "subscription":
        user_id = obj.get("client_reference_id")
        if user_id:
            await db.users.update_one({"_id": user_id}, {"$set": {"billing.customer_id": obj.get("customer")}})
    elif kind == "invoice.payment_failed":
        await db.users.update_one({"billing.customer_id": obj.get("customer")}, {"$set": {"billing.payment_problem": True}})
    elif kind == "invoice.paid":
        await db.users.update_one({"billing.customer_id": obj.get("customer")}, {"$set": {"billing.payment_problem": False}})
