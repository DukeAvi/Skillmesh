# SkillMesh — Database Layer

A **database-only** demonstration of four storage paradigms working together:

| Store | Paradigm | What it proves |
|---|---|---|
| PostgreSQL 16 | relational | normalised schema, transactions, 2 functions, 2 procedures, constraints, indexes, and a CTE + window-function view |
| pgvector 0.8 | vector similarity inside PostgreSQL | 384-dim embeddings, cosine distance, HNSW index, semantic skill matching |
| Neo4j 5 Community | graph | `MERGE`-based sync from PostgreSQL, mentor chains, multi-hop and barter queries |
| Redis 7 | key-value with TTL | presence heartbeat with `SETEX`, expiry instead of a boolean column |

There is **no web app, no REST API and no frontend**. The deliverables are the
databases plus scripts that prove they work. The audit, demo commands, speaking
notes, and viva Q&A are in [`playbook.md`](playbook.md).

---

## 1. Prerequisites

* **WSL2** running **Ubuntu 22.04+**
* **Docker Engine + Docker Compose v2** inside WSL2 (`docker compose`, not `docker-compose`)
* **Python 3.11+**
* ~2 GB free disk (the `sentence-transformers` dependency pulls in PyTorch; the
  model itself is ~80 MB)

Check everything at once:

```bash
docker --version && docker compose version && python3 --version
```

Optional: copy `.env.example` to `.env`. **You do not need it** — every setting
in `scripts/config.py` already defaults to the values `docker-compose.yml` uses.

```bash
cp .env.example .env
```

> `.gitignore` already excludes `.env` and the local `.venv/` (~1 GB of
> PyTorch), so `git add .` is safe. `.env.example` is the tracked template.
> Database data lives in Docker named volumes, not in this tree.

---

## 2. Start the databases

```bash
docker compose up -d
```

Wait for all three healthchecks to turn healthy (~20 s the first time, because
PostgreSQL has to run `sql/*.sql`):

```bash
docker compose ps          # postgres / neo4j / redis  ->  (healthy)
```

The `postgres` service mounts `./sql` at `/docker-entrypoint-initdb.d`, so on the
**first** start of an empty `pgdata` volume it runs, in order:
`01_extensions.sql` → `02_schema.sql` → `03_indexes.sql` →
`04_leaderboard_view.sql` → `04_routines.sql` → `05_seed.sql`.

To re-run the seed from scratch later:

```bash
docker compose down -v && docker compose up -d     # -v destroys the named volumes
```

### Where to look

| Thing | URL / port | Credentials |
|---|---|---|
| Neo4j Browser | http://localhost:7474 | `neo4j` / `skillmesh123` |
| Neo4j Bolt | `bolt://localhost:7687` | `neo4j` / `skillmesh123` |
| PostgreSQL | `localhost:5432` | `skillmesh` / `skillmesh` (db `skillmesh`) |
| Redis | `localhost:6380` | — |

```bash
# psql
docker compose exec postgres psql -U skillmesh -d skillmesh
# cypher-shell
docker compose exec neo4j cypher-shell -u neo4j -p skillmesh123
# redis-cli
docker compose exec redis redis-cli
```

---

## 3. Install the Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Or without a venv: `pip install -r requirements.txt`.

> First run downloads PyTorch (~200 MB CPU wheel) and the `all-MiniLM-L6-v2`
> model. If the machine is offline, `scripts/embeddings.py` automatically falls
> back to a deterministic lexical vectoriser so the scripts and tests still run
> (cosine scores become lexical rather than semantic).

---

## 4. Run the demo

```bash
# Once before the demo
./demo prepare
./demo cleanup

# Short, presenter-friendly sections
./demo app
./demo postgres
./demo race
./demo match
./demo presence
./demo graph
./demo tests
```

`./demo app` is a CLI-style product walkthrough: it creates a user, adds a new
catalogue skill, registers `TEACH` and `LEARN` skills, finds a teacher, and
creates a pending request. It leaves those rows available for inspection;
`./demo cleanup` removes only that walkthrough data and preserves the seed.

To manually add your own user and find a match, run the interactive command:

```bash
./demo add-user
```

