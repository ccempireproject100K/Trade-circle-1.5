"""Cheers endpoints: send a cheer, read your own tallies, and the admin pair-frequency report.

The economy itself lives in app/cheers.py. Cheers notify in-app only —
no texts, ever; the notices flow into the email digests like other
community activity.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field

from .. import cheers as cheers_svc
from ..deps import get_db, today
from ..models import Strict
from ..security import current_user, require_role

router = APIRouter(prefix="/api", tags=["cheers"])


class CheerIn(Strict):
    # Exactly one target: a member's page, a post, or a completed handoff.
    to_slug: str | None = None
    post_id: str | None = None
    handoff_id: str | None = None
    note: Annotated[str | None, Field(max_length=140)] = None


@router.post("/cheers", status_code=status.HTTP_201_CREATED)
async def send_cheer(body: CheerIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    request.app.state.limiters["cheer"].check(user["_id"])
    if sum(t is not None for t in (body.to_slug, body.post_id, body.handoff_id)) != 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Cheer a post, a member's page, or a handoff — pick one.")
    post = handoff = None
    if body.post_id:
        post = await db.posts.find_one({"_id": body.post_id, "status": "published"})
        if post is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
        receiver = await db.users.find_one({"_id": post["author_id"]})
    elif body.handoff_id:
        handoff = await db.handoffs.find_one({"_id": body.handoff_id})
        if handoff is None or user["_id"] not in (handoff["sender_id"], handoff["recipient_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Handoff not found")
        if handoff["status"] != "completed":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The handoff cheer is a thank-you after the cover is done — this handoff isn't completed yet.")
        if handoff["sender_id"] != user["_id"]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This cheer thanks your cover — it goes from the member who was covered to the one who covered.")
        receiver = await db.users.find_one({"_id": handoff["recipient_id"]})
    else:
        profile = await db.profiles.find_one({"slug": body.to_slug, "published": {"$ne": False}})
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
        receiver = await db.users.find_one({"_id": profile["owner_id"]})
    if receiver is None or receiver.get("disabled"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    result = await cheers_svc.send_cheer(db, user, receiver, post=post, handoff=handoff, note=body.note, day=today(request))
    request.state.audit_record = result["cheer_id"]
    return result


@router.get("/cheers/me")
async def my_cheers(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Your numbers, plainly: allowance on hand, bank cheers on hand, banked (lifetime), waiting, given — plus recent activity."""
    out = await cheers_svc.tallies(db, user, today(request))
    out["activity"] = await cheers_svc.activity(db, user["_id"])
    return out


@router.get("/admin/cheers/pairs")
async def cheers_pairs(weeks: int = 12, min_count: int = 4, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    """Pairs of members who cheer each other often, for a person to review (the farming watch)."""
    return await cheers_svc.pair_report(db, weeks=weeks, min_count=min_count)
