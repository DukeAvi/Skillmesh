"""Small standard-library web server for the SkillMesh observatory."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.config import pg_connect


ROOT = Path(__file__).parent


def query(sql, params=()):
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [column.name for column in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def json_value(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def get_payload(path):
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
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            try:
                self.send_json(get_payload(path))
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

    def log_message(self, format, *args):
        return


def main():
    port = int(os.getenv("SKILLMESH_WEB_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"SkillMesh observatory listening on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
