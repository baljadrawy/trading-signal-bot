# WP2 Engineering Foundation Status (2026-11-01)

> **Status: documentation only.** This file records what the WP2 commits on branch `feature/wp2-foundation-20261101` deliver, measured against [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md). It covers iteration 1, up to `e12b53a`, and iteration 2, `f0c560d` to `263c94e` (section 7). **Merged, Deployed and Runtime-Validated are NO for every item.** Nothing is activated on Paper. Owner decisions are recorded in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) section 3; sections 1 and 5 refer to them. Independent review is **PENDING** ([WP2_INDEPENDENT_REVIEW_HANDOFF.md](WP2_INDEPENDENT_REVIEW_HANDOFF.md)). Fixing a defect is never evidence of profitability (`CH:L46`). Aliases follow [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) ("Source aliases"). Pack line citations refer to `5cd1a61`.

## 1. Scope and authorization

| Field | Value |
|---|---|
| Branch and base | `feature/wp2-foundation-20261101`, from `5cd1a61` (pack); HEAD `263c94e`; `main` `46578aa` unchanged |
| Commits, iteration 1 | `b981bfd` (pack reconciliation), `9668485` (lane A, R5), `24340b8` (lane C, R3), `716c5a8` (lanes B, R1 and R6), `d5c1539` (lane E, R7), `e12b53a` (this file) |
| Commits, iteration 2 | `f0c560d` and `a03efdd` (owner governance documents), `9588f45` (decisions, WP-B13), `62bd37f` (WP-F02), `9d00f88` (WP-C01, SE-84 proposal), `19b6bc4` (WP-D04), `08be803` (WP-D03), `9c0aecc` (WP-A01, `drift_check` identity), `1e68b07` (WP-E08), `af319bb` (WP-A04), `cf04a4a` (funnel and R1 integration in the signal path), `9bc6f2e` (tracker and telegram integration), `263c94e` (strategy-identity closure for the integrated modules). Section 7 lists what each delivers. All are pushed to the development branch without force (D0 standing push authorization, `DFP:L41`); there is no PR and no merge |
| Authorization, iteration 1 | Owner, development-only: new isolated deterministic modules, synthetic tests and documentation fixes |
| Gate WP2-START | **APPROVED, development-only**, by the owner on 2026-11-01 (DG-70; DECISIONS_AND_GATES.md section 3, entry DG-L03). The previous owner authorization covered the initial foundation work recorded in this file, and this approval continues the same safe-development scope. It does not unlock protected experiments, production operations, strategy activation or merging |
| Integrated development | owner decision of 2026-11-01, [WP2_INTEGRATED_DEVELOPMENT_DECISION_2026-11-01.md](../../governance/WP2_INTEGRATED_DEVELOPMENT_DECISION_2026-11-01.md) at `f0c560d` (entry DG-L04). Development targets the existing bot source. The "dormant only" and "no production import" rules are superseded for source integration only, never as permission to deploy or activate (L3, L36). Gates kept: shared-host and live Paper operations stay under `docs/ops/COMPOSE_OPERATIONS.md` Class B with operation-specific authorization, and only isolated, disposable development containers are outside it (L17-18); Paper activation needs its own owner, version and operations decision (L26); research restrictions, PAPER_ONLY and A29 D1/D2 stay binding (L22-24); hash-pinned research contracts and freeze records stay unchanged (L25) |
| Other owner decisions of 2026-11-01 | DG-69 (WP-A01) APPROVED FOR COMPLETION AND REVIEW; DG-71 (WP-OD-01) HOLD; DG-35 (SE-84) HOLD (section 5) |
| Not done | no deployment, merge, activation, restart, network or production-host action; no shared or production database; no protected data, backtest, simulation, optimisation or calibration. At every flag default, Paper decisions, signals, entries, exits, stops, targets, ranking, the candidate `LIMIT`, sizing and risk limits are byte-identical to the base (section 7.3) |
| Existing files changed | iteration 1: only `tests/experimental_modules.py`. Iteration 2, under DG-L04: `scanner/main.py`, `analyzer/main.py`, `analyzer/technical_analyzer.py`, `signal_engine/main.py` (`cf04a4a`); `trade_tracker/main.py`, `telegram/main.py` (`9bc6f2e`); `ops/provenance/drift_check.py`, report-only option (`9c0aecc`); the iteration-1 identity modules (`9c0aecc`, `263c94e`); the test registry. The only new `deploy/` file is `deploy/VERSION_BOUNDARY_TEMPLATE.md` (SOURCE_VERIFIED, `git diff --name-only`) |
| Unchanged | the nine hash-pinned files (WP-N02), `research/`, `database/`, `deploy/` apart from the new template, `docker-compose.yml`, `p2_forward/` and `shared/fees.py`. The freeze record blob is `62b2059b` (SOURCE_VERIFIED, `git diff --name-only 5cd1a61 263c94e`) |
| Experimental registry | still registered, so the isolation tests still forbid a production import: `strategy_config_snapshot`, `decision_metadata`, `signal_integrity_v2`. Left the registry because they are now wired: `strategy_identity` and `strategy_version_boundary` (imported by `drift_check`), `funnel_records` and `funnel_recorder` (through `shared/funnel_hooks.py`), `portfolio_ledger` and `position_state` (through the tracker shadows) |

