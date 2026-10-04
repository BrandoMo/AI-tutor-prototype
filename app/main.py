import json
import os
import re
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import auth
from app.auth import current_student
from app.grading import MAX_TRIES, InvalidAnswer, check_answer, find_problem, pending_retry
from app.llm_client import generate_explanation
from app.progress import concept_progress, pick_next, progress_summary, update_progress
from app.state import add_attempt, get_state, save_state

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


def misconception_label(concept_facts: dict, misconception_id: str | None) -> str | None:
    """The short, student-facing name of a misconception, e.g. "change both parts"."""
    for m in concept_facts.get("misconceptions", []):
        if m["id"] == misconception_id:
            return m.get("label")
    return None


# --- Accounts ---

class Credentials(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


@app.post("/register")
def register(creds: Credentials, response: Response):
    username = auth.register(creds.username, creds.password)
    auth.start_session(response, username)
    return {"username": username}


@app.post("/login")
def login(creds: Credentials, response: Response):
    username = auth.login(creds.username, creds.password)
    auth.start_session(response, username)
    return {"username": username}


@app.post("/logout")
def logout(request: Request, response: Response):
    auth.end_session(request, response)
    return {"ok": True}


@app.get("/me")
def me(student_id: str = Depends(current_student)):
    return {"username": student_id}


# --- Tutoring (all need a signed-in student) ---

class AskRequest(BaseModel):
    concept: str
    question: str


@app.post("/ask")
def ask(req: AskRequest, student_id: str = Depends(current_student)):
    concept_facts = load_concept(req.concept)
    student_state = get_state(student_id)

    try:
        explanation = generate_explanation(concept_facts, student_state, req.question)
    except Exception as e:
        # Surface LLM failures (quota, stale model name, network) as JSON
        # the frontend can show, instead of an opaque 500
        raise HTTPException(status_code=502, detail=f"Tutor is unavailable: {e}")

    return {"explanation": explanation}


@app.get("/problem")
def problem(concept: str, student_id: str = Depends(current_student)):
    concept_facts = load_concept(concept)
    state = get_state(student_id)
    p, try_number, focus = pick_next(concept_facts, state)
    # Never send the answer key to the browser
    return {
        "id": p["id"],
        "prompt": p["prompt"],
        "answer_format": p["answer_format"],
        "try": try_number,
        "given": p.get("given"),  # shown as a pie chart; already in the prompt text
        "focus": misconception_label(concept_facts, focus),
        "progress": progress_summary(state, concept),
    }


class AnswerRequest(BaseModel):
    concept: str
    problem_id: str
    answer: str


@app.post("/answer")
def answer(req: AnswerRequest, student_id: str = Depends(current_student)):
    concept_facts = load_concept(req.concept)
    p = find_problem(concept_facts, req.problem_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Unknown problem")

    try:
        result = check_answer(concept_facts, p, req.answer)
    except InvalidAnswer as e:
        # Unparseable input isn't a real attempt -- don't log it
        raise HTTPException(status_code=400, detail=str(e))

    state = get_state(student_id)
    # Second try only if this problem's first try was wrong
    pending = pending_retry(req.concept, state)
    try_number = pending.get("try", 1) + 1 if pending and pending["problem_id"] == p["id"] else 1
    finished = result["correct"] or try_number >= MAX_TRIES

    was_mastered = concept_progress(state, req.concept)["mastered"]
    record = {
        "concept": req.concept,
        "problem_id": p["id"],
        "problem": p["prompt"],
        "try": try_number,
        "answer": result["answer"],
        "correct": result["correct"],
        "misconception": result["misconception"],
        "error_type": result["error_type"],
    }
    add_attempt(state, record)
    update_progress(state, record, p)
    save_state(student_id, state)

    progress = progress_summary(state, req.concept)
    response = {
        "correct": result["correct"],
        "try": try_number,
        "finished": finished,
        "error_type": result["error_type"],
        "feedback": result["feedback"],
        "progress": progress,
        "just_mastered": progress["mastered"] and not was_mastered,
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
