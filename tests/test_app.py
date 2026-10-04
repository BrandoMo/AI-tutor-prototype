from fractions import Fraction
from math import gcd

import pytest

import app.main as main
from app import state
from app.grading import check_answer
from app.llm_client import build_prompt
from app.progress import concept_progress

CONCEPT = "equivalent_fractions"


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def fake(concept_facts, student_state, question):
        calls.append((concept_facts, student_state, question))
        return "explanation"

    monkeypatch.setattr(main, "generate_explanation", fake)
    return calls


def answer(client, problem_id, given):
    return client.post("/answer", json={"concept": CONCEPT, "problem_id": problem_id, "answer": given})


def get_problem(client):
    return client.get("/problem", params={"concept": CONCEPT}).json()


# --- Student state ---

def test_new_students_do_not_share_state():
    a = state.get_state("a")
    state.add_attempt(a, {"concept": CONCEPT, "correct": False})
    concept_progress(a, CONCEPT)["solved"] = 5
    b = state.get_state("b")
    assert b["attempts"] == []
    assert b["progress"] == {}


def test_attempts_keep_only_last_five():
    s = state.get_state("s")
    for i in range(7):
        state.add_attempt(s, {"answer": f"answer {i}"})
    assert [a["answer"] for a in s["attempts"]] == [f"answer {i}" for i in range(2, 7)]


def test_state_saved_before_progress_existed_still_loads():
    state.redis.set("student:old", '{"current_concept": null, "attempts": []}')
    assert state.get_state("old")["progress"] == {}


# --- Asking the tutor ---

def test_ask_returns_explanation(client, fake_llm):
    r = client.post("/ask", json={"concept": CONCEPT, "question": "q"})
    assert r.status_code == 200
    assert r.json() == {"explanation": "explanation"}


@pytest.mark.parametrize("concept", ["../../etc/passwd", "Equivalent_Fractions", "a/b", ""])
def test_ask_rejects_invalid_concept(client, fake_llm, concept):
    r = client.post("/ask", json={"concept": concept, "question": "q"})
    assert r.status_code == 400
    assert fake_llm == []


def test_ask_unknown_concept_is_404(client, fake_llm):
    r = client.post("/ask", json={"concept": "nope", "question": "q"})
    assert r.status_code == 404


def test_ask_llm_failure_is_502(client, monkeypatch):
    def boom(*args):
        raise RuntimeError("quota exceeded")

    monkeypatch.setattr(main, "generate_explanation", boom)
    r = client.post("/ask", json={"concept": CONCEPT, "question": "q"})
    assert r.status_code == 502
    assert "quota exceeded" in r.json()["detail"]


# --- Problems and grading ---

def test_problem_does_not_leak_answer(client):
    assert get_problem(client) == {
        "id": "p1",
        "prompt": "Find a fraction equivalent to 2/3 with denominator 12.",
        "answer_format": "fraction",
        "try": 1,
        "given": "2/3",
        "focus": None,
        "progress": {"solved": 0, "streak": 0, "streak_goal": 3, "mastered": False},
    }


def test_correct_answer_is_graded_and_logged(client):
    r = answer(client, "p1", " 8 / 12 ")
    assert r.status_code == 200
    body = r.json()
    assert body["correct"] is True
    assert body["finished"] is True
    assert "correct_answer" not in body
    assert body["progress"] == {"solved": 1, "streak": 1, "streak_goal": 3, "mastered": False}
    last = body["state"]["attempts"][-1]
    assert last["correct"] is True
    assert last["answer"] == "8/12"
    assert last["problem_id"] == "p1"
    assert last["try"] == 1
    assert get_problem(client)["id"] == "p2"


# --- Retries ---

def test_first_wrong_try_gets_a_retry_without_the_answer(client):
    body = answer(client, "p1", "11/12").json()
    assert body["correct"] is False
    assert body["try"] == 1
    assert body["finished"] is False
    assert "correct_answer" not in body
    # The same problem comes back for a second try, with the focus as a hint
    p = get_problem(client)
    assert (p["id"], p["try"], p["focus"]) == ("p1", 2, "multiply, don't add")


