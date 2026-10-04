import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import state
from app.grading import check_answer
from app.llm_client import build_prompt

client = TestClient(main.app)


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def fake(concept_facts, student_state, question):
        calls.append((concept_facts, student_state, question))
        return "explanation"

    monkeypatch.setattr(main, "generate_explanation", fake)
    return calls


def test_new_students_do_not_share_attempts():
    state.log_attempt("a", "equivalent_fractions", False, "added instead of multiplied")
    assert state.get_state("b")["attempts"] == []


def test_attempt_stores_answer_and_keeps_last_five():
    for i in range(7):
        state.log_attempt("s", "equivalent_fractions", False, None, f"answer {i}")
    attempts = state.get_state("s")["attempts"]
    assert [a["answer"] for a in attempts] == [f"answer {i}" for i in range(2, 7)]


def test_ask_returns_explanation(fake_llm):
    r = client.post("/ask", json={"student_id": "s", "concept": "equivalent_fractions", "question": "q"})
    assert r.status_code == 200
    assert r.json() == {"explanation": "explanation"}


@pytest.mark.parametrize("concept", ["../../etc/passwd", "Equivalent_Fractions", "a/b", ""])
def test_ask_rejects_invalid_concept(fake_llm, concept):
    r = client.post("/ask", json={"student_id": "s", "concept": concept, "question": "q"})
    assert r.status_code == 400
    assert fake_llm == []


def test_ask_unknown_concept_is_404(fake_llm):
    r = client.post("/ask", json={"student_id": "s", "concept": "nope", "question": "q"})
    assert r.status_code == 404


def test_ask_llm_failure_is_502(monkeypatch):
    def boom(*args):
        raise RuntimeError("quota exceeded")

    monkeypatch.setattr(main, "generate_explanation", boom)
    r = client.post("/ask", json={"student_id": "s", "concept": "equivalent_fractions", "question": "q"})
    assert r.status_code == 502
    assert "quota exceeded" in r.json()["detail"]


def answer(problem_id, given, student_id="s"):
    return client.post("/answer", json={
        "student_id": student_id, "concept": "equivalent_fractions",
        "problem_id": problem_id, "answer": given
    })


def test_problem_does_not_leak_answer():
    r = client.get("/problem", params={"student_id": "s", "concept": "equivalent_fractions"})
    assert r.status_code == 200
    assert r.json() == {
        "id": "p1",
        "prompt": "Find a fraction equivalent to 2/3 with denominator 12.",
        "answer_format": "fraction",
    }


def test_problems_rotate_after_each_attempt():
    answer("p1", "8/12")
    r = client.get("/problem", params={"student_id": "s", "concept": "equivalent_fractions"})
    assert r.json()["id"] == "p2"


def test_problems_wrap_around():
    answer("p6", "2/3")
    r = client.get("/problem", params={"student_id": "s", "concept": "equivalent_fractions"})
    assert r.json()["id"] == "p1"


def test_correct_answer_is_graded_and_logged():
    r = answer("p1", " 8 / 12 ")
    assert r.status_code == 200
    body = r.json()
    assert body["correct"] is True
    assert "correct_answer" not in body
    last = body["state"]["attempts"][-1]
    assert last["correct"] is True
    assert last["answer"] == "8/12"
    assert last["problem_id"] == "p1"


def test_equivalent_but_wrong_denominator_is_incorrect():
    # 4/6 equals 2/3, but the problem asks for denominator 12
    body = answer("p1", "4/6").json()
    assert body["correct"] is False
    assert body["correct_answer"] == "8/12"
    assert body["error_type"] is None


def test_known_wrong_answer_is_tagged_with_misconception():
    body = answer("p1", "11/12").json()
    assert body["correct"] is False
    assert "Adding the same number" in body["error_type"]
    assert "Adding the same number" in body["state"]["attempts"][-1]["error_type"]


def test_yes_no_answers():
    assert answer("p2", "Yes").json()["correct"] is True
    body = answer("p4", "y").json()
    assert body["correct"] is False
    assert "Adding the same number" in body["error_type"]


@pytest.mark.parametrize("problem_id,given", [
    ("p1", "eight twelfths"), ("p1", "8/0"), ("p1", "8"), ("p2", "maybe"),
])
def test_unparseable_answer_is_400_and_not_logged(problem_id, given):
    r = answer(problem_id, given)
    assert r.status_code == 400
    assert state.get_state("s")["attempts"] == []


def test_unknown_problem_is_404():
    assert answer("nope", "1/2").status_code == 404


def test_answer_rejects_invalid_concept():
    r = client.post("/answer", json={"student_id": "s", "concept": "../x", "problem_id": "p1", "answer": "1/2"})
    assert r.status_code == 400


def test_answer_key_is_consistent():
    """Every problem's answer and known wrong answers parse, and wrong answers really are wrong."""
    facts = main.load_concept("equivalent_fractions")
    misconception_ids = {m["id"] for m in facts["misconceptions"]}
    for p in facts["practice_problems"]:
        assert check_answer(facts, p, p["answer"])["correct"], p["id"]
        for wrong, misconception_id in p["wrong_answers"].items():
            assert misconception_id in misconception_ids, (p["id"], wrong)
            result = check_answer(facts, p, wrong)
            assert not result["correct"], (p["id"], wrong)
            assert result["error_type"], (p["id"], wrong)


def test_prompt_excludes_answer_key():
    prompt = build_prompt(main.load_concept("equivalent_fractions"), {"attempts": []}, "q")
    assert "practice_problems" not in prompt
    assert "15/18" not in prompt


def test_prompt_only_includes_matching_concept_attempts():
    student_state = {"attempts": [
        {"concept": "equivalent_fractions", "correct": False, "error_type": "MATCHING", "answer": None},
        {"concept": "other_concept", "correct": False, "error_type": "UNRELATED", "answer": None},
    ]}
    prompt = build_prompt(main.load_concept("equivalent_fractions"), student_state, "q")
    assert "MATCHING" in prompt
    assert "UNRELATED" not in prompt
