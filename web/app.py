"""Small standard-library web server for the SkillMesh observatory."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.config import pg_connect


ROOT = Path(__file__).parent


def query(sql, params=()):
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [column.name for column in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def execute_request(payload):
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


def get_payload(path, query_string):
    if path == "/api/health":
        rows = query("SELECT current_database() AS database, NOW() AS server_time")
        return {"ok": True, **{key: json_value(value) for key, value in rows[0].items()}}
    if path == "/api/skills":
        return query(
            """
            SELECT skill_id, skill_name, category_name, teachers, learners,
                   completed_sessions, demand_gap, demand_rank
            FROM skill_popularity
            ORDER BY demand_rank, skill_name
            """
        )
    if path == "/api/users":
        return query(
            "SELECT user_id, name, email, role, department FROM users ORDER BY name"
        )
    if path == "/api/matches":
        values = parse_qs(query_string)
        learner_id = int(values.get("learner_id", ["0"])[0])
        skill_id = int(values.get("skill_id", ["0"])[0])
        return query(
            """
            SELECT provider_id, provider_name, matched_skill_id, matched_skill,
                   similarity,
                   fn_provider_average_rating(provider_id) AS rating
            FROM fn_find_skill_matches(%s::BIGINT, %s::BIGINT, 10)
            """,
            (learner_id, skill_id),
        )
    if path == "/api/requests":
        values = parse_qs(query_string)
        user_id = int(values.get("user_id", ["0"])[0])
        return query(
            """
            SELECT sr.request_id, sr.status, sr.similarity_score, sr.created_at,
                   sr.requester_id, requester.name AS requester_name,
                   sr.provider_id, provider.name AS provider_name,
                   sr.skill_id, s.name AS skill_name
            FROM swap_requests sr
            JOIN users requester ON requester.user_id = sr.requester_id
            JOIN users provider ON provider.user_id = sr.provider_id
            JOIN skills s ON s.skill_id = sr.skill_id
            WHERE sr.requester_id = %s OR sr.provider_id = %s
            ORDER BY sr.created_at DESC
            """,
            (user_id, user_id),
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


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload, default=json_value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            try:
                self.send_json(get_payload(path, parsed.query))
            except KeyError:
                self.send_json({"error": "endpoint not found"}, 404)
            except Exception as exc:
                self.send_json({"error": f"database unavailable: {exc}"}, 503)
            return

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
        self.send_header("Content-Type", mimetypes.guess_type(requested.name)[0] or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        if urlparse(self.path).path != "/api/requests":
            self.send_json({"error": "endpoint not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            self.send_json(execute_request(payload), 201)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": f"request could not be created: {exc}"}, 422)

    def log_message(self, format, *args):
        return


def main():
    port = int(os.getenv("SKILLMESH_WEB_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"SkillMesh observatory listening on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
