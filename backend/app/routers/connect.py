"""Member-to-member contact: consent-first messaging, blocking, mentoring and notifications.

Nobody can message a member until that member accepts a request. Either side
can block the other, which stops requests and messages both ways.
"""
import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import Field

from ..deps import get_db, now
from ..models import Strict
from ..notices import notify
from ..security import current_user
from .community import authors

router = APIRouter(prefix="/api", tags=["connect"])

CONTACT_METHODS = {"messages": "Trade Circle messages", "phone": "Phone call", "text": "Text message", "email": "Email"}


class RequestIn(Strict):
    to_slug: Annotated[str, Field(min_length=1, max_length=80)]
    note: Annotated[str, Field(min_length=1, max_length=1000)]
    context: Literal["general", "mentoring", "post"] = "general"
    post_id: Annotated[str, Field(max_length=64)] | None = None


class MessageIn(Strict):
    body: Annotated[str, Field(min_length=1, max_length=4000)]


class MentoringIn(Strict):
    seeking: bool = False
    offering: bool = False
    topics: list[Annotated[str, Field(min_length=2, max_length=40)]] = Field(min_length=1, max_length=8)
    experience: Annotated[str, Field(max_length=1000)] = ""
    contact_method: Literal["messages", "phone", "text", "email"] = "messages"
    # Phone number or email, shared only with members whose introduction this member accepts.
    contact_value: Annotated[str, Field(max_length=120)] = ""
    availability: Annotated[str, Field(max_length=300)] = ""
    paused: bool = False


