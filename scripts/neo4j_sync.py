"""PostgreSQL -> Neo4j sync.

PostgreSQL stays the system of record. Neo4j is a *derived* read model that we
rebuild idempotently with MERGE, so running this script twice changes nothing.

    python scripts/neo4j_sync.py

What gets mirrored
------------------
nodes        :User  <- users            (user_id, name, email, role, department)
              :Skill <- skills          (skill_id, name, description)
relationships
              (:User)-[:TEACHES]->(:Skill)  <- user_skills WHERE skill_type='TEACH'
              (:User)-[:WANTS]->(:Skill)    <- user_skills WHERE skill_type='LEARN'
              (:User)-[:MENTORS]->(:User)   <- swap_sessions WHERE status='completed'

MENTORS is never stored in PostgreSQL. It is *derived* here from who actually
completed a session with whom - which is the whole point of keeping it in a
graph: the relationship has no column anywhere, only two joins.
"""

import argparse
import pathlib
import sys

try:  # normalise imports for both `python scripts/x.py` and `import scripts.x`
    from .config import neo4j_driver, pg_connect
except ImportError:  # pragma: no cover
    from config import neo4j_driver, pg_connect

CYPHER_DIR = pathlib.Path(__file__).resolve().parent.parent / "cypher"
BATCH = 500

# --- PostgreSQL reads -------------------------------------------------------
SQL_USERS = """
    SELECT user_id, name, email, role, department
    FROM users
    ORDER BY user_id
"""

SQL_SKILLS = """
    SELECT skill_id, name, description
    FROM skills
    ORDER BY skill_id
"""

SQL_USER_SKILLS = """
    SELECT user_id, skill_id, skill_type
    FROM user_skills
    ORDER BY user_skill_id
"""

SQL_MENTORS = """
    SELECT DISTINCT provider_id, learner_id
    FROM swap_sessions
    WHERE status = 'completed' AND provider_id <> learner_id
    ORDER BY provider_id, learner_id
"""

# --- Neo4j writes (MERGE + parameters only, never string concatenation) -----
Q_USER = """
UNWIND $rows AS row
MERGE (u:User {user_id: row.user_id})
SET u.name       = row.name,
    u.email      = row.email,
    u.role       = row.role,
    u.department = row.department
"""

Q_SKILL = """
UNWIND $rows AS row
MERGE (s:Skill {skill_id: row.skill_id})
SET s.name        = row.name,
    s.description = row.description
"""

Q_TEACHES = """
UNWIND $rows AS row
MATCH (u:User {user_id: row.user_id})
MATCH (s:Skill {skill_id: row.skill_id})
MERGE (u)-[:TEACHES]->(s)
"""

Q_WANTS = """
UNWIND $rows AS row
MATCH (u:User {user_id: row.user_id})
MATCH (s:Skill {skill_id: row.skill_id})
MERGE (u)-[:WANTS]->(s)
"""

Q_MENTORS = """
UNWIND $rows AS row
MATCH (p:User {user_id: row.provider_id})
MATCH (l:User {user_id: row.learner_id})
MERGE (p)-[:MENTORS]->(l)
"""

COUNT_USERS = "MATCH (u:User) RETURN count(u) AS n"
COUNT_SKILLS = "MATCH (s:Skill) RETURN count(s) AS n"
COUNT_RELS = """
MATCH (:User)-[r:TEACHES]->(:Skill) RETURN count(r) AS n
"""
COUNT_WANTS = "MATCH (:User)-[r:WANTS]->(:Skill) RETURN count(r) AS n"
COUNT_MENTORS = "MATCH (:User)-[r:MENTORS]->(:User) RETURN count(r) AS n"


def _split_statements(text):
    """Split a .cypher file into runnable statements, dropping `//` comments."""
    without_comments = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("//")
    )
    return [stmt.strip() for stmt in without_comments.split(";") if stmt.strip()]


def apply_constraints(driver, verbose=True):
    """Run cypher/01_constraints.cypher so MERGE has unique keys to match on."""
    path = CYPHER_DIR / "01_constraints.cypher"
    if not path.exists():  # pragma: no cover
        if verbose:
            print(f"! {path} not found, skipping constraints")
        return 0

    applied = 0
    with driver.session() as session:
        for stmt in _split_statements(path.read_text()):
            session.run(stmt).consume()
            applied += 1
            if verbose:
                print(f"  constraint applied: {' '.join(stmt.split())[:72]}")
    return applied


