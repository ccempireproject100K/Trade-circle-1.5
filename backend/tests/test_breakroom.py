"""Break Room listings: required facts, automatic expiry, recheck flags, location filter, reporting, usage counts."""
import pytest

OFFER = {"kind": "public_offer", "title": "10% off work boots", "organizer": "Example Boots", "official_url": "https://example.com/deal", "location": "78701", "expires_on": "2026-11-30", "last_checked_on": "2026-10-20"}
GIVEAWAY = {"kind": "giveaway", "title": "Win a drill kit", "organizer": "Example Tools", "official_url": "https://example.com/win", "prize": "Drill kit", "geography": "US residents 18+", "rules_url": "https://example.com/rules", "expires_on": "2026-11-15", "last_checked_on": "2026-10-22"}


@pytest.fixture
def admin(client, signup, db):
    h, user = signup("Moderator")
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"role": "admin"}})
    return h


def test_members_cannot_add_listings(client, signup):
    h, _ = signup()
    assert client.post("/api/admin/break-room/listings", json=OFFER, headers=h).status_code == 403


def test_giveaway_needs_organizer_facts(client, admin):
    for missing in ("prize", "geography", "rules_url", "expires_on"):
        body = {k: v for k, v in GIVEAWAY.items() if k != missing}
        assert client.post("/api/admin/break-room/listings", json=body, headers=admin).status_code == 422, missing
    assert client.post("/api/admin/break-room/listings", json={**GIVEAWAY, "official_url": "http://example.com"}, headers=admin).status_code == 422
    assert client.post("/api/admin/break-room/listings", json={**GIVEAWAY, "last_checked_on": "2026-10-24"}, headers=admin).status_code == 422
    res = client.post("/api/admin/break-room/listings", json=GIVEAWAY, headers=admin)
    assert res.status_code == 201 and res.json()["label"] == "Giveaway"


def test_expired_listings_disappear_and_open_ended_ones_are_flagged(client, admin):
    client.post("/api/admin/break-room/listings", json={**OFFER, "title": "Expired", "expires_on": "2026-10-22"}, headers=admin)
    client.post("/api/admin/break-room/listings", json={**OFFER, "title": "Ends today", "expires_on": "2026-10-23"}, headers=admin)
    client.post("/api/admin/break-room/listings", json={**OFFER, "title": "No end", "expires_on": None}, headers=admin)
    shown = client.get("/api/break-room/listings?kind=public_offer", headers=admin).json()["listings"]
    assert {l["title"] for l in shown} == {"Ends today", "No end"}
    no_end = next(l for l in shown if l["title"] == "No end")
    assert no_end["no_end_date"] and no_end["needs_recheck"] and no_end["label"] == "Public offer"
    admin_view = client.get("/api/admin/break-room/listings", headers=admin).json()
    assert admin_view[0]["needs_recheck"] and any(l["expired"] for l in admin_view)


def test_stale_checks_are_flagged(client, admin):
    client.post("/api/admin/break-room/listings", json={**OFFER, "last_checked_on": "2026-09-01"}, headers=admin)
    assert client.get("/api/break-room/listings", headers=admin).json()["listings"][0]["needs_recheck"] is True


def test_location_filter_keeps_online_offers(client, admin):
    client.post("/api/admin/break-room/listings", json={**OFFER, "title": "Austin"}, headers=admin)
    client.post("/api/admin/break-room/listings", json={**OFFER, "title": "New York", "location": "10001"}, headers=admin)
    client.post("/api/admin/break-room/listings", json={**OFFER, "title": "Online", "location": ""}, headers=admin)
    near = client.get("/api/break-room/listings?near=78702&radius=25", headers=admin).json()["listings"]
    assert {l["title"] for l in near} == {"Austin", "Online"}


def test_members_report_and_moderators_hide(client, admin, signup):
    listing = client.post("/api/admin/break-room/listings", json=OFFER, headers=admin).json()
    h, _ = signup("Member")
    report = client.post("/api/reports", json={"target_type": "listing", "target_id": listing["id"], "reason": "fabricated", "note": "Link is dead"}, headers=h)
    assert report.status_code == 201
    client.post(f"/api/admin/reports/{report.json()['id']}/resolve", json={"action": "hide"}, headers=admin)
    assert client.get("/api/break-room/listings", headers=h).json()["listings"] == []


def test_usage_counts_are_anonymous_totals(client, admin, signup, db):
    h, _ = signup("Member")
    for _ in range(2):
        assert client.post("/api/usage", json={"event": "game_opened", "detail": "2048"}, headers=h).status_code == 204
    client.post("/api/usage", json={"event": "music_played"}, headers=h)
    assert client.get("/api/admin/usage", headers=admin).json()["totals"] == {"game_opened:2048": 2, "music_played": 1}
    rows = client.portal.call(lambda: db.usage_counts.find({}).to_list(10))
    assert all("user_id" not in r for r in rows)
    assert client.post("/api/usage", json={"event": "anything"}, headers=h).status_code == 422
