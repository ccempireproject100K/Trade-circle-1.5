from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(settings, db):
    app = create_app(settings, db=db, today=lambda: date(2026, 10, 23))
    app.state.limiters["login"].limit = 1000
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def member(client):
    n = iter(range(100))

    def make(name, trade="electrician"):
        i = next(n)
        res = client.post("/api/auth/signup", json={"email": f"c{i}@example.com", "password": "correct horse battery", "business_name": name, "trade": trade, "city": "Austin"})
        client.cookies.clear()
        h = {"Authorization": f"Bearer {res.json()['token']}"}
        return {"h": h, "slug": client.get("/api/me/profile", headers=h).json()["slug"], "id": res.json()["user"]["id"]}

    return make


def unread(client, m):
    return client.get("/api/notifications", headers=m["h"]).json()


# --- messaging needs consent ---


def test_no_messages_until_the_recipient_accepts(client, member):
    a, b = member("Alpha"), member("Bravo")
    req = client.post("/api/messages/requests", headers=a["h"], json={"to_slug": b["slug"], "note": "Saw your review of ABC, which branch?"}).json()
    assert req["status"] == "pending"
    assert client.get("/api/messages/conversations", headers=a["h"]).json() == []
    assert unread(client, b)["items"][0]["text"] == "Alpha asked to message you."
    incoming = client.get("/api/messages/requests", headers=b["h"]).json()["incoming"]
    assert incoming[0]["note"].startswith("Saw your review")

    conv = client.post(f"/api/messages/requests/{req['id']}/accept", headers=b["h"]).json()["conversation_id"]
    thread = client.get(f"/api/messages/conversations/{conv}", headers=a["h"]).json()
    assert [m["body"] for m in thread["messages"]] == ["Saw your review of ABC, which branch?"]
    assert client.post(f"/api/messages/conversations/{conv}", headers=b["h"], json={"body": "The Burnet one."}).status_code == 201
    assert unread(client, a)["unread"] == 2  # accepted + new message

    c = member("Charlie")
    assert client.get(f"/api/messages/conversations/{conv}", headers=c["h"]).status_code == 404
    assert client.post(f"/api/messages/conversations/{conv}", headers=c["h"], json={"body": "hi"}).status_code == 404


def test_declined_requests_open_nothing(client, member):
    a, b = member("Alpha"), member("Bravo")
    req = client.post("/api/messages/requests", headers=a["h"], json={"to_slug": b["slug"], "note": "Hi"}).json()
    client.post(f"/api/messages/requests/{req['id']}/decline", headers=b["h"])
    assert client.get("/api/messages/conversations", headers=a["h"]).json() == []
    assert client.get("/api/messages/requests", headers=a["h"]).json()["outgoing"][0]["status"] == "not accepted"
    assert client.post(f"/api/messages/requests/{req['id']}/accept", headers=b["h"]).status_code == 404


def test_blocking_stops_requests_and_messages_both_ways(client, member):
    a, b = member("Alpha"), member("Bravo")
    req = client.post("/api/messages/requests", headers=a["h"], json={"to_slug": b["slug"], "note": "Hi"}).json()
    conv = client.post(f"/api/messages/requests/{req['id']}/accept", headers=b["h"]).json()["conversation_id"]
    assert client.post(f"/api/members/{a['slug']}/block", headers=b["h"]).status_code == 204
    assert client.post(f"/api/messages/conversations/{conv}", headers=a["h"], json={"body": "?"}).status_code == 409
    assert client.post(f"/api/messages/conversations/{conv}", headers=b["h"], json={"body": "?"}).status_code == 409
    c = member("Charlie")
    pending = client.post("/api/messages/requests", headers=c["h"], json={"to_slug": b["slug"], "note": "Hi"}).json()
    client.post(f"/api/members/{c['slug']}/block", headers=b["h"])
    # The blocked member's pending request vanished, and new ones are refused.
    assert client.get("/api/messages/requests", headers=b["h"]).json()["incoming"] == []
    assert client.post("/api/messages/requests", headers=c["h"], json={"to_slug": b["slug"], "note": "again"}).status_code == 409
    client.delete(f"/api/members/{a['slug']}/block", headers=b["h"])
    assert client.post(f"/api/messages/conversations/{conv}", headers=a["h"], json={"body": "back"}).status_code == 201


