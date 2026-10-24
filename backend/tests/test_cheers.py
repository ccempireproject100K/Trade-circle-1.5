"""Slice 17 — the cheers economy.

Reciprocal by construction: a received cheer waits until its receiver gives
one (strict 1:1, oldest first, not necessarily back to the giver). Allowance
cheers are the monthly plan mint (Free 0 / Starter 30 / Full 90, wallet caps
100 / 200); collected cheers bank (lifetime standing + spendable), and a
bank cheer given lands double. Free members give on pass-through loan.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import cheers as cheers_svc
from app.main import create_app

PASSWORD = "correct horse battery"
DAY0 = date(2026, 10, 23)  # a Friday, the conftest "today"


class Clock:
    def __init__(self, day):
        self.day = day

    def __call__(self):
        return self.day


@pytest.fixture
def clock():
    return Clock(DAY0)


@pytest.fixture
def client(settings, db, clock):
    app = create_app(settings, db=db, today=clock)
    # These tests sign up many members and cheer a lot; lift those limits only.
    app.state.limiters["login"].limit = 1000
    app.state.limiters["cheer"].limit = 1000
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def member(client, db):
    counter = iter(range(1000))

    def _member(name, tier="free"):
        n = next(counter)
        res = client.post(
            "/api/auth/signup",
            json={"email": f"c{n}@example.com", "password": PASSWORD, "business_name": name, "trade": "electrician", "city": "Austin"},
        )
        assert res.status_code == 201, res.text
        headers = {"Authorization": f"Bearer {res.json()['token']}"}
        client.cookies.clear()
        user = res.json()["user"]
        if tier != "free":
            client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": tier}})
        slug = client.get("/api/me/profile", headers=headers).json()["slug"]
        return {"h": headers, "slug": slug, "id": user["id"], "name": name}

    return _member


def cheer(client, m, **body):
    return client.post("/api/cheers", headers=m["h"], json=body)


def mine(client, m):
    res = client.get("/api/cheers/me", headers=m["h"])
    assert res.status_code == 200, res.text
    return res.json()


def work_post(client, m, title="200A service upgrade"):
    res = client.post(
        "/api/posts",
        headers=m["h"],
        json={"kind": "project", "title": title, "fields": {"job": "Swapped a 100A panel for 200A"}, "publish": True},
    )
    assert res.status_code == 201, res.text
    return res.json()


def notices(client, m):
    return client.get("/api/notifications", headers=m["h"]).json()["items"]


def cheers_to(client, db, user_id):
    return client.portal.call(lambda: db.cheers.find({"receiver_id": user_id}).sort("created_at", 1).to_list(50))


# --- the core pairing ---


def test_post_cheer_waits_then_collects_when_receiver_gives_elsewhere(client, member, db):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric")  # free: no allowance, rides the economy on loan
    c = member("Charlie Electric")
    post = work_post(client, b)

    res = cheer(client, a, post_id=post["id"], note="Clean work")
    assert res.status_code == 201, res.text
    assert res.json()["sent"] == 1 and res.json()["funding"] == "allowance"

    # It waits. Nothing banked yet, and Bravo got the arrival alert.
    tallies = mine(client, b)
    assert (tallies["waiting"], tallies["banked"], tallies["given"]) == (1, 0, 0)
    assert any("cheered your post" in n["text"] and "waiting" in n["text"] for n in notices(client, b))

    # Bravo gives to Charlie — NOT back to Alpha — and Alpha's cheer collects.
    res = cheer(client, b, to_slug=c["slug"])
    assert res.status_code == 201, res.text
    assert res.json()["funding"] == "loan"
    assert res.json()["collected"]["from"] == "Alpha Electric"

    tallies = mine(client, b)
    assert (tallies["waiting"], tallies["banked"], tallies["collected"], tallies["given"]) == (0, 1, 1, 1)
    assert tallies["bank"] == 0  # the loan nets the wallet back to zero
    assert mine(client, c)["waiting"] == 1

    landed = cheers_to(client, db, b["id"])
    assert landed[0]["status"] == "collected" and landed[0]["unlocked_by"]
    assert landed[0]["collected_at"] is not None
    assert any("just landed" in n["text"] and "Alpha Electric" in n["text"] for n in notices(client, b))


def test_oldest_waiting_collects_first(client, member, db):
    a1 = member("Alpha Electric", tier="starter")
    a2 = member("Able Electric", tier="starter")
    b = member("Bravo Electric")
    c = member("Charlie Electric")
    post = work_post(client, b)
    assert cheer(client, a1, post_id=post["id"]).status_code == 201
    assert cheer(client, a2, post_id=post["id"]).status_code == 201
    assert mine(client, b)["waiting"] == 2

    assert cheer(client, b, to_slug=c["slug"]).status_code == 201
    landed = cheers_to(client, db, b["id"])
    assert [row["status"] for row in landed] == ["collected", "waiting"]
    assert landed[0]["giver_id"] == a1["id"]


def test_one_for_one_at_scale(client, member):
    b = member("Bravo Electric")
    targets = [member(f"Target {i}") for i in range(5)]
    for i in range(5):
        giver = member(f"Giver {i}", tier="starter")
        assert cheer(client, giver, to_slug=b["slug"]).status_code == 201
    assert mine(client, b)["waiting"] == 5

    # Five received means five gives to collect them all — no bulk unlock.
    for i, target in enumerate(targets):
        res = cheer(client, b, to_slug=target["slug"])
        assert res.status_code == 201, res.text
        tallies = mine(client, b)
        assert tallies["banked"] == i + 1 and tallies["waiting"] == 4 - i
        assert tallies["collected"] <= tallies["given"]
    # Everything collected and nothing left to fund a sixth give.
    one_more = member("One More")
    assert cheer(client, b, to_slug=one_more["slug"]).status_code == 422


def test_paid_member_collecting_through_allowance_banks_a_spendable_cheer(client, member):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric", tier="starter")
    c = member("Charlie Electric")
    assert cheer(client, b, to_slug=a["slug"]).status_code == 201
    res = cheer(client, a, to_slug=c["slug"])
    assert res.json()["funding"] == "allowance"
    tallies = mine(client, a)
    assert tallies["banked"] == 1 and tallies["bank"] == 1 and tallies["allowance"] == 29


# --- bank cheers land double ---


def test_bank_cheer_lands_double(client, member, db):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric")
    c = member("Charlie Electric")
    d = member("Delta Electric")
    # A waiting cheer for Alpha, straight into the collection (as if Bravo had cheered Alpha's page).
    client.portal.call(
        db.cheers.insert_one,
        {
            "_id": "seed1", "send_id": "seed", "giver_id": b["id"], "receiver_id": a["id"], "post_id": None,
            "handoff_id": None, "note": None, "funding": "allowance", "day": DAY0.isoformat(), "status": "waiting",
            "unlock_pair": None, "unlocked_by": None, "collected_at": None, "created_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
        },
    )
    res = cheer(client, a, to_slug=c["slug"])
    assert res.json()["funding"] == "allowance" and res.json()["collected"]["from"] == "Bravo Electric"
    assert mine(client, a)["bank"] == 1

    # Spend Alpha's allowance away; the next give comes out of the bank and lands double.
    client.portal.call(db.users.update_one, {"_id": a["id"]}, {"$set": {"cheers.allowance": 0}})
    res = cheer(client, a, to_slug=d["slug"])
    assert res.status_code == 201, res.text
    assert res.json()["funding"] == "bank" and res.json()["sent"] == 2
    assert mine(client, d)["waiting"] == 2
    assert mine(client, a)["bank"] == 0
    landed = cheers_to(client, db, d["id"])
    assert len(landed) == 2 and landed[0]["send_id"] == landed[1]["send_id"] and all(r["funding"] == "bank" for r in landed)


# --- the monthly allowance: adds, stacks, pauses at the cap ---


def test_allowance_refills_stack_and_pause_at_the_wallet_cap(db):
    async def go(db):
        await db.users.insert_one({"_id": "s1", "email": "s1@example.com", "tier": "starter", "created_at": datetime(2026, 10, 23, tzinfo=timezone.utc)})
        await db.users.insert_one({"_id": "f1", "email": "f1@example.com", "tier": "full", "created_at": datetime(2026, 10, 23, tzinfo=timezone.utc)})

        async def wallet(uid, day):
            user = await db.users.find_one({"_id": uid})
            return await cheers_svc.sync_wallet(db, user, day)

        assert (await wallet("s1", date(2026, 10, 23)))["allowance"] == 30  # first landing
        assert (await wallet("s1", date(2026, 11, 23)))["allowance"] == 60  # stacks
        assert (await wallet("s1", date(2026, 12, 23)))["allowance"] == 90
        # Nearly full: the refill tops up to the cap and no further.
        await db.users.update_one({"_id": "s1"}, {"$set": {"cheers.allowance": 95}})
        assert (await wallet("s1", date(2027, 1, 23)))["allowance"] == 100
        assert (await wallet("s1", date(2027, 2, 23)))["allowance"] == 100  # paused at the cap
        refills = [row["amount"] async for row in db.cheers_ledger.find({"user_id": "s1", "kind": "refill"}).sort("created_at", 1)]
        assert refills == [30, 30, 30, 5]

        assert (await wallet("f1", date(2026, 10, 23)))["allowance"] == 90
        assert (await wallet("f1", date(2026, 11, 23)))["allowance"] == 180
        assert (await wallet("f1", date(2026, 12, 23)))["allowance"] == 200  # Full cap

        free = {"_id": "g1", "email": "g1@example.com", "tier": "free", "created_at": datetime(2026, 10, 23, tzinfo=timezone.utc)}
        await db.users.insert_one(free)
        assert (await wallet("g1", date(2026, 12, 23)))["allowance"] == 0  # free members are never minted

    asyncio.run(go(db))


def test_upgrade_grants_the_new_allowance_right_away(db):
    async def go(db):
        await db.users.insert_one({"_id": "u1", "email": "u1@example.com", "tier": "free", "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc)})
        user = await db.users.find_one({"_id": "u1"})
        assert (await cheers_svc.sync_wallet(db, user, date(2026, 10, 23)))["allowance"] == 0
        await db.users.update_one({"_id": "u1"}, {"$set": {"tier": "starter"}})
        user = await db.users.find_one({"_id": "u1"})
        wallet = await cheers_svc.sync_wallet(db, user, date(2026, 10, 24))
        assert wallet["allowance"] == 30 and wallet["anchor_day"] == 24  # the cycle re-anchors to the upgrade day
        # A downgrade claws nothing back.
        await db.users.update_one({"_id": "u1"}, {"$set": {"tier": "free"}})
        user = await db.users.find_one({"_id": "u1"})
        assert (await cheers_svc.sync_wallet(db, user, date(2026, 11, 24)))["allowance"] == 30

    asyncio.run(go(db))


# --- free members: cannot initiate, can pass on ---


def test_free_member_cannot_initiate_but_can_pass_a_cheer_on(client, member):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric")
    c = member("Charlie Electric")
    res = cheer(client, b, to_slug=c["slug"])
    assert res.status_code == 422 and "don't have a cheer" in res.json()["detail"]

    assert cheer(client, a, to_slug=b["slug"]).status_code == 201
    res = cheer(client, b, to_slug=c["slug"])
    assert res.status_code == 201 and res.json()["funding"] == "loan"
    tallies = mine(client, b)
    assert (tallies["banked"], tallies["bank"], tallies["waiting"]) == (1, 0, 0)


# --- the caps ---


def test_daily_pair_cap(client, member, clock):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric")
    assert cheer(client, a, to_slug=b["slug"]).status_code == 201
    res = cheer(client, a, to_slug=b["slug"])
    assert res.status_code == 422 and "already cheered" in res.json()["detail"]
    clock.day = DAY0 + timedelta(days=1)
    assert cheer(client, a, to_slug=b["slug"]).status_code == 201
    assert mine(client, b)["waiting"] == 2  # both landed; the cap is on giving, not receiving


def test_unlock_pair_cap_third_pairing_in_a_week_unlocks_nothing(client, member, db, clock):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric", tier="starter")

    def pair():
        # Bravo cheers Alpha (Alpha waits), then Alpha cheers Bravo (Alpha's give, maybe an unlock).
        assert cheer(client, b, to_slug=a["slug"]).status_code == 201
        return cheer(client, a, to_slug=b["slug"])

    assert pair().json()["collected"] is not None  # unlock pairing 1
    clock.day = DAY0 + timedelta(days=1)
    assert pair().json()["collected"] is not None  # unlock pairing 2
    clock.day = DAY0 + timedelta(days=2)
    res = pair()
    assert res.status_code == 201 and res.json()["collected"] is None  # the give lands, but unlocks nothing

    tallies_a, tallies_b = mine(client, a), mine(client, b)
    assert (tallies_a["banked"], tallies_a["waiting"]) == (2, 1)
    assert (tallies_b["banked"], tallies_b["waiting"]) == (2, 1)
    third = [c for c in cheers_to(client, db, b["id"]) if c["giver_id"] == a["id"]][-1]
    assert third["unlock_pair"] is None and third["status"] == "waiting"


def test_self_cheer_is_rejected(client, member):
    a = member("Alpha Electric", tier="starter")
    post = work_post(client, a)
    assert cheer(client, a, to_slug=a["slug"]).status_code == 422
    assert cheer(client, a, post_id=post["id"]).status_code == 422


# --- notes ---


def test_note_is_the_receivers_to_read_only_once_it_collects(client, member):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric")
    c = member("Charlie Electric")
    assert cheer(client, a, to_slug=b["slug"], note="Great panel work").status_code == 201
    received = mine(client, b)["activity"]["received"]
    assert received[0]["note"] is None  # still waiting: the note hasn't landed yet
    assert cheer(client, b, to_slug=c["slug"]).status_code == 201
    received = mine(client, b)["activity"]["received"]
    assert received[0]["note"] == "Great panel work"
    assert any("Great panel work" in n["text"] for n in notices(client, b))
    assert cheer(client, a, to_slug=c["slug"], note="x" * 141).status_code == 422


# --- tallies, post counts and public standing ---


def test_tallies_post_counts_and_public_page_banked(client, member):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric")
    c = member("Charlie Electric")
    post = work_post(client, b)
    assert cheer(client, a, post_id=post["id"]).status_code == 201

    feed = client.get("/api/posts", headers=c["h"]).json()["posts"]
    shown = [p for p in feed if p["id"] == post["id"]][0]
    assert shown["cheers"] == 1 and shown["author"]["banked"] == 0

    assert cheer(client, b, to_slug=c["slug"]).status_code == 201
    feed = client.get("/api/posts", headers=c["h"]).json()["posts"]
    shown = [p for p in feed if p["id"] == post["id"]][0]
    assert shown["author"]["banked"] == 1

    page = client.get(f"/api/p/{b['slug']}").json()
    assert page["cheers_banked"] == 1
    for html in (client.get(f"/p/{b['slug']}").text, client.get(f"/p/{b['slug']}/full").text):
        assert "<strong>1</strong> banked cheer" in html


# --- the handoff prompt ---


def test_handoff_prompt_and_cheer(client, member, clock):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric")
    job = client.post(
        "/api/jobs", headers=a["h"],
        json={"title": "Panel upgrade", "customer_name": "Dana", "customer_phone": "+15125550199", "site_address": "12 Oak St"},
    ).json()["id"]
    handoff = client.post(
        "/api/handoffs", headers=a["h"],
        json={"job_id": job, "recipient_slug": b["slug"], "start_on": DAY0.isoformat()},
    ).json()
    assert client.post(f"/api/handoffs/{handoff['id']}/accept", headers=b["h"]).status_code == 200
    assert client.post(f"/api/handoffs/{handoff['id']}/complete", headers=b["h"]).status_code == 200

    views = client.get("/api/handoffs", headers=a["h"]).json()
    done = [v for v in views if v["id"] == handoff["id"]][0]
    assert done["cheer_prompt"]["to"]["slug"] == b["slug"]
    assert "cheer_sent" not in done

    # The recipient can't send this cheer; it thanks the cover, from the covered.
    assert cheer(client, b, handoff_id=handoff["id"]).status_code == 422
    res = cheer(client, a, handoff_id=handoff["id"])
    assert res.status_code == 201, res.text
    assert mine(client, b)["waiting"] == 1
    assert any("covering their job" in n["text"] for n in notices(client, b))

    views = client.get("/api/handoffs", headers=a["h"]).json()
    done = [v for v in views if v["id"] == handoff["id"]][0]
    assert done.get("cheer_sent") is True and "cheer_prompt" not in done


# --- the ledger reconciles, and cheers never touch the outbox ---


def test_ledger_conservation_and_no_outbox_traffic(client, member, db):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric")
    c = member("Charlie Electric")
    assert cheer(client, a, to_slug=b["slug"]).status_code == 201
    assert cheer(client, b, to_slug=c["slug"]).status_code == 201  # loan: collects Alpha's
    assert cheer(client, c, to_slug=a["slug"]).status_code == 201  # loan: collects Bravo's
    assert cheer(client, a, to_slug=c["slug"]).status_code == 201  # allowance: collects Charlie's, banks 1

    def sums(uid):
        rows = client.portal.call(lambda: db.cheers_ledger.find({"user_id": uid}).to_list(100))
        out = {}
        for row in rows:
            out[row["kind"]] = out.get(row["kind"], 0) + row["amount"]
        return out

    for m, expected_allowance, expected_bank in ((a, 28, 1), (b, 0, 0), (c, 0, 0)):
        led = sums(m["id"])
        allowance = led.get("refill", 0) - led.get("spend_allowance", 0)
        bank = led.get("collect", 0) - led.get("spend_bank", 0) - led.get("pass_through", 0)
        assert (allowance, bank) == (expected_allowance, expected_bank)
        tallies = mine(client, m)
        assert (tallies["allowance"], tallies["bank"]) == (allowance, bank)

    # In-app only: nothing was queued for email or text by any of this.
    assert client.portal.call(lambda: db.outbox.count_documents({})) == 0
    assert client.portal.call(lambda: db.cheers.count_documents({})) == 4


# --- moderation: the pair-frequency report ---


def test_admin_pair_frequency_report(client, member, db):
    a = member("Alpha Electric", tier="starter")
    b = member("Bravo Electric", tier="starter")
    staff = member("Trade Circle Staff")
    client.portal.call(db.users.update_one, {"_id": staff["id"]}, {"$set": {"role": "admin"}})

    assert cheer(client, a, to_slug=b["slug"]).status_code == 201
    assert cheer(client, b, to_slug=a["slug"]).status_code == 201

    assert client.get("/api/admin/cheers/pairs", headers=a["h"]).status_code == 403
    res = client.get("/api/admin/cheers/pairs", headers=staff["h"], params={"min_count": 1})
    assert res.status_code == 200, res.text
    pairs = {(p["from"]["business_name"], p["to"]["business_name"]): p for p in res.json()["pairs"]}
    row = pairs[("Bravo Electric", "Alpha Electric")]
    assert row["sends"] == 1 and row["unlocks"] == 1 and row["reverse_sends"] == 1 and row["review"] is True
    row = pairs[("Alpha Electric", "Bravo Electric")]
    assert row["sends"] == 1 and row["unlocks"] == 0


def test_cheers_need_a_membership_and_a_real_target(client, member):
    a = member("Alpha Electric", tier="starter")
    assert client.post("/api/cheers", json={"to_slug": "x"}).status_code == 401
    assert cheer(client, a, to_slug="no-such-member").status_code == 404
    assert cheer(client, a, post_id="nope").status_code == 404
    assert cheer(client, a).status_code == 422  # no target at all
    assert cheer(client, a, to_slug="x", post_id="y").status_code == 422  # two targets
