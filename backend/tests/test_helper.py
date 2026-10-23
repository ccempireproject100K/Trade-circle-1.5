"""Contractor AI helper and part lookup: allowances, shared budget, failures, concurrency."""
import asyncio
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import ai
from app.main import create_app

from conftest import TODAY


class FakeProvider:
    def __init__(self):
        self.calls = 0
        self.fail = None  # an exception to raise instead of answering

    async def answer(self, model, max_tokens, history, question):
        self.calls += 1
        if self.fail:
            raise self.fail
        return f"answer to {question}", ai.Usage(1000, 500)

    async def read_part(self, model, max_tokens, jpeg, note):
        self.calls += 1
        return '{"label_text": ["CAT 1234-56"], "matches": [{"description": "capacitor", "brand": "Acme", "model_or_part": "1234-56", "basis": "read_from_label"}, {"description": "maybe a run capacitor", "brand": "", "model_or_part": "", "basis": "visual_guess"}], "need_more": ""}', ai.Usage(3000, 200)


CONFIGURED = dict(ai_api_key="k", ai_model="test-model", ai_input_price=4.0, ai_output_price=20.0, ai_monthly_budget=5.0)


def _app(settings, db, day=TODAY, **overrides):
    app = create_app(replace(settings, **overrides), db=db, today=lambda: day)
    app.state.ai_provider = FakeProvider()
    return app


@pytest.fixture
def configured(settings, db):
    app = _app(settings, db, **CONFIGURED)
    with TestClient(app, base_url="https://testserver") as c:
        yield c, app


