"""The lead marketplace.

Customers describe a job on a public form, without an account. They get a
private link (emailed too, when email is set up) to see bids and choose who to
talk to. Contractors in that trade, near the job, see a compact preview (job
type, area, date wanted, photos, budget, with anything missing marked) and why
it matches them, then bid. Free and Starter members get MARKETPLACE_FREE_BIDS
bids a calendar month; Full is unlimited. Contact details are shared only when
the customer chooses a contractor, and then only with that contractor; the
chosen job lands in their follow-up tracker.

Requests close after OPEN_DAYS or when the customer closes them. Members can
report a request; moderators hide it.
"""
import asyncio
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from .. import geo, media
from ..deps import get_db, now, today
from ..models import TRADES, Strict, _email
from ..notices import notify
from ..notify import _message, queue_alert
from ..photos import _read_limited
from ..ratelimit import client_ip
from ..reviews import MAX_TEXT, display_name, lead_for_bid, review_view, reviewable
from ..security import current_user
from ..tiers import MARKETPLACE_FREE_BIDS, allows
from .pages import TRADE_LABELS, templates

router = APIRouter(tags=["marketplace"])

OPEN_DAYS = 14
MAX_PHOTOS = 3
DEFAULT_RADIUS = 30
PUBLIC_CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"


def _page(request: Request, name: str, ctx: dict, code: int = 200) -> HTMLResponse:
    response = templates.TemplateResponse(request, name, {"trades": {t: TRADE_LABELS[t] for t in TRADES if t != "other"}, **ctx}, status_code=code)
    response.headers["Content-Security-Policy"] = PUBLIC_CSP
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _open_query(day: date) -> dict:
    return {"status": "open", "closes_on": {"$gte": day.isoformat()}}


# --- the customer's side (public) ---


@router.get("/request", response_class=HTMLResponse, include_in_schema=False)
async def request_form(request: Request, trade: str = ""):
    return _page(request, "request.html", {"form": {"trade": trade}, "errors": []})


