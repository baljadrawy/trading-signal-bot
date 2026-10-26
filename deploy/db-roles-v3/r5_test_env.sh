#!/usr/bin/env bash
# R-5 disposable test cluster for the v3 least-privilege roles. Never points at production.
#   ./r5_test_env.sh up      build the cluster (schema-only + synthetic data), run the migration tests, apply v3, issue test creds
#   ./r5_test_env.sh test    role suite, functional suites (release images), pg_hba suite, rollback cycle
#   ./r5_test_env.sh rollback-cycle   R-01..R-04: refusal while connected, full rollback, re-apply, re-test
#   ./r5_test_env.sh down    remove container, network and every test credential
# Inputs (read-only): P0_SCHEMA (production schema at version 9, 2026-09-27), PROD_SCHEMA (production schema-only
# dump at version 11, no data), DEPLOYED (the /app of each running container), the release images.
set -euo pipefail
O=$(cd "$(dirname "$0")" && pwd)
NET=tsb-r5-net PG=tsb-r5-pg RUN=${RUN:?set RUN to a private scratch directory}
P0_SCHEMA=${P0_SCHEMA:-/home/tradmin/backups/tsb-p0-security-20260927/schema_only.sql}
PROD_SCHEMA=${PROD_SCHEMA:?set PROD_SCHEMA to a schema-only dump of production (no data)}
DEPLOYED=${DEPLOYED:?set DEPLOYED to a directory holding /app of each container}
MIGRATIONS=${MIGRATIONS:-$O/../../database/migrations}
PG_IMAGE=${PG_IMAGE:-sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea}   # production postgres 16.15
PSQL=(docker exec -i "$PG" psql -X -q -v ON_ERROR_STOP=1 -U trading_signal_bot)
log() { echo "$(date -u +%FT%TZ) [r5] $*"; }

catalog() {   # normalized structure of one database (no owners, no ACLs) for comparison
  docker exec -i "$PG" psql -X -At -U trading_signal_bot -d "$1" <<'SQL'
SELECT 'col '||c.relname||'.'||a.attname||' '||format_type(a.atttypid,a.atttypmod)||CASE WHEN a.attnotnull THEN ' NOT NULL' ELSE '' END
       ||coalesce(' DEFAULT '||pg_get_expr(d.adbin,d.adrelid),'')
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
UNION ALL SELECT 'con '||conrelid::regclass||' '||conname||' '||pg_get_constraintdef(oid) FROM pg_constraint
  WHERE connamespace='public'::regnamespace
UNION ALL SELECT 'idx '||indexdef FROM pg_indexes WHERE schemaname='public'
UNION ALL SELECT 'seq '||sequencename||' '||data_type||' '||increment_by FROM pg_sequences WHERE schemaname='public'
UNION ALL SELECT 'rel '||relname||' '||relkind::text FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN ('r','v','m','S','f','p')
ORDER BY 1;
SQL
}

roundtrip_catalog() {   # <db> <out>: dump schema-only and reload into a scratch database, so that both sides of the
  # comparison went through the same pg_dump deparse/reparse as the production reference (equivalent CHECK lists are
  # otherwise printed differently); then print the normalized catalog.
  local db=$1 rt=rt_$1
  "${PSQL[@]}" -d postgres -c "DROP DATABASE IF EXISTS $rt" -c "CREATE DATABASE $rt" >/dev/null
  docker exec "$PG" pg_dump -U trading_signal_bot -d "$db" --schema-only --no-owner --no-privileges \
    | "${PSQL[@]}" -d "$rt" >/dev/null
  catalog "$rt" > "$2"
  "${PSQL[@]}" -d postgres -c "DROP DATABASE $rt" >/dev/null
}

