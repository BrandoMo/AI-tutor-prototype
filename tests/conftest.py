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
    def __init__(self, **kwargs):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value


sys.modules["upstash_redis"] = types.SimpleNamespace(Redis=FakeRedis)

google = types.ModuleType("google")
google.genai = types.SimpleNamespace(Client=lambda **kwargs: None)
sys.modules["google"] = google
sys.modules["google.genai"] = google.genai


@pytest.fixture(autouse=True)
def clear_redis():
    from app import state
    state.redis.store.clear()