@router.post("/request", include_in_schema=False)
async def submit_request(
    request: Request,
    db=Depends(get_db),
    trade: str = Form(""), title: str = Form(""), details: str = Form(""), location: str = Form(""),
    wanted_on: str = Form(""), flexible: str = Form(""), budget: str = Form(""),
    name: str = Form(""), email: str = Form(""), phone: str = Form(""), consent: str = Form(""), website: str = Form(""),
    photos: list[UploadFile] = File(default=[]),
):
    request.app.state.limiters["quote"].check(f"market:{client_ip(request)}")
    form = {"trade": trade, "title": title, "details": details, "location": location, "wanted_on": wanted_on, "flexible": flexible, "budget": budget, "name": name, "email": email, "phone": phone}
    if website:  # honeypot
        return RedirectResponse("/request/sent", status.HTTP_303_SEE_OTHER)
    errors, place = [], None
    if trade not in TRADES:
        errors.append("Choose the kind of work.")
    if not 3 <= len(title.strip()) <= 120:
        errors.append("Add a short title, like \"Replace a ceiling fan\".")
    if not 10 <= len(details.strip()) <= 3000:
        errors.append("Describe the job in a few words (at least 10 characters).")
    try:
        place = geo.resolve(location)
    except HTTPException as exc:
        errors.append(exc.detail)
    wanted = None
    if wanted_on:
        try:
            wanted = date.fromisoformat(wanted_on)
            if wanted < today(request):
                errors.append("The date can't be in the past.")
        except ValueError:
            errors.append("Check the date.")
    if not 1 <= len(name.strip()) <= 120:
        errors.append("Add your name.")
    try:
        email = _email.validate_python(email.strip()).lower()
    except Exception:
        errors.append("Add an email address so you can see the bids.")
    if not consent:
        errors.append("Tick the box to say contractors may contact you once you choose them.")
    uploads = [p for p in photos if p.filename][:MAX_PHOTOS]
    if errors:
        return _page(request, "request.html", {"form": form, "errors": errors}, 422)
    request_id = uuid.uuid4().hex
    store = request.app.state.media
    pics = []
    for i, upload in enumerate(uploads):
        try:
            cleaned = await asyncio.to_thread(media.process, await _read_limited(upload))
        except (media.BadImage, HTTPException):
            continue  # a bad photo shouldn't lose the request
        full, thumb = f"marketplace/{request_id}/{i}.jpg", f"marketplace/{request_id}/{i}-thumb.jpg"
        store.save(full, cleaned["full"])
        store.save(thumb, cleaned["thumb"])
        pics.append({"image_url": store.url(full), "thumb_url": store.url(thumb), "media_keys": [full, thumb]})
    token = secrets.token_urlsafe(24)
    doc = {
        "_id": request_id, "token": token, "trade": trade, "title": title.strip(), "details": details.strip(),
        "location": {k: place.get(k) for k in ("label", "zip", "city", "state", "lat", "lon")}, "wanted_on": wanted.isoformat() if wanted else None,
        "flexible": bool(flexible), "budget": budget.strip()[:60], "photos": pics,
        "customer": {"name": name.strip(), "email": email, "phone": phone.strip()[:30]},
        "status": "open", "closes_on": (today(request) + timedelta(days=OPEN_DAYS)).isoformat(), "created_at": now(), "bid_count": 0,
    }
    await db.marketplace.insert_one(doc)
    link = f"{request.app.state.settings.public_url}/request/{token}"
    await db.outbox.insert_one(_message(f"customer:{request_id}", "email", email, f"Your job request \"{doc['title']}\" is posted. See bids and choose a contractor here: {link}", request_id, subject="Your Trade Circle job request", kind="marketplace_posted"))
    return RedirectResponse(f"/request/{token}?new=1", status.HTTP_303_SEE_OTHER)


@router.get("/request/sent", response_class=HTMLResponse, include_in_schema=False)
async def sent(request: Request):
    return _page(request, "request_status.html", {"missing": True})


async def _by_token(db, token: str) -> dict:
    doc = await db.marketplace.find_one({"token": token})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return doc


@router.get("/request/{token}", response_class=HTMLResponse, include_in_schema=False)
async def status_page(token: str, request: Request, db=Depends(get_db), new: str = "", reviewed: str = "", review_error: str = ""):
    doc = await db.marketplace.find_one({"token": token})
    if doc is None:
        return _page(request, "request_status.html", {"missing": True}, 404)
    bids = await db.marketplace_bids.find({"request_id": doc["_id"], "status": {"$ne": "withdrawn"}}).sort("created_at", 1).to_list(100)
    profiles = {p["owner_id"]: p async for p in db.profiles.find({"owner_id": {"$in": [b["contractor_id"] for b in bids]}})}
    chosen_phones = {}
    reviews = {}
    for b in bids:
        if b["status"] == "chosen":
            p = profiles.get(b["contractor_id"]) or {}
            chosen_phones[b["_id"]] = p.get("phone")
            # One review per lead, offered here once the work is won or done.
            lead = await lead_for_bid(db, doc, b)
            existing = await db.reviews.find_one({"lead_id": lead["_id"]}) if lead else None
            reviews[b["_id"]] = {
                "review": review_view(existing) if existing and existing["status"] != "hidden" else None,
                "can_review": bool(lead and not existing and await reviewable(db, lead)),
            }
    open_ = doc["status"] == "open" and doc["closes_on"] >= today(request).isoformat()
    return _page(request, "request_status.html", {"r": doc, "bids": bids, "profiles": profiles, "phones": chosen_phones, "reviews": reviews, "new": new == "1", "reviewed": reviewed == "1", "review_error": review_error == "1", "open": open_, "trade_label": TRADE_LABELS.get(doc["trade"], doc["trade"])})


