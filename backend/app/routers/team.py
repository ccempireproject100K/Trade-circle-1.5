"""Team invitations, roles, permissions and removal. Rules are in app/team.py."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import EmailStr, Field

from ..deps import get_db, now
from ..models import Strict
from ..notices import notify
from ..security import current_user
from ..team import PERMISSIONS, ROLES, effective_permissions, member_id

router = APIRouter(prefix="/api/team", tags=["team"])

Permission = Literal["profile", "portfolio", "follow_ups", "jobs"]


class InviteIn(Strict):
    email: EmailStr
    role: Literal["admin", "contributor"]
    permissions: list[Permission] = Field(default_factory=list, max_length=len(PERMISSIONS))


class MemberUpdate(Strict):
    role: Literal["admin", "contributor"] | None = None
    permissions: list[Permission] | None = Field(default=None, max_length=len(PERMISSIONS))


class VisibilityIn(Strict):
    show_on_profile: bool


async def _names(db, ids) -> dict:
    return {p["owner_id"]: {"business_name": p["business_name"], "slug": p["slug"]} async for p in db.profiles.find({"owner_id": {"$in": list(ids)}}, {"owner_id": 1, "business_name": 1, "slug": 1})}


async def _log(db, business_id: str, actor_id: str, action: str, target_id: str, detail: dict | None = None) -> None:
    await db.team_log.insert_one({"business_id": business_id, "actor_id": actor_id, "action": action, "target_id": target_id, "detail": detail or {}, "at": now()})


async def _manager(db, business_id: str, user: dict) -> str:
    """The caller's standing in a business they manage: "owner" or "admin". Anyone else gets 404."""
    if business_id == user["_id"]:
        return "owner"
    me = await db.team_members.find_one({"_id": member_id(business_id, user["_id"]), "status": "active", "role": "admin"})
    if me is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    return "admin"


def _view(m: dict, names: dict) -> dict:
    return {
        "user_id": m["user_id"],
        "member": names.get(m["user_id"], {"business_name": "Former member"}),
        "role": m["role"],
        "permissions": effective_permissions(m),
        "status": m["status"],
        "invited_at": m["invited_at"],
        "accepted_at": m.get("accepted_at"),
    }


@router.get("/meta")
async def meta():
    return {"permissions": PERMISSIONS, "roles": list(ROLES)}


