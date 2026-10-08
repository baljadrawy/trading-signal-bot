# G5 + G6 readiness assessment (2026-10-08)

Status: read-only assessment and design. **No production setting was changed.** Nothing in this document is
implemented; every change listed under "Implementation sequence" needs its own owner authorisation.

Scope: G5 (research parallelism 4 → 6 / 8 workers) and G6 (memory, OOM and swap governance across the shared host).
Inputs: existing sealed evidence (G2 perf, host capacity review, host governance review, G3 Stage G) plus one bounded
read-only snapshot taken 2026-10-08 ~10:01Z (`/proc`, cgroup files, `docker stats --no-stream`, one 5-s `/proc/stat`
delta). No benchmark, load test or background process was run.

Provenance labels: **M** = measured now, **E** = from sealed earlier evidence, **I** = inference.

---

## 1. Current state (relevant facts)

| Item | Value | Src |
|---|---|---|
| Host | 12 vCPU ARM Neoverse-N1 (KVM, shared vCPU), 23.4 GiB RAM, **4 GiB swap** (`/swapfile`, 524 KiB used, swappiness 10) | M |
| Swap origin | created 2026-10-07T20:29:56Z by `sudo bash /home/tradmin/swap-4g.sh`, i.e. **after** both governance reviews; their "no swap" baseline is superseded | E (G3 readiness) |
| Host CPU now | busy 0.42 vCPU, steal 0.18 vCPU, steal/(busy+steal) 0.29 | M (5-s) |
| Steal tax | demand-proportional, 0.25–0.29 of guest demand over 9.4 days; observed only up to ~3 busy vCPU | E |
| Collector | `ce4e6b6656a5`, 1.5 CPU / 768 MiB / swap 0 / pids 64; ~0.18–0.30 cores; mem 170–196 MiB; throttled 0.0003 after G3 | M + E |
| Memory PSI | some/full avg10/60/300 = 0 | M |
| CPU PSI | some avg60 0.15 % | M |
| `oom_kill` since boot | 14 — **all** from G2's deliberate `TOOM` cgroup-OOM validation units (2026-10-06 23:48–23:58Z, inside research.slice). No production OOM. | M (journal) |
| `pswpout` / `pswpin` | 20 / 0 | M |
| Container cpu.weight | 100 everywhere (no priorities) | M |
| Container oom_score_adj | 0 everywhere | M |
| Monitor | `tsbops.slice` weight 1000, slice memory.max 512 MiB, **swap.max unlimited**, oom_score_adj 100 | M |
| memory.low / memory.min | 0 on system.slice and user.slice → container/unit floors are not effective | M |
| user@1000 delegated controllers | cpu memory pids (no io) | M |
| systemd-oomd / earlyoom | inactive / absent | M |
| overcommit / dirty_ratio | 0 (heuristic) / 10 % (~2.3 GiB dirty possible) | M |

Per-container memory and swap envelopes (M):

| Container | memory.max | memory.swap.max | Note |
|---|---|---|---|
| tsb-p2-forward-collector | 768 MiB | **0** | latency-critical; correct |
| trading_scanner / signal_engine / postgres / jadrawy-web | 512 MiB | 512 MiB | Docker default memswap = 2×mem → may swap up to its own size |
| trading_analyzer | 1 GiB | 1 GiB | same |
| trading_telegram / tracker | 256 MiB | 256 MiB | same |
| hermes | 4 GiB | **4 GiB** | can consume the entire host swapfile |
| wishlist-app / xsch-app / xsch-caddy | **max** | **max** | no memory or swap limit at all |

G2 research profiles (deployed `~/ops/research-runner/research_exec/config.py`): R1 4 workers / 400 %, R2 6 / 600 %,
R3 8 / 800 %, LIGHT 2 / 200 %. R1–R3 all MemoryHigh 8 GiB / MemoryMax 10 GiB; CPUWeight=idle; OOMScoreAdjust +500;
OOMPolicy=kill (memory.oom.group); KillMode=control-group; RuntimeMaxSec. **No `MemorySwapMax` is set** (M, code).

---

## 2. G5 — research parallelism readiness

