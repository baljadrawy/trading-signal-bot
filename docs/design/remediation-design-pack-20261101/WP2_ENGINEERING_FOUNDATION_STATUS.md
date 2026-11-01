# WP2 Engineering Foundation Status (2026-11-01)

> **Status: documentation only.** This file records what the WP2 engineering-foundation commits on branch `feature/wp2-foundation-20261101` deliver, measured against [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md). Nothing here is deployed, merged, activated or approved, and no owner decision is recorded. Fixing a defect is never evidence of profitability (`CH:L46`). Aliases follow [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) ("Source aliases"). Pack line citations refer to `5cd1a61`.

## 1. Scope and authorization

| Field | Value |
|---|---|
| Branch and base | `feature/wp2-foundation-20261101`, from `5cd1a61` (pack); `main` `46578aa` unchanged |
| Commits | `b981bfd` (pack reconciliation), `9668485` (lane A, R5), `24340b8` (lane C, R3), `716c5a8` (lanes B, R1 and R6), `d5c1539` (lane E, R7), then the commit adding this file. Pushed to the development branch without force (D0 standing push authorization, `DFP:L41`); no PR, no merge |
| Authorization | Owner, development-only: new isolated deterministic modules, synthetic tests and documentation fixes |
| Not done | no deployment, merge, activation, restart, database, container, network or production-host action; no protected data, backtest, simulation, optimisation or calibration; no change to Paper decisions, signals, entries, exits, stops, targets, ranking, the candidate `LIMIT`, sizing or risk limits |
| Isolation | the eight new modules are registered in `tests/experimental_modules.py`, so the existing isolation tests forbid any production import. No existing production, configuration, deploy, research or `p2_forward` file changed; the only existing file touched is that test registry (SOURCE_VERIFIED, `git diff --name-only 5cd1a61 HEAD`) |
| Gate WP2-START | the workplan's gate (DG-70) is still **OPEN** in the pack: the development-only authorization of this phase is not recorded there as the WP2-START decision |

**Anti-drift result (charter §7 item 7).** No DEVIATION ALERT. Nothing changes the objective, forces trades, narrows the universe to BTC, transfers another strategy's results, adds tuning, treats unrealized gains as cash (`d5c1539` keeps `compounding_base` on realized net only) or bypasses A29. Every threshold, limit and bound in the new code is an explicit argument without a default; none is chosen.

## 2. Task status, WP-A01 to WP-F07

Status values: DONE; PARTIAL (part of the task delivered, rest named); NOT STARTED; BLOCKED-<gate>. "Doable next" means a Safe development-only or Documentation/design task that needs no owner gate beyond WP2-START; "edits existing file" means the planned files include an existing repository file, which this phase did not allow. Test counts are tests collected and passed by pytest (SOURCE_VERIFIED, local run).

