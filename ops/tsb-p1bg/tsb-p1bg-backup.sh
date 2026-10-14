#!/bin/bash
# tsb-p1bg-backup.sh — P1-BG minimum local backup: complete trading_signals DB (pg_dump custom) +
# production data/evidence_v2. Set model: .incomplete-<ts> -> verify -> manifest + SHA256SUMS -> atomic rename
# into sets/<ts>. Retention (newest KEEP verified sets) runs only after a successful promotion and touches only
# sets/ entries carrying this implementation's manifest. flock prevents overlap. No secrets are read or written.
# Usage: tsb-p1bg-backup.sh [run] | verify <set-dir>      Version: 2
# v2 (A41): the live evidence tree is NEVER archived directly (v1 failed nightly from 2026-10-10: tar exit 1
# "file changed as we read it"). p1bg_evidence_snapshot.py copies an append-prefix point-in-time snapshot into
# staging inside the set, the immutable staging copy is archived, and the archive is verified file by file
# against evidence_v2.manifest.json before promotion. A mutation that is not append-only fails the set closed.
set -Eeuo pipefail
umask 077
IMPL="tsb-p1bg-backup"; VERSION=2
HELPER=${P1BG_HELPER:-$(dirname "$(readlink -f "$0")")/p1bg_evidence_snapshot.py}
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
  if [ -f "$d/evidence_v2.manifest.json" ]; then        # v2 sets: every file against the snapshot manifest
    python3 "$HELPER" verify "$d/evidence_v2.tar.gz" "$d/evidence_v2.manifest.json" > /dev/null \
      || { log "verify: evidence archive does not match its manifest in $d"; return 1; }
  elif grep -q '"implementation_version": 2' "$d/MANIFEST.json" 2>/dev/null; then
    log "verify: v2 set without evidence manifest in $d"; return 1
  fi
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
[ -f "$HELPER" ] || fail "snapshot helper missing: $HELPER"
python3 "$HELPER" snapshot "$EVSRC" "$WORK/stage/evidence_v2" "$WORK/evidence_v2.manifest.json" > /dev/null \
  || fail "evidence snapshot failed (see stderr)"
tar --numeric-owner -C "$WORK/stage" -czf "$WORK/evidence_v2.tar.gz" evidence_v2 || fail "evidence archive failed"
python3 "$HELPER" verify "$WORK/evidence_v2.tar.gz" "$WORK/evidence_v2.manifest.json" > /dev/null \
  || fail "evidence archive does not match snapshot manifest"
rm -rf -- "$WORK/stage" || fail "staging cleanup failed"
tar -tzvf "$WORK/evidence_v2.tar.gz" --numeric-owner > "$WORK/evidence_v2.list" || fail "evidence archive unreadable"
# 3. manifest (no secrets) + checksums
PGVER=$(docker exec "$PGC" psql -X -At -U "$PGU" -d "$DB" -c 'show server_version' 2>/dev/null || echo unknown)
python3 - "$WORK" "$TS" "$START" "$DB" "$PGVER" "$EVSRC" "$IMPL" "$VERSION" "$(sha256sum "$0" | cut -c1-64)" "$(sha256sum "$HELPER" | cut -c1-64)" <<'PY' || fail "manifest failed"
import json, os, sys, hashlib
w, ts, start, db, pgver, ev, impl, ver, script_sha, helper_sha = sys.argv[1:]
em = json.load(open(f'{w}/evidence_v2.manifest.json'))
h = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()
m = {'implementation': impl, 'implementation_version': int(ver), 'script_sha256': script_sha, 'set': ts,
     'started_utc': start, 'database': db, 'postgres_server_version': pgver,
     'db_method': 'pg_dump --format=custom (complete database, single snapshot)',
     'db_artifact': f'{db}.dump', 'db_bytes': os.path.getsize(f'{w}/{db}.dump'), 'db_sha256': h(f'{w}/{db}.dump'),
     'evidence_source': ev, 'evidence_artifact': 'evidence_v2.tar.gz',
     'evidence_bytes': os.path.getsize(f'{w}/evidence_v2.tar.gz'), 'evidence_sha256': h(f'{w}/evidence_v2.tar.gz'),
     'evidence_entries': sum(1 for _ in open(f'{w}/evidence_v2.list')),
     'evidence_method': 'append-prefix point-in-time snapshot (p1bg_evidence_snapshot v2), then archive',
     'evidence_snapshot_utc': em['snapshot_utc'], 'evidence_files': em['totals']['files'],
     'evidence_tail_excluded_bytes': em['totals']['tail_excluded_bytes'],
     'evidence_manifest_sha256': h(f'{w}/evidence_v2.manifest.json'), 'helper_sha256': helper_sha,
     'consistency_note': 'DB dump and evidence snapshot are separate points in time (DB first); evidence may '
                         'reference rows created after the dump'}
json.dump(m, open(f'{w}/MANIFEST.json', 'w'), indent=1)
PY
( cd "$WORK" && sha256sum "$DB.dump" "$DB.toc" evidence_v2.tar.gz evidence_v2.list evidence_v2.manifest.json MANIFEST.json > SHA256SUMS ) || fail "checksums failed"
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