**Anti-drift result (charter §7 item 7).** No DEVIATION ALERT. Nothing changes the objective, forces trades, narrows the universe to BTC, transfers another strategy's results, adds tuning, treats unrealized gains as cash or bypasses A29. `compounding_base` stays on realized net (`d5c1539`), and the ledger shadow never makes unrealized gains spendable (`9bc6f2e`). Every threshold, limit and bound in the new code is an explicit argument without a default. The non-legacy selection policy refuses to start until the owner declares its version and score key, so none is chosen (`cf04a4a`).

## 2. Task status, WP-A01 to WP-F07

Status values: DONE; PARTIAL (part of the task delivered, rest named); NOT STARTED; BLOCKED-<gate>. "Integrated" means wired into the existing service code on the development branch, behind a default that reproduces current behaviour; it never means merged, deployed or activated. Test counts are tests collected by pytest at `263c94e` (SOURCE_VERIFIED, local run; section 7.3).

| Task | R ref | Status | Commit | Files | Tests |
|---|---|---|---|---|---|
| WP-A01 interface specification and boundary template | R5.d, R1.d, R1.e | DONE, pending owner acceptance after review (DG-69). Closure classes ACTIVE, DORMANT and POTENTIAL. `macro_context` is ACTIVE for both families from the source call path. No boundary entry is created | `9c0aecc` | `docs/design/STRATEGY_INTERFACE_v1.md`, `deploy/VERSION_BOUNDARY_TEMPLATE.md` | — |
| WP-A02 StrategyVersion library and types | R5.d, R2.c | PARTIAL: identity hashing and config snapshot. The closure covers the integrated modules (`263c94e`): 45 files, 95 regions, ACTIVE 36 feed `source_hash`; the new OBSERVE_ONLY class (8 telemetry and shadow modules) is hashed into `inactive_hash`, never `source_hash`. The `config_hash` key schema is proposal-2, which closes the R5.d gap SI-04. Proposal for owner review (DG-69). Frozen glossary types not all delivered | `9668485`, `9c0aecc`, `263c94e` | `shared/strategy_identity.py`, `shared/strategy_config_snapshot.py` | `tests/test_wp2_strategy_identity.py`, 142 |
| WP-A03 contract hash v2 beside v1 | R5.d | PARTIAL: closure-based hash in substance. The v1 hash and `research/governance/research_freeze.json` are untouched. Planned `research/foundation/contract_v2.py` not created | `9668485`, `9c0aecc` | `shared/strategy_identity.py` | as above |
| WP-A04 golden replay harness | R5 | DONE. Determinism across two machines is NOT_VERIFIED (one machine) | `af319bb` | `tests/golden_replay.py`, `tests/golden_replay_fixtures.py`, `tests/fixtures/golden_replay/` | `tests/test_golden_replay.py`, 93 |
| WP-A05 DecisionRecord payload and chain | R5, R6 | PARTIAL: `DecisionMetadata`, `decision_id`, `record_hash`, boundary report; `activation_record_required` covers every identity-field change, including a label-only one. Evidence v2 registration remains a proposal; offline chain verifier not delivered | `9668485`, `9c0aecc` | `shared/decision_metadata.py`, `shared/strategy_version_boundary.py` | `tests/test_wp2_strategy_identity.py` |
| WP-A06 build-provenance refusal | R5.b | NOT STARTED. In scope under DG-L04 (existing Dockerfiles, `ops/provenance/build_preflight.py`); not attempted | — | — | — |
| WP-B01 RejectionRecord writer, taxonomy v1, conservation | R6.a, R6.c, R1.f | PARTIAL: library DONE; service hooks INTEGRATED behind `FUNNEL_RECORDING=off` in scanner F0–F2, analyzer F4, signal_engine F2–F6 (`cf04a4a`) and tracker/telegram F7 (`9bc6f2e`), at non-pinned call sites. Pinned-file hooks BLOCKED-DG-71 (HOLD) | `716c5a8`, `cf04a4a`, `9bc6f2e` | `shared/funnel_records.py`, `shared/funnel_recorder.py`, `shared/funnel_flags.py`, `shared/funnel_hooks.py` | `tests/test_wp2_funnel_observability.py` 68; `tests/test_funnel_records.py` 129 |
| WP-B02 per-key decision keys | R6.b | BLOCKED-DG-71 (HOLD; pinned `signal_engine/signal_logic.py`) | — | — | — |
| WP-B03 MarketSnapshot adapter | R6, R5 | NOT STARTED. The scanner records carry `snapshot_hash` "unavailable:wp-b03" until it exists | — | — | — |
| WP-B04 per-cycle DecisionRecord and `decide` | R6, R5 | PARTIAL: one `funnel.cycle` event per cycle with counters (`cf04a4a`). The `DecisionRecord` chain and `decide` are not delivered; they need WP-A05 and WP-B03 | `cf04a4a` | `shared/funnel_hooks.py` | as WP-B01 |
| WP-B05 rank-then-limit selection | R1.b, R1.d | DONE at non-pinned sites: `SELECTION_POLICY=legacy` by default, with the existing query literal pinned by hash and `SELECTION_LIMIT` 200. `rank_then_limit_v1` refuses to start without an owner-declared `SELECTION_VERSION` and `SELECTION_SCORE_KEY` (OF-OD-14, OQ-09). Activation is WP-G01 (R1.c). `SELECTION_VERSION` and `SELECTION_SCORE_KEY` enter `config_hash` under proposal-2 (`263c94e`) | `716c5a8`, `cf04a4a` | `shared/selection_policy.py`, `signal_engine/main.py` | `tests/test_selection_rank_then_limit.py` 21 |
| WP-B06 contract-score ranking slice | R1.e | BLOCKED-DG-29, DG-30 (OF-OD-14, OQ-09) | — | — | — |
| WP-B07 EligibilityResult rule set | R6.f | PARTIAL: `EligibilityResult` record type only. Rule set BLOCKED-DG-16 to DG-20 | `716c5a8` | `shared/funnel_records.py` | as WP-B01 |
| WP-B08 F2 and F5 feasibility slice | R6 | BLOCKED-DG-21 to DG-23; also needs WP-B03 (WP-D04 is now DONE) | — | — | — |
| WP-B09 single BTC trend slice | R6 | BLOCKED-DG-24 to DG-26 | — | — | — |
| WP-B10 failure semantics slice | R6.e, R3.c | BLOCKED-DG-25 and DG-71 (HOLD): the scanner BTC fail-open sits in a pinned file | — | — | — |
| WP-B11 closed-bar and freshness slice | R6.d | PARTIAL: freshness primitives with a required max age; analyzer F4 bar and data drops are now recorded (`cf04a4a`). The bound value is BLOCKED-DG-27 | `24340b8`, `cf04a4a` | `shared/signal_integrity_v2.py` | `tests/test_wp2_signal_integrity.py`, 139 |
| WP-B12 F7 hand-off slice | R6, R7 | PARTIAL: F7 record builders, and F7 records from the tracker and the delivery gate behind `FUNNEL_RECORDING` (`9bc6f2e`). The hand-off itself (rank-order offering, refusal semantics) is BLOCKED-DG-28, DG-32, DG-72 | `716c5a8`, `9bc6f2e` | `shared/funnel_records.py`, `shared/admission_capacity.py` | `tests/test_wp2_tracker_integration.py` |
| WP-B13 admission-change runbook draft | R6 | DONE as a DRAFT, not authorized for use; owner and independent review PENDING | `9588f45` | `docs/ops/PAPER_ADMISSION_CHANGE_RUNBOOK.md` | — |
| WP-C01 enforce-mode decomposition | R3.e | DONE (EB-0 to EB-4, five split options); owner review | `9d00f88` | `docs/design/SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md` | — |
| WP-C02 `setup_key` from StrategyVersion | R3.d | PARTIAL: candle and setup key, insert-once detection, fail-closed config parsing (`24340b8`); SE-84 proposal with 102 synthetic conflict cases (`9d00f88`). Key composition BLOCKED-DG-35 (HOLD); `shared/signal_integrity_v2.py` is not integrated | `24340b8`, `9d00f88` | `shared/signal_integrity_v2.py`, `docs/design/SETUP_KEY_PROPOSAL_SE84.md` | `tests/test_wp2_signal_integrity.py`; `tests/test_setup_key_proposal.py` 102 |
| WP-C03 R3 regression suite | R3.f | PARTIAL: synthetic regression tests; the disposable-database case is not delivered | `24340b8` | `tests/test_wp2_signal_integrity.py` | as WP-B11 |
| WP-C04 admission by `setup_key` | R3.b | BLOCKED-DG-35 (HOLD: no integration of a new `setup_key`) | — | — | — |
| WP-C05 no re-fire across a boundary | R3 | PARTIAL: `F4.bar_before_version_activation` in the freshness primitives; not wired to `shared/signal_identity.py` | `24340b8` | `shared/signal_integrity_v2.py` | as WP-B11 |
| WP-D01 strategy adapters (1.0.0) | R8, R2 | NOT STARTED | — | — | — |
| WP-D02 W3 invariants and options | R2.b | NOT STARTED. In scope under DG-L04 (existing `shared/t1_cap.py`); not attempted | — | — | — |
| WP-D03 pure position state machine | R4, R7 | DONE: 8 states, a 32-row transition table, stable refusal codes. INTEGRATED as a shadow, `POSITION_STATE_SHADOW=off` (`9bc6f2e`); enforce mode not built | `08be803`, `9bc6f2e` | `shared/position_state.py`, `shared/position_state_shadow.py` | `tests/test_position_state_machine.py`, 222 |
| WP-D04 cost-model registry | R4, R8.e | DONE: `legacy_tracker_v1` reproduces the runtime rule; `research_baseline_v1` and `research_stress_v1` are labelled PROPOSED_NOT_ADOPTED (adoption is DG-10). INTEGRATED: the tracker's fee, net, barrier and close costs go through `legacy_tracker_v1` (`9bc6f2e`). No flag value can select a research model | `19b6bc4`, `9bc6f2e` | `shared/cost_models.py` | `tests/test_cost_models.py`, 59 |
| WP-D05 OrderIntent rounding | R7 | NOT STARTED; needs WP-B03 | — | — | — |
| WP-D06 hypothesis specification drafts | R8.a to R8.c | BLOCKED-WP3 (DG-01 to DG-07) | — | — | — |
| WP-D07 horizon and HOLD-scope memos | R8.d, R8.g | NOT STARTED. Closes by reference to DG-01 and DG-14 on owner review | — | — | — |
| WP-E01 pure ledger library | R7.b | DONE (invariants as listed at `d5c1539`; quote-currency fee asset until DG-46). INTEGRATED through the ledger shadow (`9bc6f2e`) | `d5c1539`, `9bc6f2e` | `shared/portfolio_ledger.py` | `tests/test_wp2_portfolio_ledger.py`, 59 |
| WP-E02 legacy adapter and reconciliation | R7.b | DONE as a shadow: `LEDGER_SHADOW=off` reconciles ledger realized net with booked net per close, in logs and evidence only; never a decision or a database write | `9bc6f2e` | `shared/ledger_legacy_adapter.py` | `tests/test_wp2_accounting_components.py` 28; `tests/test_wp2_tracker_integration.py` 707 |
| WP-E03 disposable-database migration | R7.c | NOT STARTED. Persistence of the ledger and position state needs it | — | — | — |
| WP-E04 shadow ledger writer | R7.d | BLOCKED-DG-40, DG-41 (PR-OD1, PR-OD2); also needs WP-E03 | — | — | — |
| WP-E05 daily mark-to-market series | R7.e | BLOCKED-DG-45 and DG-01 | — | — | — |
| WP-E06 net-labelled counters | R7.f, R4.d | NOT STARTED. In scope under DG-L04; not attempted | — | — | — |
| WP-E07 single-count per-leg costs | R4.a, R4.e | DONE behind `PAPER_COST_LABEL_POLICY` (default `net_after_modeled_cost_v1`, the current label; alternative `net_single_count_legacy_v1`, economic columns only, risk guard unchanged). Activation is WP-G07 plus a version boundary | `9bc6f2e` | `shared/cost_label_policy.py`, `shared/accounting_flags.py` | as WP-E02 |
| WP-E08 capacity authority, legacy mode | R7, R6 | DONE in legacy mode: wraps `evaluate_new_trade`, returns its decision object unchanged and attributes one F7 code. INTEGRATED: the tracker pre-checks and risk decision route through it, and the delivery gate uses its legacy result (`9bc6f2e`). Target mode not built (PR-OD16, PR-OD21, WP-G23) | `1e68b07`, `9bc6f2e` | `shared/capacity_authority.py`, `shared/admission_capacity.py` | `tests/test_capacity_authority.py`, 161; tracker integration |
| WP-E09 side-by-side cost reporting | R4.c | NOT STARTED | — | — | — |
| WP-F01 runbook and CLAUDE.md corrections | R9.c | NOT STARTED; owner and independent review when done | — | — | — |
| WP-F02 learner build-hazard design | R9.d | DONE (design; the image choice is owner decision LB-OD-1); `docker-compose.yml` unchanged | `62bd37f` | `docs/ops/LEARNER_BUILD_HAZARD_DESIGN.md` | — |
| WP-F03 static guards | R9.d2 | NOT STARTED; test design T2-1 to T2-7 and G-1 to G-10 is in WP-F02 | — | — | — |
| WP-F04 collector health-tiering port | R9.a2 | NOT STARTED. Edits `p2_forward/`, which stayed unchanged | — | — | — |
| WP-F05 health fields in the observation record | R9.f | NOT STARTED. `drift_check` gained only the strategy-identity mode (`9c0aecc`) | — | — | — |
| WP-F06 historical marker for the Compose backup | R9.g | NOT STARTED | — | — | — |
| WP-F07 record notes | R5.e, R5.g, R5.h | NOT STARTED; the R5.e part also needs DG-63 | — | — | — |

