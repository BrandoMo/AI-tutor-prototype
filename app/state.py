"""
Student state management, backed by Upstash Redis.

Kept isolated in this module so main.py never needs to know HOW state
is stored -- only that get_state(), add_attempt() and save_state() exist.
A student's id is their username (see auth.py).
"""

import copy
import json

from app.db import redis

DEFAULT_STATE = {
    "current_concept": None,
    # Last 5 graded attempts, as context for the tutor:
    # {"concept", "problem_id", "problem", "try", "answer", "correct", "misconception", "error_type"}
    "attempts": [],
    # Running totals per concept -- see progress.py
    "progress": {},
}


def get_state(student_id: str) -> dict:
    """Return this student's current state, or a fresh default."""
    raw = redis.get(f"student:{student_id}")
    if raw is None:
        return copy.deepcopy(DEFAULT_STATE)
    state = json.loads(raw)
    state.setdefault("progress", {})  # saved before progress existed
    return state


def add_attempt(state: dict, record: dict) -> None:
    """Append an attempt record, keeping only the last 5 for prompt context."""
    state["attempts"].append(record)
    state["attempts"] = state["attempts"][-5:]


def save_state(student_id: str, state: dict) -> None:
    redis.set(f"student:{student_id}", json.dumps(state))
