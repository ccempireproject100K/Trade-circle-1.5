import io

from PIL import Image

from app import suppliers as rules

SOURCE = [{"url": "https://www.example-lumber.com/", "method": "Official website read directly", "checked_on": "2026-10-20"}]


def admin(client, signup, db):
    headers, user = signup("Trade Circle Staff", email="staff@example.com")
    client.portal.call(db.users.update_one, {"_id": user["id"]}, {"$set": {"role": "admin"}})
    return headers


def add(client, headers, name, place=None, **extra):
    body = {"name": name, "categories": ["lumber_building_materials"], "sources": SOURCE, **extra}
    if place:
        body["locations"] = [{"place": place, "address": "100 Main St"}]
    res = client.post("/api/admin/suppliers", headers=headers, json=body)
    assert res.status_code == 201, res.text
    return res.json()


def seeded(client, signup, db):
    staff = admin(client, signup, db)
    assert client.post("/api/admin/suppliers/seed", headers=staff).json() == {"added": 5}
    assert client.post("/api/admin/suppliers/seed", headers=staff).json() == {"added": 0}
    return staff


# --- starter listings and wording ---


def test_starter_listings_get_no_preferred_placement(client, signup, db):
    staff = seeded(client, signup, db)
    add(client, staff, "Aaron's Lumber", place="Austin, TX")
    add(client, staff, "Zeta Lumber Yard", place="Austin, TX")
    names = [s["name"] for s in client.get("/api/suppliers", headers=staff).json()["suppliers"]]
    assert names == sorted(names, key=str.lower)  # plain alphabetical; starters mixed in with everyone
    assert names[0] == "Aaron's Lumber" and names[-1] == "Zeta Lumber Yard"


def test_verification_wording_states_what_was_checked(client, signup, db):
    staff = seeded(client, signup, db)
    for s in client.get("/api/suppliers", headers=staff).json()["suppliers"]:
        text = " ".join(s["verification"]).lower()
        assert "checked oct 23, 2026" in text and "not checked" in text
        assert "verified" not in text and "trusted" not in text
        assert s["added_by"] == "Trade Circle"
    graybar = next(s for s in client.get("/api/suppliers", headers=staff, params={"q": "graybar"}).json()["suppliers"])
    assert "blocked direct reading" in graybar["verification"][0]
    assert graybar["business_account"] == "unknown"


def test_listings_require_sources(client, signup, db):
    staff = admin(client, signup, db)
    res = client.post("/api/admin/suppliers", headers=staff, json={"name": "No Source Co", "categories": ["electrical"], "sources": []})
    assert res.status_code == 422


# --- filters ---


def test_location_category_and_ships_to_filters(client, signup, db):
    staff = seeded(client, signup, db)
    add(client, staff, "Round Rock Lumber", place="Round Rock, TX")  # ~15 mi from downtown Austin
    add(client, staff, "Dallas Lumber", place="75201")  # ~180 mi
    add(client, staff, "Texas Ships Lumber", ships_to=["TX"])
    add(client, staff, "Nationwide Fasteners", categories=["fasteners_hardware"], ships_to="nationwide")

    res = client.get("/api/suppliers", headers=staff, params={"near": "78701", "radius": 25, "category": "lumber_building_materials"}).json()
    assert res["near"]["state"] == "TX"
    by_name = {s["name"]: s for s in res["suppliers"]}
    assert "Round Rock Lumber" in by_name and "Dallas Lumber" not in by_name
    assert by_name["Round Rock Lumber"]["match"][0].endswith("mi away")
    assert by_name["Texas Ships Lumber"]["match"] == ["Ships to TX"]
    # Closest first when a place is given.
    assert res["suppliers"][0]["name"] == "Round Rock Lumber"

    ships = client.get("/api/suppliers", headers=staff, params={"near": "78701", "ships_here": True}).json()["suppliers"]
    assert {s["name"] for s in ships} == {"Texas Ships Lumber", "Nationwide Fasteners"}
    new_york = client.get("/api/suppliers", headers=staff, params={"near": "10001", "ships_here": True}).json()["suppliers"]
    assert {s["name"] for s in new_york} == {"Nationwide Fasteners"}

    roofing = client.get("/api/suppliers", headers=staff, params={"category": "roofing"}).json()["suppliers"]
    assert [s["name"] for s in roofing] == ["ABC Supply Co., Inc."]
    # Multi-branch chains show up anywhere, with an honest note instead of a distance.
    abc = client.get("/api/suppliers", headers=staff, params={"near": "59901", "category": "roofing"}).json()["suppliers"][0]
    assert "check their store finder" in abc["match"][0] and abc["nearest_miles"] is None


