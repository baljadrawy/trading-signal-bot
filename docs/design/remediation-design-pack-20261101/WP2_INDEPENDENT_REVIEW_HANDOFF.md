# WP2 Independent Review Handoff (2026-11-01)

> **Independent review: PENDING.** No authorized independent reviewer was available in the session that produced WP2 iterations 1 and 2. Work by agents of the same session is not independent, so no WP2 commit has an independent review. This file hands the review over. It authorizes nothing: the reviewer reviews and reports, and does not deploy, merge or activate (section 6). Delivery status is in [WP2_ENGINEERING_FOUNDATION_STATUS.md](WP2_ENGINEERING_FOUNDATION_STATUS.md): Merged, Deployed and Runtime-Validated are NO for every item. Fixing a defect is never evidence of profitability (`CH:L46`).

## Document control

| Field | Value |
|---|---|
| This file | `WP2_INDEPENDENT_REVIEW_HANDOFF.md`, documentation only |
| Branch | `feature/wp2-foundation-20261101`, HEAD `263c94e`; `main` `46578aa` unchanged |
| Review range | iteration 1: `5cd1a61..e12b53a`; iteration 2: `e12b53a..263c94e`. The owner commits `f0c560d` and `a03efdd` are governance records, not review objects |
| Why review is required | independent review is required for deployable service code and for production-operations definitions (DFP:L73). The owner-approved workflow has committed GitHub changes reviewed independently (DFP:L18; OOC:L16). The workplan's acceptance criterion 7 asks for it (IMPLEMENTATION_WORKPLAN.md section 2.4) |
| Governing records | [charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md), [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md), [Development-First Policy](../../governance/DEVELOPMENT_FIRST_POLICY.md), [WP2 integrated development decision](../../governance/WP2_INTEGRATED_DEVELOPMENT_DECISION_2026-11-01.md), [COMPOSE_OPERATIONS.md](../../ops/COMPOSE_OPERATIONS.md); owner decisions in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) section 3 (DG-L03, DG-L04) |
| Aliases | `CH`, `OOC` and `DFP` as in [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) ("Source aliases"), all `@ 46578aa` |
| Evidence classes | the implementers' claims below are DOCUMENTED_ONLY (commit messages) until the reviewer reproduces them; test results are SOURCE_VERIFIED local runs, not CI |

## 1. Scope

**Priority 1: the four foundation modules.** Review these first; every integration builds on them.

| Module | Commit(s) | Tests | Role |
|---|---|---|---|
| `shared/portfolio_ledger.py` | `d5c1539` | `tests/test_wp2_portfolio_ledger.py` | pure ledger: invariants PR-I1 to PR-I10, PR-I14, idempotency, hash chain, realized-net `compounding_base` |
| `shared/strategy_identity.py` | `9668485`, `9c0aecc`, `263c94e` | `tests/test_wp2_strategy_identity.py`, `tests/test_drift_check_strategy_identity.py` | `StrategyVersion` hashing; closure classes ACTIVE, DORMANT, POTENTIAL and OBSERVE_ONLY; only ACTIVE regions feed `source_hash`, OBSERVE_ONLY ones feed `inactive_hash` |
| `shared/signal_integrity_v2.py` | `24340b8` | `tests/test_wp2_signal_integrity.py` | candle and setup identity, insert-once duplicate and conflict detection, freshness primitives. Not integrated (still in `tests/experimental_modules.py`) |
| `shared/funnel_records.py` | `716c5a8` | `tests/test_wp2_funnel_observability.py`, `tests/test_funnel_records.py` | `RejectionRecord` schema, taxonomy v1, conservation |

**Priority 2: the other WP2 modules.**

