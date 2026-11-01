# Implementation Workplan for WP2 and Later (plan only)

> **Reconciliation 2026-11-01 (WP2).** Documentation only, on branch `feature/wp2-foundation-20261101` from `5cd1a61`. Stale state statements are corrected; no task, gate, canonical choice or decision changes. What changed:
> - **Pack state.** The pack is committed and pushed at `5cd1a61` on `docs/wp0-wp1-remediation-design-20261101` (not merged into `main`). Statements that called it uncommitted or a working tree are updated (Source aliases note, section 8 scope note).
> - **Section 8 scope.** On 2026-11-01 the WP2 reconciliation aligned OPPORTUNITY_FUNNEL.md, STRATEGY_AND_EXECUTION_CONTRACT.md, PORTFOLIO_RISK_AND_COMPOUNDING.md and REMEDIATION_REGISTER.md with WP-IR-01 to WP-IR-09. Section 8 stays the canonical reference, and its divergence citations describe the files at `5cd1a61`.
> - **Companions and NOT VERIFIED.** DECISIONS_AND_GATES.md is no longer "written in parallel". WP-NV-1 is answered by its section 1.7 and rows DG-70 to DG-72.
> - **Section 11.1.** The resolution column records the WP2 alignment.
> - **Line citations.** Line numbers of pack documents in citations refer to the files as committed at `5cd1a61`. They are not renumbered.

> **Status: plan only (charter §5 WP2–WP5 and §8, "safe engineering branch plan").** This file turns every proposed change of the pack into concrete, dependency-ordered tasks for WP2 and lists every change that must wait for a later gate. It starts nothing, runs nothing, changes nothing and authorizes nothing. Approval of WP0 or WP1 does **not** authorize the start of WP2, protected-data access, simulation, tuning, strategy activation, merging or deployment (`CH:L3`, `CH:L80`). Fixing a defect is never evidence of profitability (`CH:L46`; DFP:L31).

## Document control

| Field | Value |
|---|---|
| This file | `IMPLEMENTATION_WORKPLAN.md` (WP1 deliverable that plans WP2 onward; ID prefix WP-) |
| Baseline | `main` `46578aa`; audit `5d977f2`; ERG-01 `0729a5f`; reconciliation in [BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md) |
| Code read | analyzer and signal_engine at `ea8ae4f`; telegram and trade_tracker at `bb7825f`; `main` at `46578aa`. Every existing path named in a task was checked at `46578aa` with `git cat-file`; files that do not exist there are marked "new" |
| Design inputs | [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md) (R1 … R9, sub-items R1.a …), [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) (OF-), [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md) (SE-), [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) (PR-), [BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md) (BL-). None of them is edited by this file |
| Companions | [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) (DG-; the consolidated owner-decision entries, including WP2-START, WP-OD-01 and WP-OD-02 as DG-70 to DG-72) and [README.md](README.md) (pack index) |
| Governance | [charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md), [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md), [Development-First Policy](../../governance/DEVELOPMENT_FIRST_POLICY.md), [Evidence Ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md), [version boundaries](../../../deploy/VERSION_BOUNDARY.md) |
| ID scheme | WP-A01 … WP-F07: schedulable tasks by lane; WP-G01 …: gated items (not scheduled); WP-IR-01 …: interface reconciliation; WP-IT-01 …: tests that enforce it; WP-OD-01 …: owner decisions raised here; WP-N01 …: observations; WP-NV-1 …: not verified |

### Anti-drift statement (charter §7)

