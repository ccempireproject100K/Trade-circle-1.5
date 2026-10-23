"""Optional company accounts: invitations, explicit permissions, no self-escalation, immediate revocation."""


def _as(headers, business_id):
    return {**headers, "X-TC-Business": business_id}


def test_solo_member_needs_no_setup(client, signup):
    h, _ = signup()
    assert client.get("/api/me/portfolio", headers=h).status_code == 200
    assert client.get("/api/team/memberships", headers=h).json() == {"invitations": [], "businesses": [], "has_team": False}


def test_invitation_must_be_accepted_and_grants_only_given_permissions(client, signup):
    owner_h, owner = signup("Owner Electric")
    worker_h, worker = signup("Worker Name", email="worker@example.com")
    business = owner["id"]
    # Before anything, the worker can't touch the owner's records.
    assert client.get("/api/me/portfolio", headers=_as(worker_h, business)).status_code == 403
    res = client.post(f"/api/team/{business}/invite", json={"email": "worker@example.com", "role": "contributor", "permissions": ["portfolio"]}, headers=owner_h)
    assert res.status_code == 201, res.text
    # An invitation is not access.
    assert client.get("/api/me/portfolio", headers=_as(worker_h, business)).status_code == 403
    assert client.post(f"/api/team/invitations/{business}/accept", headers=worker_h).json() == {"status": "active"}
    assert client.get("/api/me/portfolio", headers=_as(worker_h, business)).status_code == 200
    # Only the permissions given: no follow-ups (customer details), jobs or profile.
    assert client.get("/api/inbox", headers=_as(worker_h, business)).status_code == 403
    assert client.get("/api/jobs", headers=_as(worker_h, business)).status_code == 403
    assert client.put("/api/me/profile", json={"tagline": "x"}, headers=_as(worker_h, business)).status_code == 403
    # Owner-only areas ignore the header entirely: alerts and settings are the worker's own.
    assert client.get("/api/me/alerts", headers=_as(worker_h, business)).json()["email"] == "worker@example.com"


def test_work_done_for_the_business_lands_on_the_business_and_is_audited(client, signup, db):
    owner_h, owner = signup("Owner Electric")
    worker_h, worker = signup("Worker", email="w@example.com")
    business = owner["id"]
    client.post(f"/api/team/{business}/invite", json={"email": "w@example.com", "role": "contributor", "permissions": ["jobs"]}, headers=owner_h)
    client.post(f"/api/team/invitations/{business}/accept", headers=worker_h)
    res = client.post("/api/jobs", json={"title": "Panel swap", "customer_name": "Pat"}, headers=_as(worker_h, business))
    assert res.status_code == 201, res.text
    assert [j["title"] for j in client.get("/api/jobs", headers=owner_h).json()] == ["Panel swap"]
    assert client.get("/api/jobs", headers=worker_h).json() == []
    entry = client.portal.call(db.audit_log.find_one, {"action": "POST /api/jobs"})
    assert entry["user_id"] == worker["id"] and entry["on_behalf_of"] == business


def test_no_self_escalation_and_admin_limits(client, signup):
    owner_h, owner = signup("Owner")
    admin_h, admin = signup("Admin", email="admin@example.com")
    c_h, contrib = signup("Contrib", email="c@example.com")
    business = owner["id"]
    client.post(f"/api/team/{business}/invite", json={"email": "admin@example.com", "role": "admin"}, headers=owner_h)
    client.post(f"/api/team/invitations/{business}/accept", headers=admin_h)
    # Admins invite contributors but not admins.
    assert client.post(f"/api/team/{business}/invite", json={"email": "c@example.com", "role": "admin"}, headers=admin_h).status_code == 403
    assert client.post(f"/api/team/{business}/invite", json={"email": "c@example.com", "role": "contributor", "permissions": ["jobs"]}, headers=admin_h).status_code == 201
    client.post(f"/api/team/invitations/{business}/accept", headers=c_h)
    # Contributors can't manage the team or raise their own access.
    assert client.get(f"/api/team/{business}/members", headers=c_h).status_code == 404
    assert client.patch(f"/api/team/{business}/members/{contrib['id']}", json={"role": "admin"}, headers=c_h).status_code == 404
    # Nobody changes their own access, admins included.
    assert client.patch(f"/api/team/{business}/members/{admin['id']}", json={"role": "contributor"}, headers=admin_h).status_code == 403
    # Admins can't promote others to admin or remove admins.
    assert client.patch(f"/api/team/{business}/members/{contrib['id']}", json={"role": "admin"}, headers=admin_h).status_code == 403
    ok = client.patch(f"/api/team/{business}/members/{contrib['id']}", json={"permissions": ["jobs", "portfolio"]}, headers=admin_h)
    assert ok.status_code == 200 and ok.json()["permissions"] == ["jobs", "portfolio"]
    # The change is recorded.
    log = client.get(f"/api/team/{business}/members", headers=owner_h).json()["log"]
    assert log[0]["action"] == "changed_access" and log[0]["detail"]["before"]["permissions"] == ["jobs"]


def test_removal_stops_the_next_action(client, signup):
    owner_h, owner = signup("Owner")
    w_h, worker = signup("Worker", email="w@example.com")
    business = owner["id"]
    client.post(f"/api/team/{business}/invite", json={"email": "w@example.com", "role": "contributor", "permissions": ["portfolio"]}, headers=owner_h)
    client.post(f"/api/team/invitations/{business}/accept", headers=w_h)
    assert client.get("/api/me/portfolio", headers=_as(w_h, business)).status_code == 200
    assert client.delete(f"/api/team/{business}/members/{worker['id']}", headers=owner_h).status_code == 204
    assert client.get("/api/me/portfolio", headers=_as(w_h, business)).status_code == 403
    # Re-inviting needs a fresh acceptance.
    client.post(f"/api/team/{business}/invite", json={"email": "w@example.com", "role": "contributor", "permissions": ["portfolio"]}, headers=owner_h)
    assert client.get("/api/me/portfolio", headers=_as(w_h, business)).status_code == 403


def test_link_shows_publicly_only_with_the_teammates_consent(client, signup):
    owner_h, owner = signup("Owner Electric")
    w_h, worker = signup("Sam Rivera Electric", email="w@example.com")
    business = owner["id"]
    slug = client.get("/api/me/profile", headers=owner_h).json()["slug"]
    client.post(f"/api/team/{business}/invite", json={"email": "w@example.com", "role": "contributor", "permissions": []}, headers=owner_h)
    client.post(f"/api/team/invitations/{business}/accept", headers=w_h)
    assert client.get(f"/api/p/{slug}/full").json()["team"] == []
    assert client.put(f"/api/team/memberships/{business}/visibility", json={"show_on_profile": True}, headers=w_h).status_code == 200
    assert [t["business_name"] for t in client.get(f"/api/p/{slug}/full").json()["team"]] == ["Sam Rivera Electric"]
    assert "Sam Rivera Electric" in client.get(f"/p/{slug}/full").text
    # The owner can't switch it on for them.
    assert client.put(f"/api/team/memberships/{business}/visibility", json={"show_on_profile": True}, headers=owner_h).status_code == 404


def test_invitee_needs_their_own_account(client, signup):
    owner_h, owner = signup("Owner")
    res = client.post(f"/api/team/{owner['id']}/invite", json={"email": "nobody@example.com", "role": "contributor"}, headers=owner_h)
    assert res.status_code == 404 and "sign up first" in res.json()["detail"]
