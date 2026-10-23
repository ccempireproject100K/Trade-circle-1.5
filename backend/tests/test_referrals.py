"""Referral program rules against Stripe events."""
import time
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import referrals
from app.main import create_app
from conftest import TODAY
from fakestripe import STRIPE_SETTINGS, FakeStripe, event, post_event

DAY = 86400


@pytest.fixture
def rc(settings, db):
    app = create_app(replace(settings, **STRIPE_SETTINGS), db=db, today=lambda: TODAY)
    app.state.stripe_transport = FakeStripe().transport()
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _signup(c, n, ref=None):
    body = {"email": f"r{n}@example.com", "password": "correct horse battery", "business_name": f"Shop {n}", "trade": "electrician", "city": "Austin"}
    if ref:
        body["ref"] = ref
    res = c.post("/api/auth/signup", json=body)
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}, res.json()["user"]


def _setup(c, db, referrer_tier="starter"):
    h, referrer = _signup(c, 0)
    c.portal.call(db.users.update_one, {"_id": referrer["id"]}, {"$set": {"tier": referrer_tier}})
    code = c.get("/api/referrals", headers=h).json()["code"]
    mh, member = _signup(c, 1, ref=code.lower())
    c.portal.call(db.users.update_one, {"_id": member["id"]}, {"$set": {"billing.customer_id": "cus_m", "tier": "full"}})
    return h, referrer, member


def _invoice(c, n, amount=900, when=None, charge=None):
    paid_at = when or int(time.time())
    return post_event(c, event("invoice.paid", {"id": f"in_{n}", "customer": "cus_m", "amount_paid": amount, "charge": charge or f"ch_{n}", "status_transitions": {"paid_at": paid_at}, "created": paid_at}))


def _age(c, db, days=61):
    c.portal.call(db.referral_earnings.update_many, {}, {"$set": {"earned_at": referrals.now() - timedelta(days=days)}})


def test_link_attaches_and_earns_a_quarter_once_per_invoice(rc, db):
    h, referrer, member = _setup(rc, db)
    me = rc.get("/api/referrals", headers=h).json()
    assert me["link"].endswith(f"/app/signup?ref={me['code']}") and me["referred"][0]["business_name"] == "Shop 1"
    _invoice(rc, 1)
    _invoice(rc, 1)  # Stripe resending the same invoice
    me = rc.get("/api/referrals", headers=h).json()
    assert len(me["earnings"]) == 1 and me["earnings"][0]["share_cents"] == 225
    assert me["summary"]["pending"] == 225 and me["summary"]["payable"] == 0  # still clearing
    _age(rc, db)
    assert rc.get("/api/referrals", headers=h).json()["summary"]["payable"] == 225


def test_no_self_referral_and_unknown_codes_ignored(rc, db):
    h, user = _signup(rc, 0)
    code = rc.get("/api/referrals", headers=h).json()["code"]
    _, other = _signup(rc, 2, ref="NOTACODE")
    assert rc.portal.call(db.users.find_one, {"_id": other["id"]}).get("referred_by") is None
    # Codes are tied to their owner.
    assert rc.portal.call(db.referral_codes.find_one, {"_id": code})["user_id"] == user["id"]


def test_only_members_in_good_standing_earn(rc, db):
    h, referrer, member = _setup(rc, db, referrer_tier="free")
    _invoice(rc, 1)
    e = rc.get("/api/referrals", headers=h).json()["earnings"][0]
    assert e["status"] == "not_eligible" and e["share_cents"] == 0


def test_six_month_window(rc, db):
    h, referrer, member = _setup(rc, db)
    start = int(time.time()) - 200 * DAY
    _invoice(rc, 1, when=start)
    _invoice(rc, 2, when=start + 100 * DAY)
    _invoice(rc, 3, when=start + 190 * DAY)  # past six months
    assert len(rc.get("/api/referrals", headers=h).json()["earnings"]) == 2