apply_migrations() {   # <db> <psql user> <set-role or ''>: exactly database/migrate.py's logic, against the TEST container
  local db=$1 user=$2 role=$3 f v body sum applied
  applied=$(docker exec -i "$PG" psql -X -At -v ON_ERROR_STOP=1 -U "$user" -d "$db" \
    -c "${role:+SET ROLE $role;} SELECT version||chr(9)||checksum FROM schema_migrations ORDER BY version")
  for f in "$MIGRATIONS"/[0-9][0-9][0-9]_*.sql; do
    v=$((10#$(basename "$f" | cut -c1-3))); sum=$(sha256sum "$f" | cut -c1-64)
    if printf '%s\n' "$applied" | grep -q "^$v	"; then
      printf '%s\n' "$applied" | grep -q "^$v	$sum\$" || { echo "checksum mismatch for $f" >&2; return 1; }
      continue
    fi
    { echo 'BEGIN;'; [ -n "$role" ] && echo "SET LOCAL ROLE $role;"; cat "$f"; echo
      echo "INSERT INTO schema_migrations(version,name,checksum) VALUES($v,'$(basename "$f")','$sum');"; echo 'COMMIT;'; } \
      | docker exec -i "$PG" psql -X -q -v ON_ERROR_STOP=1 -U "$user" -d "$db" >/dev/null
    log "+ $(basename "$f") applied to $db as $user${role:+ (SET ROLE $role)}"
  done
}

seed_versions_1_to_9() {   # the real names and checksums of migrations 001-009 (as in production schema_migrations)
  local db=$1 f v
  for f in "$MIGRATIONS"/00[1-9]_*.sql; do
    v=$((10#$(basename "$f" | cut -c1-3)))
    echo "INSERT INTO schema_migrations(version,name,checksum) VALUES($v,'$(basename "$f")','$(sha256sum "$f" | cut -c1-64)');"
  done | "${PSQL[@]}" -d "$db"
}

issue_creds() {
  rm -rf "$RUN/creds"
  python3 "$O/tools/provision_db_credentials.py" --out-dir "$RUN/creds" \
    --roles scanner,analyzer,signal_engine,telegram,trade_tracker,learner,backup,migrator,dashboard,research 2>/dev/null \
    | "${PSQL[@]}" -d trading_signals
  local s pw; pw=$(sed -n 's/^POSTGRES_PASSWORD=//p' "$RUN/pg.env")
  printf 'TSB_PGHOST=%s\nTSB_PW_TRADING_SIGNAL_BOT=%s\n' "$PG" "$pw" > "$RUN/test.env"
  for s in scanner:TSB_SCANNER analyzer:TSB_ANALYZER signal_engine:TSB_SIGNAL_ENGINE telegram:TSB_TELEGRAM \
           trade_tracker:TSB_TRACKER learner:TSB_LEARNER backup:TSB_BACKUP migrator:TSB_MIGRATOR \
           dashboard:TSB_DASHBOARD_RO research:TSB_RESEARCH_RO; do
    sed -n "s/^POSTGRES_PASSWORD=/TSB_PW_${s##*:}=/p" "$RUN/creds/${s%%:*}.env" >> "$RUN/test.env"
  done
}

flow_base() {   # scenario database for the functional parity tests (clone of trading_signals, synthetic signals only)
  "${PSQL[@]}" -d postgres -c "DROP DATABASE IF EXISTS flow_base" -c "CREATE DATABASE flow_base TEMPLATE trading_signals" \
    -c "REVOKE CONNECT ON DATABASE flow_base FROM PUBLIC" >/dev/null
  "${PSQL[@]}" -d flow_base <<'SQL'
DELETE FROM trade_target_fills; DELETE FROM trade_results; DELETE FROM active_trades; DELETE FROM paper_entry_orders;
DELETE FROM outbox_events; DELETE FROM signals;
INSERT INTO risk_management (date, is_trading_paused, pause_reason) VALUES (CURRENT_DATE, false, 'manual_resume')
  ON CONFLICT (date) DO UPDATE SET is_trading_paused=false, pause_reason='manual_resume';
INSERT INTO signals (symbol, timeframe, market_condition, signal_time, entry_price, target_1, target_2, target_3, stop_loss,
                     score, telegram_sent, is_paper_trade, strategy_version, decision_source, trade_type, features_snapshot)
SELECT s, '15m', 'neutral', now()::timestamp - interval '1 minute', 1.0, 1.01, 1.02, 1.03, 0.99, 4, true, true,
       'r5-syn', 'policy_ready', 'reversion', '{"stop_policy": "reversion_structure", "trade_type": "reversion"}'::jsonb
FROM unnest(ARRAY['R5AUSDT','R5BUSDT','R5CUSDT']) s;
SQL
}

local_checks() {   # backup and migrator over the local socket (pg_hba keeps them off the network)
  local f=$RUN/out/backup_migrator_local.txt rc
  : > "$f"
  rc=0; docker exec "$PG" pg_dump -U tsb_backup -d trading_signals -Fc > "$RUN/b.dump" 2> "$RUN/b.err" || rc=$?
  echo "B-01 pg_dump as tsb_backup (local socket) rc=$rc bytes=$(stat -c %s "$RUN/b.dump") stderr_lines=$(wc -l < "$RUN/b.err")" | tee -a "$f"
  echo "B-02 TABLE DATA entries for public = $(docker exec -i "$PG" pg_restore --list < "$RUN/b.dump" | grep -c 'TABLE DATA public') (expect 26)" | tee -a "$f"
  rc=0; docker exec "$PG" pg_dump -U tsb_scanner -d trading_signals -Fc > /dev/null 2> "$RUN/s.err" || rc=$?
  echo "B-05 pg_dump as tsb_scanner (must fail) rc=$rc: $(head -1 "$RUN/s.err" | cut -c1-100)" | tee -a "$f"
  docker exec -i "$PG" psql -X -At -U tsb_migrator -d owner_stage -c "SET ROLE tsb_owner" \
    -c "SELECT 'M-05 migrator (local socket, SET ROLE tsb_owner): schema_migrations rows='||count(*)||' max='||max(version) FROM schema_migrations" | tee -a "$f"
  rm -f "$RUN/b.dump" "$RUN/b.err" "$RUN/s.err"
}

up() {
  umask 077; mkdir -p "$RUN"
  local pw; pw=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  printf 'POSTGRES_USER=trading_signal_bot\nPOSTGRES_DB=trading_signals\nPOSTGRES_PASSWORD=%s\n' "$pw" > "$RUN/pg.env"
  printf 'TSB_PGHOST=%s\nTSB_PW_TRADING_SIGNAL_BOT=%s\n' "$PG" "$pw" > "$RUN/test.env"
  docker network create --internal --label purpose=r5-disposable-test "$NET" >/dev/null
  docker run -d --name "$PG" --network "$NET" --label purpose=r5-disposable-test --env-file "$RUN/pg.env" \
    --memory 1g --cpus 1 --tmpfs /var/lib/postgresql/data:rw,size=1g "$PG_IMAGE" >/dev/null
  for _ in $(seq 90); do [ "$(docker logs "$PG" 2>&1 | grep -c 'ready to accept connections')" -ge 2 ] && break; timeout 1 tail -f /dev/null || true; done
  # Mirror production's cluster layout: other projects' roles and databases, and their database ACLs.
  "${PSQL[@]}" -d postgres <<'SQL'
CREATE ROLE xsch_user LOGIN; CREATE ROLE wishlist_user LOGIN; CREATE ROLE wishlist_test_role LOGIN; CREATE ROLE shared_pg_backup LOGIN;
CREATE DATABASE xsch OWNER xsch_user; REVOKE CONNECT ON DATABASE xsch FROM PUBLIC; GRANT CONNECT ON DATABASE xsch TO shared_pg_backup;
CREATE DATABASE wishlist OWNER wishlist_user; REVOKE CONNECT ON DATABASE wishlist FROM PUBLIC; GRANT CONNECT ON DATABASE wishlist TO shared_pg_backup;
CREATE DATABASE wishlist_test OWNER wishlist_test_role;
REVOKE CONNECT ON DATABASE trading_signals FROM PUBLIC; GRANT CONNECT ON DATABASE trading_signals TO shared_pg_backup;
CREATE DATABASE prod_ref; CREATE DATABASE owner_stage; CREATE DATABASE b3_owner;
REVOKE CONNECT ON DATABASE prod_ref, owner_stage, b3_owner FROM PUBLIC;
SQL
  # Reference: production's current structure (schema-only dump, version 11).
  "${PSQL[@]}" -d prod_ref < "$PROD_SCHEMA" >/dev/null
  # M-01: production v9 schema + the real 010/011 files, applied exactly like migrate.py (admin, one transaction each).
  "${PSQL[@]}" -d trading_signals < "$P0_SCHEMA" >/dev/null
  seed_versions_1_to_9 trading_signals
  apply_migrations trading_signals trading_signal_bot ''
  catalog prod_ref > "$RUN/catalog_prod_ref.txt"; roundtrip_catalog trading_signals "$RUN/catalog_trading_signals.txt"
  [ "$(wc -l < "$RUN/catalog_prod_ref.txt")" -gt 100 ] || { log "M-01 FAIL: reference catalog is empty or too small"; return 1; }
  if diff "$RUN/catalog_prod_ref.txt" "$RUN/catalog_trading_signals.txt" > "$RUN/M01.diff"; then
    log "M-01 PASS: v9 + 010 + 011 == production v11 structure ($(wc -l < "$RUN/catalog_prod_ref.txt") catalog lines)"
  else log "M-01 FAIL: structure differs (see $RUN/M01.diff)"; fi
  # v3 roles + dashboard allowlist (production Stage 1 order), then the idempotency re-run.
  "${PSQL[@]}" -d trading_signals < "$O/roles_v3.sql" >/dev/null
  "${PSQL[@]}" -d trading_signals < "$O/dashboard_v1.sql" >/dev/null
  "${PSQL[@]}" -d trading_signals < "$O/roles_v3.sql" >/dev/null && log "M-03 roles_v3.sql applied twice (idempotent)"
  # M-02: ownership stage + migrations WITHOUT superuser (tsb_migrator, SET ROLE tsb_owner) in a separate database.
  "${PSQL[@]}" -d owner_stage < "$P0_SCHEMA" >/dev/null
  seed_versions_1_to_9 owner_stage
  sed 's/DATABASE trading_signals/DATABASE owner_stage/' "$O/ownership_v3.sql" | "${PSQL[@]}" -d owner_stage >/dev/null
  apply_migrations owner_stage tsb_migrator tsb_owner
  roundtrip_catalog owner_stage "$RUN/catalog_owner_stage.txt"
  # M-04: the v3 grants also apply on objects owned by tsb_owner (production end state: roles + ownership stage).
  sed 's/DATABASE trading_signals/DATABASE owner_stage/' "$O/roles_v3.sql" \
    | sed 's/FOR ROLE trading_signal_bot/FOR ROLE tsb_owner/' | "${PSQL[@]}" -d owner_stage >/dev/null && log "M-04 roles_v3.sql applied on tsb_owner-owned objects"
  if diff "$RUN/catalog_prod_ref.txt" "$RUN/catalog_owner_stage.txt" > "$RUN/M02.diff"; then
    log "M-02 PASS: migrations 010/011 applied by non-superuser tsb_migrator; structure == production v11"
  else log "M-02 FAIL: structure differs (see $RUN/M02.diff)"; fi
  docker exec -i "$PG" psql -X -At -U trading_signal_bot -d owner_stage -c \
    "SELECT 'owners in owner_stage: '||string_agg(DISTINCT pg_get_userbyid(relowner), ',') FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN ('r','S','i')"
  # Synthetic data only (no production rows).
  "${PSQL[@]}" -d trading_signals < "$O/tests/synthetic_seed_v3.sql" >/dev/null
  # Test credentials (SCRAM verifiers piped to psql; plaintext stays in $RUN, mode 600).
  issue_creds
  flow_base
  log "up: $PG on $NET (internal), roles v3 applied, test credentials in $RUN (600)"
}

pytest_in() {   # pytest_in <extra docker args...> -- <pytest args...>
  local args=(); while [ "$1" != -- ]; do args+=("$1"); shift; done; shift
  docker run --rm --user "$(id -u):$(id -g)" --network "$NET" --env-file "$RUN/test.env" --label purpose=r5-disposable-test \
    -e PYTHONDONTWRITEBYTECODE=1 -e R5_OUT=/out -v "$RUN/out:/out" -v "$O:/r5:ro" --tmpfs /tmp "${args[@]}" --entrypoint python \
    tsb-sync-test:pytest -m pytest -q -p no:cacheprovider -o asyncio_mode=auto -W ignore::pytest.PytestUnknownMarkWarning \
    --tb=short -rA "$@"
}

hba_on() {
  local h; h=$(docker exec "$PG" psql -U trading_signal_bot -d postgres -XAt -c 'SHOW hba_file')
  docker cp "$O/hba/pg_hba.tsb.v3.snippet" "$PG:/tmp/snip" >/dev/null
  docker exec "$PG" sh -c "cp -p $h $h.pre-r5 && awk -v snip=/tmp/snip 'BEGIN{while((getline l < snip)>0) s=s l \"\n\"} /^host[[:space:]]+all[[:space:]]+all[[:space:]]+all[[:space:]]+scram-sha-256/ && !d {printf \"%s\", s; d=1} {print}' $h.pre-r5 > $h"
  docker exec "$PG" psql -U trading_signal_bot -d postgres -XAtq -c 'SELECT pg_reload_conf()' >/dev/null
  docker exec "$PG" psql -U trading_signal_bot -d postgres -XAt -c "SELECT 'hba errors: '||count(*) FILTER (WHERE error IS NOT NULL)||', rules: '||count(*) FROM pg_hba_file_rules"
}

test_all() {
  mkdir -p "$RUN/out"
  pytest_in -v "$O/tests:/t:ro" -v "$DEPLOYED:/deployed:ro" -- /t/test_roles_v3.py > "$RUN/out/roles_suite.txt" 2>&1 || true
  log "role suite: $(tail -1 "$RUN/out/roles_suite.txt")"
  hba_on
  pytest_in -v "$O/tests:/t:ro" -v "$DEPLOYED:/deployed:ro" -- /t/test_hba_v3.py > "$RUN/out/hba_suite.txt" 2>&1 || true
  log "hba suite: $(tail -1 "$RUN/out/hba_suite.txt")"
  pytest_in -v "$O/tests:/t:ro" -v "$DEPLOYED:/deployed:ro" -e R5_HBA_ACTIVE=1 -- /t/test_roles_v3.py > "$RUN/out/roles_suite_with_hba.txt" 2>&1 || true
  log "role suite with pg_hba scoping: $(tail -1 "$RUN/out/roles_suite_with_hba.txt")"
  RUN=$RUN "$O/tests/run_tracker_parity.sh" > "$RUN/out/tracker_parity.txt" 2>&1 && log "tracker parity: PASS" || log "tracker parity: FAIL"
  RUN=$RUN "$O/tests/run_telegram_parity.sh" > "$RUN/out/telegram_parity.txt" 2>&1 && log "telegram parity: PASS" || log "telegram parity: FAIL"
  local_checks
}

smoke() {   # each deployed image starts its real main.py under its own role on the internal network (no internet)
  local s img f=$RUN/out/startup_smoke.txt; : > "$f"
  "${PSQL[@]}" -d trading_signals -c 'DELETE FROM service_heartbeats' >/dev/null
  for s in scanner analyzer signal_engine telegram tracker; do
    case $s in scanner) img=$(docker inspect --format '{{.Image}}' trading_scanner) ;; tracker) img=tsb-a561-trade_tracker:rel-ea8ae4f-r2 ;;
                *) img=tsb-a561-$s:rel-ea8ae4f-r2 ;; esac
    { printf 'POSTGRES_HOST=%s\nPOSTGRES_PORT=5432\nPOSTGRES_DB=trading_signals\nPOSTGRES_USER=tsb_%s\n' "$PG" $s
      sed -n "s/^TSB_PW_TSB_${s^^}=/POSTGRES_PASSWORD=/p" "$RUN/test.env"
      printf 'PAPER_TRADING=true\nTELEGRAM_CHAT_ID=424242\nTELEGRAM_BOT_TOKEN=000000:r5-fake-token-not-valid\nEVIDENCE_V2_ENABLED=false\nENABLE_EVIDENCE_RECORDER=false\n'; } > "$RUN/smoke.env"
    docker run -d --name "r5-smoke-$s" --network "$NET" --label purpose=r5-disposable-test --env-file "$RUN/smoke.env" --memory 512m "$img" >/dev/null
    rm -f "$RUN/smoke.env"
  done
  timeout 75 tail -f /dev/null || true
  for s in scanner analyzer signal_engine telegram tracker; do
    docker logs "r5-smoke-$s" > "$RUN/out/smoke_$s.log" 2>&1
    sed -i -E 's/(bot)[0-9]+:[A-Za-z0-9_-]+/\1<redacted>/g' "$RUN/out/smoke_$s.log"
    echo "$s: $(docker inspect --format '{{.State.Status}} exit={{.State.ExitCode}}' "r5-smoke-$s") privilege_errors=$(grep -c -i -E 'permission denied|InsufficientPrivilege|42501|must be owner' "$RUN/out/smoke_$s.log") last_error=$(grep -E '^[A-Za-z_.]+(Error|Exception)' "$RUN/out/smoke_$s.log" | tail -1 | cut -c1-110)" | tee -a "$f"
    docker rm -f "r5-smoke-$s" >/dev/null
  done
  docker exec -i "$PG" psql -X -At -F ' | ' -U trading_signal_bot -d trading_signals -c \
    "SELECT 'heartbeat '||service_name, (last_started_at IS NOT NULL)::text, (last_success_at IS NOT NULL)::text, consecutive_errors::text FROM service_heartbeats ORDER BY 1" | tee -a "$f"
}

rollback_cycle() {   # R-01 refusal while connected, R-02/R-03 full rollback restores the original ACL state, R-04 re-apply + re-test
  local f=$RUN/out/rollback_cycle.txt rc q
  q() { docker exec -i "$PG" psql -X -At -U trading_signal_bot -d "$1" -c "$2"; }
  : > "$f"
  docker exec "$PG" psql -X -q -U tsb_tracker -d trading_signals -c 'SELECT pg_sleep(15)' >/dev/null 2>&1 &
  timeout 3 tail -f /dev/null || true
  rc=0; "${PSQL[@]}" -d trading_signals < "$O/roles_v3_rollback.sql" > "$RUN/rb.txt" 2>&1 || rc=$?
  echo "R-01 rollback while a tsb_tracker session is connected: rc=$rc ($(grep -o 'tsb_\* sessions are still connected' "$RUN/rb.txt" | head -1)); tsb roles=$(q postgres "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'tsb\_%'")" | tee -a "$f"
  wait
  for d in flow_base par_admin par_role tg_admin tg_role; do q postgres "DROP DATABASE IF EXISTS $d" >/dev/null 2>&1; done
  "${PSQL[@]}" -d owner_stage < "$O/ownership_v3_rollback.sql" >/dev/null 2>&1
  sed 's/DATABASE trading_signals/DATABASE owner_stage/' "$O/roles_v3_rollback.sql" | "${PSQL[@]}" -d owner_stage >/dev/null 2>&1
  "${PSQL[@]}" -d trading_signals < "$O/roles_v3_rollback.sql" >/dev/null 2>&1
  echo "R-02 tsb roles=$(q postgres "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'tsb\_%'") (expect 0); owner_stage owners=$(q owner_stage "SELECT string_agg(DISTINCT pg_get_userbyid(relowner), ',') FROM pg_class WHERE relnamespace='public'::regnamespace")" | tee -a "$f"
  echo "R-03 non-owner ACL entries=$(q trading_signals "SELECT count(*) FROM pg_class c, aclexplode(c.relacl) a WHERE c.relnamespace='public'::regnamespace AND a.grantee <> c.relowner") (expect 0); default ACLs=$(q trading_signals "SELECT count(*) FROM pg_default_acl"); dashboard schemas=$(q trading_signals "SELECT count(*) FROM pg_namespace WHERE nspname='dashboard'"); PUBLIC TEMP=$(q trading_signals "SELECT has_database_privilege('public','trading_signals','TEMP')")" | tee -a "$f"
  "${PSQL[@]}" -d trading_signals < "$O/roles_v3.sql" >/dev/null && "${PSQL[@]}" -d trading_signals < "$O/dashboard_v1.sql" >/dev/null
  sed 's/DATABASE trading_signals/DATABASE owner_stage/' "$O/ownership_v3.sql" | "${PSQL[@]}" -d owner_stage >/dev/null
  sed 's/DATABASE trading_signals/DATABASE owner_stage/' "$O/roles_v3.sql" | sed 's/FOR ROLE trading_signal_bot/FOR ROLE tsb_owner/' | "${PSQL[@]}" -d owner_stage >/dev/null
  issue_creds; flow_base
  echo "R-04 re-applied: tsb roles=$(q postgres "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'tsb\_%'")" | tee -a "$f"
  pytest_in -v "$O/tests:/t:ro" -v "$DEPLOYED:/deployed:ro" -e R5_HBA_ACTIVE=1 -- /t/test_roles_v3.py > "$RUN/out/roles_suite_after_reapply.txt" 2>&1 || true
  echo "R-04 role suite after re-apply (pg_hba active): $(tail -1 "$RUN/out/roles_suite_after_reapply.txt")" | tee -a "$f"
  RUN=$RUN "$O/tests/run_tracker_parity.sh" > "$RUN/out/tracker_parity_after_reapply.txt" 2>&1 && echo "R-04 tracker parity after re-apply: PASS" | tee -a "$f" || echo "R-04 tracker parity after re-apply: FAIL" | tee -a "$f"
}

down() {
  docker rm -f "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$RUN/creds" "$RUN/test.env" "$RUN/pg.env"
  log "down: container, network and test credentials removed"
}

case "${1:-}" in up) up ;; test) test_all ;; rollback-cycle) rollback_cycle ;; smoke) smoke ;; down) down ;; *) echo "usage: $0 up|test|rollback-cycle|down" >&2; exit 2 ;; esac