**Counts at `263c94e`.** DONE 12, PARTIAL 11, BLOCKED 9, NOT STARTED 15; total 47. At `e12b53a` they were DONE 1, PARTIAL 11, BLOCKED 9, NOT STARTED 26. `b981bfd` and the decision-recording part of `9588f45` are pack documentation, not workplan tasks. The default-off R4.b slice behind `PAPER_BREAK_EVEN_POLICY` (`9bc6f2e`) belongs to gated item WP-G06 and has no task row.

## 3. Acceptance-gate matrix

The ten gates are those of the owner's WP2 development-only authorization, applied to every code change: 1 tests show correct behaviour on synthetic inputs; 2 existing default behaviour unchanged; 3 no change to strategy selection, signals, stops, targets or sizing at the default; 4 no protected-data access; 5 no new backtest, simulation, optimisation or calibration; 6 no production-runtime change; 7 A29 / D1 / D2 HOLD unchanged; 8 relevant repository checks pass; 9 protected_scan clean; 10 evidence and commit references recorded. Workplan section 2.4 criteria are covered by the same evidence. Its independent-review criterion is not one of the ten and stays **PENDING for every commit**, because a same-session review is not independent ([WP2_INDEPENDENT_REVIEW_HANDOFF.md](WP2_INDEPENDENT_REVIEW_HANDOFF.md)).

