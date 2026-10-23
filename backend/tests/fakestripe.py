"""A stand-in for Stripe's REST API, for tests. Records every request and answers like Stripe would."""
import itertools
import json
import time
from urllib.parse import parse_qsl

import httpx

from app.stripe_api import sign

PRICES = {"starter": "price_starter", "full": "price_full"}
STRIPE_SETTINGS = dict(stripe_secret_key="sk_test_x", stripe_webhook_secret="whsec_test", stripe_connect_webhook_secret="whsec_connect", stripe_price_starter=PRICES["starter"], stripe_price_full=PRICES["full"])


class FakeStripe:
    def __init__(self):
        self.requests = []
        self.ids = itertools.count(1)
        self.subscriptions = {}
        self.fail = None  # set to a status code to make every call fail

    def transport(self):
        return httpx.MockTransport(self.handle)

    def _id(self, prefix):
        return f"{prefix}_{next(self.ids)}"

    def handle(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode())) if request.content else dict(request.url.params)
        path = request.url.path.removeprefix("/v1")
        self.requests.append({"method": request.method, "path": path, "form": form, "headers": dict(request.headers)})
        if self.fail:
            return httpx.Response(self.fail, json={"error": {"message": "boom"}})
        if path == "/customers":
            return httpx.Response(200, json={"id": self._id("cus")})
        if path.startswith("/checkout/sessions/") and path.endswith("/expire"):
            return httpx.Response(200, json={"id": path.split("/")[3], "status": "expired"})
        if path == "/checkout/sessions":
            return httpx.Response(200, json={"id": self._id("cs"), "url": f"https://checkout.stripe.test/{next(self.ids)}"})
        if path == "/billing_portal/sessions":
            return httpx.Response(200, json={"url": "https://billing.stripe.test/session"})
        if path.startswith("/subscriptions/"):
            sub_id = path.split("/")[2]
            sub = self.subscriptions[sub_id]
            if request.method == "POST":
                if "items[0][price]" in form:
                    sub["items"]["data"][0]["price"]["id"] = form["items[0][price]"]
                if "cancel_at_period_end" in form:
                    sub["cancel_at_period_end"] = form["cancel_at_period_end"] == "true"
            return httpx.Response(200, json=sub)
        if path == "/accounts":
            return httpx.Response(200, json={"id": self._id("acct"), "charges_enabled": False, "details_submitted": False})
        if path.startswith("/accounts/"):
            return httpx.Response(200, json={"id": path.split("/")[2], "charges_enabled": True, "details_submitted": True, "payouts_enabled": True})
        if path == "/account_links":
            return httpx.Response(200, json={"url": "https://connect.stripe.test/onboard"})
        return httpx.Response(404, json={"error": {"message": f"unhandled {path}"}})

    def subscription(self, user_id, customer, plan="starter", status="active", **extra):
        sub_id = self._id("sub")
        sub = {"id": sub_id, "object": "subscription", "customer": customer, "status": status, "metadata": {"user_id": user_id},
               "cancel_at_period_end": False, "current_period_end": 1_800_000_000,
               "items": {"data": [{"id": self._id("si"), "price": {"id": PRICES[plan]}}]}, **extra}
        self.subscriptions[sub_id] = sub
        return sub


def event(kind, obj, created=None, account=None, event_id=None):
    e = {"id": event_id or f"evt_{time.time_ns()}", "type": kind, "created": created or int(time.time()), "data": {"object": obj}}
    if account:
        e["account"] = account
    return e


def post_event(client, e, secret="whsec_test", path="/api/stripe/webhook"):
    payload = json.dumps(e).encode()
    return client.post(path, content=payload, headers={"stripe-signature": sign(payload, secret), "content-type": "application/json"})
