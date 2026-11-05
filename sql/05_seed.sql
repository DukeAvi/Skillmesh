-- 05_seed.sql
-- Idempotent-ish seed data for a fresh database (docker-entrypoint-initdb.d runs
-- this exactly once, on an empty pgdata volume).
--
-- IMPORTANT: user_skills.embedding is intentionally left NULL here. Embeddings
-- are generated in Python by scripts/seed_postgres.py using
-- all-MiniLM-L6-v2, because a real transformer model has no business being
-- hard-coded in SQL.

-- ---------------------------------------------------------------------------
-- 5 skill categories
-- ---------------------------------------------------------------------------
INSERT INTO skill_categories (name) VALUES
    ('Programming'),
    ('Languages'),
    ('Music'),
    ('Math'),
    ('Sports');

-- ---------------------------------------------------------------------------
-- 10 skills spread across all 5 categories
-- ---------------------------------------------------------------------------
INSERT INTO skills (category_id, name, description) VALUES
    ((SELECT category_id FROM skill_categories WHERE name = 'Programming'),
     'Python Programming',
     'Writing clean Python: data structures, functions, files and the standard library.'),
    ((SELECT category_id FROM skill_categories WHERE name = 'Programming'),
     'C++ Systems Programming',
     'Pointers, memory management, RAII and modern C++ (11/14/17/20) for competitive coding.'),
    ((SELECT category_id FROM skill_categories WHERE name = 'Programming'),
     'Machine Learning',
     'Supervised and unsupervised learning, scikit-learn, and a gentle intro to neural networks.'),
    ((SELECT category_id FROM skill_categories WHERE name = 'Languages'),
     'Spanish',
     'Conversational Spanish: greetings, past tense, and everyday campus vocabulary.'),
    ((SELECT category_id FROM skill_categories WHERE name = 'Music'),
     'Guitar',
     'Acoustic and electric guitar: chords, strumming patterns and fingerpicking.'),
    ((SELECT category_id FROM skill_categories WHERE name = 'Music'),
     'Piano',
     'Keyboard fundamentals, scales, sight-reading and basic music theory.'),
    ((SELECT category_id FROM skill_categories WHERE name = 'Math'),
     'Linear Algebra',
     'Vectors, matrices, eigenvalues, matrix decompositions and how they show up in ML.'),
    ((SELECT category_id FROM skill_categories WHERE name = 'Math'),
     'Calculus',
     'Limits, derivatives, integrals and their use in optimisation and physics.'),
    ((SELECT category_id FROM skill_categories WHERE name = 'Sports'),
     'Badminton',
     'Footwork, grip, smash technique and doubles rotation for beginners and intermediates.'),
    ((SELECT category_id FROM skill_categories WHERE name = 'Sports'),
     'Basketball',
     'Dribbling, passing, basic man-to-man defence and shooting drills.');

-- ---------------------------------------------------------------------------
-- 6 users (password_hash is a placeholder - there is no auth in this project)
-- ---------------------------------------------------------------------------
INSERT INTO users (name, email, password_hash, role, department, year_of_study, bio) VALUES
    ('Aarav Sharma',  'aarav.sharma@campus.edu',  'placeholder-hash-aarav',  'student', 'CSE',        3,
     'Third-year CSE student who teaches Python and wants to learn music theory.'),
    ('Diya Patel',    'diya.patel@campus.edu',    'placeholder-hash-diya',   'mentor',  'ECE',        4,
     'Fourth-year ECE student, C++ and linear algebra tutor for the coding club.'),
    ('Rohan Mehta',   'rohan.mehta@campus.edu',   'placeholder-hash-rohan',  'student', 'CSE',        2,
     'Second-year student, speaks Spanish, wants to get better at Python.'),
    ('Ananya Iyer',   'ananya.iyer@campus.edu',   'placeholder-hash-ananya',  'mentor',  'Music',      3,
     'Music department student teaching piano and guitar, learning maths.'),
    ('Kabir Singh',   'kabir.singh@campus.edu',   'placeholder-hash-kabir',  'student', 'Mathematics',2,
     'Mathematics student, calculus tutor, curious about machine learning.'),
    ('Arjun',         'arjun@campus.edu',         'placeholder-hash-arjun',   'admin',   'CSE',        3,
     'SkillMesh administrator and campus skill-swap coordinator.');

