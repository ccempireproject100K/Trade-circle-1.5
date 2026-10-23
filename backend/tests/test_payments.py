"""Customer payments through Stripe Connect, against a fake Stripe."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from conftest import TODAY
from fakestripe import STRIPE_SETTINGS, FakeStripe, event, post_event

CONNECT = "/api/stripe/connect-webhook"


@pytest.fixture
def stripe():
    return FakeStripe()


@pytest.fixture
def pay_client(settings, db, stripe):
    app = create_app(replace(settings, **STRIPE_SETTINGS), db=db, today=lambda: TODAY)
    app.state.stripe_transport = stripe.transport()
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:
        yield c


def _contractor(c, db, tier="full", n=0, connected=True):
    res = c.post("/api/auth/signup", json={"email": f"p{n}@example.com", "password": "correct horse battery", "business_name": f"Spark {n} Electric", "trade": "electrician", "city": "Austin"})
    h, user = {"Authorization": f"Bearer {res.json()['token']}"}, res.json()["user"]
    update = {"tier": tier}
    if connected:
        update["payments"] = {"account_id": f"acct_{n}", "charges_enabled": True, "details_submitted": True}
    c.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": update})
    return h, user


REQ = {"customer_name": "Pat Lee", "customer_email": "Pat@Example.com", "description": "Panel upgrade", "amount_cents": 250000, "note": "Thanks for choosing us!"}


def _token(link):
    return link.rsplit("/", 1)[1]


def test_full_plan_only_and_connect_flow(pay_client, db, stripe):
    c = pay_client
    h, _ = _contractor(c, db, tier="starter", connected=False)
    assert c.post("/api/payments/connect", headers=h).status_code == 402
    h, user = _contractor(c, db, n=1, connected=False)
    assert c.post("/api/payments/requests", json=REQ, headers=h).status_code == 409  # connect first
    res = c.post("/api/payments/connect", headers=h)
    assert res.status_code == 200 and res.json()["url"] == "https://connect.stripe.test/onboard"
    acct = next(r for r in stripe.requests if r["path"] == "/accounts")["form"]
    assert acct["type"] == "standard"
    # Back from onboarding: Stripe reports the account can take charges.
    me = c.get("/api/payments/account", headers=h).json()
    assert me["connected"] and me["charges_enabled"] and me["plan_allows"]


def test_closed_until_stripe_is_configured(client, db, signup):
    h, user = signup()
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": "full"}})
    assert client.post("/api/payments/connect", headers=h).status_code == 503
    assert client.get("/api/payments/account", headers=h).json()["ready"] is False


def test_card_payment_in_full(pay_client, db, stripe):
    c = pay_client
    h, user = _contractor(c, db)
    r = c.post("/api/payments/requests", json=REQ, headers=h)
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["due_cents"] == 250000 and req["status"] == "open" and req["customer_email"] == "pat@example.com"
    page = c.get(f"/pay/{_token(req['link'])}")
    assert page.status_code == 200 and "$2,500.00" in page.text and "Spark 0 Electric" in page.text and "Thanks for choosing us!" in page.text
    assert "checkout.stripe.com" in page.headers["content-security-policy"] and page.headers["referrer-policy"] == "no-referrer"
    assert 'name="amount"' not in page.text  # no partial payments on this one
    go = c.post(f"/pay/{_token(req['link'])}", data={"method": "card"})
    assert go.status_code == 303 and go.headers["location"].startswith("https://checkout.stripe.test/")
    sent = next(r for r in stripe.requests if r["path"] == "/checkout/sessions")
    assert sent["headers"]["stripe-account"] == "acct_0" and sent["form"]["line_items[0][price_data][unit_amount]"] == "250000"
    assert sent["form"]["payment_method_types[0]"] == "card" and "idempotency-key" in sent["headers"]
    session_id = c.portal.call(db.payment_slices.find_one, {})["checkout_session"]
    assert post_event(c, event("checkout.session.completed", {"id": session_id, "payment_status": "paid", "payment_intent": "pi_1", "customer": "cus_c"}, account="acct_0"), "whsec_connect", CONNECT).status_code == 200
    req = c.get("/api/payments/requests", headers=h).json()[0]
    assert req["status"] == "paid" and req["due_cents"] == 0 and req["payments"][0]["status"] == "succeeded"
    assert "Paid in full" in c.get(f"/pay/{_token(req['link'])}").text
    # The contractor is told.
    note = c.portal.call(db.notifications.find_one, {"kind": "payment"})
    assert "Pat Lee paid $2,500.00" in note["text"]


def test_partial_bank_payments_and_ledger(pay_client, db, stripe):
    c = pay_client
    h, user = _contractor(c, db)
    req = c.post("/api/payments/requests", json={**REQ, "allow_partial": True, "min_partial_cents": 50000}, headers=h).json()
    token = _token(req["link"])
    assert 'name="amount"' in c.get(f"/pay/{token}").text
    assert c.post(f"/pay/{token}", data={"method": "bank", "amount": "100.00"}).headers["location"] == f"/pay/{token}?error=amount"  # under the minimum
    assert c.post(f"/pay/{token}", data={"method": "bank", "amount": "9999"}).headers["location"] == f"/pay/{token}?error=amount"  # over the balance
    assert c.post(f"/pay/{token}", data={"method": "bank", "amount": "1,000.00"}).status_code == 303
    first = c.portal.call(db.payment_slices.find_one, {"amount_cents": 100000})
    assert next(r for r in stripe.requests if r["path"] == "/checkout/sessions")["form"]["payment_method_types[0]"] == "us_bank_account"
    # A bank payment starts processing; the balance due accounts for it.
    post_event(c, event("checkout.session.completed", {"id": first["checkout_session"], "payment_status": "unpaid", "payment_intent": "pi_b1"}, account="acct_0"), "whsec_connect", CONNECT)
    req = c.get("/api/payments/requests", headers=h).json()[0]
    assert (req["status"], req["processing_cents"], req["due_cents"]) == ("partly_paid", 100000, 150000)
    # It fails days later: the amount is due again.
    post_event(c, event("checkout.session.async_payment_failed", {"id": first["checkout_session"], "payment_intent": "pi_b1"}, account="acct_0"), "whsec_connect", CONNECT)
    req = c.get("/api/payments/requests", headers=h).json()[0]
    assert (req["status"], req["due_cents"]) == ("open", 250000)
    # Second try by card succeeds, then a partial refund in Stripe puts that amount back on the balance.
    c.post(f"/pay/{token}", data={"method": "card", "amount": "1000"})
    second = c.portal.call(db.payment_slices.find_one, {"status": "pending"})
    post_event(c, event("checkout.session.completed", {"id": second["checkout_session"], "payment_status": "paid", "payment_intent": "pi_c2"}, account="acct_0"), "whsec_connect", CONNECT)
    assert c.get("/api/payments/requests", headers=h).json()[0]["due_cents"] == 150000
    post_event(c, event("charge.refunded", {"payment_intent": "pi_c2", "amount_refunded": 20000}, account="acct_0"), "whsec_connect", CONNECT)
    req = c.get("/api/payments/requests", headers=h).json()[0]
    assert (req["paid_cents"], req["refunded_cents"], req["due_cents"]) == (100000, 20000, 170000)


def test_events_from_another_account_are_ignored(pay_client, db):
    c = pay_client
    h, _ = _contractor(c, db)
    req = c.post("/api/payments/requests", json=REQ, headers=h).json()
    c.post(f"/pay/{_token(req['link'])}", data={"method": "card"})
    sid = c.portal.call(db.payment_slices.find_one, {})["checkout_session"]
    post_event(c, event("checkout.session.completed", {"id": sid, "payment_status": "paid"}, account="acct_someone_else"), "whsec_connect", CONNECT)
    assert c.get("/api/payments/requests", headers=h).json()[0]["status"] == "open"
    # And platform-secret signatures don't work on the connect endpoint.
    assert post_event(c, event("checkout.session.completed", {"id": sid, "payment_status": "paid"}, account="acct_0"), "whsec_test", CONNECT).status_code == 400


def test_saved_card_and_returning_customer(pay_client, db, stripe):
    c = pay_client
    h, _ = _contractor(c, db)
    req = c.post("/api/payments/requests", json={**REQ, "offer_save_card": True}, headers=h).json()
    assert "Save my card with Spark 0 Electric" in c.get(f"/pay/{_token(req['link'])}").text
    c.post(f"/pay/{_token(req['link'])}", data={"method": "card", "save_card": "on"})
    form = [r for r in stripe.requests if r["path"] == "/checkout/sessions"][-1]["form"]
    assert form["payment_intent_data[setup_future_usage]"] == "off_session" and form["customer_email"] == "pat@example.com"
    sid = c.portal.call(db.payment_slices.find_one, {})["checkout_session"]
    post_event(c, event("checkout.session.completed", {"id": sid, "payment_status": "paid", "payment_intent": "pi_1", "customer": "cus_pat"}, account="acct_0"), "whsec_connect", CONNECT)
    # Next request to the same customer offers their saved card.
    req2 = c.post("/api/payments/requests", json={**REQ, "description": "Outlet repair", "amount_cents": 15000}, headers=h).json()
    c.post(f"/pay/{_token(req2['link'])}", data={"method": "card"})
    assert [r for r in stripe.requests if r["path"] == "/checkout/sessions"][-1]["form"]["customer"] == "cus_pat"


def test_cancelled_and_unknown_links(pay_client, db):
    c = pay_client
    h, _ = _contractor(c, db)
    req = c.post("/api/payments/requests", json=REQ, headers=h).json()
    token = _token(req["link"])
    assert c.post(f"/api/payments/requests/{req['id']}/cancel", headers=h).json()["status"] == "cancelled"
    assert "was closed by" in c.get(f"/pay/{token}").text
    assert c.post(f"/pay/{token}", data={"method": "card"}).headers["location"] == f"/pay/{token}?error=closed"
    assert c.get("/pay/not-a-real-token").status_code == 404
    # Someone else can't see or cancel these requests.
    other, _ = _contractor(c, db, n=5)
    assert c.get("/api/payments/requests", headers=other).json() == []


def test_downgraded_contractor_cant_take_new_payments(pay_client, db):
    c = pay_client
    h, user = _contractor(c, db)
    req = c.post("/api/payments/requests", json=REQ, headers=h).json()
    c.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": "starter"}})
    assert "can't take online payments right now" in c.get(f"/pay/{_token(req['link'])}").text
    assert c.post("/api/payments/requests", json=REQ, headers=h).status_code == 402


def test_a_new_attempt_closes_the_earlier_checkout(pay_client, db, stripe):
    c = pay_client
    h, _ = _contractor(c, db)
    req = c.post("/api/payments/requests", json=REQ, headers=h).json()
    token = _token(req["link"])
    c.post(f"/pay/{token}", data={"method": "card"})
    first = c.portal.call(db.payment_slices.find_one, {})
    c.post(f"/pay/{token}", data={"method": "card"})
    assert any(r["path"] == f"/checkout/sessions/{first['checkout_session']}/expire" and r["headers"]["stripe-account"] == "acct_0" for r in stripe.requests)
    assert c.portal.call(db.payment_slices.find_one, {"_id": first["_id"]})["status"] == "expired"
    assert c.portal.call(db.payment_slices.count_documents, {"status": "pending"}) == 1
