"""Outside estimates: price ranges published by other sites (cost guides, unions, suppliers), kept by the community.

Any member can add one, with a link to the public page it came from, the date
they checked it, and the range copied as the source shows it. The member who
added it can edit it. Everyone else suggests a correction (new figures, or
"remove: the source no longer shows this") with a reason; other members confirm
or dispute it, and it's applied automatically once CONFIRMATIONS_NEEDED other
members confirm and confirmations outnumber disputes. Moderators can apply or
reject any correction. Every change is kept, so anyone can see who changed what
and who confirmed it. These are always shown with their source, never blended
into our own figures.
"""
import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field, model_validator

from .. import geo
from ..deps import get_db, now, today
from ..models import TRADES, Strict
from ..notices import notify
from ..security import current_user, require_role
from .community import authors

router = APIRouter(prefix="/api/rates/estimates", tags=["rates"])

STALE_AFTER_DAYS = 180
CONFIRMATIONS_NEEDED = 2
NEARBY_MILES = 100
Money = Annotated[float, Field(ge=0, le=1_000_000)]


class EstimateIn(Strict):
    trade: Literal[TRADES]  # type: ignore[valid-type]
    service: Annotated[str, Field(min_length=3, max_length=120)]  # what the range covers, e.g. "Hourly labor rate"
    unit: Literal["hour", "project", "service_call", "square_foot", "linear_foot", "other"]
    low: Money
    high: Money
    scope: Literal["national", "state", "local"]
    location: Annotated[str, Field(max_length=80)] = ""  # ZIP or "City, ST" for local; any place in the state for state
    source_name: Annotated[str, Field(min_length=2, max_length=80)]
    source_url: Annotated[str, Field(max_length=500, pattern=r"^https://\S+$")]
    checked_on: date
    note: Annotated[str, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def _sane(self):
        if self.high < self.low:
            raise ValueError("the high end can't be below the low end")
        if self.scope != "national" and not self.location.strip():
            raise ValueError("add the ZIP or city the source gives this range for")
        return self


def _place(body: EstimateIn) -> dict | None:
    if body.scope == "national":
        return None
    place = geo.resolve(body.location)
    if body.scope == "state":
        return {"state": place.get("state"), "label": place.get("state")}
    return place


def _check_date(body: EstimateIn, request: Request) -> None:
    day = today(request)
    if body.checked_on > day:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The checked date can't be in the future.")
    if body.checked_on < day - timedelta(days=365):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only add ranges you've checked on the source in the last year.")


def _fields(body: EstimateIn) -> dict:
    data = body.model_dump(mode="json", exclude={"location"})
    data["place"] = _place(body)
    return data


def _view(doc: dict, names: dict, day: date, center: dict | None = None, viewer_id: str | None = None) -> dict:
    place = doc.get("place") or {}
    out = {k: doc[k] for k in ("trade", "service", "unit", "low", "high", "scope", "source_name", "source_url", "checked_on", "note")}
    out.update(
        id=doc["_id"],
        place={k: v for k, v in place.items() if k in ("label", "state", "zip", "city")} or None,
        stale=date.fromisoformat(doc["checked_on"]) < day - timedelta(days=STALE_AFTER_DAYS),
        added_by=names.get(doc["created_by"], {}).get("business_name", "Former member"),
        updated_by=names.get(doc.get("updated_by"), {}).get("business_name") if doc.get("updated_by") else None,
        changes=len(doc.get("revisions", [])),
        open_corrections=doc.get("open_corrections", 0),
        mine=doc["created_by"] == viewer_id,
    )
    if center and place.get("lat") is not None:
        out["distance_miles"] = round(geo.miles(center, place), 1)
    return out


@router.get("")
async def list_estimates(trade: str, request: Request, location: str = "", user: dict = Depends(current_user), db=Depends(get_db)):
    """National ranges, plus ones for the member's state and within 100 miles."""
    if trade not in TRADES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose a trade")
    center = geo.resolve(location) if location.strip() else None
    query: dict = {"trade": trade, "status": "active"}
    found = await db.outside_estimates.find(query).sort("checked_on", -1).limit(300).to_list(300)
    keep = []
    for d in found:
        place = d.get("place")
        if d["scope"] == "national":
            keep.append(d)
        elif center is None:
            continue
        elif d["scope"] == "state" and place.get("state") == center.get("state"):
            keep.append(d)
        elif d["scope"] == "local" and geo.miles(center, place) <= NEARBY_MILES:
            keep.append(d)
    order = {"local": 0, "state": 1, "national": 2}
    keep.sort(key=lambda d: (order[d["scope"]], d["service"].lower()))
    names = await authors(db, [d["created_by"] for d in keep] + [d["updated_by"] for d in keep if d.get("updated_by")])
    day = today(request)
    return {"estimates": [_view(d, names, day, center, user["_id"]) for d in keep], "stale_after_days": STALE_AFTER_DAYS}


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_estimate(body: EstimateIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    request.app.state.limiters["post"].check(f"estimate:{user['_id']}")
    _check_date(body, request)
    doc = {"_id": uuid.uuid4().hex, **_fields(body), "status": "active", "created_by": user["_id"], "created_at": now(), "revisions": []}
    await db.outside_estimates.insert_one(doc)
    request.state.audit_record = doc["_id"]
    return _view(doc, await authors(db, [user["_id"]]), today(request), viewer_id=user["_id"])


async def _apply(db, current: dict, new: dict, by: str, confirmed_by: list | None = None) -> dict | None:
    """Write a new version, keeping the old one in the revision list. None if the estimate changed meanwhile."""
    before = {k: current.get(k) for k in new}
    changed = {k: {"from": before[k], "to": v} for k, v in new.items() if before[k] != v}
    if not changed:
        return current
    revision = {"at": now(), "by": by, "changes": changed}
    if confirmed_by:
        revision["confirmed_by"] = confirmed_by
    # Only apply to the version that was seen, so two changes at once can't overwrite each other silently.
    result = await db.outside_estimates.update_one(
        {"_id": current["_id"], "status": "active", "revisions": {"$size": len(current.get("revisions", []))}},
        {"$set": {**new, "updated_by": by, "updated_at": revision["at"]}, "$push": {"revisions": revision}},
    )
    if result.matched_count == 0:
        return None
    return {**current, **new, "updated_by": by, "revisions": [*current.get("revisions", []), revision]}


@router.put("/{estimate_id}")
async def update_estimate(estimate_id: str, body: EstimateIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """The member who added an estimate (or a moderator) edits it directly. Everyone else suggests a correction."""
    request.app.state.limiters["post"].check(f"estimate:{user['_id']}")
    _check_date(body, request)
    current = await db.outside_estimates.find_one({"_id": estimate_id, "status": "active"})
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estimate not found")
    if current["created_by"] != user["_id"] and user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Suggest a correction instead: other members confirm it before it changes.")
    doc = await _apply(db, current, _fields(body), user["_id"])
    if doc is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Someone else just updated this estimate. Reload and check it again.")
    return _view(doc, await authors(db, [doc["created_by"], user["_id"]]), today(request), viewer_id=user["_id"])


@router.get("/{estimate_id}/history")
async def history(estimate_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    doc = await db.outside_estimates.find_one({"_id": estimate_id, "status": "active"})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estimate not found")
    names = await authors(db, [doc["created_by"]] + [r["by"] for r in doc.get("revisions", [])])
    rows = [{"at": doc["created_at"], "by": names.get(doc["created_by"], {}).get("business_name", "Former member"), "action": "added", "changes": {}}]
    names |= await authors(db, [c for r in doc.get("revisions", []) for c in r.get("confirmed_by", [])])
    rows += [
        {"at": r["at"], "by": names.get(r["by"], {}).get("business_name", "Former member"), "action": "updated" if not r.get("confirmed_by") else "corrected",
         "confirmed_by": [names.get(c, {}).get("business_name", "Former member") for c in r.get("confirmed_by", [])],
         "changes": {k: v for k, v in r["changes"].items() if k != "place"}}
        for r in doc.get("revisions", [])
    ]
    return rows


# --- community corrections ---


class CorrectionIn(Strict):
    kind: Literal["change", "remove"]
    proposed: EstimateIn | None = None  # the full corrected estimate, for a change
    reason: Annotated[str, Field(min_length=5, max_length=500)]

    @model_validator(mode="after")
    def _shape(self):
        if self.kind == "change" and self.proposed is None:
            raise ValueError("include the corrected figures")
        if self.kind == "remove" and self.proposed is not None:
            raise ValueError("a removal doesn't take new figures")
        return self


class VoteIn(Strict):
    vote: Literal["confirm", "dispute"]
    note: Annotated[str, Field(max_length=300)] = ""


def _tally(c: dict) -> tuple[int, int]:
    votes = c.get("votes", {}).values()
    return sum(v["vote"] == "confirm" for v in votes), sum(v["vote"] == "dispute" for v in votes)


async def _correction_views(db, corrections: list, viewer_id: str) -> list:
    estimates = {e["_id"]: e async for e in db.outside_estimates.find({"_id": {"$in": [c["estimate_id"] for c in corrections]}})}
    ids = [c["proposer_id"] for c in corrections] + [u for c in corrections for u in c.get("votes", {})]
    names = await authors(db, ids)
    out = []
    for c in corrections:
        est = estimates.get(c["estimate_id"])
        if est is None:
            continue
        confirms, disputes = _tally(c)
        changes = {}
        if c["kind"] == "change":
            changes = {k: {"from": est.get(k), "to": v} for k, v in c["proposed"].items() if k != "place" and est.get(k) != v}
            if c["proposed"].get("place") != est.get("place"):
                changes["area"] = {"from": (est.get("place") or {}).get("label", "National"), "to": (c["proposed"].get("place") or {}).get("label", "National")}
        out.append({
            "id": c["_id"],
            "estimate": {"id": est["_id"], "service": est["service"], "trade": est["trade"], "source_name": est["source_name"], "source_url": est["source_url"]},
            "kind": c["kind"],
            "changes": changes,
            "reason": c["reason"],
            "status": c["status"],
            "proposed_by": names.get(c["proposer_id"], {}).get("business_name", "Former member"),
            "mine": c["proposer_id"] == viewer_id,
            "my_vote": c.get("votes", {}).get(viewer_id, {}).get("vote"),
            "confirms": confirms,
            "disputes": disputes,
            "needed": CONFIRMATIONS_NEEDED,
            "notes": [{"by": names.get(u, {}).get("business_name", "Former member"), "vote": v["vote"], "note": v["note"]} for u, v in c.get("votes", {}).items() if v.get("note")],
            "created_at": c["created_at"],
        })
    return out


async def _count_open(db, estimate_id: str) -> None:
    n = await db.estimate_corrections.count_documents({"estimate_id": estimate_id, "status": "open"})
    await db.outside_estimates.update_one({"_id": estimate_id}, {"$set": {"open_corrections": n}})


@router.post("/{estimate_id}/corrections", status_code=status.HTTP_201_CREATED)
async def suggest(estimate_id: str, body: CorrectionIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    request.app.state.limiters["post"].check(f"estimate:{user['_id']}")
    current = await db.outside_estimates.find_one({"_id": estimate_id, "status": "active"})
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Estimate not found")
    proposed = None
    if body.proposed is not None:
        if body.proposed.trade != current["trade"]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A correction can't move an estimate to another trade. Add a new one instead.")
        _check_date(body.proposed, request)
        proposed = _fields(body.proposed)
        if all(current.get(k) == v for k, v in proposed.items()):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That's the same as what's listed now.")
    if await db.estimate_corrections.find_one({"estimate_id": estimate_id, "proposer_id": user["_id"], "status": "open"}, {"_id": 1}):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have an open correction on this estimate. Withdraw it to suggest a different one.")
    doc = {
        "_id": uuid.uuid4().hex, "estimate_id": estimate_id, "proposer_id": user["_id"], "kind": body.kind, "proposed": proposed, "reason": body.reason,
        "status": "open", "votes": {}, "base_revisions": len(current.get("revisions", [])), "created_at": now(),
    }
    await db.estimate_corrections.insert_one(doc)
    await _count_open(db, estimate_id)
    if current["created_by"] != user["_id"]:
        await notify(db, current["created_by"], "estimate", f"A member suggested a correction to \"{current['service']}\" that you added.", "/rates")
    request.state.audit_record = doc["_id"]
    return (await _correction_views(db, [doc], user["_id"]))[0]


@router.get("/{estimate_id}/corrections")
async def corrections_for(estimate_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    found = await db.estimate_corrections.find({"estimate_id": estimate_id}).sort("created_at", -1).limit(50).to_list(50)
    return await _correction_views(db, found, user["_id"])


@router.get("/corrections/open")
async def open_corrections(trade: str, request: Request, location: str = "", user: dict = Depends(current_user), db=Depends(get_db)):
    """The community corrections section: open suggestions on the estimates this member can see."""
    visible = await list_estimates(trade, request, location, user, db)
    ids = [e["id"] for e in visible["estimates"]]
    found = await db.estimate_corrections.find({"estimate_id": {"$in": ids}, "status": "open"}).sort("created_at", 1).limit(100).to_list(100)
    return await _correction_views(db, found, user["_id"])


async def _resolve(db, c: dict, outcome: str, by: str, confirmed_by: list | None = None) -> str:
    """Apply or reject a correction. Returns the final status."""
    current = await db.outside_estimates.find_one({"_id": c["estimate_id"], "status": "active"})
    if outcome == "apply" and current is not None:
        if len(current.get("revisions", [])) != c["base_revisions"]:
            outcome = "superseded"  # the estimate changed after this was suggested; it no longer applies cleanly
        elif c["kind"] == "remove":
            revision = {"at": now(), "by": c["proposer_id"], "changes": {"status": {"from": "active", "to": "retired"}}, "confirmed_by": confirmed_by or [by]}
            await db.outside_estimates.update_one({"_id": current["_id"]}, {"$set": {"status": "retired", "retired_reason": c["reason"]}, "$push": {"revisions": revision}})
        elif await _apply(db, current, c["proposed"], c["proposer_id"], confirmed_by or [by]) is None:
            outcome = "superseded"
    final = {"apply": "applied", "reject": "rejected", "superseded": "superseded"}[outcome] if current is not None else "superseded"
    result = await db.estimate_corrections.update_one({"_id": c["_id"], "status": "open"}, {"$set": {"status": final, "resolved_at": now(), "resolved_by": by}})
    if result.modified_count:
        await _count_open(db, c["estimate_id"])
        if final == "applied":
            # Other open suggestions were made against the old version.
            await db.estimate_corrections.update_many({"estimate_id": c["estimate_id"], "status": "open"}, {"$set": {"status": "superseded", "resolved_at": now()}})
            await _count_open(db, c["estimate_id"])
        words = {"applied": "was confirmed and applied", "rejected": "wasn't accepted", "superseded": "no longer applies because the estimate changed"}[final]
        await notify(db, c["proposer_id"], "estimate", f"Your correction {words}.", "/rates")
    return final


@router.post("/corrections/{correction_id}/vote")
async def vote(correction_id: str, body: VoteIn, user: dict = Depends(current_user), db=Depends(get_db)):
    """Confirm (you checked the source and it's right) or dispute. You can change your vote while it's open."""
    c = await db.estimate_corrections.find_one({"_id": correction_id, "status": "open"})
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That correction isn't open")
    if c["proposer_id"] == user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Other members confirm your correction.")
    c = await db.estimate_corrections.find_one_and_update(
        {"_id": correction_id, "status": "open"},
        {"$set": {f"votes.{user['_id']}": {"vote": body.vote, "note": body.note.strip(), "at": now()}}},
        return_document=True,
    )
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That correction isn't open")
    confirms, disputes = _tally(c)
    if confirms >= CONFIRMATIONS_NEEDED and confirms > disputes:
        confirmers = [u for u, v in c["votes"].items() if v["vote"] == "confirm"]
        c["status"] = await _resolve(db, c, "apply", user["_id"], confirmers)
    return (await _correction_views(db, [c], user["_id"]))[0]


@router.post("/corrections/{correction_id}/withdraw")
async def withdraw(correction_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    c = await db.estimate_corrections.find_one_and_update({"_id": correction_id, "proposer_id": user["_id"], "status": "open"}, {"$set": {"status": "withdrawn", "resolved_at": now()}})
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No open correction of yours")
    await _count_open(db, c["estimate_id"])
    return {"status": "withdrawn"}


@router.post("/corrections/{correction_id}/{action}")
async def moderate(correction_id: str, action: Literal["apply", "reject"], user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    c = await db.estimate_corrections.find_one({"_id": correction_id, "status": "open"})
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That correction isn't open")
    return {"status": await _resolve(db, c, action, user["_id"])}
