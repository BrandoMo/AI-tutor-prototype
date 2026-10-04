"""
Accounts, sessions, trusted devices and password resets, stored in Redis.

  user:<username>              -> {"password_hash", "created_at", "role", "class"}
  session:<sha256 of token>    -> username, expires after SESSION_DAYS
  user_sessions:<username>     -> set of that user's session keys (to end them all)
  device:<sha256 of token>     -> username, expires after DEVICE_DAYS
  login_failures:<username>    -> failed sign-ins from unknown devices
  device_failures:<device key> -> failed sign-ins from one trusted device
  reset_code:<username>        -> sha256 of a one-time reset code, expires after RESET_HOURS
  reset_failures:<username>    -> wrong reset codes tried

Passwords are hashed with scrypt (Python standard library) and never
stored. The browser only holds random tokens in HttpOnly cookies, so page
scripts can't read them, and the server -- not the browser -- decides who
is making each request. Only hashes of tokens and codes are stored, so a
leaked database doesn't leak live sessions or reset codes.

Lockout uses trusted devices (OWASP's "device cookie" approach): signing
in successfully gives that browser a device cookie for that user. Too many
wrong passwords lock the username only for browsers WITHOUT the cookie, so
someone guessing elsewhere can't lock a student out of their own device.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import time

from fastapi import HTTPException, Request, Response

from app.db import redis

SESSION_COOKIE = "session"
SESSION_DAYS = 30
DEVICE_DAYS = 365
MIN_PASSWORD_LENGTH = 8
MAX_FAILED_LOGINS = 10
LOCKOUT_MINUTES = 15
RESET_HOURS = 24
USERNAME_RE = re.compile(r"[a-z0-9_]{3,20}")
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
# No 0/O, 1/I/L: easy to read aloud and copy from a screen
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# Set COOKIE_SECURE=true when serving over HTTPS so cookies are never
# sent over plain HTTP. Off by default so http://127.0.0.1 works locally.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes")
# Whoever knows this can sign up as a teacher. Unset = no teacher sign-up.
TEACHER_SIGNUP_CODE = os.environ.get("TEACHER_SIGNUP_CODE", "")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def random_code(length: int) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def normalize_code(code: str) -> str:
    """Uppercase, drop spaces/dashes: "abcd-efgh " -> "ABCDEFGH"."""
    return re.sub(r"[^A-Z0-9]", "", code.upper())


# --- Passwords ---

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=32)
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# Checked against when a username doesn't exist, so a wrong username takes
# as long as a wrong password and response times don't reveal which it was
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def check_password_length(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400,
                            detail=f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")


# --- Users ---

def normalize_username(username: str) -> str | None:
    """Lowercased username if it's valid, else None."""
    name = username.strip().lower()
    return name if USERNAME_RE.fullmatch(name) else None


def get_user(username: str) -> dict | None:
    raw = redis.get(f"user:{username}")
    if raw is None:
        return None
    user = json.loads(raw)
    user.setdefault("role", "student")  # accounts made before roles existed
    user.setdefault("class", None)
    return user


def save_user(username: str, user: dict) -> None:
    redis.set(f"user:{username}", json.dumps(user))


def register(username: str, password: str, teacher_code: str | None = None) -> str:
    name = normalize_username(username)
    if name is None:
        raise HTTPException(status_code=400, detail="Usernames are 3-20 letters, numbers or underscores.")
    check_password_length(password)

    role = "student"
    if teacher_code:
        if not TEACHER_SIGNUP_CODE:
            raise HTTPException(status_code=403, detail="Teacher sign-up isn't turned on for this site.")
        if not hmac.compare_digest(teacher_code.strip().encode(), TEACHER_SIGNUP_CODE.encode()):
            raise HTTPException(status_code=403, detail="That teacher sign-up code isn't right.")
        role = "teacher"

    record = json.dumps({
        "password_hash": hash_password(password),
        "created_at": int(time.time()),
        "role": role,
        "class": None,
    })
    # nx=True: only create the key if it doesn't exist, so two people can't
    # grab the same name at the same moment
    if not redis.set(f"user:{name}", record, nx=True):
        raise HTTPException(status_code=409, detail="That username is taken.")
    return name


# --- Signing in, with trusted-device lockout ---

def device_cookie_name(username: str) -> str:
    return f"device_{username}"  # usernames are [a-z0-9_], safe in cookie names


def _device_key(token: str) -> str:
    return "device:" + _sha256(token)


def is_locked(username: str) -> bool:
    """Locked for browsers that aren't a trusted device for this user."""
    failures = redis.get(f"login_failures:{username}")
    return failures is not None and int(failures) >= MAX_FAILED_LOGINS


def _count_failure(key: str) -> None:
    if redis.incr(key) == 1:
        redis.expire(key, LOCKOUT_MINUTES * 60)