It starts PostgreSQL if necessary, prompts for the user and skill, creates or
updates both rows, generates all missing embeddings, and prints semantic
matches. Mentors default to `TEACH` and are matched with learners; other roles
default to `LEARN` and are matched with teachers. Use `--skill-type` to override
that default. Add `--create-request` to a `LEARN` entry to persist a pending
request for the best teacher who offers that exact skill. Every prompt is also
available as a flag for repeatable use:

```bash
./demo add-user \
  --name "Alex Johnson" \
  --email "alex.johnson@campus.edu" \
  --password-hash "demo-placeholder-hash" \
  --role student \
  --department "Computer Science" \
  --year-of-study 2 \
  --bio "Interested in learning guitar." \
  --skill-type LEARN \
  --skill Guitar \
  --proficiency beginner \
  --description "I want to learn chords, strumming, and fingerpicking."
```

Continue the manual workflow with separate commands:

```bash
./demo find-match --user "alex.johnson@campus.edu" --skill Guitar
./demo create-request --learner "alex.johnson@campus.edu" --skill Guitar
./demo accept-request --provider "Ananya Iyer"
```

`create-request` lists exact-skill teachers and defaults to the best one.
`accept-request` first lists teachers with pending requests, accepts a teacher
user ID, name, or email, then prompts for the request ID. Without flags, the
learner commands first list users with `LEARN` skills and use the same selection
style. Run `./demo <command>
--help` for its complete option list. The project
has no authentication layer, so `--password-hash` remains a demo placeholder
rather than a real password.

Use `./demo all` to rehearse the CLI journey and five database-proof sections
continuously; it cleans up the journey data before the fixed-seed proofs. See
[`playbook.md`](playbook.md) for what to say and what each section proves.
The runner uses `.venv` automatically and starts the project Redis container on
host port `6380`, avoiding a host Redis that may already use `6379`.

The individual scripts remain available for development and custom arguments.
For example, this persists a request for the top match:

```bash
python scripts/match.py --learner 1 --skill 5 --create-request
```

Optional — book one of the still-open slots yourself:

```bash
docker compose exec postgres psql -U skillmesh -d skillmesh -c \
  "SELECT slot_id, provider_id, skill_id, start_time, status
     FROM availability_slots WHERE status = 'open';"

# provider_id and skill_id must match the slot's own row
python scripts/book.py --slot 7 --request 7 --provider 2 --learner 1 --skill 2
```

Run it twice: the second attempt prints `Booking refused: slot not open`.
Booking consumes the slot, so restore it with `docker compose down -v && docker compose up -d`
(or re-run `python scripts/seed_postgres.py` afterwards to refill the embeddings).

---

## 5. What "PASS" looks like

```
$ python scripts/concurrency_test.py
  thread 0: SUCCESS  session_id=8
  thread 1: FAILED   slot not open
successful bookings : 1 (expected 1)
failed bookings     : 1 (expected 1, 'slot not open')
swap_sessions rows  : 1 (expected 1)
final slot status   : booked (expected booked)
RESULT: PASS

$ python scripts/redis_presence.py
  [PASS] heartbeat() creates online:{id}        EXISTS -> 1
  [PASS] TTL is between 1 and 60                TTL -> 60s
  [PASS] heartbeat() refreshes the TTL          5s -> 60s
  [PASS] deleted key means offline              EXISTS -> 0
  [PASS] key name is 'online:1'                 key -> 'online:1'
RESULT: PASS
```

---

## 6. Manual checks against the schema

```bash
docker compose exec postgres psql -U skillmesh -d skillmesh -c '\dt'   # 8 tables
docker compose exec postgres psql -U skillmesh -d skillmesh -c '\dv'   # leaderboard view
docker compose exec postgres psql -U skillmesh -d skillmesh -c '\dx'   # vector + btree_gist

# exactly 2 functions + 2 procedures
docker compose exec postgres psql -U skillmesh -d skillmesh -c \
  "SELECT routine_name, routine_type FROM information_schema.routines
   WHERE routine_schema='public' AND routine_name IN
   ('fn_find_skill_matches', 'fn_provider_average_rating',
    'sp_create_swap_request', 'sp_complete_swap_session')
   ORDER BY routine_type, routine_name;"

# HNSW index
docker compose exec postgres psql -U skillmesh -d skillmesh -c \
  "SELECT indexdef FROM pg_indexes WHERE indexname='idx_user_skills_embedding';"
```

Constraint proofs (all four must print `ERROR`):

