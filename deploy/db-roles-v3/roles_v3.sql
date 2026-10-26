-- Least-privilege roles for database trading_signals, DESIGN v3 (R-5, 2026-10-17). NOT applied to production.
-- Run as the cluster admin (bootstrap role trading_signal_bot) while connected to trading_signals.
-- trading_signal_bot itself is NOT modified by this file (it stays the break-glass admin and object owner).
-- Passwords are NEVER in this file: they are set separately as SCRAM verifiers (tools/provision_db_credentials.py).
-- Idempotent: safe to re-run. Touches only roles named tsb_* and objects in trading_signals.
--
-- v3 changes against P0 v2 (2026-09-27), each verified against the code the containers run (ea8ae4f + scanner 63b38e7a):
--   * schema 11: tsb_tracker gets SELECT, INSERT, UPDATE on paper_entry_orders (migration 010; no sequence: PK signal_id).
--   * tsb_claude_review removed: the service is retired (CR-2) and absent from compose.
--   * tsb_learner added for continuous_learner (stopped; profile "learner"): NOLOGIN until the owner authorizes a restart.
--     It is the only writer of learned_gate_history, learning_runs and learned_gates (migration 005).
--   * tsb_research_ro is DENY-BY-DEFAULT: v2's "SELECT ON ALL TABLES" exposed the sealed FORWARD_HOLDOUT and is removed.
--     D6 is unresolved: the role gets CONNECT and USAGE only, i.e. it can read no table, view or sequence.
--   * tsb_backup added: read-only dump role (pg_dump of trading_signals). It necessarily reads every row, including the
--     holdout, so it is an operational role: local socket only (pg_hba), never issued to research or dashboards.
--   * tsb_dashboard_ro added for A59: NOLOGIN until A59 deployment is approved; no access to schema public at all.
--     Its view allowlist is in dashboard_v1.sql (separately approved).

DO $$
DECLARE r text;
BEGIN
  -- Runtime services that run today: LOGIN, connection limit 20 (asyncpg pool max 10 + healthcheck pool 2 + headroom).
  FOREACH r IN ARRAY ARRAY['tsb_scanner','tsb_analyzer','tsb_signal_engine','tsb_telegram','tsb_tracker']
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT', r);
    END IF;
    EXECUTE format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 20', r);
  END LOOP;
  -- Roles that exist but cannot log in until a separate owner decision: learner restart, A59 deployment, D6.
  FOREACH r IN ARRAY ARRAY['tsb_learner','tsb_dashboard_ro','tsb_research_ro']
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT', r);
    END IF;
    EXECUTE format('ALTER ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT %s',
                   r, CASE r WHEN 'tsb_learner' THEN 20 ELSE 5 END);
  END LOOP;
  -- Backup: LOGIN for the local socket only (pg_hba keeps it off the network). Two sessions are enough.
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tsb_backup') THEN
    CREATE ROLE tsb_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
  END IF;
  ALTER ROLE tsb_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 2;
  -- Login-scope group: no privileges, no login; members neither inherit it nor may SET ROLE to it (pg_hba scoping only).
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tsb_login_group') THEN
    CREATE ROLE tsb_login_group NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  FOREACH r IN ARRAY ARRAY['tsb_scanner','tsb_analyzer','tsb_signal_engine','tsb_telegram','tsb_tracker',
                           'tsb_learner','tsb_dashboard_ro','tsb_research_ro','tsb_backup']
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_auth_members m
                   WHERE m.roleid = 'tsb_login_group'::regrole AND m.member = r::regrole) THEN
      EXECUTE format('GRANT tsb_login_group TO %I WITH INHERIT FALSE, SET FALSE', r);
    END IF;
  END LOOP;
  -- Network-scope group: only roles that legitimately connect over the Docker network (pg_hba allows +tsb_net_group
  -- to trading_signals and rejects every other tsb_* role on the network; backup and migrator are local-socket only;
  -- research has no network login while D6 is unresolved).
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tsb_net_group') THEN
    CREATE ROLE tsb_net_group NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  FOREACH r IN ARRAY ARRAY['tsb_scanner','tsb_analyzer','tsb_signal_engine','tsb_telegram','tsb_tracker',
                           'tsb_learner','tsb_dashboard_ro']
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_auth_members m
                   WHERE m.roleid = 'tsb_net_group'::regrole AND m.member = r::regrole) THEN
      EXECUTE format('GRANT tsb_net_group TO %I WITH INHERIT FALSE, SET FALSE', r);
    END IF;
  END LOOP;