### 2.1 Existing evidence (not repeated)
- G2 synthetic CPU benchmark (pure Python, 16 units × 30 M Monte-Carlo): 1 worker 120.1 s; 4 workers 30.8 s →
  **3.90× (97 % efficiency)**, byte-identical merged result, collector unaffected (loop-lag max 823 ms vs 897 ms
  baseline, throttling briefly lower). Steal at admission 0.11–0.21 vCPU. **Steal under research load was not sampled.**
- Capacity review: ~10–11 vCPU nominally free, ~7.5–8 effective after steal (I, assumes constant tax).
- All measured P2 research jobs are single-threaded; throughput comes only from deterministic multiprocessing.
- Collector after G3: ~0.3 of 1.5 cores, 0 % of minutes throttled >10 %. Its quota is no longer the limiting factor.

### 2.2 Current bottlenecks
1. **Unmeasured steal above ~3 busy vCPU.** Steal is demand-proportional at low load; whether the provider's tax
   rises superlinearly at 6–8 busy vCPU is unknown. This is the single question that decides R2/R3 usefulness.
2. **Memory per worker, not CPU, limits heavy jobs.** D1-type builds peak at 1.3–2 GB per worker. R2/R3 keep the R1
   memory ceiling (8 GiB high / 10 GiB max): 6 × 2 GB = 12 GB and 8 × 2 GB = 16 GB exceed it. R2/R3 are valid
   only for light-memory workloads (e.g. P2-F calibration reps at ~55 MB/worker) unless the profile memory is
   raised. Worker count must be `min(cpu-stage, floor(MemoryHigh / measured per-worker peak))`.
3. **No IO isolation for research** (no io controller in user@1000; scheduler `none`). CPU-bound reps are fine; IO-heavy
   jobs remain a contention risk for the collector writer.
4. **Hermes** bursts to ~3.1 cores at equal weight; an 8-worker stage overlapping a hermes burst would push the host
   toward ~11 busy vCPU. R3 therefore stays "attended only".

### 2.3 Candidate worker counts
- **4 (R1)**: proven; remains the unattended default.
- **6 (R2)**: likely useful for CPU-bound, light-memory jobs (projected ~5.6–5.8× if steal stays proportional) — needs
  the measurement below.
- **8 (R3)**: plausible but highest steal/hermes-overlap risk; attended only; promote only if R2 passes cleanly.
- Never > 8 (keep ≥ 4 vCPU for collector, Paper, postgres, hermes, agents, kernel).

### 2.4 Minimum safe benchmark (designed, NOT run)
Goal: distinguish useful parallelism from contention with the smallest run that yields enough collector samples.
- Workload: the existing G2 `synthetic_cpu.py` (deterministic, ~7.5 s CPU per 30 M-iteration unit, ~16 MB/worker),
  so results compare directly with the G2 1/4-worker baseline and the merged hash can be checked for byte-identity.
- Stages, sequential, each ≈ 5 min wall so the 60-s monitor and 30-s watchdog produce ≥ 5 / ≥ 10 samples:
  - baseline: 5 min no research (or reuse the G3 post-resize hour if within 24 h and no rotation in between);
  - R1: 4 workers × 160 units; R2: 6 workers × 240 units; R3 (attended, hermes idle): 8 workers × 320 units.
  - Units are multiples of 4·6·8 → no tail imbalance. Total ≈ 20–25 min wall, ≈ 1.5 CPU-hours.
- Each stage launched through the G2 runner (admission + freeze watchdog), one at a time (heavy lock).
- Measure per stage: wall time → speedup vs serial (120.1 s / 16 units = 7.51 s/unit); efficiency; host
  steal/(busy+steal) at 5-s resolution (watchdog telemetry); CPU PSI; collector loop_lag, sampler lateness,
  durable_lag, beat_age, throttling, health; hermes CPU.
- **Promote** a stage only if: efficiency ≥ 0.85 × workers; steal ratio 60-s p95 ≤ 0.40; collector loop_lag p99 ≤
  1.6 s, durable_lag p99 ≤ 2.6 s, sampler lateness p99 ≤ 1.5 s, 0 DEGRADED; CPU PSI some avg60 ≤ 10 %; merged hash
  byte-identical to the 1/4-worker result.
