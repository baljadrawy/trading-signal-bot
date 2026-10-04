# P2 continuous forward collector: operations (P2-CR fast-track, 2026-10-04)

**Status:** IMPLEMENTED AND OFFLINE-VALIDATED ON BRANCH `feature/p2cr-fasttrack-20261004`. NOT deployed, NOT started.
Starting continuous collection needs the owner's start authorization (section 9). Trading stays PAPER_HALTED.

Owner decisions applied (2026-10-04):

| # | Decision |
|---|---|
| D1 | On-host sealed-day backup only (host loss accepted temporarily; NOT disaster recovery) |
| D2 | One logical continuous dataset across runs, with explicit downtime |
| D3 | `restart: "no"` plus a manual gated restart |
| D4 | Local persistent incidents plus an observer; external delivery later |
| D5 | Monitor is OBSERVE ONLY |
| D6 | R13 reader support moves to P2-C; record schema v2 and `SCHEMA.md` are unchanged |
| D7 | PR #3 not merged |

## 1. Modes (Package A, CR-B01)

| | `bounded` (default) | `continuous` |
|---|---|---|
| Selection | default; `mode` omitted or `"bounded"` | only `"mode": "continuous"` **and** `"max_runtime_s": 0` **and** `dataset_id` |
| Runtime | stops at `max_runtime_s` ∈ (0, 28,800] | no runtime limit; stops only by operator stop or fail-closed stop |
| Behaviour | P2-E1 behaviour unchanged (all G3 tests pass) | adds sections 2–6 below |
| Refused | `max_runtime_s` 0 / missing / string / bool; unknown keys | gate-only tests (`rotation_test_at_s`, `reconnect_test_at_s`), thread certifier, rotation ≥ 24 h |

A malformed config can never become continuous: `mode` must be exactly `"continuous"`, unknown keys are rejected, and
`enabled` / `max_runtime_s` are type-checked.

## 2. Dataset model (Package E, CR-R07)

**Identity**
- One directory = one logical dataset, identified by the immutable `dataset.json` (`dataset_id`, calendar).
- A start with a mismatching id or calendar, or into a non-empty directory without identity, is **refused before
  anything is written** (exit 5).

**Runs**
- Every start writes `runs/run-<boot>.json` (immutable). Each record carries `mode`, `dataset`, `previous_run` and
  `calendar`.
- At `ws_start`, the run also writes `runs/downtime-<boot>.json` plus a `downtime` lifecycle record. These name the
  previous run, its stop marker and state, and the cause:
  - `first_run`
  - `clean_stop`
  - `stopped_<state>`
  - `crash_or_kill`
- Downtime is never stitched.

**Crash**
- There is no stop marker. The day verifier derives the crashed run's end **per stream** from the data on disk
  (last persisted or gap boundary) and counts the rest as `downtime_crash`.
- A crash without a successor run cannot be verified (fail closed).

**Crash-recovery gaps**
- These start at the last salvaged record, or at the segment's hour start. They never start at epoch 0.

**Storage cap**
- Total storage is measured across the whole logical dataset, against `dir_stop_gb` (150 GB).
- The measurement is: closed days from their day-close records, open days and non-raw directories by listing, in a
  worker thread.

## 3. Day lifecycle (Package C)

**Day checkpoint**
- At the first sample boundary of each calendar day, every open gap is split. The part before midnight is recorded
  with `day_split: true`.
- A `day_checkpoint` lifecycle record then stores:
  - the run record and its SHA-256;
  - the active universe epoch;
  - each connection's state;
  - the calendar.
- Each day is therefore verifiable from its own files plus the next day's first hour (spillover).

**Universe refresh (F10)**
- Runs once per day at day start + `universe_refresh_at_s` (600 s).
- It is a deterministic tiers-v2 evaluation, persisted with its raw REST inputs.
- An accepted change becomes effective at a 1 s boundary T as a `universe_transition` record. The record lists:
  - `added`;
  - `removed` (retired streams: their gaps are closed and recorded; late messages on them are counted, never
    "unknown");
  - `retiered` (same stream, new cadence: the received messages carry over and no startup excuse is needed);
  - the new per-connection lists, which are disjoint (no duplicate subscriptions).
