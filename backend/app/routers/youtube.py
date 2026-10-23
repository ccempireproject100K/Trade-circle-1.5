"""YouTube auto-posting: connect a channel, confirm a clip, post it in the background.

A YouTube integration, not a partnership. The member connects their own
channel with Google's consent screen; Trade Circle keeps only an encrypted
refresh token, which the member can revoke here or at Google at any time.
Nothing posts without the member confirming the title, description and
visibility for that clip (docs/spec-gaps.md §8).
"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import Field

from .. import secrets, tiers, youtube
from ..deps import get_db, now
from ..digest import local_now
from ..models import Strict
from ..security import create_token, current_user, decode_token
from ..youtube_api import YouTubeError, for_state

router = APIRouter(prefix="/api/youtube", tags=["youtube"])

STATE_TTL_MINUTES = 15


class YouTubePostIn(Strict):
    clip_id: str
    title: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=5000)] = ""
    visibility: Literal["public", "unlisted", "private"] = "unlisted"


def _require_configured(request: Request) -> None:
    if not youtube.configured(request.app.state.settings):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "YouTube posting isn't switched on for this site yet.")


@router.get("/status")
async def get_status(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    settings = request.app.state.settings
    conn = youtube.connection(user)
    day = local_now(settings).date().isoformat()
    return {
        "configured": youtube.configured(settings),
        "plan_includes": tiers.allows(user, "youtube_autopost"),
        "connected": bool(conn),
        "channel": {"id": conn["channel_id"], "title": conn["channel_title"]} if conn else None,
        "needs_reconnect": bool(conn and conn.get("needs_reconnect")),
        "daily_cap": settings.youtube_daily_uploads,
        "uploads_today": await youtube.uploads_today(db, day),
    }


@router.get("/connect")
async def connect(request: Request, user: dict = Depends(current_user)):
    """Where to send the member to Google's consent screen."""
    tiers.require(user, "youtube_autopost")
    _require_configured(request)
    settings = request.app.state.settings
    state = create_token(user, settings.jwt_secret, STATE_TTL_MINUTES)
    return {"url": for_state(request.app.state).consent_url(settings.youtube_redirect_uri, state)}


@router.get("/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = "", user: dict = Depends(current_user), db=Depends(get_db)):
    """Google sends the member back here. The signed state ties the visit to their account."""
    settings = request.app.state.settings
    back = "/app/settings?youtube="
    if error or not code:
        return RedirectResponse(back + "denied", status_code=302)
    claims = decode_token(state, settings.jwt_secret)
    if claims is None or claims.get("sub") != user["_id"]:
        return RedirectResponse(back + "error", status_code=302)
    api = for_state(request.app.state)
    try:
        tokens = await api.exchange_code(code, settings.youtube_redirect_uri)
        if not tokens.get("refresh_token"):
            return RedirectResponse(back + "error", status_code=302)
        channel = await api.my_channel(tokens["access_token"])
    except YouTubeError:
        return RedirectResponse(back + "error", status_code=302)
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"youtube": {
            "refresh_token": secrets.encrypt(settings, tokens["refresh_token"]),
            "channel_id": channel["id"],
            "channel_title": channel["title"],
            "connected_at": now(),
            "needs_reconnect": False,
        }}},
    )
    request.state.audit_record = user["_id"]
    return RedirectResponse(back + "connected", status_code=302)


@router.delete("/connect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Revoke at Google (best effort) and forget the stored token."""
    settings = request.app.state.settings
    conn = youtube.connection(user)
    if conn and youtube.configured(settings):
        token = secrets.decrypt(settings, conn.get("refresh_token", ""))
        if token:
            try:
                await for_state(request.app.state).revoke(token)
            except YouTubeError:
                pass  # forgetting it here is what matters; Google revocation is best effort
    await youtube.cancel_pending(db, user["_id"])
    await db.users.update_one({"_id": user["_id"]}, {"$unset": {"youtube": ""}})


@router.post("/posts", status_code=status.HTTP_201_CREATED)
async def queue_post(body: YouTubePostIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Queue one clip for posting, with the title, description and visibility the member confirmed."""
    tiers.require(user, "youtube_autopost")
    _require_configured(request)
    if not youtube.connection(user):
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect your YouTube channel first, in Settings.")
    clip = await db.uploads.find_one({"_id": body.clip_id, "owner_id": user["_id"], "type": "video"})
    if clip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clip not found")
    current = (clip.get("youtube") or {}).get("status")
    if current in ("queued", "posting"):
        raise HTTPException(status.HTTP_409_CONFLICT, "That clip is already on its way to YouTube.")
    if current == "posted":
        raise HTTPException(status.HTTP_409_CONFLICT, "That clip is already on YouTube.")
    job = await youtube.queue_post(db, user, clip, body.title.strip(), body.description.strip(), body.visibility)
    request.state.audit_record = job["_id"]
    return {"clip_id": clip["_id"], "status": "queued", "title": job["title"], "visibility": job["privacy"]}


@router.get("/posts")
async def list_posts(user: dict = Depends(current_user), db=Depends(get_db)):
    """The member's clips and where each one stands with YouTube."""
    clips = await db.uploads.find({"owner_id": user["_id"], "type": "video", "youtube": {"$exists": True}}).sort("youtube.requested_at", -1).to_list(200)
    out = []
    for clip in clips:
        yt = clip["youtube"]
        out.append({
            "clip_id": clip["_id"],
            "video_url": clip.get("video_url"),
            "thumb_url": clip.get("thumb_url"),
            "status": yt.get("status"),
            "title": yt.get("title"),
            "visibility": yt.get("privacy"),
            "video_id": yt.get("video_id"),
            "url": yt.get("url"),
            "error": yt.get("error"),
            "requested_at": yt.get("requested_at"),
            "posted_at": yt.get("posted_at"),
        })
    return out
