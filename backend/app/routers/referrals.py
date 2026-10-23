"""Referral links, the member's referral screen, and moderator payouts. Rules are in app/referrals.py."""
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field
from pymongo.errors import DuplicateKeyError

from .. import referrals
from ..deps import get_db, now
from ..models import Strict
from ..security import current_user, require_role
from .community import authors

router = APIRouter(prefix="/api", tags=["referrals"])


class PayoutIn(Strict):
    note: Annotated[str, Field(min_length=2, max_length=300)]  # how it was paid, e.g. "PayPal 10/23"


async def code_for(db, user: dict) -> str:
    if user.get("referral_code"):
        return user["referral_code"]
    for _ in range(5):
        code = referrals.new_code()
        try:
            await db.referral_codes.insert_one({"_id": code, "user_id": user["_id"]})
        except DuplicateKeyError:
            continue
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"referral_code": code}})
        return code
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Try again")


async def attach(db, new_user_id: str, code: str | None) -> None:
    """Called at signup: link the new member to whoever referred them."""
    if not code:
        return
    found = await db.referral_codes.find_one({"_id": code.strip().upper()})
    if found and found["user_id"] != new_user_id:
        await db.users.update_one({"_id": new_user_id}, {"$set": {"referred_by": found["user_id"], "referred_at": now(), "referral_first_paid_at": None}})


@router.get("/referrals")
async def mine(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    code = await code_for(db, user)
    referred = await db.users.find({"referred_by": user["_id"]}, {"tier": 1, "referred_at": 1, "referral_first_paid_at": 1}).to_list(500)
    names = await authors(db, [u["_id"] for u in referred])
    window = timedelta(days=referrals.WINDOW_DAYS)
    earnings = await db.referral_earnings.find({"referrer_id": user["_id"]}).sort("earned_at", -1).limit(100).to_list(100)
    return {
        "code": code,
        "link": f"{request.app.state.settings.public_url}/app/signup?ref={code}",
        "eligible": referrals.good_standing(user),
        "under_review": bool(user.get("referral_review")),
        "summary": await referrals.summary(db, user["_id"]),
        "referred": [
            {"business_name": names.get(u["_id"], {}).get("business_name", "A member"), "paying": u.get("tier", "free") != "free",
             "earning_until": (u["referral_first_paid_at"] + window) if u.get("referral_first_paid_at") else None, "joined": u.get("referred_at")}
            for u in referred
        ],
        "earnings": [
            {"month": e["month"], "member": names.get(e["referred_id"], {}).get("business_name", "A member"), "revenue_cents": e["revenue_cents"] - e["refunded_cents"], "share_cents": e["share_cents"], "status": e["status"], "earned_at": e["earned_at"]}
            for e in earnings
        ],
        "terms": {"share_percent": int(referrals.SHARE * 100), "months": 6, "clearing_days": referrals.CLEARING_DAYS, "review_chargebacks": referrals.REVIEW_CHARGEBACKS},
    }


@router.get("/admin/referrals")
async def overview(user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    """Referrers with something payable, frozen or under review."""
    ids = await db.referral_earnings.distinct("referrer_id")
    ids += [u["_id"] async for u in db.users.find({"referral_review": True}, {"_id": 1})]
    names = await authors(db, ids)
    rows = []
    for rid in sorted(set(ids)):
        s = await referrals.summary(db, rid)
        u = await db.users.find_one({"_id": rid}, {"referral_review": 1, "email": 1})
        rows.append({"referrer_id": rid, "business_name": names.get(rid, {}).get("business_name", "Former member"), "email": (u or {}).get("email"), "under_review": bool((u or {}).get("referral_review")), **s})
    return sorted(rows, key=lambda r: (not r["under_review"], -r["payable"]))


@router.post("/admin/referrals/{referrer_id}/payout")
async def payout(referrer_id: str, body: PayoutIn, request: Request, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    """Record a payout made outside the platform. Pays everything cleared, less any clawbacks."""
    s = await referrals.summary(db, referrer_id)
    if s["frozen"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Payouts are frozen for this member (open chargeback or review).")
    if s["payable"] <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is payable yet.")
    cutoff = now() - timedelta(days=referrals.CLEARING_DAYS)
    payout_id = uuid.uuid4().hex
    await db.referral_earnings.update_many({"referrer_id": referrer_id, "status": "pending", "earned_at": {"$lte": cutoff}}, {"$set": {"status": "paid", "payout_id": payout_id}})
    await db.referral_adjustments.update_many({"referrer_id": referrer_id, "status": "pending"}, {"$set": {"status": "applied", "payout_id": payout_id}})
    await db.referral_payouts.insert_one({"_id": payout_id, "referrer_id": referrer_id, "cents": s["payable"], "note": body.note, "by": user["_id"], "at": now()})
    request.state.audit_record = payout_id
    return {"payout_id": payout_id, "cents": s["payable"]}


@router.post("/admin/referrals/{referrer_id}/clear-review")
async def clear_review(referrer_id: str, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    result = await db.users.update_one({"_id": referrer_id, "referral_review": True}, {"$set": {"referral_review": False, "referral_review_cleared_by": user["_id"], "referral_review_cleared_at": now()}})
    if not result.matched_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not under review")
    return {"under_review": False}
