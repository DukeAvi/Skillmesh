"""Tests for the two SQL functions and two SQL procedures."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.config import pg_connect


ROUTINES = {
    "fn_find_skill_matches": "FUNCTION",
    "fn_provider_average_rating": "FUNCTION",
    "sp_create_swap_request": "PROCEDURE",
    "sp_complete_swap_session": "PROCEDURE",
}


def test_exactly_two_demo_functions_and_two_demo_procedures_exist():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT routine_name, routine_type
                FROM information_schema.routines
                WHERE routine_schema = 'public'
                  AND routine_name = ANY(%s)
                """,
                (list(ROUTINES),),
            )
            found = dict(cur.fetchall())
        assert found == ROUTINES
    finally:
        conn.close()


def test_match_function_returns_vector_ranked_teachers():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.user_id, s.skill_id
                FROM users u
                CROSS JOIN skills s
                WHERE u.email = 'aarav.sharma@campus.edu'
                  AND s.name = 'Guitar'
                """
            )
            learner_id, skill_id = cur.fetchone()
            cur.execute(
                "SELECT * FROM fn_find_skill_matches(%s, %s, 3)",
                (learner_id, skill_id),
            )
            rows = cur.fetchall()
        assert len(rows) == 3
        assert all(row[0] != learner_id for row in rows)
        assert all(-1 <= row[4] <= 1 for row in rows)
        assert [row[4] for row in rows] == sorted((row[4] for row in rows), reverse=True)
    finally:
        conn.close()


def test_rating_function_excludes_provider_self_review():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'")
            provider_id = cur.fetchone()[0]
            cur.execute("SELECT fn_provider_average_rating(%s)", (provider_id,))
            rating = cur.fetchone()[0]
        # Diya received two learner ratings of 5. Her own rating of Rohan on
        # session 1 is deliberately excluded by the function.
        assert float(rating) == 5.0
    finally:
        conn.close()


def test_both_procedures_execute_and_preserve_the_workflow():
    conn = pg_connect()
    request_id = slot_id = session_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT learner.user_id, provider.user_id, skill.skill_id
                FROM users learner
                CROSS JOIN users provider
                CROSS JOIN skills skill
                WHERE learner.email = 'aarav.sharma@campus.edu'
                  AND provider.email = 'ananya.iyer@campus.edu'
                  AND skill.name = 'Guitar'
                """
            )
            learner_id, provider_id, skill_id = cur.fetchone()

            cur.execute(
                "CALL sp_create_swap_request(%s::BIGINT, %s::BIGINT, %s::BIGINT, "
                "%s::REAL, NULL::BIGINT)",
                (learner_id, provider_id, skill_id, 0.95),
            )
            request_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO availability_slots
                    (provider_id, skill_id, start_time, end_time, status)
                VALUES
                    (%s, %s, NOW() + INTERVAL '1000 days',
                     NOW() + INTERVAL '1000 days 1 hour', 'booked')
                RETURNING slot_id
                """,
                (provider_id, skill_id),
            )
            slot_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO swap_sessions
                    (request_id, provider_id, learner_id, skill_id, slot_id, status)
                VALUES (%s, %s, %s, %s, %s, 'scheduled')
                RETURNING session_id
                """,
                (request_id, provider_id, learner_id, skill_id, slot_id),
            )
            session_id = cur.fetchone()[0]

            cur.execute("CALL sp_complete_swap_session(%s::BIGINT)", (session_id,))
            cur.execute(
                "SELECT status, completed_at IS NOT NULL FROM swap_sessions WHERE session_id = %s",
                (session_id,),
            )
            assert cur.fetchone() == ("completed", True)
    finally:
        with conn.cursor() as cur:
            if session_id is not None:
                cur.execute("DELETE FROM swap_sessions WHERE session_id = %s", (session_id,))
            if slot_id is not None:
                cur.execute("DELETE FROM availability_slots WHERE slot_id = %s", (slot_id,))
            if request_id is not None:
                cur.execute("DELETE FROM swap_requests WHERE request_id = %s", (request_id,))
        conn.close()