| Module | Commit(s) | Tests |
|---|---|---|
| `shared/strategy_config_snapshot.py`, `shared/decision_metadata.py`, `shared/strategy_version_boundary.py` | `9668485`, `9c0aecc`, `263c94e` | `tests/test_wp2_strategy_identity.py` |
| `shared/funnel_recorder.py`, `shared/funnel_flags.py`, `shared/funnel_hooks.py` | `716c5a8`, `cf04a4a` | `tests/test_wp2_funnel_observability.py`, `tests/test_funnel_records.py` |
| `shared/selection_policy.py` | `cf04a4a` | `tests/test_selection_rank_then_limit.py` |
| `shared/cost_models.py` | `19b6bc4` | `tests/test_cost_models.py` |
| `shared/position_state.py` | `08be803` | `tests/test_position_state_machine.py` |
| `shared/capacity_authority.py` | `1e68b07` | `tests/test_capacity_authority.py` |
| `shared/accounting_flags.py`, `shared/admission_capacity.py`, `shared/cost_label_policy.py`, `shared/ledger_legacy_adapter.py`, `shared/position_state_shadow.py` | `9bc6f2e` | `tests/test_wp2_tracker_integration.py`, `tests/test_wp2_accounting_components.py` |
| `ops/provenance/drift_check.py` (report-only `strategy` mode) | `9c0aecc` | `tests/test_drift_check_strategy_identity.py` |
| test harnesses `tests/golden_replay.py`, `tests/golden_replay_fixtures.py`, `tests/funnel_service_harness.py`, `tests/wp2_service_fakes.py`, golden files in `tests/fixtures/golden_replay/` | `af319bb`, `cf04a4a`, `9bc6f2e` | `tests/test_golden_replay.py` and the integration tests |

**Priority 3: the service integrations.** These are deployable service code (DFP:L73).

| File | Commit | What changed |
|---|---|---|
| `scanner/main.py` | `cf04a4a` | F0–F2 funnel tap around the pinned scanner logic |
| `analyzer/main.py`, `analyzer/technical_analyzer.py` | `cf04a4a` | F4 bar and data-drop records |
| `signal_engine/main.py` | `cf04a4a` | F3 macro veto, F2/F4/F5 per symbol, F6 records; `SELECTION_POLICY` selection |
| `trade_tracker/main.py` | `9bc6f2e` | capacity routing, cost model, R4 flags, ledger and position-state shadows, F7 records |
| `telegram/main.py` | `9bc6f2e` | delivery gate through the capacity authority's legacy result; F7 refusal records |

**Priority 4: documents.** `docs/design/STRATEGY_INTERFACE_v1.md` and `deploy/VERSION_BOUNDARY_TEMPLATE.md` (WP-A01), `docs/design/SETUP_KEY_PROPOSAL_SE84.md` and `docs/design/SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md` (`9d00f88`), `docs/ops/LEARNER_BUILD_HAZARD_DESIGN.md` (`62bd37f`), `docs/ops/PAPER_ADMISSION_CHANGE_RUNBOOK.md` (`9588f45`, a production-operations definition), and the pack files changed in both iterations.

**Out of scope.** The nine hash-pinned files (WP-N02), `research/`, `database/`, `docker-compose.yml`, `p2_forward/` and `shared/fees.py` are unchanged in the range. Confirm that with `git diff --name-only 5cd1a61 263c94e`, then do not review them as changes.

## 2. Review questions

**For every module and integration**, answer the seven questions below and record the evidence:
1. **Correctness.** Does the code do what its docstring and the cited pack clause say, including edge cases (empty inputs, zero, NaN, negative values, missing keys)?
2. **Accounting invariants.** Is every cost charged exactly once? Can unrealized gains ever become spendable or raise sizing? Does realized net equal the booked net under the legacy model?
3. **Determinism.** Is output independent of input order, dictionary order, `PYTHONHASHSEED`, clock, environment and locale or collation? Are ties broken by a declared key?
4. **State-transition safety.** Can an illegal transition, an overfill, an over-exit or a terminal-state exit be reached? Do refusals carry a stable code?
5. **Version identity.** Does every behaviour-relevant input enter `source_hash` or `config_hash`? Does a label-only change require an activation record?
6. **Hidden runtime effects.** At the default, does the change add any database query, outbox event, log line that a consumer parses, exception path, import-time side effect or latency on the decision path?
7. **Integration risks.** Can a recorder, store or shadow failure change a decision? Does an unknown flag value refuse before any I/O? Do mirrors stay in parity with the real functions?

**Module-specific questions:**

