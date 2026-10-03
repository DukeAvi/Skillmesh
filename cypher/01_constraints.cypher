// 01_constraints.cypher
// Run once per database, either with:
//   docker exec -i skillmesh-neo4j cypher-shell -u neo4j -p skillmesh123 \
//       < cypher/01_constraints.cypher
// or by pasting into the Neo4j Browser at http://localhost:7474
//
// Uniqueness constraints are the graph equivalent of a primary key. They are
// what make `MERGE` in scripts/neo4j_sync.py safe to run repeatedly: MERGE
// matches on the constrained property, so a second sync updates instead of
// creating duplicates.

// One node per PostgreSQL users row.
CREATE CONSTRAINT user_id_unique IF NOT EXISTS
FOR (u:User) REQUIRE u.user_id IS UNIQUE;

// One node per PostgreSQL skills row.
CREATE CONSTRAINT skill_id_unique IF NOT EXISTS
FOR (s:Skill) REQUIRE s.skill_id IS UNIQUE;