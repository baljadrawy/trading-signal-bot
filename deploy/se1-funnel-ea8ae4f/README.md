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
  - Its 54 `.py` files, `/app/Dockerfile` and `requirements.txt` (56 files) hash-match `ea8ae4f` (corrected after R2) (checked in a disposable, no-network container started from that image ID).
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

## Independent review status

- **Round 1 (2026-11-01).** Three independent-context reviewers on different models, none external, each returned CONDITIONAL GO. The reports and the consolidation are in [docs/reviews/se1-external/](../../docs/reviews/se1-external/CONSOLIDATION_ROUND1.md).
- **The candidate is unchanged** at `7ff582f`: the conditions below are procedural only.
- **Not external:** an external reviewer can repeat the audit from [REVIEW_PACKAGE.md](../../docs/reviews/se1-external/REVIEW_PACKAGE.md).
- **Errata from the review:** the image holds 54 `.py` files plus `/app/Dockerfile` plus `requirements.txt`, and all 56 match `ea8ae4f` (R2). The earlier figure of "55 Python files" was wrong. The strategy-id test cannot run on the release export and is deselected there (R1-06).

## Version boundary: owner declaration required (R2-01)

- **The source changes but the label does not.** The overlay keeps `APP_VERSION=sb-2026.08`, while the strategy `source_hash` changes because `signal_engine/main.py` is ACTIVE. The template classes a changed hash under the same label as UNDECLARED, which means STOP.
- **`APP_VERSION` must NOT change.** It is the `strategy_version` stamped on signals and an input to setup identity, so changing it would re-key setups.
- **Proposed classification** for the owner to declare: an **observe-only PATCH boundary** on signal_engine, with no decision-logic change, supported by the parity evidence above.
- **Boundary entry fields:**
  - service `signal_engine`;
  - image before `sha256:c5be4e34…` and image after (the built ID);
  - source before `ea8ae4f` and source after `7ff582f`;
  - `APP_VERSION` unchanged;
  - activation minute (UTC), recorded at the recreate;
  - flags `FUNNEL_RECORDING=on` and `FUNNEL_MAX_RECORDS_PER_DAY=20000`;
  - `SELECTION_POLICY`, `SELECTION_VERSION` and `SELECTION_SCORE_KEY` **absent and forbidden** (R1-01);
  - evidence: this record plus the review.

## Activation request (only after the owner declares the boundary and approves each Class B step)

Owner-selected values: `FUNNEL_RECORDING=on`, `FUNNEL_MAX_RECORDS_PER_DAY=20000`, monitoring window 24 hours.

- **About the cap (R3-B1):** it bounds records per **process** per UTC day. Each restart resets it, so the restart count must stay 0 (see Acceptance).

1. **Build (Class B).**
   - Refuse if the tag `tsb-se1-signal_engine:7ff582f-r1` already exists.
   - Export `git archive 7ff582f` to a clean directory, never the production checkout.
   - Build with [Dockerfile](Dockerfile), whose base is pinned by digest. Use exactly the command in its header: `--network=none --pull=false`, with `SOURCE_COMMIT` set to the full SHA.
2. **Post-build gates.** Any failure means STOP and remove the new tag.
   - Layers: 26 in total, with `RootFS.Layers[0..23]` equal to the base's 24 layers.
   - Configuration: `User` (appuser), `Cmd`, `WorkingDir` (/app) and `Env` are unchanged from the base. The label `org.opencontainers.image.revision` equals `7ff582fa43b4fd16042ccb6f71035e4031b67eac`.
   - Content: `ops/provenance/runtime_manifest.py generate` with [services.json](services.json) reports **match 61, dormant 2, assembled 0, unknown 0** (R2-06).
   - Dry run (R2-07, R1-03): a disposable `docker run --rm --network none --read-only` from the new image, with exactly `FUNNEL_RECORDING=on`, `FUNNEL_MAX_RECORDS_PER_DAY=20000`, `EVIDENCE_V2_ENABLED=true` and no `SELECTION_*` keys. It must call `funnel_recording_config()` and `selection_policy_from_env()` and import `shared.funnel_hooks` without error.
3. **Compose change** (reviewed-blob rule).
   - In the signal_engine block: `image: tsb-se1-signal_engine:7ff582f-r1` (rollback comment: blob `d1a4b197…`, image `rel-ea8ae4f-r2`), and add `FUNNEL_RECORDING: "on"` and `FUNNEL_MAX_RECORDS_PER_DAY: "20000"`.
   - No `SELECTION_*` keys.
   - The independent reviewer integrates it into `main`; it is then installed in the production checkout per COMPOSE_OPERATIONS.md.
