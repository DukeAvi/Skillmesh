"""Fill in `user_skills.embedding` for every row that does not have one yet.

The seed SQL (sql/05_seed.sql) deliberately leaves the vector NULL: generating
embeddings is a Python/ML job, not a SQL job. Run this once after
`docker compose up -d`:

    python scripts/seed_postgres.py

Re-running is safe - rows that already have an embedding are skipped, unless
you pass --force.
"""

import argparse
import sys

try:  # normalise imports for both `python scripts/x.py` and `import scripts.x`
    from .config import pg_connect
    from .embeddings import backend, embed, embedding_literal
except ImportError:  # pragma: no cover
    from config import pg_connect
    from embeddings import backend, embed, embedding_literal

SELECT_MISSING = """
    SELECT us.user_skill_id, u.name, s.name, us.skill_type, us.description
    FROM user_skills us
    JOIN users u  ON u.user_id  = us.user_id
    JOIN skills s ON s.skill_id = us.skill_id
    WHERE us.embedding IS NULL
    ORDER BY us.user_skill_id
"""

UPDATE_ONE = "UPDATE user_skills SET embedding = %s::vector WHERE user_skill_id = %s"


def build_text(skill_name, description):
    """The string that actually gets embedded.

    The skill name anchors the vector in the right region of the space; the
    user-written description says what this particular person brings to it.
    """
    parts = [skill_name.strip(), (description or "").strip()]
    return " : ".join(p for p in parts if p)


def seed_embeddings(force=False, conn=None):
    own_conn = conn is None
    conn = conn or pg_connect()
    try:
        sql = SELECT_MISSING if not force else SELECT_MISSING.replace(
            "WHERE us.embedding IS NULL", ""
        )
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()

            if not rows:
                print("Nothing to do: every user_skills row already has an embedding.")
                return 0

            print(f"Embedding backend : {backend()}")
            print(f"Rows needing an embedding: {len(rows)}")
            for user_skill_id, user_name, skill_name, skill_type, description in rows:
                text = build_text(skill_name, description)
                vector = embed(text)
                assert len(vector) == 384, f"expected 384 dims, got {len(vector)}"
                cur.execute(UPDATE_ONE, (embedding_literal(vector), user_skill_id))
                print(
                    f"  [{user_skill_id:>3}] {user_name:<14} {skill_type:<5} "
                    f"{skill_name:<26} dim={len(vector)}"
                )
        print(f"Done. {len(rows)} embedding(s) written.")
        return len(rows)
    finally:
        if own_conn:
            conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force",
        action="store_true",
        help="recompute embeddings for every row, not just the NULL ones",
    )
    args = parser.parse_args(argv)
    seed_embeddings(force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())