-- 03_indexes.sql
-- Plain B-tree indexes for the columns we actually filter/join on.
-- `idx_user_skills_embedding` is the important one: an HNSW (Hierarchical
-- Navigable Small World) index over the pgvector column using the cosine
-- operator class, so `ORDER BY embedding <=> $1` is answered with an
-- approximate nearest-neighbour search instead of a full table scan.

CREATE INDEX IF NOT EXISTS idx_user_skills_user      ON user_skills(user_id);
CREATE INDEX IF NOT EXISTS idx_user_skills_skill     ON user_skills(skill_id);
CREATE INDEX IF NOT EXISTS idx_user_skills_type      ON user_skills(skill_type);
CREATE INDEX IF NOT EXISTS idx_user_skills_embedding ON user_skills
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_swap_requests_requester ON swap_requests(requester_id);
CREATE INDEX IF NOT EXISTS idx_swap_requests_provider  ON swap_requests(provider_id);
CREATE INDEX IF NOT EXISTS idx_slots_provider          ON availability_slots(provider_id);
CREATE INDEX IF NOT EXISTS idx_sessions_provider       ON swap_sessions(provider_id);
CREATE INDEX IF NOT EXISTS idx_sessions_learner        ON swap_sessions(learner_id);
CREATE INDEX IF NOT EXISTS idx_feedback_session        ON feedback(session_id);