# SE-1: signal_engine funnel telemetry (Phase 1, first increment)

**Status: PREPARED. Not built, not deployed, not activated.** This record defines one bounded Paper increment under [the functional incremental Paper activation method](../../docs/governance/WP2_FUNCTIONAL_INCREMENTAL_PAPER_ACTIVATION_2026-11-01.md). Writing it executes nothing.

| State | Value |
|---|---|
| Implemented | yes: `bc90b85` and its predecessors on `feature/wp2-foundation-20261101` |
| Integrated | yes, in source: release commit `ee042f6`, branch `release/se1-funnel-ea8ae4f` |
| Tested | yes: see "Evidence" |
| Independently reviewed | **NO (PENDING)** |
| Merged | NO |
| Deployed | NO |
| Activated | NO |
| Runtime-validated | NO |

## Scope

- **Service:** `trading_signal_engine` only. The scanner, analyzer, tracker, telegram, the collector and postgres are unchanged.
- **Base image:** the running image `tsb-a561-signal_engine:rel-ea8ae4f-r2`, image ID `sha256:c5be4e34c064c707cb421c2f5d26c38dfee8ad75f36d7e3b177be88d4a825418`.
- **Change:** the release commit `ee042f6` is the deployed source `ea8ae4f` plus six files taken unchanged from the WP2 branch: `signal_engine/main.py`, `shared/funnel_flags.py`, `shared/funnel_hooks.py`, `shared/funnel_records.py`, `shared/funnel_recorder.py` and `shared/selection_policy.py`. No other file differs (`git diff --stat ea8ae4f ee042f6`: 6 files).
- **Overlay:** [Dockerfile](Dockerfile) copies only those six files over the running image, as the owner `1000:1000`. It adds a revision label and leaves the dependency set unchanged.
- **Configuration:**
  - `FUNNEL_RECORDING: "on"` is added to the signal_engine environment.
  - `EVIDENCE_V2_ENABLED` is already `"true"` (RUNTIME_VERIFIED 2026-11-01).
  - `SELECTION_POLICY` stays unset, which means legacy.
  - Nothing else changes.

## Behaviour

- **Decisions:** unchanged.
  - The candidate query literal, `LIMIT 200` and its ordering are byte-identical (sha256 pinned in a test).
  - Traces of signals, database statements and heartbeats are identical with recording off and on (25 seeds).
- **New output:** `funnel.rejection` and `funnel.cycle` events in signal_engine's existing evidence_v2 JSONL subdirectory. They cover F3 macro veto, F2/F4/F5 per symbol, `F6.rank_below_cap` and `F6.legacy_alphabetical_cut`, which shows what the alphabetical `LIMIT 200` cut drops (R1). Records are compacted to one per state change. Each cycle emits at most 901 records; anything beyond that is counted as `records_overflow`.
- **Database:** zero additional statements. The cut records reuse the rows the deployed truncation diagnostic already reads. Off-vs-on statement traces are identical in tests.
- **Storage:**
  - About 9 to 40 MB per day at 50 live subjects. The hard ceiling at the per-cycle bound is about 2.1 GB per day.
  - Disk retention of the evidence_v2 store is not bounded by code. Retention is an operations item (OF-OD-18).
- **Failure isolation:**
  - The recorder sits behind evidence_v2's non-blocking bounded queue, which drops when full and never raises.
  - A broken store or recorder leaves decisions unchanged (`tests/test_funnel_records.py`, broken-store test).
  - An unknown `FUNNEL_RECORDING` value refuses at start-up.
- **Version identity:** the strategy source closure changes because `signal_engine/main.py` is ACTIVE. The decision logic does not change. A version-boundary record is therefore required (template [VERSION_BOUNDARY_TEMPLATE.md](../VERSION_BOUNDARY_TEMPLATE.md)).

## Evidence (local, before activation)

