# Stage A deployment record: Collector 1.6.1 (O2a), 2026-10-22

**Owner authorization:** Stage A, a single controlled deployment with the lifecycle-only O2a configuration
(2026-10-22). Evidence folder on the host: `~/ops/tsb-p2-forward/deploy-stagea-20261022T1740Z/` (mode 700).

## Identity

| | Before | After |
|---|---|---|
| Container | `65b152109ca3…`, started 2026-10-20T08:26Z, 0 restarts | **`4b860ea43f55b803d9ed8af833d64654e70c71cbf75ff3924aa243b2e65961b9`**, started **2026-10-22T17:45Z**, 0 restarts, restart policy `no` |
| Image | `sha256:324d52c9…` (1.6.0) | **`sha256:89232400d5285b7a35d0fcba14965861c2b49e7c614c9bba7daa121504d68e5d`** (`tsb-p2-forward:p2f-161-72c0bee-20261022T1558Z`) |
| Boot | `d1417a9c` | **`4be1ce76`** |
| Config | `continuous-v1.json` (`ebe6be13…`) | `continuous-v1-obs-lifecycle.json` (`0db3f89d…`); `ws_session_end_events=true`, `conn_flapping_enabled=false` |
| `config_hash` | `45296f7a443da177` | **`6546b4795fa135e4`** (as predicted) |
| Version / schema doc | 1.6.0 / `SCHEMA-v2-e7a641c3.md` | `p2cr-collector-1.6.1` / `SCHEMA-v2-c160a464.md` (hash-verified); run record `build.git_commit=72c0bee…` |
| Monitor binding | → `65b152109ca3` | → **`4b860ea43f55`**: `p2f_monitor_bind.py bind --restart`; validated mount, labels and cgroup limits; previous binding kept in `.history.jsonl` |

## Preflight (all passed, before any change)

- Running identity, health `HEALTHY` (`config_hash` `45296f7a…`), writer and certifier alive with 0 failures, 0 open gaps.
- Incidents: 0 CRITICAL, 0 DEGRADED; the 3 WARNINGs unchanged.
- Candidate image ID verified (arm64, 1.6.1). Running tag → `324d52c9…`.
- 1.6.0 archives verified (`sha256sum -c`). Original config and gated scripts byte-identical to the pre-Stage-A snapshot; the scripts equal `main`. Compose blob `12052900…` = `main` = `DEPLOYED.json`.
- Research: 0 units, both locks free, no runner process.
- Host: load 0.8 on 12 cores, 21 GB RAM available, 494 GB disk free, CPU/memory PSI about 0, Docker healthy with no warnings.
- Timing: next rotation about 5.5 h away; day close and universe refresh at about 00:10Z; the hourly seal cron (at :17) was not hit.
- Start-script gate run dry: no blocking CRITICAL.

**Findings handled during preflight (not new, not blocking):**
- **Swap limit.** `p2f_monitor_bind.py show` returned 3: the cgroup `memory.swap.max` read `max`, while Docker implies `0`.
  - The monitor has reported this WARNING since 2026-10-16. It correlates with early-morning unattended upgrades, likely through a `daemon-reload`.
  - A disposable fresh container under the same limits got `memory.swap.max=0`, so the rebind would validate. It did, and the new container shows `0`.
- **DEGRADED health blips.** Brief `health:DEGRADED` entries are the baseline: 11–173 per day over 10 days, 1–7 per hour today before the deploy. None is a DEGRADED **incident**.

## Interruption (measured)

- Stop: 17:45Z → 17:45Z (`p2f_continuous_stop.sh`). Clean marker `STOPPED`, exit 0, 0 partial segments.
- Start: 17:45Z → `UP OK` 17:45Z (`p2f_continuous_up.sh`). Gates: no blocking CRITICAL; previous run stopped cleanly.
- **Data downtime record: 24.855 s**, cause `clean_stop`, from 17:45Z (stop requested) to 17:45Z (new `ws_start`).
- Additionally, **one tier-1 depth stream** delivered no data until about 17:47Z and is recorded as a `never_ready` short gap. The symbol was in tier 1 under 1.6.0 as well. It is a low-activity stream, not attributable to 1.6.1, which changes no subscription or universe code.
- The monitor reported `STOPPED` / `binding_stale` from 17:45 until the rebind at 17:48Z, which is expected.

## Acceptance

| Checkpoint | Result |
|---|---|
| Immediate / T+2 min | Image ID `89232400…`, restart policy `no`, health `STARTING` → `DEGRADED` (that one stream) → **`HEALTHY` at 17:48Z**. All 257 streams `OBSERVING`. |
| T+10 min (17:55Z) | Container healthy, 0 restarts, OOM false; version 1.6.1; `config_hash` `6546b479…`; writer and certifier alive with 0 failures; 0 open gaps; 0 drops / malformed / task failures; incidents unchanged (3 WARNING); monitor `WARNING` (the swap mismatch has cleared); every other container unchanged; CPU 29 %, memory 150 MiB / 768 MiB, 7 PIDs. **Health state at that instant `DEGRADED`** (`stale:` on the same low-activity depth stream). The flip rate is unchanged from before the deploy, so it is not attributable to the release and no rollback trigger fires. |
| Session-end recording | Enabled in the run record. Confirmed in production at T+1 h (2 records, see below). |
| T+1 h (18:45Z) | **Passed.**
- `HEALTHY`; image `89232400…`; 0 restarts; OOM false; incidents unchanged (3 WARNING); writer and certifier alive with 0 failures; 0 open gaps, 0 drops / malformed / rejected / task failures.
- **First production `ws_session_end` records: 2**, both `local_end` / initiator `local`, after 2 `data_stall_reconnect` (correctly classified).
- DEGRADED flips: 4 in about 57 min, within the pre-deploy baseline of 1–7/h; monitor `WARNING`.
- CPU (monitor `cpu_cores_60s`): mean 0.364 after vs 0.390 in the 6 h before (−7 %). Memory (cgroup, including cache): 182 MiB after vs about 760 MiB before (fresh process).
- One isolated 60 s window with throttling 0.246 (18:06Z, CPU 0.26 cores) vs a pre-deploy max of 0.066: to watch, not a trigger.
- Every other container unchanged. |
| T+24 h (≈ 2026-10-23 17:45Z, incl. the 2026-10-22 seal with the downtime record) | pending |
| T+72 h (≈ 2026-10-25 17:45Z) | pending |

## Rollback readiness (not used)

- **Soft:** stop, then start the same image with `continuous-v1.json` (expect `config_hash` `feb253c3…`).
- **Full:** stop, then `p2f_continuous_up.sh tsb-p2-forward:p2f-160-1bfb5f6-20261014T0652Z sha256:324d52c9… <dataset> configs/continuous-v1.json compose.yml` (expect `45296f7a…`), then `p2f_monitor_bind.py bind --restart`.
- The 1.6.0 image is present locally, and two verified archives exist.
- O2a raised no incident, so nothing needs disposition after a rollback.
