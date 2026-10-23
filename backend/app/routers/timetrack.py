"""Time tracking (Starter plan and up): clock in and out, or add hours by hand, per job.

Entries belong to the business. A teammate with the jobs permission tracks their
own time for the business; the owner sees everyone's. Times are stored in UTC
and shown in the platform time zone. If the business drops to Free, entries
stay readable and exportable but no new time can be added.
"""
import csv
import io
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import Field, model_validator
from pymongo.errors import DuplicateKeyError

from ..deps import get_db, now, today
from ..models import Strict
from ..team import acting_for
from ..tiers import require
from .community import authors

router = APIRouter(prefix="/api/time", tags=["time tracking"])

Note = Annotated[str, Field(max_length=300)]
MAX_HOURS = 16


class ClockIn(Strict):
    job_id: Annotated[str, Field(max_length=64)] | None = None
    note: Note = ""


class ClockOut(Strict):
    note: Note | None = None


class ManualEntry(Strict):
    job_id: Annotated[str, Field(max_length=64)] | None = None
    day: date
    start: Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
    end: Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
    break_minutes: Annotated[int, Field(ge=0, le=480)] = 0
    note: Note = ""

    @model_validator(mode="after")
    def _order(self):
        if self.end <= self.start:
            raise ValueError("the end time has to be after the start time (split shifts that cross midnight into two entries)")
        return self


def _zone(request: Request) -> ZoneInfo:
    return ZoneInfo(request.app.state.settings.timezone)


def _worker(request: Request) -> str:
    return request.state.user_id  # the person signed in, even when working for a business


