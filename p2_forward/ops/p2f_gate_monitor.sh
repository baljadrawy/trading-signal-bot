#!/bin/bash
# Gate monitor (observes only): docker stats + health every 60 s, cgroup + process roles every 5 s; external hard stop
# at deadline; exit state.
G=$1; DEADLINE_S=$2; E=$3; DATA=$4; C=tsb-p2-forward-collector
OUT=$E/${G}_resources.tsv; echo -e "utc\tcpu\tmem\tpids\tload1\thost_free_gb\tstate\tqueue\tqueue_peak\tloop_lag_max\tws_msgs_per_s\tdocker_health" > $OUT
START=$(date +%s)
CG_OUT=$E/${G}_cgroup.tsv; echo -e "utc_ns\tcpu_max\tcpu_stat(usage_usec,user_usec,system_usec,nr_periods,nr_throttled,throttled_usec)\tmemory_max\tpids_max\tmemory_current\tpids_current\tprocs(pid=role)" > $CG_OUT
CID=$(docker inspect $C --format '{{.Id}}'); CG=/sys/fs/cgroup/system.slice/docker-$CID.scope
# G3-F4 (v7): every process of the container's OWN cgroup scope, by role (collector = PID 1 entrypoint, certifier =
# multiprocessing spawn child, tracker = multiprocessing resource tracker) -> same-cgroup proof for the whole run.
role() { case "$(tr '\0' ' ' < /proc/$1/cmdline 2>/dev/null)" in *spawn_main*) echo certifier;; *resource_tracker*) echo tracker;;
  *"-m p2_forward"*) echo collector;; *) echo other;; esac; }
cg_sample() { [ -r $CG/cpu.stat ] || return 0; P=""; for p in $(cat $CG/cgroup.procs 2>/dev/null); do P="$P$p=$(role $p),"; done
  echo -e "$(date +%s%N)\t$(cat $CG/cpu.max)\t$(awk '{printf "%s=%s,",$1,$2}' $CG/cpu.stat)\t$(cat $CG/memory.max)\t$(cat $CG/pids.max)\t$(cat $CG/memory.current)\t$(cat $CG/pids.current)\t$P" >> $CG_OUT; }
LAST_STATS=0
while docker ps --filter name=$C --filter status=running -q | /usr/bin/grep -q .; do
  cg_sample
  NOW=$(date +%s)
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
cg_sample
echo "$(date -u +%FT%TZ) container exited: $(docker inspect $C --format 'status={{.State.Status}} exit={{.State.ExitCode}} started={{.State.StartedAt}} finished={{.State.FinishedAt}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}')" >> $E/${G}_monitor.log
