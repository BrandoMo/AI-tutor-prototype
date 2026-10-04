"""
Answer checking against the answer keys in app/knowledge/*.json.

Grading is deterministic -- no LLM involved -- so a student's attempt
history only ever contains verified right/wrong results. The LLM's job
is explaining, not judging.

Each practice problem has:
  - answer_format: "fraction" or "yes_no"
  - answer: the expected answer, e.g. "8/12" or "yes"
  - kind + numbers describing the problem, used to diagnose wrong answers:
      "fill":     given "2/3", target {"denominator": 12} or {"numerator": 15}
      "simplify": given "6/9"
      "compare":  given "2/5", other "4/10" (a yes/no question)
  - wrong_answers (optional): specific wrong answers mapped to a
    misconception id, for odd cases the rules below don't catch

Diagnosis rules report these misconception ids, so a concept file using
them should define: adding, one_part_only, same_looking, wrong_form.
"""

import re
from fractions import Fraction

FRACTION_RE = re.compile(r"^\s*(-?\d+)\s*/\s*(\d+)\s*$")
YES = {"yes", "y"}
NO = {"no", "n"}
MAX_TRIES = 2  # one retry after a wrong answer, then the answer is revealed


class InvalidAnswer(ValueError):
    """The answer couldn't be parsed in the problem's expected format."""


def parse_fraction(text: str) -> tuple[int, int]:
    match = FRACTION_RE.match(text)
    if not match:
        raise InvalidAnswer("Please answer with a fraction like 3/4.")
    numerator, denominator = int(match.group(1)), int(match.group(2))
    if denominator == 0:
        raise InvalidAnswer("A fraction's denominator can't be 0.")
    return numerator, denominator


def normalize(answer: str, answer_format: str) -> str:
    """Turn raw student input into a canonical form like "8/12" or "yes"."""
    if answer_format == "fraction":
        numerator, denominator = parse_fraction(answer)
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


def concept_attempts(concept: str, student_state: dict) -> list[dict]:
    return [a for a in student_state.get("attempts", []) if a.get("concept") == concept]


def pending_retry(concept: str, student_state: dict) -> dict | None:
    """The last attempt if it was a wrong answer with a retry still to come, else None."""
    attempts = concept_attempts(concept, student_state)
    if not attempts:
        return None
    last = attempts[-1]
    if last.get("problem_id") and not last["correct"] and last.get("try", 1) < MAX_TRIES:
        return last
    return None


def diagnose(problem: dict, answer: str) -> str | None:
    """
    Guess which misconception a wrong (normalized) answer reveals, from
    the shape of the mistake. Returns a misconception id or None.
    """
    if answer in problem.get("wrong_answers", {}):
        return problem["wrong_answers"][answer]

    kind = problem.get("kind")
    if kind in ("fill", "simplify"):
        given_n, given_d = parse_fraction(problem["given"])
        n, d = parse_fraction(answer)
        if Fraction(n, d) == Fraction(given_n, given_d):
            return "wrong_form"  # right value, but not what was asked for
        n_change, d_change = n - given_n, d - given_d
        if n_change == d_change != 0:
            return "adding"  # e.g. 2/3 -> 11/12: +9 on top and bottom
        if (n_change == 0) != (d_change == 0):
            return "one_part_only"  # e.g. 2/3 -> 2/12

    elif kind == "compare":
        given_n, given_d = parse_fraction(problem["given"])
        other_n, other_d = parse_fraction(problem["other"])
        if answer == "yes" and other_n - given_n == other_d - given_d != 0:
            return "adding"  # e.g. thinks 1/3 = 2/4 because both went up by 1
        if answer == "no" and Fraction(given_n, given_d) == Fraction(other_n, other_d):
            return "same_looking"  # they look different, so "not equivalent"

    return None


def targets(problem: dict) -> set[str]:
    """
    Misconceptions a problem can reveal -- what diagnose() can detect on it.
    Used to pick problems that practise a student's recent mistake.
    """
    found = set(problem.get("wrong_answers", {}).values())
    kind = problem.get("kind")
    if kind in ("fill", "simplify"):
        found |= {"adding", "one_part_only", "wrong_form"}
    elif kind == "compare":
        given_n, given_d = parse_fraction(problem["given"])
        other_n, other_d = parse_fraction(problem["other"])
        if Fraction(given_n, given_d) == Fraction(other_n, other_d):
            found.add("same_looking")
        elif other_n - given_n == other_d - given_d != 0:
            found.add("adding")
    return found


def feedback_for(problem: dict, answer: str, misconception_id: str | None) -> str | None:
    """A short message for mistakes code can explain itself, without the tutor."""
    if misconception_id != "wrong_form":
        return None
    start = f"{answer} is equivalent to {problem['given']}, but"
    target = problem.get("target", {})
    if "denominator" in target:
        return f"{start} the question asks for denominator {target['denominator']}."
    if "numerator" in target:
        return f"{start} the question asks for numerator {target['numerator']}."
    return f"{start} it isn't in simplest form yet."


def check_answer(concept_facts: dict, problem: dict, raw_answer: str) -> dict:
    """
    Grade an answer. Returns {"correct", "answer", "misconception",
    "error_type", "feedback"}: misconception is the matched misconception's
    id and error_type its description, both None if the answer is correct
    or the mistake isn't recognised.
    Raises InvalidAnswer if the input can't be parsed.
    """
    answer = normalize(raw_answer, problem["answer_format"])
    correct = answer == normalize(problem["answer"], problem["answer_format"])

    misconception_id = error_type = feedback = None
    if not correct:
        misconception_id = diagnose(problem, answer)
        for m in concept_facts.get("misconceptions", []):
            if m["id"] == misconception_id:
                error_type = m["description"]
        if error_type is None:
            misconception_id = None  # not defined in this concept file
        feedback = feedback_for(problem, answer, misconception_id)

    return {
        "correct": correct,
        "answer": answer,
        "misconception": misconception_id,
        "error_type": error_type,
        "feedback": feedback,
    }