```bash
# 1. overlapping OPEN slots for the same provider -> rejected by the EXCLUDE constraint
docker compose exec postgres psql -U skillmesh -d skillmesh -c "
INSERT INTO availability_slots (provider_id, skill_id, start_time, end_time)
SELECT provider_id, skill_id, start_time + INTERVAL '30 min', start_time + INTERVAL '90 min'
FROM availability_slots WHERE status = 'open' LIMIT 1;"

# 2. duplicate feedback (session_id, reviewer_id) -> rejected by UNIQUE
docker compose exec postgres psql -U skillmesh -d skillmesh -c "
INSERT INTO feedback (session_id, reviewer_id, rating)
SELECT session_id, reviewer_id, 3 FROM feedback LIMIT 1;"

# 3. two sessions on one slot -> rejected by UNIQUE(slot_id)
docker compose exec postgres psql -U skillmesh -d skillmesh -c "
INSERT INTO swap_sessions (request_id, provider_id, learner_id, skill_id, slot_id)
SELECT request_id, provider_id, learner_id, skill_id, slot_id FROM swap_sessions LIMIT 1;"
```

Cypher demo queries: open http://localhost:7474 and paste the contents of
[`cypher/02_demo_queries.cypher`](cypher/02_demo_queries.cypher), or apply the
constraints from the CLI:

```bash
docker compose exec -T neo4j cypher-shell -u neo4j -p skillmesh123 \
  < cypher/01_constraints.cypher
```

(`scripts/neo4j_sync.py` already applies those constraints itself.)

---

## 7. Repository layout

```
skillmesh/
├── docker-compose.yml      # postgres (pgvector/pgvector:pg16) + neo4j + redis
├── .env.example            # optional overrides; scripts/config.py has defaults
├── README.md               # this file
├── playbook.md             # audited demo script + speaking notes + viva Q&A
├── requirements.txt
├── sql/
│   ├── 01_extensions.sql   # vector, btree_gist
│   ├── 02_schema.sql       # 8 tables + constraints
│   ├── 03_indexes.sql      # btree indexes + HNSW on user_skills.embedding
│   ├── 04_leaderboard_view.sql
│   ├── 04_routines.sql     # exactly 2 functions + 2 procedures
│   └── 05_seed.sql         # embedding column deliberately left NULL
├── cypher/
│   ├── 01_constraints.cypher
│   └── 02_demo_queries.cypher
├── scripts/
│   ├── config.py           # env-driven settings + connection factories
│   ├── embeddings.py       # all-MiniLM-L6-v2 -> 384 floats (offline fallback)
│   ├── seed_postgres.py    # fill NULL embeddings
│   ├── match.py            # pgvector cosine matching + swap_request
│   ├── book.py             # the FOR UPDATE booking transaction
│   ├── concurrency_test.py # 2 threads, 1 slot, 1 winner
│   ├── neo4j_sync.py       # PostgreSQL -> Neo4j with MERGE
│   ├── redis_presence.py   # SETEX heartbeat + TTL cycle
│   └── leaderboard.py      # pretty-print the view
└── tests/
    ├── test_pgvector.py
    ├── test_concurrency.py
    ├── test_presence.py
    ├── test_graph.py
    └── test_routines.py
```

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `the database system is starting up` | PostgreSQL is still running `sql/*.sql`. Wait ~20 s and check `docker compose logs postgres`. |
| Seed data missing after an edit to `sql/` | `docker-entrypoint-initdb.d` only runs on an empty volume: `docker compose down -v && docker compose up -d`. |
| `Relation "user_skills" does not exist` | You are connected to the wrong database/schema. Use `psql -U skillmesh -d skillmesh`. |
| `hnsw` index missing | `sql/03_indexes.sql` did not run — re-initialise the volume as above. |
| `Embedding backend : lexical-fallback` | No network / no PyTorch. Functional but the matching is lexical, not semantic. |
| `Connection refused` from Python | The containers publish to `localhost`; make sure you run the scripts on the host (or inside WSL), not from a different machine. |
| `could not translate host name "localhost"` | You are inside a container already; use the service names `postgres` / `neo4j` / `redis` there. |
| Neo4j auth error | Default is `neo4j` / `skillmesh123`; wipe with `docker compose down -v` if you changed it. |

---

## 9. Teardown

```bash
docker compose down          # stop, keep data
docker compose down -v       # stop and delete pgdata / neo4jdata / redisdata
```
