# Research execution layer (G2)

**Status:** built and validated 2026-10-06. Stage 1 of the owner-approved host resource governance. Usage is in [ops/research/README.md](../../ops/research/README.md); the governing rules are in [BACKGROUND_EXECUTION.md](BACKGROUND_EXECUTION.md).

**Scope.** The layer protects the forward Collector and production services from research batch work on the shared VM. Its host has 12 shared ARM vCPUs, about 28 % steal and no swap. It also makes parallel research fast and reproducible. It **cannot** prevent provider VM stalls, host-node storage stalls or the steal tax. Under a whole-VM pause, the job, the watchdog and the Collector all stop together.

## Architecture
```
research-run run ... -- CMD            (caller: agent shell or human; may exit, job stays supervised)
  1. admission.evaluate()  -> admission.json (decision + every input); refuse => exit 3, nothing started
  2. systemctl --user set-property --runtime research.slice  CPUWeight=idle CPUQuota=800% MemoryMax=12G TasksMax=1024
  3. systemd-run --user  rj-<id>.service  (slice research.slice)
        CPUQuota=<profile>  CPUWeight=idle  MemoryHigh/MemoryMax  TasksMax  OOMScoreAdjust=500
        OOMPolicy=kill (memory.oom.group=1)  KillMode=control-group  TimeoutStopSec=20  RuntimeMaxSec
        main = python -m research_exec _jobwrap   -> flock <state>/<lock>.lock (held for the job's life)
                                                   -> CMD (env RESEARCH_WORKERS, PYTHONHASHSEED=0, *_NUM_THREADS=1)
                                                   -> jobwrap.json (wall, rusage, cgroup cpu.stat/memory.peak at exit)
  4. systemd-run --user  rw-<id>.service  (app.slice, CPUQuota=20%, MemoryMax=128M, --collect)
        BindsTo=rj After=rj RuntimeMaxSec=job+900  main = python -m research_exec _watchdog
        tick 2 s: Collector health + monitor + steal(5 s window) + PSI + MemAvailable + windows + pause file
          freeze triggers -> systemctl --user freeze rj      (cgroup v2 freezer: paused, not destroyed)
          clean for resume_clean_s (120 s) -> thaw
          frozen > max_frozen_s (70 min) | MemAvailable < 3 GiB | PSI mem full avg10 > 10 % -> SIGKILL whole cgroup + stop
        exit: writes watchdog_summary.json + job_record.json; reset-failed on a failed job unit
  5. --wait: waits on UNIT STATE (bounded) and prints job_record.json
```
- **Why two units.** A freeze stops every process in a cgroup, so the watchdog must live outside the job's cgroup to be able to thaw it.
- **Why the watchdog can never outlive the job.** Three independent bounds apply:
  - `BindsTo=`: systemd stops the watchdog when the job stops;
  - the watchdog's own loop exits as soon as the job is inactive;
  - the watchdog's `RuntimeMaxSec`.
- **Fail-closed.** If the watchdog is stopped while the job is still active, it kills the job. If the watchdog unit fails to start, the launcher stops the job. Research never runs unsupervised.
- **Why the lock is in jobwrap.** `systemd-run` cannot pass an fd, so the launcher's lock check is only advisory. The authoritative `flock` is held by the job's main process for the job's whole life, frozen periods included. If the lock is busy, the job exits with code 75 and nothing runs.

## Envelope (config `PROFILES`, `SLICE`)
| profile | workers | CPUQuota | MemoryHigh / Max | TasksMax | oom_score_adj | max runtime | opt-in |
|---|---|---|---|---|---|---|---|
| R1 (default) | 4 | 400 % | 8 G / 10 G | 512 | +500 | 12 h | none |
| R2 | 6 | 600 % | 8 G / 10 G | 512 | +500 | 12 h | `--allow-elevated` |
| R3 | 8 | 800 % | 8 G / 10 G | 512 | +500 | 6 h | `--attended` |
| LIGHT | 2 | 200 % | 2 G / 3 G | 256 | +500 | 2 h | none; separate `light` lock |

- Workers and runtime can only be **lowered** below the profile.
- research.slice holds an aggregate runtime ceiling of 800 % / 12 G / 1024 tasks, so R3 is the hard maximum. Even with all ceilings in place, at least 4 vCPU stay free for production wake-ups, Hermes bursts and post-stall catch-up.
- `OOMScoreAdjust=+500` applies only to processes the layer launches; children inherit it. No host-wide OOM policy is changed.

## Admission (all must hold; config `admission`)
- **Collector:**
  - `state == HEALTHY`;
  - health age at most 30 s;
  - writer `durable_lag_ms` at most 5000 and `beat_age_ms` at most 3000.
- **Monitor:**
  - severity not DEGRADED or CRITICAL; the known WARNING incident is allowed;
  - `status.json` age at most 180 s.
- **Time:** not inside a protected window. These are UTC, half-open ranges:
  - hourly :12–:25;
  - daily 23:50–00:45;
  - daily 01:10–01:45.
- **Lock:** the heavy lock is free.
- **Host:**
  - PSI cpu some avg60 at most 10 % and PSI memory some avg60 at most 0.1 %;
  - MemAvailable at least the profile's MemoryMax + 6 GiB;
  - at least 150 GB free disk.
- **Steal**, over a 5 s sample:
  - steal ratio at most 0.40, judged only when the host has more than 0.5 vCPU of demand, because a near-idle host gives a noisy ratio;
  - steal at most 1.0 vCPU.
