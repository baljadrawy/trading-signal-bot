-- A59 dashboard: restricted read-only view allowlist (PROPOSAL; apply only with A59 deployment approval).
-- Run as the cluster admin in trading_signals, after roles_v3.sql. Idempotent.
-- tsb_dashboard_ro has NO usage on schema public: it can read these views and nothing else.
-- Deliberately excluded (owner decision required, see report): prices, realized/unrealized P&L, trade results and
-- WIN/LOSS labels, loss-streak counters, target hits and partial-exit fractions, signal features, error texts. These reveal FORWARD_HOLDOUT outcomes or
-- internal details; the allowlist below is operational state only.
CREATE SCHEMA IF NOT EXISTS dashboard;
REVOKE ALL ON SCHEMA dashboard FROM PUBLIC;
GRANT USAGE ON SCHEMA dashboard TO tsb_dashboard_ro;

CREATE OR REPLACE VIEW dashboard.service_health WITH (security_barrier) AS
  SELECT service_name, last_started_at, last_success_at, last_error_at, consecutive_errors, updated_at
  FROM public.service_heartbeats;

CREATE OR REPLACE VIEW dashboard.open_positions WITH (security_barrier) AS
  SELECT id, symbol, timeframe, opened_at, entry_order_type, stop_policy        -- no target/partial-exit progress
  FROM public.active_trades WHERE status = 'open';

CREATE OR REPLACE VIEW dashboard.outbox_health WITH (security_barrier) AS
  SELECT event_type, status, count(*) AS events, min(available_at) AS oldest_available_at,
         max(attempts) AS max_attempts
  FROM public.outbox_events WHERE created_at > now() - interval '7 days'
  GROUP BY event_type, status;

CREATE OR REPLACE VIEW dashboard.signal_flow_hourly WITH (security_barrier) AS
  SELECT date_trunc('hour', signal_time) AS hour, timeframe, count(*) AS signals
  FROM public.signals WHERE signal_time > now() - interval '7 days'
  GROUP BY 1, 2;

CREATE OR REPLACE VIEW dashboard.risk_state WITH (security_barrier) AS
  SELECT date, is_trading_paused, pause_reason
  FROM public.risk_management WHERE date > current_date - 30;

CREATE OR REPLACE VIEW dashboard.schema_version WITH (security_barrier) AS
  SELECT max(version) AS version FROM public.schema_migrations;

REVOKE ALL ON ALL TABLES IN SCHEMA dashboard FROM PUBLIC;
GRANT SELECT ON dashboard.service_health, dashboard.open_positions, dashboard.outbox_health,
  dashboard.signal_flow_hourly, dashboard.risk_state, dashboard.schema_version TO tsb_dashboard_ro;
