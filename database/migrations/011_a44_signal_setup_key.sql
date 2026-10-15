-- A44: idempotent signal emission (A43 design). Additive and backwards compatible:
-- * `signals.setup_key` identifies one actionable setup: one closed candle x setup type x
--   strategy version (shared/signal_identity.py). A partial unique index makes the
--   signal_engine's insert idempotent across concurrent workers, restarts and repeated cycles.
-- * No existing row is rewritten or backfilled: history keeps setup_key NULL (its candle identity
--   is not verifiable for most rows), so recorded duplicates remain recorded evidence and the
--   index never constrains them.
-- * Code from before A44 neither reads nor writes the column (it inserts NULL), so application
--   images can be rolled back without a schema rollback.
-- Locking: ADD COLUMN without a default is metadata-only; the index build on ~16k rows holds a
-- SHARE lock (blocks inserts only) for milliseconds. Fail fast instead of queueing (as in 010).
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE signals ADD COLUMN IF NOT EXISTS setup_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_signals_setup_key
    ON signals (setup_key) WHERE setup_key IS NOT NULL;
