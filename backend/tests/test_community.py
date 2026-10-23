import io

from PIL import Image


def _admin(client, signup, db):
    headers, user = signup("Trade Circle Staff", email="staff@example.com")
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"role": "admin"}})
    return headers


def ask(client, headers, title="Where to get 12/2 Romex cheap?", location="Austin, TX", **extra):
    body = {"kind": "supply_question", "title": title, "body": "Need 1000 ft.", "location": location, "trade_tags": ["electrician"], "category": "electrical", **extra}
    return client.post("/api/posts", headers=headers, json=body)


def photo(client, headers):
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), (10, 90, 160)).save(buf, "JPEG")
    return client.post("/api/media/photos", headers=headers, files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")}).json()


def test_members_only(client):
    assert client.get("/api/posts").status_code == 401


def test_question_publishes_with_location_and_filters(client, signup):
    a, _ = signup()
    res = ask(client, a)
    assert res.status_code == 201 and res.json()["status"] == "published"
    assert res.json()["location"] == {"label": "Austin, TX", "city": "Austin", "state": "TX"}
    ask(client, a, title="Copper prices in Dallas?", location="75201", category="plumbing", trade_tags=["plumber"])
    # Taylor, TX is 30 miles out: inside the search box's corner but outside a 25-mile circle.
    ask(client, a, title="Conduit in Taylor?", location="76574", category="electrical")

    near_austin = client.get("/api/posts", headers=a, params={"near": "78701", "radius": 25}).json()
    assert [p["title"] for p in near_austin["posts"]] == ["Where to get 12/2 Romex cheap?"]
    assert near_austin["posts"][0]["distance_miles"] < 10
    wide = client.get("/api/posts", headers=a, params={"near": "78701", "radius": 250}).json()
    assert len(wide["posts"]) == 3
    assert [p["title"] for p in client.get("/api/posts", headers=a, params={"category": "plumbing"}).json()["posts"]] == ["Copper prices in Dallas?"]
    assert len(client.get("/api/posts", headers=a, params={"trade": "electrician"}).json()["posts"]) == 2
    assert len(client.get("/api/posts", headers=a, params={"q": "romex"}).json()["posts"]) == 1
    assert client.get("/api/posts", headers=a, params={"near": "Nowhere, ZZ"}).status_code == 422


def test_titles_required_and_bad_places_refused(client, signup):
    a, _ = signup()
    assert ask(client, a, title="").status_code == 422
    assert ask(client, a, location="99999").status_code == 422


def test_drafts_stay_private_until_published(client, signup):
    a, _ = signup()
    b, _ = signup("Other Co", trade="painter")
    draft = client.post("/api/posts", headers=a, json={"kind": "lesson", "title": "Check the breaker first", "fields": {"what_happened": "No power"}}).json()
    assert draft["status"] == "draft"
    assert client.get(f"/api/posts/{draft['id']}", headers=b).status_code == 404
    assert client.get("/api/posts", headers=b).json()["posts"] == []
    assert client.post(f"/api/posts/{draft['id']}/comments", headers=a, json={"body": "hi"}).status_code == 409
    published = client.post(f"/api/posts/{draft['id']}/publish", headers=a).json()
    assert published["status"] == "published"
    assert client.get(f"/api/posts/{draft['id']}", headers=b).status_code == 200
    assert client.post(f"/api/posts/{draft['id']}/publish", headers=a).status_code == 409


def test_only_your_own_uploads_can_be_attached(client, signup):
    a, _ = signup()
    b, _ = signup("Other Co", trade="painter")
    mine = photo(client, a)
    theirs = photo(client, b)
    assert ask(client, a, photos=[{"id": mine["id"]}]).json()["photos"][0]["thumb_url"] == mine["thumb_url"]
    assert ask(client, a, photos=[{"id": theirs["id"]}]).status_code == 422


def test_comments_count_and_ownership(client, signup):
    a, _ = signup()
    b, _ = signup("Other Co", trade="painter")
    post = ask(client, a).json()
    c = client.post(f"/api/posts/{post['id']}/comments", headers=b, json={"body": "Try the supply house on Lamar."}).json()
    detail = client.get(f"/api/posts/{post['id']}", headers=a).json()
    assert detail["comment_count"] == 1 and detail["comments"][0]["author"]["business_name"] == "Other Co"
    assert client.delete(f"/api/comments/{c['id']}", headers=a).status_code == 404
    assert client.delete(f"/api/comments/{c['id']}", headers=b).status_code == 204
    assert client.get(f"/api/posts/{post['id']}", headers=a).json()["comment_count"] == 0


def test_equipment_posts_require_affiliation_disclosure(client, signup):
    a, _ = signup()
    base = {"kind": "equipment", "title": "Two years on the M18 SDS", "trade_tags": ["electrician"]}
    assert client.post("/api/posts", headers=a, json={**base, "fields": {"product": "M18 SDS"}}).status_code == 422
    assert client.post("/api/posts", headers=a, json={**base, "fields": {"product": "M18 SDS", "affiliation": "seller"}}).status_code == 422
    ok = client.post("/api/posts", headers=a, json={**base, "fields": {"product": "M18 SDS", "buy_again": "yes", "affiliation": "none"}})
    assert ok.status_code == 201 and ok.json()["fields"]["affiliation"] == "none"


def test_reports_and_moderation(client, signup, db):
    a, _ = signup()
    b, _ = signup("Other Co", trade="painter")
    post = ask(client, a, title="Buy my stuff at spam dot com").json()
    first = client.post("/api/reports", headers=b, json={"target_type": "post", "target_id": post["id"], "reason": "spam"}).json()
    again = client.post("/api/reports", headers=b, json={"target_type": "post", "target_id": post["id"], "reason": "spam"}).json()
    assert first["id"] == again["id"]
    assert client.post("/api/reports", headers=b, json={"target_type": "post", "target_id": "nope", "reason": "spam"}).status_code == 404
    assert client.get("/api/admin/reports", headers=b).status_code == 403

    admin = _admin(client, signup, db)
    queue = client.get("/api/admin/reports", headers=admin).json()
    assert queue[0]["target"]["title"] == "Buy my stuff at spam dot com"
    client.post(f"/api/admin/reports/{queue[0]['id']}/resolve", headers=admin, json={"action": "hide"})
    assert client.get("/api/posts", headers=b).json()["posts"] == []
    assert client.get(f"/api/posts/{post['id']}", headers=b).status_code == 404
    # The author can still see it, marked hidden, and can't edit it back.
    assert client.get(f"/api/posts/{post['id']}", headers=a).json()["status"] == "hidden"
    assert client.patch(f"/api/posts/{post['id']}", headers=a, json={"title": "Edited"}).status_code == 409
