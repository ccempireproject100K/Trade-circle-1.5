"""Customer reviews.

A homeowner who came through the lead marketplace and chose a contractor gets
a lead in that contractor's inbox. Once the lead is won — or a job made from
it is done — the homeowner can leave one review for that lead from their
private request link (no account). Reviews are public on the contractor's
page unless a moderator hides them; the contractor can answer each one once
(editable) and can flag one for a moderator to look at.
"""

# Flagged reviews stay public while they wait for a moderator; only hidden
# ones disappear from the page and the average.
VISIBLE = ("published", "flagged")

MAX_STARS = 5
MAX_TEXT = 1000


def display_name(full_name: str) -> str:
    """How a reviewer is named in public: first name and last initial."""
    parts = (full_name or "").split()
    if not parts:
        return "A customer"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0].upper()}."


def review_view(review: dict) -> dict:
    """What the public sees of a review. Never the lead's contact details."""
    response = review.get("response")
    return {
        "id": review["_id"],
        "stars": review["stars"],
        "text": review["text"],
        "reviewer_name": review["reviewer_name"],
        "created_at": review["created_at"],
        "response": {"text": response["text"], "at": response["at"]} if response else None,
    }


async def summary_for(db, owner_id: str, latest: int = 3) -> dict:
    """Count, average and the newest visible reviews for one contractor."""
    visible = await db.reviews.find({"owner_id": owner_id, "status": {"$in": list(VISIBLE)}}).sort("created_at", -1).to_list(500)
    count = len(visible)
    average = round(sum(r["stars"] for r in visible) / count, 1) if count else None
    return {"count": count, "average": average, "latest": [review_view(r) for r in visible[:latest]]}


async def lead_for_bid(db, request_doc: dict, bid: dict) -> dict | None:
    """The inbox lead a marketplace choice created for this contractor."""
    return await db.quotes.find_one({"marketplace_request_id": request_doc["_id"], "owner_id": bid["contractor_id"]})


async def reviewable(db, lead: dict) -> bool:
    """A review opens once the lead is won, or a job made from it is done."""
    if lead.get("status") == "won":
        return True
    job = await db.jobs.find_one({"owner_id": lead["owner_id"], "quote_id": lead["_id"], "status": "done"}, {"_id": 1})
    return job is not None
