# G6 — host resource allocation assessment (read-only, 2026-10-08)

**Scope:** the shared host 89.58.35.49: 12 vCPU (shared ARM), 23.41 GiB RAM, 4 GiB swap, kernel 6.8, cgroup v2.

**How this was done.** Read-only, between 16:59Z and 17:10Z on 2026-10-08. Nothing was changed: Docker, systemd,
cgroups, sysctl, databases, services and trading configuration are all as they were. The work extends §3 and §8 of
`G5_G6_READINESS.md` and does not repeat them.

**Sources and evidence class.** Every number is labelled with its class, because only the first two are measured.

| Class | Meaning | Source |
|---|---|---|
| **S** sustained | a long-run average | cgroup `cpu.stat usage_usec` ÷ container uptime (0.36–11.3 days) |
| **P** observed peak | the highest value seen, with its window | cgroup `memory.peak` since container start (**includes page cache**); Collector per-minute monitor telemetry (`samples.jsonl`, 4.3 days, 5 821 samples) |
| **W** window sample | a short sample, **not a peak** | G3 Stage G host sampler, 60 s (07:47–08:26Z and 08:31–09:32Z, about 100 min), plus one 10 s spot sample at about 17:00Z |
| **U** unknown | no telemetry exists, so no value is claimed | — |

There is **no multi-day host-wide steal or PSI history** (sysstat is not installed). Host steal and PSI numbers are
therefore class W only.

## 1. Inventory and limits

Docker values come from `HostConfig` and the live cgroup. Every container has `oom_score_adj` 0, `OomKillDisable`
unset, `RestartCount` 0, and `memory.events` oom / oom_kill 0.

| Service (owner) | CPU limit | cpu.weight | memory.max | swap allowed | pids | restart |
|---|---|---|---|---|---|---|
| tsb-p2-forward-collector (P2 research) | 1.5 | 100 | 768 MiB | **0** | 64 | `no` (gated scripts) |
| trading_analyzer (Paper) | 1.5 | 100 | 1 GiB | 1 GiB | — | unless-stopped |
| trading_scanner (Paper) | 1.0 | 100 | 512 MiB | 512 MiB | — | unless-stopped |
| trading_signal_engine (Paper) | 1.0 | 100 | 512 MiB | 512 MiB | — | unless-stopped |
| trading_telegram (Paper) | **none** | 100 | 256 MiB | 256 MiB | — | unless-stopped |
| trading_tracker (Paper) | **none** | 100 | 256 MiB | 256 MiB | — | unless-stopped |
| postgres (shared, 3 tenants) | **none** | 100 | 512 MiB | 512 MiB | — | unless-stopped |
| hermes (separate project) | 4.0 | 100 | 4 GiB | **4 GiB (= all host swap)** | 512 | unless-stopped |
| jadrawy-web (web) | none | 100 | 512 MiB | 512 MiB | 256 | unless-stopped |
| wishlist-app (web) | none | 100 | **unbounded** | **unbounded** | — | unless-stopped |
| xsch-app (web) | none | 100 | **unbounded** | **unbounded** | — | unless-stopped |
| xsch-caddy (web) | none | 100 | **unbounded** | **unbounded** | — | unless-stopped |
| tsb-p2f-monitor (user unit, tsbops.slice) | none | 1000 | 256 MiB (slice 512 MiB) | **unbounded** | — | on-failure; OOMScoreAdjust 100 |
| research.slice (G2 runner; on demand) | 8.0 (slice); R1 4 / R2 6 / R3 8 | idle | 12 GiB slice; jobs High 8 G / Max 10 G | **0** (G6 step 1) | 1024 | n/a; job oom_score_adj +500 |
| agent sessions (Claude Code, tmux scopes in user@1000) | none | 100 | **unbounded** | unbounded | — | n/a |

**Host settings:**

- `vm.swappiness` 10, `overcommit_memory` 0, `dirty_ratio` 10, `min_free_kbytes` 45 056;
- `system.slice` MemoryLow 0;
- swap used 0.5 MiB of 4 GiB; `pswpin` 0, `pswpout` 20 since boot;
- disk 514 GB free.

**Swap allowance is oversubscribed.** The containers may use 7.5 GiB of swap between them, against 4 GiB on the host.
Hermes alone may use all of it.

## 2. Measured usage

### 2.1 CPU