@router.post("/request/{token}/choose/{bid_id}", include_in_schema=False)
async def choose(token: str, bid_id: str, request: Request, db=Depends(get_db)):
    """The customer picks a contractor: their contact details go to that contractor, and only them."""
    doc = await _by_token(db, token)
    bid = await db.marketplace_bids.find_one_and_update({"_id": bid_id, "request_id": doc["_id"], "status": "sent"}, {"$set": {"status": "chosen", "chosen_at": now()}})
    if bid is not None:
        c = doc["customer"]
        await db.quotes.insert_one({
            "_id": uuid.uuid4().hex, "owner_id": bid["contractor_id"], "name": c["name"], "phone": c.get("phone") or None, "email": c["email"],
            "job_type": doc["title"], "message": doc["details"], "source": "marketplace", "channel": "other", "status": "waiting",
            "notes": f"From the lead marketplace: {doc['location']['label']}" + (f", wanted {doc['wanted_on']}" if doc.get("wanted_on") else ""),
            "follow_up_on": None, "created_at": now(),
            # Links the lead back to this request, so the customer can review it later from this page.
            "marketplace_request_id": doc["_id"], "marketplace_bid_id": bid_id,
        })
        text = f"{c['name']} chose you for \"{doc['title']}\". Their contact details are in your follow-ups."
        await notify(db, bid["contractor_id"], "marketplace", text, "/inbox")
        await queue_alert(db, bid["contractor_id"], kind="marketplace_chosen", subject="A customer chose you", text=text, link=f"{request.app.state.settings.public_url}/app/inbox", record_id=bid["_id"])
    return RedirectResponse(f"/request/{token}", status.HTTP_303_SEE_OTHER)


@router.post("/request/{token}/close", include_in_schema=False)
async def close(token: str, request: Request, db=Depends(get_db)):
    doc = await _by_token(db, token)
    await db.marketplace.update_one({"_id": doc["_id"], "status": "open"}, {"$set": {"status": "closed", "closed_at": now()}})
    return RedirectResponse(f"/request/{token}", status.HTTP_303_SEE_OTHER)


@router.post("/request/{token}/review/{bid_id}", include_in_schema=False)
async def submit_review(
    token: str, bid_id: str, request: Request, db=Depends(get_db),
    stars: str = Form(""), text: str = Form(""), website: str = Form(""),
):
    """The customer reviews the contractor they chose, from this private link.

    One review per lead (a unique index on lead_id is the backstop), and only
    once the lead is won or a job made from it is done. Like the request form
    itself: rate-limited per address, with a honeypot that fakes success.
    """
    request.app.state.limiters["quote"].check(f"review:{client_ip(request)}")
    doc = await _by_token(db, token)
    back = f"/request/{token}"
    if website:  # honeypot: answer like a success so the bot learns nothing
        return RedirectResponse(f"{back}?reviewed=1", status.HTTP_303_SEE_OTHER)
    bid = await db.marketplace_bids.find_one({"_id": bid_id, "request_id": doc["_id"], "status": "chosen"})
    lead = await lead_for_bid(db, doc, bid) if bid else None
    if lead is None or not await reviewable(db, lead):
        return RedirectResponse(back, status.HTTP_303_SEE_OTHER)
    try:
        rating = int(stars)
    except ValueError:
        rating = 0
    words = text.strip()
    if not 1 <= rating <= 5 or not 1 <= len(words) <= MAX_TEXT:
        return RedirectResponse(f"{back}?review_error=1", status.HTTP_303_SEE_OTHER)
    review = {
        "_id": uuid.uuid4().hex,
        "owner_id": bid["contractor_id"],
        "lead_id": lead["_id"],
        "marketplace_request_id": doc["_id"],
        "stars": rating,
        "text": words,
        "reviewer_name": display_name(doc["customer"]["name"]),
        "status": "published",
        "response": None,
        "created_at": now(),
    }
    try:
        await db.reviews.insert_one(review)
    except DuplicateKeyError:
        # One review per lead; a second try changes nothing.
        return RedirectResponse(back, status.HTTP_303_SEE_OTHER)
    request.state.audit_record = review["_id"]
    await notify(db, bid["contractor_id"], "review", f"{review['reviewer_name']} left you a {rating}-star review.", "/reviews")
    return RedirectResponse(f"{back}?reviewed=1", status.HTTP_303_SEE_OTHER)


