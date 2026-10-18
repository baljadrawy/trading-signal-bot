#!/bin/bash
# OPERATOR, gated: clean stop of the continuous collector (graceful drain/certify; compose stop_grace_period 450 s).
# Never removes the container, the network or any data. Prints the final state from the collector's stop marker.
# usage: p2f_continuous_stop.sh <dataset_dir> <compose_file>
set -euo pipefail
DATA=$1; COMPOSE=$2; C=tsb-p2-forward-collector
[ -n "$(docker ps -q --filter name=^/$C$)" ] || { echo "collector not running"; exit 3; }
CID=$(docker inspect $C --format '{{.Id}}')
P2F_IMAGE=x P2F_IMAGE_ID=x P2F_DATA_DIR=$DATA P2F_CONFIG_FILE=/dev/null \
  docker compose -p tsb-p2-forward -f "$COMPOSE" stop collector
docker inspect $C --format 'exit={{.State.ExitCode}} oom={{.State.OOMKilled}} finished={{.State.FinishedAt}}'
python3 - "$DATA" "$CID" <<'PY'
import json, os, sys
data = sys.argv[1]
mk = sorted((os.path.join(data, "control", f) for f in os.listdir(os.path.join(data, "control")) if f.startswith("stop-")), key=os.path.getmtime)[-1]
m = json.load(open(mk)); print("stop marker:", os.path.basename(mk), {k: m.get(k) for k in ("state", "exit_code", "reason", "partials")})
PY
