import json
import re

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import auth, db

CONCEPT = "equivalent_fractions"
TEACHER_CODE = "let-teachers-in"


@pytest.fixture(autouse=True)
def teacher_signup_on(monkeypatch):
    monkeypatch.setattr(auth, "TEACHER_SIGNUP_CODE", TEACHER_CODE)


def anonymous():
    return TestClient(main.app)


@pytest.fixture
def make_teacher():
    def make(username="ms_lee", password="teacher password"):
        c = anonymous()
        r = c.post("/register", json={"username": username, "password": password, "teacher_code": TEACHER_CODE})
        assert r.status_code == 200, r.text
        return c
    return make


@pytest.fixture
def teacher(make_teacher):
    return make_teacher()


def new_class(teacher_client, name="Year 5 Maths"):
    r = teacher_client.post("/classes", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["code"]


def answer(client, problem_id, given):
    return client.post("/answer", json={"concept": CONCEPT, "problem_id": problem_id, "answer": given})


# --- Who can be a teacher ---

def test_teacher_signup_with_the_right_code(teacher):
    assert teacher.get("/me").json() == {"username": "ms_lee", "role": "teacher", "class": None}


def test_wrong_teacher_code_is_refused():
    r = anonymous().post("/register", json={"username": "sneaky", "password": "password1", "teacher_code": "guess"})
    assert r.status_code == 403
    assert db.redis.get("user:sneaky") is None


def test_teacher_signup_off_when_no_code_is_set(monkeypatch):
    monkeypatch.setattr(auth, "TEACHER_SIGNUP_CODE", "")
    r = anonymous().post("/register", json={"username": "sneaky", "password": "password1", "teacher_code": "x"})
    assert r.status_code == 403
    assert "isn't turned on" in r.json()["detail"]


def test_accounts_from_before_roles_are_students():
    db.redis.set("user:old", json.dumps({"password_hash": auth.hash_password("old password"), "created_at": 1}))
    c = anonymous()
    assert c.post("/login", json={"username": "old", "password": "old password"}).status_code == 200
    assert c.get("/me").json() == {"username": "old", "role": "student", "class": None}


@pytest.mark.parametrize("method,path", [
    ("get", "/classes"), ("post", "/classes"), ("get", "/classes/ABC-DEF"),
    ("post", "/classes/ABC-DEF/students/sam/reset-code"), ("post", "/classes/ABC-DEF/students/sam/unlock"),
    ("delete", "/classes/ABC-DEF/students/sam"),
])
def test_teacher_endpoints_refuse_students_and_strangers(client, method, path):
    body = {"json": {"name": "x"}} if method == "post" else {}
    assert getattr(client, method)(path, **body).status_code == 403
    assert getattr(anonymous(), method)(path, **body).status_code == 401


# --- Classes ---

def test_create_and_list_classes(teacher):
    code = new_class(teacher, "  Year 5 Maths ")
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{3}-[A-HJ-NP-Z2-9]{3}", code)
    new_class(teacher, "Art club")
    assert teacher.get("/classes").json() == {"classes": [
        {"code": teacher.get("/classes").json()["classes"][0]["code"], "name": "Art club", "students": 0},
        {"code": code, "name": "Year 5 Maths", "students": 0},
    ]}


@pytest.mark.parametrize("name", ["", "   ", "x" * 41])
def test_class_names_are_checked(teacher, name):
    assert teacher.post("/classes", json={"name": name}).status_code == 400


def test_teachers_only_see_their_own_classes(make_teacher):
    lee, kim = make_teacher("ms_lee"), make_teacher("mr_kim")
    code = new_class(lee)
    assert kim.get("/classes").json() == {"classes": []}
    assert kim.get(f"/classes/{code}").status_code == 404
    assert kim.post(f"/classes/{code}/students/sam/reset-code").status_code == 404


def test_students_join_with_a_code(teacher, make_client):
    code = new_class(teacher)
    sam = make_client("sam")
    r = sam.post("/join", json={"code": code.lower().replace("-", " ")})  # forgiving about format
    assert r.status_code == 200
    assert r.json() == {"class": {"code": code, "name": "Year 5 Maths"}}
    assert sam.get("/me").json()["class"] == {"code": code, "name": "Year 5 Maths"}
    assert teacher.get("/classes").json()["classes"][0]["students"] == 1


def test_wrong_join_code(client):
    r = client.post("/join", json={"code": "ZZZ-ZZZ"})
    assert r.status_code == 404
    assert "No class has that code" in r.json()["detail"]


def test_joining_another_class_moves_the_student(teacher, make_client):
    first, second = new_class(teacher, "A"), new_class(teacher, "B")
    sam = make_client("sam")
    sam.post("/join", json={"code": first})
    sam.post("/join", json={"code": second})
    counts = {c["name"]: c["students"] for c in teacher.get("/classes").json()["classes"]}
    assert counts == {"A": 0, "B": 1}


def test_teachers_cannot_join_as_students(make_teacher):
    lee, kim = make_teacher("ms_lee"), make_teacher("mr_kim")
    assert kim.post("/join", json={"code": new_class(lee)}).status_code == 403


def test_teacher_removes_a_student(teacher, make_client):
    code = new_class(teacher)
    sam = make_client("sam")
    sam.post("/join", json={"code": code})
    assert teacher.delete(f"/classes/{code}/students/sam").status_code == 200
    assert teacher.get(f"/classes/{code}").json()["students"] == []
    assert sam.get("/me").json()["class"] is None
    assert teacher.delete(f"/classes/{code}/students/sam").status_code == 404


# --- Dashboard ---

def test_dashboard_shows_each_student_and_the_class_summary(teacher, make_client):
    code = new_class(teacher)
    sam, alex, jo = make_client("sam"), make_client("alex"), make_client("jody")
    for s in (sam, alex, jo):
        s.post("/join", json={"code": code})

    answer(sam, "p1", "11/12")    # adding
    answer(sam, "p1", "8/12")
    answer(alex, "p1", "11/12")   # adding
    answer(alex, "p1", "2/12")    # changed one part
    answer(alex, "p3", "19/20")   # adding again
    # jody hasn't practised

    r = teacher.get(f"/classes/{code}")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == code and body["name"] == "Year 5 Maths"

    rows = {row["username"]: row for row in body["students"]}
    assert list(rows) == ["alex", "jody", "sam"]  # alphabetical
    assert rows["sam"]["solved"] == 1
    assert rows["sam"]["top_mistake"] == "multiply, don't add"
    assert rows["alex"]["top_mistake"] == "multiply, don't add"  # 2x adding beats 1x one part
    assert rows["alex"]["focus"] == "multiply, don't add"
    assert rows["jody"] == {"username": "jody", "solved": 0, "streak": 0, "mastered": False,
                          "top_mistake": None, "focus": None, "last_active": None, "locked": False}
    assert rows["sam"]["last_active"] is not None

    assert body["summary"] == {
        "students": 3,
        "mastered": 0,
        "practising": 2,
        "mistakes": [
            {"label": "multiply, don't add", "students": 2, "times": 3},
            {"label": "change both parts", "students": 1, "times": 1},
        ],
    }


def test_dashboard_for_an_empty_class(teacher):
    code = new_class(teacher)
    body = teacher.get(f"/classes/{code}").json()
    assert body["students"] == []
    assert body["summary"] == {"students": 0, "mastered": 0, "practising": 0, "mistakes": []}


# --- Password reset codes ---

@pytest.fixture
def class_with_sam(teacher, make_client):
    code = new_class(teacher)
    sam = make_client("sam", "old password")
    sam.post("/join", json={"code": code})
    return code, sam


def test_reset_code_flow(teacher, class_with_sam):
    code, sam = class_with_sam
    r = teacher.post(f"/classes/{code}/students/SAM/reset-code")
    assert r.status_code == 200
    reset = r.json()["code"]
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", reset)
    assert r.json()["expires_in_hours"] == 24
    assert db.redis.ttls["reset_code:sam"] == 24 * 3600
    assert reset.replace("-", "") not in json.dumps(db.redis.store, default=list)  # only a hash is stored

    browser = anonymous()
    r = browser.post("/reset-password", json={"username": "sam", "code": reset.lower(), "new_password": "new password"})
    assert r.status_code == 200
    assert browser.get("/me").json()["username"] == "sam"  # signed straight in

    # Old password no longer works, the new one does, and the code was single-use
    assert anonymous().post("/login", json={"username": "sam", "password": "old password"}).status_code == 401
    assert anonymous().post("/login", json={"username": "sam", "password": "new password"}).status_code == 200
    r = anonymous().post("/reset-password", json={"username": "sam", "code": reset, "new_password": "another one"})
    assert r.status_code == 400


def test_resetting_signs_out_everywhere_else(teacher, class_with_sam):
    code, sam = class_with_sam
    assert sam.get("/me").status_code == 200
    reset = teacher.post(f"/classes/{code}/students/sam/reset-code").json()["code"]
    anonymous().post("/reset-password", json={"username": "sam", "code": reset, "new_password": "new password"})
    assert sam.get("/me").status_code == 401


def test_new_reset_code_replaces_the_old_one(teacher, class_with_sam):
    code, _ = class_with_sam
    first = teacher.post(f"/classes/{code}/students/sam/reset-code").json()["code"]
    second = teacher.post(f"/classes/{code}/students/sam/reset-code").json()["code"]
    r = anonymous().post("/reset-password", json={"username": "sam", "code": first, "new_password": "new password"})
    assert r.status_code == 400
    r = anonymous().post("/reset-password", json={"username": "sam", "code": second, "new_password": "new password"})
    assert r.status_code == 200


def test_wrong_reset_codes_are_limited(teacher, class_with_sam):
    code, _ = class_with_sam
    reset = teacher.post(f"/classes/{code}/students/sam/reset-code").json()["code"]
    c = anonymous()
    for _ in range(auth.MAX_FAILED_LOGINS):
        r = c.post("/reset-password", json={"username": "sam", "code": "AAAA-AAAA", "new_password": "new password"})
        assert r.status_code == 400
    r = c.post("/reset-password", json={"username": "sam", "code": reset, "new_password": "new password"})
    assert r.status_code == 429
    # A fresh code from the teacher clears the limit
    reset = teacher.post(f"/classes/{code}/students/sam/reset-code").json()["code"]
    r = c.post("/reset-password", json={"username": "sam", "code": reset, "new_password": "new password"})
    assert r.status_code == 200


def test_reset_needs_a_long_enough_password(teacher, class_with_sam):
    code, _ = class_with_sam
    reset = teacher.post(f"/classes/{code}/students/sam/reset-code").json()["code"]
    r = anonymous().post("/reset-password", json={"username": "sam", "code": reset, "new_password": "short"})
    assert r.status_code == 400
    assert "at least 8" in r.json()["detail"]


def test_reset_codes_only_for_students_in_your_class(teacher, make_client):
    code = new_class(teacher)
    make_client("alex")  # exists, but not in this class
    assert teacher.post(f"/classes/{code}/students/alex/reset-code").status_code == 404
    assert teacher.post(f"/classes/{code}/students/nobody/reset-code").status_code == 404


def test_reset_with_no_code_issued(client):
    r = anonymous().post("/reset-password", json={"username": "sam", "code": "AAAA-AAAA", "new_password": "new password"})
    assert r.status_code == 400


# --- Lockout: trusted devices and teacher unlock ---

def fail_logins(c, username="sam", times=auth.MAX_FAILED_LOGINS):
    for _ in range(times):
        assert c.post("/login", json={"username": username, "password": "wrong guess"}).status_code == 401


def test_lockout_does_not_lock_out_your_own_device(make_client):
    sam = make_client("sam", "sams password")  # signing up trusts this browser
    sam.post("/logout")
    attacker = anonymous()
    fail_logins(attacker)
    assert attacker.post("/login", json={"username": "sam", "password": "sams password"}).status_code == 429
    # Sam's own browser still gets in
    assert sam.post("/login", json={"username": "sam", "password": "sams password"}).status_code == 200


def test_device_cookie_is_httponly_and_only_sent_to_login():
    r = anonymous().post("/register", json={"username": "sam", "password": "sams password"})
    device = [h for h in r.headers.get_list("set-cookie") if h.startswith("device_sam=")]
    assert len(device) == 1
    assert "httponly" in device[0].lower()
    assert "path=/login" in device[0].lower()


def test_too_many_failures_on_a_trusted_device_stops_trusting_it(make_client):
    sam = make_client("sam", "sams password")
    sam.post("/logout")
    fail_logins(sam)
    assert sam.post("/login", json={"username": "sam", "password": "sams password"}).status_code == 429
    # Now it's just an unknown browser, subject to the username's own count
    assert sam.post("/login", json={"username": "sam", "password": "sams password"}).status_code == 200


def test_teacher_can_see_and_clear_a_lockout(teacher, class_with_sam):
    code, _ = class_with_sam
    other_device = anonymous()
    fail_logins(other_device)
    assert other_device.post("/login", json={"username": "sam", "password": "old password"}).status_code == 429
    rows = teacher.get(f"/classes/{code}").json()["students"]
    assert rows[0]["locked"] is True

    assert teacher.post(f"/classes/{code}/students/sam/unlock").status_code == 200
    assert teacher.get(f"/classes/{code}").json()["students"][0]["locked"] is False
    assert other_device.post("/login", json={"username": "sam", "password": "old password"}).status_code == 200
