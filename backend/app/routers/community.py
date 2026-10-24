"""Community posts, comments, photos, search and reporting, shared by every community feature."""
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import Field

from .. import cheers as cheers_svc
from .. import geo, photos, videos
from ..community import (
    DRAFTABLE,
    NEEDS_LOCATION,
    REPORT_REASONS,
    REVIEW_TOPICS,
    SUPPLY_CATEGORIES,
    CommentIn,
    Kind,
    PostIn,
    PostUpdate,
    MeetupUpdateIn,
    ReportIn,
    ResolveIn,
    RsvpIn,
    validate_fields,
)
from ..deps import get_db, now, today
from ..models import TRADES, Strict
from ..notices import notify_many
from ..security import current_user, require_role

router = APIRouter(prefix="/api", tags=["community"])

DEFAULT_RADIUS = 25
MAX_RADIUS = 250


@router.get("/community/meta")
async def meta():
    return {
        "kinds": [k.value for k in Kind],
        "trades": list(TRADES),
        "supply_categories": list(SUPPLY_CATEGORIES),
        "review_topics": list(REVIEW_TOPICS),
        "report_reasons": list(REPORT_REASONS),
    }


# --- photos ---


@router.post("/media/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(request: Request, file: UploadFile = File(...), user: dict = Depends(current_user), db=Depends(get_db)):
    """Upload a photo to attach to a post. Metadata (including GPS) is removed."""
    photo = await photos.ingest(request, file, user["_id"], "posts")
    await db.uploads.insert_one({"_id": photo["id"], "owner_id": user["_id"], **{k: v for k, v in photo.items() if k != "id"}, "created_at": now()})
    return {k: photo[k] for k in ("id", "image_url", "thumb_url", "width", "height")}


class VideoEditIn(Strict):
    start: Annotated[float, Field(ge=0, le=videos.MAX_SECONDS)] = 0.0
    end: Annotated[float, Field(gt=0, le=videos.MAX_SECONDS)] | None = None
    mute: bool = False


@router.post("/media/videos", status_code=status.HTTP_201_CREATED)
async def upload_video(request: Request, file: UploadFile = File(...), user: dict = Depends(current_user), db=Depends(get_db)):
    """A short clip for a walkthrough. Re-encoded so no metadata (including location) survives."""
    request.app.state.limiters["post"].check(f"video:{user['_id']}")
    clip = await videos.ingest(request, file, user["_id"])
    await db.uploads.insert_one({"_id": clip["id"], "owner_id": user["_id"], **{k: v for k, v in clip.items() if k != "id"}, "created_at": now()})
    return {k: v for k, v in clip.items() if k != "media_keys"}


@router.post("/media/videos/{video_id}/edit", status_code=status.HTTP_201_CREATED)
async def edit_video(video_id: str, body: VideoEditIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Trim and/or remove sound. Returns a new clip; the old one is deleted unless a published post uses it."""
    source = await db.uploads.find_one({"_id": video_id, "owner_id": user["_id"], "type": "video"})
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Clip not found")
    if body.end is not None and body.end <= body.start + 0.5:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The end has to come after the start.")
    request.app.state.limiters["post"].check(f"video:{user['_id']}")
    clip = await videos.edit(request, source, user["_id"], body.start, body.end, body.mute)
    await db.uploads.insert_one({"_id": clip["id"], "owner_id": user["_id"], **{k: v for k, v in clip.items() if k != "id"}, "created_at": now()})
    if not await db.posts.find_one({"photos.id": video_id, "status": {"$ne": "deleted"}}, {"_id": 1}):
        await db.uploads.delete_one({"_id": video_id})
        photos.discard(request, source)
    return {k: v for k, v in clip.items() if k != "media_keys"}


async def _attach_photos(db, user: dict, refs: list) -> list:
    if not refs:
        return []
    ids = [r["id"] for r in refs]
    owned = {u["_id"]: u async for u in db.uploads.find({"_id": {"$in": ids}, "owner_id": user["_id"]})}
    missing = [i for i in ids if i not in owned]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "One of those photos wasn't found. Please upload it again.")
    attached = []
    for r in refs:
        u = owned[r["id"]]
        item = {"id": r["id"], "group": r.get("group", ""), "image_url": u["image_url"], "thumb_url": u["thumb_url"]}
        if u.get("type") == "video":
            item.update(type="video", video_url=u["video_url"], duration=u.get("duration"), has_audio=u.get("has_audio"))
        attached.append(item)
    return attached


# --- shaping posts for display ---


async def authors(db, ids) -> dict:
    found = {}
    async for p in db.profiles.find({"owner_id": {"$in": list(set(ids))}}, {"owner_id": 1, "slug": 1, "business_name": 1, "trade": 1, "city": 1}):
        found[p["owner_id"]] = {"slug": p["slug"], "business_name": p["business_name"], "trade": p["trade"], "city": p["city"]}
    if found:
        # Banked cheers (lifetime earned) ride along as a small badge of standing — never a ranking.
        banked = await cheers_svc.banked_for(db, list(found))
        for owner_id, entry in found.items():
            entry["banked"] = banked.get(owner_id, 0)
    return found


REMOVED_SUPPLIER = {"removed": True, "name": "Supplier details removed"}


async def suppliers_by_id(db, ids) -> dict:
    found = {}
    async for s in db.suppliers.find({"_id": {"$in": [i for i in set(ids) if i]}}, {"name": 1, "status": 1}):
        found[s["_id"]] = REMOVED_SUPPLIER if s.get("status") == "removed" else {"id": s["_id"], "name": s["name"]}
    return found


def post_view(post: dict, author: dict | None, supplier: dict | None, viewer_id: str | None, distance: float | None = None) -> dict:
    view = {
        "id": post["_id"],
        "kind": post["kind"],
        "title": post.get("title", ""),
        "body": post.get("body", ""),
        "trade_tags": post.get("trade_tags", []),
        "category": post.get("category"),
        "location": {k: v for k, v in (post.get("location") or {}).items() if k in ("label", "city", "state", "zip")} or None,
        "supplier": supplier,
        "photos": [] if post.get("photos_hidden") else post.get("photos", []),
        "photos_hidden": bool(post.get("photos_hidden")),
        "fields": post.get("fields", {}),
        "featured": bool(post.get("featured")),
        "status": post["status"],
        "author": author or {"business_name": "Former member"},
        "mine": viewer_id == post["author_id"],
        "comment_count": post.get("comment_count", 0),
        "created_at": post["created_at"],
        "published_at": post.get("published_at"),
        "updated_at": post.get("updated_at"),
    }
    if distance is not None:
        view["distance_miles"] = round(distance, 1)
    if post["kind"] == Kind.meetup.value:
        view["meetup"] = {"updates": post.get("updates", []), "cancelled": post.get("cancelled")}
    return view


async def shape(db, posts: list, viewer_id: str | None, center: dict | None = None) -> list:
    who = await authors(db, [p["author_id"] for p in posts])
    sup = await suppliers_by_id(db, [p.get("supplier_id") for p in posts])
    cheer_counts: dict = {}
    if posts:
        async for c in db.cheers.find({"post_id": {"$in": [p["_id"] for p in posts]}}, {"post_id": 1}):
            cheer_counts[c["post_id"]] = cheer_counts.get(c["post_id"], 0) + 1
    meetups = [p["_id"] for p in posts if p["kind"] == Kind.meetup.value]
    rsvps: dict = {}
    if meetups:
        async for r in db.rsvps.find({"post_id": {"$in": meetups}}):
            row = rsvps.setdefault(r["post_id"], {"going": 0, "maybe": 0, "not_going": 0, "mine": None})
            row[r["response"]] += 1
            if r["user_id"] == viewer_id:
                row["mine"] = r["response"]
    out = []
    for p in posts:
        distance = geo.miles(center, p["location"]) if center and p.get("location", {}).get("lat") is not None else None
        view = post_view(p, who.get(p["author_id"]), sup.get(p.get("supplier_id")), viewer_id, distance)
        view["cheers"] = cheer_counts.get(p["_id"], 0)
        if "meetup" in view:
            view["meetup"]["rsvp"] = rsvps.get(p["_id"], {"going": 0, "maybe": 0, "not_going": 0, "mine": None})
        out.append(view)
    return out


# --- creating and editing ---


async def _supplier_ok(db, supplier_id: str | None) -> None:
    if supplier_id and not await db.suppliers.find_one({"_id": supplier_id, "status": {"$ne": "removed"}}, {"_id": 1}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")


def _ready_to_publish(post: dict) -> None:
    kind = Kind(post["kind"])
    if kind not in DRAFTABLE and not post.get("title", "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Add a short title first.")
    answered = any(isinstance(v, str) and v.strip() for v in post.get("fields", {}).values())
    if kind in DRAFTABLE and not (post.get("title", "").strip() or post.get("body", "").strip() or answered):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Answer at least one question before publishing.")
    if kind in NEEDS_LOCATION and not post.get("location"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, 'Add a ZIP code or "City, ST" so nearby members find it.')
    if kind == Kind.supplier_review and not post.get("supplier_id"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose which supplier this is about.")


@router.post("/posts", status_code=status.HTTP_201_CREATED)
async def create_post(body: PostIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    request.app.state.limiters["post"].check(user["_id"])
    await _supplier_ok(db, body.supplier_id)
    try:
        fields = validate_fields(body.kind, body.fields)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc).split("\n")[-1].strip() or "Check the details.")
    stamp = now()
    post = {
        "_id": uuid.uuid4().hex,
        "kind": body.kind.value,
        "author_id": user["_id"],
        "title": body.title.strip(),
        "body": body.body.strip(),
        "trade_tags": body.trade_tags,
        "category": body.category,
        "location": geo.resolve(body.location) if body.location.strip() else None,
        "supplier_id": body.supplier_id,
        "photos": await _attach_photos(db, user, [p.model_dump() for p in body.photos]),
        "fields": fields,
        "featured": body.featured and body.kind == Kind.project,
        "status": "draft",
        "comment_count": 0,
        "created_at": stamp,
        "updated_at": stamp,
    }
    if body.publish or body.kind not in DRAFTABLE:
        # Only walkthroughs and lessons are drafted; everything else is published when the member taps Post.
        _ready_to_publish(post)
        post["status"] = "published"
        post["published_at"] = stamp
    await db.posts.insert_one(post)
    request.state.audit_record = post["_id"]
    return (await shape(db, [post], user["_id"]))[0]


async def _own_post(db, user: dict, post_id: str) -> dict:
    post = await db.posts.find_one({"_id": post_id, "author_id": user["_id"], "status": {"$ne": "deleted"}})
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    return post


@router.patch("/posts/{post_id}")
async def update_post(post_id: str, body: PostUpdate, user: dict = Depends(current_user), db=Depends(get_db)):
    """Edit a draft or a published post. Used for draft autosave too."""
    post = await _own_post(db, user, post_id)
    if post["status"] == "hidden":
        raise HTTPException(status.HTTP_409_CONFLICT, "A moderator has hidden this post.")
    changes = body.model_dump(exclude_unset=True)
    update = {}
    for key in ("title", "body"):
        if key in changes and changes[key] is not None:
            update[key] = changes[key].strip()
    if changes.get("trade_tags") is not None:
        update["trade_tags"] = changes["trade_tags"]
    if "supplier_id" in changes:
        await _supplier_ok(db, changes["supplier_id"])
        update["supplier_id"] = changes["supplier_id"]
    if "category" in changes:
        update["category"] = changes["category"]
    if changes.get("location") is not None:
        update["location"] = geo.resolve(changes["location"]) if changes["location"].strip() else None
    if changes.get("photos") is not None:
        update["photos"] = await _attach_photos(db, user, changes["photos"])
    if changes.get("fields") is not None:
        try:
            update["fields"] = validate_fields(Kind(post["kind"]), {**post.get("fields", {}), **changes["fields"]})
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc).split("\n")[-1].strip())
    if changes.get("featured") is not None:
        update["featured"] = bool(changes["featured"]) and post["kind"] == Kind.project.value
    update["updated_at"] = now()
    merged = {**post, **update}
    if post["status"] == "published":
        _ready_to_publish(merged)
    await db.posts.update_one({"_id": post_id}, {"$set": update})
    return (await shape(db, [merged], user["_id"]))[0]


@router.post("/posts/{post_id}/publish")
async def publish_post(post_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    """Publishing is always this explicit step. Drafts are never published automatically."""
    post = await _own_post(db, user, post_id)
    if post["status"] != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only drafts can be published.")
    _ready_to_publish(post)
    stamp = now()
    await db.posts.update_one({"_id": post_id, "status": "draft"}, {"$set": {"status": "published", "published_at": stamp, "updated_at": stamp}})
    post.update(status="published", published_at=stamp)
    return (await shape(db, [post], user["_id"]))[0]


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(post_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    await _own_post(db, user, post_id)
    await db.posts.update_one({"_id": post_id}, {"$set": {"status": "deleted", "deleted_at": now()}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- reading and searching ---


@router.get("/posts")
async def search_posts(
    request: Request,
    kind: str = "",
    trade: str = "",
    category: str = "",
    supplier_id: str = "",
    q: str = "",
    near: str = "",
    radius: int = DEFAULT_RADIUS,
    upcoming: bool = False,
    limit: int = 30,
    user: dict = Depends(current_user),
    db=Depends(get_db),
):
    """Published posts, newest first. `kind` may list several kinds separated by commas."""
    # Filled openings and ones past their apply-by date drop out of search; the poster still sees them in their own posts.
    query: dict = {"status": "published", "fields.filled": {"$ne": True}, "$and": [{"$or": [{"fields.apply_by": None}, {"fields.apply_by": {"$gte": today(request).isoformat()}}]}]}
    if kind:
        kinds = [k for k in kind.split(",") if k in Kind._value2member_map_]
        query["kind"] = {"$in": kinds}
    if trade:
        query["trade_tags"] = trade
    if category:
        query["category"] = category
    if supplier_id:
        query["supplier_id"] = supplier_id
    if upcoming:
        # Meetups from today on; cancelled ones still show, marked, so people who planned to go see it.
        query["kind"] = Kind.meetup.value
        query["fields.starts_on"] = {"$gte": today(request).isoformat()}
    if q.strip():
        pattern = {"$regex": re.escape(q.strip()[:80]), "$options": "i"}
        query["$or"] = [{"title": pattern}, {"body": pattern}, {"fields.product": pattern}, {"fields.model": pattern}]
    center = None
    if near.strip():
        center = geo.resolve(near)
        radius = max(1, min(radius, MAX_RADIUS))
        bounds = geo.box(center, radius)
        query["location.lat"], query["location.lon"] = bounds["lat"], bounds["lon"]
    limit = max(1, min(limit, 100))
    order = [("fields.starts_on", 1), ("fields.starts_at", 1)] if upcoming else [("published_at", -1)]
    found = await db.posts.find(query).sort(order).limit(limit * (3 if center else 1)).to_list(None)
    if center:
        found = [p for p in found if geo.miles(center, p["location"]) <= radius][:limit]
    return {"near": center and {"label": center["label"], "radius": radius}, "posts": await shape(db, found, user["_id"], center)}


@router.get("/posts/mine")
async def my_posts(kind: str = "", post_status: str = "", user: dict = Depends(current_user), db=Depends(get_db)):
    query: dict = {"author_id": user["_id"], "status": {"$ne": "deleted"}}
    if kind:
        query["kind"] = kind
    if post_status:
        query["status"] = post_status
    found = await db.posts.find(query).sort("updated_at", -1).limit(100).to_list(100)
    return await shape(db, found, user["_id"])


async def visible_post(db, post_id: str, viewer_id: str) -> dict:
    post = await db.posts.find_one({"_id": post_id})
    if post is None or post["status"] == "deleted" or (post["status"] != "published" and post["author_id"] != viewer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    return post


@router.get("/posts/{post_id}")
async def get_post(post_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    post = await visible_post(db, post_id, user["_id"])
    view = (await shape(db, [post], user["_id"]))[0]
    comments = await db.comments.find({"post_id": post_id, "status": "published"}).sort("created_at", 1).to_list(500)
    who = await authors(db, [c["author_id"] for c in comments])
    view["comments"] = [
        {"id": c["_id"], "body": c["body"], "author": who.get(c["author_id"], {"business_name": "Former member"}), "mine": c["author_id"] == user["_id"], "created_at": c["created_at"]}
        for c in comments
    ]
    return view


# --- meetups ---


async def _meetup(db, post_id: str) -> dict:
    post = await db.posts.find_one({"_id": post_id, "kind": Kind.meetup.value, "status": "published"})
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Meetup not found")
    return post


@router.put("/posts/{post_id}/rsvp")
async def rsvp(post_id: str, body: RsvpIn, user: dict = Depends(current_user), db=Depends(get_db)):
    post = await _meetup(db, post_id)
    if post.get("cancelled"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This meetup was cancelled.")
    await db.rsvps.update_one(
        {"_id": f"{post_id}:{user['_id']}"},
        {"$set": {"post_id": post_id, "user_id": user["_id"], "response": body.response, "updated_at": now()}},
        upsert=True,
    )
    return (await shape(db, [post], user["_id"]))[0]["meetup"]


@router.get("/posts/{post_id}/attendees")
async def attendees(post_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    """Who said they're going or maybe. Shown to members, so the host and others know who to expect."""
    await _meetup(db, post_id)
    found = await db.rsvps.find({"post_id": post_id, "response": {"$in": ["going", "maybe"]}}).to_list(500)
    who = await authors(db, [r["user_id"] for r in found])
    return [{"member": who[r["user_id"]], "response": r["response"]} for r in found if r["user_id"] in who]


async def _tell_attendees(db, post: dict, text: str) -> None:
    found = await db.rsvps.find({"post_id": post["_id"], "response": {"$in": ["going", "maybe"]}}, {"user_id": 1}).to_list(500)
    await notify_many(db, [r["user_id"] for r in found if r["user_id"] != post["author_id"]], "meetup", text, f"/posts/{post['_id']}")


@router.post("/posts/{post_id}/updates", status_code=status.HTTP_201_CREATED)
async def meetup_update(post_id: str, body: MeetupUpdateIn, user: dict = Depends(current_user), db=Depends(get_db)):
    """The host posts a change or reminder. Everyone who said going or maybe is notified."""
    post = await _meetup(db, post_id)
    if post["author_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the host can post updates.")
    entry = {"at": now(), "text": body.text.strip()}
    await db.posts.update_one({"_id": post_id}, {"$push": {"updates": entry}, "$set": {"updated_at": entry["at"]}})
    await _tell_attendees(db, post, f"Update for \"{post['title']}\": {entry['text'][:120]}")
    return entry


@router.post("/posts/{post_id}/cancel")
async def cancel_meetup(post_id: str, body: MeetupUpdateIn, user: dict = Depends(current_user), db=Depends(get_db)):
    post = await _meetup(db, post_id)
    if post["author_id"] != user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the host can cancel.")
    if post.get("cancelled"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already cancelled.")
    cancelled = {"at": now(), "reason": body.text.strip()}
    await db.posts.update_one({"_id": post_id}, {"$set": {"cancelled": cancelled, "updated_at": cancelled["at"]}})
    await _tell_attendees(db, post, f"Cancelled: \"{post['title']}\". {cancelled['reason'][:120]}")
    return {"cancelled": cancelled}


# --- comments ---


@router.post("/posts/{post_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(post_id: str, body: CommentIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    request.app.state.limiters["comment"].check(user["_id"])
    post = await visible_post(db, post_id, user["_id"])
    if post["status"] != "published":
        raise HTTPException(status.HTTP_409_CONFLICT, "Publish the post before comments can be added.")
    comment = {"_id": uuid.uuid4().hex, "post_id": post_id, "author_id": user["_id"], "body": body.body.strip(), "status": "published", "created_at": now()}
    await db.comments.insert_one(comment)
    await db.posts.update_one({"_id": post_id}, {"$inc": {"comment_count": 1}})
    request.state.audit_record = comment["_id"]
    return {"id": comment["_id"], "body": comment["body"], "created_at": comment["created_at"], "mine": True}


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    comment = await db.comments.find_one_and_update(
        {"_id": comment_id, "author_id": user["_id"], "status": "published"}, {"$set": {"status": "deleted"}}
    )
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    await db.posts.update_one({"_id": comment["post_id"]}, {"$inc": {"comment_count": -1}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- reporting and moderation ---

COLLECTIONS = {"post": "posts", "comment": "comments", "supplier": "suppliers", "member": "profiles", "message": "messages", "listing": "break_room", "estimate": "outside_estimates", "lead": "marketplace"}


@router.post("/reports", status_code=status.HTTP_201_CREATED)
async def report(body: ReportIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    request.app.state.limiters["comment"].check(f"report:{user['_id']}")
    lookup = {"_id": body.target_id} if body.target_type != "member" else {"slug": body.target_id}
    if not await db[COLLECTIONS[body.target_type]].find_one(lookup, {"_id": 1}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nothing to report there.")
    existing = await db.reports.find_one({"target_type": body.target_type, "target_id": body.target_id, "reporter_id": user["_id"], "status": "open"})
    if existing:
        return {"id": existing["_id"], "status": "open"}
    item = {
        "_id": uuid.uuid4().hex,
        "target_type": body.target_type,
        "target_id": body.target_id,
        "reporter_id": user["_id"],
        "reason": body.reason,
        "note": body.note,
        "status": "open",
        "created_at": now(),
    }
    await db.reports.insert_one(item)
    request.state.audit_record = item["_id"]
    return {"id": item["_id"], "status": "open"}


async def flag_for_review(db, target_type: str, target_id: str, reason: str, note: str) -> None:
    """A moderation item raised by the system rather than a member."""
    await db.reports.insert_one(
        {"_id": uuid.uuid4().hex, "target_type": target_type, "target_id": target_id, "reporter_id": None, "reason": reason, "note": note, "status": "open", "created_at": now()}
    )


@router.get("/admin/reports")
async def list_reports(report_status: str = "open", user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    items = await db.reports.find({"status": report_status}).sort("created_at", 1).limit(200).to_list(200)
    out = []
    for r in items:
        target = await db[COLLECTIONS[r["target_type"]]].find_one({"_id": r["target_id"]} if r["target_type"] != "member" else {"slug": r["target_id"]})
        preview = None
        if target:
            preview = {k: target.get(k) for k in ("title", "body", "name", "business_name", "status", "kind", "official_url", "service", "source_url", "low", "high", "details") if target.get(k) is not None}
        out.append({"id": r["_id"], "target_type": r["target_type"], "target_id": r["target_id"], "reason": r["reason"], "note": r["note"], "from_system": r["reporter_id"] is None, "created_at": r["created_at"], "target": preview})
    return out


@router.post("/admin/reports/{report_id}/resolve")
async def resolve_report(report_id: str, body: ResolveIn, request: Request, user: dict = Depends(require_role("admin")), db=Depends(get_db)):
    r = await db.reports.find_one({"_id": report_id})
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    if r["target_type"] in ("post", "comment", "listing", "estimate", "lead") and body.action in ("hide", "restore"):
        coll = db[COLLECTIONS[r["target_type"]]]
        visible = {"listing": "active", "estimate": "active", "lead": "open"}.get(r["target_type"], "published")
        new_status = "hidden" if body.action == "hide" else visible
        await coll.update_one({"_id": r["target_id"], "status": {"$in": [visible, "hidden"]}}, {"$set": {"status": new_status, "moderated_at": now()}})
    await db.reports.update_one(
        {"_id": report_id}, {"$set": {"status": "resolved", "action": body.action, "resolution_note": body.note, "resolved_by": user["_id"], "resolved_at": now()}}
    )
    request.state.audit_record = report_id
    return {"id": report_id, "status": "resolved", "action": body.action}