- Both connections are then overlap-rotated to the new lists.

**Tier-transition semantics (R05)**
- Boundaries before T belong to the old epoch, at the old cadence and tier.
- Boundaries at or after T belong to the new epoch.
- A stream added at T has its first-observation deadline counted from T.
- If a refresh fails or is implausible (F42), the previous universe stays active, a DEGRADED state-like incident is
  raised, and the refresh is retried every 30 min.

**Proactive rotation (F24)**
- Each connection gets an overlap rotation `ws_rotation_s` (23 h) after its last (re)connect.
- The new connection's connect is an up-transition. Pre-rotation values are never persisted as fresh after it, and
  any outage becomes explicit gaps.
- A rotation that fails to overlap raises a WARNING incident.

**Day close (collector)**
- At day end + `day_close_after_s`, a day is closed: `days/<D>.json`, listing its files, sizes and manifest SHA-256.
- Preconditions: no `.partial` / `.pending` / `.certifying` file, no open writer segment in the day, and the files and
  the day manifest match exactly.
- A mismatch is a manifest/checksum integrity failure and triggers a fail-closed stop.
- Closed days leave every hot path (CR-B02).
- Certification refuses a closed day: the segment is quarantined with `conflict:day_closed`.
- Startup refuses if a closed day's files changed.

**Independent daily seal (host job)**
- `ops/p2f_seal_day.py <dataset> --day D` runs `verifier/verify_continuous.py`, the multi-run, epoch-aware day
  verifier, which imports nothing from the collector.
- PASS: writes `seals/D.json` and `seals/D.report.json`, both immutable.
- FAIL: writes `seals/D.FAILED-*.report.json` and a CRITICAL `incidents/external/seal-D-*.json`.
- It only seals closed days with final spillover.

**Sealed-day backup (F29 corrected; owner D1 on-host)**
- `ops/p2f_backup.py backup <dataset> D` copies PASS-sealed days only:
  - raw files including `.idx`;
  - spillover;
  - manifests;
  - day-close and seal records;
  - run, downtime and stop records;
  - the universe artifacts, prior artifacts and raw inputs the day needs.
- Safeguards:
  - free-space precheck (2× size plus a 60 GB floor);
  - SHA-256 at source and destination;
  - immutable destination;
  - no deletion, ever.
- `restore-test` re-checks SHA256SUMS and runs the day verifier **on the backup copy**.
- Failures raise visible external incidents.

**Hot-path bound (CR-B02)**
- These paths use open days only, never the historical tree:
  - certifier scans;
  - `pending()` in health evaluation;
  - disk accounting (worker thread);
  - manifest completion;
  - startup recovery.
- Startup also does a one-time, names-and-sizes check of closed days.

## 4. Incidents (Package G)

**Files** (`<dataset>/incidents/`)
- `state.json`: current state.
- `events.jsonl`: open / update / resolve / ack history, fsynced.
- `ack/<id>.json`: operator acknowledgements.
- `external/*.json`: written by the seal and backup jobs.

**Incident fields**
- `id`, `key`, `severity`, `first_ms`, `last_ms`, `count`, `active`, `ack`, plus the first and last occurrence
  details.

**Lifecycle**
- **Latched** (integrity events): active until acknowledged.
- **State-like** (disk warning, clock, universe refresh, day close overdue): resolve when the condition clears.
- After an acknowledgement or resolution, a recurrence opens a **new** id, so an old incident never masks a new one.

**Health**
- Each active DEGRADED or CRITICAL incident is a hard health reason (`incident:<key>`).
- Each WARNING incident is a warning.
- After an acknowledgement, the health recovers.

**Bounded mode**
- Health semantics are unchanged.

## 5. Fail-closed matrix (Package F; continuous mode)

