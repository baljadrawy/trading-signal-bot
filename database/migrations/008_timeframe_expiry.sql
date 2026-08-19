ALTER TABLE active_trades
    ADD COLUMN IF NOT EXISTS expiry_policy_version VARCHAR(32),
    ADD COLUMN IF NOT EXISTS expiry_h DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS t1_expiry_h DECIMAL(10,2),
    ADD COLUMN IF NOT EXISTS no_t1_expiry_h DECIMAL(10,2);

-- Existing rows intentionally remain NULL and retain the legacy 48/24/24 policy.
