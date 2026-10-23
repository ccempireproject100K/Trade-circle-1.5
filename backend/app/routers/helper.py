"""The contractor AI helper and part lookup. Allowance and budget rules are in app/ai.py."""
import asyncio
import json
import re
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import Field

from .. import ai, media
from ..deps import get_db, today
from ..models import Strict
from ..photos import _read_limited
from ..security import current_user
from .community import shape

router = APIRouter(prefix="/api", tags=["helper"])

MAX_QUESTION = 2000
MAX_HISTORY = 6


class Turn(Strict):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=MAX_QUESTION)]


class AskIn(Strict):
    question: Annotated[str, Field(min_length=3, max_length=MAX_QUESTION)]
    # Earlier turns of this conversation, kept by the browser. Only the last few are sent.
    history: list[Turn] = Field(default_factory=list, max_length=MAX_HISTORY)


def helper_feature(settings) -> ai.Feature:
    return ai.Feature(
        key="helper",
        model=settings.ai_model if settings.ai_api_key else "",
        input_price=settings.ai_input_price,
        output_price=settings.ai_output_price,
        monthly_budget=settings.ai_monthly_budget,
        daily_limit=settings.ai_daily_limit,
        monthly_limit=settings.ai_monthly_limit,
        max_output_tokens=settings.ai_max_output_tokens,
    )


def parts_feature(settings) -> ai.Feature:
    return ai.Feature(
        key="parts",
        model=settings.ai_model if settings.ai_api_key else "",
        input_price=settings.ai_input_price,
        output_price=settings.ai_output_price,
        monthly_budget=settings.parts_monthly_budget,
        daily_limit=settings.parts_daily_limit,
        monthly_limit=settings.parts_monthly_limit,
        max_output_tokens=min(settings.ai_max_output_tokens, 1500),
    )


def provider(request: Request):
    """Built on first use so nothing is set up while AI is off. Tests put a fake on app.state."""
    state = request.app.state
    if getattr(state, "ai_provider", None) is None:
        from ..ai_provider import AnthropicProvider

        state.ai_provider = AnthropicProvider(state.settings.ai_api_key)
    return state.ai_provider


async def _status(request: Request, db, feature: ai.Feature, user: dict) -> dict:
    out = {"available": feature.ready, "timezone": request.app.state.settings.timezone, **await ai.allowance(db, feature, user["_id"], today(request))}
    if not feature.ready:
        out["notice"] = ai.community_message(None)
    elif out["remaining_today"] == 0:
        out["notice"] = ai.member_message(date.fromisoformat(out["refreshes_on"]))
    return out


def _refusal(exc: ai.Refused) -> HTTPException:
    # 429 when this member is out; 503 when the shared service can't take requests.
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS if exc.who == "member" else status.HTTP_503_SERVICE_UNAVAILABLE, {"message": str(exc), "who": exc.who})


@router.get("/helper")
async def helper_status(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    return await _status(request, db, helper_feature(request.app.state.settings), user)


@router.post("/helper/ask")
async def ask(body: AskIn, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    feature = helper_feature(request.app.state.settings)
    history = [t.model_dump() for t in body.history][-MAX_HISTORY:]
    if history and history[0]["role"] != "user":
        history = history[1:]
    chars = len(body.question) + sum(len(t["content"]) for t in history) + 2500  # plus the instructions

    async def call():
        return await provider(request).answer(feature.model, feature.max_output_tokens, history, body.question)

    try:
        answer = await ai.run(db, feature, user["_id"], today(request), chars, call)
    except ai.Refused as exc:
        raise _refusal(exc)
    except ai.ProviderFailed:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, {"message": "The AI helper couldn't answer that just now. This didn't use one of your questions.", "who": "provider"})
    return {"answer": answer, "status": await _status(request, db, feature, user)}


# --- part lookup ---


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@router.get("/parts/search")
async def part_search(q: str, request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    """Manual model or part-number search across members' equipment posts. Always available, no AI."""
    query = q.strip()[:80]
    if len(_norm(query)) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter at least 3 letters or numbers from the label.")
    pattern = {"$regex": re.escape(query), "$options": "i"}
    found = await db.posts.find(
        {"status": "published", "$or": [{"fields.model": pattern}, {"fields.product": pattern}, {"title": pattern}, {"body": pattern}]}
    ).sort("published_at", -1).limit(40).to_list(40)
    posts = await shape(db, found, user["_id"])
    exact = [p for p in posts if _norm(p["fields"].get("model", "")) == _norm(query)]
    exact_ids = {p["id"] for p in exact}
    return {
        "query": query,
        "exact": exact,  # the model field matches what was typed, ignoring spaces and dashes
        "mentions": [p for p in posts if p["id"] not in exact_ids],
        "inquiry": f"Hi, do you carry or can you order {query}? If so, what's the price and when could I pick it up? Thanks.",
        "note": "Matches come from members' posts. Price, stock and compatibility aren't confirmed; check with the supplier.",
    }


@router.get("/parts/photo")
async def part_photo_status(request: Request, user: dict = Depends(current_user), db=Depends(get_db)):
    return await _status(request, db, parts_feature(request.app.state.settings), user)


@router.post("/parts/photo")
async def part_photo(request: Request, file: UploadFile = File(...), note: str = Form("", max_length=300), user: dict = Depends(current_user), db=Depends(get_db)):
    """Read a label photo. Off until its allowance and budget are approved; manual search works meanwhile."""
    feature = parts_feature(request.app.state.settings)
    if not feature.ready:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, {"message": "Photo identification isn't turned on yet. Type the model or part number from the label instead.", "who": "community"})
    data = await _read_limited(file)
    try:
        jpeg = (await asyncio.to_thread(media.process, data))["full"]  # metadata removed, resized; not stored
    except media.BadImage as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))

    async def call():
        return await provider(request).read_part(feature.model, feature.max_output_tokens, jpeg, note.strip())

    try:
        raw = await ai.run(db, feature, user["_id"], today(request), len(note) + 1200, call, images=1)
    except ai.Refused as exc:
        raise _refusal(exc)
    except ai.ProviderFailed:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, {"message": "We couldn't read that photo just now. This didn't use one of your lookups.", "who": "provider"})
    try:
        result = json.loads(raw)
    except ValueError:
        result = {"label_text": [], "matches": [], "need_more": raw[:500]}
    return {
        "label_text": result.get("label_text", []),
        "exact": [m for m in result.get("matches", []) if m.get("basis") == "read_from_label"],
        "possible": [m for m in result.get("matches", []) if m.get("basis") != "read_from_label"],
        "need_more": result.get("need_more", ""),
        "note": "Read by AI from your photo. Confirm the model on the label yourself. Price, stock and compatibility aren't known.",
        "status": await _status(request, db, feature, user),
    }
