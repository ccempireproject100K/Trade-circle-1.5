"""Government wage data (BLS) and community-kept outside estimates."""
import pytest

EST = {"trade": "electrician", "service": "Hourly labor rate", "unit": "hour", "low": 50, "high": 100, "scope": "national", "source_name": "HomeGuide", "source_url": "https://homeguide.com/costs/electrician-rates", "checked_on": "2026-10-20"}


def test_government_wages_match_the_bls_area(client, signup):
    h, _ = signup()
    res = client.get("/api/rates/government?trade=electrician&location=78701", headers=h).json()
    assert res["area"] == "Austin-Round Rock-San Marcos, TX" and res["period"] == "May 2025"
    first = res["occupations"][0]
    # The published BLS figures for Austin electricians, May 2025.
    assert first["title"] == "Electricians" and first["where"] == "area" and first["mean"] == 29.25 and first["median"] == 29.03
    assert "Not what contractors charge" in res["note"] and res["source_url"] == "https://www.bls.gov/oes/"


def test_city_input_and_statewide_fallback(client, signup):
    h, _ = signup()
    assert client.get("/api/rates/government?trade=plumber&location=Austin, TX", headers=h).json()["area"] == "Austin-Round Rock-San Marcos, TX"
    # Connecticut ZIPs aren't matched to an area yet: statewide figures, labeled as such.
    ct = client.get("/api/rates/government?trade=electrician&location=06103", headers=h).json()
    assert ct["area"] is None and ct["state"] == "CT" and ct["occupations"][0]["where"] == "state"


def test_adder_edits_directly_others_suggest_corrections(client, signup):
    a, _ = signup("Alpha Electric")
    b, _ = signup("Bravo Electric")
    est = client.post("/api/rates/estimates", json=EST, headers=a)
    assert est.status_code == 201, est.text
    eid = est.json()["id"]
    assert est.json()["added_by"] == "Alpha Electric"
    assert client.put(f"/api/rates/estimates/{eid}", json={**EST, "low": 55}, headers=b).status_code == 403
    upd = client.put(f"/api/rates/estimates/{eid}", json={**EST, "low": 55, "checked_on": "2026-10-23"}, headers=a)
    assert upd.status_code == 200 and upd.json()["low"] == 55 and upd.json()["changes"] == 1
    hist = client.get(f"/api/rates/estimates/{eid}/history", headers=a).json()
    assert [r["action"] for r in hist] == ["added", "updated"] and hist[1]["changes"]["low"] == {"from": 50, "to": 55}


def _correct(client, h, eid, **changes):
    return client.post(f"/api/rates/estimates/{eid}/corrections", json={"kind": "change", "proposed": {**EST, **changes}, "reason": "The source page now says $60 to $110."}, headers=h)