def _member(c, n=0):
    res = c.post("/api/auth/signup", json={"email": f"h{n}@example.com", "password": "correct horse battery", "business_name": f"Shop {n}", "trade": "electrician", "city": "Austin"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_off_until_model_prices_and_budget_are_set(client, signup, app_state=None):
    h, _ = signup()
    status_ = client.get("/api/helper", headers=h).json()
    assert status_["available"] is False and status_["notice"] == "Community AI is temporarily unavailable."
    res = client.post("/api/helper/ask", json={"question": "What wire size?"}, headers=h)
    assert res.status_code == 503 and res.json()["detail"]["who"] == "community"
    # The notice names no reset time when none is known.
    assert "try again" not in res.json()["detail"]["message"]


def test_daily_and_monthly_allowances(configured, db):
    c, app = configured
    h = _member(c)
    for i in range(3):
        res = c.post("/api/helper/ask", json={"question": f"Question {i}?"}, headers=h)
        assert res.status_code == 200, res.text
    assert res.json()["status"]["remaining_today"] == 0
    assert res.json()["status"]["remaining_this_month"] == 7
    out = c.post("/api/helper/ask", json={"question": "One more?"}, headers=h)
    assert out.status_code == 429
    assert out.json()["detail"] == {"message": "Your free AI questions refresh on October 24.", "who": "member"}
    assert c.get("/api/helper", headers=h).json()["timezone"] == "America/Chicago"
    # Another member is unaffected: the cap is personal, not a community limit.
    other = _member(c, 1)
    assert c.post("/api/helper/ask", json={"question": "Mine?"}, headers=other).status_code == 200


def test_monthly_cap_names_the_first_of_next_month(settings, db):
    app = _app(settings, db, **CONFIGURED, ai_daily_limit=20, ai_monthly_limit=2)
    with TestClient(app, base_url="https://testserver") as c:
        h = _member(c)
        for _ in range(2):
            assert c.post("/api/helper/ask", json={"question": "Okay?"}, headers=h).status_code == 200
        out = c.post("/api/helper/ask", json={"question": "Okay?"}, headers=h)
        assert out.json()["detail"]["message"] == "Your free AI questions refresh on November 1."
        assert c.get("/api/helper", headers=h).json()["refreshes_on"] == "2026-11-01"


def test_failed_requests_dont_use_the_allowance_but_reported_cost_counts(configured, db):
    c, app = configured
    h = _member(c)
    app.state.ai_provider.fail = ai.ProviderFailed("declined", usage=ai.Usage(100, 50))
    res = c.post("/api/helper/ask", json={"question": "Will this fail?"}, headers=h)
    assert res.status_code == 502 and "didn't use one of your questions" in res.json()["detail"]["message"]
    assert c.get("/api/helper", headers=h).json()["remaining_today"] == 3
    budget = c.portal.call(db.ai_budget.find_one, {"_id": "helper:2026-10"})
    assert budget["spent"] == 100 * 4 + 50 * 20 and budget["committed"] == budget["spent"]
    # A timeout may have been charged, so its whole reservation stays counted.
    app.state.ai_provider.fail = ai.ProviderFailed("timed out", unknown_cost=True)
    c.post("/api/helper/ask", json={"question": "Will this fail?"}, headers=h)
    after = c.portal.call(db.ai_budget.find_one, {"_id": "helper:2026-10"})
    assert after["spent"] > budget["spent"] and after["committed"] == after["spent"]
    assert c.get("/api/helper", headers=h).json()["remaining_today"] == 3
    usage = c.portal.call(lambda: db.ai_usage.find({}).to_list(10))
    assert all("question" not in u for u in usage)


def test_shared_budget_stops_new_requests(settings, db):
    # One request reserves (2500 + ~15 chars)/2 input tokens * $4 + 2000 output * $20 ≈ $0.045 at most.
    app = _app(settings, db, **{**CONFIGURED, "ai_monthly_budget": 0.05})
    with TestClient(app, base_url="https://testserver") as c:
        h = _member(c)
        assert c.post("/api/helper/ask", json={"question": "First?"}, headers=h).status_code == 200
        out = c.post("/api/helper/ask", json={"question": "Second?"}, headers=h)
        assert out.status_code == 503
        assert out.json()["detail"] == {"message": "Community AI is temporarily unavailable. Please try again November 1.", "who": "community"}
        # The member's slot was given back.
        assert c.get("/api/helper", headers=h).json()["remaining_today"] == 2
        assert app.state.ai_provider.calls == 1


def test_simultaneous_requests_cannot_exceed_the_allowance(configured, db):
    c, app = configured
    feature = ai.Feature("helper", "m", 4.0, 20.0, 5.0, 3, 10, 100)
    started = []

    async def call():
        started.append(1)
        await asyncio.sleep(0.01)
        return "ok", ai.Usage(10, 10)

    async def burst():
        return await asyncio.gather(*[ai.run(db, feature, "u1", TODAY, 10, call) for _ in range(8)], return_exceptions=True)

    results = c.portal.call(burst)
    assert sum(r == "ok" for r in results) == 3
    assert sum(isinstance(r, ai.Refused) for r in results) == 5 and len(started) == 3


def test_history_and_input_are_bounded(configured):
    c, _ = configured
    h = _member(c)
    assert c.post("/api/helper/ask", json={"question": "x" * 2001}, headers=h).status_code == 422
    turns = [{"role": "user", "content": "a"}] * 7
    assert c.post("/api/helper/ask", json={"question": "Okay?", "history": turns}, headers=h).status_code == 422


def test_part_search_separates_exact_model_matches(client, signup):
    h, _ = signup()
    post = {"kind": "equipment", "title": "Condenser fan motor", "fields": {"product": "Fan motor", "model": "ABC-123", "affiliation": "none"}}
    client.post("/api/posts", json=post, headers=h)
    client.post("/api/posts", json={**post, "title": "Replaced my ABC-1234", "fields": {**post["fields"], "model": "ABC-1234"}}, headers=h)
    res = client.get("/api/parts/search?q=abc 123", headers=h).json()
    assert len(res["exact"]) == 0 and res["query"] == "abc 123"
    res = client.get("/api/parts/search?q=ABC-123", headers=h).json()
    assert [p["fields"]["model"] for p in res["exact"]] == ["ABC-123"]
    assert [p["fields"]["model"] for p in res["mentions"]] == ["ABC-1234"]
    assert "aren't confirmed" in res["note"] and "ABC-123" in res["inquiry"]


def test_photo_lookup_is_off_without_its_own_budget(configured):
    c, app = configured
    h = _member(c)
    res = c.post("/api/parts/photo", files={"file": ("p.jpg", b"x", "image/jpeg")}, headers=h)
    assert res.status_code == 503 and "Type the model or part number" in res.json()["detail"]["message"]
    assert app.state.ai_provider.calls == 0


def test_photo_lookup_marks_visual_guesses(settings, db):
    import io

    from PIL import Image

    app = _app(settings, db, **CONFIGURED, parts_monthly_budget=2.0, parts_daily_limit=2, parts_monthly_limit=5)
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, "JPEG")
    with TestClient(app, base_url="https://testserver") as c:
        h = _member(c)
        res = c.post("/api/parts/photo", files={"file": ("p.jpg", buf.getvalue(), "image/jpeg")}, headers=h)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["exact"][0]["model_or_part"] == "1234-56" and body["possible"][0]["basis"] == "visual_guess"
        assert body["status"]["remaining_today"] == 1
        # The helper's allowance is separate.
        assert c.get("/api/helper", headers=h).json()["remaining_today"] == 3


def test_reset_dates_cross_the_year():
    assert ai.next_month(date(2026, 12, 31)) == date(2027, 1, 1)
    assert ai.next_day(date(2026, 12, 31)) == date(2027, 1, 1)