| Workload | Sustained (S) | Peak / window | Throttling since start |
|---|---|---|---|
| Collector, post-resize (8.5 h) | 0.370 cores | P: per-minute p50 0.357, p95 0.498, p99 0.527, max 0.552 (35 % of quota at p99) | p99 1.3 %, max 5.9 % (per minute) |
| Collector, pre-resize (0.5 cap, 3.7 d) | — | P: p99 0.413, max 0.499 (at the cap) | p50 5 %, p95 18 %, max 98 %: this is why G3 resized it |
| analyzer | 0.026 | U | 0.2 % of periods |
| scanner | 0.016 | U | 2.3 % of periods (bursty) |
| signal_engine | 0.021 | U | 1.0 % of periods |
| telegram / tracker | 0.018 / 0.021 | U (no cap, so no throttle data) | — |
| postgres | 0.019 | U | no cap |
| hermes | 0.022 | U | 0.03 % of periods |
| web (4) | ≤ 0.005 each | U | no cap |
| **Host, all** | about 0.4–0.74 vCPU busy | W: busy p95 0.63–0.67, max 1.09 vCPU | — |
| **Host steal** | — | W: p50 0.16–0.18, p95 0.20–0.22, max 0.25 vCPU; spot 0.24 vCPU = 24 % of non-idle | — |
| **Host CPU PSI some** | — | W: p95 0.8–4.6 %, max 12.5 % (pre-resize window) | — |

**Reading:**

- The host is lightly used, about 6 % busy.
- Steal is a large *share* of the small busy time, but small in absolute terms (≤ 0.25 vCPU).
- Long-run steal peaks are **U**: G5 admission samples steal at launch for this reason. The G5 benchmark is what
  will measure steal under 4–8 vCPU of load.

### 2.2 Memory

**P** is `memory.peak` since container start; it includes page cache. The anon figure is the current value.

| Workload | Current | Anon now | Peak (P) | Peak as % of limit |
|---|---|---|---|---|
| Collector, post-resize | 315 MiB | 199 MiB | 323 MiB cgroup. Telemetry: anon p99 198, max 201; current max 316 | 42 % |
| analyzer | 143 | 105 | 165 | 16 % |
| scanner | 156 | 152 | 264 | 52 % |
| signal_engine | 81 | 64 | 104 | 20 % |
| telegram | 63 | 48 | 82 | 32 % |
| tracker | 57 | 53 | 91 | 36 % |
| postgres | 205 | 35 | 223 | 44 % (internal settings not read, see §5) |
| hermes | 1 849 | 437 | 2 530 | 62 % |
| jadrawy-web | 111 | 51 | 129 | 25 % |
| wishlist-app / xsch-app / xsch-caddy | 68 / 84 / 54 | 56 / 72 / 16 | 80 / 117 / 89 | unbounded |
| monitor unit | 13 | — | 18.8 MiB (MemoryPeak) | 7 % |
| agent sessions | about 6.9 GiB cgroup, mostly cache | about 1.4 GiB | 18.3 GiB scope peak, cache plus pre-G2 research; **anon peak U** | unbounded |
| cron.service | 1.2 GiB | 0 (all page cache from backups) | 11.2 GiB, cache | — |

Host MemAvailable is 20.1 GiB now. The research admission gate needs MemoryMax + 6 GiB = 16 GiB.

### 2.3 Worst case if every limit is hit at once

| Item | GiB |
|---|---|
| bounded containers, sum of memory.max | 8.25 |
| research R-profile MemoryMax | 10.0 |
| monitor | 0.25 |
| unbounded web, at observed peaks (U above that) | 0.28 |
| agent sessions, anon now (peak U) | 1.4 |
| docker / containerd / journald / other system anon | ≈ 0.5 |
| **total** | **≈ 20.7 of 23.41** |

That leaves a margin of about 2.7 GiB with no page cache. The two unbounded classes, the web containers and the
agent sessions, are the only paths to a global OOM that limits do not already cover. This confirms G6 §3.

## 3. Proposed allocation

The proposal uses explicit margins. New limits are set at least 2.5× above the observed peak. Existing limits are
never tightened, and where the requirement is **U** no limit is tightened.

| Priority | Service | Proposal | Margin basis | Rollback condition |
|---|---|---|---|---|
| **P0** forward evidence | Collector | keep 1.5 CPU, 768 MiB, swap 0, pids 64. Add `cpu.weight` 500 (runc shares mapping, verified in the cgroup file) and `oom_score_adj` −500 | CPU p99 0.53 = 2.8× headroom; anon max 201 MiB = 3.8× | any DEGRADED; loop-lag p99 > 1.6 s; throttled > 5 % (per minute); monitor limit mismatch → restore the `compose.pre-*` backup |
| **P0** | monitor | add `MemorySwapMax=0` (G6 step 3); keep 256 MiB and weight 1000 | peak 18.8 MiB = 13× | status stale > 180 s or G2 admission refuses on the monitor → remove the drop-in |
| **P1** | Paper (5) | `memswap = mem` (swap 0); keep the memory limits; telegram/tracker CPU cap **only after** CPU peaks are measured | memory peaks 16–52 % of the limits (≥ 1.9×) | B3 changes; heartbeat missed; any oom_kill → per-service image/compose rollback |
| **P1** | postgres | `memswap = mem`, `oom_score_adj` −300; keep 512 MiB unless `shared_buffers`/`work_mem` justify more (U) | cgroup peak 223 MiB = 2.3× | connection errors, checkpoint latency up, any oom → previous compose |
| **P2** | hermes | `memswap = mem + 1 GiB`, `oom_score_adj` +300; keep 4 CPU and 4 GiB | peak 2.53 GiB incl. cache = 1.6× | swap at its cap, or oom_kill → previous compose |
| **P2** | web (4) | wishlist 768 MiB, xsch-app 768 MiB, caddy 256 MiB, jadrawy keep 512 MiB; all `memswap = mem`, pids 256 | 6.6–9.6× observed peaks | health check fails ×2 or any oom_kill → previous compose (Caddy only via its reload rule) |
| **P3** | research | unchanged: R1 default; R2 / R3 only after G5; slice 8 CPU / 12 GiB / idle / swap 0 | admission gate MemAvailable ≥ Max + 6 GiB | watchdog freeze / kill rules (G2) |
| **P3** | agent sessions | **measure first**: a per-session anon peak is U. Later option: a user-level MemoryHigh ≈ 4 GiB, no hard Max (a hard Max would kill sessions) | — | any session reclaim stall → remove |
| host | root | `system.slice` MemoryLow ≈ 2 GiB; `vm.dirty_bytes` ≈ 512 MiB (G6 step 8) | protects containers from user-slice pressure | revert drop-in / sysctl |