A fail-closed stop works as follows:
- the drain is graceful and the exit code is 6;
- a CRITICAL `failclosed:<reason>` incident is raised and recorded with `fail_closed_stop` lifecycle and fatal and
  stop markers;
- `restart: "no"` keeps the container down until an operator acts.

| Condition | Action |
|---|---|
| Disk free < 60 GB, or dataset ≥ 150 GB | **stop** (writes refused at once, then stop) |
| Disk free < 100 GB | WARNING incident (continue) |
| Day-close mismatch (manifest / checksum / listing) | **stop** |
| Certification failure | DEGRADED latched incident; 2nd in 24 h → **stop** |
| Quarantine created | DEGRADED latched incident; 2nd in 24 h → **stop** |
| Clock CRITICAL (excess > 2 s) | records flagged `clock_suspect`, CRITICAL incident; persisting 1 h → **stop** |
| HTTP 418 | **stop** at once (no automatic resume) |
| HTTP 429 | 1st: WARNING incident (visible in health); 2nd in 24 h → **stop** |
| Process-role violation (in-container self-check, v8 roles; unknown process in 2 consecutive 5 s checks) | **stop**; single sighting = WARNING |
| Writer heartbeat stale ≥ 60 s, or not durable ≥ 60 s | **stop** (DEGRADED from 5 s / 10 s) |
| Writer thread dead / certifier failed 3× | **stop** (pre-existing fatal paths) |
| Task / handler / wall-clock-step / reconnect events | incidents only (never a stop: transient) |

## 6. Authority (owner D5)

| Capability | Monitor (`ops/p2f_cont_monitor.py`) | Operator | Owner |
|---|---|---|---|
| Read cgroup, /proc, health, incidents, day / seal records | ✓ (no Docker, no signals, writes only its own output dir outside the dataset) | ✓ | ✓ |
| Start / stop / restart collector | ✗ | gated scripts only (`p2f_continuous_up.sh`, `p2f_continuous_stop.sh`) | authorizes continuous mode |
| Acknowledge incidents | ✗ | `p2f_incident_ack.sh` (reference required) | ✓ |
| Seal / back up days | ✗ | `p2f_seal_day.py`, `p2f_backup.py` | schedule needs owner authorization |
| Delete any data / evidence | ✗ | ✗ (only an owner-approved deletion list) | approval only |
| Trading, Paper, risk, funded keys, learner, W3, walk-forward, dead letters | ✗ | ✗ | outside P2 |

**Additional refusals by `p2f_continuous_up.sh`:**
- unacknowledged CRITICAL incidents;
- a non-explicit continuous config;
- a dataset id mismatch;
- a compose file that isn't `restart: "no"`, or that has ports, host networking, a Docker socket or privileged mode;
- an image ID mismatch;
- a previous run that didn't stop cleanly, unless `P2F_ACK_PREVIOUS=<boot8>` is set.

**Known limit:** OS-level separation of the monitor needs a dedicated user without Docker-group membership. That is
recommended, not yet done.

## 7. Operator runbook

| Question | Answer |
|---|---|
| Is it healthy? | Read the monitor's `status.json` (severity, reasons). The collector writes the health file to `<dataset>/health/collector_health.json`. |
| Is it writing? | Check `writer.beat_age_ms` / `durable_lag_ms` in health, and the monitor `samples.jsonl`. |
| Is data certified? | `certifier.pending` / `oldest_pending_age_ms`; the `days/` closed records; the `seals/` PASS records. |
| Is disk safe? | Health `disk.free_gb` and `collector_dir_gb` (aggregate); incidents `disk_warning` / `failclosed:disk_hard_stop`. |
| Did we lose data? | The day seal report: `totals.unexplained` must be 0; `downtime_ms` and `downtime_intervals` list every explicit outage; gaps are in the gap records. |
| Should I restart? | Only after a fail-closed or crash stop has been reviewed, and **never** for a FAILED state without reading the incident and its markers. |
| Can I restart? | Use `p2f_continuous_up.sh`, which refuses while CRITICAL incidents are unacknowledged. |
| How do I stop safely? | `p2f_continuous_stop.sh <dataset> <compose>`: graceful drain (≤ 450 s), then it prints the stop marker. Never `docker kill` / `docker rm` the collector, and never `docker exec` into it: an exec'd process trips the process-role check. |

