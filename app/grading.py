"""
Answer checking against the answer keys in app/knowledge/*.json.

Grading is deterministic -- no LLM involved -- so a student's attempt
history only ever contains verified right/wrong results. The LLM's job
is explaining, not judging.

Each practice problem has:
  - answer_format: "fraction" or "yes_no"
  - answer: the expected answer, e.g. "8/12" or "yes"
  - wrong_answers: known wrong answers mapped to a misconception id,
    so we can tell the tutor WHY the student was likely wrong
"""

import re

FRACTION_RE = re.compile(r"^\s*(-?\d+)\s*/\s*(\d+)\s*$")
YES = {"yes", "y"}
NO = {"no", "n"}


class InvalidAnswer(ValueError):
    """The answer couldn't be parsed in the problem's expected format."""


def normalize(answer: str, answer_format: str) -> str:
    """Turn raw student input into a canonical form like "8/12" or "yes"."""
    if answer_format == "fraction":
        match = FRACTION_RE.match(answer)
        if not match:
            raise InvalidAnswer("Please answer with a fraction like 3/4.")
        numerator, denominator = int(match.group(1)), int(match.group(2))
        if denominator == 0:
            raise InvalidAnswer("A fraction's denominator can't be 0.")
        return f"{numerator}/{denominator}"

    if answer_format == "yes_no":
        word = answer.strip().lower()
        if word in YES:
            return "yes"
        if word in NO:
            return "no"
        raise InvalidAnswer("Please answer yes or no.")

    raise ValueError(f"Unknown answer_format: {answer_format}")


def find_problem(concept_facts: dict, problem_id: str) -> dict | None:
    for problem in concept_facts.get("practice_problems", []):
        if problem["id"] == problem_id:
            return problem
    return None


def next_problem(concept_facts: dict, student_state: dict) -> dict:
    """Rotate through the problems, starting after the last one attempted."""
    problems = concept_facts["practice_problems"]
    ids = [p["id"] for p in problems]
    attempted = [
        a.get("problem_id") for a in student_state.get("attempts", [])
        if a.get("concept") == concept_facts["concept"] and a.get("problem_id") in ids
    ]
    if not attempted:
        return problems[0]
    return problems[(ids.index(attempted[-1]) + 1) % len(problems)]


def check_answer(concept_facts: dict, problem: dict, raw_answer: str) -> dict:
    """
    Grade an answer. Returns {"correct", "answer", "error_type"} where
    error_type is the matching misconception description, or None if the
    answer is correct or a wrong answer we don't recognise.
    Raises InvalidAnswer if the input can't be parsed.
    """
    answer = normalize(raw_answer, problem["answer_format"])
    correct = answer == normalize(problem["answer"], problem["answer_format"])

    error_type = None
    if not correct:
        misconception_id = problem.get("wrong_answers", {}).get(answer)
        for m in concept_facts.get("misconceptions", []):
            if m["id"] == misconception_id:
                error_type = m["description"]

    return {"correct": correct, "answer": answer, "error_type": error_type}