| Module | Questions |
|---|---|
| `portfolio_ledger` | Do PR-I1 to PR-I10 and PR-I14 hold under every event order the fold accepts? Is `available = cash − reserved` never negative without a refusal? Is the hash chain sensitive to every field? Is the loss-streak parity with `shared/risk_epoch.py` exact? |
| `strategy_identity` | Is the classification of the 45 files and 95 regions (ACTIVE 36) correct from actual call paths (`263c94e`)? Is `shared/macro_context.py` correctly ACTIVE (the `should_block_now()` call in `signal_engine/signal_logic.py`)? Is `shared/strategy_math.py` correctly POTENTIAL? Can any of the 8 OBSERVE_ONLY modules change a decision, for example through an exception that escapes its try/except, so that it belongs in `source_hash`? Does `config_hash` proposal-2 contain every decision-relevant key, with `SELECTION_VERSION` and `SELECTION_SCORE_KEY` required under `rank_then_limit_v1`? |
| `signal_integrity_v2` | Are candle and setup keys collision-free and canonical? Is insert-once conflict detection correct across timeframes? Does the freshness check refuse with no default bound? |
| `funnel_records` | Does conservation hold for every stage (in = passed + recorded drops)? Are `F6.rank_below_cap` and `F7.capacity_full` never conflated? Are compacted universe-level records lossless for counts? |
| `selection_policy` | Is the legacy query literal byte-identical (pinned by hash)? Does `rank_then_limit_v1` record every cut row and use the declared `tie_break_key`, not name or timeframe order? |
| `cost_models` | Does `legacy_tracker_v1` reproduce the tracker exactly (fee once per trade on configured notional; stop fill at reference times one minus `STOP_SLIPPAGE`)? Are the research models unreachable from any flag? |
| `position_state` | Is the 32-row table complete and consistent with SE B6? Are the extension rows X-01 to X-08 justified? |
| `capacity_authority`, `admission_capacity` | Is the legacy decision object returned unchanged? Is the F7 precedence the legacy precedence? Is the raise on re-derivation mismatch safe in production paths? |
| `cost_label_policy`, `ledger_legacy_adapter`, `position_state_shadow` | Do the alternatives touch only economic columns, never the risk guard? Can a shadow raise into the tracker loop? Are shadow outputs kept out of decisions and database writes? |
| `drift_check` | Without the new option, are output and exit codes unchanged and is `shared/` not imported? |
| service files | At every default, are the database calls (SQL and arguments, in order), outbox events, saved signals, heartbeats and decisions identical to `af319bb`? |

## 3. Claims to verify, and how to reproduce

### 3.1 Default-off and byte-identical claims

Each claim is the implementers' own (DOCUMENTED_ONLY) until the reviewer reproduces it.

| # | Claim | Commit | Test that asserts it |
|---|---|---|---|
| C1 | `FUNNEL_RECORDING` defaults to `off`; an unknown value refuses at start-up; `on` requires `EVIDENCE_V2_ENABLED=true`; a recorder or store failure never changes a decision | `cf04a4a` | `tests/test_funnel_records.py` |
| C2 | With recording off and on, the real `main()` loops give identical database traces, saved signals and heartbeats (scanner and signal_engine 25 seeds, analyzer 8). With recording off, they are identical to the `af319bb` sources | `cf04a4a` | `tests/test_funnel_records.py`; the before-tree cases are opt-in (section 3.2) |
| C3 | `SELECTION_POLICY=legacy` issues exactly the existing query literal (pinned by SHA-256) with `SELECTION_LIMIT` 200; the non-legacy policy refuses without owner-declared `SELECTION_VERSION` and `SELECTION_SCORE_KEY` | `cf04a4a` | `tests/test_selection_rank_then_limit.py` |
| C4 | At every default, and with every shadow on, tracker and telegram database call logs, outbox events and decisions are byte-identical to the `af319bb` sources on 160 risk, 120 admission, 200 exit and close, and 200 delivery-gate cases | `9bc6f2e` | `tests/test_wp2_tracker_integration.py`, which loads the `af319bb` sources from git |
| C5 | Unknown values of `PAPER_COST_LABEL_POLICY`, `PAPER_BREAK_EVEN_POLICY`, `LEDGER_SHADOW` and `POSITION_STATE_SHADOW` refuse at start-up; invalid cost configuration refuses; no flag value selects a research cost model | `9bc6f2e` | `tests/test_wp2_tracker_integration.py`, `tests/test_wp2_accounting_components.py` |
| C6 | The capacity authority returns the legacy decision object unchanged and raises if its re-derivation differs; the mirrors of the delivery gate, tracker pre-check and admission query are byte-identical to the real functions | `1e68b07` | `tests/test_capacity_authority.py`; `tests/test_risk_management.py` and `tests/test_paper_observe_capacity.py` stay green |
| C7 | `legacy_tracker_v1` reproduces `shared/fees.py` and the tracker call-site surface; double counting is refused | `19b6bc4` | `tests/test_cost_models.py` |
| C8 | Iteration-1 identity hashes are unchanged by the closure classification of `9c0aecc`; `263c94e` hashes OBSERVE_ONLY modules into `inactive_hash` only; `drift_check` without the new option behaves as before and does not import `shared/` | `9c0aecc`, `263c94e` | `tests/test_wp2_strategy_identity.py`, `tests/test_drift_check_strategy_identity.py` |
| C9 | The golden replay is reproducible across `PYTHONHASHSEED` values and detects a changed fixture output; tests never rewrite golden files | `af319bb` | `tests/test_golden_replay.py` |
| C10 | The nine hash-pinned files, `research/foundation/contract.py`, `research/governance/research_freeze.json` (blob `62b2059b`), `database/`, `docker-compose.yml`, `p2_forward/` and `shared/fees.py` are unchanged | all | `git diff --name-only 5cd1a61 263c94e` on those paths; `git rev-parse 263c94e:research/governance/research_freeze.json` |
| C11 | Modules still registered in `tests/experimental_modules.py` (`strategy_config_snapshot`, `decision_metadata`, `signal_integrity_v2`) have no production importer | all | the existing A42, A43, A47 and A48 isolation tests |

