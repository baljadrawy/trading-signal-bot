#!/usr/bin/env bash
# Bounded ISOLATED validation V8b (NOT a G3): realistic Docker HEALTHCHECK probes (collector RUNNING, health file
# written), the v8 sampler at 200 ms (dense) besides the normal 5 s monitor, and exact-command injections placed
# mid-interval (15 s after a real Docker run) into THIS test container only. --network none; 0.5 CPU/384 MiB/64 PIDs.
set -euo pipefail
OUT=$1; IMAGE=$2; WT=$(cd "$(dirname "$0")/.." && pwd); C=tsb-p2f-v8-validation
mkdir -p "$OUT/data"; docker rm -f $C >/dev/null 2>&1 || true
echo '{"enabled": true, "profile": "tier0_only", "max_runtime_s": 840, "data_dir": "/data", "host_label": "v8-validation-offline"}' > "$OUT/config.json"
ID=$(docker image inspect "$IMAGE" --format '{{.Id}}')
docker run -d --name $C --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --user 1000:1000 \
  --cpus 0.5 --memory 384m --memory-swap 384m --pids-limit 64 --tmpfs /tmp:size=16m,mode=1777 --restart no \
  --label tsb.purpose=g3v7-f1-v8-validation -v "$OUT/data":/data -v "$OUT/config.json":/config/collector.json:ro \
  -e P2F_CONFIG=/config/collector.json -e P2F_IMAGE_ID=$ID "$IMAGE" >/dev/null
START=$(date +%s); CID=$(docker inspect -f '{{.Id}}' $C); CG=/sys/fs/cgroup/system.slice/docker-$CID.scope
echo "{\"container_start_ms\": $((START*1000)), \"image\": \"$IMAGE\", \"id\": \"$ID\"}" > "$OUT/run.json"
P2F_MONITOR_CONTAINER=$C setsid nohup bash "$WT/ops/p2f_gate_monitor.sh" V8 1200 "$OUT" "$OUT/data" > "$OUT/monitor_stdout.txt" 2>&1 < /dev/null &
( echo "h"; while [ -d $CG ]; do printf '%s\t%s\t-\t-\t-\t-\t-\t%s\n' "$(date +%s%N)" "$(cat $CG/cpu.max 2>/dev/null)" "$(python3 "$WT/ops/p2f_proc_sample.py" "$CID" 2>/dev/null)"; sleep 0.2; done ) > "$OUT/V8dense_cgroup.tsv" &
HC_CMD=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['Test'][1])" <(docker inspect $C --format '{{json .Config.Healthcheck}}'))
sleep 240
for k in 1 2 3 4 5 6 7 8; do
  S=$(docker inspect $C --format '{{json .State.Health.Log}}' | python3 -c "import json,sys;l=json.load(sys.stdin);print(l[-1]['Start'])")
  python3 - "$S" <<'P'
import sys, time, datetime as dt
s = sys.argv[1]; s = s[:26] + s[-6:] if "." in s else s
t = dt.datetime.fromisoformat(s).timestamp() + 15.0
while time.time() < t: time.sleep(0.05)
P
  t0=$(date +%s%3N); docker exec -d $C /bin/sh -c "$HC_CMD"; echo "{\"name\":\"exact_hc_cmd_mid_interval_$k\",\"t_ms\":$t0}" >> "$OUT/injections.jsonl"
  sleep 20
done
t0=$(date +%s%3N); docker exec -d $C sleep 8; echo "{\"name\":\"arbitrary_sleep\",\"t_ms\":$t0}" >> "$OUT/injections.jsonl"
while [ "$(docker inspect -f '{{.State.Running}}' $C)" = "true" ]; do sleep 5; done
sleep 8; docker inspect $C --format 'exit={{.State.ExitCode}} oom={{.State.OOMKilled}} finished={{.State.FinishedAt}}' > "$OUT/exit.txt"
docker rm $C >/dev/null; echo done > "$OUT/done"
