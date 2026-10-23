import os
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from app.config import Settings
from app.main import create_app

TODAY = date(2026, 10, 23)


@pytest.fixture
def settings(tmp_path):
    return Settings(jwt_secret="t" * 40, media_dir=str(tmp_path / "media"))


@pytest.fixture
def db():
    """In-memory mock by default. Set TC_TEST_MONGO_URL to run against a real, disposable MongoDB."""
    url = os.environ.get("TC_TEST_MONGO_URL")
    if not url:
        yield AsyncMongoMockClient()["trade_circle_test"]
        return
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo import MongoClient

    name = f"trade_circle_test_{uuid.uuid4().hex[:8]}"
    yield AsyncIOMotorClient(url, tz_aware=True)[name]
    with MongoClient(url) as cleanup:
        cleanup.drop_database(name)


@pytest.fixture
def client(settings, db):
    app = create_app(settings, db=db, today=lambda: TODAY)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def signup(client):
    counter = iter(range(1000))

    def _signup(business_name="Bright Spark Electric", trade="electrician", city="Austin", email=None):
        n = next(counter)
        res = client.post(
            "/api/auth/signup",
            json={
                "email": email or f"pro{n}@example.com",
                "password": "correct horse battery",
                "business_name": business_name,
                "trade": trade,
                "city": city,
            },
        )
        assert res.status_code == 201, res.text
        token = res.json()["token"]
        return {"Authorization": f"Bearer {token}"}, res.json()["user"]

    return _signup
