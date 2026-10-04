"""
Student accounts and sessions, stored in Redis.

  user:<username>              -> {"password_hash", "created_at"}
  session:<sha256 of token>    -> username, expires after SESSION_DAYS
  login_failures:<username>    -> failed sign-in count, expires after LOCKOUT_MINUTES

Passwords are hashed with scrypt (Python standard library) and never
stored. The browser only holds a random session token in an HttpOnly
cookie, so page scripts can't read it, and the server -- not the
browser -- decides which student is making each request. Only a hash of
the token is stored, so a leaked database doesn't leak live sessions.
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
MIN_PASSWORD_LENGTH = 8
MAX_FAILED_LOGINS = 10
LOCKOUT_MINUTES = 15
USERNAME_RE = re.compile(r"[a-z0-9_]{3,20}")
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1

# Set COOKIE_SECURE=true when serving over HTTPS so the cookie is never
# sent over plain HTTP. Off by default so http://127.0.0.1 works locally.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes")


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


def normalize_username(username: str) -> str | None:
    """Lowercased username if it's valid, else None."""
    name = username.strip().lower()
    return name if USERNAME_RE.fullmatch(name) else None


def register(username: str, password: str) -> str:
    name = normalize_username(username)
    if name is None:
        raise HTTPException(status_code=400, detail="Usernames are 3-20 letters, numbers or underscores.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400,
                            detail=f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")

    record = json.dumps({"password_hash": hash_password(password), "created_at": int(time.time())})
    # nx=True: only create the key if it doesn't exist, so two people can't
    # grab the same name at the same moment
    if not redis.set(f"user:{name}", record, nx=True):
        raise HTTPException(status_code=409, detail="That username is taken.")
    return name


def login(username: str, password: str) -> str:
    name = normalize_username(username) or ""
    failures_key = f"login_failures:{name}"
    failures = redis.get(failures_key)
    if failures is not None and int(failures) >= MAX_FAILED_LOGINS:
        raise HTTPException(status_code=429,
                            detail=f"Too many failed attempts. Try again in {LOCKOUT_MINUTES} minutes.")

    raw = redis.get(f"user:{name}") if name else None
    stored = json.loads(raw)["password_hash"] if raw else _DUMMY_HASH
    if not verify_password(password, stored) or raw is None:
        if name and redis.incr(failures_key) == 1:
            redis.expire(failures_key, LOCKOUT_MINUTES * 60)
        raise HTTPException(status_code=401, detail="Wrong username or password.")

    redis.delete(failures_key)
    return name


def _session_key(token: str) -> str:
    return "session:" + hashlib.sha256(token.encode()).hexdigest()


def start_session(response: Response, username: str) -> None:
    token = secrets.token_urlsafe(32)
    redis.set(_session_key(token), username, ex=SESSION_DAYS * 86400)
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,    # page scripts can't read it
        samesite="lax",   # not sent on cross-site POSTs, which blocks CSRF
        secure=COOKIE_SECURE,
        path="/",
    )


def end_session(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        redis.delete(_session_key(token))
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_student(request: Request) -> str:
    """FastAPI dependency: the signed-in student's username, or a 401."""
    token = request.cookies.get(SESSION_COOKIE)
    username = redis.get(_session_key(token)) if token else None
    if not username:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return username
