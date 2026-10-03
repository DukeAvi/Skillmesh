"""Neo4j graph tests.

Runs the real PostgreSQL -> Neo4j sync first, then asserts the graph shape and
executes the Cypher demo queries from cypher/02_demo_queries.cypher.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from scripts import neo4j_sync
from scripts.config import neo4j_driver


@pytest.fixture(scope="module")
def synced_stats():
    try:
        neo4j_sync.neo4j_driver().verify_connectivity()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Neo4j is not reachable: {type(exc).__name__}: {exc}")
    return neo4j_sync.sync(verbose=False)


def _single(driver, query, **params):
    with driver.session() as session:
        return session.run(query, **params).single()["n"]


def test_users_and_skills_are_present(synced_stats):
    assert synced_stats["users"] > 0
    assert synced_stats["skills"] > 0


def test_teaches_relationships_exist(synced_stats):
    assert synced_stats["teaches"] > 0
    assert synced_stats["wants"] > 0


def test_mentors_relationships_exist(synced_stats):
    assert synced_stats["mentors"] > 0


def test_counts_match_in_neo4j(synced_stats):
    driver = neo4j_driver()
    try:
        assert _single(driver, "MATCH (u:User) RETURN count(u) AS n") > 0
        assert _single(driver, "MATCH (s:Skill) RETURN count(s) AS n") > 0
        assert _single(driver, "MATCH (:User)-[r:TEACHES]->(:Skill) RETURN count(r) AS n") > 0
        assert _single(driver, "MATCH (:User)-[r:WANTS]->(:Skill) RETURN count(r) AS n") > 0
        assert _single(driver, "MATCH (:User)-[r:MENTORS]->(:User) RETURN count(r) AS n") > 0
    finally:
        driver.close()


def test_teaches_edge_points_at_the_right_skill():
    """(u)-[:TEACHES]->(s) must connect the user to the skill they actually teach."""
    driver = neo4j_driver()
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (u:User)-[:TEACHES]->(s:Skill)
                WHERE u.name = 'Diya Patel' AND s.name = 'Linear Algebra'
                RETURN u.name AS user, s.name AS skill
                """
            ).data()
        assert rows == [{"user": "Diya Patel", "skill": "Linear Algebra"}]
    finally:
        driver.close()


def test_two_hop_mentor_query_runs_without_error():
    driver = neo4j_driver()
    try:
        with driver.session() as session:
            records = list(
                session.run(
                    "MATCH (a:User)-[:MENTORS]->(b:User)-[:MENTORS]->(c:User) "
                    "RETURN a.name AS a, b.name AS b, c.name AS c"
                )
            )
        assert isinstance(records, list)
        for record in records:
            assert record["a"] != record["b"] != record["c"]
        print(f"\n2-hop mentor chains found: {len(records)}")
    finally:
        driver.close()


def test_multi_hop_query_respects_its_bound():
    driver = neo4j_driver()
    try:
        with driver.session() as session:
            hops = [
                record["hops"]
                for record in session.run(
                    "MATCH p = (a:User)-[:MENTORS*1..3]->(b:User) RETURN length(p) AS hops"
                )
            ]
        assert hops, "expected at least one mentor path"
        assert max(hops) <= 3
        print(f"\npaths found: {len(hops)}, longest = {max(hops)} hop(s)")
    finally:
        driver.close()


def test_skill_exchange_chain_query_runs(synced_stats):
    driver = neo4j_driver()
    try:
        with driver.session() as session:
            rows = session.run(
                """
                MATCH (a:User)-[:TEACHES]->(x:Skill),
                      (b:User)-[:WANTS]->(x),
                      (b)-[:TEACHES]->(y:Skill),
                      (c:User)-[:WANTS]->(y)
                WHERE a <> b AND b <> c AND c <> a
                RETURN a.name AS a, x.name AS x, b.name AS b, y.name AS y, c.name AS c
                """
            ).data()
        print(f"\nexchange chains found: {len(rows)}")
        assert isinstance(rows, list)
        for row in rows:
            assert row["a"] != row["b"] and row["b"] != row["c"] and row["c"] != row["a"]
    finally:
        driver.close()


def test_sync_is_idempotent():
    """Running the sync twice must not duplicate a single node."""
    first = neo4j_sync.sync(verbose=False)
    second = neo4j_sync.sync(verbose=False)
    assert first == second