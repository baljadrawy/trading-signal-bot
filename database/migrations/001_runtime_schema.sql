-- Canonical runtime schema formerly created ad hoc by long-running services.
CREATE TABLE IF NOT EXISTS scan_candidates (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    data JSONB NOT NULL,
    scan_time TIMESTAMP DEFAULT NOW(),
    analyzed BOOLEAN DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_scan_candidates_analyzed
    ON scan_candidates(analyzed, scan_time DESC);

CREATE TABLE IF NOT EXISTS analysis_results (
    symbol VARCHAR(20) NOT NULL,
    analysis_data JSONB NOT NULL,
    analyzed_at TIMESTAMP DEFAULT NOW(),
    signal_generated BOOLEAN DEFAULT false,
    timeframe VARCHAR(10) DEFAULT '4h'
);
ALTER TABLE analysis_results
    ADD COLUMN IF NOT EXISTS timeframe VARCHAR(10) DEFAULT '4h';
ALTER TABLE analysis_results DROP CONSTRAINT IF EXISTS analysis_results_pkey;
CREATE UNIQUE INDEX IF NOT EXISTS analysis_results_symbol_timeframe_key
    ON analysis_results(symbol, timeframe);

CREATE TABLE IF NOT EXISTS active_trades (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id),
    symbol VARCHAR(20) NOT NULL,
    entry_price DECIMAL(20,8) NOT NULL,
    target_1 DECIMAL(20,8) NOT NULL,
    target_2 DECIMAL(20,8) NOT NULL,
    target_3 DECIMAL(20,8) NOT NULL,
    stop_loss DECIMAL(20,8) NOT NULL,
    timeframe VARCHAR(10),
    is_paper_trade BOOLEAN DEFAULT true,
    opened_at TIMESTAMP DEFAULT NOW(),
    highest_target_hit INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'open'
);
ALTER TABLE active_trades ADD COLUMN IF NOT EXISTS peak_price DECIMAL(20,8);

CREATE TABLE IF NOT EXISTS service_heartbeats (
    service_name VARCHAR(64) PRIMARY KEY,
    last_started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_success_at TIMESTAMP,
    last_error_at TIMESTAMP,
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_service_heartbeats_updated_at
    ON service_heartbeats(updated_at DESC);