def _minutes(e: dict) -> int:
    end = e.get("ended_at") or now()
    start = e["started_at"] if e["started_at"].tzinfo else e["started_at"].replace(tzinfo=timezone.utc)
    end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    return max(0, int((end - start).total_seconds() // 60) - e.get("break_minutes", 0))


async def _job_ok(db, owner_id: str, job_id: str | None) -> dict | None:
    if not job_id:
        return None
    job = await db.jobs.find_one({"_id": job_id, "owner_id": owner_id}, {"title": 1})
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


def _view(e: dict, names: dict, jobs: dict, zone: ZoneInfo, viewer: str) -> dict:
    start = e["started_at"].replace(tzinfo=timezone.utc) if e["started_at"].tzinfo is None else e["started_at"]
    end = e.get("ended_at")
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return {
        "id": e["_id"],
        "worker": names.get(e["worker_id"], {}).get("business_name", "Former member"),
        "mine": e["worker_id"] == viewer,
        "job_id": e.get("job_id"),
        "job": jobs.get(e.get("job_id")),
        "day": start.astimezone(zone).date().isoformat(),
        "start": start.astimezone(zone).strftime("%H:%M"),
        "end": end.astimezone(zone).strftime("%H:%M") if end else None,
        "running": end is None,
        "started_at": start.isoformat(),
        "break_minutes": e.get("break_minutes", 0),
        "minutes": _minutes(e),
        "note": e.get("note", ""),
        "source": e.get("source", "clock"),
    }


async def _shape(db, entries: list, zone: ZoneInfo, viewer: str) -> list:
    names = await authors(db, [e["worker_id"] for e in entries])
    job_ids = [e["job_id"] for e in entries if e.get("job_id")]
    jobs = {j["_id"]: j["title"] async for j in db.jobs.find({"_id": {"$in": job_ids}}, {"title": 1})}
    return [_view(e, names, jobs, zone, viewer) for e in entries]


@router.get("/status")
async def clock_status(request: Request, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    from ..tiers import allows

    running = await db.time_entries.find_one({"open_for": _worker(request)})
    return {"allowed": allows(user, "time_tracking"), "running": (await _shape(db, [running], _zone(request), _worker(request)))[0] if running else None}


@router.post("/clock-in", status_code=status.HTTP_201_CREATED)
async def clock_in(body: ClockIn, request: Request, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    require(user, "time_tracking")
    await _job_ok(db, user["_id"], body.job_id)
    entry = {"_id": uuid.uuid4().hex, "owner_id": user["_id"], "worker_id": _worker(request), "job_id": body.job_id, "started_at": now(), "ended_at": None,
             "break_minutes": 0, "note": body.note, "source": "clock", "open_for": _worker(request), "created_at": now()}
    try:
        # A unique index on open_for means one running clock per person, even with two taps at once.
        await db.time_entries.insert_one(entry)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "You're already clocked in. Clock out first.")
    return (await _shape(db, [entry], _zone(request), _worker(request)))[0]


@router.post("/clock-out")
async def clock_out(body: ClockOut, request: Request, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    update = {"$set": {"ended_at": now()}, "$unset": {"open_for": ""}}
    if body.note is not None:
        update["$set"]["note"] = body.note
    entry = await db.time_entries.find_one_and_update({"open_for": _worker(request)}, update, return_document=True)
    if entry is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You're not clocked in.")
    if _minutes(entry) > MAX_HOURS * 60:
        await db.time_entries.update_one({"_id": entry["_id"]}, {"$set": {"needs_review": True}})
    return (await _shape(db, [entry], _zone(request), _worker(request)))[0]


@router.post("/entries", status_code=status.HTTP_201_CREATED)
async def add_entry(body: ManualEntry, request: Request, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    require(user, "time_tracking")
    await _job_ok(db, user["_id"], body.job_id)
    if body.day > today(request):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "You can't add time for a future day.")
    zone = _zone(request)
    start = datetime.combine(body.day, time.fromisoformat(body.start), zone).astimezone(timezone.utc)
    end = datetime.combine(body.day, time.fromisoformat(body.end), zone).astimezone(timezone.utc)
    if body.break_minutes >= (end - start).total_seconds() / 60:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The break is longer than the time worked.")
    entry = {"_id": uuid.uuid4().hex, "owner_id": user["_id"], "worker_id": _worker(request), "job_id": body.job_id, "started_at": start, "ended_at": end,
             "break_minutes": body.break_minutes, "note": body.note, "source": "manual", "created_at": now()}
    await db.time_entries.insert_one(entry)
    request.state.audit_record = entry["_id"]
    return (await _shape(db, [entry], zone, _worker(request)))[0]


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: str, request: Request, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    """People remove their own entries; the business owner can remove anyone's."""
    query = {"_id": entry_id, "owner_id": user["_id"]}
    if _worker(request) != user["_id"]:
        query["worker_id"] = _worker(request)
    result = await db.time_entries.delete_one(query)
    if not result.deleted_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _week_bounds(start: date, days: int, zone: ZoneInfo) -> tuple[datetime, datetime]:
    lo = datetime.combine(start, time.min, zone).astimezone(timezone.utc)
    return lo, lo + timedelta(days=days)


async def _range(db, request: Request, user: dict, start: date, days: int) -> list:
    lo, hi = _week_bounds(start, days, _zone(request))
    query = {"owner_id": user["_id"], "started_at": {"$gte": lo, "$lt": hi}}
    if _worker(request) != user["_id"]:
        query["worker_id"] = _worker(request)  # teammates see their own time
    entries = await db.time_entries.find(query).sort("started_at", 1).to_list(5000)
    return await _shape(db, entries, _zone(request), _worker(request))


@router.get("")
async def week(request: Request, start: date | None = None, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    """A Monday-to-Sunday week of entries with totals per day, job and person."""
    day = start or today(request)
    monday = day - timedelta(days=day.weekday())
    entries = await _range(db, request, user, monday, 7)
    totals = {"days": {}, "jobs": {}, "people": {}}
    for e in entries:
        totals["days"][e["day"]] = totals["days"].get(e["day"], 0) + e["minutes"]
        key = e["job"] or "No job"
        totals["jobs"][key] = totals["jobs"].get(key, 0) + e["minutes"]
        totals["people"][e["worker"]] = totals["people"].get(e["worker"], 0) + e["minutes"]
    return {"week_of": monday.isoformat(), "timezone": request.app.state.settings.timezone, "entries": entries, "total_minutes": sum(e["minutes"] for e in entries), "totals": totals}


@router.get("/export.csv")
async def export(request: Request, start: date, end: date, user: dict = Depends(acting_for("jobs")), db=Depends(get_db)):
    if end < start or (end - start).days > 366:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose up to a year.")
    entries = await _range(db, request, user, start, (end - start).days + 1)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Date", "Person", "Job", "Start", "End", "Break (min)", "Hours", "Note"])
    for e in entries:
        writer.writerow([e["day"], e["worker"], e["job"] or "", e["start"], e["end"] or "running", e["break_minutes"], f"{e['minutes'] / 60:.2f}", e["note"]])
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="time-{start}-to-{end}.csv"'})


async def job_minutes(db, owner_id: str, job_id: str) -> int:
    """Finished time on a job, for job costing."""
    total = 0
    async for e in db.time_entries.find({"owner_id": owner_id, "job_id": job_id, "ended_at": {"$ne": None}}):
        total += _minutes(e)
    return total