def test_second_wrong_try_reveals_answer_and_moves_on(client):
    answer(client, "p1", "11/12")
    body = answer(client, "p1", "2/12").json()
    assert body["try"] == 2
    assert body["finished"] is True
    assert body["correct_answer"] == "8/12"
    assert [a["try"] for a in body["state"]["attempts"]] == [1, 2]
    # Next up practises the latest mistake (changed only one part)
    p = get_problem(client)
    assert (p["id"], p["try"], p["focus"]) == ("p3", 1, "change both parts")


def test_right_on_second_try(client):
    answer(client, "p1", "11/12")
    body = answer(client, "p1", "8/12").json()
    assert body["correct"] is True
    assert body["try"] == 2
    assert body["finished"] is True
    assert body["progress"]["streak"] == 0  # needed a hint
    p = get_problem(client)
    assert (p["id"], p["try"]) == ("p3", 1)


def test_unparseable_retry_does_not_use_up_the_retry(client):
    answer(client, "p1", "11/12")
    assert answer(client, "p1", "eight").status_code == 400
    assert answer(client, "p1", "2/12").json()["try"] == 2


def test_old_attempt_records_do_not_block_problems(client):
    # Records from before retries/problems existed have no problem_id or try
    s = state.get_state("sam")
    state.add_attempt(s, {"concept": CONCEPT, "correct": False, "error_type": "note", "answer": "x"})
    state.save_state("sam", s)
    p = get_problem(client)
    assert (p["id"], p["try"]) == ("p1", 1)


def test_prompt_withholds_answer_only_while_retry_pending(client):
    facts = main.load_concept(CONCEPT)
    answer(client, "p1", "11/12")
    assert "do NOT state the correct" in build_prompt(facts, state.get_state("sam"), "hint?")
    answer(client, "p1", "2/12")
    assert "do NOT state the correct" not in build_prompt(facts, state.get_state("sam"), "why?")


# --- Diagnosing wrong answers ---

@pytest.mark.parametrize("problem_id,given,expected", [
    ("p1", "11/12", "Adding"),            # 2/3 -> 11/12: +9 top and bottom
    ("p3", "19/20", "Adding"),            # 3/4 -> 19/20: +16 top and bottom
    ("p6", "3/6", "Adding"),              # 6/9 -> 3/6: subtracted 3 from both
    ("p5", "15/16", "Adding"),            # 5/6 -> 15/16: +10 top and bottom
    ("p1", "2/12", "only need to change"),   # kept the numerator
    ("p5", "15/6", "only need to change"),   # kept the denominator
    ("p6", "2/9", "only need to change"),
    ("p6", "6/3", "only need to change"),
    ("p4", "yes", "Adding"),              # 1/3 vs 2/4: both +1
    ("p2", "no", "written exactly the same way"),
    ("p1", "4/6", "not in the form"),     # equivalent, wrong denominator
    ("p6", "4/6", "not in the form"),     # equivalent, not simplest
])
def test_wrong_answers_are_diagnosed_by_pattern(client, problem_id, given, expected):
    body = answer(client, problem_id, given).json()
    assert body["correct"] is False
    assert expected in body["error_type"]
    assert expected in body["state"]["attempts"][-1]["error_type"]


def test_unrecognised_wrong_answer_has_no_error_type(client):
    body = answer(client, "p1", "7/12").json()
    assert body["correct"] is False
    assert body["error_type"] is None
    assert body["feedback"] is None


@pytest.mark.parametrize("problem_id,given,feedback", [
    ("p1", "4/6", "4/6 is equivalent to 2/3, but the question asks for denominator 12."),
    ("p5", "10/12", "10/12 is equivalent to 5/6, but the question asks for numerator 15."),
    ("p6", "4/6", "4/6 is equivalent to 6/9, but it isn't in simplest form yet."),
])
def test_wrong_form_gets_specific_feedback(client, problem_id, given, feedback):
    assert answer(client, problem_id, given).json()["feedback"] == feedback


