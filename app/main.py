import json
import os
import re
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.grading import (
    MAX_TRIES, InvalidAnswer, check_answer, find_problem, next_problem, pending_retry
)
from app.llm_client import generate_explanation
from app.state import get_state, log_attempt

app = FastAPI()

KNOWLEDGE_DIR = os.path.join(os.path.dirname(__file__), "knowledge")


def load_concept(concept_name: str) -> dict:
    # Only allow plain names like "equivalent_fractions" -- no path separators
    if not re.fullmatch(r"[a-z0-9_]+", concept_name):
        raise HTTPException(status_code=400, detail="Invalid concept name")
    path = os.path.join(KNOWLEDGE_DIR, f"{concept_name}.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Unknown concept")
    with open(path, "r") as f:
        return json.load(f)


class AskRequest(BaseModel):
    student_id: str
    concept: str
    question: str


@app.post("/ask")
def ask(req: AskRequest):
    concept_facts = load_concept(req.concept)
    student_state = get_state(req.student_id)

    try:
        explanation = generate_explanation(concept_facts, student_state, req.question)
    except Exception as e:
        # Surface LLM failures (quota, stale model name, network) as JSON
        # the frontend can show, instead of an opaque 500
        raise HTTPException(status_code=502, detail=f"Tutor is unavailable: {e}")

    return {"explanation": explanation}


@app.get("/problem")
def problem(student_id: str, concept: str):
    concept_facts = load_concept(concept)
    p, try_number = next_problem(concept_facts, get_state(student_id))
    problems = concept_facts["practice_problems"]
    # Never send the answer key to the browser
    return {
        "id": p["id"],
        "prompt": p["prompt"],
        "answer_format": p["answer_format"],
        "try": try_number,
        "given": p.get("given"),  # shown as a pie chart; already in the prompt text
        "number": problems.index(p) + 1,
        "total": len(problems),
    }


class AnswerRequest(BaseModel):
    student_id: str
    concept: str
    problem_id: str
    answer: str


@app.post("/answer")
def answer(req: AnswerRequest):
    concept_facts = load_concept(req.concept)
    p = find_problem(concept_facts, req.problem_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Unknown problem")

    try:
        result = check_answer(concept_facts, p, req.answer)
    except InvalidAnswer as e:
        # Unparseable input isn't a real attempt -- don't log it
        raise HTTPException(status_code=400, detail=str(e))

    # Second try only if this problem's first try was wrong
    pending = pending_retry(req.concept, get_state(req.student_id))
    try_number = pending.get("try", 1) + 1 if pending and pending["problem_id"] == p["id"] else 1
    finished = result["correct"] or try_number >= MAX_TRIES

    state = log_attempt(
        req.student_id, req.concept, result["correct"], result["error_type"],
        result["answer"], problem_id=p["id"], problem=p["prompt"], try_number=try_number
    )
    response = {
        "correct": result["correct"],
        "try": try_number,
        "finished": finished,
        "error_type": result["error_type"],
        "feedback": result["feedback"],
        "state": state,
    }
    # Only reveal the answer once there are no retries left
    if finished and not result["correct"]:
        response["correct_answer"] = p["answer"]
    return response


# Serve the simple frontend
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return FileResponse("static/index.html")