def test_refunds_reduce_the_earning(rc, db):
    h, referrer, member = _setup(rc, db)
    _invoice(rc, 1, amount=900, charge="ch_r")
    post_event(rc, event("charge.refunded", {"id": "ch_r", "amount_refunded": 400}))
    e = rc.get("/api/referrals", headers=h).json()["earnings"][0]
    assert (e["revenue_cents"], e["share_cents"]) == (500, 125)


def test_chargeback_claws_back_the_month_and_freezes_until_won(rc, db):
    h, referrer, member = _setup(rc, db)
    now_ts = int(time.time())
    _invoice(rc, 1, charge="ch_a", when=now_ts)
    _age(rc, db)
    post_event(rc, event("charge.dispute.created", {"id": "dp_1", "charge": "ch_a", "status": "needs_response"}))
    s = rc.get("/api/referrals", headers=h).json()["summary"]
    assert s["frozen"] and s["clawed_back"] == 225 and s["payable"] == 0
    post_event(rc, event("charge.dispute.closed", {"id": "dp_1", "charge": "ch_a", "status": "won"}))
    s = rc.get("/api/referrals", headers=h).json()["summary"]
    assert not s["frozen"] and s["clawed_back"] == 0 and s["payable"] == 225


def test_lost_chargeback_after_payout_comes_off_the_next_one(rc, db):
    h, referrer, member = _setup(rc, db)
    mod_h, mod = _signup(rc, 9)
    rc.portal.call(db.users.update_one, {"_id": mod["id"]}, {"$set": {"role": "admin"}})
    _invoice(rc, 1, charge="ch_a")
    _age(rc, db)
    assert rc.post(f"/api/admin/referrals/{referrer['id']}/payout", json={"note": "PayPal"}, headers=mod_h).json()["cents"] == 225
    post_event(rc, event("charge.dispute.created", {"id": "dp_1", "charge": "ch_a"}))
    assert rc.post(f"/api/admin/referrals/{referrer['id']}/payout", json={"note": "PayPal"}, headers=mod_h).status_code == 409  # frozen
    post_event(rc, event("charge.dispute.closed", {"id": "dp_1", "charge": "ch_a", "status": "lost"}))
    s = rc.get("/api/referrals", headers=h).json()["summary"]
    assert not s["frozen"] and s["adjustments"] == -225 and s["payable"] == 0
    # The next month's cleared earning is reduced by the clawback.
    _invoice(rc, 2, charge="ch_b", amount=1800, when=int(time.time()) + 40 * DAY)
    rc.portal.call(db.referral_earnings.update_one, {"_id": "inv:in_2"}, {"$set": {"earned_at": referrals.now() - timedelta(days=61)}})
    assert rc.get("/api/referrals", headers=h).json()["summary"]["payable"] == 450 - 225


def test_three_chargebacks_in_six_months_trigger_review(rc, db):
    h, referrer, member = _setup(rc, db)
    mod_h, mod = _signup(rc, 9)
    rc.portal.call(db.users.update_one, {"_id": mod["id"]}, {"$set": {"role": "admin"}})
    for n in range(3):
        _invoice(rc, n, charge=f"ch_{n}")
        post_event(rc, event("charge.dispute.created", {"id": f"dp_{n}", "charge": f"ch_{n}"}))
        post_event(rc, event("charge.dispute.closed", {"id": f"dp_{n}", "charge": f"ch_{n}", "status": "won"}))
    me = rc.get("/api/referrals", headers=h).json()
    assert me["under_review"] and me["summary"]["frozen"]
    row = rc.get("/api/admin/referrals", headers=mod_h).json()[0]
    assert row["under_review"] and row["business_name"] == "Shop 0"
    assert rc.get("/api/admin/referrals", headers=h).status_code == 403
    rc.post(f"/api/admin/referrals/{referrer['id']}/clear-review", headers=mod_h)
    assert rc.get("/api/referrals", headers=h).json()["summary"]["frozen"] is False
