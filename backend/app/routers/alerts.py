from typing import Literal

from fastapi import APIRouter, Depends, Request, Response, status

from ..deps import get_db, now
from ..models import Phone, Strict
from ..ratelimit import client_ip
from ..security import current_user
from ..tiers import ALERTS_TIER, require_tier

router = APIRouter(prefix="/api/me/alerts", tags=["alerts"])


class SmsAlertsIn(Strict):
    phone: Phone
    # The contractor must tick the consent box; recorded for carrier (A2P 10DLC) compliance.
    consent: Literal[True]


def _view(user: dict) -> dict:
    sms = user.get("alert_sms") or {}
    return {
        "sms": {"phone": sms.get("phone"), "active": bool(sms.get("active"))},
        "email": user["email"],
        "available": user.get("tier", "free") != "free",
        # Paid plans: one daily email summary of community activity and follow-ups due. On unless turned off.
        "daily_summary": user.get("digest_email", True),
    }


@router.get("")
async def get_alerts(user: dict = Depends(current_user)):
    return _view(user)


@router.put("/sms")
async def enable_sms(body: SmsAlertsIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    require_tier(user, ALERTS_TIER, "Text alerts")
    sms = {"phone": body.phone, "active": True, "consented_at": now(), "consent_ip": client_ip(request)}
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"alert_sms": sms}})
    return _view(await db.users.find_one({"_id": user["_id"]}))


@router.delete("/sms", status_code=status.HTTP_204_NO_CONTENT)
async def disable_sms(user: dict = Depends(current_user), db=Depends(get_db)):
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"alert_sms.active": False}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class DigestIn(Strict):
    on: bool


@router.put("/digest")
async def set_digest(body: DigestIn, user: dict = Depends(current_user), db=Depends(get_db)):
    require_tier(user, ALERTS_TIER, "The daily email summary")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"digest_email": body.on}})
    return _view({**user, "digest_email": body.on})
