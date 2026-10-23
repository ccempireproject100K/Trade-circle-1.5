import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pymongo.errors import DuplicateKeyError

from ..deps import get_db, now
from ..models import LoginIn, PasswordChangeIn, SignupIn
from ..profiles import reflow_layout, unique_slug
from ..ratelimit import client_ip
from ..security import (
    clear_session_cookie,
    create_token,
    current_user,
    hash_password,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/api", tags=["auth"])

SLUG_ATTEMPTS = 5


def _user_view(user: dict) -> dict:
    return {"id": user["_id"], "email": user["email"], "role": user["role"], "tier": user["tier"]}


def _token(request: Request, response: Response, user: dict) -> str:
    """Issue a token for API clients and the same token as the dashboard's session cookie."""
    settings = request.app.state.settings
    token = create_token(user, settings.jwt_secret, settings.token_ttl_minutes)
    set_session_cookie(response, token, settings)
    return token


async def _create_profile(db, owner_id: str, body: SignupIn) -> None:
    """Retry on a slug collision: two same-named businesses can sign up at the same instant."""
    for _ in range(SLUG_ATTEMPTS):
        try:
            await db.profiles.insert_one(
                {
                    "_id": uuid.uuid4().hex,
                    "owner_id": owner_id,
                    "slug": await unique_slug(db, body.business_name),
                    "business_name": body.business_name,
                    "trade": body.trade,
                    "city": body.city,
                    "verified": False,
                    "published": True,
                    "licenses": [],
                    "layout": reflow_layout(None),
                    "created_at": now(),
                }
            )
            return
        except DuplicateKeyError:
            continue
    raise RuntimeError("could not allocate a profile slug")


@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: SignupIn, request: Request, response: Response, db=Depends(get_db)):
    request.app.state.limiters["login"].check(f"ip:{client_ip(request)}")
    user = {
        "_id": uuid.uuid4().hex,
        "email": body.email.lower(),
        "password_hash": hash_password(body.password),
        "role": "contractor",
        "tier": "free",
        "token_version": 0,
        "created_at": now(),
    }
    try:
        await db.users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists")
    try:
        await _create_profile(db, user["_id"], body)
    except Exception:
        # Never leave an account without a profile; the person can simply sign up again.
        await db.users.delete_one({"_id": user["_id"]})
        raise
    from .referrals import attach

    await attach(db, user["_id"], body.ref)
    request.state.user_id = user["_id"]
    request.state.audit_record = user["_id"]
    return {"token": _token(request, response, user), "user": _user_view(user)}


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response, db=Depends(get_db)):
    email = body.email.lower()
    limiter = request.app.state.limiters["login"]
    # Limit per address and per account, so neither one IP nor a botnet can grind one password.
    limiter.check(f"ip:{client_ip(request)}")
    limiter.check(f"email:{email}")
    user = await db.users.find_one({"email": email})
    if not verify_password(user["password_hash"] if user else None, body.password) or user.get("disabled"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    request.state.user_id = user["_id"]
    return {"token": _token(request, response, user), "user": _user_view(user)}


async def _bump_token_version(db, user: dict, extra: dict | None = None) -> dict:
    update = {"$inc": {"token_version": 1}}
    if extra:
        update["$set"] = extra
    await db.users.update_one({"_id": user["_id"]}, update)
    return await db.users.find_one({"_id": user["_id"]})


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout():
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.post("/auth/logout-everywhere", status_code=status.HTTP_204_NO_CONTENT)
async def logout_everywhere(user: dict = Depends(current_user), db=Depends(get_db)):
    await _bump_token_version(db, user)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.post("/auth/password")
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    response: Response,
    user: dict = Depends(current_user),
    db=Depends(get_db),
):
    """Changing the password signs out every other device; the caller gets a fresh token."""
    request.app.state.limiters["login"].check(f"email:{user['email']}")
    if not verify_password(user["password_hash"], body.current_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is wrong")
    updated = await _bump_token_version(db, user, {"password_hash": hash_password(body.new_password)})
    return {"token": _token(request, response, updated)}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return _user_view(user)
