"""Customer reviews: one per marketplace lead, opened by a win or a finished
job, public on the contractor's page, answered and flagged from the dashboard,
hidden or restored by a moderator."""
import re


def _post(client, **extra):
    data = {"trade": "electrician", "title": "Replace a ceiling fan", "details": "Old fan wobbles, want a new one installed.", "location": "78702",
            "wanted_on": "2026-11-05", "budget": "About $300", "name": "Pat Lee", "email": "Pat@Example.com", "phone": "512-555-0100", "consent": "on", **extra}
    return client.post("/request", data=data, follow_redirects=False)


def _token(res):
    return res.headers["location"].split("/request/")[1].split("?")[0]


def _chosen_lead(client, signup, db, **customer):
    """Run the marketplace flow up to the customer choosing the contractor."""
    token = _token(_post(client, **customer))
    headers, user = signup("Bright Spark Electric")
    job = client.get("/api/marketplace?near=78701&radius=25", headers=headers).json()["requests"][0]
    res = client.post(f"/api/marketplace/{job['id']}/bids", json={"message": "I can do this next week, fan included."}, headers=headers)
    assert res.status_code == 201, res.text
    bid_id = client.portal.call(db.marketplace_bids.find_one, {})["_id"]
    client.post(f"/request/{token}/choose/{bid_id}", follow_redirects=False)
    lead = client.get("/api/inbox", headers=headers).json()[0]
    return token, bid_id, headers, user, lead


def _review_count(client, db):
    return client.portal.call(db.reviews.count_documents, {})


def _win(client, headers, lead):
    res = client.patch(f"/api/inbox/{lead['id']}", json={"status": "won"}, headers=headers)
    assert res.status_code == 200, res.text


def _submit(client, token, bid_id, **form):
    data = {"stars": "5", "text": "On time, tidy, and the fan is silent.", **form}
    return client.post(f"/request/{token}/review/{bid_id}", data=data, follow_redirects=False)


def test_review_opens_only_once_the_lead_is_won(client, signup, db):
    token, bid_id, headers, user, lead = _chosen_lead(client, signup, db)
    # Too early: no form on the page, and a direct post records nothing.
    assert "Post review" not in client.get(f"/request/{token}").text
    res = _submit(client, token, bid_id)
    assert res.status_code == 303 and "reviewed" not in res.headers["location"]
    res = client.post(f"/request/{token}/review/not-a-bid", data={"stars": "5", "text": "Hi"}, follow_redirects=False)
    assert res.status_code == 303
    assert _review_count(client, db) == 0

    _win(client, headers, lead)
    page = client.get(f"/request/{token}").text
    assert "Review Bright Spark Electric" in page and "Post review" in page
    res = _submit(client, token, bid_id)
    assert res.status_code == 303 and "reviewed=1" in res.headers["location"]
    review = client.portal.call(db.reviews.find_one, {})
    assert review["stars"] == 5 and review["status"] == "published" and review["lead_id"] == lead["id"]
    # Named for the public: first name and last initial, never the full name.
    assert review["reviewer_name"] == "Pat L."

    page = client.get(f"/request/{token}").text
    assert "Your review" in page and "the fan is silent" in page
    slug = client.get("/api/me/profile", headers=headers).json()["slug"]
    public = client.get(f"/api/p/{slug}").json()
    assert public["reviews"]["count"] == 1 and public["reviews"]["average"] == 5.0
    assert public["reviews"]["latest"][0]["reviewer_name"] == "Pat L."
    assert "Pat Lee" not in str(public["reviews"]) and "pat@example.com" not in str(public["reviews"])


def test_one_review_per_lead(client, signup, db):
    token, bid_id, headers, user, lead = _chosen_lead(client, signup, db)
    _win(client, headers, lead)
    assert "reviewed=1" in _submit(client, token, bid_id).headers["location"]
    again = _submit(client, token, bid_id, text="A second review that must not land.")
    assert "reviewed" not in again.headers["location"]
    assert _review_count(client, db) == 1
    review = client.portal.call(db.reviews.find_one, {})
    assert "fan is silent" in review["text"]


