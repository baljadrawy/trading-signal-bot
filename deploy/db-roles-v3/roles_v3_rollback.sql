-- Rollback of roles_v3.sql (and of dashboard_v1.sql if it was applied). Run as the cluster admin in trading_signals.
-- Refuses while any tsb_* session is connected (switch services back to the admin role first).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_stat_activity WHERE usename LIKE 'tsb\_%') THEN
    RAISE EXCEPTION 'tsb_* sessions are still connected; switch services back first';
  END IF;
END $$;
ALTER DEFAULT PRIVILEGES FOR ROLE trading_signal_bot IN SCHEMA public REVOKE SELECT ON TABLES FROM tsb_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE trading_signal_bot IN SCHEMA public REVOKE SELECT ON SEQUENCES FROM tsb_backup;
DROP SCHEMA IF EXISTS dashboard CASCADE;
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['tsb_scanner','tsb_analyzer','tsb_signal_engine','tsb_telegram','tsb_tracker',
                           'tsb_learner','tsb_dashboard_ro','tsb_research_ro','tsb_backup','tsb_claude_review']
  LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('DROP OWNED BY %I', r);        -- revokes every privilege of r in this database
      BEGIN
        EXECUTE format('DROP ROLE %I', r);
      EXCEPTION WHEN dependent_objects_still_exist THEN
        RAISE NOTICE '% still holds privileges in another database: run this file there too', r;
      END;
    END IF;
  END LOOP;
  FOREACH r IN ARRAY ARRAY['tsb_net_group', 'tsb_login_group'] LOOP
    BEGIN
      EXECUTE format('DROP ROLE IF EXISTS %I', r);
    EXCEPTION WHEN dependent_objects_still_exist THEN
      RAISE NOTICE '% still has members or privileges elsewhere', r;
    END;
  END LOOP;
END $$;
GRANT TEMP ON DATABASE trading_signals TO PUBLIC;    -- restores the PostgreSQL default removed by roles_v3.sql
