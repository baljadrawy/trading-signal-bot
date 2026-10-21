# Collector operations record, 2026-10-21

Owner-authorized, narrowly scoped. Read-only evidence throughout: no stream outcomes, counts or windows read or recorded, no Collector restart, no configuration change.

## 1. Acknowledgment of `inc-1792484815953-d1417a9c-1` (owner-approved single incident)

- **Cause.** Key `previous_run_crash_or_kill`, DEGRADED, count 1, opened 2026-10-20T08:26:55Z (5 s after the CHG-02 start).
  - The previous run `2cfb872f` last reported `STOPPING` at 2026-10-19T15:04:55Z, just before the host reboot at about 15:20Z. This is from the CHG-02 pre-recovery evidence.
  - The run never reached STOPPED, so the next start latched the incident.
- **Effect.** Docker health was `unhealthy` from about 08:27Z on 10-20, because the healthcheck accepts only HEALTHY, STARTING, DISABLED, STOPPING or STOPPED. The research-runner refused all admissions (`state != HEALTHY`).
- **Preflight (all PASS):**
  - identity and cause;
  - writing, sealing and backups normal;
  - 0 CRITICAL, and no other DEGRADED;
  - CHG-02 evidence SHA256SUMS OK; host scripts = `main` (13/13); `restart: no`; read-only rootfs; `gate` exit 0;
  - no queued, timed or cron research job;
  - holdout SEALED with look count 0; `DatasetPermission` gate intact.
- **Action.** `p2f_incident_ack.sh` (= `main`) at 2026-10-21T08:35Z, `binding_sha256 18a14000…`, file 0444. Nothing else was acknowledged.
- **Result.**
  - The running Collector merged the ack live (`poll_acks`).
  - State became HEALTHY in about 6 s, and Docker `healthy` at 08:35:30Z.
  - Same container `65b152109ca3`, 0 restarts.
  - The monitor went to WARNING.
  - One `ack` event was added (38 → 39).
  - `research-run admit --profile R1` now admits. No job was started; jobs start only on an explicit command.

## 2. Installation of the A41 acknowledgment-validation correction

| | Before | After |
|---|---|---|
| `~/ops/tsb-p2-forward/p2f_ack_binding.py` | blob `5f9b356`, sha256 `3ac71935…` (= `1bfb5f6`) | blob `8ef78f4`, sha256 `bf6b9188…` (= `main` = `f1b52a2`) |
| Mode / owner | 0500 tradmin:tradmin | unchanged |

- **Scope.**
  - The AST diff shows only `validate()` changed, plus the new helpers `pre_ack_record` and `_bound_run_problems` and the constant `MERGED_ACK_KEYS`.
  - `write_ack`, `gate`, `main`, `latest_run` and `load_state` are identical.
- **Dependencies.**
  - Used only per invocation, by `p2f_incident_ack.sh` and by the `p2f_continuous_up.sh` start gate (`gate()`).
  - The Collector container does not mount it, and the monitor does not use it.
  - No hash pin enforces it. `p2_forward/PROVENANCE.json` records the 2026-10-18 import state (`5f9b356`) and is now historical for this file.
- **Install.** Rollback copy `~/ops/tsb-p2-forward/backup-pre-a41-20261021T100233Z/` (SHA256SUMS verified, `ROLLBACK.md`), then an atomic replace (temp file in the same directory, mode 0500, `mv`) at 2026-10-21T10:02:47Z.
- **Validation (read-only).**
  - `gate` exit 0.
  - All **6** merged acks: `valid: true`. Before the install, all of them failed with `incident_record_changed_since_ack`, and the 5 older ones also with `run_lineage_mismatch`.
  - An unacknowledged WARNING still returns `no_ack`.
- **Evidence unchanged.** All 10 files under `incidents/` and all `seals/` files have identical sha256 before and after.
- **Stability.** Collector HEALTHY, `healthy`, 0 restarts; monitor active, 0 restarts.
- A pre-existing `__pycache__/p2f_ack_binding.cpython-312.pyc` (2026-10-14) is stale. Python invalidates it automatically because the source size and mtime changed. It was not deleted.

## 3. WARNING incidents: dispositions (none acknowledged)

Operational health and scientific data quality are assessed separately.

| Incident | Category | Operational status | Scientific data-quality implication | Recommended disposition |
|---|---|---|---|---|
| `inc-1791289593671-b1b7edb6-1` `previous_run_stopped_failed` (opened 2026-10-06) | run lifecycle: run `6fd4edbc` ended `FAILED` (the 2026-10-06 fail-closed writer-stall stop; its CRITICAL and the 2026-10-06 seal-failure CRITICAL are already acknowledged) | historical, cause resolved; no current effect | 2026-10-06 has a fail-closed stop and a **failed seal** (`2026-10-06.FAILED-*`): that day is not certified and must be excluded or flagged by a predeclared rule | acknowledge after owner review, referencing the A40 closure records |
| `inc-1791973646419-2cfb872f-1` `external:retrospective-2026-10-10-conn0-book-outage` (filed 2026-10-14) | retrospective disclosure of a bounded 2026-10-10 conn0-book outage caused by the collector 1.5.0 recovery defect, fixed by 1.6.0 (`1bfb5f6`) | historical, remediated | the outage window is recorded as gap records; affected book/miniTicker coverage must be handled by a predeclared exclusion rule | **first** import the referenced record (`RETROSPECTIVE_INCIDENT_2026-10-10`, which exists only on the held local branch) into `main` as documentation, then acknowledge |
| `inc-1791981120021-2cfb872f-2` `observation_loss:tier0` (opened 2026-10-14, count 10, last occurrence 2026-10-20) | recurring short Tier-0 observation losses on websocket disconnect/reconnect | **ongoing, intermittent**; bounded and recorded; health not affected (WARNING) | small, repeated coverage gaps in Tier-0 streams; any confirmation must fix in advance how gap records are excluded and report coverage | keep unacknowledged until a coverage summary is recorded **without** opening the holdout (counts only through the governed path). Acknowledging afterwards makes each future loss a new, visible incident |

Recurrence is visible only from the latched incident's count and last day. No stream windows or counts are reproduced here.
