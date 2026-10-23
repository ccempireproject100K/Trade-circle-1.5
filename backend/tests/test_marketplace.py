"""The lead marketplace: public posting, matching previews, bid limits, choosing, privacy."""
import io

from PIL import Image


def _post(client, **extra):
    data = {"trade": "electrician", "title": "Replace a ceiling fan", "details": "Old fan wobbles, want a new one installed.", "location": "78702",
            "wanted_on": "2026-11-05", "budget": "About $300", "name": "Pat Lee", "email": "Pat@Example.com", "phone": "512-555-0100", "consent": "on", **extra}
    return client.post("/request", data=data, follow_redirects=False)


def _token(res):
    return res.headers["location"].split("/request/")[1].split("?")[0]


def test_public_form_validates_and_keeps_answers(client):
    page = client.get("/request")
    assert page.status_code == 200 and "Post my job" in page.text and "form-action 'self'" in page.headers["content-security-policy"]
    bad = client.post("/request", data={"trade": "electrician", "title": "x", "details": "short", "location": "99999", "name": "", "email": "nope"})
    assert bad.status_code == 422
    for msg in ("Add a short title", "Describe the job", "ZIP code 99999", "Add your name", "Add an email", "Tick the box"):
        assert msg in bad.text
    assert 'value="x"' in bad.text  # what they typed stays


def test_post_preview_bid_and_choose(client, signup, db):
    res = _post(client)
    assert res.status_code == 303
    token = _token(res)
    page = client.get(f"/request/{token}?new=1")
    assert "Your job is posted" in page.text and "No bids yet" in page.text and page.headers["referrer-policy"] == "no-referrer"
    sent = client.portal.call(db.outbox.find_one, {"kind": "marketplace_posted"})
    assert sent["to"] == "pat@example.com" and token in sent["body"]

    h, user = signup("Bright Spark Electric")
    assert client.get("/api/marketplace", headers=h).json()["needs_area"] is True
    found = client.get("/api/marketplace?near=78701&radius=25", headers=h).json()
    job = found["requests"][0]
    assert job["title"] == "Replace a ceiling fan" and job["area"] == "78702" and job["missing"] == ["photos"]
    assert any("your trade" in w for w in job["why"]) and any("mi from your area" in w for w in job["why"])
    # No customer contact details before they choose.
    assert "Pat" not in str(job) and "512" not in str(job) and "customer" not in job
    # Other trades and far-away members don't see it.
    p, _ = signup("Pipes Co", trade="plumber")
    assert client.get("/api/marketplace?near=78701", headers=p).json()["requests"] == []
    assert client.get("/api/marketplace?near=10001", headers=h).json()["requests"] == []

    b = client.post(f"/api/marketplace/{job['id']}/bids", json={"message": "I can do this next week, fan included.", "price_low_cents": 25000, "price_high_cents": 35000}, headers=h)
    assert b.status_code == 201 and b.json()["bids_left"] == 2
    assert client.post(f"/api/marketplace/{job['id']}/bids", json={"message": "Another bid from me here."}, headers=h).status_code == 409
    assert client.portal.call(db.outbox.find_one, {"kind": "marketplace_bid"})["to"] == "pat@example.com"

    page = client.get(f"/request/{token}")
    assert "Bright Spark Electric" in page.text and "$250–$350 estimate" in page.text
    bid_id = client.portal.call(db.marketplace_bids.find_one, {})["_id"]
    client.post(f"/request/{token}/choose/{bid_id}", follow_redirects=False)
    assert "You chose Bright Spark Electric" in client.get(f"/request/{token}").text
    lead = client.get("/api/inbox", headers=h).json()[0]
    assert (lead["name"], lead["email"], lead["source"]) == ("Pat Lee", "pat@example.com", "marketplace")
    assert client.get("/api/marketplace/mine", headers=h).json()[0]["status"] == "chosen"


def test_free_members_get_three_bids_a_month_full_unlimited(client, signup, db):
    tokens = [_token(_post(client, title=f"Job number {i}")) for i in range(4)]
    h, user = signup()
    jobs = client.get("/api/marketplace?near=78701", headers=h).json()["requests"]
    assert len(jobs) == 4
    for j in jobs[:3]:
        assert client.post(f"/api/marketplace/{j['id']}/bids", json={"message": "Happy to help with this job."}, headers=h).status_code == 201
    over = client.post(f"/api/marketplace/{jobs[3]['id']}/bids", json={"message": "Happy to help with this job."}, headers=h)
    assert over.status_code == 402 and "3 bids this month" in over.json()["detail"]
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"tier": "full"}})
    assert client.post(f"/api/marketplace/{jobs[3]['id']}/bids", json={"message": "Happy to help with this job."}, headers=h).status_code == 201
    assert client.get("/api/marketplace?near=78701", headers=h).json()["bids_left"] is None


def test_closed_expired_and_photos(client, signup, db):
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(buf, "JPEG")
    res = client.post("/request", data={"trade": "electrician", "title": "Fix outlet", "details": "Outlet sparks when plugging in.", "location": "78701", "name": "Sam", "email": "sam@example.com", "consent": "on"},
                      files=[("photos", ("a.jpg", buf.getvalue(), "image/jpeg"))], follow_redirects=False)
    token = _token(res)
    h, _ = signup()
    job = client.get("/api/marketplace?near=78701", headers=h).json()["requests"][0]
    assert len(job["photos"]) == 1 and set(job["missing"]) == {"date", "budget"}
    client.post(f"/request/{token}/close", follow_redirects=False)
    assert client.get("/api/marketplace?near=78701", headers=h).json()["requests"] == []
    assert client.post(f"/api/marketplace/{job['id']}/bids", json={"message": "Can I still bid here?"}, headers=h).status_code == 404
    assert "closed to new bids" in client.get(f"/request/{token}").text
    # Requests stop showing after 14 days.
    t2 = _token(_post(client))
    client.portal.call(db.marketplace.update_one, {"token": t2}, {"$set": {"closes_on": "2026-10-22"}})
    assert client.get("/api/marketplace?near=78701", headers=h).json()["requests"] == []


def test_honeypot_and_unknown_links(client, db):
    assert client.post("/request", data={"website": "spam"}, follow_redirects=False).headers["location"] == "/request/sent"
    assert client.portal.call(db.marketplace.count_documents, {}) == 0
    assert client.get("/request/nope").status_code == 404


def test_reported_requests_can_be_hidden(client, signup, db):
    _post(client)
    h, _ = signup()
    mod, m = signup("Mod")
    client.portal.call(db.users.update_one, {"_id": m["id"]}, {"$set": {"role": "admin"}})
    job = client.get("/api/marketplace?near=78701", headers=h).json()["requests"][0]
    rep = client.post("/api/reports", json={"target_type": "lead", "target_id": job["id"], "reason": "spam"}, headers=h).json()
    client.post(f"/api/admin/reports/{rep['id']}/resolve", json={"action": "hide"}, headers=mod)
    assert client.get("/api/marketplace?near=78701", headers=h).json()["requests"] == []
