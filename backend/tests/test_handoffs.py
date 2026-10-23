import asyncio
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import handoffs as rules
from app.main import create_app

PASSWORD = "correct horse battery"
WED = date(2026, 10, 21)  # a Wednesday; this week runs Mon Oct 19 to Sun Oct 25


class Clock:
    def __init__(self, day):
        self.day = day

    def __call__(self):
        return self.day


@pytest.fixture
def clock():
    return Clock(WED)


@pytest.fixture
def client(settings, db, clock):
    app = create_app(settings, db=db, today=clock)
    # These tests sign up many members from one address; lift that limit only.
    app.state.limiters["login"].limit = 1000
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def member(client):
    counter = iter(range(1000))

    def _member(name):
        n = next(counter)
        res = client.post(
            "/api/auth/signup",
            json={"email": f"m{n}@example.com", "password": PASSWORD, "business_name": name, "trade": "electrician", "city": "Austin"},
        )
        assert res.status_code == 201, res.text
        headers = {"Authorization": f"Bearer {res.json()['token']}"}
        client.cookies.clear()
        slug = client.get("/api/me/profile", headers=headers).json()["slug"]
        return {"h": headers, "slug": slug, "id": res.json()["user"]["id"]}

    return _member


def job(client, m, title="Panel upgrade", **extra):
    body = {"title": title, "customer_name": "Dana Homeowner", "customer_phone": "+15125550199", "site_address": "12 Oak St", **extra}
    return client.post("/api/jobs", headers=m["h"], json=body).json()["id"]


def hand_off(client, sender, recipient, start=WED, **extra):
    return client.post(
        "/api/handoffs",
        headers=sender["h"],
        json={"job_id": job(client, sender), "recipient_slug": recipient["slug"], "start_on": start.isoformat(), **extra},
    )


@pytest.fixture
def crew(member):
    return [member(name) for name in ("Alpha Electric", "Bravo Electric", "Charlie Electric", "Delta Electric")]


# --- weekly total and same-recipient limits ---


def test_weekly_total_limit_is_three(client, crew):
    a, b, c, d = crew
    assert [hand_off(client, a, r).status_code for r in (b, c, d)] == [201, 201, 201]
    res = hand_off(client, a, b)
    assert res.status_code == 409
    msg = res.json()["detail"]
    assert "all 3 handoffs for this week" in msg
    assert "Monday October 26 at 12:00 AM" in msg
    assert "outside Trade Circle" in msg
    allowance = client.get("/api/handoffs/allowance", headers=a["h"]).json()
    assert (allowance["used"], allowance["remaining"], allowance["at_limit"]) == (3, 0, True)
    assert allowance["resets_at"] == "2026-10-26T00:00:00-05:00"


def test_same_recipient_limit_is_two(client, crew):
    a, b, c, _ = crew
    assert [hand_off(client, a, b).status_code for _ in range(2)] == [201, 201]
    res = hand_off(client, a, b)
    assert res.status_code == 409 and "already sent 2 handoffs to this member" in res.json()["detail"]
    # The third weekly slot is still free for someone else.
    assert hand_off(client, a, c).status_code == 201


def test_blocked_attempts_do_not_use_a_slot(client, crew):
    a, b, c, _ = crew
    hand_off(client, a, b)
    hand_off(client, a, b)
    hand_off(client, a, b)  # refused
    assert client.get("/api/handoffs/allowance", headers=a["h"]).json()["used"] == 2


def test_allowance_resets_next_monday(client, clock, crew):
    a, b, c, d = crew
    for r in (b, c, d):
        hand_off(client, a, r)
    clock.day = date(2026, 10, 25)  # Sunday: still this week
    assert hand_off(client, a, b, start=clock.day).status_code == 409
    clock.day = date(2026, 10, 26)  # Monday: new week
    assert hand_off(client, a, b, start=clock.day).status_code == 201
    assert client.get("/api/handoffs/allowance", headers=a["h"]).json()["used"] == 1


def test_declined_and_withdrawn_give_the_slot_back(client, crew):
    a, b, c, d = crew
    first = hand_off(client, a, b).json()
    second = hand_off(client, a, c).json()
    hand_off(client, a, d)
    client.post(f"/api/handoffs/{first['id']}/decline", headers=b["h"])
    client.post(f"/api/handoffs/{second['id']}/withdraw", headers=a["h"])
    allowance = client.get("/api/handoffs/allowance", headers=a["h"]).json()
    assert allowance["used"] == 1
    assert hand_off(client, a, b).status_code == 201


