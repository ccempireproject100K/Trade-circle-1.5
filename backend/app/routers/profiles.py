from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..cheers import banked_count
from ..deps import get_db, now, partial_update, public_doc, today
from ..models import TRADES, InsuranceIn, ProfileUpdate
from ..profiles import SECTIONS, full_view, landing_view, reflow_layout
from ..reviews import summary_for
from ..security import current_user, require_role
from ..team import acting_for

router = APIRouter(prefix="/api", tags=["profiles"])

CLEARABLE = {"tagline", "about", "service_area", "phone", "facetime", "brand_color"}


@router.get("/meta")
async def meta():
    """Choices the dashboard needs, so it never keeps its own copy of these lists."""
    return {"trades": list(TRADES), "sections": list(SECTIONS)}


async def own_profile(db, user: dict) -> dict:
    profile = await db.profiles.find_one({"owner_id": user["_id"]})
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return profile


async def portfolio_for(db, owner_id: str) -> list[dict]:
    return await db.portfolio.find({"owner_id": owner_id}).sort("position", 1).to_list(500)


async def featured_projects(db, owner_id: str) -> list[dict]:
    from ..profiles import FEATURED_PROJECTS

    query = {"author_id": owner_id, "kind": "project", "featured": True, "status": "published"}
    return await db.posts.find(query).sort("published_at", -1).limit(FEATURED_PROJECTS).to_list(FEATURED_PROJECTS)


async def team_on_profile(db, owner_id: str) -> list[dict]:
    """Teammates who chose to show their link to this business."""
    ids = [m["user_id"] async for m in db.team_members.find({"business_id": owner_id, "status": "active", "show_on_profile": True}, {"user_id": 1})]
    return [{"business_name": p["business_name"], "slug": p["slug"]} async for p in db.profiles.find({"owner_id": {"$in": ids}, "published": {"$ne": False}}, {"business_name": 1, "slug": 1})]


async def published_profile(db, slug: str) -> dict:
    """A profile the public may see: published, and its owner's account not disabled."""
    profile = await db.profiles.find_one({"slug": slug, "published": {"$ne": False}})
    if profile is not None:
        owner = await db.users.find_one({"_id": profile["owner_id"]}, {"disabled": 1})
        if owner is not None and not owner.get("disabled"):
            return profile
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")


@router.get("/me/profile")
async def get_my_profile(user: dict = Depends(acting_for("profile")), db=Depends(get_db)):
    return public_doc(await own_profile(db, user))


@router.put("/me/profile")
async def update_my_profile(
    body: ProfileUpdate, request: Request, user: dict = Depends(acting_for("profile")), db=Depends(get_db)
):
    profile = await own_profile(db, user)
    update = partial_update(body, CLEARABLE)
    if "layout" in update["$set"]:
        update["$set"]["layout"] = reflow_layout(update["$set"]["layout"])
    await db.profiles.update_one({"_id": profile["_id"], "owner_id": user["_id"]}, update)
    request.state.audit_record = profile["_id"]
    return public_doc(await own_profile(db, user))


@router.put("/me/insurance")
async def submit_insurance(
    body: InsuranceIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)
):
    """New or changed proof of insurance always goes back to pending review."""
    profile = await own_profile(db, user)
    insurance = {**body.model_dump(mode="json"), "verified": False, "submitted_at": now()}
    await db.profiles.update_one({"_id": profile["_id"]}, {"$set": {"insurance": insurance}})
    request.state.audit_record = profile["_id"]
    return {"status": "pending"}


@router.post("/admin/profiles/{profile_id}/insurance/verify")
async def verify_insurance(
    profile_id: str, user: dict = Depends(require_role("admin")), db=Depends(get_db)
):
    result = await db.profiles.update_one(
        {"_id": profile_id, "insurance": {"$exists": True}},
        {"$set": {"insurance.verified": True, "insurance.verified_by": user["_id"], "insurance.verified_at": now()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No insurance submitted for that profile")
    return {"status": "verified"}


@router.get("/p/{slug}")
async def public_landing(slug: str, request: Request, db=Depends(get_db)):
    profile = await published_profile(db, slug)
    portfolio = await portfolio_for(db, profile["owner_id"])
    page = landing_view(profile, portfolio, today(request), request.app.state.settings.recert_banner_days)
    page["reviews"] = await summary_for(db, profile["owner_id"], latest=3)
    page["cheers_banked"] = await banked_count(db, profile["owner_id"])
    return page


@router.get("/p/{slug}/full")
async def public_full(slug: str, request: Request, db=Depends(get_db)):
    profile = await published_profile(db, slug)
    portfolio = await portfolio_for(db, profile["owner_id"])
    projects = await featured_projects(db, profile["owner_id"])
    page = full_view(profile, portfolio, today(request), request.app.state.settings.recert_banner_days, projects)
    page["team"] = await team_on_profile(db, profile["owner_id"])
    page["reviews"] = await summary_for(db, profile["owner_id"], latest=10)
    page["cheers_banked"] = await banked_count(db, profile["owner_id"])
    return page
