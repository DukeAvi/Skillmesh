-- 04_leaderboard_view.sql
-- A single ranked leaderboard combining two *independent* aggregations:
--   taught  -> completed sessions where the user was the provider
--   learned -> completed sessions where the user was the learner
-- The two CTEs are joined back onto `users` with LEFT JOIN so that users with
-- zero completed sessions still appear (with 0, not NULL), and DENSE_RANK()
-- gives ties the same rank -- which is what you want for a leaderboard where
-- 3 users with 4 sessions each should all be rank 1 and the next user rank 2.

CREATE OR REPLACE VIEW leaderboard AS
WITH taught AS (
    SELECT provider_id,
           COUNT(*) AS sessions_taught
    FROM swap_sessions
    WHERE status = 'completed'
    GROUP BY provider_id
),
learned AS (
    SELECT learner_id,
           COUNT(*) AS sessions_learned
    FROM swap_sessions
    WHERE status = 'completed'
    GROUP BY learner_id
),
per_user AS (
    SELECT u.user_id,
           u.name,
           COALESCE(t.sessions_taught,  0) AS sessions_taught,
           COALESCE(l.sessions_learned, 0) AS sessions_learned
    FROM users u
    LEFT JOIN taught t ON t.provider_id = u.user_id
    LEFT JOIN learned l ON l.learner_id  = u.user_id
)
SELECT user_id,
       name,
       sessions_taught,
       sessions_learned,
       (sessions_taught + sessions_learned) AS total_sessions,
       DENSE_RANK() OVER (ORDER BY (sessions_taught + sessions_learned) DESC) AS rank
FROM per_user;