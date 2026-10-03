"""Pretty-print the `leaderboard` view built in sql/04_leaderboard_view.sql.

    python scripts/leaderboard.py
    python scripts/leaderboard.py --limit 20
"""

import argparse
import sys

try:  # normalise imports for both `python scripts/x.py` and `import scripts.x`
    from .config import pg_connect
except ImportError:  # pragma: no cover
    from config import pg_connect

LEADERBOARD_SQL = "SELECT * FROM leaderboard ORDER BY rank, total_sessions DESC;"

COLUMNS = [
    ("rank", "Rank"),
    ("user_id", "User ID"),
    ("name", "Name"),
    ("sessions_taught", "Taught"),
    ("sessions_learned", "Learned"),
    ("total_sessions", "Total"),
]

RULE = "+-------+---------+----------------------+--------+---------+-------+"
HEADER = "| Rank  | User ID | Name                 | Taught | Learned | Total |"
SEPARATOR = "+-------+---------+----------------------+--------+---------+-------+"


def render_table(rows):
    """Render leaderboard rows as a fixed-width ASCII table."""
    lines = [RULE, HEADER, SEPARATOR]
    for row in rows:
        cells = [
            f"{row['rank']:>5}",
            f"{row['user_id']:>7}",
            f"{(row['name'] or '-'):<20}",
            f"{row['sessions_taught']:>6}",
            f"{row['sessions_learned']:>7}",
            f"{row['total_sessions']:>5}",
        ]
        lines.append("| " + " | ".join(cells) + " |")
        lines.append(SEPARATOR)
    return "\n".join(lines)


def fetch_leaderboard(limit=None, conn=None):
    sql = LEADERBOARD_SQL if limit is None else LEADERBOARD_SQL.rstrip(";") + f" LIMIT {int(limit)};"
    own_conn = conn is None
    conn = conn or pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [c.name for c in cur.description]
            return [dict(zip(columns, r)) for r in cur.fetchall()]
    finally:
        if own_conn:
            conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    rows = fetch_leaderboard(args.limit)
    print("=" * 57)
    print("SkillMesh leaderboard (completed sessions)")
    print("=" * 57)
    print(render_table(rows))
    print(f"{len(rows)} user(s) ranked.")

    top = rows[0] if rows else None
    if top:
        print(f"\nTop mentor: {top['name']} with {top['total_sessions']} completed session(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())