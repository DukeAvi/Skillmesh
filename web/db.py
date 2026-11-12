"""Small PostgreSQL query and JSON serialization helpers."""

from decimal import Decimal
from scripts.config import pg_connect


def query(sql, params=()):
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [col.name for col in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def json_value(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