**Evidence to preserve before any restart (copy, never move or delete):**
- `control/` (stop, fatal and disk markers);
- `incidents/`;
- `quarantine/`;
- `health/`;
- the monitor directory;
- `docker inspect` (State, ExitCode, OOMKilled);
- `docker logs` of the exited container.

**After a host reboot:**
1. Run the production checks first (PAPER state, B3).
2. The collector is down by design.
3. Review the incident and markers.
4. Preserve the evidence.
5. Restart with `P2F_ACK_PREVIOUS` if the previous run did not stop cleanly.
6. Recovery salvages partial segments, and the downtime is recorded.

**Never delete:**
- `raw/`, `manifests/`, `days/`, `seals/`, `runs/`, `control/`, `quarantine/`, `incidents/`, `universe/`;
- the backups.

**Escalate to the owner on:**
- any CRITICAL incident or fail-closed stop;
- a seal FAIL;
- a backup or restore failure;
- a disk warning;
- a process-role warning;
- any 429/418;
- any need to delete or to change thresholds.

## 8. Initial continuous monitored soak (the first 72 h of real operation)

**Not a separate pre-start soak:** the first 72 h of authorized operation are both forward data collection and the
long-duration validation.

**Evidence collected:**
- memory (anonymous memory and cgroup memory, from monitor samples every 60 s);
- CPU and throttling;
- sampler lateness, loop lag and GC;
- 3 day transitions with their checkpoints, universe refreshes and transitions;
- 6+ proactive rotations;
- 3 day closes and 3 independent seals;
- 3 sealed-day backups and ≥ 1 restore-test;
- certification backlog;
- disk growth;
- reconnects;
- REST weights and 429/418;
- incident state.

**Proposed predeclared review criteria at 72 h:**
- 3/3 seals PASS with 0 unexplained;
- 0 fail-closed stops, or each one explained and reviewed;
- anonymous-memory floor slope over the last 48 h ≤ 0.5 MiB/h, and peak < 75 % of the limit;
- throttled periods ≤ 10 % per hour;
- sampler lateness > 2 s on ≤ 0.1 % of boundaries;
- 0 429/418;
- every rotation `overlap_ok`;
- backups and restore PASS.

**Planned gated restart (if the owner authorizes it):**
- **When:** at about +36 h, between hour :20 and :40 of the hour, when no rotation is due, ≥ 30 min after the day's
  universe refresh and transition, and away from a day end.
- **Why then:** it tests the clean-stop drain, explicit downtime, multi-run verification and restart into the same
  dataset with minimal sample loss (seconds of explicit downtime).

## 9. Start gate (owner authorization)

**Validation already done (PASS):**
- **CR-B01:** explicit continuous mode.
- **CR-B02:** bounded hot paths at 365 days of synthetic history.
- **Package C:** day lifecycle.
- **Package D:** seal, backup and restore.
- **Package E:** restart and crash correctness.
- **Package F:** fail-closed controls.
- **Package G:** incidents.
- **Package H:** GC observability.

**Execution steps at authorization:**
1. Review and approve the remediation commits on `feature/p2cr-fasttrack-20261004`.
2. Build the image from the reviewed commit in isolation and record the image ID.
3. Create the dataset directory.
4. Deploy the gated scripts and the monitor to `/home/tradmin/ops/tsb-p2-forward/`. The compose file stays
   `restart: "no"`.
5. Run the isolation probe.
6. Run the production pre-check.
7. Start with `p2f_continuous_up.sh`.
8. Start the observe-only monitor.
9. Schedule the daily seal and backup, or run them manually. Scheduling needs owner authorization.
