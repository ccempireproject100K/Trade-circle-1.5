QUOTE = {"name": "Dana Homeowner", "phone": "+15125550199", "message": "Need a panel upgrade", "job_type": "Panel"}


def _slug(client, headers):
    return client.get("/api/me/profile", headers=headers).json()["slug"]


def test_signup_creates_unverified_profile_with_landing_page(client, signup):
    headers, _ = signup("Bright Spark Electric")
    slug = _slug(client, headers)
    assert slug == "bright-spark-electric"
    page = client.get(f"/api/p/{slug}").json()
    assert page["business_name"] == "Bright Spark Electric"
    assert page["verified"] is False
    assert {"type": "unverified", "label": "Unverified"} in page["badges"]
    assert page["quote_enabled"] is True


def test_duplicate_business_names_get_distinct_slugs(client, signup):
    a, _ = signup("Ace Roofing", trade="roofer")
    b, _ = signup("Ace Roofing", trade="roofer")
    assert _slug(client, a) != _slug(client, b)


def test_profile_update_call_links_and_layout_reflow(client, signup):
    headers, _ = signup()
    res = client.put(
        "/api/me/profile",
        headers=headers,
        json={
            "tagline": "Licensed. On time.",
            "phone": "+15125550100",
            "facetime": "spark@example.com",
            "brand_color": "#FF6600",
            "layout": ["portfolio", "bogus", "portfolio", "about"],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["layout"] == ["portfolio", "about", "projects", "licenses", "insurance", "service_area", "quote"]
    page = client.get(f"/api/p/{_slug(client, headers)}").json()
    assert page["call"] == {"tel": "tel:+15125550100", "facetime": "facetime:spark@example.com"}
    assert page["brand_color"] == "#FF6600"


def test_profile_rejects_bad_input(client, signup):
    headers, _ = signup()
    assert client.put("/api/me/profile", headers=headers, json={"phone": "555-0100"}).status_code == 422
    assert client.put("/api/me/profile", headers=headers, json={"trade": "astronaut"}).status_code == 422
    assert client.put("/api/me/profile", headers=headers, json={"owner_id": "someone"}).status_code == 422


def test_lapsed_cert_badge_and_recert_banner(client, signup):
    headers, _ = signup()
    client.put(
        "/api/me/profile",
        headers=headers,
        json={
            "licenses": [
                {"name": "Master Electrician", "expires_on": "2026-01-31"},
                {"name": "OSHA 30", "expires_on": "2028-10-21", "renewed_on": "2026-10-21"},
                {"name": "EPA 608", "expires_on": "2028-01-01", "renewed_on": "2026-10-01"},
            ]
        },
    )
    page = client.get(f"/api/p/{_slug(client, headers)}/full").json()
    labels = [b["label"] for b in page["badges"]]
    assert "Master Electrician lapsed" in labels
    # Renewed two days ago: banner still up. Renewed three weeks ago: gone.
    assert page["celebrations"] == [{"type": "recertified", "label": "Re-certified: OSHA 30"}]
    assert [lic["lapsed"] for lic in page["licenses"]] == [True, False, False]


def test_insurance_pending_then_verified_by_admin(client, signup, db):
    headers, _ = signup()
    slug = _slug(client, headers)
    res = client.put(
        "/api/me/insurance",
        headers=headers,
        json={"carrier": "Acme Mutual", "policy_number": "GL-1", "expires_on": "2027-06-30", "document_url": "https://files.example.com/coi.pdf"},
    )
    assert res.json() == {"status": "pending"}
    assert client.get(f"/api/p/{slug}/full").json()["insurance"]["status"] == "pending"

    admin_headers, admin = signup("Trade Circle Staff", email="admin@example.com")
    client.portal.call(db.users.update_one, {"_id": admin["id"]}, {"$set": {"role": "admin"}})
    profile_id = client.get("/api/me/profile", headers=headers).json()["id"]
    res = client.post(f"/api/admin/profiles/{profile_id}/insurance/verify", headers=admin_headers)
    assert res.status_code == 200
    page = client.get(f"/api/p/{slug}").json()
    assert {"type": "insurance_verified", "label": "Insured"} in page["badges"]


def test_portfolio_add_reorder_and_public_layers(client, signup):
    headers, _ = signup()
    ids = []
    for n in range(8):
        res = client.post("/api/me/portfolio", headers=headers, json={"image_url": f"https://img.example.com/{n}.jpg", "caption": f"Job {n}"})
        assert res.status_code == 201
        ids.append(res.json()["id"])
    assert client.post("/api/me/portfolio", headers=headers, json={"image_url": "http://img.example.com/x.jpg"}).status_code == 422

    new_order = list(reversed(ids))
    assert client.put("/api/me/portfolio/order", headers=headers, json={"ids": new_order}).status_code == 200
    assert client.put("/api/me/portfolio/order", headers=headers, json={"ids": new_order[:3]}).status_code == 422

    slug = _slug(client, headers)
    landing = client.get(f"/api/p/{slug}").json()
    full = client.get(f"/api/p/{slug}/full").json()
    assert [p["id"] for p in landing["portfolio"]] == new_order[:6]
    assert [p["id"] for p in full["portfolio"]] == new_order


def test_quote_lands_in_owner_inbox_only(client, signup):
    owner, _ = signup("Owner Plumbing", trade="plumber")
    other, _ = signup("Other Plumbing", trade="plumber")
    slug = _slug(client, owner)

    assert client.post(f"/api/p/{slug}/quote", json=QUOTE).status_code == 202
    inbox = client.get("/api/inbox", headers=owner).json()
    assert len(inbox) == 1 and inbox[0]["name"] == "Dana Homeowner" and inbox[0]["status"] == "waiting"
    assert client.get("/api/inbox", headers=other).json() == []

    quote_id = inbox[0]["id"]
    assert client.patch(f"/api/inbox/{quote_id}", headers=other, json={"status": "won"}).status_code == 404
    assert client.patch(f"/api/inbox/{quote_id}", headers=owner, json={"status": "followed_up"}).json()["status"] == "followed_up"


def test_quote_needs_contact_and_honeypot_drops_bots(client, signup):
    headers, _ = signup()
    slug = _slug(client, headers)
    assert client.post(f"/api/p/{slug}/quote", json={"name": "A", "message": "hi"}).status_code == 422
    assert client.post(f"/api/p/{slug}/quote", json={**QUOTE, "website": "spam.example"}).status_code == 202
    assert client.get("/api/inbox", headers=headers).json() == []


def test_quote_endpoint_rate_limited(client, signup):
    headers, _ = signup()
    slug = _slug(client, headers)
    codes = [client.post(f"/api/p/{slug}/quote", json=QUOTE).status_code for _ in range(6)]
    assert codes == [202] * 5 + [429]


def test_job_sheet_crud_and_isolation(client, signup):
    owner, _ = signup()
    other, _ = signup("Someone Else", trade="painter")
    res = client.post("/api/jobs", headers=owner, json={"title": "Panel swap", "customer_name": "Dana", "estimate_cents": 185000, "scheduled_on": "2026-11-02"})
    assert res.status_code == 201
    job_id = res.json()["id"]
    assert "owner_id" not in res.json()

    assert client.get(f"/api/jobs/{job_id}", headers=other).status_code == 404
    assert client.patch(f"/api/jobs/{job_id}", headers=other, json={"status": "done"}).status_code == 404
    assert client.delete(f"/api/jobs/{job_id}", headers=other).status_code == 404
    assert client.get("/api/jobs", headers=other).json() == []

    updated = client.patch(f"/api/jobs/{job_id}", headers=owner, json={"status": "scheduled"}).json()
    assert updated["status"] == "scheduled" and updated["title"] == "Panel swap"
    assert client.delete(f"/api/jobs/{job_id}", headers=owner).status_code == 204
    assert client.get("/api/jobs", headers=owner).json() == []


def test_sensitive_routes_are_audited(client, signup, db):
    headers, user = signup()
    job_id = client.post("/api/jobs", headers=headers, json={"title": "Audit me"}).json()["id"]
    client.get("/api/inbox", headers=headers)
    client.get("/api/jobs", headers=headers)  # plain read of own data: not audited
    client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope"})

    entries = client.portal.call(lambda: db.audit_log.find({}).sort("timestamp", 1).to_list(100))
    actions = [(e["action"], e["user_id"], e["record_id"], e["status"]) for e in entries]
    assert actions == [
        ("POST /api/auth/signup", user["id"], user["id"], 201),
        ("POST /api/jobs", user["id"], job_id, 201),
        ("GET /api/inbox", user["id"], None, 200),
        ("POST /api/auth/login", None, None, 401),
    ]
    assert all(e["timestamp"] for e in entries)


def test_meta_lists_trades_and_sections(client):
    meta = client.get("/api/meta").json()
    assert "electrician" in meta["trades"]
    assert meta["sections"][0] == "about"
