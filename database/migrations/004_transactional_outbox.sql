CREATE TABLE IF NOT EXISTS outbox_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    aggregate_type VARCHAR(32) NOT NULL,
    aggregate_id BIGINT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 8,
    available_at TIMESTAMP NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMP,
    locked_by VARCHAR(128),
    last_error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMP,
    UNIQUE(event_type, aggregate_type, aggregate_id)
);

CREATE INDEX IF NOT EXISTS idx_outbox_claim
    ON outbox_events(event_type, available_at, id)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_outbox_processing_lease
    ON outbox_events(locked_at) WHERE status = 'processing';
CREATE INDEX IF NOT EXISTS idx_outbox_dead
    ON outbox_events(created_at DESC) WHERE status = 'dead';

-- Database idempotency: a signal may create one trade and one terminal result only.
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_trades_signal_id
    ON active_trades(signal_id) WHERE signal_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_results_signal_id
    ON trade_results(signal_id) WHERE signal_id IS NOT NULL;

-- Seed events for work that existed immediately before the outbox deployment.
INSERT INTO outbox_events(event_type, aggregate_type, aggregate_id, payload)
SELECT 'signal.created', 'signal', id, jsonb_build_object('signal_id', id)
FROM signals
WHERE claude_comment IS NULL AND signal_time > NOW() - INTERVAL '2 hours'
ON CONFLICT DO NOTHING;

INSERT INTO outbox_events(event_type, aggregate_type, aggregate_id, payload)
SELECT 'signal.reviewed', 'signal', id,
       jsonb_build_object('signal_id', id, 'approved', claude_approved)
FROM signals
WHERE claude_approved IS NOT NULL AND telegram_sent = false
  AND signal_time > NOW() - INTERVAL '2 hours'
ON CONFLICT DO NOTHING;