| Task | R ref | Status | Commit | Files | Tests |
|---|---|---|---|---|---|
| WP-A01 interface specification and boundary template | R5.d, R1.d, R1.e | NOT STARTED. Doable next (documentation); acceptance needs owner review (DG-69). `b981bfd` only aligned the pack | — | — | — |
| WP-A02 StrategyVersion library and types | R5.d, R2.c | PARTIAL: StrategyVersion hashing (five identity fields, `lineage` as metadata), config snapshot. Frozen glossary types not all delivered; closure and decision-key lists await the WP-A01 review | `9668485` | `shared/strategy_identity.py`, `shared/strategy_config_snapshot.py` | `tests/test_wp2_strategy_identity.py`, 125 |
| WP-A03 contract hash v2 beside v1 | R5.d | PARTIAL: closure-based hash in substance; v1 hash and `research/governance/research_freeze.json` untouched (blob `62b2059b`). Planned `research/foundation/contract_v2.py` not created; closure list awaits WP-A01. The extra closure file `shared/macro_context.py` (SE-06) needs owner confirmation | `9668485` | `shared/strategy_identity.py` | as above |
| WP-A04 golden replay harness | R5 | NOT STARTED. Doable next | — | — | — |
| WP-A05 DecisionRecord payload and chain | R5, R6 | PARTIAL: `DecisionMetadata`, replay-stable `decision_id`, `record_hash`; boundary report (R5.e). Not delivered: evidence v2 payload registration (edits existing `shared/evidence_v2.py`), offline chain verifier | `9668485` | `shared/decision_metadata.py`, `shared/strategy_version_boundary.py` | as above |
| WP-A06 build-provenance refusal | R5.b | NOT STARTED. Edits existing files (Dockerfiles, `ops/provenance/build_preflight.py`) | — | — | — |
| WP-B01 RejectionRecord writer, taxonomy v1, conservation | R6.a, R6.c, R1.f | PARTIAL: library DONE (schema, taxonomy v1, conservation, default-off recorder; a 25-seed test shows identical outcomes with the recorder off, disabled and enabled). Service hooks and the config flag BLOCKED-WP2-START, and WP-OD-01 for the pinned files | `716c5a8` | `shared/funnel_records.py`, `shared/funnel_recorder.py` | `tests/test_wp2_funnel_observability.py`, 68 |
| WP-B02 per-key decision keys | R6.b | BLOCKED-WP-OD-01 (pinned `signal_engine/signal_logic.py`) | — | — | — |
| WP-B03 MarketSnapshot adapter | R6, R5 | NOT STARTED. Library part doable next; the hook edits existing `scanner/main.py` | — | — | — |
| WP-B04 per-cycle DecisionRecord and `decide` | R6, R5 | NOT STARTED. Needs WP-A05, WP-B01, WP-B03 | — | — | — |
| WP-B05 rank-then-limit selection | R1.b, R1.d | PARTIAL: record side only (`F6.rank_below_cap`, `F6.resource_cap`, shadow `F6.legacy_alphabetical_cut`). The selection function is NOT STARTED; changing `LIMIT 200` or ranking is R1.c (WP-G01) | `716c5a8` | `shared/funnel_records.py` | as WP-B01 |
| WP-B06 contract-score ranking slice | R1.e | BLOCKED-DG-29, DG-30 (OF-OD-14, OQ-09) | — | — | — |
| WP-B07 EligibilityResult rule set | R6.f | PARTIAL: `EligibilityResult` record type only. Rule set BLOCKED-DG-16 to DG-20 (OF-OD-01 to OF-OD-05, OQ-07) | `716c5a8` | `shared/funnel_records.py` | as WP-B01 |
| WP-B08 F2 and F5 feasibility slice | R6 | BLOCKED-DG-21 to DG-23 (OF-OD-06 to OF-OD-08); also needs WP-B03, WP-D04 | — | — | — |
| WP-B09 single BTC trend slice | R6 | BLOCKED-DG-24 to DG-26 (OF-OD-09 to OF-OD-11) | — | — | — |
| WP-B10 failure semantics slice | R6.e, R3.c | BLOCKED-DG-25 (OF-OD-10), WP-OD-01 | — | — | — |
| WP-B11 closed-bar and freshness slice | R6.d | PARTIAL: freshness primitives with a required max age (`F4.bar_not_closed`, `F4.bar_stale`, `F4.data_quality`). The bound value is BLOCKED-DG-27 (OF-OD-12); venue-synchronised bar construction not delivered | `24340b8` | `shared/signal_integrity_v2.py` | `tests/test_wp2_signal_integrity.py`, 139 |
| WP-B12 F7 hand-off slice | R6, R7 | PARTIAL: F7 record builders, with `F7.capacity_full` kept separate from rank loss. The hand-off itself BLOCKED-DG-28, DG-32, DG-72 (OF-OD-13, OF-OD-16, WP-OD-02); needs WP-E08 | `716c5a8` | `shared/funnel_records.py` | as WP-B01 |
| WP-B13 admission-change runbook draft | R6 | NOT STARTED. Doable next (documentation; owner and independent review) | — | — | — |
| WP-C01 enforce-mode decomposition | R3.e | NOT STARTED. Doable next (documentation) | — | — | — |
| WP-C02 `setup_key` from StrategyVersion | R3.d | PARTIAL: candle key, setup key with a 64-hex `rule_hash`, insert-once duplicate and conflict detection (`F4.duplicate_setup`, `F4.setup_conflict`), fail-closed config parsing mapped to the A44 `integrity_mode`. Key composition BLOCKED-SE-84 (DG-35) | `24340b8` | `shared/signal_integrity_v2.py` | as WP-B11 |
| WP-C03 R3 regression suite | R3.f | PARTIAL: synthetic regression tests. The disposable-database case is not delivered | `24340b8` | `tests/test_wp2_signal_integrity.py` | as WP-B11 |
| WP-C04 admission by `setup_key` | R3.b | BLOCKED-WP2-START: the hook edits existing `trade_tracker/main.py`. The commit names WP-OD-01, but that file is not one of the nine pinned files (WP-N02) | — | — | — |
| WP-C05 no re-fire across a boundary | R3 | PARTIAL: `F4.bar_before_version_activation` in the freshness primitives; not wired to `shared/signal_identity.py` | `24340b8` | `shared/signal_integrity_v2.py` | as WP-B11 |
| WP-D01 strategy adapters (1.0.0) | R8, R2 | NOT STARTED. Doable next (new module) | — | — | — |
| WP-D02 W3 invariants and options | R2.b | NOT STARTED. Edits existing `shared/t1_cap.py` | — | — | — |
| WP-D03 pure position state machine | R4, R7 | NOT STARTED. Doable next (new module) | — | — | — |
| WP-D04 cost-model registry | R4, R8.e | NOT STARTED. Doable next (new module) | — | — | — |
| WP-D05 OrderIntent rounding | R7 | NOT STARTED. Edits existing `shared/exchange_rules.py`; needs WP-B03 | — | — | — |
| WP-D06 hypothesis specification drafts | R8.a to R8.c | BLOCKED-WP3 (DG-01 to DG-07) | — | — | — |
| WP-D07 horizon and HOLD-scope memos | R8.d, R8.g | NOT STARTED. Closes by reference to DG-01 and DG-14 on owner review | — | — | — |
| WP-E01 pure ledger library | R7.b | DONE: invariants PR-I1 to PR-I6, PR-I9, PR-I10, PR-I14; PR-I7 idempotency; PR-I8 hash chain; available = cash − reserved; unrealized never spendable; `compounding_base` on realized net only (S1–S4); `apply_derisking`; loss-streak parity with `shared/risk_epoch.py`. Quote-currency fee asset until PR-OD8 (DG-46). PR-I11 and PR-I13 belong to WP-E07 and WP-E02 | `d5c1539` | `shared/portfolio_ledger.py` | `tests/test_wp2_portfolio_ledger.py`, 59 |
| WP-E02 legacy adapter and reconciliation | R7.b | NOT STARTED. Needs WP-D04 | — | — | — |
| WP-E03 disposable-database migration | R7.c | NOT STARTED. Needs a disposable PostgreSQL, which this phase excludes | — | — | — |
| WP-E04 shadow ledger writer | R7.d | BLOCKED-DG-40, DG-41 (PR-OD1, PR-OD2) | — | — | — |
| WP-E05 daily mark-to-market series | R7.e | BLOCKED-DG-45 and DG-01 (PR-OD6; WP3 endpoint) | — | — | — |
| WP-E06 net-labelled counters | R7.f, R4.d | NOT STARTED. Edits existing `trade_tracker/main.py`, `telegram/main.py` | — | — | — |
| WP-E07 single-count per-leg costs | R4.a, R4.e | NOT STARTED. Needs WP-D04 | — | — | — |
| WP-E08 capacity authority, legacy mode | R7, R6 | NOT STARTED. Doable next (new module wrapping `evaluate_new_trade`) | — | — | — |
| WP-E09 side-by-side cost reporting | R4.c | NOT STARTED. Doable next (documentation) | — | — | — |
| WP-F01 runbook and CLAUDE.md corrections | R9.c | NOT STARTED. Edits existing production-operation documents; owner and independent review | — | — | — |
| WP-F02 learner build-hazard design | R9.d | NOT STARTED. Doable next (documentation) | — | — | — |
| WP-F03 static guards | R9.d2 | NOT STARTED. Needs WP-F01, WP-F02 | — | — | — |
| WP-F04 collector health-tiering port | R9.a2 | NOT STARTED. Edits `p2_forward/`, excluded in this phase | — | — | — |
| WP-F05 health fields in the observation record | R9.f | NOT STARTED. Edits existing `ops/provenance/drift_check.py` (wiring also named as blocked by `9668485`) | — | — | — |
| WP-F06 historical marker for the Compose backup | R9.g | NOT STARTED. Doable next (documentation) | — | — | — |
| WP-F07 record notes | R5.e, R5.g, R5.h | NOT STARTED. Doable next (documentation); the R5.e part also needs DG-63 | — | — | — |

