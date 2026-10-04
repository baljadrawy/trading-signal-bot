#!/usr/bin/env bash
# Post-process one stress run: analysis + independent verifier (integrity mode) on a copy WITHOUT the injected load.
set -euo pipefail
R=$1; WT=$(cd "$(dirname "$0")/.." && pwd); PY=${STRESS_VERIFY_PY:-python3}
python3 "$WT/stress/analyze.py" "$R" > "$R/out/analysis_summary.txt"
V=$R/verifycopy; rm -rf "$V"; cp -a "$R/data" "$V"; rm -rf "$V"/raw/zl* "$V/manifests/2099-01-01.jsonl"
set +e; timeout 600 "$PY" "$WT/verifier/verify_independent.py" "$V" --json "$R/out/verify_integrity.json" > "$R/out/verify_integrity.txt" 2>&1
echo "verifier_rc=$?" >> "$R/out/verify_integrity.txt"; set -e
rm -rf "$V"
