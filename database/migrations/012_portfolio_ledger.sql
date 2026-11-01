-- WP-E03 (PR-C04, R7.c): persistence for the event-sourced portfolio ledger of
-- shared/portfolio_ledger.py (PORTFOLIO_RISK_AND_COMPOUNDING.md §3). Additive and backwards compatible:
-- * only new objects: three tables, two trigger functions, their triggers and indexes. No existing
--   table, column, constraint, index or row is touched, so code from before 012 runs unchanged on
--   this schema and application images can be rolled back without a schema rollback;
-- * nothing writes these tables until the shadow writer (WP-E04) is wired and enabled. WP-E04 is
--   gated on PR-OD1 (Paper genesis) and PR-OD2 (genesis amount). shared/schema.py keeps
--   REQUIRED_SCHEMA_VERSION = 11: no service needs these tables to start;
-- * re-running the body is a no-op (IF NOT EXISTS / OR REPLACE).
-- Ledger invariants held by the database, beside the library's own checks (shared/ledger_store.py
-- replays and re-verifies every hash on load):
-- * PR-I12 append-only: UPDATE, DELETE and TRUNCATE are refused by triggers on all three tables.
--   The table owner or a superuser can still disable a trigger, so the writer role must also be
--   denied UPDATE/DELETE/TRUNCATE by privilege (R-5 least-privilege roles; not applied here);
-- * PR-I7 idempotency: (ledger_id, event_id) is unique. A repeated event_id is recorded in
--   portfolio_ledger_repeats as a no-op (identical payload) or a conflict (F7.ledger_event_conflict);
-- * PR-I8 hash chain and PR-I14 order: an insert must extend its ledger by exactly one entry
--   (sequence = previous + 1, prev_state_hash = previous state_hash, the all-zero GENESIS_HASH at
--   sequence 1, as_of not before the previous entry), and the first entry is a Deposit;
-- * one ledger books one cost model (§3.1 item 5): the composite key to the ledger header;
-- * corrections (§3.3 CORRECTION, PR-I12) must reference an earlier entry and carry an approval
--   reference. The library emits no correction today; the store refuses to read one.
-- Money is exact: event payloads and deltas are canonical decimal strings (never float), and
-- money_quantum is kept as text so its exponent survives.
-- Locking: every statement creates or replaces an object of this migration only. Fail fast instead
-- of queueing (as in 010 and 011).
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS portfolio_ledgers (
    ledger_id TEXT PRIMARY KEY CHECK (length(btrim(ledger_id)) > 0),
    quote_asset TEXT NOT NULL CHECK (length(btrim(quote_asset)) > 0),
    cost_model_id TEXT NOT NULL
        CHECK (cost_model_id IN ('legacy_tracker_v1', 'research_baseline_v1', 'research_stress_v1')),
    money_quantum TEXT NOT NULL
        CHECK (money_quantum ~ '^[0-9]+(\.[0-9]+)?([Ee][+-]?[0-9]+)?$' AND money_quantum::numeric > 0),
    ledger_version TEXT NOT NULL CHECK (length(btrim(ledger_version)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ledger_id, cost_model_id)
);

CREATE TABLE IF NOT EXISTS portfolio_ledger_entries (
    ledger_id TEXT NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence >= 1),
    entry_id TEXT NOT NULL UNIQUE,
    event_id TEXT NOT NULL CHECK (length(btrim(event_id)) > 0),
    event_type TEXT NOT NULL CHECK (event_type IN ('Deposit', 'Reserve', 'ReleaseReservation',
                                                   'EntryFill', 'ExitFill', 'Mark', 'Correction')),
    as_of TIMESTAMPTZ NOT NULL,
    cost_model_id TEXT NOT NULL,
    subject_id TEXT,                -- intent_id or position_id; NULL for Deposit and Mark
    symbol TEXT,                    -- Reserve and Mark only
    event_payload JSONB NOT NULL CHECK (jsonb_typeof(event_payload) = 'object'),
    event_fingerprint TEXT NOT NULL CHECK (event_fingerprint ~ '^[0-9a-f]{64}$'),
    deltas JSONB NOT NULL CHECK (jsonb_typeof(deltas) = 'object'),
    prev_state_hash TEXT NOT NULL CHECK (prev_state_hash ~ '^[0-9a-f]{64}$'),
    state_hash TEXT NOT NULL CHECK (state_hash ~ '^[0-9a-f]{64}$'),
    corrects_sequence BIGINT,
    approval_ref TEXT CHECK (approval_ref IS NULL OR length(btrim(approval_ref)) > 0),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ledger_id, sequence),
    UNIQUE (ledger_id, event_id),
    CHECK (entry_id = ledger_id || ':' || sequence::text),
    CHECK (event_payload->>'event_id' = event_id),
    CHECK (state_hash <> prev_state_hash),
    CHECK ((event_type = 'Correction') = (corrects_sequence IS NOT NULL)),
    CHECK ((event_type = 'Correction') = (approval_ref IS NOT NULL)),
    CHECK (corrects_sequence IS NULL OR (corrects_sequence >= 1 AND corrects_sequence < sequence)),
    FOREIGN KEY (ledger_id, cost_model_id) REFERENCES portfolio_ledgers (ledger_id, cost_model_id),
    FOREIGN KEY (ledger_id, corrects_sequence) REFERENCES portfolio_ledger_entries (ledger_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_ledger_entries_subject
    ON portfolio_ledger_entries (ledger_id, subject_id, sequence) WHERE subject_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_portfolio_ledger_entries_as_of
    ON portfolio_ledger_entries (ledger_id, as_of);

CREATE TABLE IF NOT EXISTS portfolio_ledger_repeats (
    repeat_id BIGSERIAL PRIMARY KEY,
    ledger_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_fingerprint TEXT NOT NULL CHECK (event_fingerprint ~ '^[0-9a-f]{64}$'),
    outcome TEXT NOT NULL CHECK (outcome IN ('duplicate_noop', 'conflict')),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (ledger_id, event_id) REFERENCES portfolio_ledger_entries (ledger_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_ledger_repeats_event
    ON portfolio_ledger_repeats (ledger_id, event_id);

CREATE OR REPLACE FUNCTION portfolio_ledger_refuse_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'portfolio_ledger_append_only: % on % is refused (PR-I12)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
    RETURN NULL;
END
$$;

CREATE OR REPLACE FUNCTION portfolio_ledger_check_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    prev_hash TEXT;
    prev_as_of TIMESTAMPTZ;
BEGIN
    IF NEW.sequence = 1 THEN
        IF NEW.prev_state_hash <> repeat('0', 64) THEN
            RAISE EXCEPTION 'portfolio_ledger_chain: first entry of % must link to the genesis hash',
                NEW.ledger_id USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.event_type <> 'Deposit' THEN
            RAISE EXCEPTION 'portfolio_ledger_chain: first entry of % must be a Deposit', NEW.ledger_id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    SELECT state_hash, as_of INTO prev_hash, prev_as_of FROM portfolio_ledger_entries
     WHERE ledger_id = NEW.ledger_id AND sequence = NEW.sequence - 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'portfolio_ledger_chain: sequence gap at % of %', NEW.sequence, NEW.ledger_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF prev_hash <> NEW.prev_state_hash THEN
        RAISE EXCEPTION 'portfolio_ledger_chain: hash chain broken at % of %', NEW.sequence, NEW.ledger_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.as_of < prev_as_of THEN
        RAISE EXCEPTION 'portfolio_ledger_chain: time regression at % of %', NEW.sequence, NEW.ledger_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE OR REPLACE TRIGGER trg_portfolio_ledger_entries_append
    BEFORE INSERT ON portfolio_ledger_entries
    FOR EACH ROW EXECUTE FUNCTION portfolio_ledger_check_append();

CREATE OR REPLACE TRIGGER trg_portfolio_ledgers_no_mutation
    BEFORE UPDATE OR DELETE ON portfolio_ledgers
    FOR EACH ROW EXECUTE FUNCTION portfolio_ledger_refuse_mutation();
CREATE OR REPLACE TRIGGER trg_portfolio_ledgers_no_truncate
    BEFORE TRUNCATE ON portfolio_ledgers
    FOR EACH STATEMENT EXECUTE FUNCTION portfolio_ledger_refuse_mutation();

CREATE OR REPLACE TRIGGER trg_portfolio_ledger_entries_no_mutation
    BEFORE UPDATE OR DELETE ON portfolio_ledger_entries
    FOR EACH ROW EXECUTE FUNCTION portfolio_ledger_refuse_mutation();
CREATE OR REPLACE TRIGGER trg_portfolio_ledger_entries_no_truncate
    BEFORE TRUNCATE ON portfolio_ledger_entries
    FOR EACH STATEMENT EXECUTE FUNCTION portfolio_ledger_refuse_mutation();

CREATE OR REPLACE TRIGGER trg_portfolio_ledger_repeats_no_mutation
    BEFORE UPDATE OR DELETE ON portfolio_ledger_repeats
    FOR EACH ROW EXECUTE FUNCTION portfolio_ledger_refuse_mutation();
CREATE OR REPLACE TRIGGER trg_portfolio_ledger_repeats_no_truncate
    BEFORE TRUNCATE ON portfolio_ledger_repeats
    FOR EACH STATEMENT EXECUTE FUNCTION portfolio_ledger_refuse_mutation();

-- ROLLBACK. Run it only on a disposable database; on any other database it is a Class B operation.
-- It removes every object above and deletes all ledger history, so export the three tables first.
-- No existing object depends on these, so nothing else changes. tests/test_ledger_migration_db.py
-- runs the block between the markers verbatim.
-- rollback:begin
-- DROP TABLE IF EXISTS portfolio_ledger_repeats;
-- DROP TABLE IF EXISTS portfolio_ledger_entries;
-- DROP TABLE IF EXISTS portfolio_ledgers;
-- DROP FUNCTION IF EXISTS portfolio_ledger_check_append();
-- DROP FUNCTION IF EXISTS portfolio_ledger_refuse_mutation();
-- DO $rb$ BEGIN
--     IF to_regclass('schema_migrations') IS NOT NULL THEN
--         DELETE FROM schema_migrations WHERE version = 12;
--     END IF;
-- END $rb$;
-- rollback:end
