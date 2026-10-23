"""Audit log.

Every sensitive request is written to the `audit_log` collection: who, when,
what action and which record. The application only ever inserts into this
collection; no code path updates or deletes it. In production, the app's
database user should be granted `insert` and `find` only on `audit_log`, so
the append-only rule is enforced by the database as well.
"""
import logging
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

log = logging.getLogger("trade_circle.audit")

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Reads that expose other people's personal details (lead names and phone numbers).
SENSITIVE_READ_PREFIXES = ("/api/inbox", "/api/admin")


def is_sensitive(request: Request) -> bool:
    path = request.url.path
    if not path.startswith("/api/"):
        return False
    return request.method in MUTATING_METHODS or path.startswith(SENSITIVE_READ_PREFIXES)


def _affected_record(request: Request) -> str | None:
    explicit = getattr(request.state, "audit_record", None)
    if explicit:
        return explicit
    for value in request.path_params.values():
        return str(value)
    return None


def _action(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", request.url.path)
    return f"{request.method} {template}"


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not is_sensitive(request):
            return await call_next(request)
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            entry = {
                "_id": uuid.uuid4().hex,
                "user_id": getattr(request.state, "user_id", None),
                # Set when a teammate acts for a business: the business's account id.
                "on_behalf_of": getattr(request.state, "on_behalf_of", None),
                "timestamp": datetime.now(timezone.utc),
                "action": _action(request),
                "record_id": _affected_record(request),
                "status": status_code,
            }
            try:
                await request.app.state.db.audit_log.insert_one(entry)
            except Exception:  # never let a logging failure hide the original outcome
                log.exception("audit write failed: %s", entry)
