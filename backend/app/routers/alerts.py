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


# What each plan's outside updates look like, in the member's words. Texts are
# capped per day by plan (tiers.SMS_DAILY_BUDGET); emails are not capped.
SMS_POLICY = {
    "free": "One weekly update email when there's something new. Texts are a paid-plan feature.",
    "starter": "One text a day: your morning rundown. New leads also arrive by email and in the app.",
    "full": "Up to two texts a day: your morning rundown, plus one more (a new lead, or an afternoon follow-up reminder). New leads also arrive by email and in the app.",
}


def _view(user: dict) -> dict:
    sms = user.get("alert_sms") or {}
    tier = user.get("tier", "free")
    return {
        "sms": {"phone": sms.get("phone"), "active": bool(sms.get("active"))},
        "email": user["email"],
        "available": tier != "free",
        "sms_policy": SMS_POLICY[tier],
        # The summary preference: the daily email summary on paid plans, the
        # weekly update email on the free plan. On unless turned off.
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
    # Every plan has a summary cadence to turn off: daily on paid, weekly on free.
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"digest_email": body.on}})
    return _view({**user, "digest_email": body.on})