-- ---------------------------------------------------------------------------
-- 15 user_skills rows, mixing TEACH and LEARN, with a unique description per
-- row. The description is what gets embedded, so it must describe the person's
-- own take on the skill (that is what makes the vector search meaningful).
-- Embeddings are filled in later by scripts/seed_postgres.py.
-- ---------------------------------------------------------------------------
INSERT INTO user_skills (user_id, skill_id, skill_type, proficiency_level, description) VALUES
    ((SELECT user_id FROM users WHERE email = 'aarav.sharma@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Python Programming'),
     'TEACH', 'advanced',
     'I teach advanced Python programming: functions, classes, generators, debugging and writing clean readable code.'),

    ((SELECT user_id FROM users WHERE email = 'aarav.sharma@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Guitar'),
     'LEARN', 'beginner',
     'I am a beginner at guitar and want to learn chords, strumming patterns and basic fingerpicking.'),

    ((SELECT user_id FROM users WHERE email = 'aarav.sharma@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Calculus'),
     'LEARN', 'beginner',
     'I want to learn calculus from scratch: limits, derivatives and integrals explained slowly.'),

    ((SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'C++ Systems Programming'),
     'TEACH', 'advanced',
     'I teach advanced C++ systems programming covering pointers, memory management, RAII and templates.'),

    ((SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Linear Algebra'),
     'TEACH', 'intermediate',
     'I teach linear algebra to second-years: vectors, matrices, determinants, eigenvalues and matrix decompositions.'),

    ((SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Piano'),
     'LEARN', 'beginner',
     'I want to learn piano basics: scales, note reading and playing simple songs with both hands.'),

    ((SELECT user_id FROM users WHERE email = 'rohan.mehta@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Spanish'),
     'TEACH', 'intermediate',
     'I teach conversational Spanish: greetings, pronunciation, past tense and everyday campus vocabulary.'),

    ((SELECT user_id FROM users WHERE email = 'rohan.mehta@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Python Programming'),
     'LEARN', 'intermediate',
     'I want to improve my Python programming for data analysis - lists, dictionaries, files and numpy.'),

    ((SELECT user_id FROM users WHERE email = 'ananya.iyer@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Piano'),
     'TEACH', 'advanced',
     'I teach advanced piano: scales, arpeggios, sight-reading, chord progressions and music theory.'),

    ((SELECT user_id FROM users WHERE email = 'ananya.iyer@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Guitar'),
     'TEACH', 'intermediate',
     'I teach intermediate guitar: chord shapes, strumming patterns, barre chords and simple fingerpicking.'),

    ((SELECT user_id FROM users WHERE email = 'ananya.iyer@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Linear Algebra'),
     'LEARN', 'intermediate',
     'I want to learn linear algebra to understand matrices better, especially eigenvalues.'),

    ((SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Calculus'),
     'TEACH', 'intermediate',
     'I teach intermediate calculus: limits, derivatives, integration techniques and optimisation problems.'),

    ((SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Machine Learning'),
     'LEARN', 'intermediate',
     'I want to learn machine learning - regression, classification, clustering and scikit-learn in Python.'),

    ((SELECT user_id FROM users WHERE email = 'arjun@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Badminton'),
     'TEACH', 'advanced',
     'I teach badminton: grip, footwork, smash technique, doubles rotation and match strategy.'),

    ((SELECT user_id FROM users WHERE email = 'arjun@campus.edu'),
     (SELECT skill_id FROM skills WHERE name = 'Spanish'),
     'LEARN', 'beginner',
     'I am a beginner at Spanish and want to learn greetings and simple everyday conversation.');

-- ---------------------------------------------------------------------------
-- Requests + slots + completed sessions + feedback.
-- These exist so that the leaderboard view has something to rank and so that
-- scripts/neo4j_sync.py produces real MENTORS edges for the Cypher demo
-- queries. Without completed swap_sessions the graph layer would be empty.
-- ---------------------------------------------------------------------------

INSERT INTO swap_requests (request_id, requester_id, provider_id, skill_id, similarity_score, status) VALUES
    (1, (SELECT user_id FROM users WHERE email = 'rohan.mehta@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'C++ Systems Programming'), 0.81, 'accepted'),
    (2, (SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Linear Algebra'), 0.78, 'accepted'),
    (3, (SELECT user_id FROM users WHERE email = 'aarav.sharma@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'ananya.iyer@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Piano'), 0.74, 'accepted'),
    (4, (SELECT user_id FROM users WHERE email = 'arjun@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'ananya.iyer@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Guitar'), 0.83, 'accepted'),
    (5, (SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'rohan.mehta@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Spanish'), 0.88, 'accepted'),
    (6, (SELECT user_id FROM users WHERE email = 'aarav.sharma@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Calculus'), 0.86, 'accepted');

-- The rows above used explicit ids, so advance the identity sequence NOW,
-- before anything else inserts into this table (scripts/match.py would
-- otherwise collide with request_id = 1).
SELECT setval(pg_get_serial_sequence('swap_requests', 'request_id'),
              (SELECT MAX(request_id) FROM swap_requests));

-- Booked slots for the completed sessions. Times are relative to NOW() so the
-- demo data is always "recent". The EXCLUDE constraint only applies to rows
-- with status = 'open', and these ranges do not overlap anyway.
INSERT INTO availability_slots (slot_id, provider_id, skill_id, start_time, end_time, status) VALUES
    (1, (SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'C++ Systems Programming'),
        NOW() - INTERVAL '30 days', NOW() - INTERVAL '30 days' + INTERVAL '2 hours', 'booked'),
    (2, (SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Linear Algebra'),
        NOW() - INTERVAL '28 days', NOW() - INTERVAL '28 days' + INTERVAL '2 hours', 'booked'),
    (3, (SELECT user_id FROM users WHERE email = 'ananya.iyer@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Piano'),
        NOW() - INTERVAL '26 days', NOW() - INTERVAL '26 days' + INTERVAL '2 hours', 'booked'),
    (4, (SELECT user_id FROM users WHERE email = 'ananya.iyer@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Guitar'),
        NOW() - INTERVAL '24 days', NOW() - INTERVAL '24 days' + INTERVAL '2 hours', 'booked'),
    (5, (SELECT user_id FROM users WHERE email = 'rohan.mehta@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Spanish'),
        NOW() - INTERVAL '22 days', NOW() - INTERVAL '22 days' + INTERVAL '2 hours', 'booked'),
    (6, (SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Calculus'),
        NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days' + INTERVAL '2 hours', 'booked');

-- Same story as swap_requests: the booked slots above used explicit ids, so
-- push the sequence past them before inserting the future slots below.
SELECT setval(pg_get_serial_sequence('availability_slots', 'slot_id'),
              (SELECT MAX(slot_id) FROM availability_slots));

-- Still bookable future slots - one per provider, so the exclusion constraint
-- has room to breathe.
INSERT INTO availability_slots (provider_id, skill_id, start_time, end_time, status) VALUES
    ((SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'C++ Systems Programming'),
        NOW() + INTERVAL '7 days', NOW() + INTERVAL '7 days' + INTERVAL '2 hours', 'open'),
    ((SELECT user_id FROM users WHERE email = 'ananya.iyer@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Guitar'),
        NOW() + INTERVAL '8 days', NOW() + INTERVAL '8 days' + INTERVAL '2 hours', 'open'),
    ((SELECT user_id FROM users WHERE email = 'rohan.mehta@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Spanish'),
        NOW() + INTERVAL '9 days', NOW() + INTERVAL '9 days' + INTERVAL '2 hours', 'open');

INSERT INTO swap_sessions (session_id, request_id, provider_id, learner_id, skill_id, slot_id, status, created_at, completed_at) VALUES
    (1, 1, (SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'rohan.mehta@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'C++ Systems Programming'), 1,
        'completed', NOW() - INTERVAL '31 days', NOW() - INTERVAL '30 days'),
    (2, 2, (SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Linear Algebra'), 2,
        'completed', NOW() - INTERVAL '29 days', NOW() - INTERVAL '28 days'),
    (3, 3, (SELECT user_id FROM users WHERE email = 'ananya.iyer@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'aarav.sharma@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Piano'), 3,
        'completed', NOW() - INTERVAL '27 days', NOW() - INTERVAL '26 days'),
    (4, 4, (SELECT user_id FROM users WHERE email = 'ananya.iyer@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'arjun@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Guitar'), 4,
        'completed', NOW() - INTERVAL '25 days', NOW() - INTERVAL '24 days'),
    (5, 5, (SELECT user_id FROM users WHERE email = 'rohan.mehta@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Spanish'), 5,
        'completed', NOW() - INTERVAL '23 days', NOW() - INTERVAL '22 days'),
    (6, 6, (SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'),
        (SELECT user_id FROM users WHERE email = 'aarav.sharma@campus.edu'),
        (SELECT skill_id FROM skills WHERE name = 'Calculus'), 6,
        'completed', NOW() - INTERVAL '21 days', NOW() - INTERVAL '20 days');

INSERT INTO feedback (session_id, reviewer_id, rating, comment) VALUES
    (1, (SELECT user_id FROM users WHERE email = 'rohan.mehta@campus.edu'), 5,
     'Diya explained pointers better than any textbook. Very patient.'),
    (1, (SELECT user_id FROM users WHERE email = 'diya.patel@campus.edu'), 4,
     'Rohan came prepared with questions - great session.'),
    (2, (SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'), 5,
     'Eigenvalues finally clicked. Handwritten notes were a bonus.'),
    (3, (SELECT user_id FROM users WHERE email = 'aarav.sharma@campus.edu'), 4,
     'Good intro to scales, would like a follow-up on chord progressions.'),
    (5, (SELECT user_id FROM users WHERE email = 'kabir.singh@campus.edu'), 5,
     'Rohan teaches Spanish really well and keeps the class fun.'),
    (6, (SELECT user_id FROM users WHERE email = 'aarav.sharma@campus.edu'), 4,
     'Clear derivations and useful exam tips.');

-- ---------------------------------------------------------------------------
-- Final belt-and-braces sequence realignment for the tables that were seeded
-- with explicit ids, so that Python scripts inserting into them (match.py,
-- concurrency_test.py) never collide with the seeded ids.
-- ---------------------------------------------------------------------------
SELECT setval(pg_get_serial_sequence('swap_requests',      'request_id'), (SELECT MAX(request_id)      FROM swap_requests));
SELECT setval(pg_get_serial_sequence('availability_slots',  'slot_id'),     (SELECT MAX(slot_id)         FROM availability_slots));
SELECT setval(pg_get_serial_sequence('swap_sessions',      'session_id'),  (SELECT MAX(session_id)      FROM swap_sessions));
SELECT setval(pg_get_serial_sequence('feedback',           'feedback_id'), (SELECT MAX(feedback_id)     FROM feedback));