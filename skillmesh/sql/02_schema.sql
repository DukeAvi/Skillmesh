-- 02_schema.sql
-- Campus Skill-Swap relational model. Tables are created in dependency order.
--
-- There is deliberately NO is_online column on `users`: presence is ephemeral,
-- high-churn state and lives in Redis with a TTL (see scripts/redis_presence.py).
-- There is deliberately NO mentor_relations table either: mentor links are
-- derived from completed swap_sessions and materialised in Neo4j.

-- ---------------------------------------------------------------------------
-- 1. users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id        BIGSERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT 'student'
                   CHECK (role IN ('student', 'mentor', 'admin')),
    department     TEXT,
    year_of_study  INT  CHECK (year_of_study BETWEEN 1 AND 6),
    bio            TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- 2. skill_categories
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS skill_categories (
    category_id  BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------------
-- 3. skills
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS skills (
    skill_id     BIGSERIAL PRIMARY KEY,
    category_id  BIGINT REFERENCES skill_categories(category_id) ON DELETE SET NULL,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT
);

-- ---------------------------------------------------------------------------
-- 4. user_skills  (the many-to-many join, plus the pgvector payload)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_skills (
    user_skill_id      BIGSERIAL PRIMARY KEY,
    user_id            BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    skill_id           BIGINT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    skill_type         TEXT NOT NULL CHECK (skill_type IN ('TEACH', 'LEARN')),
    proficiency_level  TEXT CHECK (proficiency_level IN ('beginner', 'intermediate', 'advanced')),
    description        TEXT,
    embedding          vector(384),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, skill_id, skill_type)
);

-- ---------------------------------------------------------------------------
-- 5. swap_requests
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swap_requests (
    request_id         BIGSERIAL PRIMARY KEY,
    requester_id       BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    provider_id        BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    skill_id           BIGINT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    similarity_score   REAL,
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'accepted', 'rejected', 'cancelled')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (requester_id <> provider_id)
);

-- ---------------------------------------------------------------------------
-- 6. availability_slots
--    The EXCLUDE constraint is the database-level guarantee that a provider
--    can never hold two OPEN slots whose [start, end) ranges overlap.
--    btree_gist supplies the operator class for `provider_id WITH =`.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS availability_slots (
    slot_id     BIGSERIAL PRIMARY KEY,
    provider_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    skill_id    BIGINT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    start_time  TIMESTAMPTZ NOT NULL,
    end_time    TIMESTAMPTZ NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'booked', 'cancelled')),
    CHECK (end_time > start_time),
    EXCLUDE USING gist (
        provider_id WITH =,
        tstzrange(start_time, end_time, '[)') WITH &&
    ) WHERE (status = 'open')
);

-- ---------------------------------------------------------------------------
-- 7. swap_sessions
--    slot_id is UNIQUE -> second line of defence against double booking,
--    independent of the FOR UPDATE lock taken in scripts/book.py.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS swap_sessions (
    session_id   BIGSERIAL PRIMARY KEY,
    request_id   BIGINT NOT NULL REFERENCES swap_requests(request_id) ON DELETE CASCADE,
    provider_id  BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    learner_id   BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    skill_id     BIGINT NOT NULL REFERENCES skills(skill_id) ON DELETE CASCADE,
    slot_id      BIGINT NOT NULL UNIQUE REFERENCES availability_slots(slot_id) ON DELETE RESTRICT,
    status       TEXT NOT NULL DEFAULT 'scheduled'
                 CHECK (status IN ('scheduled', 'completed', 'cancelled')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- ---------------------------------------------------------------------------
-- 8. feedback
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id  BIGSERIAL PRIMARY KEY,
    session_id   BIGINT NOT NULL REFERENCES swap_sessions(session_id) ON DELETE CASCADE,
    reviewer_id  BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    rating       INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment      TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, reviewer_id)
);