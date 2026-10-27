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

def render_table(rows):
    """Render a compact table with one rule below the column headings."""
    header = f"{'Rank':>4}  {'User':>5}  {'Name':<20}  {'Taught':>6}  {'Learned':>7}  {'Total':>5}"
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row['rank']:>4}  {row['user_id']:>5}  "
            f"{(row['name'] or '-'):<20}  {row['sessions_taught']:>6}  "
            f"{row['sessions_learned']:>7}  {row['total_sessions']:>5}"
        )
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
    parser.add_argument("--title", default="SkillMesh leaderboard")
    args = parser.parse_args(argv)

    rows = fetch_leaderboard(args.limit)
    print(f"\n{args.title}")
    print(render_table(rows))

    top = rows[0] if rows else None
    if top:
        print(
            f"\n{len(rows)} users ranked. Top: {top['name']} "
            f"with {top['total_sessions']} completed sessions."
        )
    else:
        print("\nNo users to rank.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