- **Stop** (watchdog freezes, operator aborts): collector durable_lag > 5 s, beat_age > 3 s or loop_lag > 5 s; host
  steal > 2 vCPU over 5 s; memory PSI some > 1 %; any collector incident; entering a protected window.
- Window: outside :12–:25, 23:30Z → end of seal/backup, 01:10–01:45Z, ±30 min of collector rotations
  (proactive ≈ 07:27Z, universe ≈ 00:10Z).

### 2.5 G5 verdict
**READY (PASS) for an owner-authorised minimal ramp**, with two preconditions: (a) add `MemorySwapMax=0` to research
units first (§3, step 1), so the ramp is measured under the intended memory policy; (b) treat R2/R3 as
light-memory profiles until per-worker memory is profiled. G5 does not depend on the G3 24-hour comparison; it should
avoid overlapping the first post-resize rotation window.

---

## 3. G6 — memory, OOM and swap governance readiness

### 3.1 Prioritised risks
1. **(High impact) Research can swap.** With swap now present and no `MemorySwapMax`, a research job reaching
   MemoryHigh is reclaimed by swapping its anon pages. That converts memory pressure into disk IO with no IO
   isolation, contending with the collector writer and postgres. Research should instead be throttled/killed within
   its own cgroup.
2. **Unbounded containers** (wishlist-app, xsch-app, xsch-caddy: memory.max and swap.max = max) and the unbounded
   `cron.service` (9.5 GiB historical peak, anon vs cache unknown) are the only paths to a *global* OOM.
3. **Global OOM victim order is size-based** (all adj 0). The intended order (research → agents → hermes → web → Paper
   → postgres → collector) is not encoded except research (+500) and monitor (+100).
4. **Latency-sensitive services may swap**: postgres (512 MiB swap allowance), Paper containers (Docker default
   memswap = 2×mem). Swapped DB or tracker pages under host pressure would add latency.
5. **Hermes may consume the whole 4 GiB swapfile**, leaving no swap headroom for anything else.
6. **Floors are not real**: memory.low is 0 on system.slice/user.slice, so container reservations would not protect.
7. **Dirty-page backlog** up to ~2.3 GiB can lengthen fsync for the collector and postgres.
8. Minor: monitor slice swap unlimited (13–15 MiB footprint; negligible but inconsistent).

### 3.2 Recommended protection policy
- **Swap is an emergency buffer for yieldable, non-latency-critical workloads only.** Latency-critical tiers never swap.
- P1 collector: keep `memswap = mem` (swap 0) ✔; at its next planned gated recreate add oom_score_adj −500 and verify
  cpu.weight 500 (runc mapping must be checked in the file).
- P1 monitor: unit `MemorySwapMax=0`; keep OOMScoreAdjust 100 (unprivileged floor).
- P2 postgres: `memswap = mem` (no swap), mem 1 GiB, oom −300 — at the next planned DB maintenance only.
- P3 Paper: `memswap = mem` — bundled into the next owner-approved Paper release (Paper is halted; no dedicated restart).
- P4 web (wishlist, xsch-app, xsch-caddy): add memory + swap limits — owner/project governance of those projects.
- P5 hermes: oom +300 and a swap cap (e.g. memswap = mem + 1 GiB) — hermes owner decision.
- P7 agent sessions: user-level MemoryHigh ≈ 3 GiB (later).
- P8 research: **MemorySwapMax=0** on job units (and on research.slice runtime properties); keep +500, oom.group,
  MemoryHigh/Max; size workers by measured per-worker peak.
- Host (root, owner): system.slice MemoryLow ≈ 2 GiB (makes floors real); `vm.dirty_bytes` ≈ 512 MiB; keep
  swappiness 10; do **not** add systemd-oomd/earlyoom without measurement (kernel OOM + cgroup limits + oom.group
  already give deterministic behaviour once the adj order is set).

### 3.3 G6 verdict
**READY (PASS) as a policy and sequence.** No measurement gap blocks the design; remaining uncertainty is limited to
(i) whether cron.service's 9.5 GiB peak was anon (capture backup peak RSS at the next run), and (ii) the runc
cpu-shares→cpu.weight mapping (verify the cgroup file after any change).

