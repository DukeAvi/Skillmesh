"""Race-condition demo: two learners, one slot, one winner.

Timeline of the bug this script exists to prevent:

    time   learner A                       learner B
    ----   --------------------------------  --------------------------------
    t0     SELECT status ...  -> 'open'    (not started)
    t1                                    SELECT status ...  -> 'open'
    t2     INSERT swap_sessions ...
    t3                                    INSERT swap_sessions ...   <-- double booking
    t4     UPDATE slot SET status='booked'
    t5                                    UPDATE slot SET status='booked'

`SELECT ... FOR UPDATE` serialises t0/t1: whoever takes the lock first holds it
until COMMIT, so the loser blocks at t1 and then reads 'booked'.

    python scripts/concurrency_test.py     # prints PASS/FAIL, exit 1 on FAIL

The same function is imported by tests/test_concurrency.py.
"""

import argparse
import sys
import threading

try:  # normalise imports for both `python scripts/x.py` and `import scripts.x`
    from .book import SlotNotOpen, book_slot
    from .config import pg_connect
except ImportError:  # pragma: no cover
    from book import SlotNotOpen, book_slot
    from config import pg_connect

TEST_TAG = "concurrency-test"
PROVIDER_EMAIL = f"{TEST_TAG}.provider@campus.test"
LEARNER_EMAILS = [f"{TEST_TAG}.learner1@campus.test", f"{TEST_TAG}.learner2@campus.test"]
TEST_SKILL = "Python Programming"

UPSERT_USER = """
    INSERT INTO users (name, email, password_hash, role, department)
    VALUES (%s, %s, 'not-a-real-hash', 'mentor', 'QA')
    ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
    RETURNING user_id
"""

INSERT_REQUEST = """
    INSERT INTO swap_requests (requester_id, provider_id, skill_id, status)
    VALUES (%s, %s, %s, 'pending')
    RETURNING request_id
"""

INSERT_SLOT = """
    INSERT INTO availability_slots (provider_id, skill_id, start_time, end_time, status)
    VALUES (%s, %s, NOW() + INTERVAL '1 day', NOW() + INTERVAL '1 day' + INTERVAL '3 hours', 'open')
    RETURNING slot_id
"""

COUNT_SESSIONS = "SELECT count(*) FROM swap_sessions WHERE slot_id = %s"


def teardown(conn, provider_id=None):
    """Remove anything left over from a previous run so this script is re-runnable."""
    with conn.cursor() as cur:
        if provider_id is None:
            cur.execute("SELECT user_id FROM users WHERE email = %s", (PROVIDER_EMAIL,))
            row = cur.fetchone()
            provider_id = row[0] if row else None
        if provider_id is None:
            return
        # ON DELETE CASCADE from users -> swap_requests; swap_sessions needs the
        # slot to go first (its FK to availability_slots is ON DELETE RESTRICT).
        cur.execute(
            "DELETE FROM swap_sessions WHERE slot_id IN "
            "(SELECT slot_id FROM availability_slots WHERE provider_id = %s)",
            (provider_id,),
        )
        cur.execute("DELETE FROM availability_slots WHERE provider_id = %s", (provider_id,))
        cur.execute(
            "DELETE FROM swap_requests WHERE requester_id IN "
            "(SELECT user_id FROM users WHERE email = ANY(%s))",
            (LEARNER_EMAILS,),
        )
        cur.execute("DELETE FROM users WHERE email = ANY(%s)", ([PROVIDER_EMAIL] + LEARNER_EMAILS,))


def setup_fixture(conn):
    """One provider, one open slot, two learners, one pending request each."""
    skill_id = None
    with conn.cursor() as cur:
        cur.execute("SELECT skill_id FROM skills WHERE name = %s", (TEST_SKILL,))
        row = cur.fetchone()
        if row is None:
            raise LookupError(f"seed skill '{TEST_SKILL}' is missing - is the DB seeded?")
        skill_id = row[0]

        cur.execute(UPSERT_USER, ("Concurrency Provider", PROVIDER_EMAIL))
        provider_id = cur.fetchone()[0]

        learner_ids = []
        request_ids = []
        for index, email in enumerate(LEARNER_EMAILS, start=1):
            cur.execute(UPSERT_USER, (f"Concurrency Learner {index}", email))
            learner_id = cur.fetchone()[0]
            learner_ids.append(learner_id)
            cur.execute(INSERT_REQUEST, (learner_id, provider_id, skill_id))
            request_ids.append(cur.fetchone()[0])

        cur.execute(INSERT_SLOT, (provider_id, skill_id))
        slot_id = cur.fetchone()[0]

    return {
        "provider_id": provider_id,
        "skill_id": skill_id,
        "slot_id": slot_id,
        "learner_ids": learner_ids,
        "request_ids": request_ids,
    }