# --- member suggestions and experiences ---


def test_suggestion_becomes_listing_and_keeps_its_thread(client, signup, db):
    member, _ = signup()
    staff = admin(client, signup, db)
    suggestion = client.post(
        "/api/posts",
        headers=member,
        json={"kind": "supplier_suggestion", "title": "Please add Hill Country Lumber", "location": "Austin, TX", "fields": {"suggested_name": "Hill Country Lumber"}},
    ).json()
    listing = add(client, staff, "Hill Country Lumber", place="Austin, TX", from_suggestion=suggestion["id"])
    assert listing["added_by"] == "member suggestion"
    detail = client.get(f"/api/posts/{suggestion['id']}", headers=member).json()
    assert detail["supplier"] == {"id": listing["id"], "name": "Hill Country Lumber"}


def test_experiences_are_kept_apart_from_facts(client, signup, db):
    staff = seeded(client, signup, db)
    member, _ = signup()
    abc = client.get("/api/suppliers", headers=staff, params={"q": "ABC"}).json()["suppliers"][0]
    review = {"kind": "supplier_review", "title": "Fast delivery", "body": "Shingles on site next morning.", "supplier_id": abc["id"], "fields": {"experience": "positive", "topics": ["delivery"]}}
    assert client.post("/api/posts", headers=member, json=review).status_code == 201
    bad = {**review, "title": "Returns were a pain", "fields": {"experience": "negative", "topics": ["returns"]}}
    assert client.post("/api/posts", headers=member, json=bad).status_code == 201
    assert client.post("/api/posts", headers=member, json={**review, "supplier_id": None}).status_code == 422
    assert client.post("/api/posts", headers=member, json={**review, "fields": {}}).status_code == 422

    detail = client.get(f"/api/suppliers/{abc['id']}", headers=member).json()
    assert detail["experiences"] == {"positive": 1, "mixed": 0, "negative": 1, "posts": 2}
    assert {p["title"] for p in detail["member_posts"]} == {"Fast delivery", "Returns were a pain"}
    assert "Shingles" not in detail["offers"]  # opinions never written into the facts


# --- removal at the business's request ---


def _review_with_photo(client, member, supplier):
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (200, 0, 0)).save(buf, "JPEG")
    pic = client.post("/api/media/photos", headers=member, files={"file": ("sign.jpg", buf.getvalue(), "image/jpeg")}).json()
    return client.post(
        "/api/posts",
        headers=member,
        json={
            "kind": "supplier_review",
            "title": "Hill Country Lumber has great framing lumber",
            "body": "Ask for Hill Country Lumber's contractor desk, or order at hillcountrylumber.com.",
            "supplier_id": supplier["id"],
            "photos": [{"id": pic["id"]}],
            "fields": {"experience": "positive", "topics": ["quality"]},
        },
    ).json()


