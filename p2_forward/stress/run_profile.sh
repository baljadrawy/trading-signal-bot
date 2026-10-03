#!/usr/bin/env bash
# G3-F4 bounded OFFLINE stress run (one profile). Dev/test only. No Binance, no external network, no credentials.
#   run_profile.sh <name> <runtime_s> <mult_plan> [inject_from]
# Env: STRESS_ROOT (scratch dir with tls/ load/ runs/), STRESS_IMAGE (runtime image providing python+aiohttp).
set -euo pipefail
NAME=$1; RUNTIME=$2; MULT=$3; FROM=${4:-2}
ROOT=${STRESS_ROOT:?}; IMAGE=${STRESS_IMAGE:?}
WT=$(cd "$(dirname "$0")/.." && pwd)                  # p2_forward/ (code mounted READ-ONLY)
HOUR_S=${STRESS_HOUR_S:-180}
TS=$(date -u +%Y%m%dT%H%M%SZ)
RUN=$ROOT/runs/$NAME-$TS; mkdir -p "$RUN/data" "$RUN/out"
FX=tsb-p2f-stress-fakex; CO=tsb-p2f-stress-collector
docker rm -f $FX $CO >/dev/null 2>&1 || true
COMMON=(--read-only --cap-drop ALL --security-opt no-new-privileges:true --user 1000:1000
        --label tsb.purpose=g3f4-offline-stress -v "$WT":/work:ro -v "$ROOT/tls":/tls:ro -v "$RUN/out":/out
        -w /work --entrypoint python -e PYTHONDONTWRITEBYTECODE=1 -e STRESS_OUT=/out)
docker run -d --name $FX --network none --cpus 1.0 --memory 256m --pids-limit 32 "${COMMON[@]}" \
  -e STRESS_TLS_CERT=/tls/server.pem -e STRESS_TLS_KEY=/tls/server.key "$IMAGE" -m stress fakex >/dev/null
sleep 2
docker run -d --name $CO --network container:$FX --cpus 0.5 --memory 384m --memory-swap 384m --pids-limit 64 \
  --tmpfs /tmp:size=16m,mode=1777 "${COMMON[@]}" -v "$RUN/data":/data \
  -e STRESS_TLS_CA=/tls/ca.pem -e STRESS_HOUR_S=$HOUR_S -e STRESS_RUNTIME_S=$RUNTIME -e STRESS_SEED=42 \
  -e P2F_GIT_COMMIT="$(git -C "$WT" rev-parse HEAD)-stress" -e P2F_IMAGE_ID="stress:$IMAGE" \
  "$IMAGE" -m stress collector >/dev/null
CID=$(docker inspect -f '{{.Id}}' $CO)
{ echo "name=$NAME runtime=$RUNTIME mult=$MULT inject_from=$FROM hour_s=$HOUR_S image=$IMAGE"
  echo "image_id=$(docker inspect -f '{{.Image}}' $CO) cid=$CID git=$(git -C "$WT" rev-parse HEAD) dirty=$(git -C "$WT" status --porcelain | wc -l)"
  docker inspect -f 'cpus={{.HostConfig.NanoCpus}} mem={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}} pids={{.HostConfig.PidsLimit}} net={{.HostConfig.NetworkMode}} ro={{.HostConfig.ReadonlyRootfs}} caps={{.HostConfig.CapDrop}}' $CO
  docker inspect -f 'fakex: cpus={{.HostConfig.NanoCpus}} net={{.HostConfig.NetworkMode}}' $FX
} > "$RUN/out/run_meta.txt"
python3 "$WT/stress/hostmon.py" --cid "$CID" --data "$RUN/data" --out "$RUN/out" --load "$ROOT/load" \
  --hour-s $HOUR_S --mult "$MULT" --inject-from "$FROM" > "$RUN/out/hostmon.log" 2>&1 &
HM=$!
# bounded wait: runtime + certification drain + margin, then a bounded stop (same 450 s grace as G3)
DEADLINE=$(( $(date +%s) + RUNTIME + 900 ))
while [ "$(docker inspect -f '{{.State.Running}}' $CO)" = "true" ]; do
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then echo "DEADLINE: docker stop -t 450" >> "$RUN/out/run_meta.txt"; docker stop -t 450 $CO >/dev/null; fi
  sleep 5
done
docker inspect -f 'exit={{.State.ExitCode}} oom={{.State.OOMKilled}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}' $CO >> "$RUN/out/run_meta.txt"
wait $HM || true
docker logs $CO > "$RUN/out/collector.log" 2>&1 || true
docker logs $FX > "$RUN/out/fakex.log" 2>&1 || true
docker rm -f $FX >/dev/null; docker rm $CO >/dev/null
echo "$RUN"