# --- the contractor's side ---


class BidIn(Strict):
    message: Annotated[str, Field(min_length=10, max_length=1500)]
    price_low_cents: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    price_high_cents: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    available_on: date | None = None


def _month(request: Request) -> str:
    return datetime.now(ZoneInfo(request.app.state.settings.timezone)).strftime("%Y-%m")


async def _bids_left(db, request: Request, user: dict) -> int | None:
    if allows(user, "marketplace_unlimited"):
        return None
    doc = await db.marketplace_quota.find_one({"_id": f"{user['_id']}:{_month(request)}"})
    return max(0, MARKETPLACE_FREE_BIDS - (doc or {}).get("count", 0))


def _preview(doc: dict, center: dict | None, mine: dict | None, user_trade: str | None, radius: int, vacation: dict | None) -> dict:
    distance = round(geo.miles(center, doc["location"]), 1) if center else None
    why = []
    if doc["trade"] == user_trade:
        why.append(f"It's {TRADE_LABELS.get(doc['trade'], doc['trade']).lower()} work, your trade")
    if distance is not None:
        why.append(f"It's {distance} mi from your area (you're showing jobs within {radius} mi)")
    if doc.get("wanted_on") and not vacation:
        why.append("You're not on vacation then")
    elif doc.get("wanted_on") and vacation:
        why.append(f"Heads up: you're on vacation {vacation['start_on']} to {vacation['end_on']}")
    return {
        "id": doc["_id"], "trade": doc["trade"], "title": doc["title"], "details": doc["details"],
        "area": doc["location"].get("label"), "distance_miles": distance,
        "wanted_on": doc.get("wanted_on"), "flexible": doc.get("flexible", False), "budget": doc.get("budget") or None,
        "photos": [{"image_url": p["image_url"], "thumb_url": p["thumb_url"]} for p in doc.get("photos", [])],
        # What the customer didn't say, so contractors know what to ask.
        "missing": [label for label, value in (("date", doc.get("wanted_on") or doc.get("flexible")), ("budget", doc.get("budget")), ("photos", doc.get("photos"))) if not value],
        "why": why, "bid_count": doc.get("bid_count", 0), "posted_at": doc["created_at"], "closes_on": doc["closes_on"],
        "my_bid": {k: mine[k] for k in ("message", "price_low_cents", "price_high_cents", "available_on", "status")} if mine else None,
    }


@router.get("/api/marketplace")
async def browse(request: Request, near: str = "", radius: int = DEFAULT_RADIUS, trade: str = "", user: dict = Depends(current_user), db=Depends(get_db)):
    profile = await db.profiles.find_one({"owner_id": user["_id"]}, {"trade": 1, "city": 1}) or {}
    trade = trade if trade in TRADES else profile.get("trade")
    radius = max(5, min(radius, 150))
    if not near.strip():
        return {"needs_area": True, "bids_left": await _bids_left(db, request, user), "free_bids": MARKETPLACE_FREE_BIDS, "requests": []}
    center = geo.resolve(near)
    box = geo.box(center, radius)
    query = {**_open_query(today(request)), "trade": trade, "location.lat": box["lat"], "location.lon": box["lon"]}
    found = [d for d in await db.marketplace.find(query).sort("created_at", -1).limit(200).to_list(200) if geo.miles(center, d["location"]) <= radius]
    mine = {b["request_id"]: b async for b in db.marketplace_bids.find({"contractor_id": user["_id"], "request_id": {"$in": [d["_id"] for d in found]}})}
    vacations = await db.vacations.find({"owner_id": user["_id"]}).to_list(50)

    def on_vacation(day: str | None):
        return next((v for v in vacations if day and v["start_on"] <= day <= v["end_on"]), None)

    return {
        "needs_area": False, "near": center["label"], "radius": radius, "trade": trade,
        "bids_left": await _bids_left(db, request, user), "free_bids": MARKETPLACE_FREE_BIDS,
        "requests": [_preview(d, center, mine.get(d["_id"]), profile.get("trade"), radius, on_vacation(d.get("wanted_on"))) for d in found],
    }


