"""Customer reviews: the contractor's view, responses, flags and moderation.

Submission is public and lives with the marketplace request pages
(routers/marketplace.py), where the homeowner's private link is. Everything
here is signed-in: contractors read and answer their own reviews, and
moderators hide or restore reviews that were flagged.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..deps import get_db, now
from ..models import ReviewFlagIn, ReviewResponseIn
from ..reviews import summary_for
from ..security import current_user, require_role

router = APIRouter(prefix="/api", tags=["reviews"])


def _own_view(review: dict, lead: dict | None) -> dict:
    """What the contractor sees: the public fields plus status and context."""
    return {
        "id": review["_id"],
        "lead_id": review["lead_id"],
        "job_type": (lead or {}).get("job_type"),
        "stars": review["stars"],
        "text": review["text"],
        "reviewer_name": review["reviewer_name"],
        "status": review["status"],
        "created_at": review["created_at"],
        "response": review.get("response"),
        "flag_note": review.get("flag_note", ""),
        "flagged_at": review.get("flagged_at"),
    }


async def _own_review(db, user: dict, review_id: str) -> dict:
    review = await db.reviews.find_one({"_id": review_id, "owner_id": user["_id"]})
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    return review


@router.get("/reviews")
async def my_reviews(user: dict = Depends(current_user), db=Depends(get_db)):
    """Every review of this contractor, newest first, hidden ones included."""
    mine = await db.reviews.find({"owner_id": user["_id"]}).sort("created_at", -1).to_list(500)
    leads = {q["_id"]: q async for q in db.quotes.find({"_id": {"$in": [r["lead_id"] for r in mine]}}, {"job_type": 1})}
    summary = await summary_for(db, user["_id"], latest=0)
    return {
        "count": summary["count"],
        "average": summary["average"],
        "reviews": [_own_view(r, leads.get(r["lead_id"])) for r in mine],
    }


@router.post("/reviews/{review_id}/response")
async def respond(review_id: str, body: ReviewResponseIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Answer a review in public. Sending again edits the answer."""
    review = await _own_review(db, user, review_id)
    previous = review.get("response")
    response = {"text": body.text, "at": previous["at"] if previous else now(), "edited_at": now() if previous else None}
    await db.reviews.update_one({"_id": review_id, "owner_id": user["_id"]}, {"$set": {"response": response}})
    request.state.audit_record = review_id
    lead = await db.quotes.find_one({"_id": review["lead_id"]}, {"job_type": 1})
    return _own_view({**review, "response": response}, lead)


@router.post("/reviews/{review_id}/flag")
async def flag(review_id: str, body: ReviewFlagIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Ask a moderator to look at this review. It stays public until one acts."""
    review = await _own_review(db, user, review_id)
    if review["status"] == "hidden":
        raise HTTPException(status.HTTP_409_CONFLICT, "That review is already hidden.")
    update = {"flag_note": body.note, "flagged_at": now(), "flagged_by": user["_id"]}
    if review["status"] == "published":
        update["status"] = "flagged"
    await db.reviews.update_one({"_id": review_id, "owner_id": user["_id"]}, {"$set": update})
    request.state.audit_record = review_id
    lead = await db.quotes.find_one({"_id": review["lead_id"]}, {"job_type": 1})
    return _own_view({**review, **update}, lead)


# --- moderators ---


@router.get("/admin/reviews")
async def list_reviews(review_status: str = "flagged", user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    """The moderation queue: flagged reviews by default, oldest first."""
    query = {} if review_status == "all" else {"status": review_status}
    items = await db.reviews.find(query).sort("created_at", 1).limit(200).to_list(200)
    profiles = {p["owner_id"]: p async for p in db.profiles.find({"owner_id": {"$in": [r["owner_id"] for r in items]}}, {"business_name": 1, "slug": 1, "owner_id": 1})}
    out = []
    for r in items:
        profile = profiles.get(r["owner_id"]) or {}
        out.append({**_own_view(r, None), "business_name": profile.get("business_name"), "slug": profile.get("slug")})
    return out


@router.post("/admin/reviews/{review_id}/hide")
async def hide_review(review_id: str, request: Request, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    """Take a review off the contractor's page and out of the average."""
    result = await db.reviews.update_one(
        {"_id": review_id, "status": {"$ne": "hidden"}},
        {"$set": {"status": "hidden", "hidden_at": now(), "hidden_by": user["_id"]}},
    )
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found, or already hidden")
    request.state.audit_record = review_id
    return {"id": review_id, "status": "hidden"}


@router.post("/admin/reviews/{review_id}/unhide")
async def unhide_review(review_id: str, request: Request, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    """Put a hidden review back on the page."""
    result = await db.reviews.update_one(
        {"_id": review_id, "status": "hidden"},
        {"$set": {"status": "published", "unhidden_at": now(), "unhidden_by": user["_id"]}},
    )
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found, or not hidden")
    request.state.audit_record = review_id
    return {"id": review_id, "status": "published"}