**Service priorities under contention:**

1. Collector and monitor;
2. PostgreSQL and the Paper pipeline;
3. Hermes and the web workloads;
4. research and agent sessions (idle weight / reclaimable first).

**OOM order** (most protected first): Collector −500, postgres −300, Paper 0, web 0, monitor +100, hermes +300,
research +500.

**Ownership boundaries.** Each project's limits live in **its own** compose or unit file and governance:

- the trading-signal-bot Paper compose;
- the Collector ops directory;
- shared-postgres;
- hermes;
- twitter-scheduler / xsch;
- wishlist;
- jadrawy.

No change crosses a boundary in one action, and there is one service per change window.

## 4. Classification of changes

| Change | Independently safe (no G3/G5 dependency) | Needs G3 / G5 evidence | Needs separate service-owner approval |
|---|---|---|---|
| monitor `MemorySwapMax=0` | **yes**: about 2 s monitor gap, outside protected windows; still needs owner authorization | — | — |
| web limits (wishlist / xsch / caddy / jadrawy memswap) | **yes**: no evidence dependency, lowest blast radius | — | **yes**: each web project's owner and governance |
| Collector `cpu.weight` / `oom_score_adj` | — | **G3 24 h comparison** (≥ 2026-10-09T08:29Z) first; no rotation within ±30 min | P2 owner (Class B gated stop/up) |
| Collector CPU / memory size | — | **G3**: keep 1.5 unless the 24 h comparison shows otherwise | P2 owner |
| research R2 / R3 use, slice ceiling, CPU reservation for research | — | **G5** benchmark (efficiency, steal p95, Collector lag) | owner (R2 `--allow-elevated`, R3 `--attended`) |
| `system.slice` MemoryLow sizing, `dirty_bytes` | — | **G5**: research memory and IO behaviour under load | root window (owner) |
| Paper memswap = mem; telegram/tracker CPU caps | — | CPU peaks U: measure first | **Paper owner**, next approved release; **not before PAPER-R2 +72 h (2026-10-11T10:54Z)** |
| postgres memswap / oom / memory size | — | internal settings U | **all 3 DB tenant owners**, DB maintenance window |
| hermes swap cap / oom | — | — | **hermes owner** |
| agent-session MemoryHigh | — | per-session anon peak U | owner (affects interactive work) |

## 5. Unknowns and limits of this assessment

- **Host steal and PSI history.** About 100 minutes of 60 s samples plus one 10 s spot sample. No peak is claimed.
  Steal under heavy load is unmeasured until G5.
- **Container CPU peaks** (everything except the Collector). Only long-run averages and throttle counts exist; no
  per-minute series.
- **`memory.peak` includes page cache.** The true anon peaks of the Paper, postgres, hermes and agent cgroups are
  unknown, so the margins above are conservative for memory (cache is reclaimable).
- **PostgreSQL internal memory settings** (`shared_buffers`, `work_mem`, `max_connections`) were **not read**: a
  read-only `pg_settings` query was refused by this session's permission policy. The owner can run it, or authorize
  it.
- Collector post-resize telemetry covers 8.5 h and no universe rotation yet. The first one is at
  **2026-10-09T00:10Z**; G3 covers it.

## 6. Recommended next G6 step

1. **Monitor `MemorySwapMax=0`.** It is independent of G3/G5 and has the smallest blast radius among
   Collector-path changes. Owner authorization is needed; do it outside the protected windows, and not during the
   G3 comparison or G5.
2. **Web memory limits**, in parallel through their own project governance.
3. **Collector `cpu.weight` / `oom_score_adj`** after the G3 comparison passes.

Nothing in this document is applied.
