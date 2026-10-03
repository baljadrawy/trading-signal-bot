#!/bin/bash
# G2-Repeat monitor (observes only): resource samples every 60 s; external hard stop at deadline; exit state.
G=$1; DEADLINE_S=$2; E=$3; DATA=$4; C=tsb-p2-forward-collector
OUT=$E/${G}_resources.tsv; echo -e "utc\tcpu\tmem\tpids\tload1\thost_free_gb\tstate\tqueue\tqueue_peak\tloop_lag_max\tws_msgs_per_s\tdocker_health" > $OUT
START=$(date +%s)
CG_OUT=$E/${G}_cgroup.tsv; echo -e "utc_ns\tcpu_max\tcpu_stat(usage_usec,user_usec,system_usec,nr_periods,nr_throttled,throttled_usec)" > $CG_OUT
CID=$(docker inspect $C --format '{{.Id}}'); CG=/sys/fs/cgroup/system.slice/docker-$CID.scope
cg_sample() { [ -r $CG/cpu.stat ] && echo -e "$(date +%s%N)\t$(cat $CG/cpu.max)\t$(awk '{printf "%s=%s,",$1,$2}' $CG/cpu.stat)" >> $CG_OUT; }
LAST_STATS=0
while docker ps --filter name=$C --filter status=running -q | /usr/bin/grep -q .; do
  cg_sample
  NOW=$(date +%s); SOH=$(( NOW % 3600 ))
  if [ $(( NOW - LAST_STATS )) -lt 60 ]; then                  # G3-F4: 5 s cgroup sampling near rotations / the end
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
  if [ $SOH -ge 3540 ] || [ $SOH -le 120 ] || [ $(( NOW - START )) -ge $(( DEADLINE_S - 900 )) ]; then sleep 5; else sleep 55; fi
done
cg_sample
echo "$(date -u +%FT%TZ) container exited: $(docker inspect $C --format 'status={{.State.Status}} exit={{.State.ExitCode}} started={{.State.StartedAt}} finished={{.State.FinishedAt}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}')" >> $E/${G}_monitor.log
