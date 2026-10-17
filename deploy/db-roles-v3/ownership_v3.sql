-- OPTIONAL later stage (separate approval): move object ownership off the superuser and run migrations without it.
-- Run as the cluster admin in trading_signals AFTER roles_v3.sql. Idempotent.
-- tsb_owner (NOLOGIN) owns every table, sequence, view and the app schemas; tsb_migrator logs in (local socket only,
-- via pg_hba) and must `SET ROLE tsb_owner` for DDL. Neither is a superuser. Existing grants survive ALTER ... OWNER.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tsb_owner') THEN
    CREATE ROLE tsb_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tsb_migrator') THEN
    CREATE ROLE tsb_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
  END IF;
  ALTER ROLE tsb_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 2;
  IF NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE roleid = 'tsb_owner'::regrole AND member = 'tsb_migrator'::regrole) THEN
    GRANT tsb_owner TO tsb_migrator WITH INHERIT FALSE, SET TRUE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE roleid = 'tsb_login_group'::regrole AND member = 'tsb_migrator'::regrole) THEN
    GRANT tsb_login_group TO tsb_migrator WITH INHERIT FALSE, SET FALSE;
  END IF;
END $$;
GRANT CONNECT ON DATABASE trading_signals TO tsb_migrator;
GRANT USAGE, CREATE ON SCHEMA public TO tsb_owner;

DO $$
DECLARE o record;
BEGIN
  FOR o IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
             AND pg_get_userbyid(c.relowner) <> 'tsb_owner'
             AND NOT (c.relkind = 'S' AND EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = c.oid AND d.deptype IN ('a','i')))
  LOOP
    EXECUTE format('ALTER %s public.%I OWNER TO tsb_owner',
                   CASE o.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END,
                   o.relname);                     -- owned (serial) sequences follow their table
  END LOOP;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'dashboard') THEN
    EXECUTE 'ALTER SCHEMA dashboard OWNER TO tsb_owner';
    FOR o IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'dashboard' AND c.relkind = 'v'
    LOOP
      EXECUTE format('ALTER VIEW dashboard.%I OWNER TO tsb_owner', o.relname);
    END LOOP;
  END IF;
END $$;

-- The backup role keeps reading every future table created by the new owner.
ALTER DEFAULT PRIVILEGES FOR ROLE tsb_owner IN SCHEMA public GRANT SELECT ON TABLES TO tsb_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE tsb_owner IN SCHEMA public GRANT SELECT ON SEQUENCES TO tsb_backup;
