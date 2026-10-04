"""
Shared Upstash Redis client.

Every module that stores data imports `redis` from here, so there's one
connection and one place to change if the store ever changes.
"""

import os
from dotenv import load_dotenv
from upstash_redis import Redis

load_dotenv()

redis = Redis(
    url=os.environ["UPSTASH_REDIS_URL"],
    token=os.environ["UPSTASH_REDIS_TOKEN"]
)