END $$;

-- Read-only roles cannot write even if a grant were wrong (privileges remain the real barrier; see the tests).
ALTER ROLE tsb_research_ro SET default_transaction_read_only = on;
ALTER ROLE tsb_dashboard_ro SET default_transaction_read_only = on;
ALTER ROLE tsb_backup SET default_transaction_read_only = on;

-- Database/schema access (PUBLIC has no CONNECT on this database; grant it explicitly).
GRANT CONNECT ON DATABASE trading_signals TO tsb_scanner, tsb_analyzer, tsb_signal_engine, tsb_telegram,
  tsb_tracker, tsb_learner, tsb_dashboard_ro, tsb_research_ro, tsb_backup;
GRANT USAGE ON SCHEMA public TO tsb_scanner, tsb_analyzer, tsb_signal_engine, tsb_telegram, tsb_tracker,
  tsb_learner, tsb_backup, tsb_research_ro;
-- tsb_dashboard_ro: NO usage on schema public (it reads only the dashboard schema; see dashboard_v1.sql).
REVOKE ALL ON SCHEMA public FROM tsb_dashboard_ro;

-- Common: schema-version check (read) + own heartbeat upsert (INSERT ... ON CONFLICT DO UPDATE).
GRANT SELECT ON schema_migrations TO tsb_scanner, tsb_analyzer, tsb_signal_engine, tsb_telegram, tsb_tracker, tsb_learner;
GRANT SELECT, INSERT, UPDATE ON service_heartbeats TO tsb_scanner, tsb_analyzer, tsb_signal_engine, tsb_telegram,
  tsb_tracker, tsb_learner;

-- scanner: B3 gate #1 reads risk_management; writes the scan queue; expires stale analysis rows.
GRANT SELECT ON risk_management, symbol_blacklist TO tsb_scanner;
GRANT SELECT, INSERT, DELETE ON scan_candidates TO tsb_scanner;
GRANT SELECT, UPDATE ON analysis_results TO tsb_scanner;

-- analyzer: consumes the scan queue, upserts analysis rows, reads legacy score weights.
GRANT SELECT, UPDATE ON scan_candidates TO tsb_analyzer;
GRANT SELECT, INSERT, UPDATE ON analysis_results TO tsb_analyzer;
GRANT SELECT ON indicator_weights TO tsb_analyzer;

-- signal_engine: selection, signal creation (setup_key, migration 011, is a column of signals), risk counters,
-- macro snapshot, outbox.
GRANT SELECT ON active_trades, learned_gates, optimizer_settings, trade_results, scan_candidates TO tsb_signal_engine;
GRANT SELECT, UPDATE ON analysis_results TO tsb_signal_engine;
GRANT SELECT, INSERT ON signals TO tsb_signal_engine;
GRANT SELECT, INSERT, UPDATE ON risk_management, macro_history, outbox_events TO tsb_signal_engine;

