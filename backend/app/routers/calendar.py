"""The scheduling calendar: one view of everything with a date (basic view, every plan).

Jobs by scheduled date, vacations, handoffs (sent and received, while they're
live), meetups the member hosts or said they'd go to, and follow-ups due.
Teammates working for a business see the business's jobs and follow-ups only if
they have those permissions; vacations, handoffs and meetups are always the
signed-in member's own.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..deps import get_db
from ..security import current_user
from ..team import BUSINESS_HEADER, effective_permissions, member_id

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

LIVE_HANDOFFS = ["proposed", "accepted"]
OPEN_FOLLOW_UPS = ["waiting", "followed_up"]


async def _business(request: Request, db, user: dict) -> tuple[str, set]:
    """Whose jobs and follow-ups to show, and which of those this person may see."""
    business = request.headers.get(BUSINESS_HEADER)
    if not business or business == user["_id"]:
        return user["_id"], {"jobs", "follow_ups"}
    m = await db.team_members.find_one({"_id": member_id(business, user["_id"]), "status": "active"})
    return (business, set(effective_permissions(m)) & {"jobs", "follow_ups"}) if m else (user["_id"], {"jobs", "follow_ups"})


@router.get("")
async def calendar(request: Request, start: date, days: int = 42, user: dict = Depends(current_user), db=Depends(get_db)):
    if not 1 <= days <= 92:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Show between 1 and 92 days.")
    lo, hi = start.isoformat(), (start + timedelta(days=days - 1)).isoformat()
    owner, may = await _business(request, db, user)
    events = []
    if "jobs" in may:
        async for j in db.jobs.find({"owner_id": owner, "scheduled_on": {"$gte": lo, "$lte": hi}, "status": {"$nin": ["cancelled", "handed_off"]}}):
            events.append({"kind": "job", "date": j["scheduled_on"], "title": j["title"], "detail": j.get("customer_name") or "", "status": j["status"], "link": "/jobs"})
    if "follow_ups" in may:
        async for q in db.quotes.find({"owner_id": owner, "status": {"$in": OPEN_FOLLOW_UPS}, "follow_up_on": {"$gte": lo, "$lte": hi}}):
            events.append({"kind": "follow_up", "date": q["follow_up_on"], "title": f"Follow up: {q['name']}", "detail": q.get("job_type") or "", "link": "/inbox"})
    async for v in db.vacations.find({"owner_id": user["_id"], "start_on": {"$lte": hi}, "end_on": {"$gte": lo}}):
        events.append({"kind": "vacation", "date": max(v["start_on"], lo), "end": min(v["end_on"], hi), "title": "Vacation", "detail": v.get("note", ""), "link": "/settings"})
    async for h in db.handoffs.find({"$or": [{"sender_id": user["_id"]}, {"recipient_id": user["_id"]}], "status": {"$in": LIVE_HANDOFFS}, "start_on": {"$lte": hi}}):
        end = h.get("end_on") or h["start_on"]
        if end < lo:
            continue
        outgoing = h["sender_id"] == user["_id"]
        who = h["recipient"] if outgoing else h["sender"]
        name = who.get("business_name", "a member") if isinstance(who, dict) else "a member"
        title = f"{'Handed to' if outgoing else 'Covering for'} {name}: {h['job']['title']}"
        events.append({"kind": "handoff", "date": max(h["start_on"], lo), "end": min(end, hi) if end != h["start_on"] else None, "title": title, "detail": "Waiting for a reply" if h["status"] == "proposed" else "", "link": "/handoffs"})
    going = [r["post_id"] async for r in db.rsvps.find({"user_id": user["_id"], "response": {"$in": ["going", "maybe"]}}, {"post_id": 1})]
    async for p in db.posts.find({"kind": "meetup", "status": "published", "fields.starts_on": {"$gte": lo, "$lte": hi}, "$or": [{"author_id": user["_id"]}, {"_id": {"$in": going}}]}):
        f = p["fields"]
        events.append({"kind": "meetup", "date": f["starts_on"], "title": p["title"], "detail": f"{f['starts_at']} · {f['general_location']}" + (" · cancelled" if p.get("cancelled") else ""), "link": f"/posts/{p['_id']}"})
    events.sort(key=lambda e: (e["date"], e["kind"] != "vacation", e["title"]))
    return {"start": lo, "end": hi, "events": events}
