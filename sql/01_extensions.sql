-- 01_extensions.sql
-- Extensions are installed before any table is created because 02_schema.sql
-- depends on two of them:
--   vector      -> the `vector(384)` column type used by pgvector
--   btree_gist  -> lets a plain scalar column take part in a GiST exclusion
--                  constraint (availability_slots.provider_id WITH =)
-- Both are idempotent (IF NOT EXISTS) so re-running is harmless.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;