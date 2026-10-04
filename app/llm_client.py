"""
LLM client wrapper.

Everything provider-specific lives here. main.py and other modules
only ever call generate_explanation() -- they don't know or care
whether it's Gemini, Claude, or anything else underneath.

Requires GEMINI_API_KEY in .env (see .env.example).

Swapping to Claude later: rewrite the inside of generate_explanation()
to call the Anthropic API instead. Nothing outside this file changes.

Note on model names: Google deprecates free-tier Gemini models
fairly often. If you get a 404 "no longer available to new users"
error, check https://ai.google.dev/gemini-api/docs/models for the
current recommended Flash-Lite model and update the model= string below.
"""

import os
import json
from dotenv import load_dotenv
from google import genai

load_dotenv()  # reads .env into environment variables

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def build_prompt(concept_facts: dict, student_state: dict, student_question: str) -> str:
    """
    Assemble the prompt from: knowledge base facts + student state + question.
    Kept as its own function so we can tweak prompt wording without
    touching the API call logic.
    """
    # Only this concept's attempts are relevant to this explanation
    recent_attempts = [
        a for a in student_state.get("attempts", [])
        if a.get("concept") == concept_facts.get("concept")
    ]

    # Keep the answer keys away from the LLM so it can't hand out answers
    # to problems the student hasn't tried yet
    facts = {k: v for k, v in concept_facts.items() if k != "practice_problems"}

    prompt = f"""You are a patient math tutor. Explain the concept below to a student,
using ONLY the facts provided. Do not introduce rules or examples that
aren't given here. Keep the explanation short, clear, and encouraging.

CONCEPT FACTS:
{json.dumps(facts, indent=2)}

STUDENT'S RECENT ATTEMPTS (most recent last). These were graded
automatically against an answer key, so "correct" is reliable. When
"error_type" is set it names the misconception that wrong answer matches;
when it is null on a wrong answer, the mistake wasn't a known one:
{json.dumps(recent_attempts, indent=2)}

STUDENT'S QUESTION OR WRONG ANSWER:
{student_question}

If the student's recent attempts show a specific misconception, address
it directly. Otherwise give a clear first explanation with one worked example.
"""
    return prompt


def generate_explanation(concept_facts: dict, student_state: dict, student_question: str) -> str:
    """
    Calls the Gemini API and returns the generated explanation text.
    """
    prompt = build_prompt(concept_facts, student_state, student_question)

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=prompt
    )
    return response.text
