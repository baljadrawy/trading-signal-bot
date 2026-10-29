# Sealed-safe Paper monitoring (OD-7)

**Status:** design and read-only tooling only. Nothing here is scheduled, installed on the host or enabled. Running the
commands below by hand is a Class A read-only action (`docs/ops/COMPOSE_OPERATIONS.md`). A cron entry or systemd
unit for them is host persistence and needs a separate owner approval.

## Rule

The FORWARD_HOLDOUT after the 2026-08-19 research freeze is sealed (`docs/research_temporal_governance.md`). OD-7
forbids protected outcome, count and timestamp reads (`docs/governance/DEVELOPMENT_FIRST_POLICY.md`). Routine
monitoring therefore reads no Paper trading record, count, outcome or record timestamp. Reducing such a read to a
Boolean does not make it compliant, because the Boolean still discloses information (one bit,
`deploy/rc-20261022/STAGE_B_GATE_DECISION.md`). Monitoring uses only signals whose source contains no sealed record.

## Allowed signals

| Signal | Command | Source and provenance | Alert |
|---|---|---|---|
| Paper service liveness: state, Docker health, restart count | `ops/compose-safe health` | One `docker inspect --format` per service. The template names only `State.Status`, `State.Health.Status` and `RestartCount`. The Docker CLI itself receives the full container object from the daemon, including the environment and the healthcheck log, and applies the template internally; only the three fields are returned to `compose-safe`, which never prints or stores anything else. The Docker health of every Paper service comes from its own healthcheck, `python -m shared.health`. That check reads only `last_success_at` and `consecutive_errors` from `service_heartbeats`, never `metadata` or `last_error`. `shared/health.py` is identical at the deployed source commits ea8ae4f and bb7825f. | Exit 1 and an `ALERT` line for any service that is not running and healthy, whose output is missing or unexpected, or whose `docker inspect` does not return within `HEALTH_TIMEOUT_SECONDS`. Docker output and stderr are never echoed. |
| Runtime identity, restarts, `PAPER_TRADING`, learner stopped | `ops/provenance/drift_check.py check` (existing, unchanged) | `docker inspect` with explicit templates against `deploy/DEPLOYED.json`. | DRIFT 1, UNKNOWN 2, SAFETY 3 |
| Collector container health | `docker inspect --type container --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}} {{.RestartCount}}' tsb-p2-forward-collector` | The `HEALTHCHECK` in `p2_forward/Dockerfile` reads only `ts_ms` and `state` of the Collector health file. | Not running, or not healthy |
| Collector severity and write integrity | Fields `severity`, `severity_reasons` and `writer.write_errors` of the existing Collector monitor's `status.json` (`tsb-p2f-monitor`, unchanged) | `p2_forward/ops/p2f_cont_monitor.py` `sample()` records health state, resource use, writer lag and errors, incident keys and dataset day labels. It records no market record, count or price. The installed copy is byte-identical to the repository blob (`211e027`, checked 2026-10-29). | Its own `alerts.jsonl` |

**Provenance and signal limitations.**

- **Scanner image.** The scanner image was assembled, and its source reproducibility is not proven
  (`deploy/aiohttp-3.14.3/IMAGES.md`). Its `shared/health.py` and heartbeat loop are established only by recorded
  evidence: the file hashes in `deploy/baseline-2026-09-27/deployed_files.json` (2026-09-27), plus the 2026-09-29
  overlay gate that recorded `/app` as byte-identical. They have not been re-verified against the running image.
- **Heartbeat freshness.** Each service writes its heartbeat once per loop cycle, idle and paused cycles included, so
  freshness is mainly a liveness signal. A cycle's duration still depends on its workload, so a heartbeat older than
  `HEALTH_MAX_AGE_SECONDS` can weakly reflect activity volume as well as a fault. `health` reports only the
  healthy/unhealthy status, never the heartbeat age.

`tests/test_sealed_safe_monitoring.py` pins the healthcheck sources. Any change to `shared/health.py`, a compose
healthcheck or the Collector `HEALTHCHECK` that reads anything else fails those tests. Such a change needs this design
to be reviewed again.

## Excluded from routine monitoring

- Production database queries of trading tables: `risk_management`, `outbox_events`, `active_trades`, `signals`,
  `scan_candidates`, `trade_results`.
- Container logs (`docker logs`, `ops/compose-safe logs`). They carry trading events with timestamps.
- `data/evidence_v2/`. These files hold the sealed evidence records.
- The healthcheck log (`State.Health.Log`). It holds heartbeat-age figures and error text; the status is sufficient.

## Requires separate owner authorization (not implemented)

| Check | Why it is protected | Until authorized |
|---|---|---|
| Pause or halt state (`risk_management`) | Sealed risk-state record; even a Boolean discloses information | The bot's own Telegram halt notices to the owner (unchanged). Class B deployment gates keep their procedure-authorized pause read. |
| Risk outbox counts (`risk.halted`, `risk.observed`) | Sealed event counts | Same as above |
| Admission records, first-admission label | Sealed records | The label verification is recorded once (`deploy/VERSION_BOUNDARY.md`, amendment A2) |
| Trades opened, signals, `scan_candidates` bound, non-finite trade results | Sealed counts | Not monitored; a technical bound needs an authorized design |

## Host scripts: NON-COMPLIANT

`~/ops/tsb-paper-resume/paper_continuity_check.sh`, `monitor_resume.sh` and `readiness_check.sh` are outside Git.
They query trading tables, read container logs and scan `data/evidence_v2/`, so they do not comply with OD-7. They are
left unchanged and are not scheduled (no crontab entry). **They must not be run.** Their past outputs under
`~/ops/tsb-paper-resume/` are protected material (`research/governance/contamination_registry.jsonl`).