---

## 4. Combined implementation sequence

| # | Change | Class | Restart | Depends on | Owner approval |
|---|---|---|---|---|---|
| 1 | Research runner: `MemorySwapMax=0` for job units + slice; per-profile memory gate on worker count | A (research tooling) | none | — (independent) | yes |
| 2 | G5 minimal ramp R1→R2→(R3 attended) per §2.4 | research window | none | step 1; not within ±30 min of a rotation | yes |
| 3 | Monitor unit `MemorySwapMax=0` | user unit | monitor restart (seconds) | bundle with next monitor change | yes |
| 4 | Collector oom_score_adj −500 + verify cpu.weight 500 | B (gated recreate) | ~1 min gap | G3 first post-resize rotation PASS + 24-h comparison | yes |
| 5 | Postgres memswap=mem, 1 GiB, oom −300 | B | ~90 s, 3 projects | next DB maintenance | yes (all DB tenants) |
| 6 | Paper memswap=mem (+ CPU caps) | B | per service | next Paper release (Paper halted) | yes |
| 7 | Web containers limits; hermes swap cap + oom +300 | other projects | per service | each project's governance | yes (project owners) |
| 8 | Host root steps: system.slice MemoryLow, dirty_bytes, io delegation | root | user-manager restart for io delegation | step 3 first | yes |

Independent now: 1 (then 2). Dependent on G3 follow-up: 4. Needs other projects' owners: 5 (shared DB), 7.

## 5. Recommended next authorised action
Authorise **step 1** (research runner `MemorySwapMax=0` + memory-aware worker gate, Class A, no production restart),
then **step 2**, the ~25-minute G5 minimal ramp in a protected-window-free slot.

---

## 6. G6 step 1 — research swap isolation: DONE (2026-10-08, owner-authorised)
- **Change:** `MemorySwapMax=0` on research job units (`rj-*.service`), research watchdog units
  (`rw-*.service`), and the runtime properties the runner applies to `research.slice`.
  - Code: `ops/research/research_exec/launcher.py` on `feature/g6s1-research-swap-isolation-20261008` @ `0f12d3a`
    (from `e5a4fcc`), plus regression test `tests/test_launcher_swap.py`.
- **Unchanged:** MemoryHigh, MemoryMax, TasksMax, OOMScoreAdjust +500, OOMPolicy=kill, CPU envelopes, admission.
- **Deployed:** only `~/ops/research-runner/research_exec/launcher.py`.
  - sha256 `b6cfb2ef…` → `9a5ff011…`, which equals the repo blob.
  - Backup: `research-runner-backup-pre-g6s1-20261008T110319Z`.
- **Preflight:**
  - 0 research or watchdog units loaded; heavy lock free;
  - deployed tree byte-identical to `e5a4fcc` before the change;
  - the change affects research units only, and no running service reads the file.
- **Verification:**
  - Tests: 22/22 (3 new swap tests plus the logic suite). The new tests fail on `e5a4fcc`.
  - Rendered argv for LIGHT, R1, R2 and R3, the watchdog and the slice all contain `MemorySwapMax=0`, with other
    properties unchanged.
  - A 1-s probe unit in `research.slice` read `memory.swap.max=0`. The probe was not a research job, and the
    empty slice was stopped afterwards.
  - Dry `research-run admit --profile R1`: admit=true, reasons [].
- **Production unchanged:**
  - The same 12 container IDs, all up.
  - Collector `ce4e6b6656a5` with 0 restarts, healthy.
  - Monitor MainPID 3551927, NRestarts 0.
  - B3 `2026-10-08|f|manual_resume|30463`.
- **Rollback:** restore `launcher.py` from the backup (`install` the saved file). It takes effect at the next research
  launch. No service restart is needed.
- **Remaining G6 steps:** not started. Steps 2–8 still need separate authorisation; G5 benchmarks were not run.

---

## 7. G5 final benchmark preflight (2026-10-08 ~11:17Z): READY, start gated by prerequisites
Read-only; no research job was launched and no limit was changed.