| Commit | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| `b981bfd` docs | N/A | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `9668485` lane A | PASS: 125 at the time | PASS: no production caller | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `24340b8` lane C | PASS: 139 | PASS: no production caller | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `716c5a8` lane B | PASS: 68 | PASS: no caller; 25-seed parity | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `d5c1539` lane E | PASS: 59 | PASS: no production caller | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `9588f45`, `62bd37f` docs | N/A | PASS | PASS | PASS | PASS | PASS | PASS | PASS: self-check clean | PASS | PASS |
| `9d00f88` WP-C01, SE-84 | PASS: 102 | PASS: no production file changed | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `19b6bc4` WP-D04 | PASS: 59 | PASS: no caller at that commit | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `08be803` WP-D03 | PASS: 222 | PASS: registered experimental at that commit | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `9c0aecc` WP-A01 | PASS: 137 and 11 | PASS: iteration-1 hashes pinned; `drift_check` output and exit codes unchanged without the new option | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `1e68b07` WP-E08 | PASS: 161 | PASS: no service import at that commit; mirrors byte-identical | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `af319bb` WP-A04 | PASS: 93 | PASS: test harness only | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |
| `cf04a4a` signal path | PASS: 150, of which 58 opt-in | PASS: identical database traces, saved signals and heartbeats with recording off and on (scanner and signal_engine 25 seeds, analyzer 8), and off against the `af319bb` sources | PASS at the defaults; the non-legacy selection refuses without owner declarations | PASS | PASS | PASS: nothing deployed | PASS | PASS (section 7.3) | PASS | PASS |
| `9bc6f2e` tracker, telegram | PASS: 707 and 28 | PASS: database call logs and decisions byte-identical against the `af319bb` sources on 160 risk, 120 admission, 200 exit and close, and 200 delivery-gate cases, at the defaults and with every shadow on | PASS at the defaults; R4.a/e and R4.b alternatives behind flags, not activated | PASS | PASS | PASS: nothing deployed | PASS | PASS; database matrix 4518 passed (section 7.3) | PASS | PASS |
| `263c94e` closure | PASS: 142 | PASS: identity metadata only; no service behaviour | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

