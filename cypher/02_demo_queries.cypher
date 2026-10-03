// 02_demo_queries.cypher
// Read-only demo queries for the Neo4j Browser (http://localhost:7474).
// They assume scripts/neo4j_sync.py has already populated the database with
// :User, :Skill and the TEACHES / WANTS / MENTORS relationships.
//
// -------------------------------------------------------------------------
// 0. Sanity check: how much did the sync actually load?
// -------------------------------------------------------------------------
MATCH (u:User)      RETURN count(u) AS users;
MATCH (s:Skill)     RETURN count(s) AS skills;
MATCH (:User)-[r:TEACHES]->(:Skill) RETURN count(r) AS teaches;
MATCH (:User)-[r:WANTS]->(:Skill)   RETURN count(r) AS wants;
MATCH (:User)-[r:MENTORS]->(:User)  RETURN count(r) AS mentors;

// -------------------------------------------------------------------------
// 1. Direct mentor chain
//    A -> B -> C means "A mentored B and B mentored C", i.e. B is a two-hop
//    mentor of C and, transitively, A is a senior student C could ask.
//    In a relational schema this would be two self-joins on swap_sessions.
// -------------------------------------------------------------------------
MATCH (a:User)-[:MENTORS]->(b:User)-[:MENTORS]->(c:User)
RETURN a.name, b.name, c.name;

// -------------------------------------------------------------------------
// 2. Multi-hop mentors up to 3 hops
//    Variable-length path. The upper bound keeps the expansion finite - this
//    is the classic argument for a graph DB: the shape of the query IS the
//    shape of the traversal, no matter how many joins it needs.
//    The path `p` is returned so the Browser can draw it.
// -------------------------------------------------------------------------
MATCH p = (a:User)-[:MENTORS*1..3]->(b:User)
RETURN p LIMIT 25;

// -------------------------------------------------------------------------
// 3. Skill exchange chain
//    A teaches X, B wants X, B teaches Y, C wants Y -> a three-way barter
//    where each participant both gives and receives something.
//    The a <> b, b <> c, c <> a guards stop a user being matched with
//    themselves (they could hold both a TEACH and a WANT for the same skill).
// -------------------------------------------------------------------------
MATCH (a:User)-[:TEACHES]->(x:Skill),
      (b:User)-[:WANTS]->(x),
      (b)-[:TEACHES]->(y:Skill),
      (c:User)-[:WANTS]->(y)
WHERE a <> b AND b <> c AND c <> a
RETURN a.name, x.name, b.name, y.name, c.name;

// -------------------------------------------------------------------------
// 4. Bonus: who are the most active mentors? (graph-native aggregation)
// -------------------------------------------------------------------------
MATCH (p:User)-[r:MENTORS]->(l:User)
RETURN p.name AS mentor, count(*) AS sessions_mentored
ORDER BY sessions_mentored DESC, mentor
LIMIT 10;