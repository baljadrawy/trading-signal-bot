-- Optimizer is disabled, but its schema remains migration-owned for safe future use.
CREATE TABLE IF NOT EXISTS optimizer_settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);
INSERT INTO optimizer_settings (key, value)
VALUES ('min_score_to_signal', '5.0'),
       ('min_timeframe_confirmations', '2')
ON CONFLICT (key) DO NOTHING;
