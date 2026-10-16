-- A43 PROPOSED migration 011 — NOT in database/migrations/, NOT applied anywhere.
-- Purpose: make signal emission idempotent per setup (one closed candle × setup × strategy version).
-- Requires separate owner approval, a fresh verified backup, and the A43-B integration change.
--
-- Locking: ADD COLUMN (nullable, no default) is metadata-only (brief ACCESS EXCLUSIVE).
-- The unique index on ~16k rows takes a SHARE lock for milliseconds (blocks inserts only meanwhile).
-- Existing rows keep setup_key NULL: historical duplicates stay as recorded evidence (no backfill,
-- no rewrite). Images that do not know the column insert NULL and are unaffected, so rollback by
-- image remains safe; the index never constrains NULLs.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE signals ADD COLUMN IF NOT EXISTS setup_key text;
CREATE UNIQUE INDEX IF NOT EXISTS uq_signals_setup_key
    ON signals (setup_key) WHERE setup_key IS NOT NULL;

-- Rollback (reversible, data-preserving):
--   DROP INDEX IF EXISTS uq_signals_setup_key;
--   ALTER TABLE signals DROP COLUMN IF EXISTS setup_key;   -- optional; NULL-only column is harmless