def test_other_mistakes_leave_feedback_to_the_tutor(client):
    assert answer(client, "p1", "11/12").json()["feedback"] is None


def test_listed_wrong_answer_overrides_rules():
    facts = main.load_concept(CONCEPT)
    problem = {**facts["practice_problems"][0], "wrong_answers": {"7/12": "one_part_only"}}
    result = check_answer(facts, problem, "7/12")
    assert result["misconception"] == "one_part_only"
    assert "only need to change" in result["error_type"]


@pytest.mark.parametrize("problem_id,given", [
    ("p1", "eight twelfths"), ("p1", "8/0"), ("p1", "8"), ("p2", "maybe"),
])
def test_unparseable_answer_is_400_and_not_logged(client, problem_id, given):
    r = answer(client, problem_id, given)
    assert r.status_code == 400
    assert state.get_state("sam")["attempts"] == []


def test_unknown_problem_is_404(client):
    assert answer(client, "nope", "1/2").status_code == 404


def test_answer_rejects_invalid_concept(client):
    r = client.post("/answer", json={"concept": "../x", "problem_id": "p1", "answer": "1/2"})
    assert r.status_code == 400


def test_answer_key_is_consistent():
    """Every problem's structured numbers agree with its prompt and answer key."""
    facts = main.load_concept(CONCEPT)
    misconception_ids = {m["id"] for m in facts["misconceptions"]}
    # Every misconception the diagnosis rules can report must be defined, with a label
    assert {"adding", "one_part_only", "same_looking", "wrong_form"} <= misconception_ids
    assert all(m.get("label") for m in facts["misconceptions"])
    assert len({p["id"] for p in facts["practice_problems"]}) == len(facts["practice_problems"])

    for p in facts["practice_problems"]:
        assert p["given"] in p["prompt"], p["id"]
        assert check_answer(facts, p, p["answer"])["correct"], p["id"]
        given = Fraction(p["given"])

        if p["kind"] == "compare":
            assert p["answer_format"] == "yes_no", p["id"]
            assert p["other"] in p["prompt"], p["id"]
            assert (p["answer"] == "yes") == (given == Fraction(p["other"])), p["id"]
        else:
            assert p["answer_format"] == "fraction", p["id"]
            n, d = (int(x) for x in p["answer"].split("/"))
            assert Fraction(n, d) == given, p["id"]
            if p["kind"] == "fill":
                target = p["target"]
                assert target.get("denominator", d) == d and target.get("numerator", n) == n, p["id"]
            elif p["kind"] == "simplify":
                assert gcd(n, d) == 1, p["id"]
            else:
                raise AssertionError(f"Unknown kind for {p['id']}: {p['kind']}")

        for misconception_id in p.get("wrong_answers", {}).values():
            assert misconception_id in misconception_ids, p["id"]


# --- Prompt ---

def test_prompt_excludes_answer_key():
    prompt = build_prompt(main.load_concept(CONCEPT), {"attempts": []}, "q")
    assert "practice_problems" not in prompt
    assert "15/18" not in prompt


def test_prompt_only_includes_matching_concept_attempts():
    student_state = {"attempts": [
        {"concept": CONCEPT, "correct": False, "error_type": "MATCHING", "answer": None},
        {"concept": "other_concept", "correct": False, "error_type": "UNRELATED", "answer": None},
    ]}
    prompt = build_prompt(main.load_concept(CONCEPT), student_state, "q")
    assert "MATCHING" in prompt
    assert "UNRELATED" not in prompt


def test_prompt_summarises_repeated_mistakes(client):
    for given in ["11/12", "19/20"]:  # adding, twice, on two problems
        answer(client, "p1" if given == "11/12" else "p3", given)
    facts = main.load_concept(CONCEPT)
    prompt = build_prompt(facts, state.get_state("sam"), "q")
    assert "Problems solved: 0" in prompt
    assert "Adding (or subtracting) the same number" in prompt
    assert "(2x)" in prompt
