import io

from PIL import Image


def photo(client, headers, color=(10, 90, 160)):
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), color).save(buf, "JPEG")
    return client.post("/api/media/photos", headers=headers, files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")}).json()


def start(client, headers, **fields):
    return client.post("/api/posts", headers=headers, json={"kind": "project", "fields": {"job": "Swapped a 100A panel for 200A", **fields}}).json()


def test_walkthrough_saves_as_draft_and_resumes(client, signup):
    a, _ = signup()
    draft = start(client, a, step=1)
    assert draft["status"] == "draft"
    # Autosave sends only what changed; earlier answers are kept.
    client.patch(f"/api/posts/{draft['id']}", headers=a, json={"fields": {"challenge": "Meter base was rusted through", "step": 3}})
    mine = client.get("/api/posts/mine", headers=a, params={"kind": "project", "post_status": "draft"}).json()
    assert len(mine) == 1
    fields = mine[0]["fields"]
    assert fields["job"] == "Swapped a 100A panel for 200A"
    assert fields["challenge"] == "Meter base was rusted through"
    assert fields["step"] == 3
    # Every answer is optional.
    assert fields["handled"] == "" and fields["learned"] == ""


def test_walkthrough_photos_keep_their_step(client, signup):
    a, _ = signup()
    before, after = photo(client, a), photo(client, a, (200, 200, 200))
    draft = start(client, a)
    res = client.patch(f"/api/posts/{draft['id']}", headers=a, json={"photos": [{"id": before["id"], "group": "before"}, {"id": after["id"], "group": "after"}]})
    assert [p["group"] for p in res.json()["photos"]] == ["before", "after"]


def test_nothing_is_published_without_the_explicit_step(client, signup):
    a, _ = signup()
    b, _ = signup("Other Co", trade="painter")
    draft = start(client, a)
    client.patch(f"/api/posts/{draft['id']}", headers=a, json={"title": "200A service upgrade", "fields": {"learned": "Order the meter base early"}})
    assert client.get("/api/posts", headers=b, params={"kind": "project"}).json()["posts"] == []
    assert client.get(f"/api/posts/{draft['id']}", headers=b).status_code == 404
    # Preview: the author sees exactly what will be posted.
    preview = client.get(f"/api/posts/{draft['id']}", headers=a).json()
    assert preview["status"] == "draft" and preview["title"] == "200A service upgrade"
    client.post(f"/api/posts/{draft['id']}/publish", headers=a)
    assert len(client.get("/api/posts", headers=b, params={"kind": "project"}).json()["posts"]) == 1


def test_empty_walkthrough_cannot_be_published(client, signup):
    a, _ = signup()
    empty = client.post("/api/posts", headers=a, json={"kind": "project"}).json()
    assert client.post(f"/api/posts/{empty['id']}/publish", headers=a).status_code == 422


def test_featured_walkthroughs_show_on_the_full_profile(client, signup):
    a, _ = signup()
    slug = client.get("/api/me/profile", headers=a).json()["slug"]
    after = photo(client, a)
    featured = start(client, a)
    client.patch(f"/api/posts/{featured['id']}", headers=a, json={"title": "200A service upgrade", "featured": True, "photos": [{"id": after["id"], "group": "after"}], "fields": {"learned": "Order the meter base early"}})
    not_featured = start(client, a)
    client.patch(f"/api/posts/{not_featured['id']}", headers=a, json={"title": "Kitchen circuits"})
    draft_featured = start(client, a)
    client.patch(f"/api/posts/{draft_featured['id']}", headers=a, json={"title": "Still a draft", "featured": True})
    # Featured but unpublished: not on the profile yet.
    assert client.get(f"/api/p/{slug}/full").json()["projects"] == []
    for post in (featured, not_featured):
        client.post(f"/api/posts/{post['id']}/publish", headers=a)

    projects = client.get(f"/api/p/{slug}/full").json()["projects"]
    assert [p["title"] for p in projects] == ["200A service upgrade"]
    assert projects[0]["photos"][0]["thumb_url"] == after["thumb_url"]
    html = client.get(f"/p/{slug}/full").text
    assert "Featured projects" in html and "Order the meter base early" in html
    assert "Kitchen circuits" not in html and "Still a draft" not in html


def test_only_projects_can_be_featured(client, signup):
    a, _ = signup()
    lesson = client.post("/api/posts", headers=a, json={"kind": "lesson", "title": "x", "featured": True, "publish": True}).json()
    assert lesson["featured"] is False
