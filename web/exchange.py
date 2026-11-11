"""Catalogue reads, skill profiles, matching, and exchange requests."""

from scripts.config import pg_connect
from scripts.embeddings import embed, embedding_literal
from web.db import query, json_value
from web.errors import APIError


def execute_request(payload: dict):
    required = ("requester_id", "provider_id", "skill_id")
    if any(key not in payload for key in required):
        raise ValueError("requester_id, provider_id, and skill_id are required")
    learner_id = int(payload["requester_id"])
    provider_id = int(payload["provider_id"])
    skill_id = int(payload["skill_id"])
    similarity = float(payload.get("similarity_score", 0))
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                    CALL sp_create_swap_request(
                        %s::BIGINT, %s::BIGINT, %s::BIGINT, %s::REAL, NULL::BIGINT
                    )
                """,
                (learner_id, provider_id, skill_id, similarity),
            )
            request_id = cur.fetchone()[0]
            return {"request_id": request_id, "status": "pending"}


def get_payload(path: str, query_string: str):
    if path == "/api/health":
        rows = query("SELECT current_database() AS database, NOW() AS server_time")
        return {"ok": True, **{k: json_value(v) for k, v in rows[0].items()}}
    if path == "/api/skills":
        return query(
            """
                SELECT skill_id, skill_name, category_name, teachers, learners,
                       completed_sessions, demand_gap, demand_rank
                FROM skill_popularity
                ORDER BY demand_rank, skill_name
            """
        )
    if path == "/api/leaderboard":
        return query(
            """
                SELECT rank, user_id, name, sessions_taught, sessions_learned,
                       total_sessions
                FROM leaderboard
                ORDER BY rank, total_sessions DESC, name
                LIMIT 10
            """
        )
    if path == "/api/activity":
        return query(
            """
                SELECT s.name AS skill_name, COUNT(*) AS completed_sessions
                FROM swap_sessions ss
                JOIN skills s ON s.skill_id = ss.skill_id
                WHERE ss.status = 'completed'
                GROUP BY s.name
                ORDER BY completed_sessions DESC, s.name
            """
        )
    raise KeyError(path)


def my_skills(user_id):
    return query(
        """
            SELECT us.user_skill_id, us.skill_id, s.name AS skill_name,
                   us.skill_type, us.proficiency_level, us.description
            FROM user_skills us
            JOIN skills s ON s.skill_id = us.skill_id
            WHERE us.user_id = %s
            ORDER BY us.skill_type, s.name
        """,
        (user_id,),
    )


def matches(learner_id, skill_id):
    return query(
        """
            SELECT provider_id, provider_name, matched_skill_id,
                   matched_skill, similarity,
                   fn_provider_average_rating(provider_id) AS rating
            FROM fn_find_skill_matches(%s::BIGINT, %s::BIGINT, 10)
        """,
        (learner_id, skill_id),
    )


def requests(user_id):
    return query(
        """
            SELECT sr.request_id, sr.status, sr.similarity_score,
                   sr.created_at,
                   sr.requester_id, requester.name AS requester_name,
                   sr.provider_id, provider.name AS provider_name,
                   sr.skill_id, s.name AS skill_name
            FROM swap_requests sr
            JOIN users requester ON requester.user_id = sr.requester_id
            JOIN users provider  ON provider.user_id = sr.provider_id
            JOIN skills s ON s.skill_id = sr.skill_id
            WHERE sr.requester_id = %s OR sr.provider_id = %s
            ORDER BY sr.created_at DESC
        """,
        (user_id, user_id),
    )


def save_skill(user, payload):
    skill_type = str(payload.get("skill_type", "")).upper()
    if skill_type not in ("TEACH", "LEARN"):
        raise APIError("Choose whether you teach or learn this skill", 400)
    try:
        skill_id = int(payload.get("skill_id"))
    except (TypeError, ValueError):
        raise APIError("Choose a valid skill", 400)
    proficiency = payload.get("proficiency_level") or None
    if proficiency not in (None, "beginner", "intermediate", "advanced"):
        raise APIError("Choose a valid proficiency level", 400)
    description = str(payload.get("description", "")).strip()[:500]
    skill_rows = query("SELECT name FROM skills WHERE skill_id = %s", (skill_id,))
    if not skill_rows:
        raise APIError("Skill not found", 404)
    vector = embed(f"{skill_rows[0]['name']} {description} {skill_type}")
    with pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                    INSERT INTO user_skills
                        (user_id, skill_id, skill_type, proficiency_level,
                         description, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s::vector)
                    ON CONFLICT (user_id, skill_id, skill_type)
                    DO UPDATE SET proficiency_level = EXCLUDED.proficiency_level,
                                  description = EXCLUDED.description,
                                  embedding = EXCLUDED.embedding
                    RETURNING user_skill_id
                """,
                (
                    user["user_id"],
                    skill_id,
                    skill_type,
                    proficiency,
                    description or None,
                    embedding_literal(vector),
                ),
            )
            user_skill_id = cur.fetchone()[0]
    return {"user_skill_id": user_skill_id, "status": "saved"}
