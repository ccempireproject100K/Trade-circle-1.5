import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ..deps import get_db, now, public_doc, today
from ..models import QuoteIn, QuoteUpdate, TrackerEntryIn
from ..notify import queue_lead_alert
from ..ratelimit import client_ip
from ..security import current_user
from ..team import acting_for
from .profiles import published_profile

router = APIRouter(prefix="/api", tags=["quotes"])

ACCEPTED = {"status": "received"}


@router.post("/p/{slug}/quote", status_code=status.HTTP_202_ACCEPTED)
async def request_quote(slug: str, body: QuoteIn, request: Request, db=Depends(get_db)):
    limiters = request.app.state.limiters
    limiters["quote"].check(f"ip:{client_ip(request)}")
    profile = await published_profile(db, slug)
    # Caps one contractor's inbox even when a flood comes from many addresses.
    limiters["quote_profile"].check(f"profile:{profile['_id']}")
    if body.website:
        # Honeypot tripped: answer like a success so the bot learns nothing.
        return ACCEPTED
    quote = {
        "_id": uuid.uuid4().hex,
        "owner_id": profile["owner_id"],
        "profile_id": profile["_id"],
        **body.model_dump(mode="json", exclude={"website"}),
        "source": "trade_circle",
        "status": "waiting",
        "notes": "",
        "follow_up_on": None,
        "created_at": now(),
    }
    await db.quotes.insert_one(quote)
    await queue_lead_alert(db, profile["owner_id"], quote, request.app.state.settings.public_url, day=today(request).isoformat())
    request.state.audit_record = quote["_id"]
    return ACCEPTED


OPEN = ["waiting", "followed_up"]


def _entry(q: dict) -> dict:
    view = public_doc(q)
    view.setdefault("source", "trade_circle")
    view.setdefault("notes", "")
    view.setdefault("follow_up_on", None)
    return view


@router.get("/inbox")
async def inbox(request: Request, view: str = "all", user: dict = Depends(acting_for("follow_ups")), db=Depends(get_db)):
    """The private follow-up tracker. Only the owner ever sees these entries.

    view: all (newest first), upcoming (follow-up today or later), overdue (follow-up date passed).
    """
    query: dict = {"owner_id": user["_id"]}
    day = today(request).isoformat()
    if view == "upcoming":
        query.update(status={"$in": OPEN}, follow_up_on={"$gte": day})
    elif view == "overdue":
        query.update(status={"$in": OPEN}, follow_up_on={"$lt": day, "$ne": None})
    sort = [("follow_up_on", 1)] if view in ("upcoming", "overdue") else [("created_at", -1)]
    entries = await db.quotes.find(query).sort(sort).to_list(500)
    return [_entry(q) for q in entries]


@router.post("/inbox", status_code=status.HTTP_201_CREATED)
async def add_entry(body: TrackerEntryIn, request: Request, user: dict = Depends(acting_for("follow_ups")), db=Depends(get_db)):
    """Add an inquiry that came by phone, text or in person. Adding one never sends an alert."""
    entry = {
        "_id": uuid.uuid4().hex,
        "owner_id": user["_id"],
        "source": "manual",
        **body.model_dump(mode="json"),
        "message": "",
        "created_at": now(),
    }
    await db.quotes.insert_one(entry)
    request.state.audit_record = entry["_id"]
    return _entry(entry)


@router.patch("/inbox/{quote_id}")
async def update_quote(quote_id: str, body: QuoteUpdate, user: dict = Depends(acting_for("follow_ups")), db=Depends(get_db)):
    entry = await db.quotes.find_one({"_id": quote_id, "owner_id": user["_id"]})
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    sent = body.model_dump(mode="json", exclude_unset=True)
    contact = {k for k in ("name", "phone", "email") if k in sent}
    if contact and entry.get("source", "trade_circle") != "manual":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Contact details from a customer's request can't be edited. Add notes instead.")
    if sent.get("status") is None:
        sent.pop("status", None)
    if "name" in sent and sent["name"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A name is required.")
    sent["updated_at"] = now()
    await db.quotes.update_one({"_id": quote_id, "owner_id": user["_id"]}, {"$set": sent})
    return _entry({**entry, **sent})


@router.delete("/inbox/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(quote_id: str, user: dict = Depends(acting_for("follow_ups")), db=Depends(get_db)):
    """Entries added by hand can be deleted; customer requests stay on record and can be closed instead."""
    result = await db.quotes.delete_one({"_id": quote_id, "owner_id": user["_id"], "source": "manual"})
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found, or it's a customer request (close it instead).")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
