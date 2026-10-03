import json
import os
import re
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

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

    explanation = generate_explanation(concept_facts, student_state, req.question)

    return {"explanation": explanation}


class AttemptRequest(BaseModel):
    student_id: str
    concept: str
    correct: bool
    error_type: str | None = None


@app.post("/attempt")
def attempt(req: AttemptRequest):
    state = log_attempt(req.student_id, req.concept, req.correct, req.error_type)
    return {"state": state}


# Serve the simple frontend
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return FileResponse("static/index.html")
