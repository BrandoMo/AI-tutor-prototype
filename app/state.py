"""
Student state management, backed by Upstash Redis.

Kept isolated in this module so main.py never needs to know HOW state
is stored -- only that get_state() and log_attempt() exist.
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
    # list of {"concept", "problem_id", "problem", "answer", "correct", "error_type"}
    "attempts": []
}


def get_state(student_id: str) -> dict:
    """Return this student's current state, or a fresh default."""
    raw = redis.get(f"student:{student_id}")
    if raw is None:
        return copy.deepcopy(DEFAULT_STATE)
    return json.loads(raw)


def log_attempt(student_id: str, concept: str, correct: bool,
                error_type: str = None, answer: str = None,
                problem_id: str = None, problem: str = None):
    """Append an attempt record, keeping only the last 5 for prompt context."""
    state = get_state(student_id)
    state["attempts"].append({
        "concept": concept,
        "problem_id": problem_id,
        "problem": problem,
        "correct": correct,
        "error_type": error_type,
        "answer": answer
    })
    state["attempts"] = state["attempts"][-5:]
    redis.set(f"student:{student_id}", json.dumps(state))
    return state
