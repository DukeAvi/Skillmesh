"""Booking a swap session without ever double-booking a slot.

This module contains THE transaction that scripts/concurrency_test.py and
tests/test_concurrency.py hammer with two threads at the same time.

The correctness argument has two independent layers:

1. `SELECT status FROM availability_slots WHERE slot_id = %s FOR UPDATE`
   takes a row-level EXCLUSIVE lock. The second transaction blocks here until
   the first one commits, at which point it re-reads the *committed* status
   ('booked') and aborts. This is the pessimistic / correctness layer.
2. `slot_id BIGINT NOT NULL UNIQUE` on swap_sessions (sql/02_schema.sql). Even
   if layer 1 were bypassed, the database itself would reject a second session
   for the same slot. This is the defence-in-depth layer.

Both live in PostgreSQL; the application just has to open a transaction and ask
for the row lock.
"""

import argparse
import sys

try:  # normalise imports for both `python scripts/x.py` and `import scripts.x`
    from .config import pg_connect
except ImportError:  # pragma: no cover
    from config import pg_connect


class SlotNotOpen(RuntimeError):
    """Raised when a slot is missing, not 'open', or belongs to someone else."""


def book_slot(
    conn,
    request_id,
    provider_id,
    learner_id,
    skill_id,
    slot_id,
    update_request_status=True,
):
    """Book `slot_id`. Returns the new swap_sessions.session_id.

    Raises SlotNotOpen (a RuntimeError subclass) if the slot is unavailable.
    Any raise inside the `with conn.transaction():` block rolls the whole
    transaction back, so a failed attempt leaves no partial rows behind.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            # --- layer 1: pessimistic row lock ---------------------------
            cur.execute(
                "SELECT status FROM availability_slots WHERE slot_id=%s FOR UPDATE",
                (slot_id,),
            )
            row = cur.fetchone()
            if not row or row[0] != "open":
                raise SlotNotOpen("slot not open")

            # sanity: the caller must not book a slot that is not theirs
            cur.execute(
                "SELECT provider_id, skill_id FROM availability_slots WHERE slot_id=%s",
                (slot_id,),
            )
            slot_provider_id, slot_skill_id = cur.fetchone()
            if slot_provider_id != provider_id or slot_skill_id != skill_id:
                raise SlotNotOpen("slot does not belong to that provider/skill")

            # --- the session row (UNIQUE(slot_id) is layer 2) ------------
            cur.execute(
                "INSERT INTO swap_sessions (request_id, provider_id, learner_id, skill_id, slot_id) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING session_id",
                (request_id, provider_id, learner_id, skill_id, slot_id),
            )
            session_id = cur.fetchone()[0]

            cur.execute(
                "UPDATE availability_slots SET status='booked' WHERE slot_id=%s",
                (slot_id,),
            )

            if update_request_status:
                cur.execute(
                    "UPDATE swap_requests SET status='accepted' WHERE request_id=%s",
                    (request_id,),
                )

    return session_id


def main(argv=None):
    """Book one specific slot from the command line (demo helper)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--request", type=int, required=True)
    parser.add_argument("--provider", type=int, required=True)
    parser.add_argument("--learner", type=int, required=True)
    parser.add_argument("--skill", type=int, required=True)
    args = parser.parse_args(argv)

    conn = pg_connect()
    try:
        session_id = book_slot(
            conn,
            request_id=args.request,
            provider_id=args.provider,
            learner_id=args.learner,
            skill_id=args.skill,
            slot_id=args.slot,
        )
        print(f"Booked slot {args.slot} -> swap_sessions.session_id = {session_id}")
        return 0
    except SlotNotOpen as exc:
        print(f"Booking refused: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())