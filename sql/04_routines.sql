-- 04_routines.sql
-- Exactly two PostgreSQL functions and two PostgreSQL procedures.
--
-- Functions are read-only calculations queried with SELECT. Procedures are
-- business operations invoked with CALL. CREATE OR REPLACE makes this file
-- safe to apply both during first-time Docker initialisation and manually to
-- an already-running database.

-- ---------------------------------------------------------------------------
-- FUNCTION 1: vector-ranked teachers for one learner/skill
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_find_skill_matches(
    p_learner_id BIGINT,
    p_skill_id   BIGINT,
    p_limit      INTEGER DEFAULT 5
)
RETURNS TABLE (
    provider_id       BIGINT,
    provider_name     TEXT,
    matched_skill_id  BIGINT,
    matched_skill     TEXT,
    similarity        DOUBLE PRECISION
)
LANGUAGE sql
STABLE
AS $$
    WITH learner AS (
        SELECT us.embedding
        FROM user_skills us
        WHERE us.user_id = p_learner_id
          AND us.skill_id = p_skill_id
          AND us.skill_type = 'LEARN'
          AND us.embedding IS NOT NULL
        ORDER BY us.user_skill_id
        LIMIT 1
    )
    SELECT teacher.user_id,
           u.name,
           teacher.skill_id,
           s.name,
           1 - (teacher.embedding <=> learner.embedding) AS similarity
    FROM learner
    CROSS JOIN user_skills teacher
    JOIN users u  ON u.user_id = teacher.user_id
    JOIN skills s ON s.skill_id = teacher.skill_id
    WHERE teacher.skill_type = 'TEACH'
      AND teacher.user_id <> p_learner_id
      AND teacher.embedding IS NOT NULL
    ORDER BY teacher.embedding <=> learner.embedding,
             teacher.user_skill_id
    LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 5), 50));
$$;

-- ---------------------------------------------------------------------------
-- FUNCTION 2: average rating received by a provider on completed sessions
-- Self-authored feedback is excluded. 0.00 means that no learner has rated
-- the provider yet.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_provider_average_rating(p_provider_id BIGINT)
RETURNS NUMERIC(4,2)
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(ROUND(AVG(f.rating)::NUMERIC, 2), 0.00)::NUMERIC(4,2)
    FROM swap_sessions ss
    JOIN feedback f ON f.session_id = ss.session_id
    WHERE ss.provider_id = p_provider_id
      AND ss.status = 'completed'
      AND f.reviewer_id <> ss.provider_id;
$$;

-- ---------------------------------------------------------------------------
-- PROCEDURE 1: create a valid pending request and return its new id
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_create_swap_request(
    IN    p_requester_id     BIGINT,
    IN    p_provider_id      BIGINT,
    IN    p_skill_id         BIGINT,
    IN    p_similarity_score REAL,
    INOUT p_new_request_id   BIGINT DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_requester_id = p_provider_id THEN
        RAISE EXCEPTION 'requester and provider must be different users'
            USING ERRCODE = '23514';
    END IF;

    IF p_similarity_score IS NOT NULL
       AND (p_similarity_score < -1 OR p_similarity_score > 1) THEN
        RAISE EXCEPTION 'similarity score must be between -1 and 1'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM user_skills
        WHERE user_id = p_requester_id
          AND skill_id = p_skill_id
          AND skill_type = 'LEARN'
    ) THEN
        RAISE EXCEPTION 'requester % does not have a LEARN entry for skill %',
            p_requester_id, p_skill_id
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM user_skills
        WHERE user_id = p_provider_id
          AND skill_id = p_skill_id
          AND skill_type = 'TEACH'
    ) THEN
        RAISE EXCEPTION 'provider % does not have a TEACH entry for skill %',
            p_provider_id, p_skill_id
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO swap_requests (
        requester_id, provider_id, skill_id, similarity_score, status
    )
    VALUES (
        p_requester_id, p_provider_id, p_skill_id, p_similarity_score, 'pending'
    )
    RETURNING request_id INTO p_new_request_id;
END;
$$;

-- ---------------------------------------------------------------------------
-- PROCEDURE 2: finish one scheduled session
-- The guarded UPDATE prevents an already completed/cancelled session from
-- being completed again.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE sp_complete_swap_session(
    IN p_session_id   BIGINT,
    IN p_completed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_updated_session_id BIGINT;
BEGIN
    IF p_completed_at IS NULL THEN
        RAISE EXCEPTION 'completion time cannot be NULL'
            USING ERRCODE = '23502';
    END IF;

    UPDATE swap_sessions
    SET status = 'completed',
        completed_at = p_completed_at
    WHERE session_id = p_session_id
      AND status = 'scheduled'
    RETURNING session_id INTO v_updated_session_id;

    IF v_updated_session_id IS NULL THEN
        RAISE EXCEPTION 'session % does not exist or is not scheduled', p_session_id
            USING ERRCODE = 'P0001';
    END IF;
END;
$$;

