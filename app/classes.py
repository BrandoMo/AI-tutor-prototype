"""
Classes: a teacher creates one and gets a join code; students join with it.

  class:<CODE>             -> {"name", "teacher", "created_at"}
  class_students:<CODE>    -> set of student usernames
  teacher_classes:<user>   -> set of that teacher's class codes

Codes look like "K7Q-3MP" (no 0/O or 1/I/L). A student is in at most one
class; joining another moves them. Teachers only ever see their own
classes -- any other code is reported as not found.
"""

import json
import time

from fastapi import HTTPException

from app import auth
from app.db import redis


def format_code(code: str) -> str:
    """Any spacing/case -> canonical "ABC-DEF"."""
    raw = auth.normalize_code(code)
    return f"{raw[:3]}-{raw[3:]}" if len(raw) == 6 else raw


def create_class(teacher: str, name: str) -> dict:
    name = name.strip()
    if not 1 <= len(name) <= 40:
        raise HTTPException(status_code=400, detail="Class names are 1-40 characters.")
    record = {"name": name, "teacher": teacher, "created_at": int(time.time())}
    while True:  # retry on the (very unlikely) chance the code is taken
        code = format_code(auth.random_code(6))
        if redis.set(f"class:{code}", json.dumps(record), nx=True):
            break
    redis.sadd(f"teacher_classes:{teacher}", code)
    return {"code": code, "name": name, "students": 0}


def get_class(code: str) -> dict | None:
    raw = redis.get(f"class:{format_code(code)}")
    return json.loads(raw) if raw else None


def owned_class(teacher: str, code: str) -> tuple[str, dict]:
    """(canonical code, class) if this teacher owns it, else 404."""
    code = format_code(code)
    cls = get_class(code)
    if cls is None or cls["teacher"] != teacher:
        raise HTTPException(status_code=404, detail="Class not found.")
    return code, cls


def students(code: str) -> list[str]:
    return sorted(redis.smembers(f"class_students:{code}") or [])


def list_classes(teacher: str) -> list[dict]:
    result = []
    for code in sorted(redis.smembers(f"teacher_classes:{teacher}") or []):
        cls = get_class(code)
        if cls:
            result.append({"code": code, "name": cls["name"], "students": len(students(code))})
    return sorted(result, key=lambda c: c["name"].lower())


def join_class(username: str, code: str) -> dict:
    code = format_code(code)
    cls = get_class(code)
    if cls is None:
        raise HTTPException(status_code=404, detail="No class has that code. Check it with your teacher.")
    user = auth.get_user(username)
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Teachers can't join classes as students.")
    if user["class"] and user["class"] != code:
        redis.srem(f"class_students:{user['class']}", username)
    redis.sadd(f"class_students:{code}", username)
    user["class"] = code
    auth.save_user(username, user)
    return {"code": code, "name": cls["name"]}


def class_member(code: str, username: str) -> str:
    """Canonical username if they're in this class, else 404."""
    name = auth.normalize_username(username)
    if name is None or not redis.sismember(f"class_students:{code}", name):
        raise HTTPException(status_code=404, detail="That student isn't in this class.")
    return name


def remove_student(code: str, username: str) -> None:
    redis.srem(f"class_students:{code}", username)
    user = auth.get_user(username)
    if user and user["class"] == code:
        user["class"] = None
        auth.save_user(username, user)


def class_report(code: str, concept_facts: dict) -> dict:
    """Per-student progress plus a class-wide summary for one concept."""
    concept = concept_facts["concept"]
    labels = {m["id"]: m.get("label", m["id"]) for m in concept_facts.get("misconceptions", [])}
    names = students(code)

    # Two round trips for the whole class, not two per student
    states = redis.mget(*[f"student:{n}" for n in names]) if names else []
    failures = redis.mget(*[f"login_failures:{n}" for n in names]) if names else []

    rows = []
    mistake_students = {}  # misconception id -> how many students made it
    mistake_totals = {}    # misconception id -> how many times overall
    for name, raw_state, raw_failures in zip(names, states, failures):
        state = json.loads(raw_state) if raw_state else {}
        p = state.get("progress", {}).get(concept, {})
        mistakes = p.get("misconceptions", {})
        for m, count in mistakes.items():
            mistake_students[m] = mistake_students.get(m, 0) + 1
            mistake_totals[m] = mistake_totals.get(m, 0) + count
        top = max(mistakes, key=mistakes.get) if mistakes else None
        rows.append({
            "username": name,
            "solved": p.get("solved", 0),
            "streak": p.get("streak", 0),
            "mastered": p.get("mastered", False),
            "top_mistake": labels.get(top) if top else None,
            "focus": labels.get(p.get("focus")) if p.get("focus") else None,
            "last_active": state.get("last_active"),
            "locked": raw_failures is not None and int(raw_failures) >= auth.MAX_FAILED_LOGINS,
        })

    mistakes = sorted(
        ({"label": labels.get(m, m), "students": mistake_students[m], "times": mistake_totals[m]}
         for m in mistake_students),
        key=lambda x: (-x["students"], -x["times"], x["label"]),
    )
    return {
        "students": rows,
        "summary": {
            "students": len(rows),
            "mastered": sum(r["mastered"] for r in rows),
            "practising": sum(1 for r in rows if r["last_active"]),
            "mistakes": mistakes,
        },
    }
