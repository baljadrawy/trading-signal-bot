-- database/migrate_live_learning_2026_06_25.sql
ALTER TABLE signals ADD COLUMN IF NOT EXISTS trade_type VARCHAR;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS macro_snapshot JSONB;

CREATE TABLE IF NOT EXISTS macro_history (
    date DATE PRIMARY KEY,
    usdt_d NUMERIC,
    btc_d NUMERIC,
    btc_trend VARCHAR,
    eth_trend VARCHAR,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS learned_gates (
    trade_type VARCHAR,
    macro_state VARCHAR,
    timeframe VARCHAR,
    n INT DEFAULT 0,
    wr NUMERIC,
    expectancy NUMERIC,
    weight NUMERIC DEFAULT 1.0,
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (trade_type, macro_state, timeframe)
);
