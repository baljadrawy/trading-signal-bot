-- Rollback of ownership_v3.sql. Run as the cluster admin in each database where tsb_owner owns objects
-- (production: trading_signals only). Ownership returns to the bootstrap admin; existing grants are kept.
REASSIGN OWNED BY tsb_owner TO trading_signal_bot;
ALTER DEFAULT PRIVILEGES FOR ROLE tsb_owner IN SCHEMA public REVOKE SELECT ON TABLES FROM tsb_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE tsb_owner IN SCHEMA public REVOKE SELECT ON SEQUENCES FROM tsb_backup;
DROP OWNED BY tsb_owner, tsb_migrator;            -- revokes their privileges in this database (owns nothing now)
DO $$
BEGIN
  DROP ROLE IF EXISTS tsb_migrator;
  DROP ROLE IF EXISTS tsb_owner;
EXCEPTION WHEN dependent_objects_still_exist THEN
  RAISE NOTICE 'tsb_owner/tsb_migrator still hold privileges in another database: run this file there too';
END $$;