async def _member_by_slug(db, slug: str) -> dict:
    profile = await db.profiles.find_one({"slug": slug}, {"owner_id": 1})
    user = profile and await db.users.find_one({"_id": profile["owner_id"]}, {"disabled": 1, "mentoring": 1})
    if not user or user.get("disabled"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return user


async def blocked_between(db, a: str, b: str) -> bool:
    return bool(await db.blocks.find_one({"_id": {"$in": [f"{a}:{b}", f"{b}:{a}"]}}, {"_id": 1}))


async def _name(db, user_id: str) -> str:
    profile = await db.profiles.find_one({"owner_id": user_id}, {"business_name": 1})
    return profile["business_name"] if profile else "A member"


# --- message requests ---


@router.post("/messages/requests", status_code=status.HTTP_201_CREATED)
async def send_request(body: RequestIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    request.app.state.limiters["message_request"].check(user["_id"])
    to = await _member_by_slug(db, body.to_slug)
    if to["_id"] == user["_id"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That's you.")
    if await blocked_between(db, user["_id"], to["_id"]):
        # Same answer either way, so a blocked member can't tell they were blocked.
        raise HTTPException(status.HTTP_409_CONFLICT, "This member isn't accepting messages from you.")
    if body.context == "mentoring":
        mentoring = to.get("mentoring") or {}
        if not (mentoring.get("offering") or mentoring.get("seeking")) or mentoring.get("paused"):
            raise HTTPException(status.HTTP_409_CONFLICT, "This member isn't available for mentoring right now.")
    existing = await db.conversations.find_one({"members": {"$all": [user["_id"], to["_id"]]}}, {"_id": 1})
    if existing:
        return {"conversation_id": existing["_id"], "status": "accepted"}
    pending = await db.message_requests.find_one({"from_id": user["_id"], "to_id": to["_id"], "status": "pending"}, {"_id": 1})
    if pending:
        return {"id": pending["_id"], "status": "pending"}
    item = {
        "_id": uuid.uuid4().hex,
        "from_id": user["_id"],
        "to_id": to["_id"],
        "note": body.note.strip(),
        "context": body.context,
        "post_id": body.post_id,
        "status": "pending",
        "created_at": now(),
    }
    await db.message_requests.insert_one(item)
    request.state.audit_record = item["_id"]
    label = "a mentoring introduction" if body.context == "mentoring" else "to message you"
    await notify(db, to["_id"], "message_request", f"{await _name(db, user['_id'])} asked {label}.", "/messages")
    return {"id": item["_id"], "status": "pending"}


@router.get("/messages/requests")
async def list_requests(user: dict = Depends(current_user), db=Depends(get_db)):
    incoming = await db.message_requests.find({"to_id": user["_id"], "status": "pending"}).sort("created_at", -1).to_list(100)
    outgoing = await db.message_requests.find({"from_id": user["_id"]}).sort("created_at", -1).limit(50).to_list(50)
    who = await authors(db, [r["from_id"] for r in incoming] + [r["to_id"] for r in outgoing])

    def view(r: dict, other: str) -> dict:
        # "Not accepted" rather than "declined": softer, and doesn't reveal a block.
        state = "not accepted" if r["status"] == "declined" else r["status"]
        member = who.get(other, {"business_name": "Former member"})
        return {"id": r["_id"], "member": member, "note": r["note"], "context": r["context"], "status": state, "created_at": r["created_at"]}

    return {"incoming": [view(r, r["from_id"]) for r in incoming], "outgoing": [view(r, r["to_id"]) for r in outgoing]}


async def _pending_for_me(db, request_id: str, user: dict) -> dict:
    item = await db.message_requests.find_one({"_id": request_id, "to_id": user["_id"], "status": "pending"})
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return item


@router.post("/messages/requests/{request_id}/accept")
async def accept_request(request_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    item = await _pending_for_me(db, request_id, user)
    stamp = now()
    conv = {"_id": uuid.uuid4().hex, "members": [item["from_id"], user["_id"]], "context": item["context"], "created_at": stamp, "last_message_at": stamp}
    await db.conversations.insert_one(conv)
    await db.message_requests.update_one({"_id": request_id}, {"$set": {"status": "accepted", "responded_at": stamp, "conversation_id": conv["_id"]}})
    messages = [{"_id": uuid.uuid4().hex, "conversation_id": conv["_id"], "sender_id": item["from_id"], "body": item["note"], "created_at": item["created_at"]}]
    mentoring = user.get("mentoring") or {}
    if item["context"] == "mentoring" and mentoring.get("contact_method") != "messages" and mentoring.get("contact_value"):
        # Accepting the introduction is the mentor's consent to share their preferred contact.
        method = CONTACT_METHODS[mentoring["contact_method"]]
        messages.append({"_id": uuid.uuid4().hex, "conversation_id": conv["_id"], "sender_id": None, "body": f"Prefers {method.lower()}: {mentoring['contact_value']}", "created_at": stamp})
    await db.messages.insert_many(messages)
    await notify(db, item["from_id"], "request_accepted", f"{await _name(db, user['_id'])} accepted your request.", f"/messages/{conv['_id']}")
    return {"conversation_id": conv["_id"]}


@router.post("/messages/requests/{request_id}/decline")
async def decline_request(request_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    await _pending_for_me(db, request_id, user)
    await db.message_requests.update_one({"_id": request_id}, {"$set": {"status": "declined", "responded_at": now()}})
    return {"status": "declined"}


# --- conversations ---


async def _conversation(db, conv_id: str, user: dict) -> dict:
    conv = await db.conversations.find_one({"_id": conv_id, "members": user["_id"]})
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


@router.get("/messages/conversations")
async def list_conversations(user: dict = Depends(current_user), db=Depends(get_db)):
    convs = await db.conversations.find({"members": user["_id"]}).sort("last_message_at", -1).to_list(100)
    others = [next(m for m in c["members"] if m != user["_id"]) for c in convs]
    who = await authors(db, others)
    out = []
    for c, other in zip(convs, others):
        last = await db.messages.find({"conversation_id": c["_id"]}).sort("created_at", -1).limit(1).to_list(1)
        out.append({"id": c["_id"], "member": who.get(other, {"business_name": "Former member"}), "context": c["context"], "last": last[0]["body"][:120] if last else "", "last_message_at": c["last_message_at"]})
    return out


@router.get("/messages/conversations/{conv_id}")
async def read_conversation(conv_id: str, user: dict = Depends(current_user), db=Depends(get_db)):
    conv = await _conversation(db, conv_id, user)
    other = next(m for m in conv["members"] if m != user["_id"])
    msgs = await db.messages.find({"conversation_id": conv_id}).sort("created_at", 1).to_list(1000)
    return {
        "id": conv_id,
        "member": (await authors(db, [other])).get(other, {"business_name": "Former member"}),
        "blocked": await blocked_between(db, user["_id"], other),
        "i_blocked": bool(await db.blocks.find_one({"_id": f"{user['_id']}:{other}"}, {"_id": 1})),
        "messages": [{"id": m["_id"], "body": m["body"], "mine": m["sender_id"] == user["_id"], "system": m["sender_id"] is None, "created_at": m["created_at"]} for m in msgs],
    }


@router.post("/messages/conversations/{conv_id}", status_code=status.HTTP_201_CREATED)
async def send_message(conv_id: str, body: MessageIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    request.app.state.limiters["comment"].check(f"msg:{user['_id']}")
    conv = await _conversation(db, conv_id, user)
    other = next(m for m in conv["members"] if m != user["_id"])
    if await blocked_between(db, user["_id"], other):
        raise HTTPException(status.HTTP_409_CONFLICT, "Messages are turned off in this conversation.")
    msg = {"_id": uuid.uuid4().hex, "conversation_id": conv_id, "sender_id": user["_id"], "body": body.body.strip(), "created_at": now()}
    await db.messages.insert_one(msg)
    await db.conversations.update_one({"_id": conv_id}, {"$set": {"last_message_at": msg["created_at"]}})
    await notify(db, other, "message", f"New message from {await _name(db, user['_id'])}.", f"/messages/{conv_id}")
    return {"id": msg["_id"], "body": msg["body"], "mine": True, "created_at": msg["created_at"]}


# --- blocking ---


@router.post("/members/{slug}/block", status_code=status.HTTP_204_NO_CONTENT)
async def block(slug: str, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    other = await _member_by_slug(db, slug)
    if other["_id"] == user["_id"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That's you.")
    await db.blocks.update_one(
        {"_id": f"{user['_id']}:{other['_id']}"},
        {"$setOnInsert": {"blocker_id": user["_id"], "blocked_id": other["_id"], "created_at": now()}},
        upsert=True,
    )
    # Their pending requests to you disappear quietly.
    await db.message_requests.update_many({"from_id": other["_id"], "to_id": user["_id"], "status": "pending"}, {"$set": {"status": "declined", "responded_at": now()}})
    request.state.audit_record = other["_id"]
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/members/{slug}/block", status_code=status.HTTP_204_NO_CONTENT)
async def unblock(slug: str, user: dict = Depends(current_user), db=Depends(get_db)):
    other = await _member_by_slug(db, slug)
    await db.blocks.delete_one({"_id": f"{user['_id']}:{other['_id']}"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- mentoring ---


def _mentoring_view(m: dict | None) -> dict | None:
    if not m:
        return None
    return {k: m.get(k) for k in ("seeking", "offering", "topics", "experience", "contact_method", "contact_value", "availability", "paused")}


@router.get("/me/mentoring")
async def my_mentoring(user: dict = Depends(current_user)):
    return {"mentoring": _mentoring_view(user.get("mentoring"))}


@router.put("/me/mentoring")
async def set_mentoring(body: MentoringIn, user: dict = Depends(current_user), db=Depends(get_db)):
    if not (body.seeking or body.offering):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose Looking for a mentor, Willing to help, or both. To stop, remove your mentoring status.")
    if body.contact_method != "messages" and not body.contact_value.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Add the phone number or email to share once you accept an introduction.")
    data = {**body.model_dump(), "topics": sorted({t.strip().lower() for t in body.topics}), "updated_at": now()}
    await db.users.update_one({"_id": user["_id"]}, {"$set": {"mentoring": data}})
    return {"mentoring": _mentoring_view(data)}


@router.delete("/me/mentoring", status_code=status.HTTP_204_NO_CONTENT)
async def remove_mentoring(user: dict = Depends(current_user), db=Depends(get_db)):
    await db.users.update_one({"_id": user["_id"]}, {"$unset": {"mentoring": ""}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mentoring")
async def find_mentoring(mode: Literal["offering", "seeking"] = "offering", topic: str = "", trade: str = "", user: dict = Depends(current_user), db=Depends(get_db)):
    """Members who chose to take part. Volunteers, not certified by Trade Circle."""
    query: dict = {f"mentoring.{mode}": True, "mentoring.paused": {"$ne": True}, "_id": {"$ne": user["_id"]}, "disabled": {"$ne": True}}
    if topic.strip():
        query["mentoring.topics"] = {"$regex": re.escape(topic.strip().lower()[:40])}
    found = await db.users.find(query, {"mentoring": 1}).limit(100).to_list(100)
    blocked = {b["blocked_id"] async for b in db.blocks.find({"blocker_id": user["_id"]})} | {b["blocker_id"] async for b in db.blocks.find({"blocked_id": user["_id"]})}
    found = [u for u in found if u["_id"] not in blocked]
    who = await authors(db, [u["_id"] for u in found])
    out = []
    for u in found:
        member = who.get(u["_id"])
        if not member or (trade and member["trade"] != trade):
            continue
        m = u["mentoring"]
        out.append({"member": member, "topics": m["topics"], "experience": m["experience"], "availability": m["availability"], "prefers": CONTACT_METHODS[m["contact_method"]], "seeking": m["seeking"], "offering": m["offering"]})
    return out


# --- notifications ---


@router.get("/notifications")
async def notifications(user: dict = Depends(current_user), db=Depends(get_db)):
    items = await db.notifications.find({"user_id": user["_id"]}).sort("created_at", -1).limit(50).to_list(50)
    return {
        "unread": await db.notifications.count_documents({"user_id": user["_id"], "read": False}),
        "items": [{"id": n["_id"], "kind": n["kind"], "text": n["text"], "link": n["link"], "read": n["read"], "created_at": n["created_at"]} for n in items],
    }


@router.post("/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(user: dict = Depends(current_user), db=Depends(get_db)):
    await db.notifications.update_many({"user_id": user["_id"], "read": False}, {"$set": {"read": True}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
