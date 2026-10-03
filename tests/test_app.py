import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import state
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


def test_attempt_endpoint_logs_answer():
    r = client.post("/attempt", json={
        "student_id": "s", "concept": "equivalent_fractions",
        "correct": False, "error_type": "only changed numerator", "answer": "2/5"
    })
    assert r.status_code == 200
    assert r.json()["state"]["attempts"][-1]["answer"] == "2/5"


def test_attempt_rejects_invalid_concept():
    r = client.post("/attempt", json={"student_id": "s", "concept": "../x", "correct": True})
    assert r.status_code == 400


def test_prompt_only_includes_matching_concept_attempts():
    student_state = {"attempts": [
        {"concept": "equivalent_fractions", "correct": False, "error_type": "MATCHING", "answer": None},
        {"concept": "other_concept", "correct": False, "error_type": "UNRELATED", "answer": None},
    ]}
    prompt = build_prompt(main.load_concept("equivalent_fractions"), student_state, "q")
    assert "MATCHING" in prompt
    assert "UNRELATED" not in prompt