def test_removal_requires_confirmed_authorization_and_anonymizes(client, signup, db):
    staff = admin(client, signup, db)
    member, _ = signup()
    other, _ = signup("Other Co", trade="painter")
    supplier = add(client, staff, "Hill Country Lumber", place="Austin, TX", website="https://www.hillcountrylumber.com")
    review = _review_with_photo(client, member, supplier)
    client.post(f"/api/posts/{review['id']}/comments", headers=other, json={"body": "Hill Country Lumber's yard on Main St is the one."})
    unrelated = client.post("/api/posts", headers=other, json={"kind": "supply_question", "title": "Anyone used hillcountrylumber.com?", "location": "78701"}).json()

    client.cookies.clear()
    req = client.post(
        f"/api/suppliers/{supplier['id']}/removal-requests",
        json={"requester_name": "Pat Owner", "requester_role": "Owner", "email": "pat@hillcountrylumber.com"},
    )
    assert req.status_code == 201 and "confirm you represent this business" in req.json()["message"]
    pending = client.get("/api/admin/removal-requests", headers=staff).json()[0]
    assert pending["email_matches_website"] is True
    # Nothing is removed until a moderator records how they confirmed it.
    assert client.get(f"/api/suppliers/{supplier['id']}", headers=member).status_code == 200
    no_check = client.post(f"/api/admin/removal-requests/{pending['id']}/decide", headers=staff, json={"decision": "approve"})
    assert no_check.status_code == 422

    done = client.post(
        f"/api/admin/removal-requests/{pending['id']}/decide",
        headers=staff,
        json={"decision": "approve", "authorization_check": "Emailed pat@ at the domain on their website; Pat replied confirming.", "aliases": ["HCL"]},
    ).json()
    assert done["status"] == "completed" and done["posts_anonymized"] == 2 and done["comments_anonymized"] == 1

    # The listing and its public details are gone.
    assert client.get(f"/api/suppliers/{supplier['id']}", headers=member).status_code == 404
    assert all(s["name"] != "Hill Country Lumber" for s in client.get("/api/suppliers", headers=member).json()["suppliers"])
    stored = client.portal.call(db.suppliers.find_one, {"_id": supplier["id"]})
    assert stored["status"] == "removed" and stored["name"] is None and "website" not in stored and "locations" not in stored

    # The review stays, without identifying details.
    kept = client.get(f"/api/posts/{review['id']}", headers=other).json()
    assert kept["supplier"] == {"removed": True, "name": "Supplier details removed"}
    assert kept["title"] == "[supplier] has great framing lumber"
    assert "hillcountrylumber" not in kept["body"].lower() and "Hill Country" not in kept["body"]
    assert kept["photos"] == [] and kept["photos_hidden"] is True
    assert kept["fields"]["experience"] == "positive"
    assert kept["comments"][0]["body"] == "[supplier]'s yard on [supplier] is the one."
    assert "[supplier]" in client.get(f"/api/posts/{unrelated['id']}", headers=other).json()["title"]

    # Every changed post and reply waits for a moderator to double-check.
    flags = [r for r in client.get("/api/admin/reports", headers=staff).json() if r["reason"] == "anonymization_review"]
    assert len(flags) == 3 and all(f["from_system"] for f in flags)


def test_removal_can_be_rejected(client, signup, db):
    staff = admin(client, signup, db)
    supplier = add(client, staff, "Hill Country Lumber", place="Austin, TX")
    client.cookies.clear()
    client.post(f"/api/suppliers/{supplier['id']}/removal-requests", json={"requester_name": "Someone", "requester_role": "Competitor", "email": "x@gmail.com"})
    pending = client.get("/api/admin/removal-requests", headers=staff).json()[0]
    assert pending["email_matches_website"] is False
    client.post(f"/api/admin/removal-requests/{pending['id']}/decide", headers=staff, json={"decision": "reject", "note": "Could not confirm."})
    assert client.get(f"/api/suppliers/{supplier['id']}", headers=staff).status_code == 200


def test_identifiers_cover_name_site_and_aliases():
    names = rules.identifiers({"name": "Hill Country Lumber", "website": "https://www.hillcountrylumber.com", "locations": [{"address": "100 Main St"}]}, ["HCL"])
    assert names[0] == "hillcountrylumber.com"
    assert set(names) == {"Hill Country Lumber", "hillcountrylumber.com", "hillcountrylumber", "100 Main St", "Main St", "HCL"}
