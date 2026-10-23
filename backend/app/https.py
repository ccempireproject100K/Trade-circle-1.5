from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


class HTTPSMiddleware(BaseHTTPMiddleware):
    """Redirect plain HTTP to HTTPS and add security headers."""

    async def dispatch(self, request: Request, call_next):
        settings = request.app.state.settings
        if settings.enforce_https:
            scheme = request.url.scheme
            if settings.trust_proxy:
                scheme = request.headers.get("x-forwarded-proto", scheme)
            if scheme != "https":
                return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
        response = await call_next(request)
        if settings.enforce_https:
            for name, value in SECURITY_HEADERS.items():
                # A route may set a stricter policy of its own (the public pages do).
                response.headers.setdefault(name, value)
        return response
