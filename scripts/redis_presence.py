"""Redis presence with a TTL - the reason presence is NOT a PostgreSQL column.

Model
-----
    key   : online:{user_id}
    value : 1
    TTL   : 60 seconds

Every heartbeat is a `SETEX online:{user_id} 60 1`, which both creates/overwrites
the key *and* resets its expiry to 60 seconds. A user is considered online iff
`EXISTS online:{user_id}` returns 1. If the client stops sending heartbeats, the
key simply evaporates and the user disappears from the roster - there is no
cleanup job, no "last_seen" sweep, and no row locked by a long UPDATE.

Why not a boolean column? A `users.is_online BOOLEAN` would need a write from
every heartbeat (a row-level lock + WAL + heap churn every few seconds, for
every concurrent user), and it can never represent "gone offline" without a
sweeper process. Redis gives us expiry for free.

Run:
    python scripts/redis_presence.py     -> prints PASS/FAIL, exit 1 on FAIL
"""

import argparse
import sys
import warnings

try:  # normalise imports for both `python scripts/x.py` and `import scripts.x`
    from .config import PRESENCE_TTL, redis_client
except ImportError:  # pragma: no cover
    from config import PRESENCE_TTL, redis_client

# redis-py >= 5 deprecates the Python-level setex() helper in favour of
# set(key, value, ex=ttl). Both emit the same `SET ... EX <ttl>` command, so the
# warning is noise here; keep SETEX semantics and silence it.
warnings.filterwarnings("ignore", message=".*deprecated setex.*", category=DeprecationWarning)


def presence_key(user_id):
    return f"online:{user_id}"


def heartbeat(client, user_id, ttl=PRESENCE_TTL):
    """Mark `user_id` online for the next `ttl` seconds. Returns the key name."""
    key = presence_key(user_id)
    client.setex(key, ttl, 1)
    return key


def is_online(client, user_id):
    """1 if the key exists, 0 otherwise."""
    return int(client.exists(presence_key(user_id)))


def ttl(client, user_id):
    """-2 = key gone, -1 = no TTL set, otherwise seconds remaining."""
    return int(client.ttl(presence_key(user_id)))


def offline(client, user_id):
    """Force the user offline (what an explicit 'log out' would do)."""
    return int(client.delete(presence_key(user_id)))


def heartbeat_many(client, user_ids, ttl=PRESENCE_TTL):
    """Pipeline variant - one round trip for a whole batch of users."""
    pipe = client.pipeline()
    for user_id in user_ids:
        pipe.setex(presence_key(user_id), ttl, 1)
    pipe.execute()
    return len(user_ids)


def online_users(client):
    """List heartbeat keys as sorted user IDs; the browser does not use this roster."""
    keys = list(client.scan_iter(match="online:*", count=200))
    return sorted(int(key.split(":", 1)[1]) for key in keys)


def run(verbose=True):
    """The full set / exists / ttl / expire cycle. Returns a result dict."""
    client = redis_client()
    checks = []
    try:
        client.ping()

        # clean slate
        for user_id in (1, 2):
            offline(client, user_id)

        # --- 1. heartbeat sets the key -----------------------------------
        key = heartbeat(client, 1)
        exists_after_set = is_online(client, 1)
        checks.append(("heartbeat() creates online:{id}", exists_after_set == 1,
                       f"EXISTS -> {exists_after_set}"))

        # --- 2. TTL is inside the window ---------------------------------
        remaining = ttl(client, 1)
        checks.append(("TTL is between 1 and 60", 1 <= remaining <= PRESENCE_TTL,
                       f"TTL -> {remaining}s"))

        # --- 3. heartbeat refreshes the TTL ------------------------------
        client.expire(presence_key(1), 5)
        after_shrink = ttl(client, 1)
        heartbeat(client, 1)
        after_refresh = ttl(client, 1)
        checks.append(("heartbeat() refreshes the TTL",
                       after_shrink <= 5 and after_refresh > after_shrink,
                       f"{after_shrink}s -> {after_refresh}s"))

        # --- 4. key removed => offline -----------------------------------
        heartbeat(client, 2)
        offline(client, 2)
        exists_after_delete = is_online(client, 2)
        checks.append(("deleted key means offline", exists_after_delete == 0,
                       f"EXISTS -> {exists_after_delete}"))

        # --- 5. the exact key/ttl contract -------------------------------
        checks.append((f"key name is {key!r}", key == "online:1", f"key -> {key!r}"))

        passed = all(ok for _, ok, _ in checks)

        if verbose:
            print("=" * 68)
            print(f"Redis presence cycle  (redis://{client.connection_pool.connection_kwargs['host']}"
                  f":{client.connection_pool.connection_kwargs['port']})")
            print("=" * 68)
            for label, ok, detail in checks:
                print(f"  [{'PASS' if ok else 'FAIL'}] {label:<38} {detail}")
            print("=" * 68)
            print("RESULT: PASS" if passed else "RESULT: FAIL")

        return {"passed": passed, "checks": checks, "client": client}
    except Exception as exc:  # pragma: no cover - redis unreachable
        print(f"RESULT: FAIL  (Redis unreachable: {type(exc).__name__}: {exc})")
        return {"passed": False, "checks": [], "client": client}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    outcome = run()
    return 0 if outcome["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())