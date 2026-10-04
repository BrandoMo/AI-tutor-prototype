"""
Test setup: stub out Upstash Redis and Gemini so tests run offline
with no API keys. Must run before any app module is imported.
"""

import os
import sys
import types

import pytest

os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("UPSTASH_REDIS_URL", "test")
os.environ.setdefault("UPSTASH_REDIS_TOKEN", "test")


class FakeRedis:
    """In-memory stand-in for the parts of upstash_redis.Redis the app uses."""

    def __init__(self, **kwargs):
        self.store = {}
        self.ttls = {}  # recorded, not enforced

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, nx=None, ex=None, **kwargs):
        if nx and key in self.store:
            return False
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def delete(self, *keys):
        removed = sum(1 for k in keys if self.store.pop(k, None) is not None)
        for k in keys:
            self.ttls.pop(k, None)
        return removed

    def incr(self, key):
        self.store[key] = str(int(self.store.get(key, 0)) + 1)
        return int(self.store[key])

    def expire(self, key, seconds, **kwargs):
        self.ttls[key] = seconds
        return key in self.store


sys.modules["upstash_redis"] = types.SimpleNamespace(Redis=FakeRedis)

google = types.ModuleType("google")
google.genai = types.SimpleNamespace(Client=lambda **kwargs: None)
sys.modules["google"] = google
sys.modules["google.genai"] = google.genai


@pytest.fixture(autouse=True)
def clear_redis():
    from app import db
    db.redis.store.clear()
    db.redis.ttls.clear()


@pytest.fixture
def make_client():
    """Returns a function that makes a TestClient signed in as a new student."""
    from fastapi.testclient import TestClient
    import app.main as main

    def make(username="sam", password="correct horse"):
        c = TestClient(main.app)
        r = c.post("/register", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        return c

    return make


@pytest.fixture
def client(make_client):
    """A TestClient signed in as the student "sam"."""
    return make_client()
