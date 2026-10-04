"""
Per-student progress and adaptive problem selection.

Student state only keeps the last 5 attempts (as context for the tutor).
Progress keeps running totals per concept, so we know what a student
*keeps* getting wrong:

  state["progress"][concept] = {
    "problems": {problem_id: {"seen", "correct", "last_correct"}},
    "misconceptions": {misconception_id: times seen},
    "focus": misconception id from the latest wrong answer, until the
             student answers a problem that practises it right first time,
    "solved": problems answered correctly (on either try),
    "streak": first-try correct answers in a row,
    "mastered": True once streak has reached STREAK_GOAL,
  }

Choosing the next problem (no LLM, fully deterministic):
  1. A wrong first try comes back for its retry.
  2. Never the problem just attempted; skip ones the student last got right.
  3. If there's a focus, prefer problems that can reveal that mistake.
  4. Least-practised first, then knowledge-file order.
"""

from app.grading import MAX_TRIES, concept_attempts, find_problem, pending_retry, targets

STREAK_GOAL = 3


def concept_progress(state: dict, concept: str) -> dict:
    """This concept's progress record, created empty if it doesn't exist."""
    return state.setdefault("progress", {}).setdefault(concept, {
        "problems": {},
        "misconceptions": {},
        "focus": None,
        "solved": 0,
        "streak": 0,
        "mastered": False,
    })


def update_progress(state: dict, record: dict, problem: dict) -> None:
    """Fold one graded attempt (as stored in state["attempts"]) into progress."""
    p = concept_progress(state, record["concept"])
    stats = p["problems"].setdefault(record["problem_id"], {"seen": 0, "correct": 0, "last_correct": False})
    first_try = record["try"] == 1

    if first_try:
        stats["seen"] += 1
    if record["correct"] or record["try"] >= MAX_TRIES:
        stats["last_correct"] = record["correct"]
    if record["correct"]:
        stats["correct"] += 1
        p["solved"] += 1

    misconception = record.get("misconception")
    if misconception:
        p["misconceptions"][misconception] = p["misconceptions"].get(misconception, 0) + 1
        p["focus"] = misconception
    elif record["correct"] and first_try and p["focus"] in targets(problem):
        p["focus"] = None  # practised the weak spot and got it right unaided

    if first_try:
        p["streak"] = p["streak"] + 1 if record["correct"] else 0
        if p["streak"] >= STREAK_GOAL:
            p["mastered"] = True


def pick_next(concept_facts: dict, state: dict) -> tuple[dict, int, str | None]:
    """Return (problem, try number, focus misconception id or None)."""
    concept = concept_facts["concept"]
    problems = concept_facts["practice_problems"]
    p = concept_progress(state, concept)

    pending = pending_retry(concept, state)
    if pending:
        problem = find_problem(concept_facts, pending["problem_id"])
        if problem:
            return problem, pending.get("try", 1) + 1, p["focus"]

    attempts = concept_attempts(concept, state)
    last_id = attempts[-1].get("problem_id") if attempts else None
    candidates = [q for q in problems if q["id"] != last_id] or problems
    not_solved = [q for q in candidates if not p["problems"].get(q["id"], {}).get("last_correct")]
    pool = not_solved or candidates

    focus = p["focus"]
    if focus:
        practising = [q for q in pool if focus in targets(q)]
        if practising:
            pool = practising
        else:
            focus = None  # nothing left that practises it; carry on normally

    # sorted() is stable, so equally-practised problems keep file order
    pool = sorted(pool, key=lambda q: p["problems"].get(q["id"], {}).get("seen", 0))
    return pool[0], 1, focus


def progress_summary(state: dict, concept: str) -> dict:
    """The progress numbers the page shows."""
    p = concept_progress(state, concept)
    return {
        "solved": p["solved"],
        "streak": p["streak"],
        "streak_goal": STREAK_GOAL,
        "mastered": p["mastered"],
    }