@router.post("/api/marketplace/{request_id}/bids", status_code=status.HTTP_201_CREATED)
async def bid(request_id: str, body: BidIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    doc = await db.marketplace.find_one({"_id": request_id, **_open_query(today(request))})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That job isn't open anymore.")
    if body.price_low_cents and body.price_high_cents and body.price_high_cents < body.price_low_cents:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The high end can't be below the low end.")
    if await db.marketplace_bids.find_one({"_id": f"{request_id}:{user['_id']}"}, {"_id": 1}):
        raise HTTPException(status.HTTP_409_CONFLICT, "You already bid on this job.")
    month_key = None
    if not allows(user, "marketplace_unlimited"):
        month_key = f"{user['_id']}:{_month(request)}"
        try:
            # Counted atomically, so two bids at once can't go past the limit.
            got = await db.marketplace_quota.find_one_and_update({"_id": month_key, "count": {"$lt": MARKETPLACE_FREE_BIDS}}, {"$inc": {"count": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
        except DuplicateKeyError:
            got = None
        if got is None:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, f"You've used your {MARKETPLACE_FREE_BIDS} bids this month. They reset on the 1st; the Full plan has unlimited bids.")
    entry = {"_id": f"{request_id}:{user['_id']}", "request_id": request_id, "contractor_id": user["_id"], **body.model_dump(mode="json"), "status": "sent", "created_at": now()}
    try:
        await db.marketplace_bids.insert_one(entry)
    except DuplicateKeyError:
        if month_key:
            await db.marketplace_quota.update_one({"_id": month_key}, {"$inc": {"count": -1}})
        raise HTTPException(status.HTTP_409_CONFLICT, "You already bid on this job.")
    await db.marketplace.update_one({"_id": request_id}, {"$inc": {"bid_count": 1}})
    profile = await db.profiles.find_one({"owner_id": user["_id"]}, {"business_name": 1}) or {}
    link = f"{request.app.state.settings.public_url}/request/{doc['token']}"
    await db.outbox.insert_one(_message(f"customer:{request_id}", "email", doc["customer"]["email"], f"{profile.get('business_name', 'A contractor')} sent a bid for \"{doc['title']}\". See it and choose who to talk to: {link}", entry["_id"], subject="New bid on your job request", kind="marketplace_bid"))
    request.state.audit_record = entry["_id"]
    return {"status": "sent", "bids_left": await _bids_left(db, request, user)}


@router.get("/api/marketplace/mine")
async def my_bids(user: dict = Depends(current_user), db=Depends(get_db)):
    bids = await db.marketplace_bids.find({"contractor_id": user["_id"]}).sort("created_at", -1).limit(100).to_list(100)
    jobs = {d["_id"]: d async for d in db.marketplace.find({"_id": {"$in": [b["request_id"] for b in bids]}}, {"title": 1, "location.label": 1, "status": 1, "closes_on": 1})}
    return [{"request_id": b["request_id"], "title": jobs.get(b["request_id"], {}).get("title", "Removed"), "area": jobs.get(b["request_id"], {}).get("location", {}).get("label"), "status": b["status"], "created_at": b["created_at"]} for b in bids]