The owner documents `f0c560d` and `a03efdd` are governance records and are not assessed here.

Evidence behind the rows:
- **Gates 3 and 6:** the hash-pinned files, `research/`, `database/`, `docker-compose.yml`, `p2_forward/` and `shared/fees.py` are unchanged, and `deploy/` gained only the template. The changed service files are those of section 1. Every new behaviour sits behind a flag whose default reproduces current behaviour, and an unknown value refuses at start-up (DFP:L87; section 7.2).
- **Gate 5:** the tests use synthetic fixtures only. Seeded parity tests are determinism checks on generated inputs, not market simulations.
- **Gate 7:** `docs/governance/` changed only by the owner's own decision `f0c560d`; `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md` is untouched.
- **Hash pins:** the hash-pinned files (WP-N02) and the freeze record are untouched (blob `62b2059b`).

## 4. Remediation status R1–R9

Runtime status is unchanged for every item, because nothing was deployed or activated. Development-branch progress is SOURCE_VERIFIED at the commits named, with local test runs. Merged, Deployed and Runtime-Validated are NO for every item.

| Item | Runtime status (class) | Development-branch progress |
|---|---|---|
| R1 | OPEN (SOURCE_VERIFIED) | rank-loss records and the shadow legacy cut (`716c5a8`); `rank_then_limit_v1` integrated behind `SELECTION_POLICY=legacy` (`cf04a4a`). Activation R1.c is WP-G01 and needs DG-29, DG-30 and DG-31 |
| R2 | OPEN at runtime; PARTIALLY_FIXED on `main` only (SOURCE_VERIFIED; VER-05 RUNTIME_VERIFIED) | none in WP2 (WP-D02 not started) |
| R3 | OPEN at runtime; PARTIALLY_FIXED in source, enforce mode off (SOURCE_VERIFIED; VER-02 RUNTIME_VERIFIED) | identity, duplicate and freshness primitives (`24340b8`, not integrated); enforce-mode decomposition (`9d00f88`); the SE-84 proposal waits on DG-35 (HOLD) |
| R4 | OPEN (SOURCE_VERIFIED) | cost-model registry (`19b6bc4`) integrated at the legacy model; R4.a/e behind `PAPER_COST_LABEL_POLICY` and R4.b behind `PAPER_BREAK_EVEN_POLICY`, both at the legacy default (`9bc6f2e`). Activation is WP-G06 and WP-G07, each with a version boundary |
| R5 | image content NOT_VERIFIED; identity OPEN (DOCUMENTED_ONLY) | interface specification and boundary template (`9c0aecc`); ACTIVE closure, extended to the integrated modules with the OBSERVE_ONLY class and `config_hash` proposal-2 (`263c94e`), and a report-only `drift_check` strategy mode, which reports DRIFT on both families at `9bc6f2e` because ACTIVE regions changed. A version-boundary record is required before any deployment; none is created |
| R6 | OPEN (SOURCE_VERIFIED) | funnel records integrated in scanner, analyzer, signal_engine, tracker and delivery gate behind `FUNNEL_RECORDING=off` (`cf04a4a`, `9bc6f2e`). Pinned-file reasons wait on DG-71. Enabling the writers on the host is WP-G19 |
| R7 | OPEN (SOURCE_VERIFIED) | ledger and position-state shadows and the legacy capacity authority integrated, all default off or legacy (`9bc6f2e`). No persistence (WP-E03, WP-E04); target-mode capacity is WP-G23 |
| R8 | NOT_VERIFIED; ERG-01 **INCONCLUSIVE** preserved (INFERRED) | research cost models registered as PROPOSED_NOT_ADOPTED (`19b6bc4`); WP3 not started |
| R9 | OPEN (RUNTIME_VERIFIED 2026-10-31; DOCUMENTED_ONLY) | learner build-hazard design (`62bd37f`); the Compose change waits on LB-OD-1 and WP-G33 |

