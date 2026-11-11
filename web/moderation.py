"""Moderator policy, reports, and administrative data operations."""

from scripts.config import pg_connect
from web.db import query


def ensure_arjun_is_admin() -> None:
    """Keep the single designated administrator aligned with the seed policy."""
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET role = 'student' "
                "WHERE role = 'admin' "
                "AND lower(email) <> 'arjun@campus.edu'"
            )
            cur.execute(
                "UPDATE users SET role = 'admin' "
                "WHERE lower(email) = 'arjun@campus.edu'"
            )


def ensure_moderation_tables() -> None:
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS banned_users (
                user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
                banned_by BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
                banned_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            cur.execute("""CREATE TABLE IF NOT EXISTS abuse_reports (
                report_id BIGSERIAL PRIMARY KEY,
                reporter_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
                reported_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 1000),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")


def is_moderator(user: dict | None) -> bool:
    return bool(
        user
        and str(user.get("email", "")).lower() == "arjun@campus.edu"
        and user.get("role") == "admin"
    )


def overview():
    return {
        "reports": query("""
            SELECT r.report_id, r.reported_id, r.reason, r.created_at,
                            target.name AS reported_name, reporter.name AS reporter_name,
                            (b.user_id IS NOT NULL) AS banned
                            FROM abuse_reports r JOIN users target ON target.user_id = r.reported_id
                            LEFT JOIN users reporter ON reporter.user_id = r.reporter_id
                            LEFT JOIN banned_users b ON b.user_id = r.reported_id
                            ORDER BY r.created_at DESC
        """),
        "users": query(
            "SELECT user_id, name, email, role, created_at FROM users ORDER BY user_id"
        ),
        "skills": query("SELECT skill_id, name, description FROM skills ORDER BY name"),
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
    }


def report_user(user, payload):
    target = int(payload.get("user_id", 0))
    reason = str(payload.get("reason", "")).strip()
    if target == user["user_id"] or target <= 0 or (not reason) or (len(reason) > 1000):
        raise ValueError(
            "Choose another user and provide a reason (up to 1000 characters)"
        )
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                    INSERT INTO abuse_reports (reporter_id, reported_id, reason) SELECT %s, user_id, %s
                    FROM users
                    WHERE user_id = %s
                    RETURNING report_id
                """,
                (user["user_id"], reason, target),
            )
            if not cur.fetchone():
                raise ValueError("User not found")
    return {"ok": True}


def moderate(user, payload):
    action = str(payload.get("action", ""))
    with pg_connect() as conn:
        with conn.cursor() as cur:
            if action in ("ban-user", "unban-user"):
                user_id = int(payload["user_id"])
                if user_id == user["user_id"]:
                    raise ValueError("You cannot ban your own account")
                if action == "ban-user":
                    cur.execute(
                        """
                            INSERT INTO banned_users (user_id, banned_by) SELECT user_id, %s
                            FROM users
                            WHERE user_id = %s
                            ON CONFLICT (user_id) DO NOTHING
                        """,
                        (user["user_id"], user_id),
                    )
                else:
                    cur.execute(
                        "DELETE FROM banned_users WHERE user_id = %s", (user_id,)
                    )
            elif action == "set-role":
                user_id = int(payload["user_id"])
                role = str(payload["role"])
                if role not in ("student", "mentor", "admin"):
                    raise ValueError("Invalid role")
                target = query("SELECT email FROM users WHERE user_id = %s", (user_id,))
                if not target:
                    raise ValueError("User not found")
                target_is_arjun = target[0]["email"].lower() == "arjun@campus.edu"
                if role == "admin" and (not target_is_arjun):
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
                    """
                        INSERT INTO skill_categories (name)
                        VALUES (%s)
                        ON CONFLICT (name) DO UPDATE
                        SET name = EXCLUDED.name
                        RETURNING category_id
                    """,
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
                    (
                        int(payload["provider_id"]),
                        int(payload["skill_id"]),
                        payload["start_time"],
                        payload["end_time"],
                    ),
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
                    """
                        UPDATE swap_sessions
                        SET status = %s, completed_at = CASE WHEN %s = 'completed' THEN COALESCE(completed_at, NOW()) ELSE completed_at END
                        WHERE session_id = %s
                    """,
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
    return {"ok": True}
