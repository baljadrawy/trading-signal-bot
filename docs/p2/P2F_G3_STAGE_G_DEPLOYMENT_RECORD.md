# P2F G3 Stage G: collector resize deployment record (2026-10-08)

**Verdict: PASS.** The P2 Forward Collector was resized from 0.5 CPU / 384 MiB to 1.5 CPU / 768 MiB, with swap still
disabled (`memory.swap.max 0`) and pids 64, through the gated stop and start. The image, the effective config, the dataset
and all other containers are unchanged. Nothing was merged. G5 and G6 were not started. Evidence:
`/home/tradmin/backups/tsb-aiohttp-20260929T122701Z/g3-stage-g-20261008T074327Z/`.

| Item | Before | After |
|---|---|---|
| container | `0488866e2e04`, boot `acae43bf` | `ce4e6b6656a5`, boot `2e12ddce` (previous_run `acae43bf`) |
| image | `tsb-p2-forward:p2f-150-cd2935e-20261007T1105Z`, `sha256:69187360…` | same |
| config_hash / config file | `7e95bb30…` / `continuous-v1.json` `ebe6be13…` | same (absolute path) |
| `compose.yml` | `700fe7df…` (cpus 0.5, mem 384m, memswap 384m) | `06f32bc5…` (exactly the 3-line `g3/compose-g3-resize.diff`) |
| cgroup `cpu.max` / `memory.max` / `memory.swap.max` / `pids.max` | `50000 100000` / `402653184` / `0` / `64` | `150000 100000` / `805306368` / `0` / `64` |
| HostConfig | NanoCpus 5e8, Memory = MemorySwap 402653184 | NanoCpus 1.5e9, Memory = MemorySwap 805306368, restart `no` |
| compose `config --hash collector` | `c4563bf0…` (= running label) | `e254a063…` |
| monitor binding | `b54bce49…` (0.5/384M/0/64) | `55f0cb5b…` (limits `150000 100000` / `805306368` / `0` / `64`, cgroup+docker_hostconfig) |
| monitor unit | pid 3363389 | pid 3551927, inv `28260c0e…`, code `de83e506…` (unchanged) |

## Steps

| Step | Record |
|---|---|
| Preflight | `p2f_g3_preflight.py check` (c11f906 copy, expect `4eec9f49…` unchanged: same cid). All 10 checks PASS at 08:26:08Z (`identity`, `health` HEALTHY with no exceptions, `incidents` only the established unacked WARNING `previous_run_stopped_failed`, `rotation` 2 hand-offs, 0 unresolved, 0 seq_reset, `day_lifecycle`, `monitor`, `run_chain`, `windows`, `rollback`, `host` 20.1 GiB). |
| Compose | `compose.pre-g3.yml` (0444, `700fe7df…`) and `compose.g3-staged.yml` (0444, `06f32bc5…` = readiness doc) |
| W1 | `watch --until pass`, 07:49–08:25:52Z, 0 stops, PASS |
| Stop | `p2f_continuous_stop.sh` invoked 08:26:22.147Z; stop_requested 08:26:22.505Z; marker `stop-acae43bf` STOPPED, exit 0, partials 0, oom false. Evidence preserved (control, incidents, health, quarantine, monitor files). |
| Swap | `install -m 0444 compose.g3-staged.yml compose.yml` at 08:26:50.7Z, sha `06f32bc5…` |
| Start | `p2f_continuous_up.sh` (same tag and id, absolute config) invoked 08:27:08.878Z; "previous run acae43bf: STOPPED cleanly"; `UP OK` 08:27:10Z |
| Inspect diff | Only these fields differ: id, Pid/StartedAt, NanoCpus/Memory/MemorySwap, the compose config-hash label, and the ORDER of Binds and of the two compose-set env vars (proved by hash reproduction). Unexpected diffs: 0. |
| Run chain | `verify_continuous.py --run-chain` PASS; `downtime-2e12ddce…` cause `clean_stop`, linked to `acae43bf`, 08:26:22.505 → 08:27:14.926Z (52.4 s) |
| Rebind | `bind --reason "G3 Stage G: resize to 1.5 CPU / 768 MiB …" --restart` at 08:28:33Z. Status `limits` equals the cgroup; expected_source binding; mismatch []; problems []. Own calculation agrees: mem 14.1 % = anon/805306368; cpu_pct_of_quota 17.9 % = 0.269/1.5. |
| G2 | `research-run admit --profile R1`: admit true, reasons [] (no job) |
| W2 | `watch --until never`, 60 min (08:31:27–09:30:58Z): 120 polls, all HEALTHY/WARNING, 0 stops, deadline exit 4 by design |

## Collection gap (from segments: old last record → new first record)

| Type | Old last | New first | Gap |
|---|---|---|---|
| book | 08:26:22.000Z | 08:27:17.000Z | 55 s |
| depth | 08:26:22.000Z | 08:27:18.000Z | 56 s |
| market (1-min) | 08:26:00Z | 08:28:00Z | 120 s (one missing minute, 08:27) |
| health / lifecycle | 08:26:22.83Z | 08:27:14.96Z | 52.1 s |

`candle`, `clock` and `universe` are periodic types. Their spacing is shown in the evidence; there is no hidden loss.

## 60-minute validation (the hour before the stop vs the first hour after the rebind)

| Metric (monitor 60 s samples) | Before (0.5 CPU) | After (1.5 CPU) |
|---|---|---|
| throttled fraction, mean | 0.1032 | 0.0003 |
| minutes throttled > 10 % | 47.5 % | 0 % |
| CPU cores used, mean | 0.314 | 0.298 |
| mem % of limit, max | 67.9 % (of 384 MiB) | 19.7 % (of 768 MiB) |
| loop lag p95 / sampler lateness p95 | 1289 / 666 ms | 309 / 247 ms |
| beat_age max / durable_lag max | 1336 / 2506 ms | 220 / 2019 ms |
| non-HEALTHY samples / DEGRADED | 0 / 0 | 0 / 0 |

- Separated from steal (evidence samplers, `/proc/stat` per minute):
  - Before: 39 min, all in the 0.2–0.3 steal band, throttled 10.7 %, 33 `memory.events max`.
  - After: 61 min, mean steal 0.284. In the 0.2–0.3 band (40 min) throttled 0.04 %; in 0.3–0.4 (20 min) 0.0 %; 0 `max` events.
- cgroup counters:
  - Old container, whole run: `nr_throttled/nr_periods` 0.1017, `memory.events max` 421, oom 0.
  - New container, first 65 min: 0.0002, max 0, oom 0.
- Health instrumentation:
  - Old run: GC pauses ≥ 100 ms 80.8/h, loop lag ≥ 1 s 6.1/h.
  - New run so far: 40.4/h and 0/h. The new run is a first hour without a rotation, so these numbers are indicative only.

## Remaining

- The new boot has no rotation yet. The gate's `rotation` check FAILs with the updated expect file until the 00:10Z universe
  transition on 2026-10-09, or the proactive rotation at about 07:27Z on 2026-10-09.
- The 24 h comparison script is `p2_forward/ops/g3/g3_24h_compare.py`, read-only, single pass. Run it at about +24 h. No
  existing source records per-minute steal history, so steal banding covers only the evidence sampler windows.
- `expect-g3-collector-150.json` is updated to the new cid and limits, for owner review.
