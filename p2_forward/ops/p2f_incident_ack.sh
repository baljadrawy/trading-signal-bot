#!/bin/bash
# OPERATOR: acknowledge ONE incident after review (writes incidents/ack/<id>.json; the collector only reads it).
# usage: p2f_incident_ack.sh <dataset_dir> <incident_id> <by> <reference>
set -euo pipefail
DATA=$1; ID=$2; BY=$3; REF=$4
python3 - "$DATA" "$ID" "$BY" "$REF" <<'PY'
import json, os, sys, time
data, iid, by, ref = sys.argv[1:]
st = json.load(open(os.path.join(data, "incidents", "state.json")))
inc = [i for i in st["incidents"] if i["id"] == iid]
assert inc, f"unknown incident {iid}"
p = os.path.join(data, "incidents", "ack", f"{iid}.json")
assert not os.path.exists(p), "already acknowledged"
assert ref.strip(), "a reference (ticket / evidence path) is required"
with open(p + ".tmp", "w") as fh:
    json.dump({"by": by, "ref": ref, "ts_ms": int(time.time() * 1000)}, fh)
os.rename(p + ".tmp", p); os.chmod(p, 0o444)
print("ACK", iid, inc[0]["key"], inc[0]["severity"])
PY
