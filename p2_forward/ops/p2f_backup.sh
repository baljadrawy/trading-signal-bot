#!/bin/bash
# P2 forward sealed-day backup (P2-CR Package D; F29 corrected). Thin wrapper; the logic is p2f_backup.py.
#   p2f_backup.sh backup <dataset_dir> <YYYY-MM-DD> | restore-test <dataset_dir> <YYYY-MM-DD>
# Only SEALED (independently verified, PASS) days are copied; .idx files, manifests, day-close, seal, run/downtime
# records and universe artifacts are included; free-space precheck; immutable destination; never deletes.
# Owner decision D1: ON-HOST backup for the initial continuous period (NOT disaster recovery).
# NOT SCHEDULED by this package: scheduling needs owner authorization at the continuous start gate.
set -euo pipefail
exec python3 "$(dirname "$(readlink -f "$0")")/p2f_backup.py" "$@"