## 5. Owner decisions and remaining blockers

As of 2026-11-01 (DECISIONS_AND_GATES.md section 3, DG-L03), four decisions have an owner status: DG-70 APPROVED, development-only; DG-69 APPROVED FOR COMPLETION AND REVIEW; DG-35 and DG-71 HOLD. The other 68 stay OPEN. The 72 rows are grouped in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md), section 1.0:
- safe development-only code: 26;
- a strategy-behaviour change: 6;
- portfolio-risk activation: 17;
- protected research: 16;
- deployment: 7.

**The step-1 decisions:**

| Decision | Status | What it means now |
|---|---|---|
| DG-70, WP2-START | APPROVED, development-only | Iteration 2 was carried out under it, in the existing bot source (DG-L04). Each behaviour-changing integration sits behind a flag that defaults to current behaviour and fails closed on an unknown value (DFP:L87). Not unlocked: protected experiments, production operations, strategy activation, merging |
| DG-69, review of WP-A01 | APPROVED FOR COMPLETION AND REVIEW | WP-A01 is delivered (`9c0aecc`). **Still needed:** the owner's acceptance after review, which makes the closure and decision-key lists final |
| `shared/macro_context.py` in the strategy source closure | owner instruction recorded with DG-69 | classified ACTIVE for both families, from the live-path call in `signal_engine/signal_logic.py` (`9c0aecc`); macro gating unchanged |
| DG-71, WP-OD-01 | HOLD | **Still needed:** a decision. Until then no hash-pinned file is modified |
| DG-35, SE-84 | HOLD | the proposal and 102 conflict cases are delivered (`9d00f88`). **Still needed:** a decision before any `setup_key` composition or integration |

**Remaining blockers of the development line, at `263c94e`:**

| Blocker | What waits | Gate |
|---|---|---|
| DG-71 HOLD | WP-B02; WP-B10; the pinned-file hooks of WP-B01 and WP-B05 (per-timeframe gate reasons, `F4.regime_not_accepted` against `no_setup`, the scanner BTC fail-open) | owner decision WP-OD-01 |
| DG-35 HOLD | `setup_key` composition (WP-C02) and admission by key (WP-C04) | owner decision SE-84 |
| Activation gates | WP-G01 (R1.c selection), WP-G06 (R4.b break-even), WP-G07 (R4.a/e Paper accounting), WP-G19 (funnel writers on the host), WP-G23 (target-mode capacity). Each needs its DG decisions, an owner-declared window, a version-boundary record and a Class B operation; WP-G17 also needs the reviewed runbook | DG-68 and the rows each item names (IMPLEMENTATION_WORKPLAN.md section 6) |
| Persistence | the ledger and position-state shadows write logs and evidence only. A persistent ledger needs WP-E03 (disposable-database migration) and WP-E04 (shadow writer, DG-40, DG-41) | WP-E03 needs a disposable database; WP-E04 is blocked on DG-40, DG-41 |
| LB-OD-1 | the learner image choice of WP-F02, then WP-F03 and the install WP-G33 | owner decision LB-OD-1; WP-G33 named approval |
| Version-boundary record | `drift_check` reports strategy-identity DRIFT on both families at `9bc6f2e`. A boundary record is required before any deployment of this code, and none is created | owner-approved activation (SE-36; `deploy/VERSION_BOUNDARY_TEMPLATE.md`) |
| Independent review | every iteration-1 and iteration-2 commit | an authorized independent reviewer ([WP2_INDEPENDENT_REVIEW_HANDOFF.md](WP2_INDEPENDENT_REVIEW_HANDOFF.md)) |

The other 22 group-1 rows stay OPEN and gate one named slice each (DECISIONS_AND_GATES.md section 1.1). Group 2 to 5 rows are needed only before activation, protected research or deployment.

## 6. Next-phase options for the owner

These are options, not recommendations to approve; none implies a profitability claim, and each keeps its own gate.