**Counts.** DONE 1, PARTIAL 11, BLOCKED 9, NOT STARTED 26; total 47. `b981bfd` is pack documentation and is not a workplan task.

## 3. Acceptance-gate matrix

The ten gates are those of the owner's WP2 development-only authorization (section 10, applied to every code change). Workplan section 2.4 criteria are covered by the same evidence. Its independent-review criterion is not one of the ten and stays PENDING for every code commit, because a same-session review is not independent.

| Gate | `b981bfd` | `9668485` | `24340b8` | `716c5a8` | `d5c1539` |
|---|---|---|---|---|---|
| 1. Tests show correct behaviour on synthetic inputs | N/A (docs) | PASS: 125 | PASS: 139 | PASS: 68 | PASS: 59 |
| 2. Existing default behaviour unchanged | PASS | PASS: no production caller | PASS: no production caller | PASS: no caller; recorder default-off, 25-seed parity | PASS: no production caller |
| 3. No change to strategy selection, signals, stops, targets or sizing | PASS | PASS | PASS | PASS | PASS |
| 4. No protected-data access | PASS | PASS | PASS | PASS | PASS |
| 5. No new backtest, simulation, optimisation or calibration | PASS | PASS | PASS | PASS | PASS |
| 6. No production-runtime change | PASS | PASS | PASS | PASS | PASS |
| 7. A29 / D1 / D2 HOLD unchanged | PASS | PASS | PASS | PASS | PASS |
| 8. Relevant repository checks pass | PASS | PASS | PASS | PASS | PASS |
| 9. protected_scan clean | PASS | PASS | PASS | PASS | PASS |
| 10. Evidence and commit references recorded | PASS: this file | PASS | PASS | PASS | PASS |