### 3.2 Commands

Use a clean checkout of `263c94e` with full history (the integration tests read `af319bb` from git), on a machine that is not the production host. Use a Python 3.12 virtual environment with the pinned test set of `.github/ci/requirements-test.txt`, here written `<python>`. The local runs used aiohttp 3.13.5, which makes `tests/test_aiohttp_314_compat.py::test_version` fail; with the pinned set, that test should pass.

Minimal environment, default no-database suite:

```
umask 022
env -i PATH=/usr/bin:/bin HOME="$(mktemp -d)" PYTHONDONTWRITEBYTECODE=1 <python> -m pytest tests -q -p no:cacheprovider
```

The WP2 tests only:

```
env -i PATH=/usr/bin:/bin HOME="$(mktemp -d)" PYTHONDONTWRITEBYTECODE=1 <python> -m pytest -q -p no:cacheprovider \
  tests/test_wp2_portfolio_ledger.py tests/test_wp2_strategy_identity.py tests/test_wp2_signal_integrity.py \
  tests/test_wp2_funnel_observability.py tests/test_funnel_records.py tests/test_selection_rank_then_limit.py \
  tests/test_cost_models.py tests/test_position_state_machine.py tests/test_capacity_authority.py \
  tests/test_golden_replay.py tests/test_drift_check_strategy_identity.py tests/test_setup_key_proposal.py \
  tests/test_wp2_tracker_integration.py tests/test_wp2_accounting_components.py \
  tests/test_risk_management.py tests/test_paper_observe_capacity.py
```

The opt-in before-tree parity cases of C2 need an export of the `af319bb` sources:

```
BEFORE="$(mktemp -d)"
git archive af319bb scanner analyzer signal_engine shared | tar -x -C "$BEFORE"
env -i PATH=/usr/bin:/bin HOME="$(mktemp -d)" PYTHONDONTWRITEBYTECODE=1 WP2_BEFORE_TREE="$BEFORE" <python> -m pytest -q -p no:cacheprovider \
  tests/test_funnel_records.py tests/test_selection_rank_then_limit.py
```

The read-only strategy-identity report, which reads files only and uses no Docker:

```
<python> ops/provenance/drift_check.py strategy
```

**Disposable PostgreSQL matrix, in words.** Follow the `disposable-PostgreSQL matrix` job of `.github/workflows/tests.yml`:
1. Start a fresh PostgreSQL 16 container that publishes its port on loopback only, keeps its data on tmpfs and uses a throwaway credential generated for this run. Never use a shared or production database.
2. Create the read-only reference trees that the job names (`f973cac`, `da256f7`, `5929730`, and the A38 branch where present).
3. Build the schema template with `.github/ci/build_schema_template.sh`.
4. Run the full suite with the database variables of that job pointing at the container and the reference trees. Deselect the one `test_p1fix` case that the job deselects.
5. Run `tests/test_p1fix_evidence_reliability.py` with the pre-fix tree, then `tests/test_a39_review.py` with the production tree.
6. Remove the container and its data.

Record the commit, Python and aiohttp versions, and the counts.

### 3.3 Results recorded so far

They are in [WP2_ENGINEERING_FOUNDATION_STATUS.md](WP2_ENGINEERING_FOUNDATION_STATUS.md) section 7.3. In brief:
- the database matrix at `af319bb` gave 3691 passed, 5 skipped and 1 failed (environmental);
- the matrix at `9bc6f2e` gave 4518 passed, 63 skipped (58 opt-in funnel parity cases) and 1 failed (environmental), with `test_p1fix` 18 and A39 10 passed;
- `cf04a4a` alone gave 2941 passed and 906 skipped without the database, with the aiohttp test deselected;
- the main agent ran the default no-database suite on a clean worktree at `263c94e` (3681 passed, 906 skipped, 1 failed: the environmental aiohttp test); the reviewer should still reproduce it independently, and the database matrix was last run at `9bc6f2e`.