4. **Pre-recreate captures (read-only).**
   - Identity of all running containers: ID, image ID, StartedAt, RestartCount, config-hash, IPs. The current signal_engine config-hash is `20dcae19…`.
   - **B3/PAPER_HALTED gate (R2-03).** Read before and after the recreate; the results must be identical. This follows the precedent `deploy/paper-observe-bb7825f/IMAGES.md`. Run inside `BEGIN READ ONLY` on the trading database. Explicit columns only; no outcome columns. This read needs owner approval as part of the request.
     - Q1, the latest explicit pause/resume decision (the same predicate as `shared/trading_state.py:26-33`):
       `SELECT id, is_trading_paused, pause_reason, (date IS NULL OR date > CURRENT_DATE) AS date_invalid FROM risk_management WHERE is_trading_paused = true OR pause_reason = 'manual_resume' ORDER BY date DESC NULLS FIRST, id DESC LIMIT 1;`
     - Q2, the halt notices:
       `SELECT count(*) FROM outbox_events WHERE event_type = 'risk.halted';`
   - Record the collector as the expected pre-state: it is currently unhealthy, in a separate project, and must not trigger a STOP.
5. **Recreate (Class B), signal_engine only.** `docker compose -p trading-signal-bot -f docker-compose.yml up -d --no-deps --no-build --pull never --force-recreate signal_engine`
6. **Boundary entry** written with the activation minute.

## Acceptance (owner-authorized read-only observation scope only)

Scope: funnel reasons, conservation, overflow/drop metrics and health. No trade outcomes and no P&L.

1. **Health is not taken from the old heartbeat (R2-02).**
   - The first health read counts only at least 180 s after the new StartedAt, and the two reads are at least 60 s apart.
   - One read-only `service_heartbeats` read shows `last_started_at` and `last_success_at` later than the new StartedAt, and the metadata carries `funnel`.
2. **Restarts and image (R3-B1).**
   - RestartCount stays 0 for the whole window, with no start-up refusal in the log.
   - The container `.Image` equals the built ID.
   - The other containers' identity is unchanged.
3. **Every `funnel.cycle` envelope in the window (R3-B3) has:**
   - `valid` true;
   - `observation_complete` true;
   - `integration_failures` empty;
   - no `notes.gate_block`.
4. **Counters at zero, or explained in the record:**
   - `not_recorded` is a hard 0 (R3-B2);
   - `records_overflow`;
   - `unattributed`;
   - evidence_v2 `dropped` and `errors`;
   - `cap_reached`.
5. **Envelopes and hand-off.**
   - The envelope count matches the expected cycles.
   - F-stage reason counts reconcile with the existing `cycle.outcome` decision histogram, within the observation scope.
   - The analyzer → signal_engine → telegram hand-off continues.
6. **An idle window** (no candidate cycles) is **insufficient runtime evidence**, not success.

**Roll back** on any refusal, restart, health failure, gate failure, non-zero `not_recorded`, an unexplained drop, overflow or invalid envelope, or any STOP condition.

**What the 24-hour window does not establish** (R3, D): cap behaviour, restart behaviour, queue saturation, rare labels, or count accuracy against ground truth.

## Rollback (pre-approved as part of the same authorization; R2-04)

- **Target:** the current reviewed Compose blob `d1a4b197…`, already integrated. It gives image `tsb-a561-signal_engine:rel-ea8ae4f-r2` (`sha256:c5be4e34…`), no `FUNNEL_*` keys, and expected config-hash `20dcae19…`, valid only if `.env` is unchanged.
- **Command:** restore that blob in the production checkout per COMPOSE_OPERATIONS.md, then run the same Class B recreate of signal_engine only. Verify identity, the B3 gate and health as above.
- **Not a valid SE-1 rollback:** `tsb-p1d-signal_engine` (`80096a98…`). It would also revert later releases, and its schema compatibility is unverified.
- Funnel events already written remain as evidence. No database change exists to undo.

## Post-deploy provenance (R2-09)

- Archive the new image with SHA256SUMS, following the precedent.
- Update `deploy/DEPLOYED.json` and add an IMAGES record, through review.
- Follow the per-update backup governance (CLAUDE.md, R1.3).
- Record that the source is the unmerged release branch `release/se1-funnel-ea8ae4f` at `7ff582f`.

**STOP rule:** anything unexpected (a hash, a diff, a container identity, a failed gate, a secret in output) means stop and return to the owner.