| Option | Content | Trade-off |
|---|---|---|
| (a) Review and hold | an independent review of both iterations on the pushed branch, with the handoff file; merging stays an owner decision per PR (`DFP:L41`) | no further code until the review; nothing is lost |
| (b) Continue doable development | WP-A06, WP-B03, WP-D01, WP-D02, WP-D05, WP-E06; the documentation tasks WP-D07, WP-E09, WP-F01, WP-F06, WP-F07 | progress without new decisions; each change still needs its default-parity tests |
| (c) Decide the remaining step-1 gates | DG-71 (pinned files) and DG-35 (`setup_key`); acceptance of WP-A01 after review (DG-69); LB-OD-1 | unlocks the pinned-file slices, key composition and the learner design; each decision is the owner's alone |
| (d) Start the WP3 research track in parallel | DG-01 and DG-02 (section 2.3 of DECISIONS_AND_GATES.md) | independent of WP2 code; no evaluation is authorized by it |

Integration into `main`, any deployment and any Paper activation remain owner decisions outside this file.

## 7. Iteration 2 (2026-11-01)

Iteration 2 ran under DG-70 and the integrated-development decision (DG-L04): improvements are wired into the existing service code paths, and every behaviour change sits behind a default that reproduces current behaviour. The commit messages (`git log e12b53a..263c94e`) are the implementers' own statements; this section summarises them and the evidence recorded for them (SOURCE_VERIFIED as text and local runs; not independently reviewed).

### 7.1 Commits

| Commit | Task | Delivers |
|---|---|---|
| `f0c560d`, `a03efdd` | owner | the integrated-development decision and its `CLAUDE.md` entry point |
| `9588f45` | decisions, WP-B13 | DG-L03 and DG-L04; the DRAFT admission-change runbook |
| `62bd37f` | WP-F02 | learner and optimizer build-hazard design; proposed Compose diff not applied; owner decision LB-OD-1 |
| `9d00f88` | WP-C01, SE-84 | enforce-mode decomposition EB-0 to EB-4; `setup_key` proposal A versus B with finding SK-09 (a label-only version bump re-keys every setup under A); 102 synthetic conflict cases. DG-35 stays HOLD |
| `19b6bc4` | WP-D04 | cost-model registry: `legacy_tracker_v1`, and the research models as PROPOSED_NOT_ADOPTED; double counting refused |
| `08be803` | WP-D03 | pure position state machine, 32 transition rows, stable refusal codes |
| `9c0aecc` | WP-A01, R5 | interface specification, boundary template, ACTIVE/DORMANT/POTENTIAL closure, report-only `drift_check` strategy mode |
| `1e68b07` | WP-E08 | legacy capacity authority adapter with F7 attribution; byte-identical mirrors of the delivery gate and the tracker pre-check |
| `af319bb` | WP-A04 | golden synthetic replay harness with pinned golden files |
| `cf04a4a` | WP-B01, WP-B05 | funnel recording in scanner, analyzer and signal_engine; `SELECTION_POLICY` |
| `9bc6f2e` | WP-E08, WP-D04, WP-E02, WP-D03, WP-E07, R4.b | capacity authority, cost model, ledger and position-state shadows, R4 flags and F7 records in the tracker and telegram |
| `263c94e` | WP-A01, WP-A02, R5.d | closure for the integrated modules: 45 files, 95 regions, ACTIVE 36; OBSERVE_ONLY class (funnel and shadow modules) in `inactive_hash` only; `config_hash` key schema proposal-2 with the selection and R4 policies; proposal for owner review |

### 7.2 Flags introduced

Every flag is read from the environment, and an unknown value refuses at start-up. None is set in `docker-compose.yml`, which is unchanged.

| Flag | Default (current behaviour) | Alternative | Activation gate |
|---|---|---|---|
| `FUNNEL_RECORDING` (`shared/funnel_flags.py`) | `off` | `on`, which also requires `EVIDENCE_V2_ENABLED=true`; a recorder or store failure never changes a decision | WP-G19, DG-34 |
| `SELECTION_POLICY` (`shared/selection_policy.py`) | `legacy` | `rank_then_limit_v1`, which refuses without owner-declared `SELECTION_VERSION` and `SELECTION_SCORE_KEY` | WP-G01; DG-29, DG-30, DG-31 |
| `PAPER_COST_LABEL_POLICY` (`shared/accounting_flags.py`) | `net_after_modeled_cost_v1` | `net_single_count_legacy_v1` (economic columns only; risk guard unchanged) | WP-G07; DG-37 |
| `PAPER_BREAK_EVEN_POLICY` | `legacy_tracker_v1` | `single_count_legacy_v1` (a derived round-trip cost passed into the unchanged pinned code) | WP-G06; DG-37 |
| `LEDGER_SHADOW` | `off` | `on`: reconciliation in logs and evidence only | WP-G28 for any persistent ledger (WP-E03, WP-E04) |
| `POSITION_STATE_SHADOW` | `off` | `on`: transition validation, refusals recorded | enforce mode not built; a version boundary before any enforce use |

### 7.3 Verification evidence

All runs are local, in the minimal environment with umask 022 (SOURCE_VERIFIED as local runs, not CI). No run used a shared or production database, the network or protected data.

