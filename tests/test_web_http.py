"""Exercise the cookie/CSRF boundary with real HTTP and synthetic accounts."""

import http.cookiejar
from http.server import ThreadingHTTPServer
import json
import threading
import urllib.error
import urllib.request
import uuid

from scripts.config import pg_connect
from web.app import Handler
from web.moderation import ensure_moderation_tables


def test_authenticated_request_owns_identity_and_requires_csrf():
    ensure_moderation_tables()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    email = f"http-{uuid.uuid4().hex}@campus.test"

    def call(path, payload=None, csrf=None):
        headers = {"Content-Type": "application/json"}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            headers=headers,
            data=json.dumps(payload).encode() if payload is not None else None,
        )
        try:
            with client.open(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    try:
        assert call("/api/my-skills")[0] == 401
        status, user = call(
            "/api/register",
            {"name": "HTTP learner", "email": email, "password": "Example123"},
        )
        assert status == 201
        csrf = user["csrf_token"]
        assert call("/api/me")[1]["user_id"] == user["user_id"]
        skill = {
            "skill_id": 5,
            "skill_type": "LEARN",
            "description": "Beginner guitar chords",
        }
        assert call("/api/user-skills", skill)[0] == 403
        assert call("/api/user-skills", skill, "wrong")[0] == 403
        assert call("/api/user-skills", skill, csrf)[0] == 201
        # A forged requester ID must not create a request on behalf of seed user 1.
        request = {"requester_id": 1, "provider_id": 4, "skill_id": 5}
        status, created = call("/api/requests", request, csrf)
        assert status == 201
        requests = call("/api/requests?user_id=1")[1]
        assert len(requests) == 1
        assert requests[0]["request_id"] == created["request_id"]
        assert requests[0]["requester_id"] == user["user_id"]
        assert call("/api/moderation")[0] == 403
    finally:
        with pg_connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE email = %s", (email,))
        server.shutdown()
        server.server_close()
        thread.join()
