"""Employment listings and member spot/deal suggestions reuse community posts."""

OPENING = {"kind": "opening", "title": "Hiring a journeyman electrician", "location": "78701", "trade_tags": ["electrician"], "fields": {"role": "Journeyman electrician", "employment_type": "full_time", "pay": "$30-36/hr"}}


def test_opening_is_its_own_category_and_needs_a_place(client, signup):
    h, _ = signup()
    assert client.post("/api/posts", json={**OPENING, "location": ""}, headers=h).status_code == 422
    res = client.post("/api/posts", json=OPENING, headers=h)
    assert res.status_code == 201, res.text
    post = res.json()
    assert post["kind"] == "opening" and post["status"] == "published"
    found = client.get("/api/posts?kind=opening", headers=h).json()["posts"]
    assert [p["id"] for p in found] == [post["id"]]
    assert client.get("/api/posts?kind=project", headers=h).json()["posts"] == []
    # Searchable by trade and area like other posts.
    assert client.get("/api/posts?kind=opening&near=78702&radius=10", headers=h).json()["posts"]


def test_filled_and_expired_openings_leave_search(client, signup):
    h, _ = signup()
    filled = client.post("/api/posts", json=OPENING, headers=h).json()
    expired = client.post("/api/posts", json={**OPENING, "fields": {**OPENING["fields"], "apply_by": "2026-10-22"}}, headers=h).json()
    open_ = client.post("/api/posts", json={**OPENING, "fields": {**OPENING["fields"], "apply_by": "2026-10-23"}}, headers=h).json()
    assert client.patch(f"/api/posts/{filled['id']}", json={"fields": {"filled": True}}, headers=h).status_code == 200
    ids = {p["id"] for p in client.get("/api/posts?kind=opening", headers=h).json()["posts"]}
    assert ids == {open_["id"]}
    mine = {p["id"] for p in client.get("/api/posts/mine?kind=opening", headers=h).json()}
    assert {filled["id"], expired["id"]} <= mine


def test_spot_requires_disclosure(client, signup):
    h, _ = signup()
    base = {"kind": "spot", "title": "Best breakfast tacos near the supply house", "location": "78701", "fields": {"place": "Taco stand", "suggestion": "spot", "connection": "owner"}}
    assert client.post("/api/posts", json=base, headers=h).status_code == 422
    base["fields"]["connection_detail"] = "My cousin runs it"
    assert client.post("/api/posts", json=base, headers=h).status_code == 201
    bad_link = {**base, "fields": {**base["fields"], "link": "javascript:alert(1)"}}
    assert client.post("/api/posts", json=bad_link, headers=h).status_code == 422
