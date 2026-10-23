"""Referral program (the Mind At Ease plan).

- Every member has a referral link. A member who signs up through it is linked
  to the referrer.
- The referrer earns 25% of what each referred member actually pays for their
  subscription, for 6 months from that member's first payment.
- Only members in good standing earn: on a paid plan, no failed payment, not
  frozen. Earnings missed for that reason are recorded as "not eligible".
- Payouts are on net revenue only: refunds reduce the earning, and an earning
  becomes payable only after CLEARING_DAYS, once refunds and disputes have had
  time to show up.
- Chargeback: that month's earnings for the referrer are clawed back (withheld,
  or charged back against the next payout if already paid) and all their
  payouts freeze until the dispute is resolved. A won dispute releases the
  freeze and the month's earnings; a lost one keeps them clawed back.
- 3 chargebacks within 6 months flags the referrer for manual review, which
  also holds payouts until a moderator clears it.
Payouts are made outside the platform and recorded by a moderator.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from .deps import now

SHARE = 0.25
WINDOW_DAYS = 183  # about 6 months
CLEARING_DAYS = 60
REVIEW_CHARGEBACKS = 3
REVIEW_WINDOW_DAYS = 183
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def good_standing(user: dict) -> bool:
    b = user.get("billing") or {}
    return user.get("tier", "free") != "free" and not b.get("payment_problem") and not user.get("disabled")


def _when(obj: dict) -> datetime:
    ts = (obj.get("status_transitions") or {}).get("paid_at") or obj.get("created")
    return datetime.fromtimestamp(ts, timezone.utc) if ts else now()


async def frozen(db, referrer_id: str) -> bool:
    if await db.referral_disputes.find_one({"referrer_id": referrer_id, "status": "open"}, {"_id": 1}):
        return True
    user = await db.users.find_one({"_id": referrer_id}, {"referral_review": 1})
    return bool(user and user.get("referral_review"))


async def _on_invoice_paid(db, invoice: dict) -> None:
    amount = int(invoice.get("amount_paid") or 0)
    if amount <= 0:
        return
    member = await db.users.find_one({"billing.customer_id": invoice.get("customer")})
    if not member or not member.get("referred_by"):
        return
    paid_at = _when(invoice)
    first = member.get("referral_first_paid_at")
    if first is None:
        first = paid_at
        await db.users.update_one({"_id": member["_id"], "referral_first_paid_at": None}, {"$set": {"referral_first_paid_at": paid_at}})
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if paid_at > first + timedelta(days=WINDOW_DAYS):
        return  # the 6 months are over
    referrer = await db.users.find_one({"_id": member["referred_by"]})
    eligible = referrer is not None and good_standing(referrer)
    try:
        await db.referral_earnings.insert_one({
            "_id": f"inv:{invoice['id']}",  # one earning per invoice, however often Stripe sends it
            "referrer_id": member["referred_by"],
            "referred_id": member["_id"],
            "invoice_id": invoice["id"],
            "charge": invoice.get("charge"),
            "payment_intent": invoice.get("payment_intent"),
            "revenue_cents": amount,
            "refunded_cents": 0,
            "share_cents": round(amount * SHARE) if eligible else 0,
            "status": "pending" if eligible else "not_eligible",
            "month": paid_at.strftime("%Y-%m"),
            "earned_at": paid_at,
        })
    except Exception as exc:  # duplicate invoice: already counted
        if "duplicate" not in str(exc).lower():
            raise


def _match(obj: dict, charge_field: str = "id") -> dict:
    ors = []
    if obj.get(charge_field):
        ors.append({"charge": obj[charge_field]})
    if obj.get("payment_intent"):
        ors.append({"payment_intent": obj["payment_intent"]})
    return {"$or": ors} if ors else {"_id": None}


async def _on_refund(db, charge: dict) -> None:
    async for e in db.referral_earnings.find(_match(charge)):
        refunded = int(charge.get("amount_refunded") or 0)
        net = max(0, e["revenue_cents"] - refunded)
        share = round(net * SHARE) if e["status"] != "not_eligible" else 0
        await db.referral_earnings.update_one({"_id": e["_id"]}, {"$set": {"refunded_cents": refunded, "share_cents": share}})


async def _on_dispute(db, dispute: dict, opened: bool) -> None:
    earning = await db.referral_earnings.find_one(_match(dispute, "charge"))
    if earning is None:
        return
    referrer = earning["referrer_id"]
    if opened:
        await db.referral_disputes.update_one(
            {"_id": dispute["id"]},
            {"$setOnInsert": {"referrer_id": referrer, "earning_id": earning["_id"], "month": earning["month"], "status": "open", "opened_at": now()}},
            upsert=True,
        )
        # Claw back the month: unpaid earnings are withheld; paid ones come off the next payout.
        async for e in db.referral_earnings.find({"referrer_id": referrer, "month": earning["month"], "status": {"$in": ["pending", "paid"]}}):
            await db.referral_earnings.update_one({"_id": e["_id"]}, {"$set": {"status": "clawed_back", "was": e["status"], "clawed_by": dispute["id"]}})
            if e["status"] == "paid":
                await db.referral_adjustments.insert_one({"_id": uuid.uuid4().hex, "referrer_id": referrer, "cents": -e["share_cents"], "reason": f"Chargeback in {e['month']}", "dispute": dispute["id"], "status": "pending", "at": now()})
        since = now() - timedelta(days=REVIEW_WINDOW_DAYS)
        if await db.referral_disputes.count_documents({"referrer_id": referrer, "opened_at": {"$gte": since}}) >= REVIEW_CHARGEBACKS:
            await db.users.update_one({"_id": referrer}, {"$set": {"referral_review": True, "referral_review_at": now()}})
        return
    won = dispute.get("status") == "won"
    result = await db.referral_disputes.update_one({"_id": dispute["id"], "status": "open"}, {"$set": {"status": "won" if won else "lost", "closed_at": now()}})
    if not result.modified_count or not won:
        return
    # Won: the month's earnings are released (and any charge-back against a paid payout is dropped).
    async for e in db.referral_earnings.find({"clawed_by": dispute["id"], "status": "clawed_back"}):
        await db.referral_earnings.update_one({"_id": e["_id"]}, {"$set": {"status": e.get("was", "pending")}, "$unset": {"clawed_by": "", "was": ""}})
    await db.referral_adjustments.update_many({"dispute": dispute["id"], "status": "pending"}, {"$set": {"status": "cancelled"}})


async def handle_event(db, settings, event: dict) -> None:
    kind, obj = event["type"], event["data"]["object"]
    if kind == "invoice.paid":
        await _on_invoice_paid(db, obj)
    elif kind == "charge.refunded":
        await _on_refund(db, obj)
    elif kind == "charge.dispute.created":
        await _on_dispute(db, obj, True)
    elif kind == "charge.dispute.closed":
        await _on_dispute(db, obj, False)


async def summary(db, referrer_id: str) -> dict:
    cutoff = now() - timedelta(days=CLEARING_DAYS)
    totals = {"pending": 0, "available": 0, "paid": 0, "clawed_back": 0}
    async for e in db.referral_earnings.find({"referrer_id": referrer_id}):
        earned = e["earned_at"] if e["earned_at"].tzinfo else e["earned_at"].replace(tzinfo=timezone.utc)
        if e["status"] == "pending":
            totals["available" if earned <= cutoff else "pending"] += e["share_cents"]
        elif e["status"] in ("paid", "clawed_back"):
            totals[e["status"]] += e["share_cents"]
    adjust = sum([a["cents"] async for a in db.referral_adjustments.find({"referrer_id": referrer_id, "status": "pending"})])
    is_frozen = await frozen(db, referrer_id)
    return {**totals, "adjustments": adjust, "payable": 0 if is_frozen else max(0, totals["available"] + adjust), "frozen": is_frozen, "clearing_days": CLEARING_DAYS}
