#!/bin/bash
# tsb-p1bg-backup.sh — P1-BG minimum local backup: complete trading_signals DB (pg_dump custom) +
# production data/evidence_v2. Set model: .incomplete-<ts> -> verify -> manifest + SHA256SUMS -> atomic rename
# into sets/<ts>. Retention (newest KEEP verified sets) runs only after a successful promotion and touches only
# sets/ entries carrying this implementation's manifest. flock prevents overlap. No secrets are read or written.
# Usage: tsb-p1bg-backup.sh [run] | verify <set-dir>      Version: 1
set -Eeuo pipefail
umask 077
IMPL="tsb-p1bg-backup"; VERSION=1
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
DEST=${P1BG_DEST:-/home/tradmin/backups/tsb-p1bg}
EVSRC=${P1BG_EVIDENCE_SRC:-/home/tradmin/trading-signal-bot/data/evidence_v2}
DB=${P1BG_DB:-trading_signals}; PGC=${P1BG_PG_CONTAINER:-postgres}; PGU=${P1BG_PG_USER:-trading_signal_bot}
KEEP=${P1BG_KEEP:-7}
log(){ echo "$(date -u +%FT%TZ) [p1bg] $*"; }

verify_set(){   # <dir>: checksums + dump TOC readable + evidence archive readable
  local d=$1
  ( cd "$d" && sha256sum -c --quiet SHA256SUMS ) || { log "verify: checksum mismatch in $d"; return 1; }
  docker exec -i "$PGC" pg_restore --list < "$d/$DB.dump" > /dev/null || { log "verify: dump unreadable in $d"; return 1; }
  tar -tzf "$d/evidence_v2.tar.gz" > /dev/null || { log "verify: evidence archive unreadable in $d"; return 1; }
}

if [ "${1:-run}" = verify ]; then verify_set "$2" && log "verify OK $2"; exit $?; fi

mkdir -p "$DEST/sets"; chmod 700 "$DEST" "$DEST/sets"
exec 9>"$DEST/.lock"
flock -n 9 || { log "another backup holds $DEST/.lock; exiting without work"; exit 75; }
TS=$(date -u +%Y%m%dT%H%M%SZ); WORK="$DEST/.incomplete-$TS"; mkdir -m 700 "$WORK"
fail(){ log "FAIL set=$TS: $1"; echo "$(date -u +%FT%TZ) $1" > "$WORK/FAILED" 2>/dev/null || true; exit 1; }
trap 'fail "unexpected error at line $LINENO"' ERR
START=$(date -u +%FT%TZ); log "start set=$TS db=$DB evidence=$EVSRC"

# 1. complete logical dump (single consistent snapshot; PostgreSQL stays online)
if [ -n "${P1BG_DUMP_CMD:-}" ]; then bash -c "$P1BG_DUMP_CMD" > "$WORK/$DB.dump" || fail "dump command failed"
else docker exec "$PGC" pg_dump -U "$PGU" -d "$DB" --format=custom --no-password > "$WORK/$DB.dump" || fail "pg_dump failed"; fi
[ -s "$WORK/$DB.dump" ] || fail "empty dump"
docker exec -i "$PGC" pg_restore --list < "$WORK/$DB.dump" > "$WORK/$DB.toc" || fail "dump TOC unreadable"
grep -q "TABLE DATA public signals " "$WORK/$DB.toc" || fail "dump TOC lacks signals data"
# 2. evidence directory (structure, contents, numeric owners/modes; empty dir still archived)
[ -d "$EVSRC" ] || fail "evidence source missing"
tar --numeric-owner -C "$(dirname "$EVSRC")" -czf "$WORK/evidence_v2.tar.gz" "$(basename "$EVSRC")" || fail "evidence archive failed"
tar -tzvf "$WORK/evidence_v2.tar.gz" --numeric-owner > "$WORK/evidence_v2.list" || fail "evidence archive unreadable"
# 3. manifest (no secrets) + checksums
PGVER=$(docker exec "$PGC" psql -X -At -U "$PGU" -d "$DB" -c 'show server_version' 2>/dev/null || echo unknown)
python3 - "$WORK" "$TS" "$START" "$DB" "$PGVER" "$EVSRC" "$IMPL" "$VERSION" "$(sha256sum "$0" | cut -c1-64)" <<'PY' || fail "manifest failed"
import json, os, sys, hashlib
w, ts, start, db, pgver, ev, impl, ver, script_sha = sys.argv[1:]
h = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()
m = {'implementation': impl, 'implementation_version': int(ver), 'script_sha256': script_sha, 'set': ts,
     'started_utc': start, 'database': db, 'postgres_server_version': pgver,
     'db_method': 'pg_dump --format=custom (complete database, single snapshot)',
     'db_artifact': f'{db}.dump', 'db_bytes': os.path.getsize(f'{w}/{db}.dump'), 'db_sha256': h(f'{w}/{db}.dump'),
     'evidence_source': ev, 'evidence_artifact': 'evidence_v2.tar.gz',
     'evidence_bytes': os.path.getsize(f'{w}/evidence_v2.tar.gz'), 'evidence_sha256': h(f'{w}/evidence_v2.tar.gz'),
     'evidence_entries': sum(1 for _ in open(f'{w}/evidence_v2.list'))}
json.dump(m, open(f'{w}/MANIFEST.json', 'w'), indent=1)
PY
( cd "$WORK" && sha256sum "$DB.dump" "$DB.toc" evidence_v2.tar.gz evidence_v2.list MANIFEST.json > SHA256SUMS ) || fail "checksums failed"
verify_set "$WORK" || fail "verification failed"
# 4. atomic promotion (same filesystem rename)
chmod -R go-rwx "$WORK"; mv -T "$WORK" "$DEST/sets/$TS" || fail "promotion failed"
trap - ERR
log "OK set=$TS db_bytes=$(stat -c %s "$DEST/sets/$TS/$DB.dump") evidence_bytes=$(stat -c %s "$DEST/sets/$TS/evidence_v2.tar.gz") duration_s=$(( $(date +%s) - $(date -d "$START" +%s) ))"
# 5. retention: only verified sets of this implementation, newest KEEP kept, new set always kept
mapfile -t OWN < <(cd "$DEST/sets" && for d in [0-9]*T[0-9]*Z; do [[ "$d" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] && [ -f "$d/MANIFEST.json" ] && grep -q "\"implementation\": \"$IMPL\"" "$d/MANIFEST.json" && echo "$d"; done | sort)
if [ "${#OWN[@]}" -gt "$KEEP" ]; then
  for d in "${OWN[@]:0:$(( ${#OWN[@]} - KEEP ))}"; do [ "$d" != "$TS" ] && rm -rf -- "$DEST/sets/$d" && log "retention removed set=$d"; done
fi
log "retention: ${#OWN[@]} own sets, keep=$KEEP"
