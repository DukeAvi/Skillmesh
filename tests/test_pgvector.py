"""pgvector tests: cosine similarity behaves, and the HNSW index really exists.

Run with:  pytest tests/ -v
"""

import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from scripts.config import pg_connect
from scripts.embeddings import backend, embed, embedding_literal
from scripts.match import find_matches

# Two sentences that mean the same thing -> should be close in vector space.
PHRASE_A = "teach advanced python programming and machine learning to beginners"
PHRASE_B = "teaching advanced python programming and machine learning one on one"
# A sentence about baking bread -> should be nowhere near the other two.
PHRASE_C = "sourdough bread baking with wild yeast starters and rye flour"

INSERT_USER = """
    INSERT INTO users (name, email, password_hash, role, department)
    VALUES (%s, %s, 'not-a-real-hash', 'mentor', 'QA')
    RETURNING user_id
"""

INSERT_SKILL = """
    INSERT INTO skills (name, description)
    VALUES (%s, %s)
    RETURNING skill_id
"""

INSERT_USER_SKILL = """
    INSERT INTO user_skills (user_id, skill_id, skill_type, proficiency_level, description, embedding)
    VALUES (%s, %s, 'TEACH', 'advanced', %s, %s::vector)
    RETURNING user_skill_id
"""

COSINE_SQL = """
    SELECT 1 - (a.embedding <=> b.embedding) AS similarity
    FROM user_skills a, user_skills b
    WHERE a.user_skill_id = %s AND b.user_skill_id = %s
"""

CHECK_HNSW_INDEX = "SELECT 1 FROM pg_indexes WHERE indexname='idx_user_skills_embedding'"


@pytest.fixture(scope="module")
def probes():
    """Three probe rows: two semantically close, one unrelated. Cleaned up after."""
    tag = uuid.uuid4().hex[:8]
    skill_name = f"pgvector-probe-{tag}"
    emails = [f"pgvector-{tag}-{i}@campus.test" for i in range(3)]

    conn = pg_connect()
    user_ids, user_skill_ids = [], []
    try:
        with conn.cursor() as cur:
            cur.execute(INSERT_SKILL, (skill_name, "temporary skill used by pytest"))
            skill_id = cur.fetchone()[0]
            for index, email in enumerate(emails):
                cur.execute(INSERT_USER, (f"pgvector probe {index}", email))
                user_id = cur.fetchone()[0]
                user_ids.append(user_id)
                phrase = (PHRASE_A, PHRASE_B, PHRASE_C)[index]
                cur.execute(
                    INSERT_USER_SKILL,
                    (user_id, skill_id, phrase, embedding_literal(embed(phrase))),
                )
                user_skill_ids.append(cur.fetchone()[0])
        yield {"user_ids": user_ids, "user_skill_ids": user_skill_ids, "skill_id": skill_id}
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM skills WHERE name = %s", (skill_name,))
            cur.execute("DELETE FROM users WHERE email = ANY(%s)", (emails,))
        conn.close()


def _cosine(conn, id_a, id_b):
    with conn.cursor() as cur:
        cur.execute(COSINE_SQL, (id_a, id_b))
        return float(cur.fetchone()[0])


def test_embedding_dimension():
    assert len(embed(PHRASE_A)) == 384


def test_similar_phrases_have_high_cosine_similarity(probes):
    conn = pg_connect()
    try:
        similarity = _cosine(conn, probes["user_skill_ids"][0], probes["user_skill_ids"][1])
        print(f"\ncosine(A, B) = {similarity:.4f}   [{backend()}]")
        assert similarity > 0.7, f"expected > 0.7, got {similarity}"
    finally:
        conn.close()


def test_unrelated_phrase_scores_lower(probes):
    conn = pg_connect()
    try:
        similar = _cosine(conn, probes["user_skill_ids"][0], probes["user_skill_ids"][1])
        unrelated = _cosine(conn, probes["user_skill_ids"][0], probes["user_skill_ids"][2])
        print(f"cosine(A, B) = {similar:.4f}   cosine(A, C) = {unrelated:.4f}")
        assert unrelated < similar
    finally:
        conn.close()


def test_hnsw_index_exists():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(CHECK_HNSW_INDEX)
            assert cur.fetchone() is not None, "idx_user_skills_embedding is missing"
    finally:
        conn.close()


def test_hnsw_index_uses_cosine_operator_class():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE indexname='idx_user_skills_embedding'"
            )
            indexdef = cur.fetchone()[0]
            print(f"\n{indexdef}")
            assert "hnsw" in indexdef
            assert "vector_cosine_ops" in indexdef
    finally:
        conn.close()


def test_nearest_neighbour_search_is_ordered(probes):
    """The `<=>` operator used by scripts/match.py ranks the close pair first."""
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT us.user_skill_id,
                       1 - (us.embedding <=> %s::vector) AS similarity
                FROM user_skills us
                WHERE us.user_skill_id IN (%s, %s, %s)
                ORDER BY us.embedding <=> %s::vector
                """,
                (
                    embedding_literal(embed(PHRASE_A)),
                    probes["user_skill_ids"][0],
                    probes["user_skill_ids"][1],
                    probes["user_skill_ids"][2],
                    embedding_literal(embed(PHRASE_A)),
                ),
            )
            ranked = cur.fetchall()
        assert len(ranked) == 3
        assert ranked[0][0] == probes["user_skill_ids"][0]  # itself, similarity 1.0
        assert ranked[1][0] == probes["user_skill_ids"][1]  # the close paraphrase
        assert ranked[-1][0] == probes["user_skill_ids"][2]  # the bread one
        assert ranked[0][1] > ranked[1][1] > ranked[2][1]
    finally:
        conn.close()


def test_application_match_limit_is_honoured():
    """The CLI's --limit value must reach SQL instead of being hard-coded."""
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.user_id, s.skill_id
                FROM users u
                CROSS JOIN skills s
                WHERE u.email = 'aarav.sharma@campus.edu'
                  AND s.name = 'Guitar'
                """
            )
            learner_id, skill_id = cur.fetchone()
        _, matches = find_matches(learner_id, skill_id, limit=3, conn=conn)
        assert len(matches) == 3
    finally:
        conn.close()
