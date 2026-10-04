#!/usr/bin/env bash
# Bounded ISOLATED validation of the v8 process-role monitor (NOT a G3). Real collector image + entrypoint + Docker
# HEALTHCHECK at 0.5 CPU / 384 MiB / 64 PIDs, --network none (no Binance), test-only config and data, then
# test-only negative controls injected with `docker exec` into THIS test container only.
set -euo pipefail
OUT=$1; IMAGE=$2; WT=$(cd "$(dirname "$0")/.." && pwd); C=tsb-p2f-v8-validation
mkdir -p "$OUT/data"; docker rm -f $C >/dev/null 2>&1 || true
cat > "$OUT/config.json" <<'J'
{"enabled": true, "profile": "recommended", "max_runtime_s": 3600, "data_dir": "/data", "host_label": "v8-validation-offline", "universe_load_attempts": 5, "universe_retry_backoff_s": [300]}
J
ID=$(docker image inspect "$IMAGE" --format '{{.Id}}')
docker run -d --name $C --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --user 1000:1000 \
  --cpus 0.5 --memory 384m --memory-swap 384m --pids-limit 64 --tmpfs /tmp:size=16m,mode=1777 --restart no \
  --label tsb.purpose=g3v7-f1-v8-validation -v "$OUT/data":/data -v "$OUT/config.json":/config/collector.json:ro \
  -e P2F_CONFIG=/config/collector.json -e P2F_IMAGE_ID=$ID "$IMAGE" >/dev/null
START=$(date +%s); echo "{\"container_start_ms\": $((START*1000)), \"image\": \"$IMAGE\", \"id\": \"$ID\"}" > "$OUT/run.json"
P2F_MONITOR_CONTAINER=$C setsid nohup bash "$WT/ops/p2f_gate_monitor.sh" V8 1500 "$OUT" "$OUT/data" > "$OUT/monitor_stdout.txt" 2>&1 < /dev/null &
HC_CMD=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['Test'][1])" <(docker inspect $C --format '{{json .Config.Healthcheck}}'))
inject() {  # name, delay_from_start, command...
  local n=$1 at=$2; shift 2
  while [ $(( $(date +%s) - START )) -lt $at ]; do sleep 1; done
  local t0=$(date +%s%3N); docker exec -d $C "$@"; echo "{\"name\":\"$n\",\"t_ms\":$t0,\"argv\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1:]))' "$@")}" >> "$OUT/injections.jsonl"
}
inject arbitrary_sleep 700 sleep 20
inject arbitrary_shell 760 /bin/sh -c "sleep 20"
inject arbitrary_python 820 python -c "import time; time.sleep(20)"
inject exact_hc_cmd_off_schedule_1 880 /bin/sh -c "$HC_CMD"
inject exact_hc_cmd_off_schedule_2 883 /bin/sh -c "$HC_CMD"
inject long_lived_imitation 940 /bin/sh -c "$HC_CMD; sleep 20"
while [ "$(docker inspect -f '{{.State.Running}}' $C)" = "true" ]; do sleep 5; done
sleep 8; docker inspect $C --format 'exit={{.State.ExitCode}} oom={{.State.OOMKilled}} finished={{.State.FinishedAt}}' > "$OUT/exit.txt"
docker rm $C >/dev/null; echo done > "$OUT/done"