def test_other_features_still_work_at_the_limit(client, crew):
    a, b, c, d = crew
    for r in (b, c, d):
        hand_off(client, a, r)
    assert client.post("/api/jobs", headers=a["h"], json={"title": "Still works"}).status_code == 201
    assert client.get("/api/inbox", headers=a["h"]).status_code == 200
    assert client.put("/api/me/profile", headers=a["h"], json={"tagline": "Still works"}).status_code == 200
    assert client.get(f"/p/{a['slug']}").status_code == 200


def test_limit_holds_under_simultaneous_requests(db):
    async def go():
        attempts = [rules.reserve_slot(db, "sender", f"r{i}", WED, "America/Chicago") for i in range(8)]
        results = await asyncio.gather(*attempts, return_exceptions=True)
        return sum(r is None for r in results)

    assert asyncio.run(go()) == 3


# --- vacation dates and the 14-day maximum ---


def vacation(client, m, start, end, note="Family trip"):
    return client.post("/api/me/vacations", headers=m["h"], json={"start_on": start, "end_on": end, "note": note})


def test_vacation_dates_are_checked(client, member):
    a = member("Alpha Electric")
    assert vacation(client, a, "2026-10-25", "2026-10-24").status_code == 422  # ends before it starts
    assert vacation(client, a, "2026-10-01", "2026-10-10").status_code == 422  # already over
    assert vacation(client, a, "2026-10-22", "2026-11-05").status_code == 422  # 15 days
    assert vacation(client, a, "2026-10-22", "2026-10-30", note="").status_code == 422  # note required
    res = vacation(client, a, "2026-10-22", "2026-11-04")  # exactly 14 days
    assert res.status_code == 201 and res.json()["days"] == 14


def test_overlapping_and_back_to_back_vacations_cannot_pass_fourteen_days(client, member):
    a = member("Alpha Electric")
    assert vacation(client, a, "2026-10-21", "2026-10-30").status_code == 201  # 10 days
    back_to_back = vacation(client, a, "2026-10-31", "2026-11-05")  # would make 16 in a row
    assert back_to_back.status_code == 422 and "16 days in a row" in back_to_back.json()["detail"]
    assert vacation(client, a, "2026-10-25", "2026-11-04").status_code == 422  # overlaps, 15 in a row
    assert vacation(client, a, "2026-10-31", "2026-11-03").status_code == 201  # joins to exactly 14
    assert vacation(client, a, "2026-11-04", "2026-11-04").status_code == 422  # would be day 15
    listed = client.get("/api/me/vacations", headers=a["h"]).json()
    assert listed["max_days"] == 14 and len(listed["vacations"]) == 2


def test_continuous_span_merges_chains():
    d = date.fromisoformat
    existing = [(d("2026-11-01"), d("2026-11-03")), (d("2026-11-05"), d("2026-11-06"))]
    assert rules.continuous_span(existing, (d("2026-11-04"), d("2026-11-04"))) == (d("2026-11-01"), d("2026-11-06"))
    assert rules.continuous_span(existing, (d("2026-11-09"), d("2026-11-10"))) == (d("2026-11-09"), d("2026-11-10"))


# --- vacation exception and automatic return ---


def test_vacation_lifts_limits_then_normal_limits_return(client, clock, crew):
    a, b, c, _ = crew
    vacation(client, a, "2026-10-21", "2026-10-22")  # Wed and Thu
    sent = [hand_off(client, a, b) for _ in range(5)]
    assert [r.status_code for r in sent] == [201] * 5
    assert all(r.json()["during_vacation"] for r in sent)
    allowance = client.get("/api/handoffs/allowance", headers=a["h"]).json()
    assert allowance["limits_lifted"] is True and allowance["used"] == 0

    clock.day = date(2026, 10, 23)  # Friday: vacation over, same week
    allowance = client.get("/api/handoffs/allowance", headers=a["h"]).json()
    assert allowance["limits_lifted"] is False and allowance["vacation"] is None
    # Normal limits are back, and vacation handoffs didn't use them up.
    results = [hand_off(client, a, b, start=clock.day).status_code for _ in range(3)]
    assert results == [201, 201, 409]
    assert hand_off(client, a, c, start=clock.day).status_code == 201
    assert hand_off(client, a, c, start=clock.day).status_code == 409