1. **Goal alignment.** Every task serves active daily opportunity discovery, correct execution and the integrity of net-of-cost measurement on which compounding of realized net profit depends (`CH:L8`). Discovery is not execution: no task adds a trade quota, a minimum frequency or a forced trade, and an empty cycle stays a valid, recorded outcome.
2. **Branch, SHA, runtime identity.** `main` = `46578aa`. Runtime behaviour is SOURCE_VERIFIED at the documented-deployed commits only; image content is DOCUMENTED_ONLY; runtime values are RUNTIME_VERIFIED for 2026-10-31 only (BL-11 in [BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md)). For analyzer and signal_engine, `main` is not the deployed source (BL-06).
3. **Scope.** Plans WP2 tasks for R1–R9 and lists WP3, WP4 and WP5 items as gated. **Excluded:** running anything, choosing any parameter or strategy, deciding any owner question, merging, deploying.
4. **Evidence class.** Every factual claim carries `path:Lx-Ly @ commit` or a pack reference and one class from charter §7.4.
5. **Permission class.** This file is read-only documentation. Each task carries exactly one change class; only Documentation/design and Safe development-only correction tasks are schedulable. No class implies another (`CH:L51`, `CH:L65`).
6. **Deliverables, acceptance, gates, rollback.** Per task in [section 4](#4-task-register); common rules in [section 2](#2-planning-rules-common-to-every-task). Acceptance of this file is a clean self-check and owner review.
7. **DEVIATION ALERT.** None raised; see [section 11](#11-inconsistencies-and-deviation-check).

### Source aliases

`ALIAS:Lx-Ly` means `path:Lx-Ly @ commit`:

| Alias | Path @ commit |
|---|---|
| CH, OOC, DFP, ELP | `docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md`, `docs/governance/OWNER_OPERATING_CONTRACT.md`, `docs/governance/DEVELOPMENT_FIRST_POLICY.md`, `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md`, all `@ 46578aa` |
| REP | `docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md @ 5d977f2` (defines audit IDs and OQ-01 … OQ-10) |
| ADD | `docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md @ 5d977f2` (VER-xx) |
| ERG, G1, G2, G3, G4, G5 | `docs/research/evidence-resolution-20261031/` `README.md`, `HIS05_COMPARABILITY.md`, `VERSION_EVIDENCE_LINEAGE.md`, `DEFECT_IMPACT_ASSESSMENT.md`, `POWER_AND_HORIZON_FEASIBILITY.md`, `CANDIDATE_DECISION_MATRIX.md`, all `@ 0729a5f` |

Code is cited with its full path and commit. Pack documents are cited as file, section and line numbers of the pack as committed and pushed at `5cd1a61` on `docs/wp0-wp1-remediation-design-20261101` (not merged into `main`); they are references, not evidence of runtime behaviour.

## Contents

- [1. Scope and non-authorization](#1-scope-and-non-authorization)
- [2. Planning rules common to every task](#2-planning-rules-common-to-every-task)
- [3. Parallel lanes](#3-parallel-lanes)
- [4. Task register](#4-task-register)
- [5. Coverage of every proposed change](#5-coverage-of-every-proposed-change)
- [6. Gated items not scheduled](#6-gated-items-not-scheduled)
- [7. Dependency graph and critical path](#7-dependency-graph-and-critical-path)
- [8. Interface reconciliation](#8-interface-reconciliation)
- [9. Owner decisions raised by this plan](#9-owner-decisions-raised-by-this-plan)
- [10. NOT VERIFIED items](#10-not-verified-items)
- [11. Inconsistencies and deviation check](#11-inconsistencies-and-deviation-check)

## 1. Scope and non-authorization

**What this plan covers.** WP2 ("safe remediation: approved dev-branch changes with deterministic tests, CI and review", `CH:L51`) and the hand-off of every later item to WP3 (research decision gate, `CH:L52`), WP4 (authorized evaluation only, `CH:L53`) and WP5 (operational validation and replication, `CH:L54`).

**What it does not authorize** (DOCUMENTED_ONLY, policy):
- **WP2 start.** WP2 needs its own owner approval ("approved dev-branch changes", `CH:L51`). Approval of the charter, of WP0 or of WP1 approves direction and documentation only (`CH:L80`). In this file that approval is the gate **WP2-START**; its consolidated entry belongs in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md).
  - **Dated note, 2026-11-01 (owner decisions, WP2 iteration 2).** WP2-START (DG-70) is **APPROVED, development-only** (DECISIONS_AND_GATES.md section 3, entry DG-L03). It continues the safe-development scope of the initial foundation work. It does not unlock protected experiments, production operations, strategy activation or merging. The same entry records DG-69 (WP-A01) as APPROVED FOR COMPLETION AND REVIEW, and WP-OD-01 (DG-71) and SE-84 (DG-35) as on HOLD. Task rows are not rewritten.
  - **Dated note, 2026-11-01 (integrated development).** The owner decision `docs/governance/WP2_INTEGRATED_DEVELOPMENT_DECISION_2026-11-01.md @ f0c560d` (entry DG-L04) makes the existing bot source the development target. Two rules of this plan are superseded for development source integration only, never as permission to deploy or activate (L3, L36 of that file): the "dormant only" reading, and the "no production import" rules. Those rules are the import restriction of section 2.4 criterion 4 and the WP-E01 acceptance "no import from a runtime service". These stay in force: criteria 2 and 3 of section 2.4 (byte-identical outputs at the flag default; an unknown value refuses), the WP-N02 rule (criterion 5), and the activation, shared-host and research gates of that decision (L18, L22-26).
- **Protected data, simulation, tuning.** No task reads FORWARD_HOLDOUT outcomes, counts or timestamps, the production database, logs or unlicensed data (DFP:L57-58; DFP:L42). No task runs a backtest, replay on real data, optimisation, calibration or ablation. Tests use synthetic fixtures only.
- **Activation.** A default-off flag never authorizes its own activation, a governed experiment or a production change (`CH:L51`; DFP:L87, L104).
- **Merging and integration.** Integration into `main` is an owner decision outside this plan (DFP:L41, L102; `CH:L80`). DFP:L5 permits direct integration of low-risk D0 work; this plan follows the narrower gate, as OOC:L44 requires when records diverge.
- **Deployment.** A merged commit is not a deployment authorization (OOC:L18; DFP:L7).
- **Profitability.** No task, test or completion criterion is an economic claim. Closing a defect makes behaviour correct and measurable; it says nothing about net edge (`CH:L46`; DFP:L31). The ERG-01 verdict **INCONCLUSIVE** stands, and it is a decision state, not negative evidence about any family (ERG:L119, L205).

**Change classes** (exactly one per task; definitions as in [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md), "How to read an item", L44-52):

| Class | Schedulable here? |
|---|---|
| Documentation/design | yes |
| Safe development-only correction | yes: default-off, byte-identical outputs at the default, unknown value refuses to start (DFP:L87) |
| Strategy-version-changing correction | no: [section 6](#6-gated-items-not-scheduled) |
| Protected research or simulation | no: [section 6](#6-gated-items-not-scheduled) |
| Production/runtime change | no: [section 6](#6-gated-items-not-scheduled) |

**Split of one proposed change into two tasks.** Several pack changes carry one class for the behaviour change itself, for example OF-T04 to OF-T12 (Strategy-version-changing correction). Following the precedent of R1.b/R1.c and SE-64/SE-65, this plan schedules only the **default-off implementation slice** of such a change as a Safe development-only correction, with a flag-off parity test (OPPORTUNITY_FUNNEL.md §9.2, L460), and puts the **activation** in [section 6](#6-gated-items-not-scheduled) with the class the source document gives it. The behaviour change keeps its original class; nothing is reclassified.

## 2. Planning rules common to every task

### 2.1 Base commit and the deployed source

All code tasks start from `main` `46578aa`. For telegram and trade_tracker, `main` equals the documented-deployed source `bb7825f` in every active directory; for analyzer and signal_engine it does not: 12 files differ from `ea8ae4f`, including the new `shared/t1_cap.py` (BL-06, SOURCE_VERIFIED). The funnel logic is unchanged between the two commits; `signal_engine/signal_logic.py` differs only by one telemetry argument (OF-01; BL-06). Two consequences (INFERRED):
- byte-identity at a flag default is asserted against `46578aa` behaviour, and for the funnel logic also against `ea8ae4f`;
- any future release built from WP2 work would also ship `main`'s T1 switch, so it is the R2.d release decision (WP-G04), not a side effect of a WP2 task.

### 2.2 Branch and integration model

- **One shared development branch.** Lanes are series of small commits, not branches, as the owner workflow directive prefers "at most one shared, short-lived integration branch when isolation is needed" (DFP:L5; OOC:L14). The branch name is chosen at WP2-START.
- **Review hand-off.** Pushing the development branch for review falls under the standing D0 authorization (DFP:L41), but only after WP2-START.
- **Integration.** Integration into `main` is an owner decision outside this plan; this plan prepares hand-offs only.

### 2.3 Hash-pinned files (WP-N02)

**WP-N02 · SOURCE_VERIFIED (mechanism); INFERRED (consequence).**
- The research contract hashes the bytes of nine logic files: `analyzer/simple_entry.py`, `shared/regime.py`, `shared/signal_stop.py`, `shared/triple_barrier.py`, `shared/partial_exits.py`, `shared/risk_management.py`, `shared/strategy_math.py`, `scanner/scanner_logic.py` and `signal_engine/signal_logic.py` (`research/foundation/contract.py:L69-75 @ 46578aa`).
- `shared/risk_management.py` is also pinned in the runtime contract and is deliberately left byte-identical by the existing wrapper pattern (`shared/economic_halt_policy.py:L10-13 @ bb7825f`).
- Consequence: any byte change to one of these files changes `current_contract()`, even when behaviour is identical. It would fail the SE-63 acceptance criterion "the v1 hash of `current_contract()` unchanged" and the PR-T09 assertion that the hash of `shared/risk_management.py` is unchanged.

**Rule.** Tasks put new behaviour in new or unhashed modules and wrap the pinned files. When a task cannot avoid a hook inside a pinned file, the hook is split out and waits for owner decision WP-OD-01 ([section 9](#9-owner-decisions-raised-by-this-plan)). Affected slices: the signal-engine and scanner hooks of WP-B01, WP-B02, the ranking hook of WP-B05 and the fail-open hooks of WP-B10.

### 2.4 Common acceptance criteria

For every **Safe development-only correction** task, in addition to its own criteria:
1. its listed tests are green in CI or in the local CI equivalent. That runner, `ops/ci/lce.py`, exists only on the unmerged branch `review/lce-2` (`fd66219`, BL-08), so its availability is part of WP-NV-2;
2. at the flag default, outputs are byte-identical to current behaviour on golden fixtures (WP-A04 once available; before that, the pattern of `tests/test_decision_parity_before_after.py`);
3. an unknown flag value refuses to start (DFP:L87);
4. no runtime service imports a new library module except through its default-off flag (import-graph test, the SE-61 pattern);
5. the WP-N02 rule is respected;
6. the diff passes the repository's protected-information scan (`ops/provenance/protected_scan.py`);
7. deployable service code receives independent review (DFP:L73);
8. no commit message, document or test name makes an economic claim.

For every **Documentation/design** task: owner review. Production-operation definitions also need independent review (DFP:L73).

### 2.5 Common rollback

- **Code tasks:** revert the task's commits on the development branch. Nothing is merged, released or deployed by this plan, so there is no runtime rollback; flags stay at the legacy default.
- **Disposable-database tasks:** discard the disposable database.
- **Documentation tasks:** revert the commit. Append-only records are amended, never rewritten (`deploy/VERSION_BOUNDARY.md:L3-5 @ 46578aa`).

### 2.6 Gate vocabulary

| Gate | Meaning | Source |
|---|---|---|
| WP2-START | owner approval to start WP2 work under this plan; APPROVED, development-only, on 2026-11-01 (section 1, dated note) | `CH:L51`, `CH:L80` |
| Design decisions | open individual WP2 slices; they are not WP3 decisions: OF-OD-01 … OF-OD-18, PR-OD1 … PR-OD22, SE-80, SE-82, SE-84 … SE-88, the register's bundling decision (REMEDIATION_REGISTER.md "Priority ordering", L81-86), OQ-07, OQ-09, WP-OD-01, WP-OD-02 | the pack documents |
| WP3 decisions | OD-DF-1, OD-DF-2, candidate slots and slot plan (G4 Q4, Design A E1–E8, SE-89), preregistration, cost and fill model (SE-81, SE-87, OQ-08), in ERG order | `CH:L52`; ERG:L123-131, L207-213 |
| WP4 | authorized evaluation only | `CH:L53` |
| WP5 | operational validation, deployment approval, Class B operations | `CH:L54`; OOC:L18 |

Every gate is cited by its source decision ID; the consolidated entry for each is in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md).

### 2.7 Observation WP-N01: the release label is a build default

**WP-N01 · SOURCE_VERIFIED (build files); NOT_VERIFIED (running images).**
- Every bot-service Dockerfile defaults `ARG APP_VERSION=sb-2026.08`, exports it as `ENV APP_VERSION` and defaults `ARG BUILD_REVISION=unknown` (`analyzer/Dockerfile:L5-13 @ ea8ae4f`; the same three statements in the signal_engine, scanner, telegram and trade_tracker Dockerfiles at `ea8ae4f` and `46578aa`, for example `trade_tracker/Dockerfile:L2-9 @ 46578aa`).
- The code default is `sb-2026.06` (`shared/config.py:L45 @ 46578aa`).
- This would explain the runtime label `sb-2026.08` (VER-13) and the `revision=unknown` image labels (RT-15). Whether the running images were built with these defaults is NOT_VERIFIED (VER-28 item 5).
- Consequence for the plan (INFERRED): the strategy label is a build default, independent of code content. This reinforces SE-08 and R3.d, and is handled by WP-A02 (content hashes) and WP-A06 (build refusal).

## 3. Parallel lanes

The lanes group tasks that touch disjoint modules, so they can proceed side by side once WP2-START is given. A lane is a commit series on the one development branch (section 2.2), not a branch.

| Lane | Name | Scope | R-items | Tasks | First tasks that need no design decision |
|---|---|---|---|---|---|
| A | Provenance and `StrategyVersion` identity | interface types, hashing, contract hash v2, golden replay, `DecisionRecord`, build labels | R5 (R5.b, R5.d), R2.c, R1.d, R1.e | WP-A01 – WP-A06 | WP-A01, WP-A06 |
| B | Funnel observability and selection | `RejectionRecord`, reason taxonomy, counters, `MarketSnapshot`, per-cycle record, rank-then-limit selection, default-off slices of the F1–F7 rules | R6, R1 | WP-B01 – WP-B13 | WP-B13 |
| C | Signal identity and idempotency | enforce-mode decomposition, `setup_key` from `StrategyVersion`, the R3 regression suite, admission by key, no re-fire across a boundary | R3 | WP-C01 – WP-C05 | WP-C01 |
| D | Strategy interface, geometry and execution model | strategy adapters, W3 invariants and policy options, position state machine, research cost model, exchange-filter rounding, hypothesis specifications | R2, R4 (inputs), R8 | WP-D01 – WP-D07 | WP-D07 |
| E | Ledger, accounting and capacity authority | pure ledger, legacy adapter, disposable-database migration, shadow writer, daily series, net counters, single-count costs, capacity authority in legacy mode | R7, R4 (accounting) | WP-E01 – WP-E09 | WP-E09 |
| F | Operations health, runbooks and records | runbook and CLAUDE.md corrections, learner hazard, static guards, collector health review, observation-record fields, record notes | R9, R5 (records) | WP-F01 – WP-F07 | WP-F01, WP-F02, WP-F04, WP-F05, WP-F06 |

**Concurrency in one line.** Lanes A, E and F start together. B, C and D attach to WP-A01 and WP-A02. Inside a lane, tasks run in parallel unless the dependency table of [section 7](#7-dependency-graph-and-critical-path) orders them.

## 4. Task register

Each task lists: source items (including R-items); its single change class; files and modules touched (existing paths verified at `46578aa`; new files marked "new"); dependencies; concurrency; deterministic synthetic-data tests (pack test IDs reused); completion ("done") and acceptance criteria beyond section 2.4; the owner gate that must open before it starts; and rollback (section 2.5 unless stated). "Activation" always points to a gated item of [section 6](#6-gated-items-not-scheduled).

### 4.1 Lane A: provenance and StrategyVersion identity

#### WP-A01 · Canonical interface, StrategyVersion descriptor and boundary template
- **Source:** R5.d (specification part); SE-60; SE-72; R1.d; R1.e; adoption of WP-IR-01 … WP-IR-09.
- **Class:** Documentation/design.
- **Files:** `docs/design/STRATEGY_INTERFACE_v1.md` (new), holding the reconciled types, taxonomy v1 and source-closure lists; `deploy/VERSION_BOUNDARY_TEMPLATE.md` (new), holding the strategy-boundary template of SE-36. `deploy/VERSION_BOUNDARY.md` is not edited.
- **Depends on:** none. **Beside:** WP-A06, WP-C01, WP-D07, WP-E09, lane F.
- **Tests:** none (documentation). It specifies WP-IT-01 … WP-IT-09, which the code tasks implement.
- **Done:** the specification fixes these points:
  - the five `StrategyVersion` identity fields, with `lineage` as metadata (WP-IR-09);
  - the source closure per family: the nine hashed files plus `analyzer/technical_analyzer.py`, `shared/t1_cap.py`, `shared/signal_identity.py`, the selection code of `signal_engine/main.py` and the cost-booking code (SE-37, SE-04);
  - the `config_hash` keys, including `T1_CAP_POLICY`, `SIGNAL_INTEGRITY_MODE`, the selection policy and database-held thresholds (SE-37);
  - `tie_break_key` = hash of (selection version, `setup_key`), never a name or timeframe string (R1.d; OPPORTUNITY_FUNNEL.md F6, L336);
  - `total_score` recorded as a fixed, data-mined input with no decision role in any new version (R1.e; OQ-09);
  - taxonomy v1, including the additions of section 8;
  - the SE-36 template fields.
- **Accepted:** owner review records the specification as the WP2 interface baseline (SE-60, "review only"). No boundary entry is created.
- **Gate:** WP2-START.

#### WP-A02 · StrategyVersion library and interface types
- **Source:** SE-61; R5.d (code); R2.c; prerequisite of R3.d.
- **Class:** Safe development-only correction.
- **Files:** `shared/strategy_interface.py` (new); `tests/test_strategy_interface.py` (new). It reuses `canonical_json` and `contract_hash` (`research/foundation/contract.py:L106-111 @ 46578aa`) without editing that file.
- **Depends on:** WP-A01. **Beside:** WP-A06, WP-B03, WP-D04, lanes E and F.
- **Tests:** the SE-61 tests (canonical-JSON stability, same input gives the same hash, a closure edit changes `source_hash`, network, database, environment and clock access raise, import graph unchanged); R5 tests 1–2; WP-IT-02; WP-IT-09.
- **Done:** frozen types for the glossary entities as reconciled in section 8; `StrategyVersion` hashing; `T1_CAP_POLICY` and `SIGNAL_INTEGRITY_MODE` are `config_hash` keys (R2.c); identity emission on records sits behind a default-off flag.
- **Accepted:** R5 test 1 passes for every file of the WP-A01 closure list.
- **Gate:** WP2-START.

#### WP-A03 · Contract hash v2 beside v1
- **Source:** SE-63; R5.d; G3-08 (G3:L268-277).
- **Class:** Safe development-only correction.
- **Files:** `research/foundation/contract_v2.py` (new); `tests/test_contract_hash_v2.py` (new). `research/foundation/contract.py` and `tests/test_research_foundation_contract.py` stay unchanged.
- **Depends on:** WP-A02. **Beside:** lanes B to F.
- **Tests:** the SE-63 mutation test, one per added file; v1 hash unchanged. `research/governance/research_freeze.json` stays byte-unchanged, checked by git blob identity without opening the file.
- **Done:** v1 and v2 are reported side by side.
- **Accepted:** the v1 output is byte-identical.
- **Gate:** WP2-START.

#### WP-A04 · Golden replay harness (synthetic)
- **Source:** SE-71; the SE-38 PATCH/MINOR rule.
- **Class:** Safe development-only correction.
- **Files:** `tests/golden_replay.py` (new); `tests/test_golden_replay.py` (new); synthetic fixtures under `tests/` (new).
- **Depends on:** WP-A02. **Beside:** every task in lanes B to F.
- **Tests:** SE-71: byte-identical outputs across two runs and two development machines.
- **Done:** the harness serves as acceptance criterion 2 of section 2.4 for every later code task.
- **Accepted:** a deliberately changed fixture output is detected.
- **Gate:** WP2-START.

#### WP-A05 · DecisionRecord payload, hash chain and offline verifier
- **Source:** SE-70 (SE-51, SE-55, SE-56); R5; R6; WP-IR-08.
- **Class:** Safe development-only correction.
- **Files:**
  - `shared/decision_record.py` (new);
  - `ops/provenance/decision_chain_verify.py` (new), an offline tool and not a scheduled service (`CLAUDE.md:L18 @ 46578aa`);
  - `tests/test_decision_record.py` (new);
  - a default-off payload registration in `shared/evidence_v2.py`.
- **Depends on:** WP-A02. **Beside:** lanes C to F.
- **Tests:** the SE-70 tests (deterministic `decision_id`, chain-break detection, replay gives identical hashes); WP-IT-08.
- **Done:** payload types for every `decision_type`, including the per-cycle `opportunity_rank` record.
- **Accepted:** the verifier passes on synthetic days and fails on each injected break.
- **Gate:** WP2-START. **Activation:** enabling the records on the host is WP-G19.

#### WP-A06 · Build-provenance refusal
- **Source:** R5.b; WP-N01; RT-15.
- **Class:** Safe development-only correction.
- **Files:**
  - `ops/provenance/build_preflight.py`: refuse a missing or `unknown` revision, and cover the collector, which the `SERVICES` tuple omits (`ops/provenance/build_preflight.py:L8 @ 46578aa`);
  - removal of the `unknown` default of `ARG BUILD_REVISION` in `analyzer/Dockerfile`, `signal_engine/Dockerfile`, `scanner/Dockerfile`, `telegram/Dockerfile` and `trade_tracker/Dockerfile`, so that a build without an explicit revision fails;
  - an OCI revision label in `p2_forward/Dockerfile`, fed from its existing `P2F_GIT_COMMIT` argument (`p2_forward/Dockerfile:L9 @ 46578aa`);
  - `tests/test_r14_build_preflight.py` (extended).
  
  The `APP_VERSION` default is deliberately **not** changed: it is part of today's A44 setup key, so changing it would re-key setups (SE-36, STRATEGY_AND_EXECUTION_CONTRACT.md L248).
- **Depends on:** none. **Beside:** everything.
- **Tests:** a build input with a missing or `unknown` revision is refused for all six services; `tests/test_parity_inventory.py` stays green (R5 test 3).
- **Done:** the preflight refuses unlabelled builds.
- **Accepted:** no image is built by the task; builds are WP-G04 and WP-G10.
- **Gate:** WP2-START.

### 4.2 Lane B: funnel observability and selection

#### WP-B01 · RejectionRecord writer, taxonomy v1, counters and conservation check (shadow)
- **Source:** OF-T01; R6.a; R6.c; R1.f; WP-IR-01, WP-IR-04, WP-IR-05.
- **Class:** Safe development-only correction.
- **Files:**
  - `shared/funnel_records.py` (new): schema, taxonomy v1, counters, conservation;
  - hooks behind one default-off flag in `scanner/main.py`, `analyzer/main.py`, `analyzer/technical_analyzer.py`, `signal_engine/main.py`, `telegram/main.py` and `trade_tracker/main.py`;
  - the flag in `shared/config.py`;
  - `tests/test_funnel_records.py` (new).
  
  The hooks inside `scanner/scanner_logic.py` (filters S2–S5) and `signal_engine/signal_logic.py` (gates S14–S21) are a split slice under WP-OD-01. One option there avoids the pinned files: a mirror in a new module, asserted equal to the pinned function's output in tests.
- **Depends on:** WP-A01, WP-A02. **Beside:** WP-B03, lanes C to F.
- **Tests:**
  - the OF-T01 tests. In the fixture with more than 700 fresh rows, every cut row appears as `F6.legacy_alphabetical_cut`;
  - R6 tests 1, 2 and 6;
  - R1 test 2, in shadow: every drop before eligibility is recorded;
  - WP-IT-01; WP-IT-04.
- **Done:** analyzer, delivery and admission drops are recorded. The scanner and signal-engine drops are recorded too, unless WP-OD-01 is still open; until then they are listed as pending.
- **Accepted:** conservation holds on every fixture; decisions are byte-identical with the writer on and off.
- **Gate:** WP2-START; hooks in pinned files need WP-OD-01. Retention (OF-OD-18) gates activation only (WP-G19).

#### WP-B02 · Per-(symbol, strategy, timeframe, bar) decision keys, recorded only
- **Source:** OF-T02; R6.b.
- **Class:** Safe development-only correction.
- **Files:** `signal_engine/signal_logic.py`, where `last_decisions` is keyed by symbol (`signal_engine/signal_logic.py:L853 @ ea8ae4f`, a pinned file); `signal_engine/main.py` (reason writer); `tests/test_funnel_decision_keys.py` (new). The database `decision_reason` column is unchanged.
- **Depends on:** WP-B01. **Beside:** lanes C to F.
- **Tests:** OF-T02; R6 test 3.
- **Done:** per-key records in shadow.
- **Accepted:** one symbol with three timeframe outcomes yields three distinct records.
- **Gate:** WP-OD-01. Under option (a) of WP-OD-01 this task is deferred to the next declared selection version (WP-G01).

#### WP-B03 · MarketSnapshot adapter captured in shadow
- **Source:** OF-T03; R6; R5 (input hashes).
- **Class:** Safe development-only correction.
- **Files:** `shared/market_snapshot.py` (new), the only module that knows venue field names (principle P7); a hook in `scanner/main.py`; `tests/test_market_snapshot.py` (new).
- **Depends on:** WP-A01. **Beside:** WP-A02 and later, lanes C to F.
- **Tests:** OF-T03.
- **Done:** the snapshot carries `as_of`, `source`, filters (as `MarketSnapshot.filters`, SE §B3), 24 h statistics, clock offset and a content hash.
- **Accepted:** no venue field name appears outside the adapter.
- **Gate:** WP2-START.

#### WP-B04 · Per-cycle DecisionRecord and deterministic decide(state, snapshot)
- **Source:** OF-T13; SE-51; WP-IR-08.
- **Class:** Safe development-only correction.
- **Files:** `signal_engine/main.py` (flagged emission), using `shared/decision_record.py`, `shared/funnel_records.py` and `shared/market_snapshot.py`; `tests/test_funnel_decide.py` (new).
- **Depends on:** WP-A05, WP-B01, WP-B03. **Beside:** lanes C to F.
- **Tests:** OF-T13; R1 test 4; WP-IT-08.
- **Done:** one `opportunity_rank` record per cycle with counters, conservation result and input hashes.
- **Accepted:** re-evaluating recorded synthetic inputs reproduces the record byte-for-byte.
- **Gate:** WP2-START. **Activation:** WP-G19.

#### WP-B05 · Rank-then-limit selection as a pure, default-off function
- **Source:** R1.b; OF-T10 (implementation slice); R1.d; WP-IR-04.
- **Class:** Safe development-only correction.
- **Files:**
  - `shared/candidate_selection.py`, reusing `bounded_universe`, `execution_quality_v2` and the staged pipeline (OF-23);
  - `signal_engine/main.py`, as a flag path beside the selection query (`signal_engine/main.py:L146-155 @ ea8ae4f`);
  - the selection-policy flag in `shared/config.py`: default legacy, fails closed;
  - `tests/test_selection_rank_then_limit.py` (new).
  
  `tests/test_a44_selection_pipeline.py` and `tests/test_fixed_candidate_policy.py` stay green. A hook beside `_fixed_candidate_key` in `signal_engine/signal_logic.py` falls under WP-OD-01.
- **Depends on:** WP-A02, WP-B01, WP-C02 (`tie_break_key` uses `setup_key`). **Beside:** lanes D to F.
- **Tests:** R1 tests 1–6; the OF-T10 tests; WP-IT-04.
- **Done:** with the flag on, every candidate is ranked, ties break on `tie_break_key`, caps apply after ranking with `F6.rank_below_cap`, and a resource guard records `F6.resource_cap`. With the flag off, the current query and key are reproduced. The per-cycle offer count stays at the legacy value of one in the default; its target value is OF-OD-15.
- **Accepted:** R1 test 3 (default byte-identity) and R1 test 6 (collation independence).
- **Gate:** WP2-START; WP-OD-01 for a pinned-file hook. **Activation:** WP-G01.

#### WP-B06 · Contract-score ranking slice
- **Source:** OF-T11 (implementation slice); R1.e.
- **Class:** Safe development-only correction.
- **Files:** `shared/candidate_selection.py`; the per-contract score exposed by `analyzer/strategy_adapters.py` (WP-D01); `tests/test_selection_contract_score.py` (new).
- **Depends on:** WP-B05, WP-D01. **Beside:** lanes E and F.
- **Tests:** OF-T11. Under the flag, `total_score` has no effect on order.
- **Done:** both orderings are available, with the default unchanged.
- **Accepted:** common criteria only.
- **Gate:** OF-OD-14 (ranking objective and cross-strategy comparison); OQ-09. **Activation:** WP-G02.

#### WP-B07 · EligibilityResult rule set (F1) slice
- **Source:** OF-T04 (implementation slice); R6.f.
- **Class:** Safe development-only correction.
- **Files:** `shared/funnel_eligibility.py` (new), consuming `shared/market_snapshot.py`; `tests/test_funnel_eligibility.py` (new).
- **Depends on:** WP-B01, WP-B03. **Beside:** WP-B08 to WP-B11, lanes C to F.
- **Tests:** OF-T04. Parity: at the default parameters, the shadow F1/F2a set equals the output of the existing scanner functions, which are called in tests and not edited.
- **Done:** every symbol gets an `EligibilityResult` with all of its failed rules.
- **Accepted:** a missing input makes the symbol ineligible, never eligible.
- **Gate:** OF-OD-01 … OF-OD-05; OQ-07. **Activation:** WP-G14.

#### WP-B08 · F2 liquidity and spread, F5 feasibility slice
- **Source:** OF-T05 (implementation slice).
- **Class:** Safe development-only correction.
- **Files:** `shared/funnel_eligibility.py`; `shared/market_snapshot.py`; `shared/cost_models.py` (WP-D04, for `expected_cost`); `tests/test_funnel_feasibility.py` (new).
- **Depends on:** WP-B01, WP-B03, WP-D04. **Beside:** WP-B07, WP-B09 to WP-B11.
- **Tests:** OF-T05; WP-IT-01 for `F5.stop_missing`.
- **Done:** each failure gives its own code; a missing stop rejects.
- **Accepted:** the spread used comes from a book within its age bound.
- **Gate:** OF-OD-06 … OF-OD-08. **Activation:** WP-G15.

#### WP-B09 · Single BTC trend in RegimeContext slice
- **Source:** OF-T06 (implementation slice).
- **Class:** Safe development-only correction.
- **Files:** `shared/regime_context.py` (new), with `shared/macro_context.py` read for parity and not edited; `tests/test_regime_context.py` (new). `tests/test_macro_context.py` stays green.
- **Depends on:** WP-A02, WP-B01. **Beside:** WP-B07, WP-B08, WP-B11.
- **Tests:** OF-T06.
- **Done:** exactly one BTC trend function; staleness is computed from bar time; a veto applies only to the strategies that declare it.
- **Accepted:** the universe is the same whatever the BTC label. BTC SMA200 is never a default gate (`CH:L15`).
- **Gate:** OF-OD-09 … OF-OD-11. **Activation:** WP-G16.

#### WP-B10 · Explicit failure semantics slice (the three fail-open reads)
- **Source:** OF-T07 (implementation slice); R6.e; R3.c.
- **Class:** Safe development-only correction.
- **Files:**
  - `shared/regime_context.py`;
  - the missing-field read in `shared/macro_context.py` (`shared/macro_context.py:L28-33 @ ea8ae4f`; not a pinned file);
  - `tests/test_fail_semantics.py` (new).
  
  Two hooks are in pinned files and fall under WP-OD-01: the cooldown read in `signal_engine/signal_logic.py` (`signal_engine/signal_logic.py:L417-431 @ ea8ae4f`) and the BTC trend fallback in `scanner/scanner_logic.py` (`scanner/scanner_logic.py:L116-148 @ ea8ae4f`).
- **Depends on:** WP-B01, WP-B09. **Beside:** WP-B11, lanes C to F.
- **Tests:** OF-T07; R3 test 4; R6 test 5.
- **Done:** each failing read has its declared outcome plus a record.
- **Accepted:** no default path yields `neutral`, zero or an empty cooldown set.
- **Gate:** OF-OD-10; WP-OD-01 for the pinned hooks. **Activation:** WP-G13.

#### WP-B11 · Venue-synchronised closed-bar rule and freshness bound slice
- **Source:** OF-T08 (implementation slice); R6.d.
- **Class:** Safe development-only correction.
- **Files:**
  - `shared/ohlcv.py`, for closed-bar construction against venue-synchronised time;
  - the freshness rule of `shared/signal_identity.py` (`shared/signal_identity.py:L186-200 @ ea8ae4f`) as the reference;
  - the clock offset from `shared/market_snapshot.py`;
  - `tests/test_closed_bar_freshness.py` (new). `tests/test_ohlcv.py` stays green.
- **Depends on:** WP-B01, WP-B03. **Beside:** WP-B07 to WP-B10.
- **Tests:** OF-T08; R6 test 4; R3 test 6.
- **Done:** no forming bar and no bar beyond the bound produces a candidate under the flag.
- **Accepted:** common criteria only.
- **Gate:** OF-OD-12. **Activation:** WP-G12.

#### WP-B12 · F7 hand-off interface slice
- **Source:** OF-T12 (implementation slice); WP-IR-03; WP-IR-05.
- **Class:** Safe development-only correction.
- **Files:**
  - a flag path in the admission loop of `trade_tracker/main.py` (`trade_tracker/main.py:L705-759 @ bb7825f`);
  - the delivery gate of `telegram/main.py` (`telegram/main.py:L364-382 @ bb7825f`), turned into a mirror only;
  - `shared/capacity_authority.py` (WP-E08);
  - `tests/test_f7_handoff.py` (new). `tests/test_paper_observe_capacity.py` stays green.
- **Depends on:** WP-B01, WP-B05, WP-C04, WP-E08. **Beside:** lanes D and F.
- **Tests:** OF-T12; WP-IT-03; WP-IT-04; WP-IT-05.
- **Done:** rank-order offering, a record for every refusal, declared refusal semantics, `F7.superseded` records.
- **Accepted:** with the flag off, admissions are byte-identical.
- **Gate:** OF-OD-16; OF-OD-13; WP-OD-02. A runbook (WP-B13) must exist before any activation (DFP:L104). **Activation:** WP-G17.

#### WP-B13 · Paper admission-change runbook draft
- **Source:** the OPPORTUNITY_FUNNEL.md §12 governance note (L537); DFP:L104.
- **Class:** Documentation/design.
- **Files:** `docs/ops/PAPER_ADMISSION_CHANGE_RUNBOOK.md` (new).
- **Depends on:** none; its content is cross-checked with WP-B12 once that exists. **Beside:** everything.
- **Tests:** none.
- **Done:** the runbook covers steps, identity captures before and after, the version-boundary record, rollback and the absolute STOP rule. No command is executed.
- **Accepted:** owner review and independent review, as for any production-operation definition (DFP:L73).
- **Gate:** WP2-START.

### 4.3 Lane C: signal identity and idempotency

#### WP-C01 · Enforce-mode behaviour decomposition
- **Source:** R3.e.
- **Class:** Documentation/design.
- **Files:** `docs/design/SIGNAL_INTEGRITY_MODE_DECOMPOSITION.md` (new).
- **Done:** each behaviour of `SIGNAL_INTEGRITY_MODE=enforce` is described alone, with its code site, so the owner can declare one boundary or several (R3 owner gates; SE-83):
  - insert-once identity (`signal_engine/signal_logic.py:L261-263, L730-737, L803-818 @ ea8ae4f`);
  - the one-bar freshness bound (`shared/signal_identity.py:L186-200 @ ea8ae4f`);
  - the fail-closed cooldown read;
  - the tracker's integrity refusal (`trade_tracker/main.py:L700-702 @ bb7825f`).
- **Depends on:** none. **Beside:** everything.
- **Accepted:** owner review.
- **Gate:** WP2-START.

#### WP-C02 · setup_key derived from StrategyVersion, default-off
- **Source:** R3.d; OF-T09 (key part; OPPORTUNITY_FUNNEL.md F4, L314-317).
- **Class:** Safe development-only correction.
- **Files:** `shared/signal_identity.py` (a new identity version; the A44 key, `shared/signal_identity.py:L64-88 @ ea8ae4f`, is unchanged at the default); `tests/test_setup_key_v2.py` (new). `tests/test_a43_signal_integrity.py` stays green.
- **Depends on:** WP-A02. **Beside:** lanes D to F, WP-B01 to WP-B04.
- **Tests:** R3 tests 2–3; the OF-T09 version test, in which a changed `StrategyVersion` gives a new key; the R3 version-identity acceptance test.
- **Done:** the key is derived from the five identity fields and the bar close time, and is never derived from `APP_VERSION` under the new identity version.
- **Accepted:** common criteria only.
- **Gate:** SE-84 (setup-key composition). **Activation:** WP-G05.

#### WP-C03 · R3 regression suite, default-off
- **Source:** R3.f; the OF-T09 tests.
- **Class:** Safe development-only correction.
- **Files:** `tests/test_r3_same_bar_refire.py` (new), plus a disposable-database case beside `tests/test_a44_migration_db.py` and `tests/test_a44_integration_db.py`.
- **Depends on:** WP-C02. **Beside:** WP-C04, WP-C05.
- **Tests:** R3 tests 1–7; OF-T09.
- **Done:** the suite pins today's off-mode re-fire as the expected legacy behaviour, and pins the identity behaviour under the flag.
- **Accepted:** green with the mode at `off`.
- **Gate:** WP2-START.

#### WP-C04 · Admission by setup_key, default-off
- **Source:** R3.b (implementation slice); OPPORTUNITY_FUNNEL.md F7, "Idempotent admission" (L357).
- **Class:** Safe development-only correction.
- **Files:** a flag path beside the admission query of `trade_tracker/main.py` (`trade_tracker/main.py:L718-749 @ bb7825f`); `tests/test_admission_by_setup_key.py` (new).
- **Depends on:** WP-B01, WP-C02. **Beside:** WP-C03, WP-C05.
- **Tests:** R3 test 5; supersession recorded as `F7.superseded`.
- **Done:** at most one trade per key under the flag.
- **Accepted:** default admissions are byte-identical.
- **Gate:** WP2-START. **Activation:** WP-G05.

#### WP-C05 · No re-fire across a version boundary
- **Source:** SE-36; SE-52 (`bar_before_version_activation`).
- **Class:** Safe development-only correction.
- **Files:** `shared/signal_identity.py`; `tests/test_version_boundary_refire.py` (new).
- **Depends on:** WP-A02, WP-C02. **Beside:** WP-C03, WP-C04.
- **Tests:** the SE-65 test that no pre-activation bar is re-evaluated; WP-IT-01 for `F4.bar_before_version_activation`.
- **Done:** a new version evaluates only bars whose close is at or after its activation minute.
- **Accepted:** common criteria only.
- **Gate:** WP2-START.

### 4.4 Lane D: strategy interface, geometry and execution model

#### WP-D01 · Strategy adapters for the frozen 1.0.0 families
- **Source:** SE-62; SE-39 (identity mapping only, no evidence transfer).
- **Class:** Safe development-only correction.
- **Files:** `analyzer/strategy_adapters.py` (new), which wraps `analyzer/simple_entry.py` and the levels code of `analyzer/technical_analyzer.py` without editing them; `tests/test_strategy_adapters.py` (new). `tests/test_simple_entry.py` stays green.
- **Depends on:** WP-A02. **Beside:** lanes B, C, E and F.
- **Tests:** SE-62 golden parity, including the W3 legacy behaviour, which is labelled as such; WP-IT-02.
- **Done:** `momentum_breakout 1.0.0` and `reversion_rsi_bb 1.0.0` exist, with `lineage` pointing to the preserved legacy contract. `research/governance/research_freeze.json` is unchanged.
- **Accepted:** 100% identical candidates, levels and rejection outcomes on the fixture set.
- **Gate:** WP2-START.

#### WP-D02 · W3 invariants and policy options behind T1_CAP_POLICY
- **Source:** SE-64; R2.b; SE-40.
- **Class:** Safe development-only correction.
- **Files:**
  - `shared/t1_cap.py`: options a (prior window) and c (no cap) beside `legacy_window_v1` and `independent_swing_v1`; the default is unchanged;
  - `shared/config.py`: allowed values; fails closed;
  - `tests/test_t1_cap_policy.py` (extended);
  - `tests/test_w3_invariants.py` (new), with `shared/trade_geometry.py` as the reference oracle. `tests/test_a46_trade_geometry.py` stays green.
- **Depends on:** WP-A02 (the provenance fields of `risk_plan`). **Beside:** lanes B, C, E and F.
- **Tests:** R2 tests 1, 2, 3, 5 and 6; the SE-64 property tests. R2 test 4 runs only as a parametrised check against the declared research round trip; no threshold is chosen here.
- **Done:** every SE-40 invariant holds for options a to c, and the legacy option reproduces SE-03 exactly.
- **Accepted:** common criteria only.
- **Gate:** WP2-START. **Choice and activation:** SE-80, then WP-G03. **Analyzer release:** WP-G04.

#### WP-D03 · Pure position state machine
- **Source:** SE-66; WP-IR-06.
- **Class:** Safe development-only correction.
- **Files:** `shared/position_state.py` (new); `tests/test_position_state_machine.py` (new). Parity is tested against `shared/triple_barrier.py` and `shared/partial_exits.py`; both are pinned and stay unchanged.
- **Depends on:** WP-A02. **Beside:** lanes B, C, E and F.
- **Tests:** the SE-66 tests; WP-IT-06. `tests/test_triple_barrier.py` and `tests/test_partial_exits.py` stay green.
- **Done:** the full SE §B6 transition table.
- **Accepted:** parity on synthetic paths, and no runtime import.
- **Gate:** WP2-START.

#### WP-D04 · Cost-model registry
- **Source:** SE-67; SE-44 to SE-46; R8.e (implementation support); WP-IR-07.
- **Class:** Safe development-only correction.
- **Files:** `shared/cost_models.py` (new), holding `legacy_tracker_v1`, `research_baseline_v1` and `research_stress_v1`; `tests/test_cost_models.py` (new). `shared/fees.py` is unchanged.
- **Depends on:** WP-A01. **Beside:** everything except WP-B08, WP-E02 and WP-E07.
- **Tests:**
  - the SE-67 tests: 0.40% and 0.60% round trip for symmetric fills, a stop exit charged once, per-leg notional, agreement with `a48-cost-v1` on synthetic legs;
  - R4 test 1;
  - WP-IT-07.
- **Done:** the registry exists. Its research values are the charter's proposed baseline and stress (`CH:L25`), labelled "proposed".
- **Accepted:** `legacy_tracker_v1` reproduces `shared/fees.py` on fixtures.
- **Gate:** WP2-START. Adoption for any evaluation or for Paper accounting is a **WP3** decision (SE-81, SE-87, OQ-08).

#### WP-D05 · OrderIntent validation and rounding from MarketSnapshot.filters
- **Source:** SE-69; SE-50; PR-18.
- **Class:** Safe development-only correction.
- **Files:** `shared/exchange_rules.py`, which production does not import (SE-09); `tests/test_order_intent_filters.py` (new).
- **Depends on:** WP-A02, WP-B03. **Beside:** lanes C, E and F.
- **Tests:** SE-69; PR-T11; WP-IT-05, for the code `F7.min_notional_infeasible`.
- **Done:** quantity is floored to `stepSize`, and prices are rounded to the tick in the direction that does not improve P&L.
- **Accepted:** an unknown filter is reported as "not modelled", never passed implicitly.
- **Gate:** WP2-START. Wiring into Paper is part of WP-G07.

#### WP-D06 · Hypothesis and benchmark specification drafts
- **Source:** R8.a; R8.b; R8.c; the STRATEGY_AND_EXECUTION_CONTRACT.md §B5 gap list (L255-262); SE-88 (holding ceilings for new versions).
- **Class:** Documentation/design.
- **Files:** `docs/strategy/CANDIDATE_B_SPECIFICATION_DRAFT.md` (new), `docs/strategy/CANDIDATE_C_SPECIFICATION_DRAFT.md` (new), `docs/strategy/BENCHMARKS_SPECIFICATION_DRAFT.md` (new).
- **Depends on:** WP-B05 (selection rule), WP-C02 (identity), WP-D02 (W3 options), WP-D04 (cost basis). **Beside:** lanes E and F.
- **Tests:** R8 test 1 (specification completeness). R8 test 2 applies at preregistration only.
- **Done:**
  - every R8.a field is filled for B and C, and no threshold is presented as proven;
  - `btc_buy_hold`, `cash` and Design A are declared under the same cost model. Design A keeps its benchmark role unless SE-89 admits it as a candidate (`CH:L15`).
- **Accepted:** owner review. Drafts are not preregistrations, and they rank neither candidate (G5-25).
- **Gate:** **WP3 decisions in ERG order 1–5**: OD-DF-2 with G4 Q1, Q2 and Q6; OD-DF-1; G4 Q4 and Q7; the slot plan, with Design A E1–E8 and SE-89; and the candidate prerequisites, including SE-80 (ERG:L127-131). ERG-01 states that "only after those decisions could a candidate be specified" (ERG:L215).

#### WP-D07 · Decision memos for horizon and power, and for the HOLD scope
- **Source:** R8.d; R8.g; OQ-06; CON-36.
- **Class:** Documentation/design.
- **Files:** the corresponding entries of [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md). If that file already carries the OD-DF-2 options with the G4 trade-offs and the OQ-06 question, the task closes by reference. Otherwise it adds a dated addendum.
- **Depends on:** none. **Beside:** everything.
- **Tests:** none.
- **Done:** options are listed with their trade-offs; no choice is made.
- **Accepted:** owner review.
- **Gate:** WP2-START.

### 4.5 Lane E: ledger, accounting and capacity authority

#### WP-E01 · Pure ledger library
- **Source:** PR-C02; R7.b; PORTFOLIO_RISK_AND_COMPOUNDING.md §3.
- **Class:** Safe development-only correction.
- **Files:** `shared/portfolio_ledger.py` (new): `Decimal`, event fold, PR-I1 to PR-I14, state hash, no I/O; `tests/test_portfolio_ledger.py` (new). Patterns are taken from `research/design_a/ledger.py @ ebf8d8a` and `lab/account.py @ c42e6ea`, both unmerged; the patterns transfer, not their sizing rules (PR-24).
- **Depends on:** WP-A01. **Beside:** lanes A to D and F.
- **Tests:** PR-T01 to PR-T08, PR-T11, PR-T16; WP-IT-06; WP-IT-07.
- **Done:** the library exists. The fee asset is the quote currency until PR-OD8 is decided.
- **Accepted:** no import from a runtime service.
- **Gate:** WP2-START.

#### WP-E02 · Legacy-mode adapter and reconciliation
- **Source:** PR-C03; R7.b; PR-I13.
- **Class:** Safe development-only correction.
- **Files:** `shared/ledger_legacy_adapter.py` (new); `tests/test_ledger_legacy_adapter.py` (new); synthetic row fixtures only.
- **Depends on:** WP-E01, WP-D04 (`legacy_tracker_v1`). **Beside:** WP-E03, WP-E06, WP-E08.
- **Tests:** PR-T09, PR-T10, PR-T17.
- **Done:** the PR-07 and PR-17 divergences are reproduced as named discrepancies.
- **Accepted:** fixture reconciliation is exact within quantization.
- **Gate:** WP2-START.

#### WP-E03 · Additive ledger migration on a disposable database
- **Source:** PR-C04; R7.c.
- **Class:** Safe development-only correction.
- **Files:** `database/migrations/012_portfolio_ledger.sql` (new; the number follows `011_a44_signal_setup_key.sql`); `tests/test_ledger_migration_db.py` (new).
- **Depends on:** WP-E01. **Beside:** WP-E02, WP-E06, WP-E08.
- **Tests:** PR-T18.
- **Done:** the migration exists and is tested on a disposable database.
- **Accepted:** it is idempotent and backward compatible. It is never applied to a production database; that is WP-G08 or WP-G28.
- **Gate:** WP2-START. **Rollback:** discard the disposable database.

#### WP-E04 · Shadow ledger writer, default-off
- **Source:** PR-C05; R7.d.
- **Class:** Safe development-only correction.
- **Files:** lifecycle hooks behind a flag in `trade_tracker/main.py`; `shared/config.py`; `tests/test_shadow_ledger_writer.py` (new).
- **Depends on:** WP-E02, WP-E03. **Beside:** WP-E06 to WP-E08.
- **Tests:** PR-T02, PR-T04, PR-T09, PR-T19.
- **Done:** with the flag on in tests, only ledger rows are added.
- **Accepted:** admissions, `trade_results` rows and outbox events are identical with the writer off and on.
- **Gate:** PR-OD1 (genesis) and PR-OD2 (genesis amount). **Activation:** WP-G28.

#### WP-E05 · Daily UTC mark-to-market series from the shadow ledger
- **Source:** PR-C12; R7.e; PR-22.
- **Class:** Safe development-only correction.
- **Files:** `shared/portfolio_ledger.py` (daily snapshot function); `tests/test_daily_equity_series.py` (new).
- **Depends on:** WP-E04. **Beside:** WP-E06, WP-E07.
- **Tests:** PR-T16; PR-T19.
- **Done:** one value per UTC day, or `UNKNOWN`.
- **Accepted:** the series is reproducible from the entry log and the marks.
- **Gate:** PR-OD6 and the **WP3 endpoint decision** (OD-DF-2). The approved A29 endpoint stays unless the owner formally changes it (`CH:L52`); its benchmark leg is WP3 (PORTFOLIO_RISK_AND_COMPOUNDING.md §3.5, L312).

#### WP-E06 · Net-labelled counters beside the legacy gross counters
- **Source:** PR-C14; R7.f; R4.d; CON-09.
- **Class:** Safe development-only correction.
- **Files:**
  - `trade_tracker/main.py`, where the counter writes are (`trade_tracker/main.py:L1371-1379 @ bb7825f`); the new counters are additive and flagged;
  - the labels of the `/status` and `/stats` fields in `telegram/main.py`;
  - `tests/test_counter_basis.py` (new).
  
  Any new column joins the WP-E03 migration.
- **Depends on:** WP-A01. **Beside:** lanes A to D and F.
- **Tests:** PR-T17; R4 test 4.
- **Done:** every counter names its basis.
- **Accepted:** the legacy gross columns are unchanged and labelled.
- **Gate:** WP2-START.

#### WP-E07 · Single-count, per-leg costs under a new label_policy
- **Source:** R4.a; R4.e; SE-45; PR-I11.
- **Class:** Safe development-only correction.
- **Files:** `shared/cost_models.py` (per-leg booking); `shared/portfolio_ledger.py` (cost-model folds); `tests/test_single_count_costs.py` (new).
- **Depends on:** WP-E01, WP-D04. **Beside:** WP-E04 to WP-E06.
- **Tests:** R4 tests 1–4; PR-T05; PR-T15.
- **Done:** a stop exit is charged its slippage once; the fee is per side on each leg's notional.
- **Accepted:** the legacy fields are byte-identical, and history is never rewritten.
- **Gate:** WP2-START. **Runtime accounting change:** WP-G07. **Deploying the fields:** WP-G08.

#### WP-E08 · Capacity authority in legacy mode (shadow)
- **Source:** WP-IR-03; the PORTFOLIO_RISK_AND_COMPOUNDING.md §5 legacy mode (`legacy_v1`, L500-502); PR-14; the OPPORTUNITY_FUNNEL.md §12 note (L542-547).
- **Class:** Safe development-only correction.
- **Files:** `shared/capacity_authority.py` (new). It wraps `evaluate_new_trade`; `shared/risk_management.py` stays byte-identical. Also `tests/test_capacity_authority.py` (new); `tests/test_risk_management.py` and `tests/test_paper_observe_capacity.py` stay green.
- **Depends on:** WP-A01. **Beside:** WP-E01 to WP-E03, lanes A to D and F.
- **Tests:** WP-IT-03; PR-T09.
- **Done:** one function returns "admit" or `F7.capacity_full`, with its inputs. In shadow, the delivery and tracker pre-checks are compared with it as mirrors.
- **Accepted:** the legacy result is byte-identical on golden grids.
- **Gate:** WP2-START. **Target-mode inputs and activation:** PR-OD16 and PR-OD21, then WP-G23.

#### WP-E09 · Side-by-side cost reporting specification
- **Source:** R4.c; OQ-08; STRATEGY_AND_EXECUTION_CONTRACT.md §C4.
- **Class:** Documentation/design.
- **Files:** `docs/design/COST_REPORTING_SIDE_BY_SIDE.md` (new).
- **Depends on:** none. **Beside:** everything.
- **Tests:** none.
- **Done:** every reported net figure names its `cost_model_id` and `label_policy`. The runtime 0.30% and the research 0.40% and 0.60% are shown side by side and never pooled (DFP:L61).
- **Accepted:** owner review.
- **Gate:** WP2-START.

### 4.6 Lane F: operations health, runbooks and records

#### WP-F01 · Runbook and CLAUDE.md dated corrections
- **Source:** R9.c; CON-01, CON-08, CON-11; BL-17, BL-18; the stale PAPER_HALTED statement.
- **Class:** Documentation/design.
- **Files:** dated notes in `docs/ops/COMPOSE_OPERATIONS.md`, at the pin paragraph (`docs/ops/COMPOSE_OPERATIONS.md:L40-48 @ 46578aa`), and in `CLAUDE.md` (`CLAUDE.md:L3, L37, L48 @ 46578aa`). No history is rewritten.
- **Depends on:** none. **Beside:** everything.
- **Tests:** none here. WP-F03 test 1 turns green once these notes land.
- **Done:** each stale statement carries a dated correction.
- **Accepted:** owner review and independent review, because these files define production operations (DFP:L73).
- **Gate:** WP2-START.

#### WP-F02 · Learner and optimizer build-hazard design
- **Source:** R9.d; ARC-18 to ARC-20; LRN-19.
- **Class:** Documentation/design.
- **Files:** `docs/ops/LEARNER_BUILD_HAZARD_DESIGN.md` (new). It describes the proposed `docker-compose.yml` change: the learner pinned to a released image or without `build:`, and a boundary record required before `LEARNING_GATES_ENABLED` can be set. The Compose file itself is not changed.
- **Depends on:** none. **Beside:** everything.
- **Tests:** none.
- **Done:** the design names every service that builds from the working tree and the guard for each.
- **Accepted:** owner review. Nothing is deleted without a named approval.
- **Gate:** WP2-START.

#### WP-F03 · Static guards
- **Source:** R9.d2; R9 tests 1–3.
- **Class:** Safe development-only correction.
- **Files:** `tests/test_runbook_pin_parity.py` (new); `tests/test_compose_safe.py` (extended); `tests/test_learning_gates_boundary_guard.py` (new). `ops/compose-safe` is a read-only reference.
- **Depends on:** WP-F01 and WP-F02. By design, test 1 fails until the runbook is corrected. **Beside:** lanes A to E.
- **Tests:** R9 tests 1–3.
- **Done:** all three guards exist.
- **Accepted:** all three are green after WP-F01.
- **Gate:** WP2-START.

#### WP-F04 · Collector health-tiering review and port
- **Source:** R9.a2. The input is five default-off commits on the unmerged branch `integration/rnd`: `dfa8f65`, `d23be24`, `3693017`, `b225472` and `44ae384` (BL-08).
- **Class:** Safe development-only correction.
- **Files:** the `p2_forward/` modules those commits touch, and `p2_forward/tests/test_health_view.py`, `p2_forward/tests/test_monitor_episodes.py` and `p2_forward/tests/test_backup_existing.py`. These test files exist on `integration/rnd`; they are new on the development branch.
- **Depends on:** none. **Beside:** everything.
- **Tests:** R9 test 4.
- **Done:** review notes, and a port onto the development branch with every default off.
- **Accepted:** the collector's own synthetic suites are green. Integration is the owner's decision.
- **Gate:** WP2-START. The collector operation itself (R9.a) is WP-G31.

#### WP-F05 · Health fields in the observation record
- **Source:** R9.f; RT-35; RT-44.
- **Class:** Safe development-only correction.
- **Files:** `ops/provenance/drift_check.py` (its observe and validate paths); `deploy/DEPLOYED.md` (schema text); `tests/test_drift_check.py` (extended).
- **Depends on:** none. **Beside:** everything.
- **Tests:** the extended drift-check tests on synthetic records.
- **Done:** the schema accepts a health state and a redaction-safe count of warning categories. No observation is made.
- **Accepted:** existing records still validate.
- **Gate:** WP2-START.

#### WP-F06 · Historical marker for docker-compose.yml.bak
- **Source:** R9.g; ARC-18.
- **Class:** Documentation/design.
- **Files:** `docs/ops/COMPOSE_BAK_HISTORICAL_NOTE.md` (new), a dated note. `docker-compose.yml.bak` is neither edited nor deleted; deletion needs a named approval.
- **Depends on:** none. **Beside:** everything.
- **Tests:** none.
- **Done:** the note records that the file still defines `claude_review` and is historical.
- **Accepted:** owner review.
- **Gate:** WP2-START.

#### WP-F07 · Record notes: lineage labels, record corrections, boundary-amendment preparation
- **Source:** R5.g; R5.h (CON-04, CON-06, CON-07); R5.e.
- **Class:** Documentation/design.
- **Files:** `docs/design/LINEAGE_AND_RECORD_NOTES.md` (new). Amendment text for `deploy/VERSION_BOUNDARY.md` is prepared for owner review only.
- **Depends on:** none. **Beside:** everything.
- **Tests:** none.
- **Done:** every historical figure the pack cites carries its version window, with no pooling (G2). Each record discrepancy has a dated note.
- **Accepted:** owner review.
- **Gate:** WP2-START. The R5.e part also needs owner review of amendments A1 (`4ba6cad`) and A2 (`d1184c8`), whose content may carry protected identifiers (OD-7; BL-10); integrating them is the owner's merge decision.

## 5. Coverage of every proposed change

Every proposed change in the five pack documents maps to exactly one place: a WP task (section 4), a gated item (section 6), or a WP1 deliverable that is already complete in a pack document. "Slice + G" means a default-off implementation task plus the gated activation.

### 5.1 Opportunity funnel (OF-T)

| Change | Where | Change | Where | Change | Where |
|---|---|---|---|---|---|
| OF-T01 | WP-B01 | OF-T06 | WP-B09 + WP-G16 | OF-T11 | WP-B06 + WP-G02 |
| OF-T02 | WP-B02 | OF-T07 | WP-B10 + WP-G13 | OF-T12 | WP-B12, WP-B13 + WP-G17 |
| OF-T03 | WP-B03 | OF-T08 | WP-B11 + WP-G12 | OF-T13 | WP-B04 (enabling: WP-G19) |
| OF-T04 | WP-B07 + WP-G14 | OF-T09 | WP-C02, WP-C03, WP-C05 + WP-G05 | OF-T14 | WP-G18 |
| OF-T05 | WP-B08 + WP-G15 | OF-T10 | WP-B05 + WP-G01 | OF-T15 | WP-G19 |

### 5.2 Strategy and execution contract (SE-60 to SE-75)

| Change | Where | Change | Where | Change | Where |
|---|---|---|---|---|---|
| SE-60 | WP-A01 | SE-66 | WP-D03 | SE-72 | WP-A01 |
| SE-61 | WP-A02 | SE-67 | WP-D04 | SE-73 | WP-G09 |
| SE-62 | WP-D01 | SE-68 | WP-G07 | SE-74 | WP-G30 |
| SE-63 | WP-A03 | SE-69 | WP-D05 | SE-75 | WP1 deliverable (SE-83 and the register bundling decision; consolidated in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md)) |
| SE-64 | WP-D02 | SE-70 | WP-A05 (enabling: WP-G19) | | |
| SE-65 | WP-G03 | SE-71 | WP-A04 | | |

### 5.3 Portfolio, risk and compounding (PR-C)

| Change | Where | Change | Where | Change | Where |
|---|---|---|---|---|---|
| PR-C01 | WP1 deliverable ([PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md)) | PR-C07 | WP-G21 | PR-C13 | WP-G26 |
| PR-C02 | WP-E01 | PR-C08 | WP-G22 | PR-C14 | WP-E06 |
| PR-C03 | WP-E02 | PR-C09 | WP-G23 (legacy-mode shadow: WP-E08) | PR-C15 | WP-G27 |
| PR-C04 | WP-E03 | PR-C10 | WP-G24 | PR-C16 | WP-G28 |
| PR-C05 | WP-E04 | PR-C11 | WP-G25 | | |
| PR-C06 | WP-G20 | PR-C12 | WP-E05 | | |

### 5.4 Remediation register sub-items (R1 to R9)

| Item | Sub-items and where they go |
|---|---|
| R1 | R1.a: WP1 deliverable (OPPORTUNITY_FUNNEL.md F6); R1.b: WP-B05; R1.c: WP-G01; R1.d: WP-A01 and WP-B05; R1.e: WP-A01 and WP-B06; R1.f: WP-B01 |
| R2 | R2.a: WP1 deliverable (STRATEGY_AND_EXECUTION_CONTRACT.md §B8 and SE-80); R2.b: WP-D02; R2.c: WP-A02; R2.d: WP-G04; R2.e: WP-G03 |
| R3 | R3.a: WP-G05; R3.b: WP-C04 + WP-G05; R3.c: WP-B10 + WP-G13; R3.d: WP-C02; R3.e: WP-C01; R3.f: WP-C03 |
| R4 | R4.a: WP-E07; R4.b: WP-G06; R4.c: WP-E09; R4.d: WP-E06; R4.e: WP-E07; R4.f: WP-G08 |
| R5 | R5.a: WP-G09; R5.b: WP-A06; R5.c: WP-G10; R5.d: WP-A01 (specification) and WP-A02 (code); R5.e: WP-F07; R5.f: WP-G11; R5.g: WP-F07; R5.h: WP-F07 |
| R6 | R6.a: WP-B01; R6.b: WP-B02; R6.c: WP-B01; R6.d: WP-B11 + WP-G12; R6.e: WP-B10 + WP-G13; R6.f: WP-B07 + WP-G14; R6.g: WP-G18; R6.h: WP-G19 |
| R7 | R7.a: WP1 deliverable (PR-C01); R7.b: WP-E01, WP-E02; R7.c: WP-E03; R7.d: WP-E04; R7.e: WP-E05; R7.f: WP-E06; R7.g: WP-G21; R7.h: WP-G22 to WP-G26; R7.i: WP-G27; R7.j: WP-G28 |
| R8 | R8.a, R8.b, R8.c: WP-D06; R8.d: WP-D07; R8.e: WP1 deliverable (STRATEGY_AND_EXECUTION_CONTRACT.md §C2, §C4) with code in WP-D04; R8.f: WP-G29; R8.g: WP-D07 |
| R9 | R9.a: WP-G31; R9.a2: WP-F04; R9.b: WP-G32; R9.c: WP-F01; R9.d: WP-F02; R9.d2: WP-F03; R9.d3: WP-G33; R9.e: WP-G34; R9.f: WP-F05; R9.g: WP-F06 |

**Counts.** 47 schedulable tasks: 37 Safe development-only corrections and 10 Documentation/design tasks. Section 6 holds 34 gated items. No proposed change is unplaced.

## 6. Gated items not scheduled

Nothing in this table is scheduled, started or authorized by this plan. Every row keeps the change class its source document gives it.

**How to read the gate column.**
- **"WP5 (WP3 if evidential)".** A Strategy-version-changing activation in Paper needs an owner-declared window (D2, DFP:L43), a `VERSION_BOUNDARY` entry and deployment approval (WP5). If the window is meant to produce governed evidence, the WP3 decisions (preregistration, slots, endpoint, cost and fill model) must come first (`CH:L52`).
- **"WP3 → WP4".** Protected research or simulation runs only in WP4, after its WP3 permissions (`CH:L53`).
- **"WP5 operation".** A Production/runtime change is a separately approved operation under the Class A/B/C rules (DFP:L45; OOC:L18).

**Merging** any WP2 commit into `main` is not a change-class item. It is an owner decision outside this plan (DFP:L41).

| ID | Item | Class | Blocking decisions (source IDs) | Gate | Prerequisite tasks |
|---|---|---|---|---|---|
| WP-G01 | R1.c / OF-T10: activate rank-then-limit selection in Paper | Strategy-version-changing correction | OQ-09; OF-OD-15; OF-OD-01; SE-83 and the register bundling decision | WP5 (WP3 if evidential) | WP-A02, WP-A03, WP-B01, WP-B05, WP-C02 |
| WP-G02 | OF-T11: contract score replaces the execution-quality key; `total_score` leaves the ordering | Strategy-version-changing correction | OF-OD-14; OQ-09; SE-83 | WP5 (WP3 if evidential) | WP-B06, WP-D01 |
| WP-G03 | R2.e / SE-65: activate a W3 option (`momentum_breakout 2.0.0`) | Strategy-version-changing correction | SE-80; SE-83 | WP5 (WP3 if evidential) | WP-A02, WP-A03, WP-C05, WP-D02; WP-G04 |
| WP-G04 | R2.d: analyzer release built from a commit containing `a4a7561`, at the legacy default | Production/runtime change | Class B approval; R2 owner gates | WP5 operation | WP-A06. The register puts runtime verification (WP-G09) in tier P1, before any activation |
| WP-G05 | R3.a, R3.b, OF-T09: insert-once identity and admission by `setup_key` in Paper | Strategy-version-changing correction | the boundary choice prepared by WP-C01; SE-84; SE-83; OF-OD-13 | WP5 (WP3 if evidential) | WP-B01, WP-C01 to WP-C05 |
| WP-G06 | R4.b: break-even stop computed from the declared cost contract | Strategy-version-changing correction | OQ-08; SE-82; SE-83 | WP5 (WP3 if evidential) | WP-D03, WP-D04, WP-E07 |
| WP-G07 | SE-68, with SE-69 wiring: Paper accounting books slippage once, on per-leg notional, with optional spread and exchange rounding | Strategy-version-changing correction | OQ-08; SE-82; PR-OD7 | WP5 (WP3 if evidential) | WP-D05, WP-E04, WP-E06, WP-E07 |
| WP-G08 | R4.f: deploy the R4.a ledger fields | Production/runtime change | Class B approval; OQ-08 | WP5 operation | WP-E03, WP-E07 |
| WP-G09 | R5.a / SE-73: image-content verification per service (read-only, outside Class A) | Production/runtime change | OQ-03; SE-85; VER-28 item 1 | WP5 operation; register tier P1 | none |
| WP-G10 | R5.c: scanner release built from one commit | Production/runtime change | Class B approval | WP5 operation | WP-A06 |
| WP-G11 | R5.f: metadata-only read of the pause-decision history | Production/runtime change | owner approval for R5.f; OQ-01 scope | WP5 operation | none |
| WP-G12 | R6.d / OF-T08: freshness bound and venue-synchronised closed bars in Paper | Strategy-version-changing correction | OF-OD-12 | WP5 (WP3 if evidential) | WP-B11 |
| WP-G13 | R6.e / OF-T07 / R3.c: explicit failure semantics in Paper | Strategy-version-changing correction | OF-OD-10; OF-OD-11; WP-OD-01 | WP5 (WP3 if evidential) | WP-B10 |
| WP-G14 | R6.f / OF-T04: `EligibilityResult` rules in Paper | Strategy-version-changing correction | OF-OD-01 to OF-OD-05; OQ-07 | WP5 (WP3 if evidential) | WP-B07 |
| WP-G15 | OF-T05: liquidity, spread, depth and feasibility rules in Paper | Strategy-version-changing correction | OF-OD-06 to OF-OD-08 | WP5 (WP3 if evidential) | WP-B08 |
| WP-G16 | OF-T06: single BTC trend in `RegimeContext` in Paper | Strategy-version-changing correction | OF-OD-09 to OF-OD-11 | WP5 (WP3 if evidential) | WP-B09 |
| WP-G17 | OF-T12: F7 hand-off in Paper (rank-order offering, recorded refusals) | Strategy-version-changing correction | OF-OD-16; OF-OD-13; WP-OD-02; the runbook required by DFP:L104 | WP5 (WP3 if evidential) | WP-B12, WP-B13, WP-E08 |
| WP-G18 | R6.g / OF-T14: measure how often each funnel drop occurred | Protected research or simulation | OF-OD-17; OD-DF-1; OD-7 | WP3 → WP4 | WP-B01 |
| WP-G19 | R6.h / OF-T15: enable the funnel writers and records on the host, including the SE-70 and OF-T13 records | Production/runtime change | OF-OD-18; window declaration; DFP:L104 where admission is touched | WP5 operation | WP-A05, WP-B01 to WP-B04 |
| WP-G20 | PR-C06: mark records and the `mark_stale` refusal | Strategy-version-changing correction | PR-OD3; PR-OD4; PR-OD5 | WP5 (WP3 if evidential) | WP-E04 |
| WP-G21 | R7.g / PR-C07: risk inputs taken from the ledger | Strategy-version-changing correction | PR-OD7; PR-OD22 | WP5 (WP3 if evidential) | WP-E04, WP-E07 |
| WP-G22 | R7.h / PR-C08: `SizingDecision` engine (realized-net sizing base, settlement, caps) | Strategy-version-changing correction | PR-OD9; PR-OD13; PR-OD14; PR-OD19 | WP3 → WP5: sizing belongs to the version contract and is fixed before any governed window (PORTFOLIO_RISK_AND_COMPOUNDING.md §4.7, L486) | WP-D05, WP-E01, WP-E04 |
| WP-G23 | PR-C09: exposure, heat and slot caps on ledger values, i.e. the capacity authority of WP-IR-03 in target mode | Strategy-version-changing correction | PR-OD10; PR-OD12; PR-OD15; PR-OD16; PR-OD21 | WP3 → WP5 | WP-E08; WP-G22 |
| WP-G24 | PR-C10: correlated-cluster exposure | Strategy-version-changing correction | PR-OD11; PR-OD12 | WP3 → WP5 | WP-E01 |
| WP-G25 | PR-C11: capital reservation for working entry intents | Strategy-version-changing correction | PR-OD17 | WP3 → WP5 | WP-E01 |
| WP-G26 | PR-C13: high-water mark, de-risking ladder, period windows, recovery-epoch handling | Strategy-version-changing correction | PR-OD18; PR-OD20; PR-OD21; PR-OD22 | WP3 → WP5 | WP-E04 |
| WP-G27 | R7.i / PR-C15: shadow valuation under the 0.40% and 0.60% models | Protected research or simulation | OD-DF-1 for any protected data; SE-81 | WP3 → WP4 | WP-D04, WP-E07 |
| WP-G28 | R7.j / PR-C16: activation in Paper of PR-C05 to PR-C14 (flag, migration, image) | Production/runtime change | PR-OD1; PR-OD2; a version-boundary record | WP5 operation | WP-E03 to WP-E06 |
| WP-G29 | R8.f: any evaluation of Candidate B, Candidate C or another hypothesis | Protected research or simulation | OD-DF-1; OD-DF-2; G4 Q3 to Q7; the slot plan with SE-89 and E1–E8; a preregistration approval | WP3 → WP4 | WP-D04, WP-D06, WP-E05 |
| WP-G30 | SE-74: level-3 execution calibration from a forward capture | Protected research or simulation | SE-86 | WP3 → WP4 | WP-D03, WP-D04 |
| WP-G31 | R9.a: read collector incident metadata and decide its remediation | Production/runtime change | OQ-04 | WP5 operation | WP-F04 |
| WP-G32 | R9.b: decision on the stale production checkout | Production/runtime change | OQ-05 | WP5 operation | WP-F02 |
| WP-G33 | R9.d3: install the learner Compose change | Production/runtime change | a named approval; `config --hash` verification | WP5 operation | WP-F02, WP-F03 |
| WP-G34 | R9.e: backup model and one isolated restore test | Production/runtime change | OD-DF-4 | WP5 operation | none |

**Where WP4 blocks.** No schedulable task waits for WP4. WP4 blocks only WP-G18, WP-G27, WP-G29 and WP-G30.

## 7. Dependency graph and critical path

### 7.1 Dependency table

Every task also needs WP2-START. "Unblocks (gated)" lists the section 6 items for which the task is a prerequisite; those items still need their own decisions and gates. Points where a **WP3** decision blocks a schedulable task are in bold.

| Task | Depends on | Unblocks (tasks) | Unblocks (gated) | Owner gate before start |
|---|---|---|---|---|
| WP-A01 | — | WP-A02, WP-B01, WP-B03, WP-D04, WP-E01, WP-E06, WP-E08 | — | WP2-START |
| WP-A02 | WP-A01 | WP-A03, WP-A04, WP-A05, WP-B01, WP-B05, WP-B09, WP-C02, WP-C05, WP-D01, WP-D02, WP-D03, WP-D05 | WP-G01, WP-G03 | WP2-START |
| WP-A03 | WP-A02 | — | WP-G01, WP-G03 | WP2-START |
| WP-A04 | WP-A02 | — | — | WP2-START |
| WP-A05 | WP-A02 | WP-B04 | WP-G19 | WP2-START |
| WP-A06 | — | — | WP-G04, WP-G10 | WP2-START |
| WP-B01 | WP-A01, WP-A02 | WP-B02, WP-B04, WP-B05, WP-B07, WP-B08, WP-B09, WP-B10, WP-B11, WP-B12, WP-C04 | WP-G01, WP-G05, WP-G18, WP-G19 | WP2-START; WP-OD-01 for the pinned-file hooks |
| WP-B02 | WP-B01 | — | WP-G19 | WP-OD-01 |
| WP-B03 | WP-A01 | WP-B04, WP-B07, WP-B08, WP-B11, WP-D05 | WP-G19 | WP2-START |
| WP-B04 | WP-A05, WP-B01, WP-B03 | — | WP-G19 | WP2-START |
| WP-B05 | WP-A02, WP-B01, WP-C02 | WP-B06, WP-B12, WP-D06 | WP-G01 | WP2-START; WP-OD-01 for a pinned-file hook |
| WP-B06 | WP-B05, WP-D01 | — | WP-G02 | OF-OD-14; OQ-09 |
| WP-B07 | WP-B01, WP-B03 | — | WP-G14 | OF-OD-01 to OF-OD-05; OQ-07 |
| WP-B08 | WP-B01, WP-B03, WP-D04 | — | WP-G15 | OF-OD-06 to OF-OD-08 |
| WP-B09 | WP-A02, WP-B01 | WP-B10 | WP-G16 | OF-OD-09 to OF-OD-11 |
| WP-B10 | WP-B01, WP-B09 | — | WP-G13 | OF-OD-10; WP-OD-01 |
| WP-B11 | WP-B01, WP-B03 | — | WP-G12 | OF-OD-12 |
| WP-B12 | WP-B01, WP-B05, WP-C04, WP-E08 | — | WP-G17 | OF-OD-16; OF-OD-13; WP-OD-02 |
| WP-B13 | — | — | WP-G17 | WP2-START |
| WP-C01 | — | — | WP-G05 | WP2-START |
| WP-C02 | WP-A02 | WP-B05, WP-C03, WP-C04, WP-C05, WP-D06 | WP-G01, WP-G05 | SE-84 |
| WP-C03 | WP-C02 | — | WP-G05 | WP2-START |
| WP-C04 | WP-B01, WP-C02 | WP-B12 | WP-G05 | WP2-START |
| WP-C05 | WP-A02, WP-C02 | — | WP-G03, WP-G05 | WP2-START |
| WP-D01 | WP-A02 | WP-B06 | WP-G02 | WP2-START |
| WP-D02 | WP-A02 | WP-D06 | WP-G03 | WP2-START |
| WP-D03 | WP-A02 | — | WP-G06, WP-G30 | WP2-START |
| WP-D04 | WP-A01 | WP-B08, WP-D06, WP-E02, WP-E07 | WP-G06, WP-G27, WP-G29, WP-G30 | WP2-START |
| WP-D05 | WP-A02, WP-B03 | — | WP-G07, WP-G22 | WP2-START |
| WP-D06 | WP-B05, WP-C02, WP-D02, WP-D04 | — | WP-G29 | **WP3**: ERG order 1–5 (OD-DF-2, OD-DF-1, G4 Q4/Q7, slot plan with SE-89, candidate prerequisites with SE-80) |
| WP-D07 | — | — | — | WP2-START |
| WP-E01 | WP-A01 | WP-E02, WP-E03, WP-E07 | WP-G22, WP-G24, WP-G25 | WP2-START |
| WP-E02 | WP-E01, WP-D04 | WP-E04 | — | WP2-START |
| WP-E03 | WP-E01 | WP-E04 | WP-G08, WP-G28 | WP2-START |
| WP-E04 | WP-E02, WP-E03 | WP-E05 | WP-G07, WP-G20, WP-G21, WP-G22, WP-G26, WP-G28 | PR-OD1; PR-OD2 |
| WP-E05 | WP-E04 | — | WP-G28, WP-G29 | PR-OD6; **WP3** endpoint decision (OD-DF-2) |
| WP-E06 | WP-A01 | — | WP-G07, WP-G28 | WP2-START |
| WP-E07 | WP-E01, WP-D04 | — | WP-G06, WP-G07, WP-G08, WP-G21, WP-G27 | WP2-START |
| WP-E08 | WP-A01 | WP-B12 | WP-G17, WP-G23 | WP2-START |
| WP-E09 | — | — | — | WP2-START |
| WP-F01 | — | WP-F03 | — | WP2-START |
| WP-F02 | — | WP-F03 | WP-G32, WP-G33 | WP2-START |
| WP-F03 | WP-F01, WP-F02 | — | WP-G33 | WP2-START |
| WP-F04 | — | — | WP-G31 | WP2-START |
| WP-F05 | — | — | — | WP2-START |
| WP-F06 | — | — | — | WP2-START |
| WP-F07 | — | — | — | WP2-START; owner review of A1/A2 (OD-7) for the R5.e part |

### 7.2 Critical path

The longest dependency chains have five tasks. Measured to "all schedulable tasks ready for owner review", the binding chain is the one that ends in a WP3 decision:

**WP2-START → WP-A01 → WP-A02 → WP-C02 (needs SE-84) → WP-B05 (WP-OD-01 for its pinned-file hook) → WP-D06 (blocked until the WP3 decisions in ERG order 1–5).**

Four other chains have the same length and meet owner decisions rather than WP3:

| Chain | Owner decisions on it | WP3 or WP4 block |
|---|---|---|
| WP-A01 → WP-E01 → WP-E02 or WP-E03 → WP-E04 → WP-E05 (also WP-A01 → WP-D04 → WP-E02) | PR-OD1, PR-OD2 at WP-E04; PR-OD6 at WP-E05 | **WP3** endpoint decision (OD-DF-2) at WP-E05 |
| WP-A01 → WP-A02 → WP-C02 → WP-C04 → WP-B12 | SE-84; OF-OD-16, OF-OD-13, WP-OD-02 at WP-B12 | none |
| WP-A01 → WP-A02 → WP-B01 → WP-B05 → WP-B06 | WP-OD-01; OF-OD-14, OQ-09 at WP-B06 | none |
| WP-A01 → WP-A02 → WP-B01 → WP-B09 → WP-B10 | OF-OD-09 to OF-OD-11; OF-OD-10 and WP-OD-01 at WP-B10 | none |

**Blocking points, explicitly.**
- **WP3 blocks** exactly two schedulable tasks:
  - WP-D06, which waits for OD-DF-2, OD-DF-1, G4 Q4 and Q7, the slot plan (Design A E1–E8 and SE-89) and the candidate prerequisites, including SE-80 (ERG:L127-131, L215);
  - WP-E05, which waits for the endpoint decision and its benchmark leg.
  
  WP3 also gates the adoption, but not the construction, of WP-D04's research models (SE-81, SE-87, OQ-08).
- **WP4 blocks** no schedulable task; it blocks WP-G18, WP-G27, WP-G29 and WP-G30 only.
- **WP-OD-01** is the most widely binding design decision: it gates the pinned-file slices of WP-B01, WP-B02, WP-B05 and WP-B10.

**What can start the day WP2-START is given.**
- No further decision needed: WP-A01, WP-A06, WP-B13, WP-C01, WP-D07, WP-E09, WP-F01, WP-F02, WP-F04, WP-F05, WP-F06 and WP-F07, the last except for its R5.e part.
- After WP-A01: WP-B03, WP-D04, WP-E01, WP-E06 and WP-E08.

The engineering work is short compared with the decision path. The plan's duration is set by owner decisions, not by implementation. No effort or calendar estimate is given (WP-NV-3).

## 8. Interface reconciliation

The pack documents were written in parallel and name some interfaces differently. This section fixes **one canonical name or rule for each divergence**. For each one it gives: the divergence with citations; the canonical choice; the rationale; the wording it supersedes; and the test that enforces it.

**Scope of "supersede".** It is interface-level only. At `5cd1a61` the five documents were not edited. On 2026-11-01 the WP2 reconciliation aligned OPPORTUNITY_FUNNEL.md, STRATEGY_AND_EXECUTION_CONTRACT.md, PORTFOLIO_RISK_AND_COMPOUNDING.md and REMEDIATION_REGISTER.md with this section. Where any wording still differs, implementation tasks follow this section. WP-A01 records the result as the WP2 interface baseline for owner review. Pack citations below are file, section and line numbers of the pack at `5cd1a61`, so the divergences describe the text before that alignment. Their class is DOCUMENTED_ONLY (design text) unless a code citation is given.

### WP-IR-01 · RejectionRecord stage and reason-code names

**Divergence.**
- STRATEGY_AND_EXECUTION_CONTRACT.md §B3 defines its own record (L195-203):
  - `stage` is a free string with the values `strategy.input`, `strategy.regime`, `strategy.entry` and `strategy.geometry` (L197, L215);
  - `symbol`, `timeframe` and `strategy_id` are non-null; `as_of` is an integer;
  - its codes come from the contract clause (L215), SE-52 (L498), SE-40 (L345-346), SE-42 (L311) and the §B6 transitions (L295-299).
- OPPORTUNITY_FUNNEL.md §8.1 (L368-391) defines a different shape:
  - `stage` ∈ F0 … F7, plus a `sub_stage` field added for strategy-contract stage names (L375);
  - subject fields are nullable by scope (L378-383); `as_of` is a timestamp (L384);
  - codes are `stage.reason` from a closed taxonomy (L393-408).
- The two meet in OF's alignment table (L410-416). It keeps the SE codes in `reason_code` while naming the funnel code each "stands in for", so one drop can carry two codes.
- OF is also inconsistent with itself. The table files `strategy.regime` under F4 with `regime_veto:<series>` (L415), a code its own taxonomy lists under F3 (L402).

**Canonical choice.**
1. **Schema.** OPPORTUNITY_FUNNEL.md §8.1 is the schema.
2. **`stage`.** `stage` ∈ {F0 … F7} is the stage at which the record is counted for conservation (OF §8.3).
3. **`reason_code`.** `reason_code` comes from **one closed enumeration**, written `F<n>.<reason>`, and its prefix always equals `stage`.
4. **`sub_stage`.** `sub_stage` is a closed enumeration:
   - `strategy.input`, `strategy.regime`, `strategy.entry` and `strategy.geometry` for records that a strategy's `evaluate` returns;
   - `shared.identity`, `shared.sizing`, `shared.order_intent` and `shared.admission` for shared producers;
   - null for funnel rules.
5. **The strategy's own code.** It is kept verbatim in `detail.strategy_code`. It is never rewritten and never used as the aggregation key.
6. **Field types.** All times are integer UTC epoch milliseconds, the SE §B3 convention, consistent with the UTC rule PR-I14. Subject fields are nullable by scope, as in OF L378-383.

**Rationale.**
- Per-reason counters and the conservation equations (OF §8.3; R6 tests 1–2) need exactly one aggregation key per drop.
- R6 test 2 requires a closed enumeration.
- Keeping the strategy code in `detail` honours OF's rule that "a reason is never rewritten" (L410).
- The F4 regime clash is resolved by separating two different events. A strategy's own regime routing, such as `classify_regime` returning a label the strategy does not accept, is one event. A declared context-series veto applied by F3 is the other.

**Mapping: SE name → canonical.**

| SE stage or code (source) | Canonical `stage` | Canonical `reason_code` | `sub_stage` | Note |
|---|---|---|---|---|
| `strategy.input` / `incomplete_candles` (SE L215; SE-52) | F4 | `F4.data_quality` | `strategy.input` | |
| `strategy.input` / `insufficient_history` (SE L215); research `NOT_ELIGIBLE_INSUFFICIENT_HISTORY` (SE-52) | F4 | `F4.history_insufficient` | `strategy.input` | |
| research `REJECT_DATA_QUALITY` (SE-52) | F4 | `F4.data_quality` | `strategy.input` | |
| `strategy.input` / `stale_regime` (SE L215) | F4 | `F4.regime_stale` (new) | `strategy.input` | candidate scope; the cycle-level record stays `F3.regime_stale` |
| `strategy.regime`; research `REJECT_REGIME` (SE L197; SE-52) | F4 | `F4.regime_not_accepted` (new) | `strategy.regime` | `F3.regime_veto:<series>` stays reserved for a declared context-series veto |
| `strategy.entry`; research `REJECT_ENTRY` (SE-52) | F4 | `F4.no_setup` | `strategy.entry` | legacy label `no_trade_setup` |
| `strategy.geometry` / `structural_risk_exceeds_cap` (SE-42, L311); research `REJECT_STOP_DISTANCE` (SE-52) | F5 | `F5.stop_risk_above_cap` | `strategy.geometry` | legacy label `stop_rejected:<reason>` |
| `strategy.geometry` / `invalid_geometry` (SE-40, L345) | F5 | `F5.bracket_invalid` | `strategy.geometry` | |
| `strategy.geometry` / `t1_not_cost_feasible` (SE-40, L346) | F5 | `F5.t1_not_cost_feasible` (new) | `strategy.geometry` | used only if SE-80 chooses "reject"; distinct from `F5.cost_above_budget` |
| missing stop plan (SE-40; OF F5) | F5 | `F5.stop_missing` | `strategy.geometry` | |
| `duplicate_setup_key` (SE-52, L498) | F4 | `F4.duplicate_setup` | `shared.identity` | a different bracket on the same key is `F4.setup_conflict` |
| `bar_before_version_activation` (SE-36, L248; SE-52) | F4 | `F4.bar_before_version_activation` (new) | `shared.identity` | |
| `signal_invalidated_before_fill` (SE §B6, L295) | F7 | `F7.entry_rejected` | `shared.order_intent` | `detail.rule` keeps the SE name |
| transition to `EXPIRED_UNFILLED` (SE §B6, L289, L298) | F7 | `F7.entry_wait_expired` | `shared.order_intent` | |
| `below_exchange_minimum` (SE §B6, L299; SE-50, L447) | F7 | `F7.min_notional_infeasible` | `shared.order_intent` | see WP-IR-05 |

**Taxonomy v1 additions** made by WP-IR-01, WP-IR-04 and WP-IR-05. WP-A01 records them; a code is never reused (OF L408):
- F4: `F4.regime_stale`, `F4.regime_not_accepted`, `F4.bar_before_version_activation`;
- F5: `F5.t1_not_cost_feasible`;
- F6: `F6.legacy_alphabetical_cut`;
- F7: `F7.mark_stale`, `F7.ledger_mismatch`, `F7.ledger_event_conflict`, `F7.economic_limit:<rule>`, `F7.exposure_gross`, `F7.heat_cap`.

**Supersedes.**
- STRATEGY_AND_EXECUTION_CONTRACT.md §B3, the `RejectionRecord` type (L195-203) and the input-guard clause (L215).
- STRATEGY_AND_EXECUTION_CONTRACT.md §E2, the code list of SE-52 (L498).
- OPPORTUNITY_FUNNEL.md §8.1, the "null otherwise" rule for `sub_stage` (L375).
- OPPORTUNITY_FUNNEL.md §8.2, the alignment table (L410-416).

**Enforced by WP-IT-01**, implemented in WP-A02 and WP-B01:
- every record on every fixture has a `reason_code` in taxonomy v1 whose prefix equals `stage`;
- a table-driven test maps every SE-side name above exactly once;
- `sub_stage` belongs to its closed enumeration;
- per-stage conservation counts each record under its own stage only;
- an unknown code or `sub_stage` is refused.

### WP-IR-02 · Where risk_plan lives: Candidate or Opportunity

**Divergence.**
- STRATEGY_AND_EXECUTION_CONTRACT.md §B3 puts `risk_plan` on `Candidate` (L193). The strategy proposes the plan in price terms (L218). The state machine takes its parameters through it (L277). The W3 provenance fields live in it (L343).
- The pack's shared glossary (the pack brief; not a tracked file, DOCUMENTED_ONLY) lists `risk_plan` as a field of `Opportunity`.
- OPPORTUNITY_FUNNEL.md F6 also adds it to `Opportunity` "from the strategy contract" (L346).
- PORTFOLIO_RISK_AND_COMPOUNDING.md sizes from `Opportunity.risk_plan` (§3.1 item 7, L238; §12, L626).

**Canonical choice.** `risk_plan` is a field of `Candidate`.
- `Strategy.evaluate` produces it once and it is frozen.
- `Opportunity` holds its `Candidate` by reference. `Opportunity.risk_plan` is a read-only alias of `Opportunity.candidate.risk_plan`, never a recomputed or edited copy.
- F5 feasibility reads the Candidate's plan (`F5.stop_missing`, `F5.bracket_invalid`, `F5.stop_risk_above_cap`). Sizing (PORTFOLIO_RISK_AND_COMPOUNDING.md §5) reads the same object through the Opportunity.
- One `risk_plan_hash` enters both the candidate `DecisionRecord` and the `SizingDecision` inputs.

**Rationale.**
- The plan must exist before ranking, because F5 checks the geometry before F6 ranks (OPPORTUNITY_FUNNEL.md §7 F5, L321-330).
- The strategy is the plan's only author (SE L218).
- A single object prevents a gap between the plan that was checked and the plan that is sized.
- The glossary and PR wording stay true, read as an alias.

**Supersedes.**
- The glossary row for `Opportunity`, at interface level: `risk_plan` is reachable from it, not owned by it.
- OPPORTUNITY_FUNNEL.md §7 F6 "Output" (L346), read as carry-through.
- PORTFOLIO_RISK_AND_COMPOUNDING.md §3.1 item 7 (L238) and §12 (L626), read as the alias.

**Enforced by WP-IT-02**, in WP-A02 and WP-D01:
- for every `Opportunity` in the fixtures, `risk_plan_hash(opportunity) = risk_plan_hash(candidate)`;
- the frozen types refuse mutation;
- the `SizingDecision` input hash includes the plan hash;
- a deliberate edit of the plan between F5 and F7 makes the test fail.

### WP-IR-03 · One capacity authority

**Divergence.** Capacity is checked in three places, with different inputs and different meanings of a zero limit. Two pack documents record this: OPPORTUNITY_FUNNEL.md §12 (L542-547) and PR-14 in PORTFOLIO_RISK_AND_COMPOUNDING.md §2.3 (L119-124), the latter as "three capacity checks, two limits". In code (SOURCE_VERIFIED):

| # | Site | Input and limit | Zero or negative limit |
|---|---|---|---|
| 1 | Delivery gate, `telegram/main.py:L364-382 @ bb7825f` | open `active_trades`; min(`MAX_OPEN_TRADES`, `RISK_CANARY_MAX_OPEN_TRADES`) at L379 | the check is skipped unless capacity > 0 (L380) |
| 2 | Tracker pre-check, `trade_tracker/main.py:L705-716, L751-759 @ bb7825f` | open `active_trades`; `MAX_OPEN_TRADES` only (10 at runtime, VER-12) | skipped unless the limit is > 0 (L708, L752) |
| 3 | Risk policy, `trade_tracker/main.py:L976-988 @ bb7825f` → `shared/risk_management.py` | min(…) passed in; effective slots = max(1, floor(min(limit, exposure-derived bound) × multiplier)) (`shared/risk_management.py:L116-120 @ bb7825f`) | refused as `invalid_risk_state` (`shared/risk_management.py:L71-76 @ bb7825f`) |

A related site, not a check: `enforce_max_open_trades` force-closes the most-losing positions above `MAX_OPEN_TRADES` (`trade_tracker/main.py:L508-520 @ bb7825f`; PR-14).

INFERRED from the table:
- the effective limit is 2 only because sites 1 and 3 agree at the runtime values (VER-12);
- working orders count at none of the three (PR-12);
- a zero limit means "unlimited" at sites 1 and 2 but "invalid" at site 3.

Research replay maps `max_open_trades` to `REJECT_MAX_TRADES` (`research/foundation/replay.py:L135-139 @ 46578aa`).

**Canonical choice.** The single capacity authority is the **F7 capacity check inside the portfolio `decide(state, snapshot)`** (PORTFOLIO_RISK_AND_COMPOUNDING.md §5, steps 4–5).
- It is implemented once, in `shared/capacity_authority.py`: in legacy mode by WP-E08, in target mode by PR-C09 (WP-G23).
- It is evaluated once per Opportunity, in the admission-authority service. The boundary record names trade_tracker as that service (`deploy/VERSION_BOUNDARY.md:L12 @ 46578aa`).

| Input | Target mode | `legacy_v1` mode (reproduces today) |
|---|---|---|
| Slot limit | `RiskBudget.max_positions` with `budget_version` (PR-OD16) | min(`MAX_OPEN_TRADES`, `RISK_CANARY_MAX_OPEN_TRADES`) |
| Loss-driven slot reduction | the chosen ladder (PR-OD21) | L-1: min of the triggers, floored at 1 |
| Exposure | separate F7 exposure checks (WP-IR-05) | the exposure-derived slot bound of `shared/risk_management.py:L116-119` |
| Occupancy | ledger positions with `qty_open > 0` plus active reservations of working intents (PR-I3; PR-C11) | open `active_trades` only |
| Invalid limit (zero, negative, non-integer, missing) | refuse with `F7.risk_state_invalid`; never "unlimited" | same |

**Output.** Either "admit", or `F7.capacity_full` with `detail` = {open, reserved, limit, multiplier, `budget_version`}.

**What the other two sites become.**
- **Delivery gate.** It makes no capacity decision. In shadow (WP-B12, flag off) it is a recorded mirror, compared with the authority. After OF-T12 is activated (WP-G17), delivery never drops an Opportunity for capacity.
- **Tracker pre-check.** It becomes a configuration ceiling checked at start (`max_positions` ≤ `MAX_OPEN_TRADES`, otherwise refuse to start). At run time it is an early exit that asks the authority, not a comparison against a limit of its own.
- **Force-close above `MAX_OPEN_TRADES`.** It is not a capacity check. Under the target it becomes an invariant alarm: technical refusal of new admissions plus an alert. Whether the legacy force-close stays is WP-OD-02.
- **Research.** `REJECT_MAX_TRADES` maps to `F7.capacity_full`.

**Rationale.**
- One decision, one set of inputs, one record.
- `legacy_v1` reproduces runtime exactly (PORTFOLIO_RISK_AND_COMPOUNDING.md §5, "Legacy mode", L500-502).
- Counting reservations closes PR-12.
- Refusing an invalid limit follows the rule that technical safeguards stay fail-closed (OOC:L26).

**Supersedes.** OPPORTUNITY_FUNNEL.md §12 (L542-547) and PR-14 (L119-124) as design baselines; both stay correct as descriptions of today. OPPORTUNITY_FUNNEL.md §7 F7 (L351-360) is consistent with this choice and stays as written.

**Enforced by WP-IT-03**, in WP-E08 and WP-B12:
1. golden grids in `legacy_v1` reproduce the slot limit, the exposure bound and the multiplier (PR-T09);
2. over synthetic sequences, the delivery mirror and the tracker pre-check never disagree with the authority, and any disagreement is recorded;
3. a zero, negative or missing limit refuses;
4. in target mode, reserved intents count (PR-T13).

### WP-IR-04 · Rank loss is not capacity

**Divergence.**
- At `signal_engine/signal_logic.py:L848-854 @ ea8ae4f`, a rank loser gets two different labels:
  - the evidence decision `rejected_fixed_policy_rank` (L852);
  - `last_decisions` = `not_selected_capacity` (L853), which is what reaches the database reason (`signal_engine/main.py:L178-186 @ ea8ae4f`).

  No capacity check runs at that point (OF-07, OPPORTUNITY_FUNNEL.md L160; REMEDIATION_REGISTER.md, inconsistency table, L670).
- Research repeats the conflation: rank losers are marked `REJECT_RANK_CAPACITY`, policy `fixed_execution_quality_v1` (`research/foundation/runner.py:L139-148 @ 46578aa`; enum at `research/foundation/opportunity.py:L30 @ 46578aa`).
- In the risk policy, a capacity refusal is labelled with the first loss-ladder reason whenever a multiplier lowered the slot count (`shared/risk_management.py:L141-142 @ bb7825f`). Capacity is then reported under a sizing label.
- The register names stages that are not in OF's stage enumeration: `selection_capacity` (R1.f, REMEDIATION_REGISTER.md L133), and `selection_capacity` and `portfolio_capacity` (R6.c, L439).
- OF-OD-15 option (b), "every ranked Opportunity up to free capacity" (OPPORTUNITY_FUNNEL.md L510), would make the F6 offer count depend on portfolio state.

**Canonical codes.**

| Event | Code | `detail` |
|---|---|---|
| Lost on rank, below the per-cycle offer count (today one winner per cycle) | `F6.rank_below_cap` | rank, `offer_cap`, selection version |
| Dropped by a hash-ordered resource guard | `F6.resource_cap` | hash position, guard bound |
| Today's alphabetical `LIMIT 200` cut, recorded in shadow only | `F6.legacy_alphabetical_cut` (new) | position in name order, limit 200. Retired when WP-G01 activates; never used by a target selection version |
| Refused by the capacity authority (WP-IR-03) | `F7.capacity_full` | open, reserved, limit, multiplier and its reasons, `budget_version` |
| Older pending Opportunity on the same symbol replaced | `F7.superseded` | the superseding `setup_key` |

**Rule.** F6 never reads portfolio state. The offer count is a constant of the selection version (OF-OD-15). Under OF-OD-15 option (b), F6 offers every ranked Opportunity, and F7 refuses the excess with `F7.capacity_full`, each record carrying its rank.

**Legacy mapping**, for the shadow parity of WP-B01:

| Legacy label or code | Canonical |
|---|---|
| `not_selected_capacity`, `rejected_fixed_policy_rank` | `F6.rank_below_cap` (`offer_cap` 1) |
| `delivery.refused` with `portfolio_capacity_<n>/<m>` (`telegram/main.py:L381 @ bb7825f`) | `F7.capacity_full`, `sub_stage` `shared.admission` |
| tracker pre-check stop (`trade_tracker/main.py:L712-715, L756-759 @ bb7825f`) | `F7.capacity_full`, `detail.check` = tracker pre-check |
| risk reason `max_open_trades`, or a ladder reason at `shared/risk_management.py:L142` | `F7.capacity_full`, ladder reason kept in `detail` |
| research `REJECT_RANK_CAPACITY` | `F6.rank_below_cap` |
| register stage `selection_capacity` | F6: `F6.legacy_alphabetical_cut` today; `F6.resource_cap` or `F6.rank_below_cap` in a target version |
| register stage `portfolio_capacity` | `F7.capacity_full` |

**Rationale.**
- A ranking loss and a capacity refusal have different causes and different remedies.
- Mixing them hides whether opportunities are lost to selection or to portfolio limits, which is exactly the R6 question.
- The target's hash-ordered guard must not be confused with today's name-ordered cut.

**Supersedes.**
- OPPORTUNITY_FUNNEL.md §8.2, the F6 row (L405): adds the legacy code.
- OPPORTUNITY_FUNNEL.md §10, the OF-OD-15 option (b) wording (L510): read as stated in the rule above.
- REMEDIATION_REGISTER.md R1.f (L133) and R6.c (L439): their stage names.

**Enforced by WP-IT-04**, in WP-B01, WP-B05 and WP-B12:
1. three eligible candidates, offer count 1, free capacity: two `F6.rank_below_cap` records and no F7 record;
2. capacity full and one Opportunity offered: one `F7.capacity_full` and no capacity-labelled F6 record;
3. F6 output is invariant under any change of ledger state (property test);
4. a static test: `not_selected_capacity` and `REJECT_RANK_CAPACITY` appear in new code only inside the legacy mapping table.

### WP-IR-05 · F7 and sizing reason codes

**Divergence.**
- **Minimum order size has four names.** OPPORTUNITY_FUNNEL.md uses `F1.min_order_infeasible` (L270, L400) and `F7.min_notional_infeasible` (L406). STRATEGY_AND_EXECUTION_CONTRACT.md uses `below_exchange_minimum` (L299, L447, L498). PORTFOLIO_RISK_AND_COMPOUNDING.md uses `below_min_notional` (§4.4, L447).
- **The technical risk state is spelled two ways.** Code and PR use `invalid_risk_state` (`shared/risk_management.py:L75 @ bb7825f`; PR-20, L54, L181); OF's taxonomy uses `risk_state_invalid` (L406).
- **Technical reasons are missing from OF's F7 list (L406).** PR's `mark_stale` (L300), `ledger_event_conflict` (PR-I7, L286) and `ledger_mismatch` (PR-I13, L292) are named as kill-switch reasons (L459) but have no F7 code.
- **Economic hard stops have no code.** In enforce mode, the stops of `shared/risk_management.py:L122-132 @ bb7825f` refuse, but OF's F7 list has no code for them. In observe mode, PR records `observed:<rule>` (L495).
- **Exposure codes do not match.** PR measures gross exposure and portfolio heat (§4.1, L337, L342) and has a `cluster_cap` field (L249). OF has codes only for symbol, strategy, regime and correlation (L406). The code labels exposure refusals `gross_exposure_limit` and `*_concentration_limit` (`shared/risk_management.py:L133-140 @ bb7825f`).

**Canonical choice.**

| Event | Code | `sub_stage` | Replaces or maps |
|---|---|---|---|
| The smallest order the `RiskBudget` allows cannot clear the venue floor (universe pre-check) | `F1.min_order_infeasible` | null | — |
| Sized quantity, rounded down to the step, is below the venue minimum | `F7.min_notional_infeasible` | `shared.sizing` | PR `below_min_notional` |
| `OrderIntent` re-validation fails, for example after filters changed while working | `F7.min_notional_infeasible` | `shared.order_intent` | SE `below_exchange_minimum` |
| Invalid or non-finite risk inputs | `F7.risk_state_invalid` | `shared.admission` | `invalid_risk_state`, kept unchanged in the legacy `RiskDecision` and in `detail.legacy_reason` |
| Stale or missing mark | `F7.mark_stale` (new) | `shared.admission` | PR `mark_stale` |
| Ledger reconciliation mismatch | `F7.ledger_mismatch` (new) | `shared.admission` | PR `ledger_mismatch` |
| Conflicting duplicate `event_id` | `F7.ledger_event_conflict` (new) | `shared.admission` | PR `ledger_event_conflict` |
| Economic limit, enforce mode | `F7.economic_limit:<rule>` (new), rule ∈ {`daily_loss_limit`, `weekly_loss_limit`, `max_drawdown_limit`, `loss_streak_halt`} | `shared.admission` | research `REJECT_DAILY_RISK`, `REJECT_WEEKLY_RISK`, `REJECT_DRAWDOWN`. In observe mode there is no `RejectionRecord`, only the `DecisionRecord` annotation `observed:<rule>` |
| Manual or administrative pause | `F7.paused` | `shared.admission` | `manual_pause` and pause reasons |
| Gross exposure cap | `F7.exposure_gross` (new) | `shared.admission` | `gross_exposure_limit` |
| Symbol, strategy or regime concentration | `F7.exposure_symbol`, `F7.exposure_strategy`, `F7.exposure_regime` | `shared.admission` | `symbol_concentration_limit`, `strategy_concentration_limit`, `regime_concentration_limit` |
| Correlated-cluster cap | `F7.exposure_correlation` | `shared.admission` | PR `cluster_cap` stays the `RiskBudget` field name, not a code |
| Portfolio heat cap leaves no feasible size | `F7.heat_cap` (new) | `shared.sizing` | — |

The research catch-all `REJECT_PORTFOLIO_CAP` (`research/foundation/runner.py:L154-159 @ 46578aa`) is split by its `detail.reason` according to this table.

**Rationale.**
- One code per cause across funnel, contract and ledger.
- The legacy strings stay byte-identical where the hash-pinned `RiskDecision` produces them (WP-N02). The canonical code is added beside them, not substituted.
- The observe-mode economic outcome stays an observation, not a refusal (OOC:L24-26).

**Supersedes.**
- OPPORTUNITY_FUNNEL.md §8.2, the F7 row (L406): adds codes and spells the existing ones.
- STRATEGY_AND_EXECUTION_CONTRACT.md §B6 (L299), SE-50 (L447) and SE-52 (L498): the name `below_exchange_minimum`.
- PORTFOLIO_RISK_AND_COMPOUNDING.md §4.4 (L447): the name `below_min_notional`; and §3.5, §4.5 (L300, L459): the free-standing technical reason names.

**Enforced by WP-IT-05**, in WP-B12, WP-D05 and WP-E08:
- every `SizingDecision` with outcome "reject", every `OrderIntent` refusal and every legacy `RiskDecision` reason maps to exactly one F7 code;
- the legacy `RiskDecision` fields stay byte-identical (PR-T09).

### WP-IR-06 · Order and position state names

**Divergence.**
- STRATEGY_AND_EXECUTION_CONTRACT.md §B6 defines eight states (L281-289): `PLANNED`, `WORKING`, `OPEN`, `PARTIAL_T1`, `PARTIAL_T2`, `CLOSED`, `REJECTED` and `EXPIRED_UNFILLED`.
- PORTFOLIO_RISK_AND_COMPOUNDING.md §3.2 gives `Position.state` four values: `pending` → `open` → `partially_exited` → `closed` (L248).

**Canonical choice.** The SE §B6 machine is the only state machine: shared infrastructure, implemented in WP-D03. PR's `Position.state` is a derived projection, never an independent truth:

| SE state | PR projection | Ledger event (PORTFOLIO_RISK_AND_COMPOUNDING.md §3.3) |
|---|---|---|
| `PLANNED`, `WORKING` | `pending` | `RESERVE` at intent |
| `OPEN` | `open` | `ENTRY_FILL`, also for each partial entry fill |
| `PARTIAL_T1`, `PARTIAL_T2` | `partially_exited` | `EXIT_FILL` per leg |
| `CLOSED` | `closed` | final `EXIT_FILL` |
| `REJECTED`, `EXPIRED_UNFILLED` | no position | `RELEASE` of the unconsumed reservation (L260) |

**Rationale.**
- One machine prevents the lifecycle and the ledger from disagreeing about whether a position exists.
- The SE states carry the detail that exits need.

**Supersedes.** PORTFOLIO_RISK_AND_COMPOUNDING.md §3.2, the `state` values in the `Position` row (L248), read as the projection.

**Enforced by WP-IT-06**, in WP-D03 and WP-E01:
- every legal SE transition sequence from the SE-66 exhaustive table maps to a legal projection sequence;
- each transition emits exactly the listed ledger event, and PR-I1 to PR-I6 hold after it (PR-T01);
- an illegal projection is refused.

### WP-IR-07 · Cost-model identifiers

**Divergence.**
- STRATEGY_AND_EXECUTION_CONTRACT.md names the field `cost_model_id` (L226, L491). It uses the identifiers `legacy_tracker_v1` (§C4, L455) and `research_baseline_v1` / `research_stress_v1` (SE-67, L532).
- PORTFOLIO_RISK_AND_COMPOUNDING.md names the field `cost_model_version` (L247). It uses the identifier `legacy_tracker_30bps` (L320; PR-C03, L541) and names the research models only by their values (L321-322).
- The register adds a `label_policy` (R4.a, REMEDIATION_REGISTER.md L318). The policy in force is `net_after_modeled_cost_v1` (`shared/fees.py:L41 @ bb7825f`).

**Canonical choice.**
- **Field.** `cost_model_id`, on every `LedgerEntry`, `Fill`, `SizingDecision`, `DecisionRecord` and `StrategyContract`.
- **Identifiers.** `legacy_tracker_v1`, `research_baseline_v1` and `research_stress_v1`.
- **Parameters.** Numeric parameters live in the model's configuration and enter `config_hash`. They never form part of an identifier.
- **`label_policy`.** It remains a separate field that names the reporting rule.

**Rationale.**
- A value inside an identifier forces a rename at every recalibration and bypasses the SE-38 versioning rule.
- The strategy-and-execution contract owns the cost model (OPPORTUNITY_FUNNEL.md, related-documents table, L46; STRATEGY_AND_EXECUTION_CONTRACT.md §B7, L333).

**Supersedes.** PORTFOLIO_RISK_AND_COMPOUNDING.md §3.2 (L247), the field name; and §3.6 (L320) and PR-C03 (L541), the identifier.

**Enforced by WP-IT-07**, in WP-D04, WP-E01 and WP-E07:
- the registry holds exactly the three identifiers;
- every ledger entry and fill names one of them;
- `legacy_tracker_v1` reproduces `shared/fees.py` (R4 test 1; PR-T15).

### WP-IR-08 · DecisionRecord granularity

**Divergence.**
- OPPORTUNITY_FUNNEL.md F8 specifies "one `DecisionRecord` per cycle" (L362-364), and `RejectionRecord.cycle_id` is "the cycle's `DecisionRecord` id" (L373).
- SE-51 keys one record to each decision, with `decision_type` ∈ {`candidate`, `rejection`, `opportunity_rank`, `sizing`, `order_intent`, `fill`, `position_transition`, `ledger_entry`} (STRATEGY_AND_EXECUTION_CONTRACT.md L486-496).
- The glossary describes "a deterministic record of each decision".

**Canonical choice.** SE-51 per-decision records, carried in the evidence v2 envelope.
- **The OF F8 cycle record** is the `DecisionRecord` whose `decision_type` is `opportunity_rank`, one per cycle. It carries every OF F8 field: the input hashes, the candidate-set hash, the ranked list, the selected Opportunities, the counters, the conservation result and `ranking_incomplete`.
- **`RejectionRecord.cycle_id`** is that record's `decision_id`.
- **A rejection-type record** carries both `record_id` (OPPORTUNITY_FUNNEL.md §8.1, L372: the identity of the drop) and `decision_id` (SE-51: the identity of the computation).

**Rationale.** This keeps OF's cycle-level reproducibility and SE's per-decision chain without adding a second record type.

**Supersedes.** OPPORTUNITY_FUNNEL.md F8, the phrase "one DecisionRecord per cycle" (L364), read as one `opportunity_rank` record per cycle among the per-decision records.

**Enforced by WP-IT-08**, in WP-A05 and WP-B04. Re-evaluating recorded synthetic inputs reproduces the cycle record, every per-decision record, both identifiers and the chain (the OF-T13 and SE-70 tests).

### WP-IR-09 · StrategyVersion identity fields

**Divergence.** The glossary defines five fields. STRATEGY_AND_EXECUTION_CONTRACT.md §B3 adds a sixth, `lineage` (L156), while SE-51 refers to "the five `StrategyVersion` fields" (L491).

**Canonical choice.** The identity is the five glossary fields. `lineage` is recorded metadata. It is excluded from identity comparison, from `setup_key` and from the identifier written into `RejectionRecord.strategy_version`, consistent with SE's own note that lineage is "never a claim of inherited evidence" (L156).

**Rationale.** Re-parenting a version must not create a new identity, and ancestry must never look like evidence.

**Supersedes.** STRATEGY_AND_EXECUTION_CONTRACT.md §B3 (L149-156), read with `lineage` outside the identity.

**Enforced by WP-IT-09**, in WP-A02 and WP-C02. Changing `lineage` alone leaves the identity hash and `setup_key` unchanged; changing any of the five fields changes both.

### Summary of canonical choices

| ID | Canonical choice in one line |
|---|---|
| WP-IR-01 | OF §8.1 schema; `stage` F0–F7; one closed `F<n>.<reason>` code per drop; strategy stage names in `sub_stage`, strategy codes in `detail.strategy_code` |
| WP-IR-02 | `risk_plan` belongs to `Candidate`; `Opportunity.risk_plan` is a read-only alias with the same hash |
| WP-IR-03 | one capacity authority: the F7 check in the portfolio `decide()` at the admission service; the delivery gate becomes a mirror, the tracker pre-check a start-up ceiling |
| WP-IR-04 | `F6.rank_below_cap`, `F6.resource_cap` and the shadow-only `F6.legacy_alphabetical_cut` for selection; `F7.capacity_full` for capacity; F6 never reads portfolio state |
| WP-IR-05 | one F7 code per cause: `F7.min_notional_infeasible`, `F7.risk_state_invalid`, new technical, economic-limit, gross-exposure and heat codes |
| WP-IR-06 | the SE §B6 state machine is canonical; PR `Position.state` is its projection |
| WP-IR-07 | field `cost_model_id`; identifiers `legacy_tracker_v1`, `research_baseline_v1`, `research_stress_v1`; no values in identifiers |
| WP-IR-08 | one `DecisionRecord` per decision; the per-cycle record is `decision_type` `opportunity_rank` |
| WP-IR-09 | `StrategyVersion` identity = the five glossary fields; `lineage` is metadata |

## 9. Owner decisions raised by this plan

Both items are **OWNER DECISION REQUIRED**. The options are not ranked and none is chosen. They are raised here because no pack document records them. Their consolidated entries in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) are DG-71 and DG-72 (WP-NV-1, answered).

### WP-OD-01 · Edits to the nine hash-pinned logic files during WP2

Basis: WP-N02 (section 2.3).

| Option | Content | Trade-off |
|---|---|---|
| (a) No edits | WP2 never edits a pinned file. The scanner and signal-engine records of WP-B01 come from mirrors in new modules, which tests assert equal to the pinned functions. WP-B02 and the pinned hooks of WP-B05 and WP-B10 wait for the next declared strategy version | The frozen v1 contract hash stays intact. Per-timeframe reasons and signal-engine gate records are delayed, and the mirrors duplicate logic that must stay in parity |
| (b) PATCH identity events | Behaviour-identical edits are allowed. Each is recorded as a PATCH identity event: the golden replay (WP-A04) shows byte-identical decisions; contract hash v2 (WP-A03) reports the change; the v1 change is recorded with the preserved legacy hash kept as lineage (SE-39); `research_freeze.json` stays untouched | Full observability sooner. But the v1 hash no longer matches the frozen bytes, so every research comparison must use the recorded event, and SE-38's PATCH rule is applied to the research contract for the first time |
| (c) Every edit is a boundary | Any edit of a pinned file is a strategy-version boundary | The strictest attribution. Instrumentation-only changes then need a declared window and restart evidence (SE-25) |

**Blocks:** the pinned-file slices of WP-B01, WP-B02, WP-B05 and WP-B10; WP-G13.

### WP-OD-02 · The legacy force-close above MAX_OPEN_TRADES in the target design

Basis: WP-IR-03.

| Option | Content | Trade-off |
|---|---|---|
| (a) Keep | Keep the force-close unchanged, in `legacy_v1` and in the target | Reproduces today. It is a shared-layer exit outside every strategy's exit policy |
| (b) Alarm, no liquidation | Replace it in the target by an invariant alarm: technical refusal of new admissions plus an alert, with no liquidation | Consistent with "never force-closes a position outside its own exit policy" (PORTFOLIO_RISK_AND_COMPOUNDING.md §4.6, L478) and with SE-43, under which the shared layer imposes no holding ceiling (STRATEGY_AND_EXECUTION_CONTRACT.md L317-319). A breach then has to be resolved by a person |
| (c) Contract-declared only | Keep a forced exit only where a strategy contract declares it as its own exit rule | Explicit per strategy. More contract work for each version |

At the runtime values the trigger cannot fire, because admissions stop at 2 while the force-close limit is 10. This is INFERRED from VER-12 and `trade_tracker/main.py:L508-520 @ bb7825f`.

**Blocks:** WP-B12; WP-G17.

## 10. NOT VERIFIED items

| ID | Question | Blocker |
|---|---|---|
| WP-NV-1 | Does [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) carry a consolidated entry for every source decision cited here, including WP2-START, WP-OD-01 and WP-OD-02? | Answered on 2026-11-01: DECISIONS_AND_GATES.md section 1.7 maps every cited source decision, and DG-70 to DG-72 carry WP2-START, WP-OD-01 and WP-OD-02 |
| WP-NV-2 | Is the CI, or the local CI equivalent, of acceptance criterion 1 available? | `ops/ci/lce.py` exists only on the unmerged branch `review/lce-2` (`fd66219`); the CI state was not observed in this phase |
| WP-NV-3 | Effort and calendar duration of each lane | Nothing was measured, and no estimate is given |
| WP-NV-4 | Do the running images contain the code the tasks modify? | Image content not re-verified (RT-17; WP-G09) |
| WP-NV-5 | Does the runtime `APP_VERSION` come from the Dockerfile default (WP-N01)? | Image build arguments not inspected (VER-28 item 5) |
| WP-NV-6 | Do the reused unmerged inputs still fit `46578aa`? These are the `integration/rnd` collector commits, `lab/account.py @ c42e6ea`, `research/design_a/ledger.py @ ebf8d8a` and `shared/shadow_opportunity.py @ 1dc9ac5` | No merge or apply was run |
| WP-NV-7 | Any runtime value after 2026-10-31 | No observation in this phase (R-NV-8 in [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md)) |

## 11. Inconsistencies and deviation check

### 11.1 Inconsistencies found in the five pack documents

| # | Observation | Class | Resolution |
|---|---|---|---|
| 1 | Nine interface divergences between the funnel, contract and portfolio documents | DOCUMENTED_ONLY (design text) | WP-IR-01 to WP-IR-09; source documents aligned by WP2 on 2026-11-01 |
| 2 | OPPORTUNITY_FUNNEL.md lists `regime_veto:<series>` under F3 in its taxonomy (L402), but files it under F4 in its alignment table (L415) | DOCUMENTED_ONLY | WP-IR-01; OPPORTUNITY_FUNNEL.md aligned by WP2 on 2026-11-01 |
| 3 | SE-12 cites the charter's "§4, L41" for separating R4 accounting from stop geometry (STRATEGY_AND_EXECUTION_CONTRACT.md L374). R4 is `CH:L39`; L41 is R6. The content is unaffected | SOURCE_VERIFIED (charter lines) | citation slip; corrected to `CH:L39` in SE-12 by WP2 on 2026-11-01 |
| 4 | Two acceptance criteria assume that no pinned file changes: SE-63's "the v1 hash of `current_contract()` unchanged" (L528) and PR-T09's "the hash of `shared/risk_management.py` is unchanged" (L570). Yet OF-T02 and parts of OF-T01, OF-T07 and OF-T10 need hooks inside pinned files. No pack document notes that these files are hash-pinned | INFERRED from SOURCE_VERIFIED code (WP-N02) | WP-OD-01 |
| 5 | A zero capacity limit means "unlimited" at the delivery gate and the tracker pre-check, but "invalid" in the risk policy. Neither OPPORTUNITY_FUNNEL.md §12 nor PR-14 records this | SOURCE_VERIFIED (code, WP-IR-03) | WP-IR-03 |
| 6 | When a ladder multiplier lowered the slot count, the risk policy labels a capacity refusal with the ladder reason (`shared/risk_management.py:L141-142 @ bb7825f`). PR-05 and PR-14 do not mention this | SOURCE_VERIFIED | WP-IR-04, WP-IR-05 |
| 7 | SE-52 proposes reusing the research `RejectionCode` names "where they exist" (L498). That enumeration includes `REJECT_RANK_CAPACITY`, which repeats the OF-07 conflation (`research/foundation/runner.py:L145-148 @ 46578aa`) | SOURCE_VERIFIED | WP-IR-04; SE-52 aligned by WP2 on 2026-11-01 |
| 8 | The register's stage names `selection_capacity` and `portfolio_capacity` (R1.f, R6.c) are not in OPPORTUNITY_FUNNEL.md's stage enumeration | DOCUMENTED_ONLY | WP-IR-04; R1.f and R6.c aligned by WP2 on 2026-11-01 |
| 9 | The pack's shared glossary is referenced ("pack glossary", STRATEGY_AND_EXECUTION_CONTRACT.md L136, L141; the PORTFOLIO_RISK_AND_COMPOUNDING.md §3.2 heading, L243), but none of the five documents reproduces it | DOCUMENTED_ONLY | to be carried by [README.md](README.md), or recorded by WP-A01 |

### 11.2 Governance notes (not deviations)

- **Integration rule.** DFP:L5 lets low-risk D0 work be integrated into `main` without a PR or repeated owner approval. DFP:L41 and DFP:L102 make merging an owner decision per PR. The conflict sits inside the governing policy and predates this pack. This plan follows the narrower gate (OOC:L44) and leaves integration to the owner.
- **HOLD scope.** The HOLD scope question (CON-36; BL-19; OQ-06) is pre-existing and goes to WP-D07.

### 11.3 DEVIATION ALERT check

**No DEVIATION ALERT is raised.** Against the list in `CH:L67`:
- **Objective.** Unchanged.
- **Transferring results.** No result of another strategy is used as evidence for or against any task.
- **Unregistered tuning.** None. No parameter is chosen. WP-D04 carries the charter's proposed cost figures, labelled as proposed. WP-D02 adds only the alternatives SE §B8 already documents, all behind the legacy default.
- **Forced trades.** None. The F6 offer count is a cap, not a quota, and an empty cycle stays valid.
- **BTC-only scope.** None. WP-B09 tests that the universe is the same whatever the BTC label.
- **Unrealized gains as cash.** Prevented: PR-T06 is part of WP-E01.
- **A29.** Not bypassed. WP-E05 and WP-D06 wait for WP3, and no evaluation is scheduled.
