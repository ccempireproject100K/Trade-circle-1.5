"""Pay and billing-rate comparisons: private submissions, aggregated historical figures only."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.rates import MIN_CONTRIBUTORS

from conftest import TODAY

OLD = "2026-06-01"  # older than the 90-day cutoff from TODAY


@pytest.fixture
def published(settings, db):
    app = create_app(replace(settings, rate_comparisons=True), db=db, today=lambda: TODAY)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def _member(c, n):
    res = c.post("/api/auth/signup", json={"email": f"r{n}@example.com", "password": "correct horse battery", "business_name": f"Shop {n}", "trade": "electrician", "city": "Austin"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


WAGE = {"kind": "wage", "trade": "electrician", "location": "78701", "role": "journeyman", "base_hourly": 30, "benefits": ["health"]}


def _age(c, db):
    c.portal.call(db.rate_submissions.update_many, {}, {"$set": {"submitted_on": OLD}})


def test_submission_is_private_and_keeps_only_the_state(client, signup):
    h, _ = signup()
    other, _ = signup()
    res = client.put("/api/rates/mine", json=WAGE, headers=h)
    assert res.status_code == 200, res.text
    saved = res.json()
    assert saved["state"] == "TX" and "location" not in saved and "contributor_id" not in saved
    assert client.get("/api/rates/mine", headers=other).json() == []
    assert client.delete(f"/api/rates/mine/{saved['id']}", headers=other).status_code == 404
    # A second submission for the same group replaces the first, so each member counts once.
    client.put("/api/rates/mine", json={**WAGE, "base_hourly": 32}, headers=h)
    mine = client.get("/api/rates/mine", headers=h).json()
    assert len(mine) == 1 and mine[0]["base_hourly"] == 32
    assert client.delete(f"/api/rates/mine/{saved['id']}", headers=h).status_code == 204


def test_wage_and_billing_fields_dont_mix(client, signup):
    h, _ = signup()
    assert client.put("/api/rates/mine", json={**WAGE, "labor_hourly": 90}, headers=h).status_code == 422
    assert client.put("/api/rates/mine", json={"kind": "billing", "trade": "electrician", "location": "78701", "pricing": "hourly"}, headers=h).status_code == 422
    ok = client.put("/api/rates/mine", json={"kind": "billing", "trade": "electrician", "location": "78701", "pricing": "project", "service_call_minimum": 95}, headers=h)
    assert ok.status_code == 200, ok.text


def test_nothing_published_until_review(client, signup):
    h, _ = signup()
    body = client.get("/api/rates/compare?kind=wage&trade=electrician&state=TX", headers=h).json()
    assert body["published"] is False and "metrics" not in body


def test_small_groups_and_recent_submissions_are_suppressed(published, db):
    heads = [_member(published, n) for n in range(MIN_CONTRIBUTORS)]
    for i, h in enumerate(heads[:-1]):
        published.put("/api/rates/mine", json={**WAGE, "base_hourly": 25 + i}, headers=h)
    _age(published, db)
    url = "/api/rates/compare?kind=wage&trade=electrician&state=TX"
    assert published.get(url, headers=heads[0]).json()["insufficient_data"] is True
    # The fifth submission is current, so it doesn't count yet.
    published.put("/api/rates/mine", json={**WAGE, "base_hourly": 60}, headers=heads[-1])
    assert published.get(url, headers=heads[0]).json()["insufficient_data"] is True
    _age(published, db)
    body = published.get(url, headers=heads[0]).json()
    assert body["insufficient_data"] is False and body["sample_size"] == MIN_CONTRIBUTORS
    assert body["metrics"]["base_hourly"]["median"] == 27
    assert "overtime_hourly" not in body["metrics"]  # nobody gave it
    assert body["area"] == "TX (statewide)" and "Self-reported" in body["source"]
    assert body["oldest_month"] == "2026-06" and body["benefits"]["health"] == 100
    # No individual figures or contributor identities anywhere in the response.
    assert "rows" not in body and "contributor_id" not in str(body)


def test_other_states_and_trades_are_separate(published, db):
    heads = [_member(published, n) for n in range(MIN_CONTRIBUTORS)]
    for h in heads:
        published.put("/api/rates/mine", json={**WAGE, "location": "10001"}, headers=h)
    _age(published, db)
    assert published.get("/api/rates/compare?kind=wage&trade=electrician&state=TX", headers=heads[0]).json()["insufficient_data"] is True
    assert published.get("/api/rates/compare?kind=wage&trade=plumber&state=NY", headers=heads[0]).json()["insufficient_data"] is True
    assert published.get("/api/rates/compare?kind=wage&trade=electrician&state=NY", headers=heads[0]).json()["insufficient_data"] is False
