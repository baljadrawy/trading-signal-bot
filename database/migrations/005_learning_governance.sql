ALTER TABLE signals ADD COLUMN IF NOT EXISTS decision_source VARCHAR(32);
ALTER TABLE signals ADD COLUMN IF NOT EXISTS strategy_version VARCHAR(64);

UPDATE signals
SET decision_source = CASE
    WHEN claude_comment LIKE 'live-learning: auto-approved%' THEN 'policy_auto'
    WHEN claude_comment IS NOT NULL THEN 'claude'
    ELSE 'legacy_unknown'
END
WHERE decision_source IS NULL;

UPDATE signals SET strategy_version = 'legacy' WHERE strategy_version IS NULL;

ALTER TABLE learned_gates ADD COLUMN IF NOT EXISTS strategy_version VARCHAR(64) NOT NULL DEFAULT 'legacy';
ALTER TABLE learned_gates ADD COLUMN IF NOT EXISTS learning_run_id BIGINT;

CREATE TABLE IF NOT EXISTS learning_runs (
    id BIGSERIAL PRIMARY KEY,
    strategy_version VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('validating','applied','rejected','rolled_back')),
    trade_count INTEGER NOT NULL DEFAULT 0,
    cell_count INTEGER NOT NULL DEFAULT 0,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS learned_gate_history (
    id BIGSERIAL PRIMARY KEY,
    learning_run_id BIGINT REFERENCES learning_runs(id),
    action VARCHAR(16) NOT NULL CHECK (action IN ('insert','update','expire','rollback')),
    trade_type VARCHAR NOT NULL,
    macro_state VARCHAR NOT NULL,
    timeframe VARCHAR NOT NULL,
    old_value JSONB,
    new_value JSONB,
    strategy_version VARCHAR(64) NOT NULL,
    changed_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gate_history_run ON learned_gate_history(learning_run_id, id);
CREATE INDEX IF NOT EXISTS idx_gate_history_cell ON learned_gate_history(trade_type, macro_state, timeframe, changed_at DESC);

DO $$ BEGIN
    ALTER TABLE learned_gates
        ADD CONSTRAINT learned_gates_learning_run_fk
        FOREIGN KEY (learning_run_id) REFERENCES learning_runs(id) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
