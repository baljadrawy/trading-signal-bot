#!/bin/bash
# P2 forward-data backup (PREPARED ONLY — NOT SCHEDULED in P2-E1; activation needs owner authorization).
# Usage: p2f_backup.sh backup <YYYY-MM-DD> | restore-test <YYYY-MM-DD>
# Copies only CERTIFIED segments listed in manifests/<day>.jsonl, verifying SHA-256 at source and destination.
# Never deletes source data. Same-host copy != off-host protection (owner D4).
set -euo pipefail; umask 077
SRC=${P2F_SRC:-/home/tradmin/research-data/trading-signal-bot/p2/forward}
DST=${P2F_DST:-/home/tradmin/backups/tsb-p2-forward}
MODE=${1:?mode}; DAY=${2:?YYYY-MM-DD}
[[ "$DAY" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "bad day"; exit 2; }
mkdir -p "$DST"; exec 9>"$DST/.lock"; flock -n 9 || { echo "another backup running"; exit 75; }
MAN="$SRC/manifests/$DAY.jsonl"; OUT="$DST/$DAY"
verify_set() {  # $1 base dir containing the segment paths of the manifest
  python3 - "$MAN" "$1" <<'PY'
import json,hashlib,sys
man,base=sys.argv[1:]; bad=0; n=0
for line in open(man):
    e=json.loads(line); n+=1; p=f"{base}/{e['segment']}"
    h=hashlib.sha256(open(p,'rb').read()).hexdigest()
    side=open(p+'.sha256').read().split()[0]
    if h!=e['sha256'] or side!=h: bad+=1; print('MISMATCH',e['segment'])
print(f'segments={n} mismatches={bad}'); sys.exit(1 if bad or n==0 else 0)
PY
}
if [ "$MODE" = backup ]; then
  [ -f "$MAN" ] || { echo "no manifest for $DAY"; exit 3; }
  verify_set "$SRC"
  [ ! -e "$OUT" ] || { echo "destination exists (immutable): $OUT"; exit 4; }
  TMP="$DST/.incomplete-$DAY"; rm -rf "$TMP"; mkdir -p "$TMP/manifests"
  cp -p "$MAN" "$TMP/manifests/"
  python3 - "$MAN" "$SRC" "$TMP" <<'PY'
import json,shutil,os,sys
man,src,tmp=sys.argv[1:]
for line in open(man):
    seg=json.loads(line)['segment']
    for suf in ('','.sha256'):
        os.makedirs(os.path.dirname(f"{tmp}/{seg}"),exist_ok=True); shutil.copy2(f"{src}/{seg}{suf}",f"{tmp}/{seg}{suf}")
PY
  MAN="$TMP/manifests/$DAY.jsonl" verify_set "$TMP"
  (cd "$TMP" && find . -type f ! -name SHA256SUMS | sort | xargs sha256sum > SHA256SUMS)
  sync; mv -T "$TMP" "$OUT"; chmod -R a-w "$OUT"; echo "backup OK $OUT"
elif [ "$MODE" = restore-test ]; then
  MAN="$OUT/manifests/$DAY.jsonl"; (cd "$OUT" && sha256sum -c --quiet SHA256SUMS); verify_set "$OUT"
  python3 -c "
import gzip,json,sys,glob
n=0
for p in glob.glob('$OUT/raw/*/$DAY/*.jsonl.gz'):
    for l in gzip.open(p,'rt'): json.loads(l); n+=1
print('restore-test decoded records',n)"
else echo "unknown mode"; exit 2; fi