def test_messages_can_be_reported(client, member):
    a, b = member("Alpha"), member("Bravo")
    req = client.post("/api/messages/requests", headers=a["h"], json={"to_slug": b["slug"], "note": "Buy my leads list"}).json()
    conv = client.post(f"/api/messages/requests/{req['id']}/accept", headers=b["h"]).json()["conversation_id"]
    msg = client.get(f"/api/messages/conversations/{conv}", headers=b["h"]).json()["messages"][0]
    assert client.post("/api/reports", headers=b["h"], json={"target_type": "message", "target_id": msg["id"], "reason": "spam"}).status_code == 201
    assert client.post("/api/reports", headers=b["h"], json={"target_type": "member", "target_id": a["slug"], "reason": "harassment"}).status_code == 201


def test_message_requests_are_rate_limited(client, member):
    a = member("Alpha")
    client.app.state.limiters["message_request"].limit = 2
    others = [member(f"Other {i}") for i in range(3)]
    codes = [client.post("/api/messages/requests", headers=a["h"], json={"to_slug": o["slug"], "note": "Hi"}).status_code for o in others]
    assert codes == [201, 201, 429]


# --- mentoring ---


MENTOR = {"offering": True, "topics": ["Estimating", "Hiring first helper"], "experience": "18 years, ran a 6-person crew", "contact_method": "phone", "contact_value": "+15125550111", "availability": "Weekday evenings"}


def test_mentoring_is_voluntary_and_can_be_paused_or_removed(client, member):
    mentor, seeker = member("Old Hand Electric"), member("New Electric")
    assert client.put("/api/me/mentoring", headers=mentor["h"], json={**MENTOR, "offering": False}).status_code == 422
    assert client.put("/api/me/mentoring", headers=mentor["h"], json={**MENTOR, "contact_value": ""}).status_code == 422
    assert client.put("/api/me/mentoring", headers=mentor["h"], json=MENTOR).status_code == 200
    found = client.get("/api/mentoring", headers=seeker["h"], params={"mode": "offering", "topic": "estimat"}).json()
    assert found[0]["member"]["slug"] == mentor["slug"] and found[0]["prefers"] == "Phone call"
    assert "contact_value" not in found[0] and "+15125550111" not in str(found)  # not shown before consent
    client.put("/api/me/mentoring", headers=mentor["h"], json={**MENTOR, "paused": True})
    assert client.get("/api/mentoring", headers=seeker["h"]).json() == []
    assert client.post("/api/messages/requests", headers=seeker["h"], json={"to_slug": mentor["slug"], "note": "Hi", "context": "mentoring"}).status_code == 409
    client.delete("/api/me/mentoring", headers=mentor["h"])
    assert client.get("/api/me/mentoring", headers=mentor["h"]).json() == {"mentoring": None}


def test_mentor_contact_is_shared_only_after_they_accept(client, member):
    mentor, seeker = member("Old Hand Electric"), member("New Electric")
    client.put("/api/me/mentoring", headers=mentor["h"], json=MENTOR)
    req = client.post("/api/messages/requests", headers=seeker["h"], json={"to_slug": mentor["slug"], "note": "Could you look at how I price service calls?", "context": "mentoring"}).json()
    assert unread(client, mentor)["items"][0]["text"] == "New Electric asked a mentoring introduction."
    conv = client.post(f"/api/messages/requests/{req['id']}/accept", headers=mentor["h"]).json()["conversation_id"]
    messages = client.get(f"/api/messages/conversations/{conv}", headers=seeker["h"]).json()["messages"]
    assert messages[-1] == {**messages[-1], "system": True, "body": "Prefers phone call: +15125550111"}


def test_blocked_members_dont_appear_in_mentoring(client, member):
    mentor, seeker = member("Old Hand Electric"), member("New Electric")
    client.put("/api/me/mentoring", headers=mentor["h"], json=MENTOR)
    client.post(f"/api/members/{seeker['slug']}/block", headers=mentor["h"])
    assert client.get("/api/mentoring", headers=seeker["h"]).json() == []


# --- meetups ---


