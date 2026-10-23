import re
import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import EmailStr, Field, HttpUrl, field_validator

from .. import geo
from .. import suppliers as rules
from ..community import SUPPLY_CATEGORIES, Kind
from ..deps import get_db, now
from ..models import Strict, _check_trade, _https_only
from ..ratelimit import client_ip
from ..security import current_user, require_role
from .community import flag_for_review, shape

router = APIRouter(prefix="/api", tags=["suppliers"])

DEFAULT_RADIUS = 25
EXPERIENCE_KINDS = [Kind.supplier_review.value, Kind.supply_question.value]


class LocationIn(Strict):
    place: Annotated[str, Field(min_length=3, max_length=80)]  # ZIP or "City, ST"
    address: Annotated[str, Field(max_length=200)] = ""


class SourceIn(Strict):
    url: HttpUrl
    method: Annotated[str, Field(min_length=5, max_length=200)]
    checked_on: date


class SupplierIn(Strict):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    website: HttpUrl | None = None
    offers: Annotated[str, Field(max_length=1000)] = ""
    categories: list[str] = Field(min_length=1, max_length=8)
    trades: list[str] = Field(default_factory=list, max_length=8)
    coverage: Literal["multi_branch", "local"] = "local"
    branch_note: Annotated[str, Field(max_length=300)] = ""
    locations: list[LocationIn] = Field(default_factory=list, max_length=20)
    delivery: Annotated[str, Field(max_length=300)] = "unknown"
    business_account: Annotated[str, Field(max_length=300)] = "unknown"
    ships_to: Literal["unknown", "nationwide"] | list[str] = "unknown"
    # Required: every listing says where its facts came from.
    sources: list[SourceIn] = Field(min_length=1, max_length=5)
    from_suggestion: Annotated[str, Field(max_length=64)] | None = None

    _https = field_validator("website")(_https_only)

    @field_validator("categories")
    @classmethod
    def _cats(cls, cats):
        bad = [c for c in cats if c not in SUPPLY_CATEGORIES]
        if bad:
            raise ValueError(f"unknown categories: {', '.join(bad)}")
        return cats

    @field_validator("trades")
    @classmethod
    def _trades(cls, trades):
        return [_check_trade(t) for t in trades]

    @field_validator("ships_to")
    @classmethod
    def _states(cls, value):
        if isinstance(value, list):
            states = [s.upper() for s in value]
            bad = [s for s in states if s not in geo.STATES]
            if bad:
                raise ValueError(f"unknown states: {', '.join(bad)}")
            return sorted(set(states))
        return value


class RemovalRequestIn(Strict):
    requester_name: Annotated[str, Field(min_length=2, max_length=120)]
    requester_role: Annotated[str, Field(min_length=2, max_length=120)]
    email: EmailStr
    phone: Annotated[str, Field(max_length=40)] = ""
    message: Annotated[str, Field(max_length=2000)] = ""


class RemovalDecisionIn(Strict):
    decision: Literal["approve", "reject"]
    # How the request was confirmed to come from the business, in the moderator's words. Required to approve.
    authorization_check: Annotated[str, Field(max_length=500)] = ""
    aliases: list[Annotated[str, Field(min_length=3, max_length=120)]] = Field(default_factory=list, max_length=10)
    note: Annotated[str, Field(max_length=1000)] = ""


# --- views ---


def _supplier_view(s: dict, center: dict | None = None, center_state: str | None = None) -> dict:
    locations = []
    nearest = None
    for loc in s.get("locations", []):
        entry = {"label": loc["label"], "address": loc.get("address", "")}
        if center:
            entry["distance_miles"] = round(geo.miles(center, loc), 1)
            nearest = entry["distance_miles"] if nearest is None else min(nearest, entry["distance_miles"])
        locations.append(entry)
    ships = s.get("ships_to", "unknown")
    view = {
        "id": s["_id"],
        "name": s["name"],
        "website": s.get("website"),
        "offers": s.get("offers", ""),
        "categories": s.get("categories", []),
        "trades": s.get("trades", []),
        "coverage": s.get("coverage", "local"),
        "branch_note": s.get("branch_note", ""),
        "locations": locations,
        "delivery": s.get("delivery", "unknown"),
        "business_account": s.get("business_account", "unknown"),
        "ships_to": ships,
        "verification": rules.verification_text(s.get("sources", [])),
        "added_by": "member suggestion" if s.get("origin") == "member_suggestion" else "Trade Circle",
    }
    if center:
        reasons = []
        if nearest is not None:
            reasons.append(f"{nearest} mi away")
        if s.get("coverage") == "multi_branch":
            reasons.append("Has branches in many areas; check their store finder for one near you")
        if ships == "nationwide" or (isinstance(ships, list) and center_state in ships):
            reasons.append(f"Ships to {center_state}" if center_state else "Ships nationwide")
        view["match"] = reasons
        view["nearest_miles"] = nearest
    return view


