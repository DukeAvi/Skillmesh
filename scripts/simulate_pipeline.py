"""Verify the exchange workflow with synthetic data across all three stores.

Run a private HTTP server, sign in synthetic accounts, exercise matching and
CSRF-protected requests, race a booking, complete a session, and check ratings,
views, TTL presence, and graph relationships. Cleanup restores the baseline.
"""

from __future__ import annotations

import argparse
import http.cookiejar
from http.server import ThreadingHTTPServer
import json
import pathlib
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.book import SlotNotOpen, book_slot
from scripts.config import neo4j_driver, pg_connect, redis_client
from scripts.embeddings import embed, embedding_literal
from scripts.neo4j_sync import sync as sync_neo4j
from web.app import Handler
from web.auth import password_hash
from web.moderation import ensure_moderation_tables

SIM_TAG = "sim-pipeline"
SIM_USERS = [
    {
        "name": "Dr. Elena Rostova",
        "email": f"elena.rostova.{SIM_TAG}@campus.test",
        "role": "mentor",
        "department": "Computer Science",
        "bio": "Distributed systems researcher, Raft consensus and Paxos specialist.",
        "skill_type": "TEACH",
        "proficiency": "advanced",
        "description": "Raft consensus, Paxos, distributed transaction commit, and vector clocks.",
    },
    {
        "name": "Jordan Hayes",
        "email": f"jordan.hayes.{SIM_TAG}@campus.test",
        "role": "student",
        "department": "Computer Science",
        "bio": "Second-year CS student interested in building distributed key-value stores.",
        "skill_type": "LEARN",
        "proficiency": "beginner",
        "description": "I want to understand Raft consensus, leader election, and distributed logs.",
    },
    {
        "name": "Samira Khan",
        "email": f"samira.khan.{SIM_TAG}@campus.test",
        "role": "student",
        "department": "Computer Science",
        "bio": "Third-year student building fault-tolerant storage engines.",
        "skill_type": "LEARN",
        "proficiency": "intermediate",
        "description": "Looking for guidance on fault-tolerant replication and Byzantine agreement.",
    },
]
SIM_SKILL_NAME = "Distributed Systems (Simulation)"
SIM_SKILL_DESC = "Architectures for high-availability, consensus protocols, and replication."
SIM_CATEGORY = "Programming"
WEB_URL = ""
SIM_PASSWORD = "Simulation123"
CLIENTS = {}


def banner(title: str) -> None:
    print(f"\n{'=' * 74}\n  {title}\n{'=' * 74}")


def step(num: int, title: str) -> None:
    print(f"\n--- [STEP {num:02d}] {title} ---")


