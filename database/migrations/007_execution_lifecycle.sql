ALTER TABLE active_trades
    ADD COLUMN IF NOT EXISTS entry_order_type VARCHAR(16) DEFAULT 'market',
    ADD COLUMN IF NOT EXISTS stop_policy VARCHAR(64),
    ADD COLUMN IF NOT EXISTS stop_invalidation DECIMAL(20,8),
    ADD COLUMN IF NOT EXISTS exit_policy_version VARCHAR(32) NOT NULL DEFAULT 'legacy_full',
    ADD COLUMN IF NOT EXISTS min_order_notional_usdt DECIMAL(12,4) NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS remaining_fraction DECIMAL(8,6) NOT NULL DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS realized_profit_percent DECIMAL(12,6) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS realized_profit_usdt DECIMAL(12,6) NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS trade_target_fills (
    id BIGSERIAL PRIMARY KEY,
    active_trade_id INTEGER NOT NULL REFERENCES active_trades(id),
    signal_id INTEGER REFERENCES signals(id),
    symbol VARCHAR(20) NOT NULL,
    target_number INTEGER NOT NULL CHECK (target_number BETWEEN 1 AND 3),
    fill_price DECIMAL(20,8) NOT NULL,
    quantity_fraction DECIMAL(8,6) NOT NULL CHECK (quantity_fraction > 0),
    notional_usdt DECIMAL(12,4) NOT NULL,
    gross_profit_percent_contribution DECIMAL(12,6) NOT NULL,
    gross_profit_usdt DECIMAL(12,6) NOT NULL,
    filled_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(active_trade_id, target_number)
);

CREATE INDEX IF NOT EXISTS idx_trade_target_fills_trade
    ON trade_target_fills(active_trade_id, target_number);