def test_review_opens_when_a_job_from_the_lead_is_done(client, signup, db):
    token, bid_id, headers, user, lead = _chosen_lead(client, signup, db)
    job = client.post("/api/jobs", json={"title": "Ceiling fan", "quote_id": lead["id"], "status": "scheduled"}, headers=headers)
    assert job.status_code == 201, job.text
    # A job that is only scheduled doesn't open the review yet.
    _submit(client, token, bid_id)
    assert _review_count(client, db) == 0
    done = client.patch(f"/api/jobs/{job.json()['id']}", json={"status": "done"}, headers=headers)
    assert done.status_code == 200, done.text
    # The lead itself was never marked won; the finished job opens the review.
    assert client.get("/api/inbox", headers=headers).json()[0]["status"] == "waiting"
    assert "reviewed=1" in _submit(client, token, bid_id).headers["location"]
    assert _review_count(client, db) == 1


def test_review_validation_honeypot_and_unknown_links(client, signup, db):
    token, bid_id, headers, user, lead = _chosen_lead(client, signup, db)
    _win(client, headers, lead)
    # (Submissions share the quote form's per-address limit, so this test
    # stays under it: three bad tries, the honeypot, one unknown link.)
    for form in ({"stars": "9"}, {"text": "   "}, {"text": "x" * 1001}):
        res = _submit(client, token, bid_id, **form)
        assert "review_error=1" in res.headers["location"], form
    assert _review_count(client, db) == 0
    # The honeypot answers like a success and records nothing.
    res = _submit(client, token, bid_id, website="spam")
    assert "reviewed=1" in res.headers["location"]
    assert _review_count(client, db) == 0
    # A made-up link gets nothing.
    assert client.post("/request/nope/review/x", data={"stars": "5", "text": "Hi"}).status_code == 404


def test_contractor_responds_and_can_edit(client, signup, db):
    token, bid_id, headers, user, lead = _chosen_lead(client, signup, db)
    _win(client, headers, lead)
    _submit(client, token, bid_id, stars="4", text="Good work, one small delay.")
    mine = client.get("/api/reviews", headers=headers).json()
    assert mine["count"] == 1 and mine["average"] == 4.0
    review = mine["reviews"][0]
    assert review["response"] is None and review["job_type"] == "Replace a ceiling fan"

    res = client.post(f"/api/reviews/{review['id']}/response", json={"text": "Thanks Pat — sorry about the delay."}, headers=headers)
    assert res.status_code == 200 and res.json()["response"]["text"].startswith("Thanks Pat")
    slug = client.get("/api/me/profile", headers=headers).json()["slug"]
    full = client.get(f"/api/p/{slug}/full").json()
    assert full["reviews"]["latest"][0]["response"]["text"].startswith("Thanks Pat")
    html = client.get(f"/p/{slug}/full").text
    assert "Good work, one small delay." in html and "Response from the business" in html

    edited = client.post(f"/api/reviews/{review['id']}/response", json={"text": "Thanks! All sorted now."}, headers=headers)
    assert edited.json()["response"]["text"] == "Thanks! All sorted now."
    assert edited.json()["response"]["edited_at"] is not None

    # Not the owner's review: another contractor sees nothing and can do nothing.
    other, _ = signup("Someone Else", trade="plumber")
    assert client.get("/api/reviews", headers=other).json()["reviews"] == []
    assert client.post(f"/api/reviews/{review['id']}/response", json={"text": "Not mine"}, headers=other).status_code == 404
    assert client.post(f"/api/reviews/{review['id']}/flag", json={}, headers=other).status_code == 404
    client.cookies.clear()  # drop the session cookie the signups set
    assert client.get("/api/reviews").status_code == 401


def _make_admin(client, signup, db):
    headers, user = signup("Moderator")
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"role": "admin"}})
    return headers


