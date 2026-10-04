#!/bin/bash
# Gate monitor (observes only): docker stats + health every 60 s, cgroup + process roles every 5 s; external hard stop
# at deadline; exit state.
G=$1; DEADLINE_S=$2; E=$3; DATA=$4; C=${P2F_MONITOR_CONTAINER:-tsb-p2-forward-collector}
SAMPLER=$(dirname "$(readlink -f "$0")")/p2f_proc_sample.py      # v8: per-process identity (host side, read-only)
OUT=$E/${G}_resources.tsv; echo -e "utc\tcpu\tmem\tpids\tload1\thost_free_gb\tstate\tqueue\tqueue_peak\tloop_lag_max\tws_msgs_per_s\tdocker_health" > $OUT
START=$(date +%s)
CG_OUT=$E/${G}_cgroup.tsv; echo -e "utc_ns\tcpu_max\tcpu_stat(usage_usec,user_usec,system_usec,nr_periods,nr_throttled,throttled_usec)\tmemory_max\tpids_max\tmemory_current\tpids_current\tprocs(pid=role)\tdetail(json)" > $CG_OUT
CID=$(docker inspect $C --format '{{.Id}}'); CG=/sys/fs/cgroup/system.slice/docker-$CID.scope
# v8 (G3V7-F1): every process of the container's OWN cgroup scope with its identity (pid, ppid, ns pid, comm, command,
# exe, own cgroup, parent command; incomplete transients followed up to 2 s; collector descendants outside the scope).
# Column 8 = human role hints only; acceptance re-derives roles independently from column 9.
cg_sample() { [ -r $CG/cpu.stat ] || return 0; T=$(date +%s%N); PD=$(python3 "$SAMPLER" "$CID" 2>/dev/null || printf 'sampler_error\t{"error":"sampler"}')
  echo -e "$T\t$(cat $CG/cpu.max)\t$(awk '{printf "%s=%s,",$1,$2}' $CG/cpu.stat)\t$(cat $CG/memory.max)\t$(cat $CG/pids.max)\t$(cat $CG/memory.current)\t$(cat $CG/pids.current)\t$PD" >> $CG_OUT; }
HC_OUT=$E/${G}_healthcheck_log.jsonl; LAST_HC=0                       # v8: Docker's own health log (keeps 5 runs)
docker inspect $C --format '{{json .Config.Healthcheck}}' > $E/${G}_healthcheck_config.json
hc_poll() { echo "{\"t_ms\":$(date +%s%3N),\"health\":$(docker inspect $C --format '{{json .State.Health}}' 2>/dev/null || echo null)}" >> $HC_OUT; }
LAST_STATS=0
while docker ps --filter name=$C --filter status=running -q | /usr/bin/grep -q .; do
  cg_sample
  NOW=$(date +%s)
  if [ $(( NOW - LAST_HC )) -ge 30 ]; then hc_poll; LAST_HC=$NOW; fi
  if [ $(( NOW - LAST_STATS )) -lt 60 ]; then                  # docker stats / health line every 60 s
    sleep 5; continue
  fi
  LAST_STATS=$NOW
  S=$(docker stats --no-stream --format '{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}' $C 2>/dev/null)
  H=$(python3 -c "import json;h=json.load(open('$DATA/health/collector_health.json'));print(h['state'],h.get('queue_depth'),h.get('queue_peak'),(h.get('loop_lag_ms') or {}).get('max_60s'),'/'.join(str(w.get('msgs_per_s')) for w in h.get('ws',[])),sep='\t')" 2>/dev/null)
  DH=$(docker inspect $C --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null)
  echo -e "$(date -u +%FT%TZ)\t$S\t$(cut -d' ' -f1 /proc/loadavg)\t$(df -BG --output=avail / | tail -1 | tr -dc 0-9)\t$H\t$DH" >> $OUT
  if [ $(( $(date +%s) - START )) -ge $DEADLINE_S ]; then
    echo "$(date -u +%FT%TZ) DEADLINE reached: external stop" >> $E/${G}_monitor.log
    docker stop -t 450 $C >> $E/${G}_monitor.log 2>&1; break
  fi
  sleep 5                                                       # v7: cgroup every 5 s for the whole run
done
cg_sample; hc_poll
echo "$(date -u +%FT%TZ) container exited: $(docker inspect $C --format 'status={{.State.Status}} exit={{.State.ExitCode}} started={{.State.StartedAt}} finished={{.State.FinishedAt}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}')" >> $E/${G}_monitor.log