**Verified:**
- **Deployed runner:** byte-identical to `feature/g6s1-research-swap-isolation-20261008` @ `0f12d3a` (launcher
  sha `9a5ff011…`; the remote SHA matches).
  - G6 step 1 is in force: `MemorySwapMax=0` on job, watchdog and slice.
- **Host snapshot (5 s):**
  - CPU: busy 0.90 vCPU, steal 0.23 vCPU (ratio 0.21); load 0.78.
  - Memory: MemAvailable 20.15 GiB; swap used 0.5 MiB.
  - Pressure: CPU some avg60 0.09 %, memory 0.
  - Collector ≈ 0.44 cores of 1.5; hermes idle.
  - Capacity is unchanged from §1. 4→6→8 workers stays appropriate and keeps ≥ 4 vCPU free.
- **Memory fit:** G2 measured a 62.8 MiB peak at 4 workers (≈ 16 MiB/worker). That projects to ≈ 0.13 GiB at 8
  workers, far below MemoryHigh 8 GiB / MemoryMax 10 GiB. Admission needs MemAvailable ≥ MemoryMax + 6 GiB = 16 GiB;
  20.15 GiB is available.

**Confirmed parameters** (refined from §2.4: one identical plan for all stages, so speedup is measured on equal work
and determinism is checked across worker counts):

| Stage | Profile / opt-in | Workers | Plan | Expected wall |
|---|---|---|---|---|
| baseline | — | 0 | 5 min no research (60-s monitor and 5-s steal) | 5 min |
| S1 | R1 (default) | 4 | `synthetic_cpu.py --units 240 --iters 30000000` (= 1,800 CPU-s; G2: 7.51 s/unit) | ≈ 7.5 min |
| S2 | R2 `--allow-elevated` | 6 | same plan | ≈ 5.0 min |
| S3 | R3 `--attended` (operator present, hermes idle) | 8 | same plan | ≈ 3.75 min |

- Total ≈ 21 min, run sequentially (heavy lock).
- Each stage uses its own job and checkpoint directory. Reusing a directory would resume completed units and
  falsify the timings.
- Command per stage:
  `research-run run --job-id g5-s<N> --owner g5 --profile <P> [--allow-elevated|--attended] --max-runtime-s 1200 --wait -- python3 <runner>/examples/synthetic_cpu.py --units 240 --iters 30000000 --checkpoint <jobdir>/ckpt --out <jobdir>/merged.json`.

**Safety gates** (all from the deployed config; none changed):
- **Admission:**
  - Collector HEALTHY, health ≤ 30 s, durable lag ≤ 5 s, beat ≤ 3 s;
  - monitor fresh (≤ 180 s), INFO/WARNING only, written by the supervised `tsb-p2f-monitor.service`;
  - outside the protected windows (hh:12–25, 23:50–00:45, 01:10–01:45);
  - heavy lock free;
  - steal ratio ≤ 0.40 and steal ≤ 1.0 vCPU (5 s);
  - PSI CPU some avg60 ≤ 10 %, memory ≤ 0.10;
  - MemAvailable ≥ MemoryMax + 6 GiB; disk ≥ 150 GB free.
- **Freeze (watchdog, 2 s tick):**
  - Collector health age > 30 s, durable lag > 5 s, beat > 3 s or loop lag > 5 s;
  - monitor not INFO/WARNING or stale > 180 s;
  - steal > 2.0 vCPU over 5 s; memory PSI some avg10 > 1 %;
  - entering a protected window; the operator pause file.

  Thaw after 120 s clean.
- **Kill (whole group):** frozen > 4,200 s; MemAvailable < 3 GiB; memory PSI full avg10 > 10 %. Plus systemd OOM
  group kill and RuntimeMaxSec.
- **Promote a stage only if all hold:**
  - efficiency ≥ 0.85 × workers versus 7.51 s/unit;
  - steal ratio 60-s p95 ≤ 0.40;
  - Collector loop-lag p99 ≤ 1.6 s, durable lag p99 ≤ 2.6 s, sampler lateness p99 ≤ 1.5 s, 0 DEGRADED;
  - CPU PSI some avg60 ≤ 10 %;
  - merged result hash identical across S1–S3;
  - 0 new Collector incidents.
