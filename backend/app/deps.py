from datetime import date, datetime, timezone

from fastapi import HTTPException, Request, status
from pydantic import BaseModel


def get_db(request: Request):
    return request.app.state.db


def today(request: Request) -> date:
    return request.app.state.today()


def now() -> datetime:
    return datetime.now(timezone.utc)


def public_doc(doc: dict) -> dict:
    """Rename Mongo's _id and drop owner bookkeeping before returning a record to its owner."""
    out = {k: v for k, v in doc.items() if k not in ("_id", "owner_id")}
    out["id"] = doc["_id"]
    return out


def partial_update(body: BaseModel, clearable: set[str]) -> dict:
    """Turn a partial-update body into a Mongo update: values are set, nulls on optional fields are unset."""
    sent = body.model_dump(mode="json", exclude_unset=True)
    required_nulls = sorted(k for k, v in sent.items() if v is None and k not in clearable)
    if required_nulls:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Cannot clear: {', '.join(required_nulls)}")
    update: dict = {"$set": {k: v for k, v in sent.items() if v is not None}}
    update["$set"]["updated_at"] = now()
    unset = {k: "" for k, v in sent.items() if v is None}
    if unset:
        update["$unset"] = unset
    return update
