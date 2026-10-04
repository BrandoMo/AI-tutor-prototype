import app.main as main
from app import state
from app.progress import STREAK_GOAL, concept_progress, pick_next

CONCEPT = "equivalent_fractions"
FACTS = main.load_concept(CONCEPT)
ANSWERS = {p["id"]: p["answer"] for p in FACTS["practice_problems"]}


def answer(client, problem_id, given):
    r = client.post("/answer", json={"concept": CONCEPT, "problem_id": problem_id, "answer": given})
    assert r.status_code == 200, r.text
    return r.json()


def next_problem(client):
    return client.get("/problem", params={"concept": CONCEPT}).json()


def solve_next(client):
    """Answer whatever comes next correctly; return its id."""
    p = next_problem(client)
    answer(client, p["id"], ANSWERS[p["id"]])
    return p["id"]


def test_new_student_works_through_problems_in_order(client):
    assert [solve_next(client) for _ in range(5)] == ["p1", "p2", "p3", "p4", "p5"]


def test_after_solving_everything_least_practised_comes_first_and_never_repeats(client):
    seen = [solve_next(client) for _ in range(len(ANSWERS))]
    assert seen == [f"p{i}" for i in range(1, 15)]
    # Review round: all solved once, so back to file order, skipping the one just done
    assert solve_next(client) == "p1"
    assert solve_next(client) == "p2"


def test_wrong_answer_steers_to_problems_that_practise_it(client):
    answer(client, "p2", "no")   # 2/5 vs 4/10: "they look different, so no"
    answer(client, "p2", "no")   # second try, also wrong
    p = next_problem(client)
    assert p["id"] == "p7"       # Is 3/4 equivalent to 9/12? -- same misconception
    assert p["focus"] == "equivalent can look different"


def test_focus_clears_after_a_right_first_try_on_a_problem_that_practises_it(client):
    answer(client, "p2", "no")
    answer(client, "p2", "no")
    answer(client, "p7", "yes")  # practised it, right first time
    p = next_problem(client)
    assert p["focus"] is None
    assert p["id"] == "p1"       # back to normal order: least practised first


def test_focus_survives_a_right_answer_that_needed_the_retry(client):
    answer(client, "p1", "11/12")           # adding
    answer(client, "p1", "8/12")            # right, but on the second try
    assert next_problem(client)["focus"] == "multiply, don't add"


def test_focus_dropped_when_nothing_unsolved_practises_it(client):
    answer(client, "p7", "yes")
    answer(client, "p11", "yes")
    answer(client, "p2", "no")
    answer(client, "p2", "no")   # same_looking, but p7 and p11 are already solved
    p = next_problem(client)
    assert p["focus"] is None
    assert p["id"] == "p1"


def test_missed_problems_come_back_after_unseen_ones():
    s = state.get_state("x")
    progress = concept_progress(s, CONCEPT)
    for pid in ANSWERS:
        progress["problems"][pid] = {"seen": 1, "correct": 1, "last_correct": True}
    progress["problems"]["p9"] = {"seen": 1, "correct": 0, "last_correct": False}
    s["attempts"] = [{"concept": CONCEPT, "problem_id": "p3", "try": 1, "correct": True}]
    problem, try_number, focus = pick_next(FACTS, s)
    assert (problem["id"], try_number, focus) == ("p9", 1, None)


def wrong_answer_for(problem):
    if problem["answer_format"] == "yes_no":
        return "no" if ANSWERS[problem["id"]] == "yes" else "yes"
    return "1/1000"


def test_streak_and_mastery(client):
    for _ in range(STREAK_GOAL - 1):
        solve_next(client)
    pid = next_problem(client)["id"]
    body = answer(client, pid, ANSWERS[pid])
    assert body["progress"]["streak"] == STREAK_GOAL
    assert body["progress"]["mastered"] is True
    assert body["just_mastered"] is True

    # Mastery is kept; a wrong first try resets the streak; no second celebration
    p = next_problem(client)
    body = answer(client, p["id"], wrong_answer_for(p))
    assert body["progress"]["streak"] == 0
    assert body["progress"]["mastered"] is True
    assert body["just_mastered"] is False


def test_solved_and_mistake_counts_build_up(client):
    answer(client, "p1", "11/12")     # adding
    answer(client, "p1", "8/12")      # right on second try: counts as solved
    answer(client, "p3", "19/20")     # adding again
    answer(client, "p3", "3/20")      # changed one part
    progress = state.get_state("sam")["progress"][CONCEPT]
    assert progress["solved"] == 1
    assert progress["misconceptions"] == {"adding": 2, "one_part_only": 1}
    assert progress["problems"]["p1"] == {"seen": 1, "correct": 1, "last_correct": True}
    assert progress["problems"]["p3"] == {"seen": 1, "correct": 0, "last_correct": False}


def test_each_student_has_their_own_progress(make_client):
    sam, alex = make_client("sam"), make_client("alex")
    solve_next(sam)
    solve_next(sam)
    assert next_problem(sam)["progress"]["solved"] == 2
    assert next_problem(alex)["progress"]["solved"] == 0
    assert next_problem(alex)["id"] == "p1"
