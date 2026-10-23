"""Plans and subscription billing against a fake Stripe."""
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.stripe_api import encode, sign, verify
from conftest import TODAY
from fakestripe import STRIPE_SETTINGS, FakeStripe, event, post_event


@pytest.fixture
def stripe():
    return FakeStripe()


@pytest.fixture
def billing_client(settings, db, stripe):
    app = create_app(replace(settings, **STRIPE_SETTINGS), db=db, today=lambda: TODAY)
    app.state.stripe_transport = stripe.transport()
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _member(c, n=0):
    res = c.post("/api/auth/signup", json={"email": f"b{n}@example.com", "password": "correct horse battery", "business_name": f"Shop {n}", "trade": "electrician", "city": "Austin"})
    return {"Authorization": f"Bearer {res.json()['token']}"}, res.json()["user"]


def test_plans_list_built_and_unbuilt_features_honestly(client):
    plans = {p["key"]: p for p in client.get("/api/plans").json()}
    assert plans["starter"]["price_cents"] == 300 and plans["full"]["price_cents"] == 900
    starter = {a["key"]: a["built"] for a in plans["starter"]["adds"]}
    assert starter["lead_alerts"] is True and starter["google_business_profile"] is False


def test_billing_closed_until_configured(client, signup):
    h, _ = signup()
    assert client.get("/api/billing", headers=h).json()["ready"] is False
    res = client.post("/api/billing/checkout", json={"plan": "starter"}, headers=h)
    assert res.status_code == 503 and "aren't open yet" in res.json()["detail"]


def test_checkout_creates_customer_once_and_plan_changes_only_on_stripe_confirmation(billing_client, stripe, db):
    c = billing_client
    h, user = _member(c)
    res = c.post("/api/billing/checkout", json={"plan": "full"}, headers=h)
    assert res.status_code == 200 and res.json()["url"].startswith("https://checkout.stripe.test/")
    session = next(r for r in stripe.requests if r["path"] == "/checkout/sessions")["form"]
    assert session["mode"] == "subscription" and session["line_items[0][price]"] == "price_full" and session["subscription_data[metadata][user_id]"] == user["id"]
    assert session["success_url"].endswith("/app/plan?checkout=done")
    c.post("/api/billing/checkout", json={"plan": "full"}, headers=h)
    assert sum(r["path"] == "/customers" for r in stripe.requests) == 1
    # Nothing changes until Stripe says the subscription is active.
    assert c.get("/api/billing", headers=h).json()["plan"] == "free"
    customer = c.portal.call(db.users.find_one, {"_id": user["id"]})["billing"]["customer_id"]
    sub = stripe.subscription(user["id"], customer, "full")
    assert post_event(c, event("customer.subscription.created", sub)).status_code == 200
    me = c.get("/api/billing", headers=h).json()
    assert me["plan"] == "full" and me["subscribed"] and me["status"] == "active"
    assert c.get("/api/me", headers=h).json()["tier"] == "full"
    # A second checkout is refused: change the plan instead.
    assert c.post("/api/billing/checkout", json={"plan": "starter"}, headers=h).status_code == 409


def test_webhook_signature_and_duplicates(billing_client, stripe, db):
    c = billing_client
    h, user = _member(c)
    c.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"billing.customer_id": "cus_9"}})
    e = event("customer.subscription.created", stripe.subscription(user["id"], "cus_9", "starter"), event_id="evt_same")
    payload = json.dumps(e).encode()
    assert c.post("/api/stripe/webhook", content=payload, headers={"stripe-signature": sign(payload, "wrong")}).status_code == 400
    assert c.post("/api/stripe/webhook", content=payload, headers={"stripe-signature": sign(payload, "whsec_test", 1_000)}).status_code == 400  # too old
    assert c.post("/api/stripe/webhook", content=payload).status_code == 400
    assert post_event(c, e).json() == {"received": True}
    assert post_event(c, e).json() == {"received": True, "duplicate": True}
    assert c.get("/api/billing", headers=h).json()["plan"] == "starter"


def test_payment_problems_cancellation_and_out_of_order_events(billing_client, stripe, db):
    c = billing_client
    h, user = _member(c)
    sub = stripe.subscription(user["id"], "cus_1", "starter")
    post_event(c, event("customer.subscription.created", sub, created=100))
    post_event(c, event("customer.subscription.updated", {**sub, "status": "past_due"}, created=200))
    me = c.get("/api/billing", headers=h).json()
    assert me["plan"] == "starter" and me["payment_problem"] is True  # keeps the plan while Stripe retries
    # An older event arriving late is ignored.
    post_event(c, event("customer.subscription.updated", {**sub, "status": "canceled"}, created=150))
    assert c.get("/api/billing", headers=h).json()["plan"] == "starter"
    post_event(c, event("customer.subscription.deleted", {**sub, "status": "canceled"}, created=300))
    me = c.get("/api/billing", headers=h).json()
    assert me["plan"] == "free" and not me["subscribed"]
    # Free again: paid features stop.
    assert c.put("/api/me/alerts/digest", json={"on": True}, headers=h).status_code == 402


def test_change_plan_cancel_and_portal(billing_client, stripe, db):
    c = billing_client
    h, user = _member(c)
    c.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"billing.customer_id": "cus_1"}})
    sub = stripe.subscription(user["id"], "cus_1", "starter")
    post_event(c, event("customer.subscription.created", sub, created=100))
    up = c.post("/api/billing/change", json={"plan": "full"}, headers=h)
    assert up.status_code == 200 and up.json()["plan"] == "full"
    change = [r for r in stripe.requests if r["method"] == "POST" and r["path"] == f"/subscriptions/{sub['id']}"][-1]["form"]
    assert change["items[0][price]"] == "price_full" and change["proration_behavior"] == "create_prorations"
    down = c.post("/api/billing/change", json={"plan": "free"}, headers=h).json()
    assert down["plan"] == "full" and down["cancel_at_period_end"] is True  # keeps Full until the period ends
    assert c.post("/api/billing/portal", headers=h).json()["url"] == "https://billing.stripe.test/session"
    stripe.fail = 500
    assert c.post("/api/billing/change", json={"plan": "starter"}, headers=h).status_code == 502


def test_ending_an_old_subscription_doesnt_touch_the_current_one(billing_client, stripe):
    c = billing_client
    h, user = _member(c)
    old = stripe.subscription(user["id"], "cus_1", "starter")
    new = stripe.subscription(user["id"], "cus_1", "full")
    post_event(c, event("customer.subscription.created", new, created=100))
    post_event(c, event("customer.subscription.deleted", {**old, "status": "canceled"}, created=200))
    assert c.get("/api/billing", headers=h).json()["plan"] == "full"


def test_encoding_and_verification_helpers():
    assert encode({"a": {"b": 1}, "items": [{"price": "p"}], "flag": True, "skip": None}) == [("a[b]", "1"), ("items[0][price]", "p"), ("flag", "true")]
    payload = b'{"id": "evt_1"}'
    assert verify(payload, sign(payload, "s", 1000), "s", now=1100)["id"] == "evt_1"
    with pytest.raises(ValueError):
        verify(payload + b" ", sign(payload, "s", 1000), "s", now=1100)
