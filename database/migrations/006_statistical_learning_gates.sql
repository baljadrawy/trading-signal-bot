ALTER TABLE learned_gates ADD COLUMN IF NOT EXISTS ci_low NUMERIC;
ALTER TABLE learned_gates ADD COLUMN IF NOT EXISTS ci_high NUMERIC;
ALTER TABLE learned_gates ADD COLUMN IF NOT EXISTS sample_start TIMESTAMP;
ALTER TABLE learned_gates ADD COLUMN IF NOT EXISTS sample_end TIMESTAMP;

-- Existing point-estimate gates were learned from mixed/contaminated history. Keep their
-- audit history, but fail open until a clean statistically-valid cycle replaces them.
UPDATE learned_gates
SET weight=1.0, ci_low=NULL, ci_high=NULL, learning_run_id=NULL,
    strategy_version='pre-statistical-reset', updated_at=NOW();
