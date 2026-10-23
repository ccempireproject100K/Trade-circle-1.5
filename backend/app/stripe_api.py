"""A small Stripe client: the few REST calls Trade Circle makes, and webhook signature checks.

Calls go straight to Stripe's REST API with httpx, like the Twilio and Resend
senders. Tests swap in a fake transport (app.state.stripe_transport), so
nothing here needs a Stripe account until the keys are configured.
"""
import hashlib
import hmac
import json
import time

import httpx

API = "https://api.stripe.com/v1"
SIGNATURE_TOLERANCE = 300  # seconds, Stripe's recommended default


class StripeError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def encode(params: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's form encoding: {"a": {"b": 1}, "c": [x]} -> a[b]=1, c[0]=x."""
    out = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if value is None:
            continue
        if isinstance(value, dict):
            out += encode(value, name)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                out += encode(item, f"{name}[{i}]") if isinstance(item, dict) else [(f"{name}[{i}]", _scalar(item))]
        else:
            out.append((name, _scalar(value)))
    return out


def _scalar(v) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


class Stripe:
    def __init__(self, secret_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self.secret_key = secret_key
        self.transport = transport

    async def request(self, method: str, path: str, params: dict | None = None, account: str | None = None, idempotency_key: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.secret_key}"}
        if account:
            headers["Stripe-Account"] = account  # act on a contractor's connected account
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(base_url=API, transport=self.transport, timeout=20) as client:
            if method == "GET":
                res = await client.get(path, params=encode(params or {}), headers=headers)
            else:
                res = await client.request(method, path, data=dict(encode(params or {})) if params else None, headers=headers)
        try:
            body = res.json()
        except ValueError:
            body = {}
        if res.status_code >= 400:
            raise StripeError((body.get("error") or {}).get("message") or f"Stripe error {res.status_code}", res.status_code)
        return body


def verify(payload: bytes, header: str | None, secret: str, now: float | None = None) -> dict:
    """Check a webhook's Stripe-Signature header and return the event. Raises ValueError if it doesn't check out."""
    if not header or not secret:
        raise ValueError("missing signature")
    parts = [p.split("=", 1) for p in header.split(",") if "=" in p]
    timestamp = next((v for k, v in parts if k == "t"), None)
    signatures = [v for k, v in parts if k == "v1"]
    if not timestamp or not signatures:
        raise ValueError("malformed signature")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in signatures):
        raise ValueError("signature mismatch")
    if abs((now or time.time()) - int(timestamp)) > SIGNATURE_TOLERANCE:
        raise ValueError("signature too old")
    return json.loads(payload)


def sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Make a Stripe-Signature header. Used by tests and local checks."""
    t = timestamp or int(time.time())
    return f"t={t},v1={hmac.new(secret.encode(), f'{t}.'.encode() + payload, hashlib.sha256).hexdigest()}"
