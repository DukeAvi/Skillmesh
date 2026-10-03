"""Redis presence tests: SETEX / EXISTS / TTL / expiry.

No sleeping: a 61-second wait would make the suite unusable, so the "key has
expired" case is simulated with an explicit DEL, which leaves Redis in exactly
the state an expired key would leave it in (key absent).
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

# redis-py deprecates the setex() helper; scripts/redis_presence.py already
# filters that warning at runtime, pytest needs to be told separately.
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

from scripts import redis_presence
from scripts.config import PRESENCE_TTL, redis_client


@pytest.fixture()
def client():
    try:
        conn = redis_client()
        conn.ping()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Redis is not reachable: {type(exc).__name__}: {exc}")
    yield conn
    redis_presence.offline(conn, 1)
    redis_presence.offline(conn, 2)


def test_heartbeat_creates_the_key(client):
    redis_presence.offline(client, 1)
    key = redis_presence.heartbeat(client, 1)
    assert key == "online:1"
    assert client.exists(key) == 1
    assert redis_presence.is_online(client, 1) == 1


def test_ttl_is_between_1_and_60(client):
    redis_presence.heartbeat(client, 1)
    remaining = redis_presence.ttl(client, 1)
    assert 1 <= remaining <= PRESENCE_TTL, f"TTL out of range: {remaining}"


def test_heartbeat_refreshes_the_ttl(client):
    redis_presence.heartbeat(client, 1)
    client.expire(redis_presence.presence_key(1), 5)
    assert redis_presence.ttl(client, 1) <= 5
    redis_presence.heartbeat(client, 1)
    assert redis_presence.ttl(client, 1) > 5


def test_deleted_key_means_offline(client):
    """Expiry is simulated with DEL - same observable state, no 61s sleep."""
    redis_presence.heartbeat(client, 2)
    assert redis_presence.is_online(client, 2) == 1
    redis_presence.offline(client, 2)
    assert redis_presence.is_online(client, 2) == 0
    assert redis_presence.ttl(client, 2) == -2  # -2 == key does not exist


def test_presence_is_not_stored_in_postgres(client):
    """The `users` table must not carry presence - that is the whole point."""
    import psycopg

    from scripts.config import PG_DSN

    with psycopg.connect(PG_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'is_online'
            """
        )
        assert cur.fetchone()[0] == 0


def test_full_cycle_reports_pass(client):
    outcome = redis_presence.run(verbose=False)
    failed = [label for label, ok, _ in outcome["checks"] if not ok]
    assert outcome["passed"], f"failing presence checks: {failed}"
    assert len(outcome["checks"]) >= 4


def test_online_users_roster(client):
    redis_presence.offline(client, 1)
    redis_presence.offline(client, 2)
    redis_presence.heartbeat_many(client, [1, 2])
    assert redis_presence.online_users(client)[-2:] == [1, 2]
    redis_presence.offline(client, 1)
    assert 1 not in redis_presence.online_users(client)