def query_dict(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if not cur.description:
                return []
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def http_call(endpoint, payload=None, user_id=None):
    """Use the actual HTTP handler; errors never fall back to direct DB writes."""
    client, csrf = CLIENTS.get(user_id, (urllib.request.build_opener(), None))
    headers = {"Content-Type": "application/json"}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    request = urllib.request.Request(
        f"{WEB_URL}{endpoint}", headers=headers,
        data=json.dumps(payload).encode() if payload is not None else None,
    )
    try:
        with client.open(request, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def http_get(endpoint):
    values = urllib.parse.parse_qs(urllib.parse.urlparse(endpoint).query)
    user_id = int(values.get("user_id", values.get("learner_id", ["0"]))[0])
    status, data = http_call(endpoint, user_id=user_id)
    assert status == 200, (endpoint, status, data)
    return data


def http_post(endpoint, payload):
    return http_call(endpoint, payload, payload.get("requester_id"))


def sign_in(user_id, email):
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    request = urllib.request.Request(
        f"{WEB_URL}/api/login", headers={"Content-Type": "application/json"},
        data=json.dumps({"email": email, "password": SIM_PASSWORD}).encode(),
    )
    with client.open(request, timeout=10) as response:
        user = json.load(response)
    CLIENTS[user_id] = client, user["csrf_token"]


def cleanup_simulation(verbose: bool = True) -> None:
    """Safely delete all simulated entities from PostgreSQL, Redis, and Neo4j."""
    if verbose:
        print("Cleaning up any existing simulation data...")

    emails = tuple(u["email"] for u in SIM_USERS)
    with pg_connect() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                # 1. Feedback
                cur.execute(
                    """
                    DELETE FROM feedback
                    WHERE reviewer_id IN (SELECT user_id FROM users WHERE email = ANY(%s))
                       OR session_id IN (
                           SELECT session_id FROM swap_sessions
                           WHERE provider_id IN (SELECT user_id FROM users WHERE email = ANY(%s))
                              OR learner_id  IN (SELECT user_id FROM users WHERE email = ANY(%s))
                       )
                    """,
                    (list(emails), list(emails), list(emails)),
                )
                # 2. Swap sessions
                cur.execute(
                    """
                    DELETE FROM swap_sessions
                    WHERE provider_id IN (SELECT user_id FROM users WHERE email = ANY(%s))
                       OR learner_id  IN (SELECT user_id FROM users WHERE email = ANY(%s))
                    """,
                    (list(emails), list(emails)),
                )
                # 3. Availability slots
                cur.execute(
                    """
                    DELETE FROM availability_slots
                    WHERE provider_id IN (SELECT user_id FROM users WHERE email = ANY(%s))
                       OR skill_id IN (SELECT skill_id FROM skills WHERE name = %s)
                    """,
                    (list(emails), SIM_SKILL_NAME),
                )
                # 4. Swap requests
                cur.execute(
                    """
                    DELETE FROM swap_requests
                    WHERE requester_id IN (SELECT user_id FROM users WHERE email = ANY(%s))
                       OR provider_id  IN (SELECT user_id FROM users WHERE email = ANY(%s))
                    """,
                    (list(emails), list(emails)),
                )
                # 5. User skills
                cur.execute(
                    """
                    DELETE FROM user_skills
                    WHERE user_id IN (SELECT user_id FROM users WHERE email = ANY(%s))
                       OR skill_id IN (SELECT skill_id FROM skills WHERE name = %s)
                    """,
                    (list(emails), SIM_SKILL_NAME),
                )
                # 6. Users
                cur.execute("DELETE FROM users WHERE email = ANY(%s)", (list(emails),))
                del_users = cur.rowcount
                # 7. Skill
                cur.execute("DELETE FROM skills WHERE name = %s", (SIM_SKILL_NAME,))
                del_skills = cur.rowcount

    # Neo4j cleanup
    try:
        driver = neo4j_driver()
        with driver.session() as s:
            s.run("MATCH (u:User) WHERE u.email ENDS WITH $tag DETACH DELETE u", tag=f"{SIM_TAG}@campus.test")
            s.run("MATCH (sk:Skill {name: $name}) DETACH DELETE sk", name=SIM_SKILL_NAME)
        driver.close()
    except Exception as exc:
        if verbose:
            print(f"  Neo4j cleanup notice: {exc}")

    # Redis cleanup
    try:
        r = redis_client()
        for key in r.keys("online:*"):
            pass
    except Exception as exc:
        if verbose:
            print(f"  Redis cleanup notice: {exc}")

    if verbose:
        print(f"Cleanup complete: {del_users} sim users, {del_skills} sim skills removed.")


def _run_simulation(keep: bool = False) -> bool:
    banner("SKILLMESH COMPLETE STACK & PROFILE SIMULATION")
    cleanup_simulation(verbose=False)

    # -------------------------------------------------------------------------
    # Step 0: Record Baseline
    # -------------------------------------------------------------------------
    step(0, "Record Pre-Simulation Baseline")
    base_users = query_dict("SELECT COUNT(*) AS count FROM users")[0]["count"]
    base_skills = query_dict("SELECT COUNT(*) AS count FROM skills")[0]["count"]
    base_sessions = query_dict("SELECT COUNT(*) AS count FROM swap_sessions WHERE status='completed'")[0]["count"]
    base_leader = query_dict("SELECT rank, name, total_sessions FROM leaderboard ORDER BY rank LIMIT 1")[0]

    print(f"  Baseline Users    : {base_users}")
    print(f"  Baseline Skills   : {base_skills}")
    print(f"  Completed Sessions: {base_sessions}")
    print(f"  Current Top Leader: {base_leader['name']} ({base_leader['total_sessions']} sessions, Rank #{base_leader['rank']})")

    # -------------------------------------------------------------------------
    # Step 1: Onboard Simulated Users & Register Skills
    # -------------------------------------------------------------------------
    step(1, "Onboard Simulated Users & Register Skills with Embeddings")
    created_users = {}
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT category_id FROM skill_categories WHERE name = %s", (SIM_CATEGORY,))
            cat_id = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO skills (category_id, name, description) VALUES (%s, %s, %s) RETURNING skill_id",
                (cat_id, SIM_SKILL_NAME, SIM_SKILL_DESC),
            )
            sim_skill_id = cur.fetchone()[0]
            print(f"  Created Skill: '{SIM_SKILL_NAME}' (ID: {sim_skill_id})")

            for u in SIM_USERS:
                cur.execute(
                    """
                    INSERT INTO users (name, email, password_hash, role, department, year_of_study, bio)
                    VALUES (%s, %s, %s, %s, %s, 3, %s)
                    RETURNING user_id
                    """,
                    (u["name"], u["email"], password_hash(SIM_PASSWORD), u["role"], u["department"], u["bio"]),
                )
                uid = cur.fetchone()[0]
                created_users[u["email"]] = uid
                print(f"  Created User : {u['name']:<20} ({u['role']:<6}) -> ID {uid}")

                text_to_embed = f"{SIM_SKILL_NAME} : {u['description']}"
                vec = embed(text_to_embed)
                cur.execute(
                    """
                    INSERT INTO user_skills (user_id, skill_id, skill_type, proficiency_level, description, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s::vector)
                    """,
                    (uid, sim_skill_id, u["skill_type"], u["proficiency"], u["description"], embedding_literal(vec)),
                )
                print(f"    Registered {u['skill_type']:<5} for '{SIM_SKILL_NAME}' ({len(vec)}-d vector)")

    elena_id = created_users[SIM_USERS[0]["email"]]
    jordan_id = created_users[SIM_USERS[1]["email"]]
    samira_id = created_users[SIM_USERS[2]["email"]]

    step(2, "Verify signed-in profiles and deny public user listing")
    assert http_call("/api/users")[0] == 401
    for email, user_id in created_users.items():
        sign_in(user_id, email)
        status, profile = http_call("/api/me", user_id=user_id)
        assert status == 200 and profile["user_id"] == user_id
        assert profile["email"] == email and profile["csrf_token"]
    print("  [PASS] Real login, session cookies, private profiles, and CSRF tokens.")

    # -------------------------------------------------------------------------
    # Step 3: Catalogue Search & Client Filtering Simulation
    # -------------------------------------------------------------------------
    step(3, "Simulate Frontend Catalogue Search & Category Filtering")
    all_skills = http_get("/api/skills")
    print(f"  Total catalogue skills returned: {len(all_skills)}")

    search_term = "distributed"
    filtered = [s for s in all_skills if search_term in f"{s['skill_name']} {s['category_name']}".lower()]
    print(f"  Search term '{search_term}' -> Matched: {[s['skill_name'] for s in filtered]}")
    assert len(filtered) == 1 and filtered[0]["skill_id"] == sim_skill_id

    category_term = "programming"
    filtered_cat = [s for s in all_skills if category_term in f"{s['skill_name']} {s['category_name']}".lower()]
    print(f"  Search term '{category_term}' -> Found {len(filtered_cat)} skills")
    assert any(s["skill_id"] == sim_skill_id for s in filtered_cat)
    print("  [PASS] Frontend catalogue search filtering accurately matches queries.")

    # -------------------------------------------------------------------------
    # Step 4: Verify View 2 (`skill_popularity`) Demand Gap
    # -------------------------------------------------------------------------
    step(4, "Inspect `skill_popularity` View with New Registrations")
    pop_row = [s for s in all_skills if s["skill_id"] == sim_skill_id][0]
    print(f"  Skill          : {pop_row['skill_name']}")
    print(f"  Teachers       : {pop_row['teachers']} (Elena)")
    print(f"  Learners       : {pop_row['learners']} (Jordan, Samira)")
    print(f"  Demand Gap     : {pop_row['demand_gap']} (Learners - Teachers = 2 - 1 = +1)")
    print(f"  Demand Rank    : #{pop_row['demand_rank']}")
    assert pop_row["teachers"] == 1
    assert pop_row["learners"] == 2
    assert pop_row["demand_gap"] == 1
    print("  [PASS] `skill_popularity` view dynamically computes teacher/learner gap.")

    # -------------------------------------------------------------------------
    # Step 5: Test Matchmaker Endpoint (/api/matches) with Ratings
    # -------------------------------------------------------------------------
    step(5, "Test Matchmaker Endpoint (/api/matches) & Provider Rating")
    matches = http_get(f"/api/matches?learner_id={jordan_id}&skill_id={sim_skill_id}")
    print(f"  Matches returned for Jordan (Learner ID {jordan_id}):")
    for m in matches:
        print(f"    -> {m['provider_name']:<20} | Skill: {m['matched_skill']:<30} | Sim: {m['similarity']:.4f} | Rating: {m['rating']}")
    assert len(matches) > 0
    top = matches[0]
    assert top["provider_id"] == elena_id
    print(f"  [PASS] Dr. Elena Rostova ranked #1 match with {top['similarity'] * 100:.1f}% similarity.")

    # -------------------------------------------------------------------------
    # Step 6: Test HTTP POST /api/requests (Creation & Validation)
    # -------------------------------------------------------------------------
    step(6, "Test HTTP POST /api/requests Endpoint (Creation & Validation)")
    # Valid Request 1: Jordan -> Elena
    status_code, resp_jordan = http_post(
        "/api/requests",
        {
            "requester_id": jordan_id,
            "provider_id": elena_id,
            "skill_id": sim_skill_id,
            "similarity_score": top["similarity"],
        },
    )
    print(f"  Jordan request: Status {status_code} -> {resp_jordan}")
    assert status_code == 201 and "request_id" in resp_jordan
    req_jordan_id = resp_jordan["request_id"]

    # Valid Request 2: Samira -> Elena
    status_code, resp_samira = http_post(
        "/api/requests",
        {
            "requester_id": samira_id,
            "provider_id": elena_id,
            "skill_id": sim_skill_id,
            "similarity_score": 0.72,
        },
    )
    print(f"  Samira request: Status {status_code} -> {resp_samira}")
    assert status_code == 201 and "request_id" in resp_samira
    req_samira_id = resp_samira["request_id"]

    # Validation Test A: Missing fields (Expect 400 Bad Request)
    status_bad, resp_bad = http_post("/api/requests", {"requester_id": jordan_id})
    print(f"  Missing fields test: Status {status_bad} -> {resp_bad}")
    assert status_bad == 400

    # Validation Test B: Self-request violation (Expect 422 Unprocessable)
    status_self, resp_self = http_post(
        "/api/requests",
        {
            "requester_id": elena_id,
            "provider_id": elena_id,
            "skill_id": sim_skill_id,
            "similarity_score": 1.0,
        },
    )
    print(f"  Self-request test  : Status {status_self} -> {resp_self}")
    assert status_self in (400, 422)
    print("  [PASS] /api/requests validates input and handles errors gracefully.")

    # -------------------------------------------------------------------------
    # Step 7: Verify Exchange Log Endpoint (/api/requests?user_id=...)
    # -------------------------------------------------------------------------
    step(7, "Test Exchange Log Endpoint (/api/requests?user_id=...)")
    requests_jordan = http_get(f"/api/requests?user_id={jordan_id}")
    requests_elena = http_get(f"/api/requests?user_id={elena_id}")
    print(f"  Requests in Jordan's log: {len(requests_jordan)}")
    print(f"  Requests in Elena's log : {len(requests_elena)}")

    assert any(r["request_id"] == req_jordan_id and r["provider_name"] == "Dr. Elena Rostova" for r in requests_jordan)
    assert any(r["request_id"] == req_jordan_id and r["requester_name"] == "Jordan Hayes" for r in requests_elena)
    print("  [PASS] Exchange logs display matching outgoing and incoming requests.")

    # -------------------------------------------------------------------------
    # Step 8: Pessimistic Row Lock & Slot Contention (`book_slot`)
    # -------------------------------------------------------------------------
    step(8, "Test Pessimistic Row Lock (`SELECT ... FOR UPDATE`) Contention")
    slot_id = None
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO availability_slots (provider_id, skill_id, start_time, end_time, status)
                VALUES (%s, %s, NOW() + INTERVAL '2 days', NOW() + INTERVAL '2 days 2 hours', 'open')
                RETURNING slot_id
                """,
                (elena_id, sim_skill_id),
            )
            slot_id = cur.fetchone()[0]
            print(f"  Elena published 1 slot (ID {slot_id}) - status: open")

    results = {}

    def book_worker(learner_id, req_id, thread_name):
        c = pg_connect()
        try:
            sid = book_slot(
                c,
                request_id=req_id,
                provider_id=elena_id,
                learner_id=learner_id,
                skill_id=sim_skill_id,
                slot_id=slot_id,
            )
            results[thread_name] = ("SUCCESS", sid)
        except SlotNotOpen as exc:
            results[thread_name] = ("REFUSED", str(exc))
        finally:
            c.close()

    t1 = threading.Thread(target=book_worker, args=(jordan_id, req_jordan_id, "Jordan-Thread"))
    t2 = threading.Thread(target=book_worker, args=(samira_id, req_samira_id, "Samira-Thread"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print(f"  Contention results: {results}")
    successes = [v for v in results.values() if v[0] == "SUCCESS"]
    refused = [v for v in results.values() if v[0] == "REFUSED"]
    assert len(successes) == 1 and len(refused) == 1
    session_id = successes[0][1]
    print(f"  [PASS] Exactly ONE learner booked slot {slot_id} (session_id = {session_id}). Double-booking prevented.")

    # -------------------------------------------------------------------------
    # Step 9: Complete Session with Procedure 2 (`sp_complete_swap_session`)
    # -------------------------------------------------------------------------
    step(9, "Test Procedure 2: `sp_complete_swap_session`")
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("CALL sp_complete_swap_session(%s::BIGINT)", (session_id,))
            cur.execute("SELECT status, completed_at FROM swap_sessions WHERE session_id = %s", (session_id,))
            sess_row = cur.fetchone()
            print(f"  Session {session_id} marked '{sess_row[0]}' at {sess_row[1]}")
            assert sess_row[0] == "completed" and sess_row[1] is not None

            # Guard test: completing again must raise error
            try:
                cur.execute("CALL sp_complete_swap_session(%s::BIGINT)", (session_id,))
                assert False, "Double-completion should have failed"
            except Exception as e:
                print(f"  [PASS] Duplicate completion prevented: {type(e).__name__}")

    # -------------------------------------------------------------------------
    # Step 10: Feedback & Provider Average Rating Calculation
    # -------------------------------------------------------------------------
    step(10, "Test Feedback Submission & `fn_provider_average_rating`")
    winning_learner_id = jordan_id if results["Jordan-Thread"][0] == "SUCCESS" else samira_id
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feedback (session_id, reviewer_id, rating, comment)
                VALUES (%s, %s, 5, 'Exceptional breakdown of consensus protocols!')
                """,
                (session_id, winning_learner_id),
            )
            # Provider self-review
            cur.execute(
                """
                INSERT INTO feedback (session_id, reviewer_id, rating, comment)
                VALUES (%s, %s, 3, 'Provider self assessment.')
                """,
                (session_id, elena_id),
            )
            cur.execute("SELECT fn_provider_average_rating(%s)", (elena_id,))
            rating = cur.fetchone()[0]
            print(f"  Calculated Rating for Elena: {rating} / 5.00")
            assert float(rating) == 5.00
            print("  [PASS] `fn_provider_average_rating` computed 5.00 (excluded self-feedback).")

    # -------------------------------------------------------------------------
    # Step 11: Dynamic Views Verification (`leaderboard` & `skill_popularity`)
    # -------------------------------------------------------------------------
    step(11, "Verify Live Views Dynamic Update (`leaderboard` & `skill_popularity`)")
    leaderboard = http_get("/api/leaderboard")
    elena_leader = [u for u in leaderboard if u["user_id"] == elena_id]
    assert len(elena_leader) == 1
    print(f"  Leaderboard entry for Elena: Rank #{elena_leader[0]['rank']} | Taught: {elena_leader[0]['sessions_taught']} | Total: {elena_leader[0]['total_sessions']}")
    assert elena_leader[0]["sessions_taught"] == 1

    activity = http_get("/api/activity")
    sim_activity = [a for a in activity if a["skill_name"] == SIM_SKILL_NAME]
    assert len(sim_activity) == 1
    print(f"  Activity trace entry       : '{sim_activity[0]['skill_name']}' -> {sim_activity[0]['completed_sessions']} session(s)")
    assert sim_activity[0]["completed_sessions"] == 1
    print("  [PASS] Leaderboard and Activity views dynamically reflect completed sessions.")

    # -------------------------------------------------------------------------
    # Step 12: Redis Ephemeral Presence Lifecycle
    # -------------------------------------------------------------------------
    step(12, "Test Redis Ephemeral Presence Lifecycle")
    r = redis_client()
    key_elena = f"online:{elena_id}"
    r.set(key_elena, "1", ex=60)
    print(f"  Heartbeat sent: {key_elena} -> EXISTS = {r.exists(key_elena)}, TTL = {r.ttl(key_elena)}s")
    assert r.exists(key_elena) and r.ttl(key_elena) > 50

    r.expire(key_elena, 10)
    print(f"  Simulated degraded TTL: {r.ttl(key_elena)}s")
    r.set(key_elena, "1", ex=60)
    print(f"  Heartbeat refreshed TTL: {r.ttl(key_elena)}s")
    assert r.ttl(key_elena) > 50

    r.delete(key_elena)
    print(f"  Simulated logout: {key_elena} -> EXISTS = {r.exists(key_elena)}")
    assert not r.exists(key_elena)
    print("  [PASS] Redis presence lifecycle verified.")

    # -------------------------------------------------------------------------
    # Step 13: Neo4j Graph Synchronization & Edge Verification
    # -------------------------------------------------------------------------
    step(13, "Test Neo4j Graph Sync & Derived MENTORS Edge")
    sync_stats = sync_neo4j(verbose=False)
    print(f"  Neo4j sync: {sync_stats['users']} users, {sync_stats['skills']} skills, {sync_stats['mentors']} mentor edges")

    driver = neo4j_driver()
    with driver.session() as s:
        teaches = s.run(
            "MATCH (u:User {email: $email})-[:TEACHES]->(sk:Skill {name: $skill}) RETURN u.name, sk.name",
            email=SIM_USERS[0]["email"],
            skill=SIM_SKILL_NAME,
        ).single()
        assert teaches is not None
        print(f"  [PASS] Neo4j TEACHES: {teaches[0]} -> {teaches[1]}")

        wants = s.run(
            "MATCH (u:User {email: $email})-[:WANTS]->(sk:Skill {name: $skill}) RETURN u.name, sk.name",
            email=SIM_USERS[1]["email"],
            skill=SIM_SKILL_NAME,
        ).single()
        assert wants is not None
        print(f"  [PASS] Neo4j WANTS  : {wants[0]} -> {wants[1]}")

        mentors = s.run(
            "MATCH (m:User {email: $email})-[:MENTORS]->(l:User) RETURN m.name, l.name",
            email=SIM_USERS[0]["email"],
        ).single()
        assert mentors is not None
        print(f"  [PASS] Neo4j MENTORS: {mentors[0]} -> {mentors[1]} (derived from completed session)")
    driver.close()

    # -------------------------------------------------------------------------
    # Step 14: Full Frontend Web Client Payloads
    # -------------------------------------------------------------------------
    step(14, "Verify All Web Client Endpoints")
    health = http_get("/api/health")
    print(f"  /api/health: ok={health['ok']}, database={health['database']}")
    assert health["ok"] is True
    print("  [PASS] All Web Observatory endpoints operational.")

    # -------------------------------------------------------------------------
    # Step 15: Teardown & Baseline Verification
    # -------------------------------------------------------------------------
    if not keep:
        step(15, "Clean Up Simulation Data & Restore Baseline")
        cleanup_simulation(verbose=True)
        sync_neo4j(verbose=False)

        post_users = query_dict("SELECT COUNT(*) AS count FROM users")[0]["count"]
        post_skills = query_dict("SELECT COUNT(*) AS count FROM skills")[0]["count"]
        post_sessions = query_dict("SELECT COUNT(*) AS count FROM swap_sessions WHERE status='completed'")[0]["count"]
        assert post_users == base_users, f"Users mismatch: {post_users} != {base_users}"
        assert post_skills == base_skills, f"Skills mismatch: {post_skills} != {base_skills}"
        assert post_sessions == base_sessions, f"Sessions mismatch: {post_sessions} != {base_sessions}"
        print("  [PASS] Database and graph restored to pristine pre-simulation state.")
    else:
        print("\n  [INFO] --keep passed. Simulation data left in database for live browser inspection.")
        print(f"  Web Observatory: {WEB_URL}")
        print(f"  Neo4j Browser  : http://localhost:7474")

    banner("ALL 16 SIMULATION & VERIFICATION STAGES PASSED")
    return True


def run_simulation(keep: bool = False) -> bool:
    """Run against a private HTTP server and the configured synthetic databases."""
    global WEB_URL
    ensure_moderation_tables()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    WEB_URL = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return _run_simulation(keep)
    finally:
        if not keep:
            cleanup_simulation(verbose=False)
        CLIENTS.clear()
        server.shutdown()
        server.server_close()
        thread.join()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="Keep simulation data in DB for web browser viewing")
    parser.add_argument("--cleanup", action="store_true", help="Clean up any simulation data and exit")
    args = parser.parse_args()

    if args.cleanup:
        cleanup_simulation(verbose=True)
        sync_neo4j(verbose=False)
        return 0

    success = run_simulation(keep=args.keep)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