def race_for_slot(fixture, barrier=None):
    """Two threads, two independent connections, the same slot_id."""
    results = []
    lock = threading.Lock()
    barrier = barrier or threading.Barrier(2)

    def attempt(index):
        # Every thread needs its OWN connection: a psycopg connection is not
        # thread-safe and, more importantly, two sessions are what makes this
        # an actual database-level race.
        conn = pg_connect()
        try:
            if barrier is not None:
                barrier.wait(timeout=30)
            session_id = book_slot(
                conn,
                request_id=fixture["request_ids"][index],
                provider_id=fixture["provider_id"],
                learner_id=fixture["learner_ids"][index],
                skill_id=fixture["skill_id"],
                slot_id=fixture["slot_id"],
            )
            with lock:
                results.append({"index": index, "ok": True, "session_id": session_id, "error": None})
        except SlotNotOpen as exc:
            with lock:
                results.append({"index": index, "ok": False, "session_id": None, "error": str(exc)})
        except Exception as exc:  # pragma: no cover - surfaced as a failure
            with lock:
                results.append(
                    {"index": index, "ok": False, "session_id": None,
                     "error": f"{type(exc).__name__}: {exc}"}
                )
        finally:
            conn.close()

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def run(teardown_after=True, verbose=True):
    """Set up, race, verify, tear down. Returns a result dict."""
    conn = pg_connect()
    try:
        # Always clear leftovers first so the script is safe to re-run.
        teardown(conn)
        fixture = setup_fixture(conn)
        if verbose:
            print("=" * 68)
            print("Concurrency test: SELECT ... FOR UPDATE double-booking guard")
            print("=" * 68)
            print(f"provider_id = {fixture['provider_id']}")
            print(f"slot_id     = {fixture['slot_id']} (status = open)")
            print(f"learners    = {fixture['learner_ids']}")
            print(f"requests    = {fixture['request_ids']}")
            print("-" * 68)

        results = race_for_slot(fixture)

        with conn.cursor() as cur:
            cur.execute(COUNT_SESSIONS, (fixture["slot_id"],))
            session_rows = cur.fetchone()[0]
            cur.execute(
                "SELECT status FROM availability_slots WHERE slot_id = %s", (fixture["slot_id"],)
            )
            slot_status = cur.fetchone()[0]

        successes = [r for r in results if r["ok"]]
        failures = [r for r in results if not r["ok"]]
        passed = (
            len(successes) == 1
            and len(failures) == 1
            and session_rows == 1
            and slot_status == "booked"
        )

        if verbose:
            for result in sorted(results, key=lambda r: r["index"]):
                if result["ok"]:
                    print(f"  thread {result['index']}: SUCCESS  session_id={result['session_id']}")
                else:
                    print(f"  thread {result['index']}: FAILED   {result['error']}")
            print("-" * 68)
            print(f"successful bookings : {len(successes)} (expected 1)")
            print(f"failed bookings     : {len(failures)} (expected 1, 'slot not open')")
            print(f"swap_sessions rows  : {session_rows} (expected 1)")
            print(f"final slot status   : {slot_status} (expected booked)")
            print("=" * 68)
            print("RESULT: PASS" if passed else "RESULT: FAIL")

        return {
            "passed": passed,
            "results": results,
            "successes": len(successes),
            "failures": len(failures),
            "session_rows": session_rows,
            "slot_status": slot_status,
            "slot_id": fixture["slot_id"],
            "fixture": fixture,
        }
    finally:
        if teardown_after:
            teardown(conn)
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave the fixture rows in place for manual inspection",
    )
    args = parser.parse_args(argv)
    outcome = run(teardown_after=not args.keep)
    return 0 if outcome["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())