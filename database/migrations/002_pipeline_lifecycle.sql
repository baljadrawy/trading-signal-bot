-- Add observability without changing eligibility or selection behavior.
ALTER TABLE scan_candidates
    ADD COLUMN IF NOT EXISTS processing_status VARCHAR(24) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS failure_reason TEXT;

ALTER TABLE analysis_results
    ADD COLUMN IF NOT EXISTS processing_status VARCHAR(24) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS decision_reason TEXT,
    ADD COLUMN IF NOT EXISTS decision_at TIMESTAMP;

UPDATE scan_candidates
SET processing_status = CASE WHEN analyzed THEN 'analyzed' ELSE 'pending' END,
    processed_at = CASE WHEN analyzed THEN COALESCE(processed_at, scan_time) ELSE processed_at END;

UPDATE analysis_results
SET processing_status = CASE
        WHEN signal_generated THEN 'signal_created'
        WHEN analyzed_at < NOW() - INTERVAL '2 hours' THEN 'expired'
        ELSE 'pending'
    END,
    decision_reason = CASE
        WHEN signal_generated THEN COALESCE(decision_reason, 'signal_created')
        WHEN analyzed_at < NOW() - INTERVAL '2 hours' THEN COALESCE(decision_reason, 'stale_analysis')
        ELSE decision_reason
    END,
    decision_at = CASE
        WHEN signal_generated OR analyzed_at < NOW() - INTERVAL '2 hours'
        THEN COALESCE(decision_at, analyzed_at)
        ELSE decision_at
    END;

CREATE INDEX IF NOT EXISTS idx_scan_candidates_pipeline_pending
    ON scan_candidates(scan_time DESC) WHERE analyzed = false;
CREATE INDEX IF NOT EXISTS idx_analysis_results_pipeline_fresh
    ON analysis_results(analyzed_at DESC, symbol)
    WHERE signal_generated = false;
CREATE INDEX IF NOT EXISTS idx_analysis_results_status
    ON analysis_results(processing_status, analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_review_queue
    ON signals(signal_time DESC)
    WHERE claude_approved IS NULL OR claude_approved = false;
CREATE INDEX IF NOT EXISTS idx_signals_telegram_queue
    ON signals(signal_time DESC)
    WHERE claude_approved = true AND telegram_sent = false;
CREATE INDEX IF NOT EXISTS idx_active_trades_open
    ON active_trades(symbol, opened_at DESC) WHERE status = 'open';
