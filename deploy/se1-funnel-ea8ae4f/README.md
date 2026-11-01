# SE-1: signal_engine funnel telemetry (Phase 1, first increment)

**Status: PREPARED. Not built, not deployed, not activated.** This record defines one bounded Paper increment under [the functional incremental Paper activation method](../../docs/governance/WP2_FUNCTIONAL_INCREMENTAL_PAPER_ACTIVATION_2026-11-01.md). Writing it executes nothing.

| State | Value |
|---|---|
| Implemented | yes (feature branch, last SE-1 change `13704d4`) |
| Integrated | yes, in source: release commit `7ff582f` on branch `release/se1-funnel-ea8ae4f` |
| Tested | yes: see "Evidence" |
| Independently reviewed | **NO (PENDING)**: a same-session pre-review was done and is **not** independent |
| Merged | NO |
| Deployed | NO |
| Activated | NO |
| Runtime-validated | NO |

## Scope

- **Service:** Compose service `signal_engine` (container `trading_signal_engine`, project `trading-signal-bot`; labels verified read-only on 2026-11-01). The scanner, analyzer, tracker, telegram, the collector and postgres are unchanged.
- **Base image:** the running `tsb-a561-signal_engine:rel-ea8ae4f-r2`, image ID `sha256:c5be4e34c064c707cb421c2f5d26c38dfee8ad75f36d7e3b177be88d4a825418`.
  - The running container uses exactly this ID.
  - Its 55 Python files and its `requirements.txt` hash-match `ea8ae4f` (checked in a disposable, no-network container started from that image ID).
- **Source:** release commit `7ff582fa43b4fd16042ccb6f71035e4031b67eac` = `ea8ae4f` + six files: `signal_engine/main.py`, `shared/funnel_flags.py`, `shared/funnel_hooks.py`, `shared/funnel_records.py`, `shared/funnel_recorder.py`, `shared/selection_policy.py`. `git diff --stat ea8ae4f 7ff582f` lists exactly 6 files.
- **Overlay:** [Dockerfile](Dockerfile) copies only those six files, as `1000:1000`, onto the base image ID and adds revision labels. The dependency set is unchanged.
- **Configuration** (exact strings; any other value refuses at start-up):
  - `FUNNEL_RECORDING: "on"`;
  - `FUNNEL_MAX_RECORDS_PER_DAY: "<positive integer, owner-chosen>"`, which is required whenever recording is `on`;
  - `EVIDENCE_V2_ENABLED` stays `"true"` (RUNTIME_VERIFIED);
  - `SELECTION_POLICY` stays **unset**, which means legacy.
  - Nothing else changes.
- **Rollback images present locally:**
  - `tsb-a561-signal_engine:rel-ea8ae4f-r2` (`c5be4e34…`), the current one;
  - `tsb-p1d-signal_engine:p1d-59297305-20261001T2045Z` (`80096a98…`), the documented older rollback.

## Behaviour

- **Decisions unchanged:**
  - All six SQL literals of `ea8ae4f` `main.py` are present unchanged (AST comparison). The candidate query, `LIMIT 200` and its ordering are byte-identical, with the sha256 pinned in a test.
  - Signals, database statement text, count and order, and downstream messages are identical with recording off and on (25-seed parity, including before-tree parity against `ea8ae4f`).
  - Funnel on issues **zero additional database statements**.
- **New output:**
  - `funnel.rejection`, series-close and `funnel.cycle` events in signal_engine's existing evidence_v2 subdirectory.
  - Reason codes: F2/F4/F5 per symbol, F3 macro veto, `F6.rank_below_cap`, `F6.legacy_alphabetical_cut` (what the alphabetical `LIMIT 200` cut drops; R1 evidence) and F7 `exposure_symbol` (open trade exists). Taxonomy is v1.1, additive.
  - Every live-selector label is mapped. An unknown label is counted once as `F4.unattributed` and does not invalidate the cycle.
- **Storage bound:** records are compacted to one per state change, with at most 901 per cycle, and capped per UTC day by `FUNNEL_MAX_RECORDS_PER_DAY`.
  - Worst case per day ≤ 1440 × 2006 B (the always-emitted cycle envelopes, about 2.9 MB) + cap × 1657 B. For example, a cap of 20000 gives about 36 MB per day.
  - Expected typical volume is about 9 to 40 MB per day at 50 live subjects.
  - Disk free on the data filesystem: 474 GB (37 % used; read-only `df`, 2026-11-01).
  - The evidence_v2 store has no retention mechanism. Deleting evidence would be an evidence mutation, so the bound is applied at the source.
- **Latency:** worst case 75 to 175 ms of synchronous CPU per cycle, before the existing save and `mark_success` (measured in the pre-review). Statement order is unchanged.
- **Failure isolation:**
  - The recorder sits behind evidence_v2's non-blocking queue (10000 events, drops when full, never raises).
  - With a broken store or recorder, decisions are unchanged (tested).
  - The series cache is bounded to 50000 entries.
  - Funnel events share the evidence_v2 queue. If the sink fails, other evidence types drop sooner (visible in `dropped`).
- **Start-up refusal** (fail-closed, DFP:L87): with an invalid value the container exits before any database I/O, and under `restart: unless-stopped` it restart-loops. This is visible only in the container log. That is why the validation below checks the log and the RestartCount first, and the exact strings above are part of the request.
- **Heartbeat:** the `mark_success` metadata gains a `funnel` key. `python -m shared.health` reads only `last_success_at` and `consecutive_errors`, and still passes.
- **Identity:** the `code_sha` stamped in saved signals changes with any new image. No code reads it. The strategy source closure changes (`signal_engine/main.py` is ACTIVE) without a decision change, so a version-boundary record is required (template [VERSION_BOUNDARY_TEMPLATE.md](../VERSION_BOUNDARY_TEMPLATE.md)).

