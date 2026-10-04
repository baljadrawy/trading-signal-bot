#!/bin/bash
# OPERATOR, gated: start the isolated continuous collector ONCE (P2-CR; owner decision D3: restart "no", manual
# gated restarts only). Never touches the production project. Refuses unless every check passes.
# usage: p2f_continuous_up.sh <image_tag> <expected_image_id> <dataset_dir> <config_file> <compose_file>
# Env: P2F_ACK_PREVIOUS=<boot8>  required when the previous run of this dataset did not stop cleanly (crash / kill /
#      fail-closed): the operator confirms the evidence-preservation steps of the runbook were done.
set -euo pipefail
IMG=$1; IID=$2; DATA=$3; CFG=$4; COMPOSE=$5; C=tsb-p2-forward-collector
fail() { echo "REFUSED: $*"; exit 2; }
actual=$(docker image inspect "$IMG" --format '{{.Id}}') || fail "image missing"
[ "$actual" = "$IID" ] || fail "IMAGE_ID_MISMATCH tag=$IMG actual=$actual expected=$IID"
[ -d "$DATA" ] || fail "DATA_DIR_MISSING $DATA"
[ -z "$(docker ps -q --filter name=^/$C$)" ] || fail "collector already running"
/usr/bin/grep -qE '^\s*restart: "no"' "$COMPOSE" || fail "compose restart policy is not \"no\""
! /usr/bin/grep -qE 'docker\.sock|ports:|network_mode: *host|privileged' "$COMPOSE" || fail "compose isolation check"
python3 - "$CFG" "$DATA" <<'PY' || fail "config / dataset / incident gate"
import json, os, sys
cfg, data = json.load(open(sys.argv[1])), sys.argv[2]
assert cfg.get("enabled") is True and cfg.get("mode") == "continuous" and cfg.get("max_runtime_s") == 0, "not an explicit continuous config"
assert cfg.get("data_dir", "/data") == "/data", "data_dir must be /data (the mount)"
ds = os.path.join(data, "dataset.json")
if os.path.exists(ds):
    assert json.load(open(ds))["dataset_id"] == cfg["dataset_id"], "dataset_id mismatch"
else:
    assert not [x for x in os.listdir(data) if not x.startswith(".")], "fresh dataset dir must be empty"
st = os.path.join(data, "incidents", "state.json")
if os.path.exists(st):
    crit = [i["id"] for i in json.load(open(st))["incidents"] if i["active"] and i["ack"] is None and i["severity"] == "CRITICAL"]
    assert not crit, f"unacknowledged CRITICAL incidents: {crit[:5]} (p2f_incident_ack.sh after review)"
runs = sorted((json.load(open(os.path.join(data, "runs", f))) for f in os.listdir(os.path.join(data, "runs")) if f.startswith("run-")),
              key=lambda r: r["created_ms"]) if os.path.isdir(os.path.join(data, "runs")) else []
if runs:
    b = runs[-1]["boot_id"]; mk = os.path.join(data, "control", f"stop-{b[:8]}.json")
    clean = os.path.exists(mk) and json.load(open(mk)).get("state") == "STOPPED"
    print(f"previous run {b[:8]}: {'STOPPED cleanly' if clean else 'NOT a clean stop'}")
    if not clean:
        assert os.environ.get("P2F_ACK_PREVIOUS") == b[:8], f"previous run {b[:8]} did not stop cleanly: set P2F_ACK_PREVIOUS={b[:8]} after the runbook evidence steps"
PY
P2F_IMAGE=$IMG P2F_IMAGE_ID=$IID P2F_DATA_DIR=$DATA P2F_CONFIG_FILE=$CFG \
  docker compose -p tsb-p2-forward -f "$COMPOSE" up -d --no-build --pull never --force-recreate collector
run_img=$(docker inspect $C --format '{{.Image}}')
if [ "$run_img" != "$IID" ]; then docker stop -t 450 $C; fail "RUNNING_IMAGE_MISMATCH $run_img"; fi
echo "UP OK $(date -u +%FT%TZ) cid=$(docker inspect $C --format '{{.Id}}') image=$run_img data=$DATA config=$CFG restart=$(docker inspect $C --format '{{.HostConfig.RestartPolicy.Name}}')"