- An unreadable input counts as a refusal reason.

## Watchdog triggers (config `watchdog`)
- **Freeze** on any of:
  - Collector not HEALTHY;
  - health older than 30 s;
  - durable lag over 5 s;
  - beat age over 3 s;
  - loop lag over 5 s;
  - monitor DEGRADED or CRITICAL;
  - steal over 2.0 vCPU over 5 s;
  - PSI memory some avg10 over 1 %;
  - inside a protected window;
  - the operator `pause_file` exists.
- **Thaw** after 120 s clean.
- **Kill** the whole group if:
  - the job has been frozen for more than 4200 s (longer than the longest window, 55 min);
  - MemAvailable is below 3 GiB;
  - PSI memory full avg10 is above 10 %.

  A freeze does not release memory, so memory danger kills and does not freeze.
- **Telemetry.** A `sample` event is written to `watchdog.jsonl` every 30 s. It records Collector lag, steal, PSI, MemAvailable, job CPU, job memory and job throttling. This is the hook G5 will use.

## Deterministic parallelism (`research_exec.detpool`, stdlib)
- **Seeds.** A plan is an ordered list of `Unit(key, seed, params)`. Each seed is `derive_seed(base, key)`, taken from the first 63 bits of `sha256("base:key")`. It does not depend on `PYTHONHASHSEED`.
- **Execution.** Units run on `ProcessPoolExecutor` with the `spawn` start method. A worker death raises `BrokenProcessPool` and never hangs.
- **Merge.** Each result is serialised as canonical JSON (sorted keys, no whitespace, NaN forbidden). Results are merged **in plan order**, and `result_sha256` is the SHA-256 of the merged bytes. Neither the worker count nor the completion order can change it.
- **Checkpoint.**
  - The parent process is the single writer. Each unit is written atomically (temp file, fsync, rename, dir fsync) as `units/<key>.json`, followed by `units/<key>.sha256`.
  - `plan.json` binds the directory to one `plan_sha256`. A different plan raises `PlanMismatch`.
  - On resume, partial temp files and units whose digest, identity or parse fails are moved to `quarantine/` with a reason and recomputed. `strict=True` raises `CorruptUnit` instead.
  - `manifest.json` records per-unit digests, the reused, computed and rejected counts, and `result_sha256`. `verify_checkpoint()` audits a finished directory.
- **Function contract.** `fn(unit)` must be a pure top-level function of the unit. It should use `unit.rng()` and must not use global random state, time or PID.

## Measurement (per job: `<state_dir>/jobs/<id>/job_record.json`)
Each record holds:
- admission decision and reasons;
- status: finished, refused, killed, oom-killed, timeout, terminated or lock_busy;
- exit code;
- wall time, total frozen seconds and active wall time;
- CPU seconds, from cgroup `cpu.stat` and from rusage;
- `cpu_parallelism`;
- `memory.peak`, `pids.peak`, `throttled_usec` and memory events;
- freeze periods, with reasons;
- group kills.

For a job that was killed, the measurement comes from the watchdog's last 2 s sample (`measurement_source`).

## Evidence-based corrections to the governance review (2026-10-06)
- **Freezer.** Supported. `systemctl --user freeze/thaw` works on transient user services; `FreezerState` and `cgroup.events` show `frozen 1`. SIGKILL also works on a frozen unit.
- **Controllers.** Confirmed: user units get only `cpu memory pids`. IO caps remain impossible without root.
- **CPU weight.** `CPUWeight=idle` sets `cpu.weight 0, cpu.idle 1` on the unit, and on research.slice through the runtime set-property. As the review said, this only yields to siblings inside user@1000 (agents and the monitor). **The CPU quota is the real guard against system.slice.**
- **SIGTERM.** New finding: multiprocessing `spawn` workers and `resource_tracker` ignore SIGTERM (`SigIgn` includes bit 15). That is why the old orphans survived. The layer relies on cgroup-wide SIGKILL (`KillMode=control-group` plus `systemctl kill --kill-whom=all -s SIGKILL`), not on SIGTERM.
- **`--collect`.** A transient unit with `--collect` is unloaded before its `Result` (for example `oom-kill`) can be read. The job unit therefore omits `--collect`, and the watchdog runs `reset-failed` after recording the result.

## Limitations
- There are no IO limits, because user units have no io controller. Write output in modest streams.
- memory.low protection is ineffective until root sets ancestor protection (S6). Research is made the preferred OOM victim instead.
- Steal and VM pauses cannot be prevented. The watchdog freezes on a steal spike to leave room for catch-up after a stall.
- With `CPUWeight=idle`, research can be starved by agent sessions. That is acceptable for batch work.
- The runtime slice properties vanish when the user manager restarts and are re-applied at each launch. `Linger=no`: if every tradmin session ends, the user manager and any running job stop. That is acceptable for batch work, and G4 (the monitor unit plus linger) changes it.
- The monitor-freshness admission check refuses research if the monitor dies. That is intentional.

## Rollback
- Stop a job: `research-run kill --job-id ID`, or `systemctl --user stop rj-ID.service`.
- Remove the slice properties: `systemctl --user revert research.slice`.
- Remove the deployment: `rm -r ~/ops/research-runner ~/.local/state/research-runner`.

No persistent unit files, root, system-slice or host settings are used.