async def _experience_summary(db, supplier_ids: list[str]) -> dict:
    summary = {i: {"positive": 0, "mixed": 0, "negative": 0, "posts": 0} for i in supplier_ids}
    async for p in db.posts.find({"supplier_id": {"$in": supplier_ids}, "status": "published"}, {"supplier_id": 1, "kind": 1, "fields": 1}):
        row = summary[p["supplier_id"]]
        row["posts"] += 1
        if p["kind"] == Kind.supplier_review.value:
            row[p["fields"].get("experience", "mixed")] += 1
    return summary


# --- directory ---


@router.get("/suppliers")
async def directory(
    category: str = "",
    trade: str = "",
    q: str = "",
    near: str = "",
    radius: int = DEFAULT_RADIUS,
    ships_here: bool = False,
    user: dict = Depends(current_user),
    db=Depends(get_db),
):
    """The supplier directory. Ordered by distance when a place is given, otherwise alphabetically.

    Starter listings get no special placement.
    """
    query: dict = {"status": "active"}
    if category:
        query["categories"] = category
    if trade:
        query["trades"] = trade
    if q.strip():
        query["name"] = {"$regex": re.escape(q.strip()[:80]), "$options": "i"}
    found = await db.suppliers.find(query).to_list(1000)

    center = geo.resolve(near) if near.strip() else None
    state = geo.state_of(center) if center else None
    radius = max(1, min(radius, 250))
    results = []
    for s in found:
        view = _supplier_view(s, center, state)
        if center:
            close = view["nearest_miles"] is not None and view["nearest_miles"] <= radius
            ships = s.get("ships_to") == "nationwide" or (isinstance(s.get("ships_to"), list) and state in s["ships_to"])
            if ships_here and not ships:
                continue
            if not (close or ships or s.get("coverage") == "multi_branch"):
                continue
        results.append(view)
    results.sort(key=lambda v: (v.get("nearest_miles") is None, v.get("nearest_miles") or 0, v["name"].lower()))
    summary = await _experience_summary(db, [r["id"] for r in results])
    for r in results:
        r["experiences"] = summary[r["id"]]
    return {"near": center and {"label": center["label"], "state": state, "radius": radius}, "suppliers": results}


@router.get("/suppliers/{supplier_id}")
async def supplier_detail(supplier_id: str, near: str = "", user: dict = Depends(current_user), db=Depends(get_db)):
    s = await db.suppliers.find_one({"_id": supplier_id})
    if s is None or s.get("status") == "removed":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")
    center = geo.resolve(near) if near.strip() else None
    view = _supplier_view(s, center, geo.state_of(center) if center else None)
    view["experiences"] = (await _experience_summary(db, [supplier_id]))[supplier_id]
    posts = await db.posts.find({"supplier_id": supplier_id, "status": "published", "kind": {"$in": EXPERIENCE_KINDS}}).sort("published_at", -1).to_list(200)
    view["member_posts"] = await shape(db, posts, user["_id"])
    return view


# --- adding listings (moderators), usually from a member's suggestion ---


async def _locations(body: SupplierIn) -> list[dict]:
    out = []
    for loc in body.locations:
        point = geo.resolve(loc.place)
        out.append({"label": point["label"], "address": loc.address, "lat": point["lat"], "lon": point["lon"], "state": point.get("state")})
    return out