## 4. Known differences and gaps reported by the implementers

From the commit messages (DOCUMENTED_ONLY). Each is a review target, not an accepted fact.

| Commit | Reported difference or gap |
|---|---|
| `9d00f88` | SK-09: under composition A, a label-only version bump re-keys every setup. The version-excluded key exists only as proposal helpers in the test file. DG-35 stays HOLD |
| `19b6bc4` | the 0.2 fee plus 0.1 slippage split of the legacy model is attribution only; spread is UNSPECIFIED; the R4 slippage double count is declared, not hidden; the research models' spread-versus-slippage split is UNSPECIFIED (SE-81) |
| `08be803` | differences from legacy: the machine closes a T1/T3 tranche merge at T2 while legacy stays open with zero remaining; a zero-size T1 maps to `partially_exited`; three legacy rules are not covered by SE B6; legacy treats a fill-time risk refusal as a retry, not terminal. Enforce-mode wiring would change behaviour and needs a version boundary |
| `9c0aecc` | at that commit, 33 closure files and 70 regions (superseded by `263c94e`): ACTIVE 30, DORMANT 3, POTENTIAL 1 (`shared/strategy_math.py`, pinned but run by no service). WP-A05 evidence v2 registration is still a proposal |
| `1e68b07` | pause state and open counts are inputs; non-capacity SQL filters, collation and equal-time ties are not mirrored; one-open-per-symbol is mapped to `F7.exposure_symbol` by inference; target mode is not built |
| `af319bb` | determinism across two development machines is NOT_VERIFIED (one machine was available) |
| `cf04a4a` | blocked by DG-71: per-timeframe gate reasons (WP-B02), `F4.regime_not_accepted` against `no_setup`, the scanner BTC fail-open (WP-B10). `open_trade_exists` and the learned-gate labels have no taxonomy-v1 mapping and mark the cycle invalid when recording is on. A non-legacy `SELECTION_VERSION` is not yet in `config_hash` (R5.d gap) |
| `9bc6f2e` | no schema change, so ledger and position-state persistence need WP-E03 and WP-E04. Enforce modes of the shadows are not built. `drift_check` reports strategy-identity DRIFT on both families, so a version-boundary record is required before any deployment; none is created |
| `263c94e` | the closure is a proposal for owner review (DG-69). DORMANT regions: `rank_then_limit`, `tie_break_key`, `score_of` (under `SELECTION_POLICY=legacy`) and `single_count_close`; POTENTIAL: `compare_shadow`, `legacy_admission_queue`, `ResearchPricer` (no caller). `FUNNEL_RECORDING`, `LEDGER_SHADOW` and `POSITION_STATE_SHADOW` are excluded from `config_hash` |

## 5. Expected output of the review

- A findings list with severity, file and line at `263c94e`, the review question it answers (section 2) and the evidence. Mark each finding "reproduced" or "reasoned".
- For each claim C1 to C11: CONFIRMED, NOT CONFIRMED (with the failing evidence) or NOT CHECKED.
- An explicit statement of what was not reviewed.
- The reviewer's identity as an authorized independent reviewer, the date and the commit reviewed.

The owner records the review outcome. A review outcome is not a merge, deployment or activation decision.

## 6. What the reviewer must not do

- Do not merge, push to `main` or open a PR unless the owner asks; integration into `main` is an owner decision (DFP:L41, L102).
- Do not deploy, build or retag images, or run any Class B or Class C operation. Do not restart, recreate or `exec` into any running container (the Class B and Class C rules of [COMPOSE_OPERATIONS.md](../../ops/COMPOSE_OPERATIONS.md)).
- Do not set any WP2 flag on the running Paper services, and do not activate any behaviour on Paper (WP-G01 to WP-G34 keep their gates).
- Do not use a shared or production database. The only database permitted is the disposable matrix container of section 3.2.
- Do not read protected data or sealed holdout outcomes, counts or timestamps (DFP:L57). Run no backtest, simulation, optimisation or calibration on real data.
- Do not edit the hash-pinned files, `research/foundation/contract.py` or the freeze record. Do not run the golden replay's `regenerate` command.
- Do not start the learner.
- Report findings; do not fix them in place on this branch unless the owner asks.
