-- D6 option (c) PROTOTYPE: a filtered research layer that enforces the holdout boundary in the database.
-- TEST CLUSTER ONLY. D6 is unresolved: this file is NOT part of roles_v3.sql and must not be applied to production
-- without an explicit owner decision. With roles_v3.sql alone, tsb_research_ro can read nothing.
-- Boundary: FORWARD_HOLDOUT = everything after 2026-08-19 09:33:46 UTC (freeze 63da7d3). signal_time is UTC
-- (timestamp without time zone). Rows are kept only when their signal is strictly before the freeze.
CREATE SCHEMA IF NOT EXISTS research_pre_freeze;
REVOKE ALL ON SCHEMA research_pre_freeze FROM PUBLIC;
GRANT USAGE ON SCHEMA research_pre_freeze TO tsb_research_ro;

CREATE OR REPLACE VIEW research_pre_freeze.signals WITH (security_barrier) AS
  SELECT * FROM public.signals WHERE signal_time < TIMESTAMP '2026-08-19 09:33:46';
CREATE OR REPLACE VIEW research_pre_freeze.trade_results WITH (security_barrier) AS
  SELECT r.* FROM public.trade_results r JOIN public.signals s ON s.id = r.signal_id
  WHERE s.signal_time < TIMESTAMP '2026-08-19 09:33:46';
CREATE OR REPLACE VIEW research_pre_freeze.active_trades WITH (security_barrier) AS
  SELECT a.* FROM public.active_trades a JOIN public.signals s ON s.id = a.signal_id
  WHERE s.signal_time < TIMESTAMP '2026-08-19 09:33:46';
CREATE OR REPLACE VIEW research_pre_freeze.trade_target_fills WITH (security_barrier) AS
  SELECT f.* FROM public.trade_target_fills f JOIN public.signals s ON s.id = f.signal_id
  WHERE s.signal_time < TIMESTAMP '2026-08-19 09:33:46';

REVOKE ALL ON ALL TABLES IN SCHEMA research_pre_freeze FROM PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA research_pre_freeze TO tsb_research_ro;