def login(username: str, password: str, request: Request) -> str:
    name = normalize_username(username) or ""
    device_token = request.cookies.get(device_cookie_name(name)) if name else None
    device_key = _device_key(device_token) if device_token else None
    trusted = device_key is not None and redis.get(device_key) == name

    # A trusted device has its own failure count; everyone else shares the username's
    failures_key = f"device_failures:{device_key}" if trusted else f"login_failures:{name}"
    failures = redis.get(failures_key)
    if failures is not None and int(failures) >= MAX_FAILED_LOGINS:
        if trusted:
            redis.delete(device_key, failures_key)  # stop trusting this browser
        raise HTTPException(status_code=429,
                            detail=f"Too many failed attempts. Try again in {LOCKOUT_MINUTES} minutes, "
                                   "or ask your teacher to unlock your account.")

    user = get_user(name) if name else None
    stored = user["password_hash"] if user else _DUMMY_HASH
    if not verify_password(password, stored) or user is None:
        if name:
            _count_failure(failures_key)
        raise HTTPException(status_code=401, detail="Wrong username or password.")

    redis.delete(failures_key)
    return name


def unlock(username: str) -> None:
    redis.delete(f"login_failures:{username}")


# --- Sessions ---

def _session_key(token: str) -> str:
    return "session:" + _sha256(token)


def _set_cookie(response: Response, name: str, value: str, days: int, path: str = "/") -> None:
    response.set_cookie(
        name, value,
        max_age=days * 86400,
        httponly=True,    # page scripts can't read it
        samesite="lax",   # not sent on cross-site POSTs, which blocks CSRF
        secure=COOKIE_SECURE,
        path=path,
    )


def start_session(response: Response, username: str, old_device_token: str | None = None) -> None:
    token = secrets.token_urlsafe(32)
    key = _session_key(token)
    redis.set(key, username, ex=SESSION_DAYS * 86400)
    redis.sadd(f"user_sessions:{username}", key)
    _set_cookie(response, SESSION_COOKIE, token, SESSION_DAYS)

    # (Re)issue this browser's trusted-device cookie for this user. It's only
    # ever needed when signing in, so it's only sent to /login.
    if old_device_token:
        redis.delete(_device_key(old_device_token))
    device_token = secrets.token_urlsafe(32)
    redis.set(_device_key(device_token), username, ex=DEVICE_DAYS * 86400)
    _set_cookie(response, device_cookie_name(username), device_token, DEVICE_DAYS, path="/login")


def end_session(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        key = _session_key(token)
        username = redis.get(key)
        redis.delete(key)
        if username:
            redis.srem(f"user_sessions:{username}", key)
    response.delete_cookie(SESSION_COOKIE, path="/")


def end_all_sessions(username: str) -> None:
    keys = redis.smembers(f"user_sessions:{username}") or []
    if keys:
        redis.delete(*keys)
    redis.delete(f"user_sessions:{username}")


def current_student(request: Request) -> str:
    """FastAPI dependency: the signed-in user's username (any role), or a 401."""
    token = request.cookies.get(SESSION_COOKIE)
    username = redis.get(_session_key(token)) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return username


def current_user(request: Request) -> dict:
    """FastAPI dependency: {"username", "role", "class"} for the signed-in user."""
    username = current_student(request)
    user = get_user(username)
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return {"username": username, "role": user["role"], "class": user["class"]}


def require_teacher(request: Request) -> dict:
    """FastAPI dependency: the signed-in user if they're a teacher, else 403."""
    user = current_user(request)
    if user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Only teachers can do that.")
    return user


# --- Password reset codes (issued by a teacher) ---

def issue_reset_code(username: str) -> str:
    """A new one-time code like "K7QX-3MPA". Replaces any earlier code."""
    code = random_code(8)
    redis.set(f"reset_code:{username}", _sha256(code), ex=RESET_HOURS * 3600)
    redis.delete(f"reset_failures:{username}")
    return f"{code[:4]}-{code[4:]}"


def reset_password(username: str, code: str, new_password: str) -> str:
    check_password_length(new_password)
    wrong = HTTPException(status_code=400, detail="That reset code isn't right. Check it with your teacher.")
    name = normalize_username(username)
    if name is None:
        raise wrong

    failures_key = f"reset_failures:{name}"
    failures = redis.get(failures_key)
    if failures is not None and int(failures) >= MAX_FAILED_LOGINS:
        raise HTTPException(status_code=429, detail="Too many wrong codes. Ask your teacher for a new one.")

    stored = redis.get(f"reset_code:{name}")
    user = get_user(name)
    if not stored or user is None or not hmac.compare_digest(_sha256(normalize_code(code)), stored):
        _count_failure(failures_key)
        raise wrong

    user["password_hash"] = hash_password(new_password)
    save_user(name, user)
    redis.delete(f"reset_code:{name}", failures_key, f"login_failures:{name}")
    end_all_sessions(name)  # anyone signed in with the old password is signed out
    return name