Evidence behind the rows:
- **Gates 3 and 6:** no file under `analyzer/`, `scanner/`, `signal_engine/`, `telegram/`, `trade_tracker/`, `database/`, `deploy/`, `p2_forward/`, `research/` or any `docker-compose*` file changed in base..HEAD. The only existing code-side file changed is the test registry `tests/experimental_modules.py`.
- **Gate 2:** all eight new modules are registered there, so the existing A42, A43, A47 and A48 isolation tests fail if any non-test file imports them.
- **Gate 5:** the tests use synthetic fixtures only. The 25-seed funnel test is a determinism check on generated records, not a market simulation.
- **Gate 7:** `docs/governance/` and `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md` are untouched.
- **Gate 8:** the one exception is the pre-existing environment failure below, and the database matrix was not run (see below).
- **Hash pins:** the hash-pinned files (WP-N02) and the freeze record are untouched (blob `62b2059b`).

**Suite evidence** (local, minimal environment, umask 022; SOURCE_VERIFIED as a local run, not CI):
- default no-database suite: 2189 passed, 848 skipped, 1 failed. The failure, `tests/test_aiohttp_314_compat.py::test_version`, is an environment version mismatch that also fails at the base, where 1798 passed;
- collector suite `p2_forward/tests`: 466 passed, 1 skipped;
- static parity inventory: rc 2 with the CI assertions holding (21 blockers, as expected);
- protected scan clean for each commit and for base..HEAD.

The disposable-PostgreSQL matrix was not run, because it needs containers. Its impact is INFERRED to be none, since no database-touching file changed. Gate 7 stays open: a same-session review is not independent.

## 4. Remediation status R1–R9

Runtime status is unchanged for every item, because nothing was deployed or activated. Development-branch progress is SOURCE_VERIFIED at the commits named, with local test runs.

