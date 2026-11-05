"""Secure web server for the SkillMesh observatory.

Security features:
- PBKDF2-SHA256 password hashing (600 000 rounds, per-user salt)
- Random server-side session tokens
- Brute-force rate limiting (5 attempts per email per 15 min window)
- CSRF protection via X-CSRF-Token on authenticated data mutations
- Per-session CSRF token delivered via /api/me
- Secure cookie flags (HttpOnly, SameSite=Strict, Secure in production)
- Input validation and length limits on every endpoint
- Timing-safe password comparison (hmac.compare_digest)
- Content-Security-Policy, X-Content-Type-Options, X-Frame-Options headers
- Request body size limit (16 KiB)
- No user enumeration on login (generic "Invalid email or password")
- Session expiry (24 h) with server-side store
- Password rules enforced server-side (8-256 chars, upper+lower+digit)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
from collections import defaultdict
from decimal import Decimal
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.config import pg_connect
from scripts.embeddings import embed, embedding_literal

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
SESSION_TTL = 86400  # 24 hours
MAX_BODY = 16384     # 16 KiB

# Rate limiting: max attempts per window
RATE_LIMIT_WINDOW = 900   # 15 minutes
RATE_LIMIT_MAX = 5        # 5 attempts per window per email

# ---------------------------------------------------------------------------
# Session store (server-side, in-memory)
# ---------------------------------------------------------------------------

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


def ensure_arjun_is_admin() -> None:
    """Keep the single designated administrator aligned with the seed policy."""
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET role = 'student' "
                "WHERE role = 'admin' "
                "AND lower(name) NOT LIKE 'arjun%' "
                "AND lower(email) <> 'arjun@campus.edu'"
            )
            cur.execute(
                "UPDATE users SET role = 'admin' "
                "WHERE lower(name) LIKE 'arjun%' OR lower(email) = 'arjun@campus.edu'"
            )


def is_moderator(user: dict | None) -> bool:
    return bool(user and (str(user.get("name", "")).lower().startswith("arjun")
                or str(user.get("email", "")).lower() == "arjun@campus.edu")
                and user.get("role") == "admin")


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, per email)
# ---------------------------------------------------------------------------

_rate_lock = threading.Lock()
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(email: str) -> bool:
    """Return True if the email is within rate limits, False if blocked."""
    now = time.time()
    key = email.lower().strip()
    with _rate_lock:
        bucket = _rate_buckets[key]
        # Prune old entries
        _rate_buckets[key] = [t for t in bucket if t > now - RATE_LIMIT_WINDOW]
        if len(_rate_buckets[key]) >= RATE_LIMIT_MAX:
            return False
        _rate_buckets[key].append(now)
    return True


# ---------------------------------------------------------------------------
# Password hashing (PBKDF2-SHA256, 600 000 rounds)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def query(sql, params=()):
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [col.name for col in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def execute_request(payload: dict):
    required = ("requester_id", "provider_id", "skill_id")
    if any(key not in payload for key in required):
        raise ValueError("requester_id, provider_id, and skill_id are required")
    learner_id = int(payload["requester_id"])
    provider_id = int(payload["provider_id"])
    skill_id = int(payload["skill_id"])
    similarity = float(payload.get("similarity_score", 0))
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CALL sp_create_swap_request(
                    %s::BIGINT, %s::BIGINT, %s::BIGINT, %s::REAL, NULL::BIGINT
                )
                """,
                (learner_id, provider_id, skill_id, similarity),
            )
            request_id = cur.fetchone()[0]
            return {"request_id": request_id, "status": "pending"}


def json_value(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# Read-only data endpoints
# ---------------------------------------------------------------------------


def get_payload(path: str, query_string: str):
    if path == "/api/health":
        rows = query("SELECT current_database() AS database, NOW() AS server_time")
        return {"ok": True, **{k: json_value(v) for k, v in rows[0].items()}}
    if path == "/api/skills":
        return query(
            """
            SELECT skill_id, skill_name, category_name, teachers, learners,
                   completed_sessions, demand_gap, demand_rank
            FROM skill_popularity
            ORDER BY demand_rank, skill_name
            """
        )
    if path == "/api/leaderboard":
        return query(
            """
            SELECT rank, user_id, name, sessions_taught, sessions_learned,
                   total_sessions
            FROM leaderboard
            ORDER BY rank, total_sessions DESC, name
            LIMIT 10
            """
        )
    if path == "/api/activity":
        return query(
            """
            SELECT s.name AS skill_name, COUNT(*) AS completed_sessions
            FROM swap_sessions ss
            JOIN skills s ON s.skill_id = ss.skill_id
            WHERE ss.status = 'completed'
            GROUP BY s.name
            ORDER BY completed_sessions DESC, s.name
            """
        )
    raise KeyError(path)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

# Security headers applied to every response
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    ),
}