MEETUP = {"kind": "meetup", "title": "Coffee and code questions", "body": "Bring your NEC questions.", "location": "78701", "trade_tags": ["electrician"],
          "fields": {"starts_on": "2026-11-05", "starts_at": "07:00", "timezone": "America/Chicago", "general_location": "Coffee shop near downtown Austin"}}


def test_meetup_rsvp_updates_and_cancellation(client, member):
    host, a, b = member("Host Electric"), member("Alpha"), member("Bravo")
    meetup = client.post("/api/posts", headers=host["h"], json=MEETUP).json()
    assert meetup["meetup"]["rsvp"] == {"going": 0, "maybe": 0, "not_going": 0, "mine": None}
    client.put(f"/api/posts/{meetup['id']}/rsvp", headers=a["h"], json={"response": "going"})
    client.put(f"/api/posts/{meetup['id']}/rsvp", headers=b["h"], json={"response": "maybe"})
    client.put(f"/api/posts/{meetup['id']}/rsvp", headers=b["h"], json={"response": "not_going"})
    view = client.get(f"/api/posts/{meetup['id']}", headers=a["h"]).json()["meetup"]
    assert view["rsvp"] == {"going": 1, "maybe": 0, "not_going": 1, "mine": "going"}
    assert [x["member"]["slug"] for x in client.get(f"/api/posts/{meetup['id']}/attendees", headers=host["h"]).json()] == [a["slug"]]

    assert client.post(f"/api/posts/{meetup['id']}/updates", headers=a["h"], json={"text": "hijack"}).status_code == 403
    client.post(f"/api/posts/{meetup['id']}/updates", headers=host["h"], json={"text": "Moved to 7:30."})
    assert unread(client, a)["items"][0]["text"] == 'Update for "Coffee and code questions": Moved to 7:30.'
    assert unread(client, b)["unread"] == 0  # said not going: not notified

    client.post(f"/api/posts/{meetup['id']}/cancel", headers=host["h"], json={"text": "Rained out."})
    after = client.get(f"/api/posts/{meetup['id']}", headers=a["h"]).json()["meetup"]
    assert after["cancelled"]["reason"] == "Rained out." and after["updates"][0]["text"] == "Moved to 7:30."
    assert client.put(f"/api/posts/{meetup['id']}/rsvp", headers=b["h"], json={"response": "going"}).status_code == 409


def test_meetup_filters(client, member):
    host, a = member("Host Electric"), member("Alpha")
    client.post("/api/posts", headers=host["h"], json=MEETUP)
    client.post("/api/posts", headers=host["h"], json={**MEETUP, "title": "Past one", "fields": {**MEETUP["fields"], "starts_on": "2026-10-01"}})
    client.post("/api/posts", headers=host["h"], json={**MEETUP, "title": "Plumbers in Dallas", "location": "75201", "trade_tags": ["plumber"]})
    titles = lambda **p: [x["title"] for x in client.get("/api/posts", headers=a["h"], params={"upcoming": True, **p}).json()["posts"]]
    assert set(titles()) == {"Coffee and code questions", "Plumbers in Dallas"}
    assert titles(near="78701", radius=25) == ["Coffee and code questions"]
    assert titles(trade="plumber") == ["Plumbers in Dallas"]
    bad_zone = client.post("/api/posts", headers=host["h"], json={**MEETUP, "fields": {**MEETUP["fields"], "timezone": "Mars/Base"}})
    assert bad_zone.status_code == 422


# --- equipment ---


def test_equipment_posts_are_searchable_by_model_and_link_to_suppliers(client, member):
    a = member("Alpha")
    post = client.post("/api/posts", headers=a["h"], json={"kind": "equipment", "title": "Three years with it", "fields": {"product": "Fish tape", "model": "FT-250X", "buy_again": "no", "affiliation": "none", "durability": "Kinked after a year"}}).json()
    client.post("/api/posts", headers=a["h"], json={"kind": "equipment_question", "title": "Anyone use the FT-250X?", "fields": {"model": "FT-250X"}})
    found = client.get("/api/posts", headers=a["h"], params={"kind": "equipment,equipment_question", "q": "ft-250x"}).json()["posts"]
    assert {p["kind"] for p in found} == {"equipment", "equipment_question"}
    assert post["fields"]["buy_again"] == "no"
