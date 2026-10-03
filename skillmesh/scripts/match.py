"""Semantic skill matching with pgvector.

Given a learner who marked skill S as LEARN, find the users who marked S (or
something semantically close) as TEACH, ranked by cosine distance.

    python scripts/match.py --learner 1 --skill 6
    python scripts/match.py --learner 1 --skill 6 --create-request

The query below is the whole point of the project: `us.embedding <=> %s` is
pgvector's cosine-distance operator, and `ORDER BY` on it is what the HNSW
index (sql/03_indexes.sql) accelerates.
"""

import argparse
import sys

try:  # normalise imports for both `python scripts/x.py` and `import scripts.x`
    from .config import pg_connect
    from .embeddings import embed, embedding_literal
except ImportError:  # pragma: no cover
    from config import pg_connect
    from embeddings import embed, embedding_literal

FETCH_LEARNER_EMBEDDING = """
    SELECT us.user_skill_id, us.skill_id, s.name AS skill_name, us.embedding::text
    FROM user_skills us
    JOIN skills s ON s.skill_id = us.skill_id
    WHERE us.user_id = %s AND us.skill_id = %s AND us.skill_type = 'LEARN'
"""

MATCH_SQL = """
    SELECT us.user_skill_id, us.user_id, u.name, us.skill_id,
           1 - (us.embedding <=> %s) AS similarity
    FROM user_skills us
    JOIN users u ON u.user_id = us.user_id
    WHERE us.skill_type = 'TEACH'
      AND us.user_id <> %s
    ORDER BY us.embedding <=> %s
    LIMIT 10;
"""

INSERT_REQUEST = """
    INSERT INTO swap_requests (requester_id, provider_id, skill_id, similarity_score, status)
    VALUES (%s, %s, %s, %s, 'pending')
    RETURNING request_id, status
"""


def find_matches(learner_id, skill_id, limit=10, conn=None):
    """Return the ranked TEACH matches for a learner/skill pair."""
    own_conn = conn is None
    conn = conn or pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(FETCH_LEARNER_EMBEDDING, (learner_id, skill_id))
            row = cur.fetchone()
            if row is None:
                raise LookupError(
                    f"user {learner_id} has no LEARN row for skill {skill_id}. "
                    "Run `python scripts/seed_postgres.py` first if embeddings are missing."
                )
            user_skill_id, skill_id, skill_name, embedding_text = row
            if not embedding_text:
                raise LookupError(
                    "that user_skills row has a NULL embedding - run "
                    "`python scripts/seed_postgres.py` first."
                )

            query_vector = embedding_literal(embed(skill_name))

            cur.execute(MATCH_SQL, (query_vector, learner_id, query_vector))
            return skill_name, cur.fetchall()
    finally:
        if own_conn:
            conn.close()


def create_swap_request(learner_id, provider_id, skill_id, similarity, conn=None):
    """Persist the top match as a pending swap_request."""
    own_conn = conn is None
    conn = conn or pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(INSERT_REQUEST, (learner_id, provider_id, skill_id, float(similarity)))
            return cur.fetchone()
    finally:
        if own_conn:
            conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--learner", type=int, required=True, help="learner user_id")
    parser.add_argument("--skill", type=int, required=True, help="skill_id they want to LEARN")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--create-request",
        action="store_true",
        help="also insert a pending swap_request for the top match",
    )
    args = parser.parse_args(argv)

    skill_name, matches = find_matches(args.learner, args.skill, args.limit)
    if not matches:
        print(f"No TEACH rows found for '{skill_name}'.")
        return 1

    print(f"\nSkill '{skill_name}' - who could teach it to user {args.learner}\n")
    print(f"{'#':>2}  {'user_id':>7}  {'name':<16}  {'skill_id':>8}  {'cosine similarity'}")
    print("-" * 66)
    for rank, (user_skill_id, user_id, name, matched_skill_id, similarity) in enumerate(matches, 1):
        print(
            f"{rank:>2}  {user_id:>7}  {name:<16}  {matched_skill_id:>8}  {similarity:.4f}"
        )

    top = matches[0]
    print(f"\nBest match: {top[2]} (user_id={top[1]}) at cosine similarity {top[4]:.4f}")

    if args.create_request:
        created = create_swap_request(args.learner, top[1], top[3], top[4])
        print(f"Created swap_request {created[0]} with status '{created[1]}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())