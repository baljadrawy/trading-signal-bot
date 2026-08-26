-- Explicit, auditable recovery boundary for the hard loss-streak halt.
--
-- Before this migration the hard halt at STOP_ON_CONSECUTIVE_LOSSES had no
-- exit once the streak reached the threshold with no open position left to
-- produce a resetting win: admission was refused, so no new trade could close,
-- so the streak could never fall back below the threshold.
--
-- A recovery row moves the *start boundary* of the streak calculation forward.
-- History is never rewritten: trade_results stays byte-identical and the
-- acknowledged incident stays queryable here.
--
-- FAIL-SAFE DEFAULT: an empty table means "no epoch declared", which makes the
-- effective start fall back to LEARNING_CLEAN_START -- exactly the pre-migration
-- behaviour. Applying this migration therefore never clears an active halt.
CREATE TABLE IF NOT EXISTS risk_recovery_events (
    id SERIAL PRIMARY KEY,
    -- Closed trades with exit_time < this boundary stop counting toward the streak.
    epoch_started_at TIMESTAMPTZ NOT NULL,
    acknowledged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Who authorised it (operator principal, not a display name).
    acknowledged_by TEXT NOT NULL,
    -- Mandatory free-text justification: recovery is an acknowledgement, not a reset.
    reason TEXT NOT NULL,
    -- Which halt was acknowledged, and the state at the moment of acknowledgement.
    halt_reason TEXT NOT NULL,
    consecutive_losses_before INTEGER NOT NULL,
    open_positions_at_recovery INTEGER NOT NULL,
    CONSTRAINT risk_recovery_reason_not_blank CHECK (btrim(reason) <> ''),
    CONSTRAINT risk_recovery_actor_not_blank CHECK (btrim(acknowledged_by) <> ''),
    -- Record-integrity assertion ONLY: it pins the value stored in this row.
    -- It does NOT prove the live portfolio was empty -- that guarantee comes
    -- from the shared pg_advisory_xact_lock plus the in-transaction re-read in
    -- shared/risk_epoch.py::record_recovery.
    CONSTRAINT risk_recovery_requires_flat_book CHECK (open_positions_at_recovery = 0)
);

-- The admission path reads the newest boundary on every evaluation.
CREATE INDEX IF NOT EXISTS idx_risk_recovery_epoch
    ON risk_recovery_events (epoch_started_at DESC);
