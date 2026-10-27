"""Central configuration for every script.

Values come from the environment (a local `.env` is loaded automatically, see
`.env.example`). Each setting has a working default that matches
`docker-compose.yml`, so the project runs with zero configuration.

Connections always point at `localhost` because the Docker ports are published
to the host; the containers themselves talk over the compose network and never
use these variables.
"""

import os

try:  # pragma: no cover - trivial import shim
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

if load_dotenv is not None:
    # .env next to the project root (one level above scripts/)
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

# --- PostgreSQL -------------------------------------------------------------
PG_DSN = os.getenv("PG_DSN", "postgresql://skillmesh:skillmesh@localhost:5432/skillmesh")

# --- Neo4j ------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASS", "skillmesh123")

# --- Redis ------------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6380"))

# --- Embeddings -------------------------------------------------------------
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

# --- Presence ---------------------------------------------------------------
PRESENCE_TTL = int(os.getenv("PRESENCE_TTL", "60"))


def pg_connect(**kwargs):
    """Open a psycopg3 connection.

    `autocommit=True` is the default on purpose: each script then owns its
    transactions explicitly via `with conn.transaction():`, which is what makes
    the `SELECT ... FOR UPDATE` locking behaviour in scripts/book.py
    unambiguous. Pass `autocommit=False` if you want classic driver-managed
    transactions.
    """
    import psycopg

    kwargs.setdefault("autocommit", True)
    return psycopg.connect(PG_DSN, **kwargs)


def neo4j_driver():
    from neo4j import GraphDatabase

    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))


def redis_client():
    import redis

    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
