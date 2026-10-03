"""
Student state management, backed by Upstash Redis.

Kept isolated in this module so main.py never needs to know HOW state
is stored -- only that get_state() and update_state() exist.
"""

import os
import copy
import json
from dotenv import load_dotenv
from upstash_redis import Redis

load_dotenv()

redis = Redis(
    url=os.environ["UPSTASH_REDIS_URL"],
    token=os.environ["UPSTASH_REDIS_TOKEN"]
)

DEFAULT_STATE = {
    "current_concept": None,
    "attempts": []  # list of {"concept": ..., "correct": bool, "error_type": str|None}
}


def get_state(student_id: str) -> dict:
    """Return this student's current state, or a fresh default."""
    raw = redis.get(f"student:{student_id}")
    if raw is None:
        return copy.deepcopy(DEFAULT_STATE)
    return json.loads(raw)


def update_state(student_id: str, **changes) -> dict:
    """Merge changes into the student's state and save."""
    state = get_state(student_id)
    state.update(changes)
    redis.set(f"student:{student_id}", json.dumps(state))
    return state


def log_attempt(student_id: str, concept: str, correct: bool, error_type: str = None):
    """Append an attempt record, keeping only the last 5 for prompt context."""
    state = get_state(student_id)
    state["attempts"].append({
        "concept": concept,
        "correct": correct,
        "error_type": error_type
    })
    state["attempts"] = state["attempts"][-5:]
    redis.set(f"student:{student_id}", json.dumps(state))
    return state