def _batched(rows, size=BATCH):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _write(driver, query, rows, label):
    if not rows:
        print(f"  {label:<10} 0 rows (nothing to write)")
        return 0
    with driver.session() as session:
        for chunk in _batched(rows):
            session.run(query, rows=chunk).consume()
    print(f"  {label:<10} {len(rows)} row(s) merged")
    return len(rows)


def sync(verbose=True):
    """Pull from PostgreSQL, push to Neo4j. Returns a stats dict."""
    pg = pg_connect()
    try:
        with pg.cursor() as cur:
            cur.execute(SQL_USERS)
            users = [dict(zip(("user_id", "name", "email", "role", "department"), r))
                     for r in cur.fetchall()]
            cur.execute(SQL_SKILLS)
            skills = [dict(zip(("skill_id", "name", "description"), r)) for r in cur.fetchall()]
            cur.execute(SQL_USER_SKILLS)
            user_skills = [dict(zip(("user_id", "skill_id", "skill_type"), r))
                           for r in cur.fetchall()]
            cur.execute(SQL_MENTORS)
            mentors = [dict(zip(("provider_id", "learner_id"), r)) for r in cur.fetchall()]
    finally:
        pg.close()

    teaches = [r for r in user_skills if r["skill_type"] == "TEACH"]
    wants = [r for r in user_skills if r["skill_type"] == "LEARN"]

    driver = neo4j_driver()
    try:
        if verbose:
            print("Applying graph constraints...")
        apply_constraints(driver, verbose=verbose)

        if verbose:
            print("Merging nodes and relationships...")
        _write(driver, Q_USER, users, "users")
        _write(driver, Q_SKILL, skills, "skills")
        _write(driver, Q_TEACHES, teaches, "TEACHES")
        _write(driver, Q_WANTS, wants, "WANTS")
        _write(driver, Q_MENTORS, mentors, "MENTORS")

        with driver.session() as session:
            stats = {
                "users": session.run(COUNT_USERS).single()["n"],
                "skills": session.run(COUNT_SKILLS).single()["n"],
                "teaches": session.run(COUNT_RELS).single()["n"],
                "wants": session.run(COUNT_WANTS).single()["n"],
                "mentors": session.run(COUNT_MENTORS).single()["n"],
            }
    finally:
        driver.close()

    if verbose:
        print("-" * 52)
        print("Neo4j now holds:")
        for key, value in stats.items():
            print(f"  {key:<8} {value}")
    return stats


DEMO_QUERIES = [
    (
        "Direct mentor chain (A -> B -> C)",
        "MATCH (a:User)-[:MENTORS]->(b:User)-[:MENTORS]->(c:User) "
        "RETURN a.name AS mentor, b.name AS mentor2, c.name AS mentee LIMIT 10",
    ),
    (
        "Multi-hop mentors (1..3 hops)",
        "MATCH p = (a:User)-[:MENTORS*1..3]->(b:User) RETURN length(p) AS hops LIMIT 10",
    ),
    (
        "Skill exchange chain (A teaches X, B wants X, B teaches Y, C wants Y)",
        "MATCH (a:User)-[:TEACHES]->(x:Skill), (b:User)-[:WANTS]->(x), "
        "(b)-[:TEACHES]->(y:Skill), (c:User)-[:WANTS]->(y) "
        "WHERE a <> b AND b <> c AND c <> a "
        "RETURN a.name AS a, x.name AS x, b.name AS b, y.name AS y, c.name AS c LIMIT 10",
    ),
]


def show_demo_queries():
    driver = neo4j_driver()
    try:
        for title, query in DEMO_QUERIES:
            print("-" * 68)
            print(title)
            with driver.session() as session:
                rows = session.run(query)
                keys = rows.keys()
                print("  " + " | ".join(keys))
                found = 0
                for record in rows:
                    print("  " + " | ".join(str(record[k]) for k in keys))
                    found += 1
                if not found:
                    print("  (no rows)")
    finally:
        driver.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--demo-queries",
        action="store_true",
        help="also run the three demo queries from cypher/02_demo_queries.cypher",
    )
    args = parser.parse_args(argv)
    print("=" * 68)
    print("PostgreSQL -> Neo4j sync")
    print("=" * 68)
    stats = sync()
    print("=" * 68)
    print("Neo4j Browser: http://localhost:7474  (neo4j / skillmesh123)")
    print("Load cypher/02_demo_queries.cypher there for the full graph demo.")
    if args.demo_queries:
        show_demo_queries()
    return 0 if stats["users"] > 0 and stats["teaches"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
