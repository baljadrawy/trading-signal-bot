#!/bin/bash
# OPERATOR: acknowledge ONE incident after review. Writes incidents/ack/<id>.json ONCE (0444, never overwritten) as a
# hash-bound record of exactly that incident (id, key, severity, boot, opened/last time, full-record sha256), dataset and
# run lineage (p2f_ack_binding.py). Works while the collector is RUNNING (it merges the file into state.json within one
# health interval) and while it is STOPPED (p2f_continuous_up.sh validates the binding; the next run merges it).
# usage: p2f_incident_ack.sh <dataset_dir> <incident_id> <by> <reference> <reason>
set -euo pipefail
[ $# -eq 5 ] || { echo "usage: $0 <dataset_dir> <incident_id> <by> <reference> <reason>"; exit 64; }
HERE=$(cd "$(dirname "$0")" && pwd)
exec python3 -B "$HERE/p2f_ack_binding.py" ack "$1" "$2" "$3" "$4" "$5"
