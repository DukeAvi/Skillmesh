"""HTTP routing, cookies, CSRF checks, and static assets for SkillMesh."""

from __future__ import annotations
import hmac
import json
import mimetypes
import os
import sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Preserve the documented direct-file entry point; package imports need no shim.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web import auth, exchange, moderation
from web.db import query, json_value
from web.errors import APIError

ROOT = Path(__file__).resolve().parent
MAX_BODY = 16384

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
        if (
            self.headers.get("X-Forwarded-Proto") == "https"
            or os.getenv("SKILLMESH_SECURE_COOKIES") == "1"
        ):
            base += "; Secure"
        return base

    def _session_cookie(self, token: str) -> str:
        return f"session={token}; {self._cookie_flags()}; Max-Age={auth.SESSION_TTL}"

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
        sess = auth._get_session(token)
        if not sess:
            return None
        rows = query(
            """
                SELECT user_id, name, email, role
                FROM users
                WHERE user_id = %s
                AND NOT EXISTS (SELECT 1
                FROM banned_users
                WHERE user_id = users.user_id)
            """,
            (sess["user"]["user_id"],),
        )
        if not rows:
            auth._destroy_session(token)
            return None
        return rows[0]

    def _require_csrf(self) -> bool:
        """Validate the CSRF token for mutating requests. Return True if OK."""
        token = self._get_session_token()
        if not token:
            self.send_json({"error": "Sign in required"}, 401)
            return False
        sess = auth._get_session(token)
        if not sess:
            self.send_json({"error": "Session expired, please sign in again"}, 401)
            return False
        if not self.session():
            self.send_json({"error": "Sign in required"}, 401)
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

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            try:
                if path == "/api/me":
                    token = self._get_session_token()
                    sess = auth._get_session(token) if token else None
                    user = self.session() if sess else None
                    self.send_json(
                        {**user, "csrf_token": sess["csrf"]} if user else None
                    )
                elif path == "/api/users":
                    self.send_json({"error": "endpoint not found"}, 404)
                elif path == "/api/moderation":
                    if not moderation.is_moderator(self.session()):
                        raise APIError("Moderator access required", 403)
                    self.send_json(moderation.overview())
                elif path in ("/api/my-skills", "/api/matches", "/api/requests"):
                    user = self.session()
                    if not user:
                        raise APIError("Sign in required", 401)
                    user_id = user["user_id"]
                    if path == "/api/my-skills":
                        result = exchange.my_skills(user_id)
                    elif path == "/api/matches":
                        values = parse_qs(parsed.query)
                        result = exchange.matches(
                            user_id, int(values.get("skill_id", ["0"])[0])
                        )
                    else:
                        result = exchange.requests(user_id)
                    self.send_json(result)
                else:
                    self.send_json(exchange.get_payload(path, parsed.query))
            except APIError as exc:
                self.send_json({"error": str(exc)}, exc.status)
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

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in (
            "/api/login",
            "/api/register",
            "/api/logout",
            "/api/moderator/setup",
            "/api/requests",
            "/api/user-skills",
            "/api/moderation",
            "/api/reports",
        ):
            self.send_json({"error": "endpoint not found"}, 404)
            return
        try:
            if path == "/api/logout":
                token = self._get_session_token()
                if token:
                    auth._destroy_session(token)
                self.send_json({"ok": True}, cookie=self._clear_cookie())
                return
            payload = self._read_json_body()
            if payload is None:
                return
            if path == "/api/moderator/setup":
                self.send_json(auth.setup_moderator(payload))
                return
            if path in ("/api/login", "/api/register"):
                user = (
                    auth.login(payload)
                    if path == "/api/login"
                    else auth.register(payload)
                )
                token, csrf = auth._create_session(user)
                self.send_json(
                    {**user, "csrf_token": csrf},
                    200 if path == "/api/login" else 201,
                    cookie=self._session_cookie(token),
                )
                return
            if not self._require_csrf():
                return
            user = self.session()
            if not user:
                raise APIError("Sign in required", 401)
            if path == "/api/moderation":
                if not moderation.is_moderator(user):
                    raise APIError("Moderator access required", 403)
                self.send_json(moderation.moderate(user, payload))
            elif path == "/api/reports":
                self.send_json(moderation.report_user(user, payload), 201)
            elif path == "/api/user-skills":
                self.send_json(exchange.save_skill(user, payload), 201)
            else:
                payload["requester_id"] = user["user_id"]
                self.send_json(exchange.execute_request(payload), 201)
        except APIError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except (ValueError, TypeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": f"request could not be created: {exc}"}, 422)

    def log_message(self, format, *args):
        return


def main():
    port = int(os.getenv("SKILLMESH_WEB_PORT", "8080"))
    moderation.ensure_moderation_tables()
    moderation.ensure_arjun_is_admin()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"SkillMesh observatory listening on http://localhost:{port}")
    print("Security: PBKDF2-SHA256 · CSRF tokens · rate limiting · secure headers")
    server.serve_forever()


if __name__ == "__main__":
    main()
