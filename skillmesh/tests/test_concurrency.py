"""Concurrency tests: the SELECT ... FOR UPDATE guard prevents double booking.

The heavy lifting lives in scripts/concurrency_test.py; this file wraps it in
pytest assertions and additionally checks the database invariants directly.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import concurrency_test
from scripts.config import pg_connect


def test_exactly_one_booking_wins_the_race(capsys):
    outcome = concurrency_test.run(verbose=False)
    with capsys.disabled():
        print(
            f"\nsuccesses={outcome['successes']} failures={outcome['failures']} "
            f"swap_sessions rows={outcome['session_rows']}"
        )
        for result in outcome["results"]:
            state = "SUCCESS" if result["ok"] else f"FAILED ({result['error']})"
            print(f"  thread {result['index']}: {state}")

    assert outcome["successes"] == 1, f"expected exactly 1 success, got {outcome['successes']}"
    assert outcome["failures"] == 1, f"expected exactly 1 failure, got {outcome['failures']}"
    assert outcome["session_rows"] == 1, f"expected 1 swap_sessions row, got {outcome['session_rows']}"
    assert outcome["slot_status"] == "booked"
    assert outcome["passed"] is True


def test_loser_reports_slot_not_open():
    outcome = concurrency_test.run(verbose=False)
    failures = [r for r in outcome["results"] if not r["ok"]]
    assert len(failures) == 1
    assert failures[0]["error"] == "slot not open"
    assert failures[0]["session_id"] is None


def test_only_one_swap_session_row_exists_for_the_slot():
    outcome = concurrency_test.run(teardown_after=False, verbose=False)
    slot_id = outcome["slot_id"]
    try:
        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM swap_sessions WHERE slot_id = %s", (slot_id,))
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT status FROM availability_slots WHERE slot_id = %s", (slot_id,))
                assert cur.fetchone()[0] == "booked"
        finally:
            conn.close()
    finally:
        cleanup = pg_connect()
        try:
            concurrency_test.teardown(cleanup)
        finally:
            cleanup.close()


def test_unique_slot_id_is_the_second_safeguard():
    """Even without the row lock, UNIQUE(slot_id) refuses a second session."""
    outcome = concurrency_test.run(teardown_after=False, verbose=False)
    slot_id = outcome["slot_id"]
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT request_id, provider_id, learner_id, skill_id FROM swap_sessions "
                "WHERE slot_id = %s",
                (slot_id,),
            )
            request_id, provider_id, learner_id, skill_id = cur.fetchone()
        raised = False
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO swap_sessions (request_id, provider_id, learner_id, skill_id, slot_id) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (request_id, provider_id, learner_id, skill_id, slot_id),
                )
        except Exception as exc:
            raised = "swap_sessions_slot_id_key" in str(exc)
        assert raised, "UNIQUE(slot_id) should have rejected the duplicate insert"
    finally:
        concurrency_test.teardown(conn)
        conn.close()