def test_ending_vacation_early_restores_limits_today(client, clock, crew):
    a, b, _, _ = crew
    clock.day = date(2026, 10, 20)
    vac = vacation(client, a, "2026-10-19", "2026-10-25").json()  # started yesterday
    assert client.get("/api/handoffs/allowance", headers=a["h"]).json()["limits_lifted"] is True
    assert client.delete(f"/api/me/vacations/{vac['id']}", headers=a["h"]).status_code == 204
    allowance = client.get("/api/handoffs/allowance", headers=a["h"]).json()
    assert allowance["limits_lifted"] is False
    # Kept on record, ending yesterday, and it still counts toward the 14-day rule.
    stored = client.get("/api/me/vacations", headers=a["h"]).json()["vacations"][0]
    assert (stored["start_on"], stored["end_on"]) == ("2026-10-19", "2026-10-19")
    assert vacation(client, a, "2026-10-20", "2026-11-02").status_code == 422  # 1 + 14 days in a row


# --- proposals, consent and records ---


def test_recipient_sees_details_and_must_confirm(client, crew):
    a, b, c, _ = crew
    res = hand_off(client, a, b, end_on="2026-10-23", note="Out sick this week")
    assert res.status_code == 201 and res.json()["status"] == "proposed"
    hid = res.json()["id"]

    incoming = client.get("/api/handoffs", headers=b["h"]).json()[0]
    assert incoming["direction"] == "incoming" and incoming["status"] == "proposed"
    assert incoming["job"]["title"] == "Panel upgrade" and incoming["job"]["site_address"] == "12 Oak St"
    assert (incoming["start_on"], incoming["end_on"], incoming["note"]) == ("2026-10-21", "2026-10-23", "Out sick this week")
    assert incoming["from"]["slug"] == a["slug"]
    # The homeowner's contact details wait until the recipient agrees.
    assert "customer_phone" not in incoming["job"] and "customer_name" not in incoming["job"]
    # Proposing doesn't move the job: the sender still has it, and the recipient has nothing yet.
    assert client.get("/api/jobs", headers=b["h"]).json() == []
    assert client.get("/api/jobs", headers=a["h"]).json()[0]["status"] == "lead"

    # Only the recipient can accept.
    assert client.post(f"/api/handoffs/{hid}/accept", headers=a["h"]).status_code == 404
    assert client.post(f"/api/handoffs/{hid}/accept", headers=c["h"]).status_code == 404
    accepted = client.post(f"/api/handoffs/{hid}/accept", headers=b["h"])
    assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
    assert accepted.json()["job"]["customer_phone"] == "+15125550199"
    assert client.post(f"/api/handoffs/{hid}/accept", headers=b["h"]).status_code == 409
    assert client.post(f"/api/handoffs/{hid}/decline", headers=b["h"]).status_code == 409

    their_job = client.get("/api/jobs", headers=b["h"]).json()[0]
    assert (their_job["title"], their_job["status"], their_job["scheduled_on"]) == ("Panel upgrade", "scheduled", "2026-10-21")
    assert their_job["customer_phone"] == "+15125550199"
    assert client.get("/api/jobs", headers=a["h"]).json()[0]["status"] == "handed_off"

    done = client.post(f"/api/handoffs/{hid}/complete", headers=b["h"]).json()
    assert done["status"] == "completed" and done["completed_at"] and done["responded_at"]
    assert client.get("/api/jobs", headers=b["h"]).json()[0]["status"] == "done"
    outgoing = client.get("/api/handoffs", headers=a["h"]).json()[0]
    assert (outgoing["direction"], outgoing["status"], outgoing["to"]["slug"]) == ("outgoing", "completed", b["slug"])


def test_handoff_rules_for_jobs_and_members(client, crew, member):
    a, b, c, _ = crew
    job_id = job(client, a)
    first = client.post("/api/handoffs", headers=a["h"], json={"job_id": job_id, "recipient_slug": b["slug"], "start_on": "2026-10-22"})
    assert first.status_code == 201
    again = client.post("/api/handoffs", headers=a["h"], json={"job_id": job_id, "recipient_slug": c["slug"], "start_on": "2026-10-22"})
    assert again.status_code == 409  # already offered
    assert hand_off(client, a, a).status_code == 422  # yourself
    assert hand_off(client, a, b, start=date(2026, 10, 20)).status_code == 422  # in the past
    assert client.post("/api/handoffs", headers=a["h"], json={"job_id": job(client, b), "recipient_slug": c["slug"], "start_on": "2026-10-22"}).status_code == 404
    hidden = member("Hidden Electric")
    client.put("/api/me/profile", headers=hidden["h"], json={"published": False})
    assert hand_off(client, a, hidden).status_code == 404


