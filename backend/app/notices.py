"""In-app notifications, shown when a member opens Trade Circle.

These are for community activity (message requests, meetup changes). They are
never sent by email or text: outside alerts are a paid-plan feature for new
leads, and extending them to community activity is an open pricing decision.
"""
import uuid

from .deps import now


async def notify(db, user_id: str, kind: str, text: str, link: str) -> None:
    await db.notifications.insert_one(
        {"_id": uuid.uuid4().hex, "user_id": user_id, "kind": kind, "text": text, "link": link, "read": False, "created_at": now()}
    )


async def notify_many(db, user_ids, kind: str, text: str, link: str) -> None:
    stamp = now()
    docs = [{"_id": uuid.uuid4().hex, "user_id": u, "kind": kind, "text": text, "link": link, "read": False, "created_at": stamp} for u in set(user_ids)]
    if docs:
        await db.notifications.insert_many(docs)
