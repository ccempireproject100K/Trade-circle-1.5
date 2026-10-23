"""YouTube auto-posting: members connect a channel, confirm a clip's title,
description and visibility, and the upload happens here in the background.

This is a YouTube integration, not a partnership. Jobs are queued in
`youtube_jobs` and claimed, retried and backed off exactly like the alert
outbox; a failed upload never touches the local clip. One upload costs 1,600
of the Google project's 10,000 daily quota units, so a site-wide daily counter
holds extra posts for the next day instead of letting them fail at YouTube.
"""
import logging
import uuid
from datetime import timedelta
from pathlib import Path

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from . import secrets
from .deps import now
from .digest import local_now
from .youtube_api import YouTube, YouTubeError

log = logging.getLogger("trade_circle.youtube")

MAX_ATTEMPTS = 5
BATCH = 10
PRIVACY_STATES = ("public", "unlisted", "private")


def configured(settings) -> bool:
    return settings.youtube_ready


def connection(user: dict) -> dict | None:
    return (user or {}).get("youtube") or None


def _media_root(settings) -> Path:
    if settings.media_dir:
        return Path(settings.media_dir)
    return Path(__file__).resolve().parents[2] / "media"


# --- the site-wide daily upload counter (quota discipline) ---


async def _take(db, day: str, cap: int) -> bool:
    """Reserve one of today's uploads, atomically. Mirrors the AI allowance."""
    try:
        doc = await db.youtube_daily.find_one_and_update(
            {"_id": day, "count": {"$lt": cap}}, {"$inc": {"count": 1}, "$set": {"updated_at": now()}}, upsert=True, return_document=ReturnDocument.AFTER
        )
    except DuplicateKeyError:
        return False  # the counter exists and is already at the cap
    return doc is not None


async def _give_back(db, day: str) -> None:
    await db.youtube_daily.update_one({"_id": day, "count": {"$gt": 0}}, {"$inc": {"count": -1}})


async def uploads_today(db, day: str) -> int:
    doc = await db.youtube_daily.find_one({"_id": day}) or {}
    return doc.get("count", 0)


def _next_day_start(settings):
    here = local_now(settings)
    return (here + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


# --- queueing ---


async def _set_clip(db, clip_id: str, **fields) -> None:
    await db.uploads.update_one({"_id": clip_id}, {"$set": {f"youtube.{k}": v for k, v in fields.items()}})


async def queue_post(db, user: dict, clip: dict, title: str, description: str, privacy: str) -> dict:
    """Record the member's confirmed choices and queue the background upload."""
    job = {
        "_id": uuid.uuid4().hex,
        "user_id": user["_id"],
        "clip_id": clip["_id"],
        "title": title,
        "description": description,
        "privacy": privacy,
        "status": "queued",
        "attempts": 0,
        "next_attempt_at": now(),
        "created_at": now(),
        "last_error": None,
    }
    await db.youtube_jobs.insert_one(job)
    await _set_clip(db, clip["_id"], status="queued", title=title, description=description, privacy=privacy, error=None, video_id=None, url=None, requested_at=now(), updated_at=now())
    return job


async def cancel_pending(db, user_id: str) -> None:
    """On disconnect: stop anything still waiting, and clear the clips' queued marks."""
    async for job in db.youtube_jobs.find({"user_id": user_id, "status": "queued"}, {"clip_id": 1}):
        await db.uploads.update_one({"_id": job["clip_id"]}, {"$unset": {"youtube": ""}})
    await db.youtube_jobs.update_many({"user_id": user_id, "status": "queued"}, {"$set": {"status": "cancelled"}})


# --- the worker ---


async def _claim(db):
    return await db.youtube_jobs.find_one_and_update(
        {"status": "queued", "next_attempt_at": {"$lte": now()}},
        {"$set": {"status": "posting", "claimed_at": now()}, "$inc": {"attempts": 1}},
        sort=[("next_attempt_at", 1)],
        return_document=ReturnDocument.AFTER,
    )


async def _failed(db, job: dict, reason: str, permanent: bool) -> None:
    reason = reason[:300]
    if permanent or job["attempts"] >= MAX_ATTEMPTS:
        await db.youtube_jobs.update_one({"_id": job["_id"]}, {"$set": {"status": "failed", "last_error": reason}})
        await _set_clip(db, job["clip_id"], status="failed", error=reason, updated_at=now())
        log.warning("youtube job %s failed permanently: %s", job["_id"], reason)
    else:
        await db.youtube_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "queued", "last_error": reason, "next_attempt_at": now() + timedelta(seconds=30 * 2 ** job["attempts"])}},
        )
        await _set_clip(db, job["clip_id"], status="queued", error=reason, updated_at=now())
        log.warning("youtube job %s will retry: %s", job["_id"], reason)


async def _deliver_one(db, settings, api: YouTube, job: dict) -> bool:
    """Post one queued clip. Returns True when the video went up."""
    user = await db.users.find_one({"_id": job["user_id"]})
    clip = await db.uploads.find_one({"_id": job["clip_id"]})
    conn = connection(user) if user else None
    if user is None or clip is None or conn is None:
        await _failed(db, job, "The channel was disconnected before this could post.", permanent=True)
        return False

    day = local_now(settings).date().isoformat()
    if not await _take(db, day, settings.youtube_daily_uploads):
        # Not a failure: the site's daily quota budget is spent. Hold for tomorrow.
        await db.youtube_jobs.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "queued", "next_attempt_at": _next_day_start(settings), "last_error": "Daily upload limit reached; held for tomorrow."}, "$inc": {"attempts": -1}},
        )
        log.info("youtube job %s held: daily cap of %s uploads reached", job["_id"], settings.youtube_daily_uploads)
        return False

    await _set_clip(db, clip["_id"], status="posting", error=None, updated_at=now())
    try:
        refresh_token = secrets.decrypt(settings, conn.get("refresh_token", ""))
        if not refresh_token:
            raise YouTubeError("The stored YouTube sign-in couldn't be read. Reconnect the channel in Settings.", permanent=True)
        try:
            access = await api.refresh(refresh_token)
        except YouTubeError as exc:
            if exc.permanent:
                await db.users.update_one({"_id": user["_id"]}, {"$set": {"youtube.needs_reconnect": True}})
                raise YouTubeError("Your YouTube connection stopped working. Reconnect it in Settings.", permanent=True) from exc
            raise
        keys = clip.get("media_keys") or []
        path = _media_root(settings) / keys[0] if keys else None
        if path is None or not path.exists():
            raise YouTubeError("The clip's file is missing from this server.", permanent=True)
        result = await api.upload(access, path.read_bytes(), job["title"], job["description"], job["privacy"])
    except YouTubeError as exc:
        await _give_back(db, day)
        await _failed(db, job, str(exc), exc.permanent)
        return False

    await db.youtube_jobs.update_one({"_id": job["_id"]}, {"$set": {"status": "sent", "provider_id": result["id"], "sent_at": now(), "last_error": None}})
    await _set_clip(db, clip["_id"], status="posted", video_id=result["id"], url=result["url"], error=None, posted_at=now(), updated_at=now())
    return True


async def deliver_due(db, settings, transport=None) -> int:
    """Post what is due. Returns the number of videos posted this pass."""
    if not configured(settings):
        return 0
    api = YouTube(settings.youtube_client_id, settings.youtube_client_secret, transport)
    posted = 0
    for _ in range(BATCH):
        job = await _claim(db)
        if job is None:
            break
        if await _deliver_one(db, settings, api, job):
            posted += 1
    return posted