def test_correction_applies_after_two_confirmations(client, signup):
    a, _ = signup("Alpha")
    b, _ = signup("Bravo")
    c, _ = signup("Charlie")
    d, _ = signup("Delta")
    e, _ = signup("Echo")
    eid = client.post("/api/rates/estimates", json=EST, headers=a).json()["id"]
    cor = _correct(client, b, eid, low=60, high=110)
    assert cor.status_code == 201, cor.text
    cid = cor.json()["id"]
    assert cor.json()["changes"] == {"low": {"from": 50, "to": 60}, "high": {"from": 100, "to": 110}}
    assert client.get("/api/rates/estimates?trade=electrician", headers=a).json()["estimates"][0]["open_corrections"] == 1
    # The suggester can't confirm their own correction.
    assert client.post(f"/api/rates/estimates/corrections/{cid}/vote", json={"vote": "confirm"}, headers=b).status_code == 403
    one = client.post(f"/api/rates/estimates/corrections/{cid}/vote", json={"vote": "confirm", "note": "Checked it too"}, headers=c).json()
    assert one["status"] == "open" and one["confirms"] == 1
    assert client.get("/api/rates/estimates?trade=electrician", headers=a).json()["estimates"][0]["low"] == 50  # not yet
    # Two confirmations with two disputes isn't enough: confirmations must outnumber disputes.
    client.post(f"/api/rates/estimates/corrections/{cid}/vote", json={"vote": "dispute", "note": "Still $50 for me"}, headers=d)
    client.post(f"/api/rates/estimates/corrections/{cid}/vote", json={"vote": "dispute"}, headers=a)
    held = client.post(f"/api/rates/estimates/corrections/{cid}/vote", json={"vote": "confirm"}, headers=e).json()
    assert held["status"] == "open" and (held["confirms"], held["disputes"]) == (2, 2)
    assert {n["note"] for n in held["notes"]} == {"Checked it too", "Still $50 for me"}
    # Alpha checks the source again and changes their vote.
    done = client.post(f"/api/rates/estimates/corrections/{cid}/vote", json={"vote": "confirm"}, headers=a).json()
    assert done["status"] == "applied"
    shown = client.get("/api/rates/estimates?trade=electrician", headers=a).json()["estimates"][0]
    assert (shown["low"], shown["high"], shown["open_corrections"]) == (60, 110, 0)
    hist = client.get(f"/api/rates/estimates/{eid}/history", headers=a).json()
    assert hist[-1]["action"] == "corrected" and hist[-1]["by"] == "Bravo" and sorted(hist[-1]["confirmed_by"]) == ["Alpha", "Charlie", "Echo"]


def test_removal_correction_retires_the_estimate(client, signup):
    a, _ = signup("Alpha")
    b, _ = signup("Bravo")
    c, _ = signup("Charlie")
    eid = client.post("/api/rates/estimates", json=EST, headers=a).json()["id"]
    cid = client.post(f"/api/rates/estimates/{eid}/corrections", json={"kind": "remove", "reason": "The page was taken down."}, headers=b).json()["id"]
    client.post(f"/api/rates/estimates/corrections/{cid}/vote", json={"vote": "confirm"}, headers=a)
    assert client.post(f"/api/rates/estimates/corrections/{cid}/vote", json={"vote": "confirm"}, headers=c).json()["status"] == "applied"
    assert client.get("/api/rates/estimates?trade=electrician", headers=a).json()["estimates"] == []


def test_stale_corrections_dont_overwrite_newer_changes(client, signup):
    a, _ = signup("Alpha")
    b, _ = signup("Bravo")
    c, _ = signup("Charlie")
    d, _ = signup("Delta")
    eid = client.post("/api/rates/estimates", json=EST, headers=a).json()["id"]
    first = _correct(client, b, eid, low=60).json()["id"]
    second = _correct(client, c, eid, low=70).json()["id"]
    client.post(f"/api/rates/estimates/corrections/{first}/vote", json={"vote": "confirm"}, headers=a)
    client.post(f"/api/rates/estimates/corrections/{first}/vote", json={"vote": "confirm"}, headers=d)
    # Applying the first one retires the second, which was made against the old figures.
    assert client.post(f"/api/rates/estimates/corrections/{second}/vote", json={"vote": "confirm"}, headers=a).status_code == 404
    assert client.get("/api/rates/estimates?trade=electrician", headers=a).json()["estimates"][0]["low"] == 60


