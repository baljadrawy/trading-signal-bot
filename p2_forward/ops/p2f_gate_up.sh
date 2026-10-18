#!/bin/bash
# Start the ISOLATED collector project (tsb-p2-forward) for one bounded gate, with identity checks (review N1).
# usage: p2f_gate_up.sh <image_tag> <expected_image_id> <data_dir> <config_file> <compose_file>
# Never touches the production project; restart "no"; no scheduling.
set -euo pipefail
IMG=$1; IID=$2; DATA=$3; CFG=$4; COMPOSE=$5
actual=$(docker image inspect "$IMG" --format '{{.Id}}')
[ "$actual" = "$IID" ] || { echo "IMAGE_ID_MISMATCH tag=$IMG actual=$actual expected=$IID"; exit 2; }
[ -d "$DATA" ] || { echo "DATA_DIR_MISSING $DATA"; exit 2; }
P2F_IMAGE=$IMG P2F_IMAGE_ID=$IID P2F_DATA_DIR=$DATA P2F_CONFIG_FILE=$CFG \
  docker compose -p tsb-p2-forward -f "$COMPOSE" up -d --no-build --pull never --force-recreate collector
run_img=$(docker inspect tsb-p2-forward-collector --format '{{.Image}}')
if [ "$run_img" != "$IID" ]; then
  docker stop -t 30 tsb-p2-forward-collector; echo "RUNNING_IMAGE_MISMATCH $run_img"; exit 3
fi
echo "UP OK $(date -u +%FT%TZ) image=$run_img data=$DATA config=$CFG"