@router.post("/admin/suppliers", status_code=status.HTTP_201_CREATED)
async def add_supplier(body: SupplierIn, request: Request, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    data = body.model_dump(mode="json", exclude={"locations", "from_suggestion"})
    if body.website and await db.suppliers.find_one({"website": data["website"], "status": "active"}, {"_id": 1}):
        raise HTTPException(status.HTTP_409_CONFLICT, "A listing with that website already exists.")
    supplier = {
        "_id": uuid.uuid4().hex,
        **data,
        "locations": await _locations(body),
        "origin": "member_suggestion" if body.from_suggestion else "admin",
        "status": "active",
        "created_by": user["_id"],
        "created_at": now(),
    }
    await db.suppliers.insert_one(supplier)
    if body.from_suggestion:
        # Connect the suggestion to its new listing so the conversation stays with it.
        await db.posts.update_one({"_id": body.from_suggestion, "kind": Kind.supplier_suggestion.value}, {"$set": {"supplier_id": supplier["_id"], "fields.listing_added": True}})
    request.state.audit_record = supplier["_id"]
    return _supplier_view(supplier)


@router.post("/admin/suppliers/seed")
async def seed_starters(user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    return {"added": await rules.seed(db)}


# --- removal requests from businesses ---


@router.post("/suppliers/{supplier_id}/removal-requests", status_code=status.HTTP_201_CREATED)
async def request_removal(supplier_id: str, body: RemovalRequestIn, request: Request, db=Depends(get_db)):
    """Open to the business itself, which may not be a member. A moderator confirms it's really them before anything is removed."""
    request.app.state.limiters["quote"].check(f"removal:{client_ip(request)}")
    s = await db.suppliers.find_one({"_id": supplier_id, "status": "active"})
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")
    email_domain = body.email.split("@", 1)[1].lower()
    site = rules.domain(s.get("website") or "")
    item = {
        "_id": uuid.uuid4().hex,
        "supplier_id": supplier_id,
        "supplier_name": s["name"],
        **body.model_dump(),
        # A hint for the moderator, not proof: confirmation still has to be done by a person.
        "email_matches_website": bool(site) and (email_domain == site or email_domain.endswith("." + site)),
        "status": "pending",
        "created_at": now(),
    }
    await db.removal_requests.insert_one(item)
    request.state.audit_record = item["_id"]
    return {
        "id": item["_id"],
        "status": "pending",
        "message": "Thanks. A moderator will contact you to confirm you represent this business before the listing is removed.",
    }


@router.get("/admin/removal-requests")
async def list_removal_requests(request_status: str = "pending", user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    items = await db.removal_requests.find({"status": request_status}).sort("created_at", 1).to_list(200)
    return [{**{k: v for k, v in i.items() if k != "_id"}, "id": i["_id"]} for i in items]


@router.post("/admin/removal-requests/{request_id}/decide")
async def decide_removal(request_id: str, body: RemovalDecisionIn, request: Request, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    item = await db.removal_requests.find_one({"_id": request_id, "status": "pending"})
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No pending request with that id")
    decision = {"decided_by": user["_id"], "decided_at": now(), "note": body.note}
    if body.decision == "reject":
        await db.removal_requests.update_one({"_id": request_id}, {"$set": {"status": "rejected", **decision}})
        return {"id": request_id, "status": "rejected"}
    if len(body.authorization_check.strip()) < 10:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Describe how you confirmed the request comes from the business or its authorized representative.",
        )
    supplier = await db.suppliers.find_one({"_id": item["supplier_id"]})
    if supplier is None or supplier.get("status") == "removed":
        raise HTTPException(status.HTTP_409_CONFLICT, "That listing is already removed.")
    result = await rules.remove(db, supplier, body.aliases, flag_for_review)
    await db.removal_requests.update_one(
        {"_id": request_id},
        {"$set": {"status": "completed", "authorization_check": body.authorization_check, "result": {k: v for k, v in result.items() if k != "names_replaced"}, **decision}},
    )
    request.state.audit_record = request_id
    return {"id": request_id, "status": "completed", "posts_anonymized": result["posts"], "comments_anonymized": result["comments"], "flagged_for_review": result["posts"] + result["comments"]}
