-- 04_skill_popularity_view.sql
-- Demand and supply metrics for every catalogue skill, including unused skills.
-- A positive demand_gap means more users want to learn the skill than teach it.

CREATE OR REPLACE VIEW skill_popularity AS
WITH supply AS (
    SELECT skill_id,
           COUNT(DISTINCT user_id) AS teachers
    FROM user_skills
    WHERE skill_type = 'TEACH'
    GROUP BY skill_id
),
demand AS (
    SELECT skill_id,
           COUNT(DISTINCT user_id) AS learners
    FROM user_skills
    WHERE skill_type = 'LEARN'
    GROUP BY skill_id
),
completed AS (
    SELECT skill_id,
           COUNT(*) AS completed_sessions
    FROM swap_sessions
    WHERE status = 'completed'
    GROUP BY skill_id
)
SELECT s.skill_id,
       s.name AS skill_name,
       c.name AS category_name,
       COALESCE(sup.teachers, 0) AS teachers,
       COALESCE(dem.learners, 0) AS learners,
       COALESCE(com.completed_sessions, 0) AS completed_sessions,
       COALESCE(dem.learners, 0) - COALESCE(sup.teachers, 0) AS demand_gap,
       DENSE_RANK() OVER (
           ORDER BY COALESCE(dem.learners, 0) DESC
       ) AS demand_rank
FROM skills s
LEFT JOIN skill_categories c ON c.category_id = s.category_id
LEFT JOIN supply sup ON sup.skill_id = s.skill_id
LEFT JOIN demand dem ON dem.skill_id = s.skill_id
LEFT JOIN completed com ON com.skill_id = s.skill_id;