def test_paid_recipient_is_alerted(client, crew, db):
    a, b, _, _ = crew
    client.portal.call(db.users.update_one, {"_id": b["id"]}, {"$set": {"tier": "starter"}})
    hand_off(client, a, b)
    alerts = client.portal.call(lambda: db.outbox.find({"user_id": b["id"]}).to_list(10))
    assert [m["kind"] for m in alerts] == ["handoff_proposed"]
    assert "Alpha Electric asked you to cover" in alerts[0]["subject"]


def test_member_lookup(client, crew, member):
    a = crew[0]
    hidden = member("Hidden Electric")
    client.put("/api/me/profile", headers=hidden["h"], json={"published": False})
    found = client.get("/api/members", headers=a["h"], params={"trade": "electrician", "city": "austin"}).json()
    names = {m["business_name"] for m in found}
    assert names == {"Bravo Electric", "Charlie Electric", "Delta Electric"}
    assert [m["business_name"] for m in client.get("/api/members", headers=a["h"], params={"q": "brav"}).json()] == ["Bravo Electric"]


# --- reviewable history without automatic penalties ---


def test_repeated_pairs_are_flagged_for_review_only(client, clock, crew, db, member):
    a, b, _, _ = crew
    for week in range(3):
        clock.day = WED + timedelta(weeks=week)
        for _ in range(2):
            assert hand_off(client, a, b, start=clock.day).status_code == 201
    admin = member("Staff")
    client.portal.call(db.users.update_one, {"_id": admin["id"]}, {"$set": {"role": "admin"}})
    assert client.get("/api/admin/handoffs/patterns", headers=a["h"]).status_code == 403
    report = client.get("/api/admin/handoffs/patterns", headers=admin["h"], params={"weeks": 12, "min_count": 4}).json()
    top = report["pairs"][0]
    assert (top["from"]["slug"], top["to"]["slug"], top["total"], top["review"]) == (a["slug"], b["slug"], 6, True)
    # Flagging changes nothing for the members: normal limits still apply as usual.
    clock.day = WED + timedelta(weeks=3)
    assert hand_off(client, a, b, start=clock.day).status_code == 201


# --- vacations are rare: about 3 months between separate ones ---


def test_separate_vacations_need_three_months_between(client, member):
    a = member("Alpha Electric")
    assert vacation(client, a, "2026-10-21", "2026-10-30").status_code == 201
    too_soon = vacation(client, a, "2026-12-01", "2026-12-05")
    assert too_soon.status_code == 422 and "start on 2027-01-29 or later" in too_soon.json()["detail"]
    assert vacation(client, a, "2027-01-28", "2027-01-30").status_code == 422  # day 90: still too soon
    # Extending the current vacation is still allowed, up to 14 days in total...
    assert vacation(client, a, "2026-10-31", "2026-11-03").status_code == 201
    # ...and the gap then counts from the new end date.
    assert "start on 2027-02-02 or later" in vacation(client, a, "2027-01-29", "2027-02-05").json()["detail"]
    assert vacation(client, a, "2027-02-02", "2027-02-05").status_code == 201  # 90 full days between
    # And the gap is checked the other way too: nothing squeezed in before a planned one.
    b = member("Bravo Electric")
    assert vacation(client, b, "2027-03-01", "2027-03-05").status_code == 201
    early = vacation(client, b, "2026-12-20", "2026-12-24")
    assert early.status_code == 422 and "need to end by 2026-11-30" in early.json()["detail"]


def test_cancelled_vacation_does_not_block_a_new_one(client, member):
    a = member("Alpha Electric")
    planned = vacation(client, a, "2026-11-10", "2026-11-12").json()
    client.delete(f"/api/me/vacations/{planned['id']}", headers=a["h"])
    assert vacation(client, a, "2026-12-01", "2026-12-03").status_code == 201


# --- reversing or cancelling after acceptance ---


def _accepted(client, a, b):
    h = hand_off(client, a, b).json()
    client.post(f"/api/handoffs/{h['id']}/accept", headers=b["h"])
    return h["id"]


def _jobs(client, m):
    return {j["title"]: j["status"] for j in client.get("/api/jobs", headers=m["h"]).json()}


