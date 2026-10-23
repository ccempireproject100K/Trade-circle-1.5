"""Private rate submissions and aggregated comparisons. Rules are in app/rates.py."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .. import geo, wages
from ..deps import get_db, now, today
from ..models import TRADES
from ..rates import BENEFITS, EXPERIENCE, MIN_AGE_DAYS, MIN_CONTRIBUTORS, ROLES, SubmissionIn, aggregate, cutoff
from ..security import current_user

router = APIRouter(prefix="/api/rates", tags=["rates"])


@router.get("/meta")
async def meta(request: Request):
    return {
        "trades": list(TRADES),
        "roles": list(ROLES),
        "experience": list(EXPERIENCE),
        "benefits": list(BENEFITS),
        "min_contributors": MIN_CONTRIBUTORS,
        "min_age_days": MIN_AGE_DAYS,
        "published": request.app.state.settings.rate_comparisons,
    }


def _own_view(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k not in ("_id", "contributor_id")}
    out["id"] = doc["_id"]
    return out


@router.put("/mine")
async def submit(body: SubmissionIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Save your figures. One submission per kind, trade and state; a new one replaces the old."""
    place = geo.resolve(body.location)
    if not place.get("state"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "We couldn't tell which state that is. Try a ZIP code.")
    data = body.model_dump(exclude={"location"})
    key = f"{user['_id']}:{body.kind}:{body.trade}:{place['state']}"
    doc = {**data, "contributor_id": user["_id"], "state": place["state"], "submitted_on": today(request).isoformat(), "updated_at": now()}
    await db.rate_submissions.replace_one({"_id": key}, {"_id": key, **doc}, upsert=True)
    return _own_view({"_id": key, **doc})


@router.get("/mine")
async def mine(user: dict = Depends(current_user), db=Depends(get_db)):
    return [_own_view(d) async for d in db.rate_submissions.find({"contributor_id": user["_id"]}).sort("updated_at", -1)]


@router.delete("/mine/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw(submission_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    result = await db.rate_submissions.delete_one({"_id": submission_id, "contributor_id": user["_id"]})
    if not result.deleted_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/government")
async def government(trade: str, location: str, user: dict = Depends(current_user)):
    """Employee wages for a trade near a ZIP or city, from the BLS survey. Available now: no review needed."""
    if trade not in TRADES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose a trade")
    return wages.lookup(geo.resolve(location), trade)


@router.get("/compare")
async def compare(kind: str, trade: str, request: Request, state: str = "", location: str = "", role: str = "", user: dict = Depends(current_user), db=Depends(get_db)):
    if location.strip() and not state:
        state = geo.resolve(location).get("state") or ""
    if kind not in ("wage", "billing") or trade not in TRADES or state.upper() not in geo.STATES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose a comparison, a trade and a state.")
    state = state.upper()
    group = {"kind": kind, "trade": trade, "state": state, "area": f"{state} (statewide)"}
    if kind == "wage" and role:
        if role not in ROLES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown role")
        group["role"] = role
    if not request.app.state.settings.rate_comparisons:
        return {**group, "published": False}
    query = {"kind": kind, "trade": trade, "state": state, "submitted_on": {"$lte": cutoff(today(request))}}
    if group.get("role"):
        query["role"] = role
    rows = await db.rate_submissions.find(query, {"contributor_id": 0}).to_list(5000)
    return {**group, "published": True, **aggregate(rows, kind)}