def test_corrections_section_rules(client, signup, db):
    a, _ = signup("Alpha")
    b, _ = signup("Bravo")
    mod, m = signup("Moderator")
    client.portal.call(db.users.update_one, {"_id": m["id"]}, {"$set": {"role": "admin"}})
    eid = client.post("/api/rates/estimates", json=EST, headers=a).json()["id"]
    assert _correct(client, b, eid).status_code == 422  # same as listed (reason only, no figures changed)
    assert client.post(f"/api/rates/estimates/{eid}/corrections", json={"kind": "change", "reason": "wrong"}, headers=b).status_code == 422
    assert _correct(client, b, eid, trade="plumber", low=1).status_code == 422
    cid = _correct(client, b, eid, low=65).json()["id"]
    assert _correct(client, b, eid, low=66).status_code == 409  # one open correction per member per estimate
    section = client.get("/api/rates/estimates/corrections/open?trade=electrician&location=78701", headers=a).json()
    assert [x["id"] for x in section] == [cid] and section[0]["needed"] == 2 and section[0]["proposed_by"] == "Bravo"
    # The adder is told about it.
    notes = client.portal.call(lambda: db.notifications.find({"kind": "estimate"}).to_list(10))
    assert len(notes) == 1
    # Moderators can reject; members can't use moderator actions.
    assert client.post(f"/api/rates/estimates/corrections/{cid}/reject", headers=a).status_code == 403
    assert client.post(f"/api/rates/estimates/corrections/{cid}/reject", headers=mod).json() == {"status": "rejected"}
    assert client.get("/api/rates/estimates/corrections/open?trade=electrician", headers=a).json() == []
    # Withdrawal by the suggester.
    cid2 = _correct(client, b, eid, low=66).json()["id"]
    assert client.post(f"/api/rates/estimates/corrections/{cid2}/withdraw", headers=a).status_code == 404
    assert client.post(f"/api/rates/estimates/corrections/{cid2}/withdraw", headers=b).json() == {"status": "withdrawn"}


@pytest.mark.parametrize("bad", [
    {"source_url": "http://homeguide.com"},
    {"low": 120, "high": 100},
    {"checked_on": "2026-10-24"},
    {"checked_on": "2025-09-01"},
    {"scope": "local", "location": ""},
])
def test_estimates_need_a_source_and_a_sane_range(client, signup, bad):
    h, _ = signup()
    assert client.post("/api/rates/estimates", json={**EST, **bad}, headers=h).status_code == 422


def test_scope_filters_and_stale_flags(client, signup):
    h, _ = signup()
    client.post("/api/rates/estimates", json=EST, headers=h)
    client.post("/api/rates/estimates", json={**EST, "service": "Austin hourly", "scope": "local", "location": "78701"}, headers=h)
    client.post("/api/rates/estimates", json={**EST, "service": "New York hourly", "scope": "local", "location": "10001"}, headers=h)
    client.post("/api/rates/estimates", json={**EST, "service": "Texas hourly", "scope": "state", "location": "Dallas, TX", "checked_on": "2026-03-01"}, headers=h)
    near = client.get("/api/rates/estimates?trade=electrician&location=78702", headers=h).json()["estimates"]
    assert [e["service"] for e in near] == ["Austin hourly", "Texas hourly", "Hourly labor rate"]
    assert next(e for e in near if e["service"] == "Texas hourly")["stale"] is True
    assert [e["service"] for e in client.get("/api/rates/estimates?trade=electrician", headers=h).json()["estimates"]] == ["Hourly labor rate"]
    assert client.get("/api/rates/estimates?trade=plumber&location=78702", headers=h).json()["estimates"] == []


def test_reported_estimates_can_be_hidden(client, signup, db):
    h, _ = signup()
    mod, m = signup("Moderator")
    client.portal.call(db.users.update_one, {"_id": m["id"]}, {"$set": {"role": "admin"}})
    eid = client.post("/api/rates/estimates", json=EST, headers=h).json()["id"]
    rep = client.post("/api/reports", json={"target_type": "estimate", "target_id": eid, "reason": "fabricated", "note": "Source page says $60-120"}, headers=h).json()
    client.post(f"/api/admin/reports/{rep['id']}/resolve", json={"action": "hide"}, headers=mod)
    assert client.get("/api/rates/estimates?trade=electrician", headers=h).json()["estimates"] == []
    assert client.put(f"/api/rates/estimates/{eid}", json=EST, headers=h).status_code == 404
    assert client.post(f"/api/rates/estimates/{eid}/corrections", json={"kind": "remove", "reason": "gone already"}, headers=h).status_code == 404


def test_member_compare_accepts_a_location(client, signup):
    h, _ = signup()
    assert client.get("/api/rates/compare?kind=wage&trade=electrician&location=78701", headers=h).json()["state"] == "TX"