- **Regression:** the `ea8ae4f` test suite on the `ee042f6` tree gives 1064 passed / 847 skipped, identical to pristine `ea8ae4f`.
- **Signal-engine funnel and selection tests on the `ee042f6` tree:**
  - On the host, with before-tree parity against `ea8ae4f`: 86 passed.
  - **Inside the deployed image** (disposable container, no network, read-only mounts): 85 passed. One harness-only case is excluded because its child process loses the mounted pytest path.
- **Branch suites (development tree):**
  - Full no-database suite: 4232 passed. The one failure, `test_aiohttp_314_compat::test_version`, is environmental. It passes 11/11 in a venv built from `.github/ci/requirements-test.txt`, where aiohttp is 3.14.3.
  - Disposable-PostgreSQL matrix at `774b0b7`: 4638 passed, with the same single environmental failure.
- protected_scan is clean.

## Activation request (specific approvals still required)

1. **Independent review** of `git diff ea8ae4f ee042f6` (six files) and of [Dockerfile](Dockerfile), by a reviewer other than this Claude session.
2. **Owner answer on observation scope.** Confirm that SE-1 operational telemetry may be read during validation: funnel reason codes and conservation counts, with no outcomes and no P&L. If not, validation is limited to health, drop and overflow metrics (OD-7 protects forward counts).
3. **Class B: the release-image build.**
   - Export `git archive ee042f6` to a clean directory, never the production checkout.
   - Verify that the base tag resolves to `sha256:c5be4e34…`.
   - Build with `docker build --network=none --pull=false --build-arg BASE_TAG=<verified tag> --build-arg SOURCE_COMMIT=ee042f6420be2a267295c173232d451a17aacbd6 -t tsb-se1-signal_engine:ee042f6-r1 .`
   - Verify the result with `ops/provenance/runtime_manifest.py` against [services.json](services.json).
4. **Compose change through the reviewed-blob rule.** In `docker-compose.yml`, the signal_engine `image:` becomes `tsb-se1-signal_engine:ee042f6-r1` (rollback comment: `tsb-a561-signal_engine:rel-ea8ae4f-r2`), and `FUNNEL_RECORDING: "on"` is added. The change is integrated into `main` by the independent reviewer and installed in the production checkout per COMPOSE_OPERATIONS.md.
5. **Class B: recreate of signal_engine only.**
   - Use the documented form: `docker compose -p trading-signal-bot -f docker-compose.yml up -d --no-deps --no-build --pull never --force-recreate signal_engine`.
   - Capture identity before and after (container ID, image ID, StartedAt, RestartCount, IPs).
   - Run two fresh health checks.
   - Check the PAPER_HALTED/B3 gate per COMPOSE_OPERATIONS.md.
6. **Version-boundary entry** for signal_engine, recorded at activation.

## Validation after activation

Within 15 minutes:
- the container is healthy twice;
- the image ID is the new one;
- the logs show no start-up refusal;
- the heartbeat carries `funnel` health, with `not_recorded`, `records_overflow`, and evidence_v2 `dropped`/`errors` all at 0.

Over the observation window:
- every `funnel.cycle` event passes conservation;
- the analyzer → signal_engine → telegram hand-off continues;
- error and restart counts are unchanged.

If no candidate cycles occur, the result is **insufficient runtime evidence**, not success.

**Accept** when health, drop/overflow and conservation hold for the window. **Roll back** on any start-up refusal, health failure, unexpected database statement, non-zero drop, or STOP condition.

## Rollback

Restore the signal_engine `image:` to `tsb-a561-signal_engine:rel-ea8ae4f-r2` and remove `FUNNEL_RECORDING`, through the same Compose path. Then repeat the Class B recreate of signal_engine only, and verify identity and health twice. Funnel events already written stay where they are. Nothing else in the database or on disk changes.

**STOP rule:** anything unexpected (a hash, a diff, a container identity, a failed gate, a secret in output) means stop and return to the owner.
