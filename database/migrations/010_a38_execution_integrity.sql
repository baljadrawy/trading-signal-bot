-- A38: execution integrity and delivery reliability. Additive and backwards compatible:
-- * no existing row is rewritten. New columns are NULL (or a neutral default) on history,
--   so existing observations are never reinterpreted;
-- * code from before A38 keeps working against this schema (it neither reads nor writes these
--   columns), so application code can be rolled back without a schema rollback.

-- A39: never queue behind a long transaction while holding ACCESS EXCLUSIVE locks on live tables. Fail fast
-- instead; migrate.py runs the file in one transaction, so a timeout rolls everything back (no partial schema).
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- Outbox: a deferral (waiting for a known future state, e.g. the end of an admission window, or
-- a transient channel outage) is not a failed attempt. `deferrals` counts it separately, and
-- `outcome` names the terminal state an event was acked or dead-lettered with.
ALTER TABLE outbox_events
    ADD COLUMN IF NOT EXISTS deferrals INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS outcome VARCHAR(64);

-- Dead-letter monitoring reads new dead letters by the time they died.
CREATE INDEX IF NOT EXISTS idx_outbox_dead_processed
    ON outbox_events(processed_at, id) WHERE status = 'dead';

-- Economic classification. `result` keeps its legacy meaning (gross P&L > 0) because strategy
-- code and history depend on it. The economic label is net of the modeled cost and is stored
-- with the cost and the policy that produced it.
ALTER TABLE trade_results
    ADD COLUMN IF NOT EXISTS cost_usdt NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS net_profit_usdt NUMERIC(12,6),
    ADD COLUMN IF NOT EXISTS economic_result VARCHAR(10)
        CHECK (economic_result IN ('WIN', 'LOSS', 'BREAKEVEN')),
    ADD COLUMN IF NOT EXISTS label_policy VARCHAR(40);

-- Entry fill model that priced each trade (NULL = before A38).
ALTER TABLE active_trades
    ADD COLUMN IF NOT EXISTS entry_fill_model VARCHAR(32);

-- Durable paper entry orders: one per delivered signal, created on its first entry evaluation.
-- It records whether the order arrived marketable or rested at its limit. That decides the fill
-- price, and it survives tracker restarts.
CREATE TABLE IF NOT EXISTS paper_entry_orders (
    signal_id INTEGER PRIMARY KEY REFERENCES signals(id),
    placed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    order_kind VARCHAR(16) NOT NULL CHECK (order_kind IN ('marketable', 'resting')),
    limit_price NUMERIC(20,8) NOT NULL CHECK (limit_price > 0),
    first_observed_price NUMERIC(20,8) NOT NULL CHECK (first_observed_price > 0),
    status VARCHAR(16) NOT NULL DEFAULT 'working'
        CHECK (status IN ('working', 'filled', 'rejected')),
    fill_price NUMERIC(20,8),
    fill_basis VARCHAR(32),
    terminal_reason VARCHAR(64),
    fill_model VARCHAR(32) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
