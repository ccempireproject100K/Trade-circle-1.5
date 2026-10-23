"""Password hashing, tokens and access control."""
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_hasher = PasswordHasher()
# Verified against when the email is unknown, so login timing doesn't reveal which emails exist.
_DUMMY_HASH = _hasher.hash("trade-circle-timing-equalizer")

ROLES = ("contractor", "admin")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Pass None for an unknown user; the dummy check keeps the timing the same."""
    try:
        matched = _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return matched and password_hash is not None


def create_token(user: dict, secret: str, ttl_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user["_id"],
        # Bumping the user's token_version signs out every existing session.
        "ver": user.get("token_version", 0),
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub", "ver"]})
    except jwt.PyJWTError:
        return None


_bearer = HTTPBearer(auto_error=False)
_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"}
)

# The dashboard signs in with an HttpOnly cookie, so page scripts never hold the token.
SESSION_COOKIE = "tc_session"
# Cookie-authenticated writes must carry this header. Other sites can't add custom
# headers to a cross-site request without a CORS preflight, which we never grant.
CSRF_HEADER = "x-tc-csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def set_session_cookie(response: Response, token: str, settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.token_ttl_minutes * 60,
        httponly=True,
        secure=settings.enforce_https,
        # Lax, not Strict, so tapping the inbox link in a text alert arrives signed in.
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


async def current_user(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> dict:
    if creds is not None:
        token = creds.credentials
    else:
        token = request.cookies.get(SESSION_COOKIE)
        if token is None:
            raise _UNAUTHORIZED
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing CSRF header")
    claims = decode_token(token, request.app.state.settings.jwt_secret)
    if claims is None:
        raise _UNAUTHORIZED
    user = await request.app.state.db.users.find_one({"_id": claims["sub"]})
    if user is None or user.get("disabled") or user.get("token_version", 0) != claims["ver"]:
        raise _UNAUTHORIZED
    # Read by the audit middleware.
    request.state.user_id = user["_id"]
    return user


def require_role(*roles: str):
    """Role is read from the database on every request, so a demotion takes effect at once."""

    async def dependency(user: dict = Depends(current_user)) -> dict:
        if user.get("role") not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed")
        return user

    return dependency