def test_recipient_can_reverse_and_the_job_goes_back(client, crew):
    a, b, _, _ = crew
    hid = _accepted(client, a, b)
    assert _jobs(client, a) == {"Panel upgrade": "handed_off"} and _jobs(client, b) == {"Panel upgrade": "scheduled"}
    assert client.post(f"/api/handoffs/{hid}/reverse", headers=a["h"], json={"reason": "nope"}).status_code == 404  # not the sender
    assert client.post(f"/api/handoffs/{hid}/reverse", headers=b["h"], json={"reason": ""}).status_code == 422  # reason required
    res = client.post(f"/api/handoffs/{hid}/reverse", headers=b["h"], json={"reason": "Truck broke down"})
    assert res.status_code == 200
    view = res.json()
    assert (view["status"], view["end_reason"]) == ("reversed", "Truck broke down") and view["reversed_at"]
    assert _jobs(client, a) == {"Panel upgrade": "lead"}  # back exactly as it was
    assert _jobs(client, b) == {"Panel upgrade": "cancelled"}
    # The sender didn't choose this, so the weekly slot comes back.
    assert client.get("/api/handoffs/allowance", headers=a["h"]).json()["used"] == 0
    notes = client.get("/api/notifications", headers=a["h"]).json()["items"]
    assert notes[0]["text"] == 'Bravo Electric handed "Panel upgrade" back to you: Truck broke down'
    assert client.post(f"/api/handoffs/{hid}/reverse", headers=b["h"], json={"reason": "again"}).status_code == 409


def test_sender_can_ask_to_cancel_and_recipient_decides(client, crew):
    a, b, c, _ = crew
    hid = _accepted(client, a, b)
    assert client.post(f"/api/handoffs/{hid}/cancel-request", headers=b["h"], json={"reason": "x" * 5}).status_code == 404  # not the sender
    res = client.post(f"/api/handoffs/{hid}/cancel-request", headers=a["h"], json={"reason": "Customer asked for me"}).json()
    assert res["status"] == "accepted" and res["cancel_request"]["status"] == "pending"
    assert client.post(f"/api/handoffs/{hid}/cancel-request", headers=a["h"], json={"reason": "again please"}).status_code == 409
    assert client.post(f"/api/handoffs/{hid}/cancel-request/respond", headers=c["h"], json={"agree": True}).status_code == 404
    assert "asked to cancel" in client.get("/api/notifications", headers=b["h"]).json()["items"][0]["text"]

    # The recipient keeps the job: nothing changes, and the sender may ask again later.
    kept = client.post(f"/api/handoffs/{hid}/cancel-request/respond", headers=b["h"], json={"agree": False}).json()
    assert (kept["status"], kept["cancel_request"]["status"]) == ("accepted", "declined")
    assert _jobs(client, b) == {"Panel upgrade": "scheduled"}
    client.post(f"/api/handoffs/{hid}/cancel-request", headers=a["h"], json={"reason": "Customer really insists"})

    done = client.post(f"/api/handoffs/{hid}/cancel-request/respond", headers=b["h"], json={"agree": True}).json()
    assert (done["status"], done["cancel_request"]["status"]) == ("cancelled", "agreed") and done["cancelled_at"]
    assert _jobs(client, a) == {"Panel upgrade": "lead"} and _jobs(client, b) == {"Panel upgrade": "cancelled"}
    # The sender chose to take it back, so the slot stays used.
    assert client.get("/api/handoffs/allowance", headers=a["h"]).json()["used"] == 1


def test_completed_handoffs_cannot_be_reversed_or_cancelled(client, crew):
    a, b, _, _ = crew
    hid = _accepted(client, a, b)
    client.post(f"/api/handoffs/{hid}/complete", headers=b["h"])
    assert client.post(f"/api/handoffs/{hid}/reverse", headers=b["h"], json={"reason": "too late"}).status_code == 409
    assert client.post(f"/api/handoffs/{hid}/cancel-request", headers=a["h"], json={"reason": "too late"}).status_code == 409


def test_proposals_cannot_be_reversed(client, crew):
    a, b, _, _ = crew
    hid = hand_off(client, a, b).json()["id"]
    assert client.post(f"/api/handoffs/{hid}/reverse", headers=b["h"], json={"reason": "not yet accepted"}).status_code == 409
    assert client.post(f"/api/handoffs/{hid}/cancel-request", headers=a["h"], json={"reason": "use withdraw"}).status_code == 409
