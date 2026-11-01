"""Pretty-print the `skill_popularity` view.

    python scripts/skill_stats.py
    python scripts/skill_stats.py --limit 5
"""

import argparse
import sys

try:  # normalise imports for both `python scripts/x.py` and `import scripts.x`
    from .config import pg_connect
except ImportError:  # pragma: no cover
    from config import pg_connect


SKILL_STATS_SQL = """
SELECT demand_rank, skill_name, category_name, teachers, learners,
       completed_sessions, demand_gap
FROM skill_popularity
ORDER BY demand_rank, skill_name;
"""


def fetch_skill_stats(limit=None, conn=None):
    """Return skill supply-and-demand rows, optionally limited to the top ranks."""
    own_conn = conn is None
    conn = conn or pg_connect()
    try:
        sql = SKILL_STATS_SQL
        if limit is not None:
            sql = sql.rstrip(";\n") + f" LIMIT {int(limit)};"
        with conn.cursor() as cur:
            cur.execute(sql)
            columns = [column.name for column in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        if own_conn:
            conn.close()


def render_table(rows):
    """Render a compact supply-and-demand table."""
    header = (
        f"{'Rank':>4}  {'Skill':<26}  {'Category':<14}  "
        f"{'Teach':>5}  {'Learn':>5}  {'Done':>4}  {'Gap':>4}"
    )
    lines = [header, "-" * len(header)]
    for row in rows:
        lines.append(
            f"{row['demand_rank']:>4}  {(row['skill_name'] or '-'):<26}  "
            f"{(row['category_name'] or '-'):<14}  {row['teachers']:>5}  "
            f"{row['learners']:>5}  {row['completed_sessions']:>4}  "
            f"{row['demand_gap']:>4}"
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--title", default="Skill popularity and demand")
    args = parser.parse_args(argv)

    rows = fetch_skill_stats(args.limit)
    print(f"\n{args.title}")
    print(render_table(rows))
    print(f"\n{len(rows)} skills analysed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