- **Operator abort:** do not continue to the next stage on any failed criterion. Stop a running stage with the pause
  file or `systemctl --user stop rj-g5-s<N>.service`.

**Rollback:** no configuration changes, so nothing to roll back. After the run, verify:
- no `rj-`/`rw-` units remain;
- `research.slice` is inactive;
- the heavy lock is free;
- the Collector, monitor, Paper and container identities are unchanged.

Job directories stay as evidence.

**Remaining prerequisites (start gate):**
1. **PAPER-R2 T0 + 1 h checkpoint** (due 2026-10-08T11:54Z) completed, so Paper's first post-resume admissions are
   observed before any research load.
2. **G3:** the first post-resize rotation (≈ 00:10Z 2026-10-09) passes. The 24-h comparison window
   (2026-10-08T08:29Z → 2026-10-09T08:29Z) is collected **before** the benchmark, because research load inside that
   window would confound the post-G3 steal/latency comparison.
3. **Window:** proposed 2026-10-09 08:45–09:10Z. That is after the 24-h comparison, clear of the hh:12–25 window,
   and clear of the ±30 min around the proactive rotation (≈ 07:27Z). Recompute from health before starting.
4. **Owner authorisation** for R2 `--allow-elevated` and R3 `--attended` (operator present, hermes idle).

---

## 8. G6 Steps 2–8 — prioritised implementation plan (2026-10-08; documentation only, nothing applied)
Priority = (risk reduced) ÷ (blast radius). Every step needs its own owner authorisation, one service at a time, with
before/after identity capture and a GitHub checkpoint. Production limits and host settings are unchanged today.

| Prio | Step | Change | Mechanism / class | Precondition | Verify | Rollback |
|---|---|---|---|---|---|---|
| 1 | **7a** | limits for the **unbounded** web containers (wishlist-app, xsch-app, xsch-caddy): memory 768M/768M/256M, memswap = mem, pids 256 | each project's own compose + its governance; Class B per service; Caddy via its reload rule | project owner approval; low-traffic window | `memory.max`, `memory.swap.max` = 0, health ×2 | previous compose blob |
| 2 | **3** | monitor unit `MemorySwapMax=0` | user unit drop-in; restart of `tsb-p2f-monitor` (≈ 2 s gap) | Collector HEALTHY; outside protected windows | unit cgroup `memory.swap.max` = 0; fresh status; G2 admit | remove the drop-in, restart |
| 3 | **4** | Collector `oom_score_adj −500` (+ verify `cpu.weight` 500) | Collector compose; gated stop/up; G4 rebind | G3 24-h comparison done; no rotation within ±30 min | `/proc/<pid>/oom_score_adj`, cgroup `cpu.weight` file (runc mapping) | `compose.pre-*` backup |
| 4 | **5** | postgres memswap = mem, mem 1G, oom −300 | shared-postgres compose; Class B | **all 3 DB tenants' owners**; next planned DB maintenance (≈ 90 s) | `memory.max`, swap 0, checkpoint latency | previous compose |
| 5 | **6** | Paper containers memswap = mem (+ CPU caps telegram/tracker) | trading-signal-bot compose PR + gated per-service recreate | next owner-approved Paper release; Paper not mid-checkpoint | per-container swap 0; B3 unchanged; heartbeats | image/compose rollback per `IMAGES.md` |
| 6 | **7b** | hermes swap cap (memswap = mem + 1G) + oom +300 | hermes project's compose | hermes owner decision | swap.max = 1G; oom_score_adj | previous compose |
| 7 | **8** | host: `system.slice MemoryLow≈2G`, `vm.dirty_bytes≈512M`, user@ io delegation | root; user-manager restart for io delegation | step 2 done (monitor survives the restart); owner root window | sysctl/slice values; PSI; monitor uptime | revert drop-ins/sysctl |

- **Ordering:**
  - Step 1 closes the only global-OOM paths with the lowest blast radius.
  - Steps 2–3 protect the forward-evidence path.
  - Steps 4–6 need other owners or a planned release.
  - Step 7 is root-level and last.
- **Read-only facts (from §1 / §3):** 4 GiB swap; 0 production OOM; all container `oom_score_adj` 0; three containers
  unbounded; research already swap-isolated (G6 step 1).
