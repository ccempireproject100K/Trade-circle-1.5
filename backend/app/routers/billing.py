"""Plans and subscription billing screens, and the Stripe webhook. Rules are in app/billing.py."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo.errors import DuplicateKeyError

from .. import billing, referrals, stripe_api
from ..deps import get_db, now
from ..models import Strict
from ..security import current_user
from ..tiers import PLANS, catalog

router = APIRouter(prefix="/api", tags=["billing"])
log = logging.getLogger("trade_circle.billing")

NOT_OPEN = "Paid plans aren't open yet. Billing is being set up."
# Other modules add handlers here for the events they care about (payments, referrals).
EVENT_HANDLERS = [billing.handle_event, referrals.handle_event]


class PlanIn(Strict):
    plan: Literal["starter", "full"]


class ChangeIn(Strict):
    plan: Literal["free", "starter", "full"]


@router.get("/plans")
async def plans():
    return catalog()


@router.get("/billing")
async def my_billing(request: Request, user: dict = Depends(current_user)):
    b = user.get("billing") or {}
    return {
        "ready": billing.ready(request.app.state.settings),
        "plan": user.get("tier", "free"),
        "status": b.get("status"),
        "subscribed": bool(b.get("subscription_id")),
        "current_period_end": b.get("current_period_end"),
        "cancel_at_period_end": bool(b.get("cancel_at_period_end")),
        "payment_problem": bool(b.get("payment_problem")),
        "plans": catalog(),
    }


def _require_ready(request: Request) -> None:
    if not billing.ready(request.app.state.settings):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_OPEN)


async def _customer(request: Request, db, user: dict) -> str:
    existing = (user.get("billing") or {}).get("customer_id")
    if existing:
        return existing
    customer = await billing.stripe_client(request.app).request(
        "POST", "/customers", {"email": user["email"], "metadata": {"user_id": user["_id"]}}, idempotency_key=f"customer-{user['_id']}"
    )
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"billing.customer_id": customer["id"]}})
    return customer["id"]


@router.post("/billing/checkout")
async def checkout(body: PlanIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Start a subscription on Stripe's hosted checkout page. The plan changes when Stripe confirms payment."""
    _require_ready(request)
    if (user.get("billing") or {}).get("subscription_id"):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a subscription. Change your plan instead.")
    settings = request.app.state.settings
    try:
        customer = await _customer(request, db, user)
        session = await billing.stripe_client(request.app).request("POST", "/checkout/sessions", {
            "mode": "subscription",
            "customer": customer,
            "client_reference_id": user["_id"],
            "line_items": [{"price": settings.stripe_price_starter if body.plan == "starter" else settings.stripe_price_full, "quantity": 1}],
            "subscription_data": {"metadata": {"user_id": user["_id"]}},
            "success_url": f"{settings.public_url}/app/plan?checkout=done",
            "cancel_url": f"{settings.public_url}/app/plan",
        })
    except stripe_api.StripeError as exc:
        log.warning("checkout failed for %s: %s", user["_id"], exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "We couldn't reach the payment service. Please try again.")
    return {"url": session["url"]}


@router.post("/billing/change")
async def change(body: ChangeIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Switch between Starter and Full (prorated), cancel at the end of the period, or undo a cancellation."""
    _require_ready(request)
    b = user.get("billing") or {}
    if not b.get("subscription_id"):
        raise HTTPException(status.HTTP_409_CONFLICT, "You don't have a subscription yet. Choose a plan to start one.")
    settings = request.app.state.settings
    stripe = billing.stripe_client(request.app)
    try:
        if body.plan == "free":
            sub = await stripe.request("POST", f"/subscriptions/{b['subscription_id']}", {"cancel_at_period_end": True})
        else:
            current = await stripe.request("GET", f"/subscriptions/{b['subscription_id']}")
            price = settings.stripe_price_starter if body.plan == "starter" else settings.stripe_price_full
            sub = await stripe.request("POST", f"/subscriptions/{b['subscription_id']}", {
                "items": [{"id": current["items"]["data"][0]["id"], "price": price}],
                "proration_behavior": "create_prorations",
                "cancel_at_period_end": False,
            })
    except stripe_api.StripeError as exc:
        log.warning("plan change failed for %s: %s", user["_id"], exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "We couldn't reach the payment service. Please try again.")
    # Stripe's answer is authoritative; the webhook that follows will say the same thing.
    await billing.apply_subscription(db, settings, sub, int(now().timestamp()))
    return await my_billing(request, await db.users.find_one({"_id": user["_id"]}))


@router.post("/billing/portal")
async def portal(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Stripe's hosted page for card details, invoices and receipts."""
    _require_ready(request)
    customer = (user.get("billing") or {}).get("customer_id")
    if not customer:
        raise HTTPException(status.HTTP_409_CONFLICT, "There's no billing account yet.")
    try:
        session = await billing.stripe_client(request.app).request("POST", "/billing_portal/sessions", {"customer": customer, "return_url": f"{request.app.state.settings.public_url}/app/plan"})
    except stripe_api.StripeError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "We couldn't reach the payment service. Please try again.")
    return {"url": session["url"]}


async def _receive(request: Request, secret: str, handlers: list) -> dict:
    payload = await request.body()
    try:
        event = stripe_api.verify(payload, request.headers.get("stripe-signature"), secret)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid signature: {exc}")
    db = request.app.state.db
    # Stripe may send an event more than once; each is handled once.
    try:
        await db.stripe_events.insert_one({"_id": event["id"], "type": event["type"], "account": event.get("account"), "received_at": now()})
    except DuplicateKeyError:
        return {"received": True, "duplicate": True}
    try:
        for handler in handlers:
            await handler(db, request.app.state.settings, event)
    except Exception:
        # Forget it so Stripe's retry is processed.
        await db.stripe_events.delete_one({"_id": event["id"]})
        log.exception("stripe event %s failed", event["id"])
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Event not processed")
    return {"received": True}


@router.post("/stripe/webhook", include_in_schema=False)
async def webhook(request: Request):
    return await _receive(request, request.app.state.settings.stripe_webhook_secret, EVENT_HANDLERS)
