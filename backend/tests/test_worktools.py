"""Time tracking, job costing, quote templates and the calendar."""
from datetime import date, timedelta

import pytest

from app.routers.costing import price_quote, summarize


@pytest.fixture
def starter(client, signup, db):
    h, user = signup()
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": "starter"}})
    return h, user


def _job(client, h, **extra):
    return client.post("/api/jobs", json={"title": "Panel swap", "customer_name": "Pat", **extra}, headers=h).json()


def test_time_tracking_is_a_starter_feature_and_one_clock_per_person(client, signup, starter):
    free, _ = signup()
    assert client.post("/api/time/clock-in", json={}, headers=free).status_code == 402
    assert client.get("/api/time/status", headers=free).json()["allowed"] is False
    h, _ = starter
    job = _job(client, h)
    res = client.post("/api/time/clock-in", json={"job_id": job["id"]}, headers=h)
    assert res.status_code == 201 and res.json()["running"] and res.json()["job"] == "Panel swap"
    assert client.post("/api/time/clock-in", json={}, headers=h).status_code == 409
    assert client.get("/api/time/status", headers=h).json()["running"]["job"] == "Panel swap"
    out = client.post("/api/time/clock-out", json={"note": "Rough-in done"}, headers=h)
    assert out.status_code == 200 and out.json()["running"] is False and out.json()["note"] == "Rough-in done"
    assert client.post("/api/time/clock-out", json={}, headers=h).status_code == 409
    assert client.post("/api/time/clock-in", json={}, headers=h).status_code == 201  # free to start again


def test_manual_entries_week_totals_and_csv(client, starter):
    h, _ = starter
    job = _job(client, h)
    bad = {"job_id": job["id"], "day": "2026-10-21", "start": "16:00", "end": "08:00"}
    assert client.post("/api/time/entries", json=bad, headers=h).status_code == 422
    assert client.post("/api/time/entries", json={**bad, "day": "2026-10-24", "start": "08:00", "end": "16:00"}, headers=h).status_code == 422  # future
    assert client.post("/api/time/entries", json={**bad, "start": "08:00", "end": "09:00", "break_minutes": 60}, headers=h).status_code == 422
    e = client.post("/api/time/entries", json={**bad, "start": "07:30", "end": "16:00", "break_minutes": 30}, headers=h).json()
    assert (e["day"], e["start"], e["end"], e["minutes"]) == ("2026-10-21", "07:30", "16:00", 480)
    client.post("/api/time/entries", json={"day": "2026-10-22", "start": "08:00", "end": "10:00"}, headers=h)
    week = client.get("/api/time?start=2026-10-23", headers=h).json()
    assert week["week_of"] == "2026-10-19" and week["total_minutes"] == 600
    assert week["totals"]["jobs"] == {"Panel swap": 480, "No job": 120}
    assert client.get("/api/time?start=2026-10-26", headers=h).json()["entries"] == []
    csv = client.get("/api/time/export.csv?start=2026-10-19&end=2026-10-25", headers=h)
    assert csv.headers["content-type"].startswith("text/csv") and "2026-10-21,Bright Spark Electric,Panel swap,07:30,16:00,30,8.00" in csv.text
    assert client.delete(f"/api/time/entries/{e['id']}", headers=h).status_code == 204


def test_downgrade_keeps_time_readable(client, starter, db):
    h, user = starter
    client.post("/api/time/entries", json={"day": "2026-10-22", "start": "08:00", "end": "10:00"}, headers=h)
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": "free"}})
    assert client.get("/api/time?start=2026-10-22", headers=h).json()["total_minutes"] == 120
    assert client.post("/api/time/entries", json={"day": "2026-10-22", "start": "11:00", "end": "12:00"}, headers=h).status_code == 402


def test_teammates_track_their_own_time_for_the_business(client, signup, db):
    owner_h, owner = signup("Owner Co")
    w_h, worker = signup("Worker", email="worker@example.com")
    client.portal.call(db.users.update_one, {"_id": owner["id"]}, {"$set": {"tier": "starter"}})
    client.post(f"/api/team/{owner['id']}/invite", json={"email": "worker@example.com", "role": "contributor", "permissions": ["jobs"]}, headers=owner_h)
    client.post(f"/api/team/invitations/{owner['id']}/accept", headers=w_h)
    as_biz = {**w_h, "X-TC-Business": owner["id"]}
    assert client.post("/api/time/entries", json={"day": "2026-10-22", "start": "08:00", "end": "12:00"}, headers=as_biz).status_code == 201
    client.post("/api/time/entries", json={"day": "2026-10-22", "start": "13:00", "end": "14:00"}, headers=owner_h)
    assert client.get("/api/time?start=2026-10-22", headers=owner_h).json()["totals"]["people"] == {"Worker": 240, "Owner Co": 60}
    assert client.get("/api/time?start=2026-10-22", headers=as_biz).json()["totals"]["people"] == {"Worker": 240}
    # The worker's own (free) account isn't charged for the business's feature.
    assert client.post("/api/time/entries", json={"day": "2026-10-22", "start": "08:00", "end": "09:00"}, headers=w_h).status_code == 402


