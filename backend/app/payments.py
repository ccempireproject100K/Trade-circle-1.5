"""Customer payments for Full-plan contractors, through Stripe Connect.

- Each contractor connects their own Stripe account using Stripe's hosted
  onboarding (a Standard account). Payments are direct charges on that
  account: money goes to the contractor's bank, Stripe's fees come out of it,
  and Trade Circle takes no cut and never holds funds or card numbers.
- A payment request has a total and a running balance kept in a ledger.
  Customers can pay in full or, if the contractor allows it, in parts. Each
  part is its own Stripe Checkout session and PaymentIntent ("slice").
- Card or bank (ACH). Bank payments take a few days to clear, so a slice
  stays "processing" until Stripe says it succeeded or failed.
- If the contractor allows it, the customer can save their card with the
  contractor for next time. The saved card lives in the contractor's Stripe
  account, linked to that customer's email.
"""
import secrets

from .deps import now
from .notices import notify
from .notify import queue_alert

OPEN = ("open", "partly_paid")


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


async def balance(db, request: dict) -> dict:
    """Paid, processing and still-due amounts from the ledger."""
    paid = processing = refunded = 0
    async for s in db.payment_slices.find({"request_id": request["_id"]}):
        if s["status"] == "succeeded":
            paid += s["amount_cents"]
            refunded += s.get("refunded_cents", 0)
        elif s["status"] == "processing":
            processing += s["amount_cents"]
    due = max(0, request["amount_cents"] - (paid - refunded) - processing)
    return {"paid_cents": paid, "refunded_cents": refunded, "processing_cents": processing, "due_cents": due}


async def refresh_status(db, request: dict) -> str:
    if request["status"] == "cancelled":
        return "cancelled"
    b = await balance(db, request)
    status = "paid" if b["due_cents"] == 0 and b["processing_cents"] == 0 else ("partly_paid" if b["paid_cents"] - b["refunded_cents"] > 0 or b["processing_cents"] > 0 else "open")
    if status != request["status"]:
        await db.payment_requests.update_one({"_id": request["_id"]}, {"$set": {"status": status, "updated_at": now()}})
    return status


def new_token() -> str:
    return secrets.token_urlsafe(24)


async def _settle(db, settings, slice_: dict, status: str, payment_intent: str | None = None, customer: str | None = None) -> None:
    update = {"status": status, "updated_at": now()}
    if payment_intent:
        update["payment_intent"] = payment_intent
    result = await db.payment_slices.update_one({"_id": slice_["_id"], "status": {"$in": ["pending", "processing"]}}, {"$set": update})
    if not result.modified_count:
        return
    request = await db.payment_requests.find_one({"_id": slice_["request_id"]})
    if request is None:
        return
    if customer and request.get("customer_email"):
        # Remember the customer on the contractor's account, so a saved card is offered next time.
        await db.payment_customers.update_one(
            {"_id": f"{request['owner_id']}:{request['customer_email']}"}, {"$set": {"stripe_customer": customer, "updated_at": now()}}, upsert=True
        )
    await refresh_status(db, request)
    if status == "succeeded":
        text = f"{request['customer_name']} paid {money(slice_['amount_cents'])} toward \"{request['description']}\"."
        await notify(db, request["owner_id"], "payment", text, "/payments")
        await queue_alert(db, request["owner_id"], kind="payment_received", subject=f"Payment received: {money(slice_['amount_cents'])}", text=text, link=f"{settings.public_url}/app/payments", record_id=slice_["_id"])
    elif status == "failed":
        await notify(db, request["owner_id"], "payment", f"A bank payment from {request['customer_name']} for {money(slice_['amount_cents'])} didn't go through.", "/payments")


async def handle_connect_event(db, settings, event: dict) -> None:
    """Events from contractors' connected accounts."""
    kind, obj = event["type"], event["data"]["object"]
    if kind == "account.updated":
        await db.users.update_one(
            {"payments.account_id": obj["id"]},
            {"$set": {"payments.charges_enabled": bool(obj.get("charges_enabled")), "payments.details_submitted": bool(obj.get("details_submitted"))}},
        )
        return
    if kind.startswith("checkout.session."):
        slice_ = await db.payment_slices.find_one({"checkout_session": obj["id"]})
        if slice_ is None or slice_.get("account_id") != event.get("account"):
            return
        if kind == "checkout.session.completed":
            # Cards are paid at once; bank payments start processing and finish days later.
            status = "succeeded" if obj.get("payment_status") == "paid" else "processing"
            if status == "processing":
                await db.payment_slices.update_one({"_id": slice_["_id"], "status": "pending"}, {"$set": {"status": "processing", "payment_intent": obj.get("payment_intent"), "updated_at": now()}})
                request = await db.payment_requests.find_one({"_id": slice_["request_id"]})
                if request:
                    await refresh_status(db, request)
            else:
                await _settle(db, settings, slice_, status, obj.get("payment_intent"), obj.get("customer"))
        elif kind == "checkout.session.async_payment_succeeded":
            await _settle(db, settings, slice_, "succeeded", obj.get("payment_intent"), obj.get("customer"))
        elif kind == "checkout.session.async_payment_failed":
            await _settle(db, settings, slice_, "failed", obj.get("payment_intent"))
        elif kind == "checkout.session.expired":
            await db.payment_slices.update_one({"_id": slice_["_id"], "status": "pending"}, {"$set": {"status": "expired", "updated_at": now()}})
        return
    if kind == "charge.refunded" and obj.get("payment_intent"):
        slice_ = await db.payment_slices.find_one({"payment_intent": obj["payment_intent"], "account_id": event.get("account")})
        if slice_:
            await db.payment_slices.update_one({"_id": slice_["_id"]}, {"$set": {"refunded_cents": int(obj.get("amount_refunded", 0)), "updated_at": now()}})
            request = await db.payment_requests.find_one({"_id": slice_["request_id"]})
            if request:
                await refresh_status(db, request)