def test_flag_keeps_review_public_until_a_moderator_hides_it(client, signup, db):
    token, bid_id, headers, user, lead = _chosen_lead(client, signup, db)
    _win(client, headers, lead)
    _submit(client, token, bid_id, stars="1", text="Never showed up.")
    review = client.get("/api/reviews", headers=headers).json()["reviews"][0]
    slug = client.get("/api/me/profile", headers=headers).json()["slug"]

    flagged = client.post(f"/api/reviews/{review['id']}/flag", json={"note": "We did show; this is a mix-up."}, headers=headers)
    assert flagged.status_code == 200 and flagged.json()["status"] == "flagged"
    # Flagged is not hidden: the page and the average still count it.
    assert client.get(f"/api/p/{slug}").json()["reviews"]["count"] == 1

    mod = _make_admin(client, signup, db)
    assert client.get("/api/admin/reviews", headers=headers).status_code == 403
    queue = client.get("/api/admin/reviews", headers=mod).json()
    assert [r["id"] for r in queue] == [review["id"]] and queue[0]["flag_note"] == "We did show; this is a mix-up."
    assert queue[0]["business_name"] == "Bright Spark Electric"

    assert client.post(f"/api/admin/reviews/{review['id']}/hide", headers=mod).json()["status"] == "hidden"
    assert client.get(f"/api/p/{slug}").json()["reviews"]["count"] == 0
    assert "Never showed up." not in client.get(f"/p/{slug}").text
    # The contractor still sees it in the dashboard, marked hidden, and can't flag it again.
    mine = client.get("/api/reviews", headers=headers).json()["reviews"][0]
    assert mine["status"] == "hidden"
    assert client.post(f"/api/reviews/{review['id']}/flag", json={}, headers=headers).status_code == 409

    assert client.post(f"/api/admin/reviews/{review['id']}/unhide", headers=mod).json()["status"] == "published"
    assert client.get(f"/api/p/{slug}").json()["reviews"]["count"] == 1


def _second_lead(client, db, headers, **customer):
    """A second customer choosing the same contractor."""
    token = _token(_post(client, **customer))
    found = client.get("/api/marketplace?near=78701&radius=25", headers=headers).json()["requests"]
    job = next(r for r in found if r["title"] == customer.get("title", "Replace a ceiling fan"))
    res = client.post(f"/api/marketplace/{job['id']}/bids", json={"message": "Happy to take this one too."}, headers=headers)
    assert res.status_code == 201, res.text
    bid = client.portal.call(db.marketplace_bids.find_one, {"request_id": job["id"]})
    client.post(f"/request/{token}/choose/{bid['_id']}", follow_redirects=False)
    inbox = client.get("/api/inbox", headers=headers).json()
    lead = next(e for e in inbox if e["name"] == customer.get("name", "Pat Lee"))
    return token, bid["_id"], lead


def test_public_pages_show_stars_average_and_rating_markup(client, signup, db):
    token, bid_id, headers, user, lead = _chosen_lead(client, signup, db)
    _win(client, headers, lead)
    _submit(client, token, bid_id, stars="5")
    # A second customer and a second job, for an average that needs rounding.
    token2, bid2, lead2 = _second_lead(client, db, headers, name="Sam Ortiz", email="sam@example.com", title="Fix the porch light")
    _win(client, headers, lead2)
    _submit(client, token2, bid2, stars="2", text="Slow to reply.")

    slug = client.get("/api/me/profile", headers=headers).json()["slug"]
    public = client.get(f"/api/p/{slug}").json()
    assert public["reviews"]["count"] == 2 and public["reviews"]["average"] == 3.5
    assert [r["stars"] for r in public["reviews"]["latest"]] == [2, 5]  # newest first

    html = client.get(f"/p/{slug}").text
    assert "Reviews" in html and "3.5" in html and "2 reviews" in html
    assert "Slow to reply." in html and "Sam O." in html
    data = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1)
    import json as _json
    rating = _json.loads(data)["aggregateRating"]
    assert rating == {"@type": "AggregateRating", "ratingValue": 3.5, "reviewCount": 2}
    full_html = client.get(f"/p/{slug}/full").text
    assert "the fan is silent" in full_html and "Pat L." in full_html
