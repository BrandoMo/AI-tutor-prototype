import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import auth, db

CONCEPT = "equivalent_fractions"


def anonymous():
    return TestClient(main.app)


def test_register_signs_you_in():
    c = anonymous()
    r = c.post("/register", json={"username": "  Sam_1 ", "password": "correct horse"})
    assert r.status_code == 200
    assert r.json() == {"username": "sam_1"}  # trimmed and lowercased
    assert c.get("/me").json() == {"username": "sam_1"}


def test_password_is_hashed_not_stored():
    anonymous().post("/register", json={"username": "sam", "password": "correct horse"})
    stored = db.redis.get("user:sam")
    assert "correct horse" not in stored
    assert '"password_hash": "scrypt$' in stored


def test_session_cookie_is_httponly_and_lax():
    r = anonymous().post("/register", json={"username": "sam", "password": "correct horse"})
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("session=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=2592000" in cookie  # 30 days


def test_session_token_is_stored_hashed():
    c = anonymous()
    c.post("/register", json={"username": "sam", "password": "correct horse"})
    token = c.cookies["session"]
    assert not any(token in key for key in db.redis.store)
    session_keys = [k for k in db.redis.store if k.startswith("session:")]
    assert len(session_keys) == 1
    assert db.redis.ttls[session_keys[0]] == 30 * 86400


@pytest.mark.parametrize("username", ["ab", "a" * 21, "sam smith", "sam!", "", "../x"])
def test_register_rejects_bad_usernames(username):
    r = anonymous().post("/register", json={"username": username, "password": "correct horse"})
    assert r.status_code == 400
    assert "3-20" in r.json()["detail"]


def test_register_rejects_short_password():
    r = anonymous().post("/register", json={"username": "sam", "password": "short"})
    assert r.status_code == 400
    assert "at least 8" in r.json()["detail"]


def test_register_rejects_overlong_input():
    r = anonymous().post("/register", json={"username": "sam", "password": "x" * 201})
    assert r.status_code == 422


def test_username_taken_regardless_of_case(make_client):
    make_client("sam")
    r = anonymous().post("/register", json={"username": "SAM", "password": "another one"})
    assert r.status_code == 409


def test_login_and_logout(make_client):
    make_client("sam", "correct horse")
    c = anonymous()
    assert c.get("/me").status_code == 401
    r = c.post("/login", json={"username": "Sam", "password": "correct horse"})
    assert r.status_code == 200
    assert c.get("/me").json() == {"username": "sam"}

    token = c.cookies["session"]
    assert c.post("/logout").status_code == 200
    assert c.get("/me").status_code == 401
    # The old token is dead server-side too, not just deleted from the browser
    c.cookies.set("session", token)
    assert c.get("/me").status_code == 401


@pytest.mark.parametrize("username,password", [("sam", "wrong password"), ("nobody", "correct horse")])
def test_wrong_credentials_get_the_same_answer(make_client, username, password):
    make_client("sam", "correct horse")
    r = anonymous().post("/login", json={"username": username, "password": password})
    assert r.status_code == 401
    assert r.json()["detail"] == "Wrong username or password."


def test_repeated_failures_lock_the_account_for_a_while(make_client):
    make_client("sam", "correct horse")
    c = anonymous()
    for _ in range(auth.MAX_FAILED_LOGINS):
        assert c.post("/login", json={"username": "sam", "password": "nope nope"}).status_code == 401
    assert db.redis.ttls["login_failures:sam"] == auth.LOCKOUT_MINUTES * 60
    # Locked: even the right password is refused until the lock expires
    r = c.post("/login", json={"username": "sam", "password": "correct horse"})
    assert r.status_code == 429


def test_successful_login_resets_failure_count(make_client):
    make_client("sam", "correct horse")
    c = anonymous()
    c.post("/login", json={"username": "sam", "password": "nope nope"})
    c.post("/login", json={"username": "sam", "password": "correct horse"})
    assert db.redis.get("login_failures:sam") is None


def test_corrupt_password_hash_fails_closed():
    assert auth.verify_password("anything", "not-a-real-hash") is False


@pytest.mark.parametrize("method,path,body", [
    ("get", f"/problem?concept={CONCEPT}", None),
    ("post", "/answer", {"concept": CONCEPT, "problem_id": "p1", "answer": "8/12"}),
    ("post", "/ask", {"concept": CONCEPT, "question": "hi"}),
])
def test_tutoring_needs_a_signed_in_student(method, path, body):
    c = anonymous()
    r = c.get(path) if method == "get" else c.post(path, json=body)
    assert r.status_code == 401
    c.cookies.set("session", "made-up-token")
    r = c.get(path) if method == "get" else c.post(path, json=body)
    assert r.status_code == 401


def test_request_body_cannot_pick_another_student(make_client):
    sam, alex = make_client("sam"), make_client("alex")
    # An old-style student_id in the body is ignored; the session decides
    r = alex.post("/answer", json={"concept": CONCEPT, "problem_id": "p1", "answer": "11/12", "student_id": "sam"})
    assert r.status_code == 200
    assert db.redis.get("student:sam") is None
    assert sam.get("/problem", params={"concept": CONCEPT}).json()["try"] == 1
    assert alex.get("/problem", params={"concept": CONCEPT}).json()["try"] == 2
