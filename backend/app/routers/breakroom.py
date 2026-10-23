"""The Break Room: sponsor-run giveaways and public offers, curated by moderators, plus basic usage counts.

Listings point to the organizer's own official pages. Trade Circle doesn't run
entries, pick winners, hold prizes or collect members' emails, and a listing
never implies sponsorship. Every listing carries the date someone last checked
it; expired ones disappear automatically, and offers with no published end
date are flagged for rechecking. Member suggestions are community posts
(kind "spot"), so they get replies, reporting and moderation for free.
"""
import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import Field, model_validator

from .. import geo
from ..deps import get_db, now, today
from ..models import Strict
from ..security import current_user, require_role

router = APIRouter(prefix="/api", tags=["break room"])

Url = Annotated[str, Field(max_length=500, pattern=r"^https://\S+$")]
Text = lambda n: Annotated[str, Field(max_length=n)]  # noqa: E731
RECHECK_AFTER_DAYS = 30


class ListingIn(Strict):
    kind: Literal["giveaway", "public_offer"]
    title: Annotated[str, Field(min_length=3, max_length=140)]
    organizer: Annotated[str, Field(min_length=2, max_length=120)]  # the business or sponsor running it
    official_url: Url
    details: Text(2000) = ""
    restrictions: Text(1000) = ""  # eligibility, limits, fine print
    # Giveaways
    prize: Text(300) = ""
    geography: Text(200) = ""  # where entrants must live, as the official rules say
    rules_url: Url | None = None
    # Offers: a ZIP or "City, ST" so members can filter by distance; blank for online offers
    location: Text(80) = ""
    expires_on: date | None = None  # closing date for giveaways, end date for offers
    last_checked_on: date

    @model_validator(mode="after")
    def _complete(self):
        if self.kind == "giveaway":
            missing = [name for name, value in (("prize", self.prize), ("geography", self.geography), ("official rules link", self.rules_url), ("closing date", self.expires_on)) if not value]
            if missing:
                raise ValueError(f"a giveaway needs its {', '.join(missing)}")
        return self


class UsageIn(Strict):
    event: Literal["music_opened", "music_played", "game_opened", "listing_opened", "deals_viewed", "giveaways_viewed"]
    detail: Annotated[str, Field(max_length=40, pattern=r"^[a-z0-9_-]*$")] = ""


def _view(doc: dict, center: dict | None, today_: date) -> dict:
    out = {k: v for k, v in doc.items() if k not in ("_id", "created_by", "location")}
    out["id"] = doc["_id"]
    out["location"] = {k: v for k, v in (doc.get("location") or {}).items() if k in ("label", "city", "state", "zip")} or None
    out["label"] = "Giveaway" if doc["kind"] == "giveaway" else "Public offer"
    # No published end date: show it, but mark it so a moderator rechecks it and members know.
    out["no_end_date"] = doc.get("expires_on") is None
    out["needs_recheck"] = out["no_end_date"] or date.fromisoformat(doc["last_checked_on"]) < today_ - timedelta(days=RECHECK_AFTER_DAYS)
    if center and doc.get("location"):
        out["distance_miles"] = round(geo.miles(center, doc["location"]), 1)
    return out


@router.get("/break-room/listings")
async def listings(request: Request, kind: str = "public_offer", near: str = "", radius: int = 25, user: dict = Depends(current_user), db=Depends(get_db)):
    if kind not in ("giveaway", "public_offer"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown kind")
    day = today(request)
    # Expired listings are hidden automatically: no one has to remember to take them down.
    query = {"kind": kind, "status": "active", "$or": [{"expires_on": None}, {"expires_on": {"$gte": day.isoformat()}}]}
    found = await db.break_room.find(query).sort([("expires_on", 1), ("created_at", -1)]).limit(100).to_list(100)
    center = None
    if near.strip():
        center = geo.resolve(near)
        radius = max(1, min(radius, 250))
        # Online offers (no location) still show; local ones must be within the radius.
        found = [d for d in found if not d.get("location") or geo.miles(center, d["location"]) <= radius]
    return {"near": center and {"label": center["label"], "radius": radius}, "listings": [_view(d, center, day) for d in found]}


@router.get("/admin/break-room/listings")
async def all_listings(request: Request, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    """Everything, including expired and hidden, with the ones needing a recheck first."""
    day = today(request)
    found = await db.break_room.find({"status": {"$ne": "deleted"}}).sort("last_checked_on", 1).to_list(500)
    views = [_view(d, None, day) | {"expired": bool(d.get("expires_on") and d["expires_on"] < day.isoformat())} for d in found]
    return sorted(views, key=lambda v: (not v["needs_recheck"], v["last_checked_on"]))


def _doc(body: ListingIn) -> dict:
    data = body.model_dump(mode="json", exclude={"location"})
    data["location"] = geo.resolve(body.location) if body.location.strip() else None
    return data


@router.post("/admin/break-room/listings", status_code=status.HTTP_201_CREATED)
async def add_listing(body: ListingIn, request: Request, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    if body.last_checked_on > today(request):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The last-checked date can't be in the future.")
    doc = {"_id": uuid.uuid4().hex, **_doc(body), "status": "active", "created_by": user["_id"], "created_at": now()}
    await db.break_room.insert_one(doc)
    request.state.audit_record = doc["_id"]
    return _view(doc, None, today(request))


@router.put("/admin/break-room/listings/{listing_id}")
async def update_listing(listing_id: str, body: ListingIn, request: Request, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    """Used for rechecks too: confirm the details and set a new last-checked date."""
    if body.last_checked_on > today(request):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The last-checked date can't be in the future.")
    doc = await db.break_room.find_one_and_update({"_id": listing_id, "status": {"$ne": "deleted"}}, {"$set": {**_doc(body), "updated_at": now()}}, return_document=True)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    return _view(doc, None, today(request))


@router.post("/admin/break-room/listings/{listing_id}/{action}")
async def set_status(listing_id: str, action: Literal["hide", "show", "delete"], user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    new = {"hide": "hidden", "show": "active", "delete": "deleted"}[action]
    result = await db.break_room.update_one({"_id": listing_id, "status": {"$ne": "deleted"}}, {"$set": {"status": new, "updated_at": now()}})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    return {"id": listing_id, "status": new}


# --- basic usage counts: totals per day, never who ---


@router.post("/usage", status_code=status.HTTP_204_NO_CONTENT)
async def count(body: UsageIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    key = f"{today(request).isoformat()}:{body.event}:{body.detail}"
    await db.usage_counts.update_one({"_id": key}, {"$inc": {"count": 1}, "$set": {"day": today(request).isoformat(), "event": body.event, "detail": body.detail}}, upsert=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/admin/usage")
async def usage(request: Request, days: int = 30, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    since = (today(request) - timedelta(days=max(1, min(days, 365)))).isoformat()
    totals: dict = {}
    async for row in db.usage_counts.find({"day": {"$gt": since}}):
        name = f"{row['event']}:{row['detail']}" if row["detail"] else row["event"]
        totals[name] = totals.get(name, 0) + row["count"]
    return {"since": since, "totals": dict(sorted(totals.items()))}