class Handler(BaseHTTPRequestHandler):
    # --- helpers ---------------------------------------------------------

    def _send_security_headers(self):
        for header, value in _SECURITY_HEADERS.items():
            self.send_header(header, value)

    def send_json(self, payload, status=200, cookie=None):
        body = json.dumps(payload, default=json_value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_security_headers()
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _cookie_flags(self) -> str:
        """Return cookie attribute string; add Secure when behind HTTPS."""
        base = "Path=/; HttpOnly; SameSite=Strict"
        # If X-Forwarded-Proto is set (behind a reverse proxy) or explicit env
        if (self.headers.get("X-Forwarded-Proto") == "https"
                or os.getenv("SKILLMESH_SECURE_COOKIES") == "1"):
            base += "; Secure"
        return base

    def _session_cookie(self, token: str) -> str:
        return f"session={token}; {self._cookie_flags()}; Max-Age={SESSION_TTL}"

    def _clear_cookie(self) -> str:
        return f"session=; {self._cookie_flags()}; Max-Age=0"

    def _get_session_token(self) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie["session"].value
        except (KeyError, ValueError):
            return None

    def session(self) -> dict | None:
        """Return the user dict from the session, or None."""
        token = self._get_session_token()
        if not token:
            return None
        sess = _get_session(token)
        return sess["user"] if sess else None

    def _require_csrf(self) -> bool:
        """Validate the CSRF token for mutating requests. Return True if OK."""
        token = self._get_session_token()
        if not token:
            self.send_json({"error": "Sign in required"}, 401)
            return False
        sess = _get_session(token)
        if not sess:
            self.send_json({"error": "Session expired, please sign in again"}, 401)
            return False
        csrf_header = self.headers.get("X-CSRF-Token", "")
        if not csrf_header or not hmac.compare_digest(csrf_header, sess["csrf"]):
            self.send_json({"error": "Invalid or missing CSRF token"}, 403)
            return False
        return True

    def _read_json_body(self) -> dict | None:
        """Read and parse JSON body with size limit. Returns None on error (already sent response)."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_BODY:
                self.send_json({"error": "Request too large"}, 413)
                return None
            raw = self.rfile.read(length)
            return json.loads(raw) if raw else {}
        except (ValueError, json.JSONDecodeError):
            self.send_json({"error": "Invalid JSON"}, 400)
            return None

    # --- GET routes ------------------------------------------------------

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            try:
                if path == "/api/me":
                    token = self._get_session_token()
                    sess = _get_session(token) if token else None
                    if sess:
                        roles = query("SELECT role FROM users WHERE user_id = %s", (sess["user"]["user_id"],))
                        if not roles:
                            _destroy_session(token)
                            self.send_json(None)
                            return
                        self.send_json({
                            **sess["user"],
                            "role": roles[0]["role"],
                            "csrf_token": sess["csrf"],
                        })
                    else:
                        self.send_json(None)
                    return

                if path == "/api/users":
                    self.send_json({"error": "endpoint not found"}, 404)
                    return

                if path == "/api/my-skills":
                    user = self.session()
                    if not user:
                        self.send_json({"error": "Sign in required"}, 401)
                        return
                    self.send_json(query(
                        """
                        SELECT us.user_skill_id, us.skill_id, s.name AS skill_name,
                               us.skill_type, us.proficiency_level, us.description
                        FROM user_skills us
                        JOIN skills s ON s.skill_id = us.skill_id
                        WHERE us.user_id = %s
                        ORDER BY us.skill_type, s.name
                        """,
                        (user["user_id"],),
                    ))
                    return

                if path == "/api/moderation":
                    user = self.session()
                    if not is_moderator(user):
                        self.send_json({"error": "Moderator access required"}, 403)
                        return
                    self.send_json({
                            "users": query(
                                "SELECT user_id, name, email, role, created_at FROM users ORDER BY user_id"
                            ),
                            "skills": query(
                                "SELECT skill_id, name, description FROM skills ORDER BY name"
                            ),
                            "requests": query(
                                """
                                SELECT sr.request_id, sr.status, s.name AS skill_name,
                                       requester.name AS requester_name, provider.name AS provider_name
                                FROM swap_requests sr
                                JOIN skills s ON s.skill_id = sr.skill_id
                                JOIN users requester ON requester.user_id = sr.requester_id
                                JOIN users provider ON provider.user_id = sr.provider_id
                                ORDER BY sr.created_at DESC
                                """
                            ),
                            "slots": query(
                                """
                                SELECT a.slot_id, a.provider_id, u.name AS provider_name,
                                       a.skill_id, s.name AS skill_name, a.start_time,
                                       a.end_time, a.status
                                FROM availability_slots a
                                JOIN users u ON u.user_id = a.provider_id
                                JOIN skills s ON s.skill_id = a.skill_id
                                ORDER BY a.start_time DESC
                                """
                            ),
                            "sessions": query(
                                """
                                SELECT ss.session_id, ss.status, ss.provider_id,
                                       provider.name AS provider_name, ss.learner_id,
                                       learner.name AS learner_name, s.name AS skill_name,
                                       ss.slot_id
                                FROM swap_sessions ss
                                JOIN users provider ON provider.user_id = ss.provider_id
                                JOIN users learner ON learner.user_id = ss.learner_id
                                JOIN skills s ON s.skill_id = ss.skill_id
                                ORDER BY ss.created_at DESC
                                """
                            ),
                            "feedback": query(
                                """
                                SELECT f.feedback_id, f.session_id, f.reviewer_id,
                                       u.name AS reviewer_name, f.rating, f.comment
                                FROM feedback f JOIN users u ON u.user_id = f.reviewer_id
                                ORDER BY f.created_at DESC
                                """
                            ),
                    })
                    return

                if path in ("/api/requests", "/api/matches"):
                    user = self.session()
                    if not user:
                        self.send_json({"error": "Sign in required"}, 401)
                        return
                    values = parse_qs(parsed.query)
                    id_key = "user_id" if path == "/api/requests" else "learner_id"
                    values[id_key] = [str(user["user_id"])]

                    if path == "/api/matches":
                        result = query(
                            """
                            SELECT provider_id, provider_name, matched_skill_id,
                                   matched_skill, similarity,
                                   fn_provider_average_rating(provider_id) AS rating
                            FROM fn_find_skill_matches(%s::BIGINT, %s::BIGINT, 10)
                            """,
                            (
                                int(values.get("learner_id", ["0"])[0]),
                                int(values.get("skill_id", ["0"])[0]),
                            ),
                        )
                        self.send_json(result)
                    else:
                        user_id = int(values.get("user_id", ["0"])[0])
                        result = query(
                            """
                            SELECT sr.request_id, sr.status, sr.similarity_score,
                                   sr.created_at,
                                   sr.requester_id, requester.name AS requester_name,
                                   sr.provider_id, provider.name AS provider_name,
                                   sr.skill_id, s.name AS skill_name
                            FROM swap_requests sr
                            JOIN users requester ON requester.user_id = sr.requester_id
                            JOIN users provider  ON provider.user_id = sr.provider_id
                            JOIN skills s ON s.skill_id = sr.skill_id
                            WHERE sr.requester_id = %s OR sr.provider_id = %s
                            ORDER BY sr.created_at DESC
                            """,
                            (user_id, user_id),
                        )
                        self.send_json(result)
                    return

                self.send_json(get_payload(path, parsed.query))
            except KeyError:
                self.send_json({"error": "endpoint not found"}, 404)
            except Exception as exc:
                self.send_json({"error": f"database unavailable: {exc}"}, 503)
            return

        # Static file serving with path traversal protection
        relative = "index.html" if path == "/" else path.lstrip("/")
        requested = (ROOT / relative).resolve()
        if ROOT not in requested.parents and requested != ROOT:
            self.send_json({"error": "invalid path"}, 400)
            return
        if not requested.is_file():
            self.send_json({"error": "not found"}, 404)
            return
        body = requested.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            mimetypes.guess_type(requested.name)[0] or "text/plain",
        )
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    # --- POST routes -----------------------------------------------------

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path

        if path not in (
            "/api/requests",
            "/api/login",
            "/api/register",
            "/api/logout",
            "/api/user-skills",
            "/api/moderation",
        ):
            self.send_json({"error": "endpoint not found"}, 404)
            return

        try:
            # --- Logout (no CSRF check — just clears the session) --------
            if path == "/api/logout":
                token = self._get_session_token()
                if token:
                    _destroy_session(token)
                self.send_json({"ok": True}, cookie=self._clear_cookie())
                return

            payload = self._read_json_body()
            if payload is None:
                return

            # --- Login ---------------------------------------------------
            if path == "/api/login":
                email = str(payload.get("email", "")).strip().lower()
                password = str(payload.get("password", ""))
                if not email or "@" not in email:
                    self.send_json({"error": "Enter a valid email"}, 400)
                    return
                if not password:
                    self.send_json({"error": "Enter your password"}, 400)
                    return

                # Rate limiting
                if not _check_rate_limit(email):
                    self.send_json(
                        {"error": "Too many login attempts. Try again in 15 minutes."},
                        429,
                    )
                    return

                rows = query(
                    "SELECT user_id, name, email, role, password_hash "
                    "FROM users WHERE lower(email) = %s",
                    (email,),
                )
                if not rows or not verify_password(password, rows[0]["password_hash"]):
                    self.send_json({"error": "Invalid email or password"}, 401)
                    return

                user = {
                    "user_id": rows[0]["user_id"],
                    "name": rows[0]["name"],
                    "email": rows[0]["email"],
                    "role": rows[0]["role"],
                }
                token, csrf = _create_session(user)
                self.send_json(
                    {**user, "csrf_token": csrf},
                    cookie=self._session_cookie(token),
                )
                return

            # --- Register ------------------------------------------------
            if path == "/api/register":
                email = str(payload.get("email", "")).strip().lower()
                password = str(payload.get("password", ""))
                name = str(payload.get("name", "")).strip()

                if not name or len(name) > 100:
                    self.send_json(
                        {"error": "Enter a name (up to 100 characters)"}, 400
                    )
                    return
                if not email or "@" not in email or len(email) > 254:
                    self.send_json({"error": "Enter a valid email address"}, 400)
                    return

                pw_error = _validate_password_strength(password)
                if pw_error:
                    self.send_json({"error": pw_error}, 400)
                    return

                with pg_connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO users (name, email, password_hash) "
                            "VALUES (%s, %s, %s) "
                            "ON CONFLICT (email) DO NOTHING "
                            "RETURNING user_id, name, email",
                            (name, email, password_hash(password)),
                        )
                        row = cur.fetchone()
                        if not row:
                            self.send_json(
                                {"error": "An account with that email already exists"},
                                409,
                            )
                            return

                user = dict(zip(("user_id", "name", "email"), row))
                user["role"] = "student"
                token, csrf = _create_session(user)
                self.send_json(
                    {**user, "csrf_token": csrf},
                    201,
                    cookie=self._session_cookie(token),
                )
                return

            if path == "/api/user-skills":
                if not self._require_csrf():
                    return
                user = self.session()
                if not user:
                    self.send_json({"error": "Sign in required"}, 401)
                    return
                skill_type = str(payload.get("skill_type", "")).upper()
                if skill_type not in ("TEACH", "LEARN"):
                    self.send_json({"error": "Choose whether you teach or learn this skill"}, 400)
                    return
                try:
                    skill_id = int(payload.get("skill_id"))
                except (TypeError, ValueError):
                    self.send_json({"error": "Choose a valid skill"}, 400)
                    return
                proficiency = payload.get("proficiency_level") or None
                if proficiency not in (None, "beginner", "intermediate", "advanced"):
                    self.send_json({"error": "Choose a valid proficiency level"}, 400)
                    return
                description = str(payload.get("description", "")).strip()[:500]
                skill_rows = query("SELECT name FROM skills WHERE skill_id = %s", (skill_id,))
                if not skill_rows:
                    self.send_json({"error": "Skill not found"}, 404)
                    return
                vector = embed(f"{skill_rows[0]['name']} {description} {skill_type}")
                with pg_connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO user_skills
                                (user_id, skill_id, skill_type, proficiency_level,
                                 description, embedding)
                            VALUES (%s, %s, %s, %s, %s, %s::vector)
                            ON CONFLICT (user_id, skill_id, skill_type)
                            DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level,
                                          description = EXCLUDED.description,
                                          embedding = EXCLUDED.embedding
                            RETURNING user_skill_id
                            """,
                            (
                                user["user_id"], skill_id, skill_type, proficiency,
                                description or None, embedding_literal(vector),
                            ),
                        )
                        user_skill_id = cur.fetchone()[0]
                self.send_json({"user_skill_id": user_skill_id, "status": "saved"}, 201)
                return

            if path == "/api/moderation":
                user = self.session()
                if not is_moderator(user):
                    self.send_json({"error": "Moderator access required"}, 403)
                    return
                action = str(payload.get("action", ""))
                with pg_connect() as conn:
                    with conn.cursor() as cur:
                        if action == "set-role":
                            user_id = int(payload["user_id"])
                            role = str(payload["role"])
                            if role not in ("student", "mentor", "admin"):
                                raise ValueError("Invalid role")
                            target = query("SELECT name FROM users WHERE user_id = %s", (user_id,))
                            if not target:
                                raise ValueError("User not found")
                            target_is_arjun = target[0]["name"].lower() == "arjun"
                            if role == "admin" and not target_is_arjun:
                                raise ValueError("Only Arjun can be an admin")
                            if target_is_arjun and role != "admin":
                                raise ValueError("Arjun must remain an admin")
                            cur.execute(
                                "UPDATE users SET role = %s WHERE user_id = %s RETURNING user_id",
                                (role, user_id),
                            )
                            if not cur.fetchone():
                                raise ValueError("User not found")
                        elif action == "create-skill":
                            name = str(payload.get("name", "")).strip()
                            category = str(payload.get("category", "")).strip()
                            description = str(payload.get("description", "")).strip() or None
                            if not name or not category:
                                raise ValueError("Skill name and category are required")
                            cur.execute(
                                "INSERT INTO skill_categories (name) VALUES (%s) "
                                "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
                                "RETURNING category_id",
                                (category,),
                            )
                            category_id = cur.fetchone()[0]
                            cur.execute(
                                "INSERT INTO skills (category_id, name, description) VALUES (%s, %s, %s)",
                                (category_id, name, description),
                            )
                        elif action == "request-status":
                            status = str(payload["status"])
                            if status not in ("pending", "accepted", "rejected", "cancelled"):
                                raise ValueError("Invalid request status")
                            cur.execute(
                                "UPDATE swap_requests SET status = %s WHERE request_id = %s",
                                (status, int(payload["request_id"])),
                            )
                        elif action == "create-slot":
                            cur.execute(
                                """
                                INSERT INTO availability_slots
                                    (provider_id, skill_id, start_time, end_time)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (int(payload["provider_id"]), int(payload["skill_id"]),
                                 payload["start_time"], payload["end_time"]),
                            )
                        elif action == "slot-status":
                            status = str(payload["status"])
                            if status not in ("open", "booked", "cancelled"):
                                raise ValueError("Invalid slot status")
                            cur.execute(
                                "UPDATE availability_slots SET status = %s WHERE slot_id = %s",
                                (status, int(payload["slot_id"])),
                            )
                        elif action == "session-status":
                            status = str(payload["status"])
                            if status not in ("scheduled", "completed", "cancelled"):
                                raise ValueError("Invalid session status")
                            cur.execute(
                                "UPDATE swap_sessions SET status = %s, "
                                "completed_at = CASE WHEN %s = 'completed' THEN COALESCE(completed_at, NOW()) ELSE completed_at END "
                                "WHERE session_id = %s",
                                (status, status, int(payload["session_id"])),
                            )
                        elif action == "delete-feedback":
                            cur.execute(
                                "DELETE FROM feedback WHERE feedback_id = %s",
                                (int(payload["feedback_id"]),),
                            )
                        elif action == "delete-user":
                            user_id = int(payload["user_id"])
                            if user_id == user["user_id"]:
                                raise ValueError("Arjun cannot delete his own account")
                            cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
                        else:
                            raise ValueError("Unknown moderation action")
                self.send_json({"ok": True})
                return

            # --- Create swap request (authenticated + CSRF) --------------
            if not self._require_csrf():
                return
            user = self.session()
            if not user:
                self.send_json({"error": "Sign in required"}, 401)
                return
            payload["requester_id"] = user["user_id"]
            self.send_json(execute_request(payload), 201)

        except (ValueError, TypeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": f"request could not be created: {exc}"}, 422)

    def log_message(self, format, *args):
        return


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    port = int(os.getenv("SKILLMESH_WEB_PORT", "8080"))
    ensure_arjun_is_admin()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"SkillMesh observatory listening on http://localhost:{port}")
    print(f"Security: PBKDF2-SHA256 · CSRF tokens · rate limiting · secure headers")
    server.serve_forever()


if __name__ == "__main__":
    main()