## Evidence (local, 2026-11-01)

| Check | Result |
|---|---|
| `ea8ae4f` test suite on the pristine tree and on the `7ff582f` tree | 1064 passed / 847 skipped on both |
| Signal-engine funnel and selection tests on `7ff582f`, before-tree parity against `ea8ae4f`, on the host | 151 passed |
| The same tests **inside the deployed image** (disposable container, no network, read-only mounts) | 150 passed. One harness-only case is excluded: its child process loses the mounted pytest path |
| Branch full suite at `7b468be` with the repository-pinned CI venv (`.github/ci/requirements-test.txt`, aiohttp 3.14.3) | **4234 passed, 0 failed** |
| Branch full suite, local venv (aiohttp 3.13.5) | the only failure is `test_aiohttp_314_compat::test_version`, environmental; it passes 11/11 under the pinned venv |
| Disposable-PostgreSQL matrix at `7b468be` | 5080 passed, 64 skipped, 1 failed (the same environmental test); p1fix 18 and A39 10 passed |
| Branch full suite after the last SE-1 fix (`13704d4`) | 4297 passed, 1 failed (the same environmental test) |
| protected_scan | clean for every commit |

**Same-session pre-review** (NOT independent), and how each finding was resolved:
- Missing cap in this record: fixed here.
- Unmapped labels invalidating cycles: fixed in `13704d4` and released as `7ff582f`.
- Strict flag strings: documented above.
- Latency, heartbeat, `code_sha`, disk and queue: notes recorded above.

## Independent review (required before any operation)

The reviewer must be someone other than this Claude session (for example the owner's integrator). They should:
1. Review `git diff ea8ae4f 7ff582f` (six files) and [Dockerfile](Dockerfile).
2. Confirm or refute:
   - decisions, statements and messages are unchanged when funnel is on;
   - zero extra database statements;
   - bounded memory and disk under the cap;
   - fail-closed start-up;
   - the overlay paths and ownership.
3. Reproduce the evidence. Export `git archive 7ff582f`, set `WP2_BEFORE_TREE` to an export of `ea8ae4f`, and run `tests/test_funnel_records.py` and `tests/test_selection_rank_then_limit.py` from the feature branch against the export, excluding the scanner and analyzer cases, which are not in this release.
4. Record the verdict and any findings in this directory.

## Activation request (only after the review passes)

1. **Owner values:**
   - `FUNNEL_MAX_RECORDS_PER_DAY`: proposal 20000 (about 36 MB per day worst case);
   - the monitoring window: proposal 24 hours.
2. **Class B: release-image build.**
   - Export `git archive 7ff582f` to a clean directory, never the production checkout.
   - Verify the base tag resolves to `sha256:c5be4e34…`.
   - `docker build --network=none --pull=false --build-arg BASE_TAG=<verified tag> --build-arg SOURCE_COMMIT=7ff582fa43b4fd16042ccb6f71035e4031b67eac -t tsb-se1-signal_engine:7ff582f-r1 .`
   - Then verify the image file hashes against [services.json](services.json).
3. **Compose change** (reviewed-blob rule; integrated into `main` by the independent reviewer, then installed per COMPOSE_OPERATIONS.md):
   - signal_engine `image: tsb-se1-signal_engine:7ff582f-r1`, with rollback comment `tsb-a561-signal_engine:rel-ea8ae4f-r2`;
   - add `FUNNEL_RECORDING: "on"` and `FUNNEL_MAX_RECORDS_PER_DAY: "<value>"`.
4. **Class B: recreate of signal_engine only.**
   - Command: `docker compose -p trading-signal-bot -f docker-compose.yml up -d --no-deps --no-build --pull never --force-recreate signal_engine`.
   - Capture identity before and after (container ID, image ID, StartedAt, RestartCount, IPs).
   - Run two fresh health checks.
   - Check the PAPER_HALTED/B3 gate per COMPOSE_OPERATIONS.md.
5. **Version-boundary entry** for signal_engine at activation.

## Validation (owner-authorized read-only observation, 2026-11-01)

Observation scope: funnel rejection reasons, conservation counts, overflow and drop metrics, and service health only. No trade outcomes, no P&L, no protected or sealed evidence.

- **First 15 minutes:**
  - RestartCount is unchanged after start and there is no start-up refusal in the log;
  - the image ID is the new one;
  - health passes twice;
  - the heartbeat carries `funnel` health.
- **During the window:**
  - every `funnel.cycle` has `valid` true;
  - `unattributed`, `not_recorded`, `records_overflow`, evidence_v2 `dropped` and `errors` are 0 or explained;
  - `cap_reached` stays false or is explained;
  - the analyzer → signal_engine → telegram hand-off continues and the error rate is unchanged.

If no candidate cycles occur, the result is **insufficient runtime evidence**, not success.

**Accept** when every check above holds for the window. **Roll back** on a refusal or restart loop, a health failure, a non-zero drop, overflow or invalid cycle that cannot be explained, or any STOP condition.

## Rollback

Restore the signal_engine `image:` to `tsb-a561-signal_engine:rel-ea8ae4f-r2` and remove the two `FUNNEL_*` keys, through the same Compose path. Then repeat the Class B recreate of signal_engine only, and verify identity and health twice. Funnel events already written remain as evidence. No database change exists to undo.

**STOP rule:** anything unexpected (a hash, a diff, a container identity, a failed gate, a secret in output) means stop and return to the owner.
