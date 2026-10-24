import re
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .. import handoffs as rules
from ..deps import get_db, now, today
from ..models import CancelResponseIn, HandoffIn, HandoffReasonIn, VacationIn
from ..notices import notify
from ..notify import queue_alert
from ..security import current_user, require_role

router = APIRouter(prefix="/api", tags=["handoffs"])

# Details the recipient sees before accepting. The homeowner's name and phone
# are shared only once the recipient has agreed to take the job.
PRIVATE_JOB_FIELDS = ("customer_name", "customer_phone")


def _settings(request: Request):
    return request.app.state.settings


# --- vacations ---


def _vacation_view(v: dict, day: date) -> dict:
    return {
        "id": v["_id"],
        "start_on": v["start_on"],
        "end_on": v["end_on"],
        "note": v["note"],
        "days": rules.vacation_days(date.fromisoformat(v["start_on"]), date.fromisoformat(v["end_on"])),
        "active": v["start_on"] <= day.isoformat() <= v["end_on"],
        "past": v["end_on"] < day.isoformat(),
    }


@router.get("/me/vacations")
async def list_vacations(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    day = today(request)
    entries = await db.vacations.find({"owner_id": user["_id"]}).sort("start_on", -1).to_list(100)
    return {"max_days": rules.VACATION_MAX_DAYS, "min_gap_days": rules.VACATION_MIN_GAP_DAYS, "vacations": [_vacation_view(v, day) for v in entries]}


@router.post("/me/vacations", status_code=status.HTTP_201_CREATED)
async def add_vacation(body: VacationIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    day = today(request)
    rules.check_vacation(body.start_on, body.end_on, day, await rules.vacation_ranges(db, user["_id"]))
    vacation = {
        "_id": uuid.uuid4().hex,
        "owner_id": user["_id"],
        "start_on": body.start_on.isoformat(),
        "end_on": body.end_on.isoformat(),
        "note": body.note,
        "created_at": now(),
    }
    await db.vacations.insert_one(vacation)
    request.state.audit_record = vacation["_id"]
    return _vacation_view(vacation, day)


@router.delete("/me/vacations/{vacation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_vacation(vacation_id: str, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Cancel an upcoming vacation, or end a current one early. Past ones stay on record."""
    day = today(request)
    vacation = await db.vacations.find_one({"_id": vacation_id, "owner_id": user["_id"]})
    if vacation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vacation not found")
    if vacation["end_on"] < day.isoformat():
        raise HTTPException(status.HTTP_409_CONFLICT, "That vacation is over and stays on record.")
    if vacation["start_on"] >= day.isoformat():
        await db.vacations.delete_one({"_id": vacation_id})
    else:
        # Started already: it ends yesterday, so normal limits apply from today.
        await db.vacations.update_one({"_id": vacation_id}, {"$set": {"end_on": (day - timedelta(days=1)).isoformat(), "ended_early_at": now()}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- finding a member ---


@router.get("/members")
async def find_members(
    request: Request,
    q: str = "",
    trade: str = "",
    city: str = "",
    user: dict = Depends(current_user),
    db=Depends(get_db),
):
    """Published members other than you, for choosing who to hand a job to."""
    query: dict = {"published": {"$ne": False}, "owner_id": {"$ne": user["_id"]}}
    if trade:
        query["trade"] = trade.lower()
    if city:
        query["city"] = {"$regex": f"^{re.escape(city.strip())}$", "$options": "i"}
    if q.strip():
        query["business_name"] = {"$regex": re.escape(q.strip()[:60]), "$options": "i"}
    profiles = await db.profiles.find(query, {"slug": 1, "business_name": 1, "trade": 1, "city": 1, "owner_id": 1}).limit(25).to_list(25)
    disabled = {u["_id"] async for u in db.users.find({"_id": {"$in": [p["owner_id"] for p in profiles]}, "disabled": True}, {"_id": 1})}
    return [
        {"slug": p["slug"], "business_name": p["business_name"], "trade": p["trade"], "city": p["city"]}
        for p in profiles
        if p["owner_id"] not in disabled
    ]


# --- handoffs ---


def _view(h: dict, viewer_id: str) -> dict:
    outgoing = h["sender_id"] == viewer_id
    job = dict(h["job"])
    if not outgoing and h["status"] == "proposed":
        for field in PRIVATE_JOB_FIELDS:
            job.pop(field, None)
    view = {
        "id": h["_id"],
        "direction": "outgoing" if outgoing else "incoming",
        "status": h["status"],
        "from": h["sender"],
        "to": h["recipient"],
        "job": job,
        "start_on": h["start_on"],
        "end_on": h.get("end_on"),
        "note": h.get("note", ""),
        "during_vacation": not h.get("counted", True),
        "proposed_at": h["proposed_at"],
        "responded_at": h.get("responded_at"),
        "completed_at": h.get("completed_at"),
        "reversed_at": h.get("reversed_at"),
        "cancelled_at": h.get("cancelled_at"),
        "end_reason": h.get("end_reason"),
        "cancel_request": h.get("cancel_request"),
    }
    if outgoing:
        # The sender's own job; the recipient gets a separate copy when they accept.
        view["job_id"] = h["job_id"]
    return view


async def _member(db, user_id: str) -> dict:
    profile = await db.profiles.find_one({"owner_id": user_id}, {"slug": 1, "business_name": 1})
    return {"slug": profile["slug"], "business_name": profile["business_name"]}


async def _attach_cheer_prompts(db, views: list, handoffs: list, viewer_id: str) -> None:
    """Cheer prompt data on completed handoffs: the sender gets a one-tap thank-you for their cover.

    A completed handoff the sender hasn't cheered yet carries `cheer_prompt`
    (who to thank); once they've sent it, the view carries `cheer_sent` instead.
    """
    targets = [h for h in handoffs if h["status"] == "completed" and h["sender_id"] == viewer_id]
    if not targets:
        return
    cheered = {c["handoff_id"] async for c in db.cheers.find({"handoff_id": {"$in": [h["_id"] for h in targets]}}, {"handoff_id": 1})}
    by_id = {h["_id"]: h for h in targets}
    for view in views:
        h = by_id.get(view["id"])
        if h is None:
            continue
        if h["_id"] in cheered:
            view["cheer_sent"] = True
        else:
            view["cheer_prompt"] = {"to": h["recipient"]}


@router.get("/handoffs/allowance")
async def get_allowance(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    return await rules.allowance(db, user["_id"], today(request), _settings(request).timezone)


@router.get("/handoffs")
async def list_handoffs(user: dict = Depends(current_user), db=Depends(get_db)):
    found = await db.handoffs.find({"$or": [{"sender_id": user["_id"]}, {"recipient_id": user["_id"]}]}).sort("proposed_at", -1).to_list(500)
    views = [_view(h, user["_id"]) for h in found]
    await _attach_cheer_prompts(db, views, found, user["_id"])
    return views


@router.post("/handoffs", status_code=status.HTTP_201_CREATED)
async def propose(body: HandoffIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    settings = _settings(request)
    day = today(request)
    if body.start_on < day:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The start date has already passed.")
    if body.end_on and body.end_on < body.start_on:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The end date must be on or after the start date.")

    job = await db.jobs.find_one({"_id": body.job_id, "owner_id": user["_id"]})
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job["status"] in ("done", "cancelled", "handed_off"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only open jobs can be handed off.")
    if await db.handoffs.find_one({"job_id": job["_id"], "status": {"$in": list(rules.OPEN_STATUSES)}}, {"_id": 1}):
        raise HTTPException(status.HTTP_409_CONFLICT, "This job already has a handoff in progress.")

    recipient_profile = await db.profiles.find_one({"slug": body.recipient_slug, "published": {"$ne": False}})
    recipient = recipient_profile and await db.users.find_one({"_id": recipient_profile["owner_id"]}, {"disabled": 1})
    if not recipient or recipient.get("disabled"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if recipient["_id"] == user["_id"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You can't hand a job to yourself.")

    vacation = await rules.active_vacation(db, user["_id"], day)
    if vacation is None:
        await rules.reserve_slot(db, user["_id"], recipient["_id"], day, settings.timezone)

    handoff = {
        "_id": uuid.uuid4().hex,
        "sender_id": user["_id"],
        "recipient_id": recipient["_id"],
        "sender": await _member(db, user["_id"]),
        "recipient": {"slug": recipient_profile["slug"], "business_name": recipient_profile["business_name"]},
        "job_id": job["_id"],
        "job": {k: job.get(k) for k in ("title", "site_address", "notes", "estimate_cents", "customer_name", "customer_phone")},
        "start_on": body.start_on.isoformat(),
        "end_on": body.end_on.isoformat() if body.end_on else None,
        "note": body.note,
        "status": "proposed",
        "week_start": rules.week_start(day).isoformat(),
        # Handoffs sent on vacation don't use the weekly allowance.
        "counted": vacation is None,
        "vacation_id": vacation["_id"] if vacation else None,
        "proposed_at": now(),
    }
    try:
        await db.handoffs.insert_one(handoff)
    except Exception:
        await rules.release_slot(db, handoff)
        raise
    request.state.audit_record = handoff["_id"]
    await queue_alert(
        db,
        recipient["_id"],
        kind="handoff_proposed",
        subject=f"{handoff['sender']['business_name']} asked you to cover a job",
        text=f"{handoff['sender']['business_name']} asked you to cover \"{job['title']}\" starting {handoff['start_on']}. Accept or decline:",
        link=f"{settings.public_url}/app/handoffs",
        record_id=handoff["_id"],
        day=day.isoformat(),
    )
    return _view(handoff, user["_id"])


async def _transition(db, handoff_id: str, *, who: str, user_id: str, from_status: str, to_status: str, stamp: str, extra: dict | None = None) -> dict:
    """Move a handoff between states in one atomic step, so two taps can't both succeed."""
    updated = await db.handoffs.find_one_and_update(
        {"_id": handoff_id, who: user_id, "status": from_status},
        {"$set": {"status": to_status, stamp: now(), **(extra or {})}},
        return_document=True,
    )
    if updated is None:
        exists = await db.handoffs.find_one({"_id": handoff_id, who: user_id}, {"status": 1})
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Handoff not found")
        raise HTTPException(status.HTTP_409_CONFLICT, f"This handoff is {exists['status']}, so it can't be {to_status}.")
    return updated


async def _tell_sender(db, settings, h: dict, verb: str, day: str) -> None:
    name = h["recipient"]["business_name"]
    await queue_alert(
        db,
        h["sender_id"],
        kind=f"handoff_{verb}",
        subject=f"{name} {verb} your handoff",
        text=f"{name} {verb} \"{h['job']['title']}\".",
        link=f"{settings.public_url}/app/handoffs",
        record_id=h["_id"],
        day=day,
    )


@router.post("/handoffs/{handoff_id}/accept")
async def accept(handoff_id: str, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    h = await _transition(db, handoff_id, who="recipient_id", user_id=user["_id"], from_status="proposed", to_status="accepted", stamp="responded_at")
    # The job moves onto the recipient's job sheet; the sender's copy is marked handed off.
    await db.jobs.insert_one(
        {
            "_id": uuid.uuid4().hex,
            "owner_id": user["_id"],
            **{k: h["job"].get(k) for k in ("title", "site_address", "estimate_cents", "customer_phone")},
            "customer_name": h["job"].get("customer_name") or "",
            "notes": "\n\n".join(filter(None, [f"Covering for {h['sender']['business_name']}.", h.get("note"), h["job"].get("notes")])),
            "status": "scheduled",
            "scheduled_on": h["start_on"],
            "from_handoff": h["_id"],
            "created_at": now(),
        }
    )
    before = await db.jobs.find_one_and_update(
        {"_id": h["job_id"], "owner_id": h["sender_id"]}, {"$set": {"status": "handed_off", "updated_at": now()}}
    )
    # Remembered so the job can go back exactly as it was if the handoff is reversed or cancelled.
    await db.handoffs.update_one({"_id": h["_id"]}, {"$set": {"sender_job_status": (before or {}).get("status", "scheduled")}})
    await _tell_sender(db, _settings(request), h, "accepted", today(request).isoformat())
    return _view(h, user["_id"])


@router.post("/handoffs/{handoff_id}/decline")
async def decline(handoff_id: str, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    h = await _transition(db, handoff_id, who="recipient_id", user_id=user["_id"], from_status="proposed", to_status="declined", stamp="responded_at")
    await rules.release_slot(db, h)
    await _tell_sender(db, _settings(request), h, "declined", today(request).isoformat())
    return _view(h, user["_id"])


@router.post("/handoffs/{handoff_id}/withdraw")
async def withdraw(handoff_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    h = await _transition(db, handoff_id, who="sender_id", user_id=user["_id"], from_status="proposed", to_status="withdrawn", stamp="responded_at")
    await rules.release_slot(db, h)
    return _view(h, user["_id"])


@router.post("/handoffs/{handoff_id}/complete")
async def complete(handoff_id: str, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    h = await _transition(db, handoff_id, who="recipient_id", user_id=user["_id"], from_status="accepted", to_status="completed", stamp="completed_at")
    await db.jobs.update_one({"from_handoff": h["_id"], "owner_id": user["_id"]}, {"$set": {"status": "done", "updated_at": now()}})
    await _tell_sender(db, _settings(request), h, "completed", today(request).isoformat())
    return _view(h, user["_id"])


# --- after acceptance: reversal by the recipient, cancellation requested by the sender ---
#
# Counting: a reversal by the recipient gives the sender's weekly slot back, like a
# decline, because the sender didn't choose it. A cancellation the sender asked for
# keeps the slot used, so "hand off, then cancel" can't get around the weekly limit.


async def _return_job(db, h: dict) -> None:
    """The job goes back onto the sender's sheet as it was; the recipient's copy is cancelled."""
    await db.jobs.update_one(
        {"_id": h["job_id"], "owner_id": h["sender_id"], "status": "handed_off"},
        {"$set": {"status": h.get("sender_job_status") or "scheduled", "updated_at": now()}},
    )
    await db.jobs.update_one(
        {"from_handoff": h["_id"], "owner_id": h["recipient_id"]},
        {"$set": {"status": "cancelled", "updated_at": now()}},
    )


async def _tell(db, settings, to_id: str, h: dict, kind: str, text: str, day: str) -> None:
    # In-app for everyone; email or text too on paid plans, under the existing alert rules.
    await notify(db, to_id, kind, text, "/handoffs")
    await queue_alert(db, to_id, kind=kind, subject=text, text=text, link=f"{settings.public_url}/app/handoffs", record_id=h["_id"], day=day)


@router.post("/handoffs/{handoff_id}/reverse")
async def reverse(handoff_id: str, body: HandoffReasonIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """The recipient hands an accepted job back before it's completed."""
    h = await _transition(
        db, handoff_id, who="recipient_id", user_id=user["_id"], from_status="accepted", to_status="reversed", stamp="reversed_at",
        extra={"end_reason": body.reason.strip(), "ended_by": user["_id"]},
    )
    if (h.get("cancel_request") or {}).get("status") == "pending":
        await db.handoffs.update_one({"_id": handoff_id}, {"$set": {"cancel_request.status": "closed"}})
    await _return_job(db, h)
    await rules.release_slot(db, h)
    await _tell(db, _settings(request), h["sender_id"], h, "handoff_reversed",
                f"{h['recipient']['business_name']} handed \"{h['job']['title']}\" back to you: {body.reason.strip()[:120]}", today(request).isoformat())
    return _view(await db.handoffs.find_one({"_id": handoff_id}), user["_id"])


@router.post("/handoffs/{handoff_id}/cancel-request")
async def request_cancel(handoff_id: str, body: HandoffReasonIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """The sender asks to take an accepted job back. The recipient agrees or keeps it."""
    updated = await db.handoffs.find_one_and_update(
        {"_id": handoff_id, "sender_id": user["_id"], "status": "accepted", "cancel_request.status": {"$ne": "pending"}},
        {"$set": {"cancel_request": {"reason": body.reason.strip(), "requested_at": now(), "status": "pending"}}},
        return_document=True,
    )
    if updated is None:
        h = await db.handoffs.find_one({"_id": handoff_id, "sender_id": user["_id"]})
        if h is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Handoff not found")
        if h["status"] != "accepted":
            raise HTTPException(status.HTTP_409_CONFLICT, f"This handoff is {h['status']}, so it can't be cancelled.")
        raise HTTPException(status.HTTP_409_CONFLICT, "You've already asked to cancel; waiting for their answer.")
    request.state.audit_record = handoff_id
    await _tell(db, _settings(request), updated["recipient_id"], updated, "handoff_cancel_requested",
                f"{updated['sender']['business_name']} asked to cancel the handoff of \"{updated['job']['title']}\": {body.reason.strip()[:120]}", today(request).isoformat())
    return _view(updated, user["_id"])


@router.post("/handoffs/{handoff_id}/cancel-request/respond")
async def respond_cancel(handoff_id: str, body: CancelResponseIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    settings = _settings(request)
    pending = await db.handoffs.find_one({"_id": handoff_id, "recipient_id": user["_id"], "status": "accepted", "cancel_request.status": "pending"})
    if pending is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No cancellation request waiting on this handoff")
    if body.agree:
        h = await _transition(
            db, handoff_id, who="recipient_id", user_id=user["_id"], from_status="accepted", to_status="cancelled", stamp="cancelled_at",
            extra={"cancel_request.status": "agreed", "end_reason": pending["cancel_request"]["reason"], "ended_by": pending["sender_id"]},
        )
        await _return_job(db, h)
        # The weekly slot stays used: the sender chose to take the job back.
        await _tell(db, settings, h["sender_id"], h, "handoff_cancelled", f"{h['recipient']['business_name']} agreed: \"{h['job']['title']}\" is back on your job sheet.", today(request).isoformat())
    else:
        await db.handoffs.update_one({"_id": handoff_id, "cancel_request.status": "pending"}, {"$set": {"cancel_request.status": "declined", "cancel_request.answered_at": now()}})
        await _tell(db, settings, pending["sender_id"], pending, "handoff_cancel_declined", f"{pending['recipient']['business_name']} is keeping \"{pending['job']['title']}\".", today(request).isoformat())
    return _view(await db.handoffs.find_one({"_id": handoff_id}), user["_id"])


# --- review ---


@router.get("/admin/handoffs/patterns")
async def handoff_patterns(weeks: int = 12, min_count: int = 4, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    """Pairs of members who hand jobs to each other often, for a person to review.

    This only surfaces patterns. Nothing here limits or penalizes anyone.
    """
    weeks = max(1, min(weeks, 52))
    since = now() - timedelta(weeks=weeks)
    pairs: dict[tuple[str, str], dict] = {}
    async for h in db.handoffs.find({"proposed_at": {"$gte": since}}):
        key = (h["sender_id"], h["recipient_id"])
        pair = pairs.setdefault(key, {"from": h["sender"], "to": h["recipient"], "total": 0, "by_status": {}, "during_vacation": 0})
        pair["total"] += 1
        pair["by_status"][h["status"]] = pair["by_status"].get(h["status"], 0) + 1
        pair["during_vacation"] += 0 if h.get("counted", True) else 1
    rows = []
    for (sender, recipient), pair in pairs.items():
        back = pairs.get((recipient, sender), {}).get("total", 0)
        rows.append({**pair, "reverse_total": back, "review": pair["total"] >= min_count or pair["total"] + back >= 2 * min_count})
    rows.sort(key=lambda r: (not r["review"], -r["total"]))
    return {"weeks": weeks, "min_count": min_count, "pairs": rows}