def test_job_costing_with_tracked_labor(client, starter):
    h, _ = starter
    job = _job(client, h, estimate_cents=300000)
    client.post("/api/time/entries", json={"job_id": job["id"], "day": "2026-10-21", "start": "08:00", "end": "18:00"}, headers=h)
    body = {
        "labor_cost_per_hour_cents": 4000, "overhead_percent": 10,
        "estimate": [{"kind": "labor", "description": "2 days", "quantity": 16, "unit_cost_cents": 4000}, {"kind": "materials", "description": "Panel and breakers", "quantity": 1, "unit_cost_cents": 90000}],
        "actual": [{"kind": "materials", "description": "Panel and breakers", "quantity": 1, "unit_cost_cents": 105000}],
    }
    res = client.put(f"/api/jobs/{job['id']}/costing", json=body, headers=h).json()
    s = res["summary"]
    assert s["price_cents"] == 300000 and s["tracked_hours"] == 10 and s["tracked_labor_cents"] == 40000
    # Estimate: (64,000 + 90,000) * 1.10 = 169,400 cost; profit 130,600 on 300,000.
    assert s["estimate"]["cost_cents"] == 169400 and s["estimate"]["margin_percent"] == 43.5 and s["estimate"]["markup_percent"] == 77.1
    # Actual: (105,000 + 40,000 tracked) * 1.10 = 159,500.
    assert s["actual"]["cost_cents"] == 159500 and s["variance"] == {"labor": -24000, "materials": 15000}


def test_costing_templates(client, starter):
    h, _ = starter
    t = client.post("/api/costing/templates", json={"name": "200A panel", "lines": [{"kind": "materials", "description": "Panel", "unit_cost_cents": 60000}]}, headers=h).json()
    assert [x["name"] for x in client.get("/api/costing/templates", headers=h).json()] == ["200A panel"]
    assert client.delete(f"/api/costing/templates/{t['id']}", headers=h).status_code == 204


def test_seasonal_quote_templates(client, starter):
    h, _ = starter
    body = {"name": "AC tune-up", "items": [{"description": "Tune-up", "price_cents": 12000}, {"description": "Filter", "price_cents": 3000}],
            "seasons": [{"label": "Peak AC season", "months": [6, 7, 8], "adjust_percent": 15}, {"label": "Winter special", "months": [12, 1, 2], "adjust_percent": -10}]}
    assert client.post("/api/quote-templates", json={**body, "seasons": [*body["seasons"], {"label": "x", "months": [8], "adjust_percent": 5}]}, headers=h).status_code == 422
    t = client.post("/api/quote-templates", json=body, headers=h).json()
    july = client.get(f"/api/quote-templates/{t['id']}/price?on=2027-07-04", headers=h).json()
    assert july["season"]["label"] == "Peak AC season" and july["subtotal_cents"] == 15000 and july["total_cents"] == 17250
    assert client.get(f"/api/quote-templates/{t['id']}/price?on=2027-01-10", headers=h).json()["total_cents"] == 13500
    oct_ = client.get(f"/api/quote-templates/{t['id']}/price?on=2026-10-23", headers=h).json()
    assert oct_["season"] is None and oct_["total_cents"] == 15000


def test_calendar_collects_dated_things(client, signup, db):
    h, user = signup()
    _job(client, h, scheduled_on="2026-10-27")
    _job(client, h, title="Old", scheduled_on="2026-09-01")
    client.post("/api/inbox", json={"name": "Sam", "channel": "phone", "follow_up_on": "2026-10-25"}, headers=h)
    assert client.post("/api/me/vacations", json={"start_on": "2026-11-02", "end_on": "2026-11-06", "note": "Fishing"}, headers=h).status_code == 201
    client.post("/api/posts", json={"kind": "meetup", "title": "Coffee", "location": "78701", "fields": {"starts_on": "2026-10-30", "starts_at": "07:00", "timezone": "America/Chicago", "general_location": "Downtown"}}, headers=h)
    cal = client.get("/api/calendar?start=2026-10-23&days=21", headers=h).json()
    kinds = [(e["kind"], e["date"]) for e in cal["events"]]
    assert kinds == [("follow_up", "2026-10-25"), ("job", "2026-10-27"), ("meetup", "2026-10-30"), ("vacation", "2026-11-02")]
    assert cal["events"][-1]["end"] == "2026-11-06"
    assert client.get("/api/calendar?start=2026-10-23&days=200", headers=h).status_code == 422


def test_pure_helpers():
    assert price_quote({"items": [{"description": "x", "price_cents": 1000}], "seasons": []}, date(2026, 1, 1))["total_cents"] == 1000
    s = summarize({"estimate": [], "actual": [], "price_cents": 0}, {"estimate_cents": None}, 0)
    assert s["estimate"]["margin_percent"] is None
