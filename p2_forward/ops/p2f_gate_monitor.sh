#!/bin/bash
# G2-Repeat monitor (observes only): resource samples every 60 s; external hard stop at deadline; exit state.
G=$1; DEADLINE_S=$2; E=$3; DATA=$4; C=tsb-p2-forward-collector
OUT=$E/${G}_resources.tsv; echo -e "utc\tcpu\tmem\tpids\tload1\thost_free_gb\tstate\tqueue\tqueue_peak\tloop_lag_max\tws_msgs_per_s\tdocker_health" > $OUT
START=$(date +%s)
while docker ps --filter name=$C --filter status=running -q | /usr/bin/grep -q .; do
  S=$(docker stats --no-stream --format '{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}' $C 2>/dev/null)
  H=$(python3 -c "import json;h=json.load(open('$DATA/health/collector_health.json'));print(h['state'],h.get('queue_depth'),h.get('queue_peak'),(h.get('loop_lag_ms') or {}).get('max_60s'),'/'.join(str(w.get('msgs_per_s')) for w in h.get('ws',[])),sep='\t')" 2>/dev/null)
  DH=$(docker inspect $C --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null)
  echo -e "$(date -u +%FT%TZ)\t$S\t$(cut -d' ' -f1 /proc/loadavg)\t$(df -BG --output=avail / | tail -1 | tr -dc 0-9)\t$H\t$DH" >> $OUT
  if [ $(( $(date +%s) - START )) -ge $DEADLINE_S ]; then
    echo "$(date -u +%FT%TZ) DEADLINE reached: external stop" >> $E/${G}_monitor.log
    docker stop -t 150 $C >> $E/${G}_monitor.log 2>&1; break
  fi
  sleep 60
done
echo "$(date -u +%FT%TZ) container exited: $(docker inspect $C --format 'status={{.State.Status}} exit={{.State.ExitCode}} started={{.State.StartedAt}} finished={{.State.FinishedAt}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}')" >> $E/${G}_monitor.log