| Item | Runtime status (class) | Development-branch progress |
|---|---|---|
| R1 | OPEN (SOURCE_VERIFIED) | records for rank loss and the shadow legacy cut (`716c5a8`); the selection change R1.c is not started |
| R2 | OPEN at runtime; PARTIALLY_FIXED on `main` only (SOURCE_VERIFIED; VER-05 RUNTIME_VERIFIED) | none in WP2 |
| R3 | OPEN at runtime; PARTIALLY_FIXED in source, enforce mode off (SOURCE_VERIFIED; VER-02 RUNTIME_VERIFIED) | dormant candle and setup identity, duplicate and conflict detection, freshness primitives (`24340b8`); key composition waits for SE-84 |
| R4 | OPEN (SOURCE_VERIFIED) | none (cost models WP-D04 and WP-E07 not started) |
| R5 | image content NOT_VERIFIED; identity OPEN (DOCUMENTED_ONLY) | StrategyVersion hashing, config snapshot, decision metadata and boundary report (`9668485`); the closure list waits for the WP-A01 review. This `config_hash` is distinct from the evidence v2 `config_hash` |
| R6 | OPEN (SOURCE_VERIFIED) | `RejectionRecord` schema, taxonomy v1 and conservation (`716c5a8`); no service writes records |
| R7 | OPEN (SOURCE_VERIFIED) | pure ledger with invariants and realized-net compounding base (`d5c1539`); no runtime ledger |
| R8 | NOT_VERIFIED; ERG-01 **INCONCLUSIVE** preserved (INFERRED) | none; WP3 not started |
| R9 | OPEN (RUNTIME_VERIFIED 2026-10-31; DOCUMENTED_ONLY) | none |

## 5. Remaining owner decisions, by when they are needed

All 72 decisions (DG-01 to DG-72) stay OPEN. Their grouping is in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md), section 1.0:
- safe development-only code: 26;
- a strategy-behaviour change: 6;
- portfolio-risk activation: 17;
- protected research: 16;
- deployment: 7.

**Needed before the next development step:**

| Decision | Why it is needed now |
|---|---|
| DG-70, WP2-START | recording it (or an explicit statement that the development-only authorization stands in for it) opens the tasks that edit existing files under a flag: WP-A06, WP-B03 hook, WP-B01 hooks, WP-C04, WP-E06 |
| DG-69, review of WP-A01 | the WP-A01 specification fixes the source-closure and decision-key lists that `9668485` leaves open |
| DG-71, WP-OD-01 | edits to the nine hash-pinned files: the pinned hooks of WP-B01, WP-B02, WP-B05 and WP-B10 |
| DG-35, SE-84 | `setup_key` composition for WP-C02 and the chain to WP-B05 |
| `shared/macro_context.py` in the strategy source closure | an owner confirmation within the WP-A01 review (SE-06, SE-37); not a separate DG row |

The other group-1 rows gate one named slice each (DECISIONS_AND_GATES.md section 1.1). Group 2 to 5 rows are needed only before activation, protected research or deployment.

## 6. Next-phase options for the owner

These are options, not recommendations to approve; none implies a profitability claim, and each keeps its own gate.

| Option | Content | Trade-off |
|---|---|---|
| (a) Review and hold | review the five commits and this file on the pushed branch; merging stays an owner decision per PR (`DFP:L41`) | no further code until the review; nothing is lost |
| (b) Continue doable safe-dev tasks | WP-A04, WP-D01, WP-D03, WP-D04, WP-E08 and the library part of WP-B03 (new modules only), plus the documentation tasks WP-A01, WP-B13, WP-C01, WP-E09, WP-F02, WP-F06, WP-F07 | progress without new decisions; WP-A01 still needs owner review before the closure lists are final |
| (c) Decide the step-1 gates first | DG-70, DG-69, DG-71, DG-35 and the `macro_context` question | unlocks the hooks and pinned-file slices; each decision is the owner's alone |
| (d) Start the WP3 research track in parallel | DG-01 and DG-02 (section 2.3 of DECISIONS_AND_GATES.md) | independent of WP2 code; no evaluation is authorized by it |

Integration into `main` remains an owner decision outside this file.