| Run | Tree | Result |
|---|---|---|
| Default no-database suite | working tree before `cf04a4a` and `9bc6f2e` | 3676 passed, 906 skipped, 1 failed |
| Disposable isolated PostgreSQL matrix (a PostgreSQL 16 container bound to loopback, tmpfs storage, removed afterwards) | `af319bb` | 3691 passed, 5 skipped, 1 failed; `test_p1fix` with the pre-fix tree 18 passed; A39 with the production tree 10 passed |
| Disposable isolated PostgreSQL matrix | `9bc6f2e` | full suite with databases 4518 passed, 63 skipped (58 of them the opt-in funnel parity cases), 1 failed; `test_p1fix` with the pre-fix tree 18 passed; A39 with the production tree 10 passed |
| Default no-database suite | `cf04a4a` alone | 2941 passed, 906 skipped; the aiohttp test deselected |
| Default no-database suite | clean worktree at `263c94e` (main agent) | 3681 passed, 906 skipped, 1 failed (`test_aiohttp_314_compat::test_version`, environmental) |
| WP2 test files plus `tests/test_risk_management.py` and `tests/test_paper_observe_capacity.py`, indicative | same working tree | 2217 passed, 58 skipped; the 58 are the opt-in before-tree cases |
| The opt-in before-tree cases (`WP2_BEFORE_TREE` set to an export of the `af319bb` service and `shared/` sources), indicative | same working tree | `tests/test_funnel_records.py` and `tests/test_selection_rank_then_limit.py`: 150 passed |
| `protected_scan` | every commit | clean |

**The one failure** is `tests/test_aiohttp_314_compat.py::test_version` in every run. It is ENVIRONMENTAL: the local virtual environment has aiohttp 3.13.5, while the test and the CI pin (`.github/ci/requirements-test.txt:L2`) expect 3.14.3. It is not a repository defect, and no pin was changed. Separately, the analyzer, signal_engine, optimizer and claude_review requirement files still pin aiohttp 3.13.5. That predates WP2 and is out of scope.

### 7.4 Status by category

The integrated-development decision requires these six states to be reported separately; none implies the next (the decision file at `f0c560d`, L13). "Integrated" means wired into existing service code on the development branch.

| Component | Implemented | Integrated | Tested | Merged | Deployed | Runtime-Validated |
|---|---|---|---|---|---|---|
| Funnel records, recorder and hooks (WP-B01) | yes | yes: scanner, analyzer, signal_engine, tracker, delivery gate; `FUNNEL_RECORDING=off`; pinned hooks no (DG-71) | yes | NO | NO | NO |
| Selection policy (WP-B05) | yes | yes: signal_engine, `SELECTION_POLICY=legacy` | yes | NO | NO | NO |
| Capacity authority, legacy mode (WP-E08) | yes | yes: tracker and delivery gate | yes | NO | NO | NO |
| Cost-model registry (WP-D04) | yes | yes: tracker at `legacy_tracker_v1`; research models not selectable | yes | NO | NO | NO |
| R4.a/e cost labels (WP-E07), R4.b break-even (WP-G06 slice) | yes | yes: tracker, legacy defaults | yes | NO | NO | NO |
| Ledger library and legacy adapter (WP-E01, WP-E02) | yes | yes: tracker shadow, `LEDGER_SHADOW=off`; no persistence | yes | NO | NO | NO |
| Position state machine (WP-D03) | yes | yes: tracker shadow, `POSITION_STATE_SHADOW=off`; enforce mode not built | yes | NO | NO | NO |
| Strategy identity and version boundary (WP-A01 to WP-A03, R5) | yes | yes: report-only `drift_check strategy` mode; no service import | yes | NO | NO | NO |
| Golden replay harness (WP-A04) | yes | not applicable (test harness) | yes | NO | NO | NO |
| Signal integrity v2, config snapshot, decision metadata | yes | no (still registered experimental) | yes | NO | NO | NO |
| `setup_key` proposal (SE-84) | proposal only | no (DG-35 HOLD) | yes: 102 synthetic cases | NO | NO | NO |
| Documents: WP-A01 spec and template, WP-B13, WP-C01, WP-F02 | yes | not applicable | self-check and scan | NO | NO | NO |

### 7.5 Known differences and gaps

The implementers recorded these in their commit messages. They are listed with the review questions in [WP2_INDEPENDENT_REVIEW_HANDOFF.md](WP2_INDEPENDENT_REVIEW_HANDOFF.md) section 4:
- funnel labels `open_trade_exists` and the learned-gate labels have no taxonomy-v1 mapping, and they mark the cycle invalid when recording is on;
- a non-legacy `SELECTION_VERSION` was not in `config_hash` at `cf04a4a`; proposal-2 (`263c94e`) closes this gap (SI-04);
- the capacity mirrors take the pause state and open counts as inputs; non-capacity SQL filters, collation and equal-time ties are not mirrored; one-open-per-symbol maps to `F7.exposure_symbol` by inference;
- the position state machine differs from legacy on the T1/T3 tranche merge, a zero-size T1, three uncovered legacy rules and the fill-time risk refusal;
- determinism of the golden replay across two machines is NOT_VERIFIED;
- `drift_check` reports strategy-identity DRIFT on both families at `9bc6f2e`, so a version-boundary record is required before any deployment;
- the closure of `263c94e` is a proposal for owner review (DG-69); the OBSERVE_ONLY classification rests on the claim that those modules only log or record inside try/except and cannot change a decision.
