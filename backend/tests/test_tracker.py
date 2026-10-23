import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import create_app, migrate

QUOTE = {"name": "Dana Homeowner", "phone": "+15125550199", "message": "Need a panel upgrade"}


class Clock:
    day = date(2026, 10, 23)

    def __call__(self):
        return self.day


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def client(settings, db, clock):
    app = create_app(settings, db=db, today=clock)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def add(client, headers, name, **extra):
    res = client.post("/api/inbox", headers=headers, json={"name": name, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def test_manual_entries_are_private_to_their_owner(client, signup):
    a, _ = signup()
    b, _ = signup("Other Co", trade="painter")
    entry = add(client, a, "Sam from church", phone="(512) 555-0100", channel="in_person", notes="Wants a quote for a shed subpanel")
    assert entry["source"] == "manual" and entry["phone"] == "+15125550100" and entry["status"] == "waiting"
    assert client.get("/api/inbox", headers=b).json() == []
    assert client.patch(f"/api/inbox/{entry['id']}", headers=b, json={"status": "won"}).status_code == 404
    assert client.delete(f"/api/inbox/{entry['id']}", headers=b).status_code == 404
    client.cookies.clear()
    assert client.get("/api/inbox").status_code == 401


def test_upcoming_and_overdue_views(client, signup, clock):
    a, _ = signup()
    add(client, a, "Past due", follow_up_on="2026-10-20")
    add(client, a, "Today", follow_up_on="2026-10-23")
    add(client, a, "Next week", follow_up_on="2026-10-30")
    add(client, a, "No date")
    add(client, a, "Already won", follow_up_on="2026-10-01", status="won")
    names = lambda view: [e["name"] for e in client.get("/api/inbox", headers=a, params={"view": view}).json()]
    assert names("overdue") == ["Past due"]
    assert names("upcoming") == ["Today", "Next week"]
    assert len(names("all")) == 5
    clock.day = date(2026, 10, 24)
    assert names("overdue") == ["Past due", "Today"]


def test_notes_dates_and_statuses(client, signup):
    a, _ = signup()
    entry = add(client, a, "Lee", follow_up_on="2026-10-25")
    res = client.patch(f"/api/inbox/{entry['id']}", headers=a, json={"status": "followed_up", "notes": "Left voicemail", "follow_up_on": None}).json()
    assert (res["status"], res["notes"], res["follow_up_on"]) == ("followed_up", "Left voicemail", None)
    assert client.patch(f"/api/inbox/{entry['id']}", headers=a, json={"status": "lost"}).status_code == 422
    for s in ("won", "closed", "waiting"):
        assert client.patch(f"/api/inbox/{entry['id']}", headers=a, json={"status": s}).json()["status"] == s


def test_customer_requests_keep_their_contact_details(client, signup):
    a, _ = signup()
    slug = client.get("/api/me/profile", headers=a).json()["slug"]
    client.post(f"/api/p/{slug}/quote", json=QUOTE)
    quote = client.get("/api/inbox", headers=a).json()[0]
    assert quote["source"] == "trade_circle" and quote["status"] == "waiting"
    assert client.patch(f"/api/inbox/{quote['id']}", headers=a, json={"phone": "+15125550000"}).status_code == 422
    assert client.patch(f"/api/inbox/{quote['id']}", headers=a, json={"notes": "Called back"}).status_code == 200
    assert client.delete(f"/api/inbox/{quote['id']}", headers=a).status_code == 404  # close it instead
    manual = add(client, a, "Typo Nmae")
    assert client.patch(f"/api/inbox/{manual['id']}", headers=a, json={"name": "Typo Name"}).json()["name"] == "Typo Name"
    assert client.delete(f"/api/inbox/{manual['id']}", headers=a).status_code == 204


def test_adding_entries_never_sends_alerts(client, signup, db):
    a, user = signup()
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": "full"}})
    add(client, a, "Phone call", follow_up_on="2026-10-24")
    assert client.portal.call(lambda: db.outbox.count_documents({})) == 0


def test_lead_alert_rules_unchanged(client, signup, db):
    free, _ = signup()
    paid, paid_user = signup("Paid Co", trade="plumber")
    client.portal.call(db.users.update_one, {"_id": paid_user["id"]}, {"$set": {"tier": "starter"}})
    for headers in (free, paid):
        slug = client.get("/api/me/profile", headers=headers).json()["slug"]
        client.post(f"/api/p/{slug}/quote", json=QUOTE)
    alerts = client.portal.call(lambda: db.outbox.find({}).to_list(10))
    assert {a["user_id"] for a in alerts} == {paid_user["id"]}  # free plan: log in to see leads


def test_old_statuses_are_converted(db):
    async def go():
        await db.quotes.insert_many([{"_id": "1", "status": "new"}, {"_id": "2", "status": "contacted"}, {"_id": "3", "status": "lost"}, {"_id": "4", "status": "won"}])
        await migrate(db)
        await migrate(db)  # safe to repeat
        return {q["_id"]: q["status"] async for q in db.quotes.find({})}

    assert asyncio.run(go()) == {"1": "waiting", "2": "followed_up", "3": "closed", "4": "won"}
