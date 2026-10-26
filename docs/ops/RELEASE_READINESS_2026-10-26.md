# Release readiness: runtime baseline vs `main` (2026-10-26)

**Status: documentation only.** Nothing was deployed, restarted or changed. Every observation below is Class A
(read-only, `docs/ops/COMPOSE_OPERATIONS.md`): `docker ps`, `docker inspect`, `docker image inspect`,
`docker compose -p trading-signal-bot -f docker-compose.yml config --hash <svc>`, `git hash-object`, git reads, and
metadata or status files under `~/ops` and `~/backups`. No database was read and no trade outcome was read.

- `main` at observation: `cce58c3` (#92). #92 changed CI only: `.github/ci/change_scope.py`, three workflow
  files, `docs/ops/CI_EFFICIENCY.md`, `tests/test_ci_workflows.py` (`git diff --stat ef3d735 cce58c3`).
  No runtime file, no compose file, no Dockerfile.
- Baseline record: `deploy/DEPLOYED.json` (observed 2026-10-18, collector entry updated by #83 for Stage A).
- Release record: `deploy/a561-rel-ea8ae4f/IMAGES.md` (+ `CORRECTIONS.md`).

## 1. Runtime parity

Container ID, image ID and the `com.docker.compose.config-hash` label were compared with `deploy/DEPLOYED.json`.
The render hash is `config --hash <svc>` from the production directory.

| Service | Container ID | Image ID | Config-hash label | Render hash = label | Image vs `IMAGES.md` | Restarts |
|---|---|---|---|---|---|---|
| scanner | match (`891c46fd…`) | match (`63b38e7a…`) | match (`e99de276…`) | match | match | 0 |
| analyzer | match (`40b52387…`) | match (`011f99ba…`) | match (`c69beccc…`) | match | match | 0 |
| signal_engine | match (`f12b0176…`) | match (`c5be4e34…`) | match (`20dcae19…`) | match | match | 0 |
| telegram | match (`39fa735b…`) | match (`51d62f4d…`) | match (`3f039028…`) | match | match | 0 |
| trade_tracker | match (`c384b611…`) | match (`2cf1dd52…`) | match (`9d914e8f…`) | match | match | 0 |
| collector | match (`4b860ea4…`) | match (`89232400…`, 1.6.1) | match (`d12ba3b3…`) | not computed (needs the `P2F_*` values of the gated start script; covered by D3/D5) | **historical row**: `IMAGES.md` still lists 1.6.0 (`324d52c9…`); superseded by Stage A and recorded in `DEPLOYED.json` | 0, OOM false |
| postgres | match (`28eae480…`) | match (`721873c3…`, 16.15) | match (`2012965f…`) | out of scope (project `shared-postgres`, outside this repository) | match | 0 |
| continuous_learner | match (`e8c5ab76…`) | match | match | not computed (`compose-safe` refuses the learner) | n/a | exited, as required |

Compose files:

| File | Production blob | `origin/main` blob | Result |
|---|---|---|---|
| `docker-compose.yml` | `04f965ef8c20…` | `04f965ef8c20…` | match (also = `DEPLOYED.json`) |
| `p2_forward/compose.yml` (installed at `~/ops/tsb-p2-forward/compose.yml`) | `120529002e61…` | `120529002e61…` | match |

`StartedAt` of the five Paper services and postgres is 2026-10-19, after the host reboot of that day; the container
IDs are unchanged, so this is a restart of the same containers, not a recreate. `DEPLOYED.json` still carries the
pre-reboot start times (observed 2026-10-18). This is a staleness of the record, not drift; refreshing it is a
separate reviewed PR.

All five scanner/analyzer/signal_engine/telegram/trade_tracker containers and the collector report `healthy`.

## 2. On `main` but not deployed (since release `ea8ae4f` / `rel-ea8ae4f-r2`)

`ea8ae4f` is an ancestor of `main`. Diff of the service directories (`scanner/ analyzer/ signal_engine/ telegram/
trade_tracker/ shared/`) plus the other paths copied into images (`research/null_a/` for signal_engine):

| Merge | Change | Runtime files | Images affected if rebuilt | State |
|---|---|---|---|---|
| #59 (`614cecd`) | Versioned T1 resistance-cap policy flag, default unchanged | `analyzer/main.py`, `analyzer/technical_analyzer.py`, `shared/config.py` (+4), `shared/strategy_math.py`, `shared/t1_cap.py` (new), `shared/trade_geometry.py` | analyzer directly; `shared/` is in every service image | Not deployed. Excluded from RC-B by design (`deploy/rc-20261022/RELEASE_CANDIDATES.md` §3) |
| #74 (`80ab75d`) | Optional evidence telemetry write-rate limit, default unchanged | `research/null_a/recorder.py`, `shared/config.py` (+2), `signal_engine/signal_logic.py` (+1) | signal_engine | Not deployed. Packaged as RC-B `tsb-a561-signal_engine:rc-b-37a7c2c-20261022T0725Z` (`sha256:11e81d5d…`, present locally). Stage B **HOLD**, awaiting owner decision |

Other paths:

- `p2_forward/`: the collector runs `72c0bee` (1.6.1). Since then only tests changed (#81:
  `TEST_CORRECTIONS.md`, `test_p2f_rotation_e2e.py`, `tests/tools/diag_rotation_overlaps.py`). Nothing to deploy.
- `ops/research/`: #80 and #82 add `research_exec/budget.py` and `research_exec/budget_probes.py`. Neither is
  installed in `~/ops/research-runner` (the installed runner is unchanged since Stage C). Nothing wired.
- scanner: runs an assembled image (`deploy/aiohttp-3.14.3/IMAGES.md`, `deploy/baseline-2026-09-27/deployed_files.json`),
  not `ea8ae4f`. `DEPLOYED.json` records that 8 of its 23 files differ from `main` `scanner/` and `shared/`.
  A canonical scanner rebuild from `main` would therefore change more than #59.
- `docker-compose.yml`: unchanged since #39 and identical to production.

## 3. Open runtime-relevant Draft PRs

| PR | Scope | Wiring |
|---|---|---|
| #87 `feat/pipeline-liveness-monitor` | `ops/monitoring/pipeline_liveness.py` + tests: independent Paper pipeline-liveness monitor | Draft; not deployed, not installed on the host |
| #89 `feat/technical-halt-recovery` | `shared/halt_recovery.py`, `docs/ops/TECHNICAL_HALT_RECOVERY.md` + tests | Draft; design-and-test only. **Not wired**: no service imports it, risk controls unchanged. Because it lives in `shared/`, merging it puts the file into every future image build scope; that alone changes no behaviour |
| #84 | Stage B R-B3 runtime-safety validation (docs) | Docs; Stage B not authorized |
| #86 | Review-only dependency lock candidates (`deploy/locks/`) | No build uses them |
| #36 (base `develop`) | Least-privilege DB roles v3 | Design + isolated tests; not applied |
| #29 (base `integration/a49-candidate`) | `shared/fees.py` nonfinite guard | Not on `main` |

## 4. Collector health (read-only)

Source: `~/ops/tsb-p2-forward/monitor/p2-forward-continuous-v1/` (`status.json`, `alerts.jsonl`, daily
`samples.jsonl`, `monitor_lifecycle.jsonl`) and the daily seal files. Market payloads were not read; only health
states, reason categories and counts.

- Current: `health_state` HEALTHY, severity WARNING from the same 3 standing WARNING incidents as at Stage A
  (`previous_run_stopped_failed`, the 2026-10-10 external retrospective, `observation_loss:tier0`). No CRITICAL.
  Writer write errors 0, durable lag 0, certifier failures 0 / pending 0, OOM 0, swap 0, limits mismatch none,
  memory about 35 % of the anonymous limit, CPU about 29 % of quota. Single maximum GC pause in the last window
  about 2.4 s: worth watching, not a trigger.
- Restarts: container `RestartCount` 0 since the Stage A start on 2026-10-22 (17:45Z); monitor started once (the
  rebind on 2026-10-22), no monitor restart since.
- Seals: 2026-10-22, -23, -24, -25 all `result` PASS, report `PASS` true, `failures` empty (0). Every day from
  2026-10-07 to 2026-10-25 is sealed PASS.
- Alerts since 2026-10-22 (17:45Z): 536 DEGRADED entries, each followed by a recovery to WARNING; 2 STOPPED records
  during the Stage A recreate itself (binding transition), none afterwards.

| UTC day | DEGRADED alert entries | DEGRADED share of monitor samples |
|---|---|---|
| 2026-10-22 (from 17:45Z) | 32 | partial day |
| 2026-10-23 | 126 | 12.2 % (173 / 1415) |
| 2026-10-24 | 49 | 6.6 % (94 / 1415) |
| 2026-10-25 | **295** | **38.9 % (549 / 1413)** |
| 2026-10-26 (to about 17Z) | 34 | 5.6 % (56 / 1005) |

Reason categories in DEGRADED samples are `stale`, `gap_short`, `gap_open`, `awaiting_post_reconnect`, rarely
`conn_not_data_live`. On 2026-10-25 a single low-activity depth stream of one symbol was stale in 342 of 462
samples that carried a `stale` reason (a second depth stream in 105), at a steady 9–17 entries per hour all day.
On 2026-10-26 neither of those two streams is among the top two; the leading stream accounts for 21 of 37 such
samples and the hourly rate is back to 0–5. **The 2026-10-25 rise did not continue.** It is a flap of the health
classification on thin streams, not a data-loss event: the 2026-10-25 seal passed with 0 failures.

Stage A T+24 h and T+72 h rows in `deploy/rc-20261022/STAGE_A_DEPLOYMENT_RECORD.md` are still marked pending on
`main`. The evidence above is consistent with both windows passing (0 restarts, no CRITICAL, seals PASS, no
release-attributable DEGRADED), but recording that is an owner step.

## 5. Backup evidence (P1-BG)

Source: `~/backups/tsb-p1bg/` (log lines and names only).

| Run (UTC day) | Backup | Restore-verify | Retention |
|---|---|---|---|
| 2026-10-24 | OK | OK (26 tables, server 16.15) | 9 own sets, 2 restore-verified, removed 0, held by `RETENTION_HOLD` |
| 2026-10-25 | OK | OK | 10 own sets, 3 restore-verified, removed 0, held |
| 2026-10-26 | OK | OK | 11 own sets, 4 restore-verified, removed 0, held |

- `sets/`: 11 sets (7 older ones from 2026-10-02 to 2026-10-09, 4 since the fix on 2026-10-23).
- `RETENTION_HOLD`: present.
- `.incomplete-*` directories: 15 (2026-10-07 and 2026-10-10 to 2026-10-23, the failing period). Kept; nothing
  deleted.
- The daily run moved one hour later in UTC on 2026-10-25 (the host local-time change); the schedule is unchanged.
- Every set and image archive is on this host only.

## 6. Rollback references (from `deploy/*`)

| Service | Running | Rollback target | Offline archive |
|---|---|---|---|
| analyzer | `tsb-a561-analyzer:rel-ea8ae4f-r2` | `tsb-p1d-analyzer:p1d-59297305-20261001T2045Z` (`b9b13d95…`, present locally) | running: `~/backups/tsb-a564-release-images-20261016T204443Z/analyzer.rel-ea8ae4f-r2.tar`; rollback: `~/backups/tsb-a561-rollback-images-20261016T193728Z/analyzer.p1d-59297305.tar` (hashes in `deploy/a561-rel-ea8ae4f/ARCHIVE_REFERENCES.json`) |
| signal_engine | `tsb-a561-signal_engine:rel-ea8ae4f-r2` | `tsb-p1d-signal_engine:p1d-59297305-20261001T2045Z` (`80096a98…`, present) | running and rollback archives in the same two sets |
| telegram | `tsb-a561-telegram:rel-ea8ae4f-r2` | `tsb-p1d-telegram:p1d-59297305-20261001T2045Z` (`e5f3096b…`, present) | running archive in the A56.4 set; rollback: `~/backups/tsb-paper-images-a41-20261014T212634Z/telegram.p1d-59297305.20261014T212634Z.tar` (with `SHA256SUMS`) |
| trade_tracker | `tsb-a561-trade_tracker:rel-ea8ae4f-r2` | `tsb-p1d-trade_tracker:p1d-59297305-20261001T2045Z` (`698d3173…`, present) | running archive in the A56.4 set; rollback: `trade_tracker.p1d-59297305.20261014T212634Z.tar` in the same A41 set |
| scanner | `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z` | `tsb-aiohttp-rollback-scanner:pre-3.14.3-20260929` (`9b0b53a6…`, present) | running: `~/backups/tsb-aiohttp-20260929T122701Z/image-archive-20260930T091705Z/scanner-aiohttp-3.14.3.tar` |
| collector | `tsb-p2-forward:p2f-161-72c0bee-20261022T1558Z` | `tsb-p2-forward:p2f-160-1bfb5f6-20261014T0652Z` (`324d52c9…`, present) with the original `configs/continuous-v1.json` | rollback: two verified 1.6.0 archives in `~/backups/tsb-p2-forward-images/`. **No offline archive of the running 1.6.1 image was found** (local image store only) |
| postgres | upstream 16.15 | pre-upgrade evidence in `~/backups/tsb-pg-preupgrade-20260929T115158Z` | data recovery follows `docs/ops/TSB_BACKUP_RECOVERY_PLAN.md` |

The compose `image:` lines carry their rollback comments (`deploy/a561-rel-ea8ae4f/IMAGES.md`, "Compose"). The
collector procedure is in `deploy/rc-20261022/STAGE_A_MANIFEST.md` ("Rollback") and the deployment record.

## 7. Generic per-service rollback checklist (documentation only)

This restates `docs/ops/COMPOSE_OPERATIONS.md` Class B for a rollback; that file wins on any difference. It
authorizes nothing. Every step needs explicit owner approval for this specific service.

1. **Approval and plan.** Owner approval names one service, the exact rollback image (tag and ID from section 6)
   and the expected config hash. One service per step; never the learner; the collector uses its own gated
   start script, not the Paper compose.
2. **Evidence folder.** Create a timestamped, mode-700 folder. Capture for the target and for every other bot
   container: container ID, image ID and reference, `StartedAt`, `RestartCount`, network addresses, config-hash
   label.
3. **Pre-gates.** Risk posture verified per gate 2 (database read, or the approved invariance proof as in
   `deploy/rc-20261022/STAGE_B_GATE_DECISION.md`); learner stopped; rollback image present locally with the
   expected ID (if lost, load from the verified archive and re-check the ID before use); the production compose
   blob equals the reviewed blob; the render hash of the target equals the expected value.
4. **Execute.** Exactly one command for one service, in the canonical recreate form of `COMPOSE_OPERATIONS.md`
   Class B, against the rollback image (rollback override or the reviewed compose change). No build, pull,
   prune, bare `up`, `down` or `--remove-orphans`.
5. **Post-checks.** Target runs the expected image and config hash; every other container unchanged (IDs,
   images, start times); `healthy` on two consecutive fresh reads; log review (counts and codes only, nothing
   secret); risk posture and stopped learner re-verified.
6. **Record.** Update `deploy/DEPLOYED.json` through a reviewed PR after the rollback.
7. **Any deviation: STOP.** Keep the evidence and return to the owner. No improvised fix.

## 8. Not claimed / open

- Bit-for-bit reproducibility is not claimed for any image; parity here is identity (IDs and hashes), not a
  content re-verification (`runtime_manifest.py verify` uses `docker save` and was not run).
- The collector render hash was not computed.
- Undeployed on `main`: #59 (not packaged) and #74 (RC-B, Stage B HOLD).
- Gaps to schedule: offline archive of the running collector 1.6.1 image; off-host copies of every archive and
  backup set; refresh of `DEPLOYED.json` start times after the 2026-10-19 reboot; Stage A T+24 h / T+72 h
  closure entries.