-- telegram: delivery (B3 gate #2), owner commands (/pause /resume /recover_risk), lists, reports.
GRANT SELECT ON active_trades, analysis_results, optimizer_settings, trade_results, trade_target_fills TO tsb_telegram;
GRANT SELECT, UPDATE ON signals TO tsb_telegram;
GRANT SELECT, INSERT, UPDATE ON approval_requests, outbox_events, risk_management TO tsb_telegram;
GRANT SELECT, INSERT ON risk_recovery_events TO tsb_telegram;
GRANT SELECT, INSERT, UPDATE, DELETE ON symbol_blacklist, symbol_whitelist TO tsb_telegram;

-- trade_tracker: admission (B3 gate #3 + advisory lock), entry orders (schema 11), positions, fills, results, outbox.
GRANT SELECT, INSERT, UPDATE ON active_trades, outbox_events, risk_management, paper_entry_orders TO tsb_tracker;
GRANT SELECT, INSERT ON trade_results, trade_target_fills TO tsb_tracker;
GRANT SELECT, UPDATE ON signals TO tsb_tracker;
GRANT SELECT ON approval_requests, risk_recovery_events, symbol_blacklist TO tsb_tracker;

-- continuous_learner (NOLOGIN until authorized): learning runs, gate history, learned gates, macro snapshot.
GRANT SELECT ON signals, trade_results TO tsb_learner;
GRANT SELECT, INSERT ON learned_gate_history TO tsb_learner;
GRANT SELECT, INSERT, UPDATE ON learning_runs, macro_history TO tsb_learner;
GRANT SELECT, INSERT, UPDATE, DELETE ON learned_gates TO tsb_learner;

-- backup: read every table and sequence of this database (pg_dump); never writes (no INSERT/UPDATE/DELETE/TRUNCATE).
GRANT SELECT ON ALL TABLES IN SCHEMA public TO tsb_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO tsb_backup;

-- research (D6 unresolved): DENY BY DEFAULT. Remove any table/sequence privilege a v2 test cluster may have granted.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM tsb_research_ro;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM tsb_research_ro;

-- Sequences (all are SERIAL): USAGE for exactly the tables each role inserts into.
DO $$
DECLARE g record; s text;
BEGIN
  FOR g IN SELECT * FROM (VALUES
      ('tsb_scanner','scan_candidates'), ('tsb_scanner','service_heartbeats'),
      ('tsb_analyzer','analysis_results'), ('tsb_analyzer','service_heartbeats'),
      ('tsb_signal_engine','signals'), ('tsb_signal_engine','risk_management'),
      ('tsb_signal_engine','macro_history'), ('tsb_signal_engine','outbox_events'),
      ('tsb_signal_engine','service_heartbeats'),
      ('tsb_telegram','approval_requests'), ('tsb_telegram','outbox_events'),
      ('tsb_telegram','risk_management'), ('tsb_telegram','risk_recovery_events'),
      ('tsb_telegram','symbol_blacklist'), ('tsb_telegram','symbol_whitelist'),
      ('tsb_telegram','service_heartbeats'),
      ('tsb_tracker','active_trades'), ('tsb_tracker','outbox_events'),
      ('tsb_tracker','risk_management'), ('tsb_tracker','trade_results'),
      ('tsb_tracker','trade_target_fills'), ('tsb_tracker','service_heartbeats'),
      ('tsb_learner','learned_gate_history'), ('tsb_learner','learning_runs'),
      ('tsb_learner','learned_gates'), ('tsb_learner','macro_history'), ('tsb_learner','service_heartbeats')
    ) AS t(role_name, table_name)
  LOOP
    FOR s IN SELECT format('%I.%I', n.nspname, c.relname)
             FROM pg_depend d JOIN pg_class c ON c.oid = d.objid AND c.relkind = 'S'
             JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE d.refobjid = format('public.%I', g.table_name)::regclass AND d.deptype IN ('a','i')
    LOOP
      EXECUTE format('GRANT USAGE ON SEQUENCE %s TO %I', s, g.role_name);
    END LOOP;
  END LOOP;
END $$;

-- Hardening (no effect on the admin role; no deployed service creates temporary tables).
REVOKE TEMP ON DATABASE trading_signals FROM PUBLIC;
-- Future tables are deny-by-default for every runtime, research and dashboard role: each new migration that adds a
-- table must add its GRANTs (and the test suite must pass) before deployment. The only default privilege is for the
-- backup role, so a new table can never silently fall out of the dump (objects created by the current owner).
ALTER DEFAULT PRIVILEGES FOR ROLE trading_signal_bot IN SCHEMA public GRANT SELECT ON TABLES TO tsb_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE trading_signal_bot IN SCHEMA public GRANT SELECT ON SEQUENCES TO tsb_backup;
