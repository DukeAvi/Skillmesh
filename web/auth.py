"""Password policy, login, one-time setup, sessions, and rate limiting."""

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import defaultdict
from scripts.config import pg_connect
from web.db import query
from web.errors import APIError

SESSION_TTL = 86400  # 24 hours

# Rate limiting: max attempts per window
RATE_LIMIT_WINDOW = 900  # 15 minutes
RATE_LIMIT_MAX = 5  # 5 attempts per window per email


SESSIONS: dict[str, dict] = {}
SESSION_LOCK = threading.Lock()


def _create_session(user: dict) -> tuple[str, str]:
    """Create a session for the user; return (token, csrf_token)."""
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    with SESSION_LOCK:
        SESSIONS[token] = {
            "user": user,
            "csrf": csrf_token,
            "expires": time.time() + SESSION_TTL,
        }
    return token, csrf_token


def _get_session(token: str) -> dict | None:
    """Return session dict or None if expired/missing."""
    with SESSION_LOCK:
        item = SESSIONS.get(token)
        if item and item["expires"] > time.time():
            return item
        SESSIONS.pop(token, None)
    return None


def _destroy_session(token: str) -> None:
    with SESSION_LOCK:
        SESSIONS.pop(token, None)


_rate_lock = threading.Lock()
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(email: str) -> bool:
    """Return True if the email is within rate limits, False if blocked."""
    now = time.time()
    key = email.lower().strip()
    with _rate_lock:
        bucket = _rate_buckets[key]
        _rate_buckets[key] = [t for t in bucket if t > now - RATE_LIMIT_WINDOW]
        if len(_rate_buckets[key]) >= RATE_LIMIT_MAX:
            return False
        _rate_buckets[key].append(now)
    return True


_HASH_ALGORITHM = "pbkdf2_sha256"
_HASH_ROUNDS = 600_000


def password_hash(password: str) -> str:
    """Hash a password with a random 16-byte salt."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _HASH_ROUNDS
    )
    return f"{_HASH_ALGORITHM}${_HASH_ROUNDS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time password verification."""
    try:
        algorithm, rounds, salt, digest = stored.split("$")
        if algorithm != _HASH_ALGORITHM or int(rounds) != _HASH_ROUNDS:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(rounds)
        )
        return hmac.compare_digest(actual.hex(), digest)
    except (ValueError, TypeError):
        return False


def _validate_password_strength(password: str) -> str | None:
    """Return an error message if the password is too weak, else None."""
    if len(password) < 8 or len(password) > 256:
        return "Password must be 8–256 characters"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter"
    if not re.search(r"\d", password):
        return "Password must contain at least one digit"
    return None


def setup_moderator(payload):
    if not _check_rate_limit("__moderator_setup__"):
        raise APIError("Too many setup attempts. Try again later.", 429)
    configured = os.getenv("SKILLMESH_SETUP_CODE", "")
    supplied = str(payload.get("code", ""))
    if len(configured) < 16 or not hmac.compare_digest(
        configured.encode(), supplied.encode()
    ):
        raise APIError("Invalid or unavailable setup code", 403)
    password = str(payload.get("password", ""))
    error = _validate_password_strength(password)
    if error:
        raise APIError(error, 400)
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                    UPDATE users
                    SET password_hash = %s
                    WHERE lower(email) = %s
                    AND password_hash = %s
                    RETURNING user_id
                """,
                (password_hash(password), "arjun@campus.edu", "placeholder-hash-arjun"),
            )
            row = cur.fetchone()
    if not row:
        raise APIError("Moderator account is already activated or missing", 409)
    return {"ok": True}


def login(payload):
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    if not email or "@" not in email:
        raise APIError("Enter a valid email", 400)
    if not password:
        raise APIError("Enter your password", 400)
    if not _check_rate_limit(email):
        raise APIError("Too many login attempts. Try again in 15 minutes.", 429)
    rows = query(
        """
            SELECT user_id, name, email, role, password_hash, (banned_at IS NOT NULL) AS banned
            FROM users
            WHERE lower(email) = %s
        """,
        (email,),
    )
    if not rows or not verify_password(password, rows[0]["password_hash"]):
        raise APIError("Invalid email or password", 401)
    if rows[0]["banned"]:
        raise APIError("This account has been banned", 403)
    user = {
        "user_id": rows[0]["user_id"],
        "name": rows[0]["name"],
        "email": rows[0]["email"],
        "role": rows[0]["role"],
    }
    return user


def register(payload):
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    name = str(payload.get("name", "")).strip()
    if not name or len(name) > 100:
        raise APIError("Enter a name (up to 100 characters)", 400)
    if not email or "@" not in email or len(email) > 254:
        raise APIError("Enter a valid email address", 400)
    pw_error = _validate_password_strength(password)
    if pw_error:
        raise APIError(pw_error, 400)
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                    INSERT INTO users (name, email, password_hash)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                    RETURNING user_id, name, email
                """,
                (name, email, password_hash(password)),
            )
            row = cur.fetchone()
            if not row:
                raise APIError("An account with that email already exists", 409)
    user = dict(zip(("user_id", "name", "email"), row))
    user["role"] = "student"
    return user