@router.get("/{business_id}/members")
async def members(business_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    standing = await _manager(db, business_id, user)
    found = await db.team_members.find({"business_id": business_id, "status": {"$in": ["invited", "active"]}}).sort("invited_at", 1).to_list(200)
    log = await db.team_log.find({"business_id": business_id}).sort("at", -1).limit(50).to_list(50)
    names = await _names(db, {m["user_id"] for m in found} | {e["actor_id"] for e in log} | {e["target_id"] for e in log} | {business_id})
    return {
        "business": names.get(business_id),
        "you_are": standing,
        "members": [_view(m, names) for m in found],
        "log": [{"action": e["action"], "actor": names.get(e["actor_id"], {}).get("business_name", "Former member"), "target": names.get(e["target_id"], {}).get("business_name", "Former member"), "detail": e["detail"], "at": e["at"]} for e in log],
    }


@router.post("/{business_id}/invite", status_code=status.HTTP_201_CREATED)
async def invite(business_id: str, body: InviteIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    standing = await _manager(db, business_id, user)
    if body.role == "admin" and standing != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can add admins.")
    request.app.state.limiters["message_request"].check(f"team:{user['_id']}")
    invitee = await db.users.find_one({"email": body.email.lower()})
    # Teammates need their own Trade Circle login; we don't create accounts for them.
    if invitee is None or invitee.get("disabled"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Trade Circle member uses that email. Ask them to sign up first, then invite them.")
    if invitee["_id"] == business_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "That's the owner's own account.")
    key = member_id(business_id, invitee["_id"])
    existing = await db.team_members.find_one({"_id": key, "status": {"$in": ["invited", "active"]}})
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "They're already on the team or invited.")
    member = {
        "_id": key, "business_id": business_id, "user_id": invitee["_id"], "role": body.role,
        "permissions": sorted(set(body.permissions)) if body.role == "contributor" else [],
        "status": "invited", "invited_by": user["_id"], "invited_at": now(), "show_on_profile": False,
    }
    await db.team_members.replace_one({"_id": key}, member, upsert=True)
    await _log(db, business_id, user["_id"], "invited", invitee["_id"], {"role": body.role, "permissions": effective_permissions(member)})
    names = await _names(db, [business_id])
    await notify(db, invitee["_id"], "team", f"{names.get(business_id, {}).get('business_name', 'A business')} invited you to their team as {'an admin' if body.role == 'admin' else 'a contributor'}.", "/team")
    return _view(member, await _names(db, [invitee["_id"]]))


@router.patch("/{business_id}/members/{user_id}")
async def update_member(business_id: str, user_id: str, body: MemberUpdate, user: dict = Depends(current_user), db=Depends(get_db)):
    standing = await _manager(db, business_id, user)
    if user_id == user["_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't change your own access.")
    member = await db.team_members.find_one({"_id": member_id(business_id, user_id), "status": {"$in": ["invited", "active"]}})
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on this team")
    touches_admin = member["role"] == "admin" or body.role == "admin"
    if touches_admin and standing != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can add or change admins.")
    role = body.role or member["role"]
    permissions = sorted(set(body.permissions if body.permissions is not None else member.get("permissions", []))) if role == "contributor" else []
    before = {"role": member["role"], "permissions": effective_permissions(member)}
    # Only change what was there when we looked, so two managers editing at once can't overwrite each other silently.
    result = await db.team_members.update_one({"_id": member["_id"], "role": member["role"], "permissions": member.get("permissions", [])}, {"$set": {"role": role, "permissions": permissions, "updated_at": now()}})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Someone else just changed this teammate. Reload and try again.")
    after = {"role": role, "permissions": effective_permissions({"role": role, "permissions": permissions})}
    await _log(db, business_id, user["_id"], "changed_access", user_id, {"before": before, "after": after})
    return _view({**member, "role": role, "permissions": permissions}, await _names(db, [user_id]))


@router.delete("/{business_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(business_id: str, user_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    """Managers remove teammates; anyone can leave. Takes effect on the teammate's next request."""
    member = await db.team_members.find_one({"_id": member_id(business_id, user_id), "status": {"$in": ["invited", "active"]}})
    if user_id != user["_id"]:
        standing = await _manager(db, business_id, user)
        if member is not None and member["role"] == "admin" and standing != "owner":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owner can remove admins.")
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on this team")
    await db.team_members.update_one({"_id": member["_id"]}, {"$set": {"status": "removed", "removed_at": now(), "removed_by": user["_id"], "show_on_profile": False}})
    await _log(db, business_id, user["_id"], "left" if user_id == user["_id"] else "removed", user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- the teammate's side ---


@router.get("/memberships")
async def my_memberships(user: dict = Depends(current_user), db=Depends(get_db)):
    found = await db.team_members.find({"user_id": user["_id"], "status": {"$in": ["invited", "active"]}}).to_list(100)
    names = await _names(db, {m["business_id"] for m in found})
    rows = [{"business_id": m["business_id"], "business": names.get(m["business_id"]), "role": m["role"], "permissions": effective_permissions(m), "status": m["status"], "show_on_profile": m.get("show_on_profile", False)} for m in found]
    has_team = await db.team_members.count_documents({"business_id": user["_id"], "status": {"$in": ["invited", "active"]}}, limit=1)
    return {"invitations": [r for r in rows if r["status"] == "invited"], "businesses": [r for r in rows if r["status"] == "active"], "has_team": bool(has_team)}


async def _respond(db, business_id: str, user: dict, accept: bool) -> dict:
    key = member_id(business_id, user["_id"])
    changes = {"status": "active", "accepted_at": now()} if accept else {"status": "declined", "declined_at": now()}
    member = await db.team_members.find_one_and_update({"_id": key, "status": "invited"}, {"$set": changes})
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No invitation to answer")
    await _log(db, business_id, user["_id"], "accepted" if accept else "declined", user["_id"])
    await notify(db, member["invited_by"], "team", f"{(await _names(db, [user['_id']])).get(user['_id'], {}).get('business_name', 'A member')} {'joined' if accept else 'declined'} your team invitation.", "/team")
    return {"status": changes["status"]}


@router.post("/invitations/{business_id}/accept")
async def accept(business_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    return await _respond(db, business_id, user, True)


@router.post("/invitations/{business_id}/decline")
async def decline(business_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    return await _respond(db, business_id, user, False)


@router.put("/memberships/{business_id}/visibility")
async def visibility(business_id: str, body: VisibilityIn, user: dict = Depends(current_user), db=Depends(get_db)):
    """Only the teammate decides whether their link to the business shows publicly."""
    result = await db.team_members.update_one({"_id": member_id(business_id, user["_id"]), "status": "active"}, {"$set": {"show_on_profile": body.show_on_profile}})
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on this team")
    await _log(db, business_id, user["_id"], "shown_on_profile" if body.show_on_profile else "hidden_from_profile", user["_id"])
    return {"show_on_profile": body.show_on_profile}
