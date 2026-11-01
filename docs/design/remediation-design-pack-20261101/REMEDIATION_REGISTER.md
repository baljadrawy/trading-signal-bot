# Remediation Register R1–R9 (WP0)

> **Reconciliation 2026-11-01 (WP2).** Documentation only, on branch `feature/wp2-foundation-20261101` from `5cd1a61`. This file now uses the canonical interfaces of [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) section 8. No item's status, gate or priority changes. What changed:
> - **Stage names.** R1.f and R6.c no longer name the stages `selection_capacity` and `portfolio_capacity`, which are not in the funnel's F0–F7 enumeration. They name F6 codes (`F6.legacy_alphabetical_cut` in shadow, `F6.resource_cap`, `F6.rank_below_cap`) and the F7 code `F7.capacity_full` from the single capacity authority (WP-IR-03, WP-IR-04).
> - **R6 test 2.** It now uses the canonical `RejectionRecord` fields: `stage` F0–F7, a closed `sub_stage`, a taxonomy v1 code whose prefix equals `stage`, and subject fields nullable by scope (WP-IR-01).
> - **R4.a and R4 test 1.** They name `cost_model_id` and `legacy_tracker_v1` beside `label_policy` (WP-IR-07).
> - **R5.d and R3.d.** They state the five-field `StrategyVersion` identity with `lineage` as metadata (WP-IR-09).
> - **Inconsistency table.** The OF-07 row names its target code.
> - **Line citations.** Line numbers of pack documents in citations refer to the files as committed at `5cd1a61`. They are not renumbered.

> **Status: documentation only (charter §4, §5 WP0).** This is the single deduplicated tracker of the nine remediation items that the charter defines (`CH:L33-46`). It consolidates audit, ERG-01 and governance findings and re-checks code locations at the documented-deployed commits and at `main` `46578aa`. It runs nothing, changes nothing and authorizes nothing. **No item here, once fixed, establishes profitability** (`CH:L46`; DFP:L31).

## Document control

| Field | Value |
|---|---|
| This file | `REMEDIATION_REGISTER.md` (WP0; item IDs R1 … R9, sub-items such as R1.a) |
| Baseline | `main` `46578aa`; audit `5d977f2`; ERG-01 `0729a5f`; reconciliation in [BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md) |
| Code read | analyzer and signal_engine at `ea8ae4f`; telegram and trade_tracker at `bb7825f`; `main` at `46578aa`; scanner blob `fa03cc2a` (`scanner/scanner_logic.py`, identical at `ea8ae4f` and `46578aa`) |
| Design documents | [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) (OF-), [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md) (SE-), [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) (PR-), [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) (WP-), [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) (DG-) |
| Governance | [charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md), [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md), [Development-First Policy](../../governance/DEVELOPMENT_FIRST_POLICY.md), [Evidence Ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md), [version boundaries](../../../deploy/VERSION_BOUNDARY.md) |

### Anti-drift statement (charter §7)

1. **Goal alignment.** Each item is judged by its effect on daily opportunity discovery, on execution correctness and on the integrity of net-profit measurement, which compounding of realized net profit depends on (`CH:L8`).
2. **Branch, SHA, runtime identity.** `main` = `46578aa`. Runtime behaviour is SOURCE_VERIFIED at the deployed commits only; image content parity is DOCUMENTED_ONLY; runtime values are RUNTIME_VERIFIED for 2026-10-31 only (BL-11 in [BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md)).
3. **Scope.** R1–R9 exactly as in `CH:L36-44`; WP0, with hand-offs to WP1–WP5.
4. **Evidence class.** On every factual claim.
5. **Permission class.** Read-only documentation; every *proposed* change carries one change class (below).
6. **Deliverables.** This register; acceptance is a clean self-check. Every item lists its own tests, gates and closure proof.
7. **DEVIATION ALERT.** None raised (BASELINE_AND_EVIDENCE §8).

### Source aliases

`ALIAS:Lx-Ly` means `path:Lx-Ly @ commit`:

| Alias | Path @ commit |
|---|---|
| CH, OOC, DFP, ELP | `docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md`, `docs/governance/OWNER_OPERATING_CONTRACT.md`, `docs/governance/DEVELOPMENT_FIRST_POLICY.md`, `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md`, all `@ 46578aa` |
| REP | `docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md @ 5d977f2` (defines audit IDs) |
| ADD | `docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md @ 5d977f2` (VER-xx) |
| ERG, G1, G2, G3, G4, G5 | `docs/research/evidence-resolution-20261031/` `README.md`, `HIS05_COMPARABILITY.md`, `VERSION_EVIDENCE_LINEAGE.md`, `DEFECT_IMPACT_ASSESSMENT.md`, `POWER_AND_HORIZON_FEASIBILITY.md`, `CANDIDATE_DECISION_MATRIX.md`, all `@ 0729a5f` |

Code is always cited with its full path and commit.

## How to read an item

**Fields.** Every item records: charter row; original evidence with references; current code or configuration location at the deployed commits and at `46578aa`; evidence status; fix status; consequences for opportunity discovery, execution correctness and profitability measurement; engineering versus strategy-version type; sub-items with proposed changes and their change class; tests and acceptance criteria; dependencies; owner gates; closure proof (`CH:L46`).

**Fix status.** OPEN (defect present at runtime as documented); FIXED (corrected in the documented-deployed source); PARTIALLY_FIXED (a correction exists but is incomplete, default-off or not deployed); NOT_VERIFIED (cannot be established; blocker stated).

**Change classes** (exactly one per proposed change; none implies another, `CH:L51`, `CH:L65`):

| Change class | Meaning here |
|---|---|
| Documentation/design | text, specifications, contracts |
| Safe development-only correction | default-off code with no runtime effect: at the default, outputs are byte-identical to current behaviour and an unknown value refuses to start (DFP:L87) |
| Strategy-version-changing correction | changes which candidates, brackets, exits or sizes Paper produces; a declared version boundary (DFP:L63; OOC:L36) |
| Protected research or simulation | any replay, backtest, measurement on post-freeze or unlicensed data |
| Production/runtime change | any operation on the production host or its files, including read-only operations outside Class A |

**Type.** "Engineering" means the item concerns correctness or measurement and can be fully specified and tested on synthetic inputs. "Strategy-version" means correcting it changes Paper behaviour and starts a new version with no outcome evidence (G3:L287-293).

## Summary

| Item | Finding (`CH:L36-44`) | Fix status | Status class | Type | Primary gate | Priority |
|---|---|---|---|---|---|---|
| [R1](#r1-alphabetical-limit-200-candidate-cut) | Alphabetical `LIMIT 200` candidate cut | OPEN | SOURCE_VERIFIED | strategy-version (selection) | selection boundary; protected-data permission for counts | P0 design and default-off code; P2 activation |
| [R2](#r2-w3-momentum-t1-geometry) | W3: momentum T1 capped at the breakout bar's own high | OPEN at runtime; PARTIALLY_FIXED on `main` only | SOURCE_VERIFIED; VER-05 RUNTIME_VERIFIED | strategy-version (geometry) | correction choice; geometry boundary; analyzer image change | P2 |
| [R3](#r3-same-4h-and-1d-candle-re-fire) | Same 4h/1d candle re-fire | OPEN at runtime; PARTIALLY_FIXED in source (enforce mode, off) | SOURCE_VERIFIED; VER-02 RUNTIME_VERIFIED | strategy-version (integrity) | integrity boundary | P0 tests; first P2 activation |
| [R4](#r4-stop-slippage-double-accounting) | Stop slippage counted twice | OPEN | SOURCE_VERIFIED; VER-19 RUNTIME_VERIFIED | engineering (accounting); geometry part strategy-version | OQ-08; geometry boundary for R4.b | P0 accounting; P2 geometry |
| [R5](#r5-source-runtime-image-parity-and-lineage) | Source, runtime and image parity; historical lineage | NOT_VERIFIED (image content); OPEN (identity) | DOCUMENTED_ONLY | engineering | owner approval for host verification; no restart | P0 identity; P1 verification |
| [R6](#r6-filter-rejection-freshness-and-ranking-transparency) | Filter rejection, freshness, ranking transparency | OPEN | SOURCE_VERIFIED | engineering (observability); rule changes strategy-version | protected data requires permission | P0 observability; P2 rules |
| [R7](#r7-equity-ledger-and-realized-profit-compounding) | Equity ledger and realized-profit compounding | OPEN | SOURCE_VERIFIED | engineering (ledger); sizing strategy-version and owner risk policy | no live allocation change | P0 ledger; P3 sizing |
| [R8](#r8-economic-viability-of-active-hypotheses) | Economic viability of B, C and other hypotheses | NOT_VERIFIED; verdict **INCONCLUSIVE** preserved | INFERRED (ERG-01) | research | OD-DF-1, OD-DF-2, owner approval | P1 decisions; evaluation only after WP3 |
| [R9](#r9-backups-runtime-health-and-drift) | Backups, runtime health and drift | OPEN | RUNTIME_VERIFIED (2026-10-31) and DOCUMENTED_ONLY | engineering and operations | no unapproved production action | P0 documents; P1 operations |

## Priority ordering

The order puts engineering correctness and measurement integrity before any strategy change, as the charter requires (`CH:L57`; DFP:L31-33).

| Tier | Content | Why this order |
|---|---|---|
| **P0** — no runtime effect | R5.d `StrategyVersion` identity and hash coverage; R5.e boundary-record completion; R6 shadow `RejectionRecord` and per-(symbol, timeframe) decision keys; R3 key-uniqueness and fail-closed tests; R1 pure, default-off selection function; R4.a single-count cost ledger alongside the legacy one; R7 pure ledger with reconciliation tests; R9.c runbook and CLAUDE.md corrections; R9.d learner-hazard design | Without a real version identity, R1–R3 corrections are invisible to the contract hash (G3-08, G3:L277), so no later evidence could be attributed. Without funnel records and a reconciled ledger, nothing later can be counted or reconciled. None of these changes outcomes |
| **P1** — owner-gated reads and decisions | R5.a image content verification; R9.a collector root cause; R9.e backup state and isolated restore test; R9.b checkout decision; owner decisions OQ-07, OQ-08, OQ-09, OD-DF-1, OD-DF-2 | Runtime truth and safety must be established before any version change is activated; the research decisions gate R8 and do not block P0 |
| **P2** — declared strategy-version boundaries | R3 integrity mode → R1 selection → R2 geometry → R4.b break-even stop; R6 eligibility and freshness rules (OF-T04 to OF-T09) | Integrity first (no duplicate counting, no stale bars), then selection fairness, then geometry, which changes trade economics directly. Each correction starts with no outcome evidence (G3-09) |
| **P3** — evaluation and allocation | R8 evaluation (WP4) only after WP3 approvals; R7 risk-based sizing and compounding only after ledger reconciliation and an owner risk policy | Economics can be judged only on an attributable version with reconciled accounting (`CH:L29`) |

**OWNER DECISION REQUIRED — bundling of P2 boundaries.** Options:
- **Sequential boundaries** (one correction per boundary). This keeps attribution of each correction. But each boundary restarts evidence, and the 365-day horizon is already binding (G4-06, G4:L38).
- **One bundled boundary** (R3 + R1 + R2, optionally R4.b). This needs one window. But the effect of each correction cannot be separated. ERG-01 lists all three as prerequisites of Candidate B (ERG:L131).
- **Hybrid.** Integrity (R3) first, alone; then selection plus geometry together.

No option is chosen here.

## R1. Alphabetical LIMIT 200 candidate cut

**Charter row** (`CH:L36`): source-confirmed, realized impact UNKNOWN; verify current source; design ranked selection, deterministic tie-breaks and rejection explanations; gate: strategy selection or version change.

**Fix status: OPEN** (never fixed, G3:L149). **Type:** strategy-version (selection), with engineering prerequisites.

**Original evidence**

| Reference | Content | Class |
|---|---|---|
| UNI-16 (REP:L698), HIS-28 (REP:L1146) | `ORDER BY symbol, total_score DESC LIMIT 200` over rows at most 30 min old: alphabetical truncation, not fixed | SOURCE_VERIFIED |
| UNI-17 (REP:L699) | the cut binds above about 66 symbols × 3 timeframes; frequency NOT VERIFIED | INFERRED |
| STR-13 (REP:L517) | live ranking key (spread, −24 h quote volume, symbol, timeframe); ranks execution quality, not signal strength | SOURCE_VERIFIED |
| LRN-16, LRN-17 (REP:L786-787); VER-22 (ADD:L129-157); VER-31 item 3 (ADD:L290) | the 44 frozen indicator weights reach live decisions only through ordering and truncation | SOURCE_VERIFIED effect; RUNTIME_VERIFIED values |
| G3-02 (G3:L23, L140-220) | mechanism MECHANICALLY INFERRED, economic impact UNKNOWN; present from `2d11780` (2026-04-08) through `eba90dd`; correction is a selection boundary outside the hashed contract | INFERRED from SOURCE_VERIFIED code |
| G3-NV-03, NV-04, NV-08 (G3:L302-307) | pre-freeze frequency; DB sort collation; rationale of `ORDER BY symbol` | NOT_VERIFIED |
| OQ-09 (REP:L1521) | should frozen weights keep their effect on ordering and truncation? | owner question |
| OF-03, OF-20, OF-21 ([OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md)) | the cut, the inactive score deciding the boundary symbol, the lexical timeframe tie-break | as stated there |

**Current location** (re-checked in this phase; SOURCE_VERIFIED)

| Site | `ea8ae4f` (deployed signal_engine) | `46578aa` (`main`) |
|---|---|---|
| Candidate query | `signal_engine/main.py:146-155` (ORDER BY at L153, LIMIT at L154) | identical, same lines (`signal_engine/main.py` unchanged) |
| Truncation recorder | `signal_engine/main.py:26-66` (`SELECTION_LIMIT`, `_v2_truncation`), called at L158 | identical |
| Decision marking | `signal_engine/main.py:179-186`: one reason per **symbol**, only for symbols in the returned set | identical |
| Ranking key | `signal_engine/signal_logic.py:287-293` (`_fixed_candidate_key`) | `signal_engine/signal_logic.py:288-294` (one-line shift, BL-06) |
| Unwired replacement | `shared/candidate_selection.py` `bounded_universe` (G3:L151) | `shared/candidate_selection.py:209`; no caller under `signal_engine/` (`git grep`) |

Runtime context: `TIMEFRAMES=15m,4h,1d` (VER-06, ADD:L98) and `EVIDENCE_V2_ENABLED=true` for signal_engine (VER-20, ADD:L112), so the truncation recorder is active. Its records are post-freeze FORWARD_HOLDOUT material and were not read (G3:L196).

**Consequences**
- *Opportunity discovery:* when more than 200 fresh rows qualify, symbols late in name order are excluded before any setup, spread or cooldown check, systematically and in every cycle while the overflow lasts. Rows without a setup still consume slots (G3:L185-186). INFERRED.
- *Execution correctness:* the selected candidate is the best only within the alphabetical prefix. Among one symbol's timeframes, string order `'15m' < '1d' < '4h'` decides (G3:L188). The boundary symbol's surviving timeframes are chosen by an inactive legacy score built on frozen weights. SOURCE_VERIFIED mechanism.
- *Profitability measurement:* whenever the cut binds, the Paper sample describes a name-ordered sub-universe, not the declared scanner universe; direction of bias UNKNOWN (G3:L213). Frequency NOT_VERIFIED.

**Sub-items and proposed changes**

| Sub-item | Finding | Proposed change | Change class |
|---|---|---|---|
| R1.a | the cut precedes eligibility | specify the eligibility-first, rank-then-limit selection of [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) F6 | Documentation/design |
| R1.b | same | implement it as a pure function behind a flag whose default reproduces the current query and key byte-for-byte | Safe development-only correction |
| R1.c | same | activate the new selection on Paper | Strategy-version-changing correction |
| R1.d | lexical tie-breaks | declare the tie-break key in the `StrategyVersion` contract; no symbol-name order (the A44 `execution_quality_v2` hash tie-break, OF-23, is one option) | Documentation/design |
| R1.e | frozen weights steer survival and order (OQ-09) | remove `total_score` from the selection order as part of R1.c; until then, record the weights as a fixed, data-mined input | Documentation/design |
| R1.f | truncated rows get no DB decision reason | cross-reference R6.c: a shadow `RejectionRecord` at stage F6, `F6.legacy_alphabetical_cut` for today's cut (shadow only, retired at R1.c), and `F6.resource_cap` or `F6.rank_below_cap` in a target selection version (WP-IR-04) | Safe development-only correction |

**Tests and acceptance criteria** (synthetic inputs only)
1. *Name-order invariance (property test):* for random candidate sets of size 0, 1, 199, 200, 201 and 1,000 with fixed features, any permutation or renaming of symbol names leaves the selected candidate (identified by its features) unchanged, except for exact ties. Exact ties follow the declared `tie_break_key`, and the tie is recorded.
2. *No pre-eligibility drop:* `count(input rows) = count(evaluated) + Σ count(RejectionRecord)` for every cycle; no row is dropped by a limit before eligibility, unless a declared resource guard fires, which is itself recorded (OF-23).
3. *Default byte-identity:* with the flag at its default, the selected signal and `decision_reason` values equal the current code on a fixed fixture, in the pattern of `tests/test_decision_parity_before_after.py`.
4. *Determinism:* the same snapshot gives the same `DecisionRecord` hash across runs and process restarts.
5. *Timeframe tie:* one symbol with setups on 15m, 4h and 1d is resolved by the declared rule, never by string order.
6. *Collation independence:* selection does not depend on database string collation (G3-NV-04).
- Acceptance: tests 1–6 green in CI or the local CI equivalent; the flag defaults to current behaviour and fails closed on unknown values.

**Dependencies.** R5.d (the selection version must enter `config_hash`/`source_hash`, because `signal_engine/main.py` is outside the hashed contract, G3:L272); R6 (`RejectionRecord` contract); R3 (setup identity for de-duplication); R8 (B needs this correction, ERG:L131).

**Owner gates.** Activation is a declared selection boundary with operational approval (DFP:L63; OOC:L36; G3:L219). Measuring truncation frequency needs a permission over protected records (OD-7; `CH:L21`). OQ-09.

**Closure proof.** (1) Merged default-off implementation with tests 1–6 green. (2) Separately, an activation record in `deploy/VERSION_BOUNDARY.md` with the new `strategy_version` and hashes. Closure is a correctness claim only, never an economic one.

## R2. W3 momentum T1 geometry

**Charter row** (`CH:L37`): W3 momentum T1 uses the breakout candle high; source-confirmed, impact UNKNOWN; define independent geometry, invariants, tests; gate: geometry or version change.

**Fix status: OPEN at runtime; PARTIALLY_FIXED in source** (a default-off switch on `main` that the deployed analyzer does not contain). **Type:** strategy-version (geometry).

**Original evidence**

| Reference | Content | Class |
|---|---|---|
| STR-21 (REP:L527), HIS-30 (REP:L1148), IND-10 (REP:L730) | T1 capped at 0.99 × the 20-bar high including the decision bar; can sit below net break-even; not look-ahead; not fixed at runtime | SOURCE_VERIFIED |
| STR-17 (REP:L525), CON-22 (REP:L1475) | `T1_CAP_POLICY` exists at `bb7825f` and `main`, not at `ea8ae4f`; the running analyzer cannot be switched | SOURCE_VERIFIED; CONTRADICTORY (main vs deployed) |
| VER-05 (ADD:L97) | `T1_CAP_POLICY` unset in every service | RUNTIME_VERIFIED |
| G3-01, G3-01a, G3-01b (G3:L22, L43-136) | for **every** momentum signal the cap reference is the breakout bar's own high; net P&L sign UNKNOWN; the defect is part of the frozen implementation | INFERRED from SOURCE_VERIFIED code |
| G1-10 (G1:L192-195) | two different corrections are documented, none chosen: A45 L191 (prior 20 bars excluding the decision bar) and A46 G1 (nearest confirmed swing high, implemented as `independent_swing_v1`) | CONTRADICTORY |
| CON-33 (REP:L1486) | severity labels differ (A42 vs A45); mechanism agreed | CONTRADICTORY |
| SE-03, SE §B8 ([STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md)) | W3 invariant and interface | as stated there |

**Current location** (SOURCE_VERIFIED)

| Site | `ea8ae4f` (deployed analyzer) | `46578aa` (`main` = `bb7825f`) |
|---|---|---|
| Cap window | `analyzer/technical_analyzer.py:409-411` (`df.tail(20)`, max high) | `analyzer/technical_analyzer.py:410-412` |
| Cap rule | `analyzer/technical_analyzer.py:454, 463-467`, hard-coded | `analyzer/technical_analyzer.py:455, 465-469` via `shared/t1_cap.py` |
| Policy | none | `shared/t1_cap.py:22-74`; `shared/config.py:124` default `legacy_window_v1`; unknown value refuses start (`shared/t1_cap.py:29-34`) |
| Provenance label | none | written only off the default (`analyzer/technical_analyzer.py:483-485`) |
| Research copy | `shared/strategy_math.py:53, 71-72` (G3:L56) | same rule |
| Dormant alternatives | `shared/trade_geometry.py` (`a46-tg-v1`, G1–G3) | same |
| Existing tests | — | `tests/test_t1_cap_policy.py`, `tests/test_a46_trade_geometry.py` |

**Consequences**
- *Opportunity discovery:* none on candidate generation; the setup predicate is unchanged.
- *Execution correctness:* when binding (upper wick between about 1.01% of entry and 1R), T1 lies inside (entry, entry + 1R) and can be below the flat 0.30% round trip (G3:L87-90). The capped T1 also sets the post-T1 protective stop and the post-T2 trailing floor (G3:L92-94). INFERRED.
- *Profitability measurement:* T1-touch rates and "protected" exits of momentum trades describe the capped geometry, not the designed 1R geometry, and are not comparable with any corrected version (G3:L126). Net sign UNKNOWN.

**Sub-items and proposed changes**

| Sub-item | Finding | Proposed change | Change class |
|---|---|---|---|
| R2.a | correction not chosen (G1-10) | present both documented corrections, plus "no cap", with their invariants, for an owner decision | Documentation/design |
| R2.b | geometry invariants are unwritten | write the invariants of [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md) §B8 as property tests over the existing `shared/t1_cap.py` policies | Safe development-only correction |
| R2.c | default rows carry no policy label; the contract hash ignores the switch (G3:L270) | include `T1_CAP_POLICY` in `config_hash` and label every row (R5.d) | Safe development-only correction |
| R2.d | the switch is absent from the deployed analyzer (CON-22) | a release built from a commit that contains `a4a7561`, at the legacy default | Production/runtime change |
| R2.e | activation of the chosen correction | switch the policy on Paper | Strategy-version-changing correction |

**Tests and acceptance criteria**
1. *Decision-bar independence (property):* under a corrected policy, changing the decision bar's high never changes the T1 reference.
2. *Legacy reproduction:* under `legacy_window_v1`, for every synthetic momentum breakout the reference equals the decision bar's high. This documents the frozen version exactly.
3. *Bracket invariants:* stop < entry < T1 ≤ entry + 1R; T2 and T3 unchanged by the cap; T1 never at or below entry.
4. *Cost-aware T1 (only if the owner adopts it):* T1's gross gain ≥ the declared research round trip (0.40%, stress 0.60%, `CH:L25`), never the runtime 0.30%.
5. *Provenance:* a non-default policy changes `config_hash` and writes the policy and `strategy_version` into the signal row and the `DecisionRecord`.
6. *Default byte-identity:* existing `tests/test_t1_cap_policy.py` remains green.

**Dependencies.** R4.b (the post-T1 break-even stop uses the double-counted term; geometry and accounting changes must stay separate, `CH:L39`); R5.d (identity); R8 (B requires a chosen correction, ERG:L131).

**Owner gates.** Correction choice (R2.a); geometry boundary (DFP:L63); an analyzer release (Class B) for R2.d; never attribute earlier outcomes to the corrected version (OOC:L36).

**Closure proof.** Tests 1–6 green; a released analyzer image whose content manifest shows `shared/t1_cap.py` (R5.a); a VERSION_BOUNDARY entry for the activation. No profitability inference.

## R3. Same 4h and 1d candle re-fire

**Charter row** (`CH:L38`): source and runtime-mode audit; idempotent symbol, strategy and candle key with regression tests; gate: integrity or version change.

**Fix status: OPEN at runtime; PARTIALLY_FIXED in source.** The A44 identity and insert-once fix exists but acts only under `SIGNAL_INTEGRITY_MODE=enforce`, and runtime is `off`. **Type:** strategy-version (integrity mode).

**Original evidence**

| Reference | Content | Class |
|---|---|---|
| HIS-25, HIS-26 (REP:L1143-1144) | the 2 h cooldown is shorter than a 4h or 1d bar, so one bar is re-emitted and per-signal n is inflated; duplicates handled only in enforce mode | SOURCE_VERIFIED |
| EXE-17 (REP:L837) | a same-bar re-fire after the cooldown is possible for 4h and 1d | SOURCE_VERIFIED |
| STR-33 (REP:L600); VER-02 (ADD:L94) | integrity mode defaults to off; unset at runtime, so off | SOURCE_VERIFIED; RUNTIME_VERIFIED |
| HIS-27, CON-32 (REP:L1145, L1485) | the cooldown read fails open in off mode; a test file calls it fixed, the off path still returns an empty set | SOURCE_VERIFIED; CONTRADICTORY |
| G3-03 (G3:L24, L225-237) | MECHANICALLY INFERRED for evidence validity, UNKNOWN economically; enabling enforce is a declared boundary; mode not in the hashed contract | INFERRED |
| G3-NV-07 (G3:L306) | whether the tracker admitted same-bar repeats before the freeze | NOT_VERIFIED |
| OF-15, OF-16, OF-24, OF-T07, OF-T09 ([OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md)) | cooldown fail-open, re-fire, the existing key, proposed changes | as stated there |

**Current location** (SOURCE_VERIFIED)

| Site | Deployed commit | `46578aa` |
|---|---|---|
| Re-upsert on every scan | `analyzer/main.py:165-174 @ ea8ae4f` (`signal_generated = false` on each analysis) | identical |
| Wall-clock cooldown | `signal_engine/signal_logic.py:25-26 @ ea8ae4f` (`COOLDOWN_SQL`, 2 h) | same lines |
| Cooldown fail-open (off mode) | `signal_engine/signal_logic.py:417-431 @ ea8ae4f` (`return set()` at L431) | L418-432 |
| Setup identity | `shared/signal_identity.py:64-88 @ ea8ae4f`: key over identity version, symbol, timeframe, candle open time, trade type, direction, `strategy_version`, setup policy | identical |
| Freshness rule | `shared/signal_identity.py:186-200 @ ea8ae4f` (rejects a decision before close or one bar or more after it) | identical |
| Enforce path | `signal_engine/signal_logic.py:730-737, 803-818 @ ea8ae4f`; insert-once `ON CONFLICT (setup_key)` at L261-263; migration `database/migrations/011_a44_signal_setup_key.sql` | L731-738, L804-819 |
| Mode default | `shared/config.py:118 @ ea8ae4f` (`off`) | `shared/config.py:120` |
| Tracker admission guard | `trade_tracker/main.py:718-740 @ bb7825f`: `DISTINCT ON (symbol)`, signals under 2 h old, and no `active_trades` row for the same (symbol, timeframe) opened within one candle interval of **now** | identical |
| Existing tests | — | `tests/test_a43_signal_integrity.py`, `tests/test_a44_selection_pipeline.py`, `tests/test_a44_migration_db.py`, `tests/test_a44_integration_db.py` |

**R3.b · INFERRED (from the SOURCE_VERIFIED query above; new in this register).** The tracker guard measures a wall-clock window from `opened_at`, not candle identity. It stops a second **trade** on the same bar only after a first one was opened. If the first emission of a bar was not admitted (capacity refusal, limit-wait expiry or risk rejection), a later re-emission of the same bar can be admitted, priced on that bar's old close. Whether this happened is NOT_VERIFIED (G3-NV-07).

**R3.d · INFERRED.** The setup key includes `strategy_version` = `APP_VERSION`. At runtime that is `sb-2026.08` (VER-13, ADD:L105), a label that does not identify implementations (G2-02, G2:L26-29). The key is therefore unique per candle but not per real strategy version. It depends on R5.d.

**Consequences**
- *Opportunity discovery:* duplicate 4h/1d signals occupy the one-signal-per-cycle slot and trigger the 2 h symbol cooldown again, which can displace other candidates. INFERRED.
- *Execution correctness:* a stale re-emission can be admitted on an old bar (R3.b), and a cooldown read error makes cooled-down symbols eligible (R3.c).
- *Profitability measurement:* per-signal statistics on 4h/1d count one setup more than once, which inflates n and understates dependence (G3:L235). Economic sign UNKNOWN.

**Sub-items and proposed changes**

| Sub-item | Finding | Proposed change | Change class |
|---|---|---|---|
| R3.a | signal-level re-fire | enable insert-once identity (enforce mode, or an identity-only mode split out of it) | Strategy-version-changing correction |
| R3.b | admission by wall-clock window | admit by setup key: at most one trade per key, ever | Strategy-version-changing correction |
| R3.c | cooldown read fails open | a read error blocks the cycle and is recorded | Strategy-version-changing correction |
| R3.d | key relies on `APP_VERSION` | derive the key from the five `StrategyVersion` identity fields, `lineage` excluded (R5.d; OF-T09; WP-IR-09) | Safe development-only correction (until activated) |
| R3.e | enforce mode bundles identity, a one-bar freshness bound, fail-closed reads and tracker refusals in one switch | document each behaviour separately, so the owner can decide whether to declare one boundary or several | Documentation/design |
| R3.f | regression coverage | the tests below, default-off | Safe development-only correction |

**Tests and acceptance criteria**
1. *Key uniqueness (idempotency):* re-analysing one closed 1d bar 12 times at 2 h intervals, and one 4h bar twice, yields exactly one `signals` row and one `signal.ready` event per (strategy_id, strategy_version, symbol, timeframe, bar close time). With concurrent inserts against migration 011's partial unique index, one row survives (DB test, disposable database).
2. *Key stability:* the key is invariant to re-analysis time, process restart and worker count. A recomputed, different bracket on the same bar is reported as a conflict and never re-emitted.
3. *New bar, new key:* consecutive bars give distinct keys; 15m behaviour is unchanged.
4. *Fail-closed cooldown:* a forced read error in the new path yields no eligible candidate and a recorded reason.
5. *Admission by key:* two signals with the same key give at most one `active_trades` row, whether or not the first was admitted.
6. *Freshness:* a decision before the bar's close, or one bar or more after it, is rejected with its reason code.
7. *Default byte-identity:* with the mode at `off`, outputs equal today's on the existing fixtures.
- Acceptance: 1–7 green; a version-identity test shows that changing `strategy_version` changes the key.

**Dependencies.** R5.d (identity), R6 (freshness and rejection records), R1 (same selection loop).

**Owner gates.** Enabling identity or enforce mode is an integrity-mode boundary (DFP:L63) and needs Class B deployment of signal_engine and trade_tracker configuration. Counting past repeats needs a permission over protected or pre-freeze data (OD-7).

**Closure proof.** Tests green; a VERSION_BOUNDARY activation record; afterwards, an owner-approved liveness check showing zero duplicate keys, without reading counts of outcomes.

## R4. Stop slippage double-accounting

**Charter row** (`CH:L39`): mechanism confirmed, realized impact UNKNOWN; separate accounting from stop-geometry corrections; gate: geometry gated.

**Fix status: OPEN.** Runtime accounting is unchanged; the research ledger `a48-cost-v1` counts slippage once (G3:L246). **Type:** engineering (accounting); the break-even stop part is strategy-version (geometry).

**Original evidence**

| Reference | Content | Class |
|---|---|---|
| HIS-31 (REP:L1149); CON-17 (REP:L1470) | a stop exit costs about 0.4% because slippage is counted twice | SOURCE_VERIFIED; CONTRADICTORY |
| EXE-13, EXE-14, EXE-15 (REP:L833-835) | flat 0.30% per trade on $50, stop fills × 0.999; effective about 0.40% on stops; below the 0.40% / 0.60% research baselines except on stops | SOURCE_VERIFIED; INFERRED |
| VER-19 (ADD:L111) | `FEE_ROUNDTRIP_PCT` 0.3 and `STOP_SLIPPAGE` 0.001 (code defaults) | RUNTIME_VERIFIED |
| G3-04 (G3:L25, L239-251) | conservative accounting direction; geometry sign UNKNOWN; cost fields are in the hashed contract | INFERRED / SOURCE_VERIFIED |
| ERG X-05 (ERG:L167) | the HIS-09 net figures plausibly carry the same bias; size UNKNOWN | INFERRED |
| CON-09 (REP:L1462) | operational counters and `/status` use gross labels, `/stats` net | CONTRADICTORY |
| OQ-08 (REP:L1520) | keep the flat 0.30%, or adopt 0.40% / 0.60%? | owner question |
| SE-12, SE §C1–C2 ([STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md)); PR-06 ([PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md)) | cost model and the risk guard's fee recomputation | as stated there |

**Current location** (SOURCE_VERIFIED; `46578aa` = `bb7825f` for these files)

| Site | Location |
|---|---|
| Flat round trip and its comment ("0.1%/side fee + ~0.1% slippage … consistent with STOP_SLIPPAGE") | `shared/config.py:90-92 @ 46578aa` (`ea8ae4f`: L88-90) |
| Stop slippage | `shared/config.py:107 @ 46578aa` (`ea8ae4f`: L105) |
| Stop fill | `shared/triple_barrier.py:308-322 @ 46578aa` (fill = stop × (1 − slippage), L320) |
| Break-even stop after T1 | `shared/triple_barrier.py:92-96 @ 46578aa`: min(T1, entry × (1 + round trip) / (1 − slippage)) |
| Stored economic result | `shared/fees.py:52-61 @ 46578aa` (`economic_close`: flat cost on the configured notional) |
| Risk guard net | `trade_tracker/main.py:947-952 @ bb7825f` (profit minus the flat fee, recomputed from current config, PR-06) |
| Evidence event | `trade_tracker/main.py:405-418 @ bb7825f` (net = gross − flat fee; `result_label` from gross) |
| Repository's own decomposition | `shared/execution_calibration.py:343-362 @ 46578aa` ("slippage on the stop fraction is charged twice") |

**Consequences**
- *Opportunity discovery:* none.
- *Execution correctness:* the post-T1 stop is placed about one slippage term higher than a single-count rule would place it, which changes exits (G3:L249).
- *Profitability measurement:* reported net on stop paths is understated by up to about 0.1 percentage point of the stopped fraction (INFERRED, G3:L249). Gross and net labels are mixed across surfaces (CON-09). The runtime model is not the owner research standard (OOC:L10; `CH:L25`).

**Sub-items and proposed changes**

| Sub-item | Finding | Proposed change | Change class |
|---|---|---|---|
| R4.a | accounting double count | add a single-count, per-leg cost ledger under a new `label_policy`, computed alongside the legacy fields; every entry names its `cost_model_id` (`legacy_tracker_v1`, `research_baseline_v1` or `research_stress_v1`), and `label_policy` stays a separate field (WP-IR-07); the policy in force is `net_after_modeled_cost_v1` (`shared/fees.py:L41 @ bb7825f`); legacy fields stay byte-identical and history is never rewritten | Safe development-only correction |
| R4.b | break-even stop uses both terms | change the break-even formula only as a declared geometry change | Strategy-version-changing correction |
| R4.c | runtime 0.30% vs research 0.40% / 0.60% | report both, side by side and labelled; the choice for Paper accounting is OQ-08 | Documentation/design |
| R4.d | gross/net label mixing | one net label per surface, with the label policy named | Safe development-only correction |
| R4.e | the flat fee ignores per-leg executed notional | per-leg fee on executed notional in the R4.a ledger (PR §3.6) | Safe development-only correction |
| R4.f | writing the R4.a fields on the host | deploy the ledger fields | Production/runtime change |

**Tests and acceptance criteria**
1. *Single count:* for a full stop exit at S with slippage s, the R4.a ledger charges fee per side plus s once; the legacy model `legacy_tracker_v1` reproduces flat 0.30% plus s exactly.
2. *Component uniqueness (property):* over random synthetic paths (targets, stop, expiry, mixed partial exits), each cost component identifier appears once per leg, and Σ leg costs = ledger total.
3. *No rewrite:* existing `trade_results` rows and their labels are unchanged by any migration (disposable-database test).
4. *Label policy:* every result row names its `label_policy`; aggregation across policies without stratification is refused.
5. *Geometry (R4.b only, if approved):* the break-even stop equals entry × (1 + c) / (1 − s), with c taken from the declared cost contract, independent of the accounting change.
- Acceptance: 1–4 green with legacy outputs byte-identical; R4.b is accepted separately.

**Dependencies.** R2 (T1 and break-even interplay), R7 (the ledger consumes these costs), R8 (research cost baselines). **Owner gates.** OQ-08; geometry boundary for R4.b; R4.f is a Class B release. **Closure proof.** Tests green; for R4.f, the release record; for R4.b, a VERSION_BOUNDARY entry.

## R5. Source, runtime, image parity and lineage

**Charter row** (`CH:L40`): not fully verified; read-only provenance inventory and discrepancy register; gate: no restart.

**Fix status: NOT_VERIFIED** for image content; **OPEN** for strategy-version identity and boundary records. **Type:** engineering.

**Original evidence**

| Reference | Content | Class |
|---|---|---|
| RT-14 … RT-17 (REP:L277-293) | image ids and labels; content parity recorded only in deploy records; image filesystems not hashed | RUNTIME_VERIFIED (metadata); DOCUMENTED_ONLY (content); NOT_VERIFIED |
| RT-23, RT-24, RT-35, RT-36 (REP:L304-305, L334-335) | config hashes and Compose blob match records; `release_manifest` still points to the a561 manifest | RUNTIME_VERIFIED; DOCUMENTED_ONLY |
| RT-37 (REP:L341); CON-21, CON-22 (REP:L1474-1475) | version drift between deployed commits and `main`; A42–A47 analysed `59297305`, not `ea8ae4f` | SOURCE_VERIFIED; CONTRADICTORY |
| RT-39, RT-40 (REP:L343-344) | the scanner image is an assembled overlay of older blobs; its imports NOT_VERIFIED | DOCUMENTED_ONLY; NOT_VERIFIED |
| CAL-08 … CAL-10 (REP:L761-763); VER-13 (ADD:L105) | weak version boundaries for data; `APP_VERSION` `sb-2026.08` at runtime vs `sb-2026.06` in code | SOURCE_VERIFIED; RUNTIME_VERIFIED |
| CON-04, CON-06, CON-07 (REP:L1457, L1459-1460) | record wording on digests; collector commit `1bfb5f6` vs `72c0bee`; stale "not wired" docstrings | CONTRADICTORY |
| VER-28 items 1, 5, 6, 7 (ADD:L245-257) | image parity, `APP_VERSION` source, observe code path, `.env` drift after creation | NOT_VERIFIED |
| G2-01 … G2-14 (G2:L21-166) | no historical result attributable to the deployed rules; labels do not identify implementations; freeze record retrospective | INFERRED; CONTRADICTORY |
| G3-07, G3-08 (G3:L30, L268-277) | the contract hash excludes the files of R1, R2 and the integrity mode | INFERRED |
| BL-10, BL-12 ([BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md)) | boundary amendments only on unmerged branches; the pause-to-resume transition is unrecorded on `main` | SOURCE_VERIFIED; NOT_VERIFIED |
| SE §B4, §E1 ([STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md)) | `StrategyVersion` identity chain | as stated there |

**Current location** (SOURCE_VERIFIED at `46578aa`)

| Site | Location |
|---|---|
| Documented baseline | `deploy/DEPLOYED.json:L35` (`observed_at` 2026-10-27), L37 (`release_manifest`), `source_commit` at L78, L112, L260, L314, L368 |
| Boundary record | `deploy/VERSION_BOUNDARY.md:L3-5` (rules), L7-36 (VB-2026-10-27-01; `config_hash_after` and `code_sha_after` PENDING at L22-23) |
| Paper-observe content check | `deploy/paper-observe-bb7825f/IMAGES.md:L35-37` (MATCH 46, FULL at deploy time), L49-57 (manifest kept on the host) |
| Image pins | `docker-compose.yml:L39, L70, L108, L149, L249` |
| Provenance tools | `ops/provenance/drift_check.py:1-27` (D2 content check only with `--deep`); `ops/provenance/runtime_manifest.py:1-18`; `ops/provenance/parity_inventory.py:1-16` (runtime parity never provable from GitHub alone) |
| Version label | `shared/config.py:45` (`APP_VERSION` default `sb-2026.06`) |
| Contract hash sources | `research/foundation/contract.py:68-75` (G3:L263) |
| Existing tests | `tests/test_drift_check.py`, `tests/test_parity_inventory.py`, `tests/test_decision_parity_before_after.py` |

**Consequences**
- *Opportunity discovery:* indirect. A wrong belief about which source runs would mis-describe the funnel (for example, `main`'s T1 switch, CON-22).
- *Execution correctness:* no runtime behaviour is RUNTIME_VERIFIED. All behaviour claims stand on DOCUMENTED_ONLY image content (BL-11).
- *Profitability measurement:* without a strategy identity that changes when decision code or configuration changes, evidence cannot be attributed to a version. This is the precondition for every economic statement (`CH:L29`; G3-08).

**Sub-items and proposed changes**

| Sub-item | Finding | Proposed change | Change class |
|---|---|---|---|
| R5.a | image content not re-verified | owner-approved `drift_check.py check --deep` (or `runtime_manifest.py verify`) per service against a committed or redacted manifest; read-only, outside Class A | Production/runtime change |
| R5.b | labels `revision=unknown`, collector unlabelled | wire source-revision labels into future builds and refuse a build without them | Safe development-only correction |
| R5.c | scanner assembled from older blobs | a scanner release from one commit, in a later release cycle | Production/runtime change |
| R5.d | no real strategy identity | specify `StrategyVersion` (strategy_id, semantic version, `source_hash` over the decision closure, `config_hash` over every decision key including `T1_CAP_POLICY` and `SIGNAL_INTEGRITY_MODE`, `contract_hash`), the five identity fields, with `lineage` as recorded metadata outside the identity (WP-IR-09); emit it on every `DecisionRecord` behind a default-off flag | Documentation/design (spec), then Safe development-only correction (code) |
| R5.e | boundary record incomplete on `main` | integrate amendments A1/A2 after owner review of their protected content; fill the PENDING fields by amendment, never by rewriting (`deploy/VERSION_BOUNDARY.md:L44-46`) | Documentation/design |
| R5.f | pause-to-resume transition unrecorded | owner-approved read of the pause-decision row history, metadata only, recorded as a dated note | Production/runtime change |
| R5.g | historical lineage | keep G2 attributions; label every historical figure with its version window; no pooling | Documentation/design |
| R5.h | records: collector commit, digest wording, stale docstrings (CON-04, CON-06, CON-07) | correct by dated notes | Documentation/design |

**Tests and acceptance criteria**
1. *Hash coverage (property):* changing any file in the declared decision closure, or any decision configuration key, changes `source_hash` or `config_hash`; a change outside the closure does not. This closes G3-08.
2. *Emission refusal:* with the flag on, a `DecisionRecord` without `strategy_version`, `source_hash` and `config_hash` is refused (fail closed).
3. *Static inventory:* every DEPLOYED.json service has a `source_commit` and either a committed manifest path or an explicit host-only marker (`parity_inventory.py`, existing test pattern).
4. *Runtime closure (R5.a):* `drift_check.py check --deep` reports MATCH with verification FULL for each bot service, recorded with date and commit.
- Acceptance: 1–3 green in CI; 4 as an owner-approved operation record.

**Dependencies.** None upstream; R1, R2, R3, R4.b, R7 and R8 all depend on R5.d. **Owner gates.** R5.a and R5.f need owner approval (OQ-03; VER-28 item 1); no restart (`CH:L40`); merging boundary amendments is an owner decision. **Closure proof.** Merged identity code with tests; dated verification records for R5.a; completed VERSION_BOUNDARY fields.

## R6. Filter rejection, freshness and ranking transparency

**Charter row** (`CH:L41`): economic effects unverified; full funnel specification and safe observability plan; gate: protected data requires permission.

**Fix status: OPEN.** **Type:** engineering (observability); every rule change is strategy-version. The full current-state trace and target design are in [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) (silent-drop register OF-03 to OF-21; change register OF-T01 onward). This item records only the tracker-level facts and the remediation status.

**Original evidence**

| Reference | Content | Class |
|---|---|---|
| UNI-01, UNI-02, UNI-11, UNI-12 (REP:L683-684, L693-694) | USDT pairs only; three stablecoins excluded; no depth or size filter; a timeframe skipped below 200 bars | SOURCE_VERIFIED |
| UNI-18, UNI-19 (REP:L700-701) | one signal per cycle; no daily cap on the live path; ranking favours the deepest majors | SOURCE_VERIFIED; INFERRED |
| EXE-01, EXE-02 (REP:L800-801) | ordered gates; a refused delivery is acknowledged and lost | SOURCE_VERIFIED |
| EXE-05, EXE-06, EXE-09 (REP:L809-811) | closed bars by host clock; no exchange time sync; in off mode the candle age is never checked (a 1d bar can be about 24 h old) | SOURCE_VERIFIED; INFERRED |
| MKT-02, MKT-13 … MKT-16 (REP:L644, L655-658) | scanner BTC trend fails open; macro fail-closed on staleness but fail-open on missing keys | SOURCE_VERIFIED; INFERRED |
| STR-32 (REP:L599) | ranking cannot change signal frequency (synthetic) | HISTORICAL_REPORTED |
| VER-20, VER-24 (ADD:L112, L165-167) | evidence stream on in signal_engine, off in the scanner; blacklist empty | RUNTIME_VERIFIED |
| OQ-07 (REP:L1519) | "all eligible assets" or a restricted set? | owner question |

**Current location** (SOURCE_VERIFIED)

| Stage | Location | Record of a drop |
|---|---|---|
| Scanner filters | `scanner/scanner_logic.py:88-115 @ 46578aa` (blob `fa03cc2a`, identical at `ea8ae4f`) | none: `return False`; scanner evidence off (VER-20) |
| Analyzer history | `analyzer/technical_analyzer.py:47-48 @ ea8ae4f` | none: `return None` |
| Signal-engine gates | `signal_engine/signal_logic.py:719-861 @ ea8ae4f` | per-candidate reason codes in the evidence stream; the DB keeps **one reason per symbol** (`signal_engine/main.py:179-186`, OF-08) |
| Limit cut | `signal_engine/main.py:146-155 @ ea8ae4f` | `selection.truncation` evidence record only (R1) |
| Delivery | `telegram/main.py:364-382 @ bb7825f` (pause or capacity refusal) | acknowledged and lost (OF-10) |
| Admission | `trade_tracker/main.py:705-904 @ bb7825f` | entry rejection terminal; risk rejection retried within 2 h; supersession by `DISTINCT ON (symbol)` unrecorded (OF-11) |
| Unwired building blocks | `shared/candidate_selection.py` staged pipeline (OF-23); `shared/shadow_opportunity.py` on unmerged `integration/rnd` (`1dc9ac5`); `d1c24bd` stale-fill-price guard on unmerged `integration/paper-observe-activation` | — |

**Consequences**
- *Opportunity discovery:* the set the system can trade is narrower than the eligible spot universe (UNI-19). How much narrower, and why, is unknowable today because the scanner and analyzer drops leave no record.
- *Execution correctness:* decisions can rest on a bar up to one full period old (EXE-09). Three context reads fail open (OF section 4).
- *Profitability measurement:* without a conservation check, no evidence window can show what was not traded and why. "Discovery is not execution" cannot be audited.

**Sub-items and proposed changes** (details in [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) §9)

| Sub-item | Finding | Proposed change | Change class |
|---|---|---|---|
| R6.a | scanner and analyzer drops are silent | shadow `RejectionRecord` writer with closed reason taxonomy and per-stage counters (OF-T01) | Safe development-only correction |
| R6.b | per-symbol reason collapse | per-(symbol, strategy, timeframe, bar) decision keys (OF-T02) | Safe development-only correction |
| R6.c | limit-cut and capacity drops unrecorded in the DB | covered by R6.a: the limit cut at stage F6 (`F6.legacy_alphabetical_cut` today, in shadow; `F6.resource_cap` or `F6.rank_below_cap` in a target version) and capacity drops at stage F7 (`F7.capacity_full`, from the single capacity authority, WP-IR-03); a rank loss is never labelled as capacity (WP-IR-04); the unmerged shadow ledger is the reference for capacity-blocked candidates | Safe development-only correction |
| R6.d | no decision-bar age bound in off mode; host clock | venue-synchronised closed-bar rule and freshness bound (OF-T08) | Strategy-version-changing correction |
| R6.e | three fail-open reads | make each explicit and recorded, fail-closed or flagged as the owner decides (OF-T07) | Strategy-version-changing correction |
| R6.f | eligibility gaps (venue filters, stablecoins, depth) | `EligibilityResult` rule set (OF-T04, OF-T05) | Strategy-version-changing correction |
| R6.g | measuring funnel counts on post-freeze records | only under an owner permission | Protected research or simulation |
| R6.h | enabling the R6.a–c writers on the host | deploy with the evidence retention decision of OF §8.4 | Production/runtime change |

**Tests and acceptance criteria**
1. *Conservation (property):* for every stage, `count_in = count_out + Σ count(RejectionRecord by reason)`; any silent drop fails the test.
2. *Record completeness:* each `RejectionRecord` has `stage` F0 to F7, a `reason_code` from the closed taxonomy v1 whose prefix equals `stage`, a `sub_stage` from its closed enumeration or null, the subject fields `symbol`, `timeframe` and `strategy_id` nullable by scope, and `as_of` in integer UTC epoch milliseconds (OPPORTUNITY_FUNNEL.md §8.1; WP-IR-01); an unknown code or `sub_stage` is refused.
3. *Per-timeframe reasons:* one symbol with different outcomes on 15m, 4h and 1d keeps three reasons.
4. *Freshness:* a bar older than the bound is rejected with a reason; a forming bar is never used; a simulated host-clock skew is detected.
5. *Fail-open removal:* each of the three reads, when failing, produces a recorded outcome, never a silent default.
6. *Default byte-identity:* with every flag off, decisions equal today's on fixed fixtures.
- Acceptance: 1–6 green; for R6.h, a deployment record. No count from protected records is reported without permission.

**Dependencies.** R1 (selection stage), R3 (freshness, identity), R5.d (strategy identity in records), R7 (portfolio-capacity stage). **Owner gates.** Protected-data permission for any count (`CH:L21`, `CH:L41`; OD-7); OQ-07; the OF owner decisions. **Closure proof.** Merged writers with tests; after deployment, an owner-approved liveness check that the conservation check passes, reported without counts.

## R7. Equity ledger and realized-profit compounding

**Charter row** (`CH:L42`): owner goal clear, implementation not fully verified; reconcile the existing implementation and design a risk and capital contract; gate: no live allocation change.

**Fix status: OPEN.** There is no ledger and no compounding; sizing is a fixed notional. **Type:** engineering (ledger, reconciliation); sizing and compounding are strategy-version changes under an owner risk policy. The full reconciliation (PR-01 to PR-24), target ledger, invariants, decisions PR-OD1 to PR-OD22, changes PR-C01 to PR-C16 and tests PR-T01 to PR-T20 are in [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md). This item does not re-derive them.

**Original evidence**

| Reference | Content | Class |
|---|---|---|
| EXE-12 (REP:L832) | fixed `TRADE_AMOUNT_USDT` 50 on a virtual 500; no risk or volatility sizing; the tracker never reads `size_multiplier` | SOURCE_VERIFIED |
| RSK-01, RSK-02, RSK-05, RSK-06 (REP:L851-856) | risk gate, capacity, regime-cap key; utilisation at most 20% | SOURCE_VERIFIED; INFERRED |
| ECO-01, ECO-07 (REP:L1225, L1241) | not a capital-allocation system; no mark-to-market equity curve at runtime | INFERRED |
| VER-12, VER-17 (ADD:L104, L109) | capacity min(10, 2) = 2; 50 / 500 and the loss and exposure limits | RUNTIME_VERIFIED |
| G4-12 (G4:L44) | 20% utilisation does not change a Sharpe ratio but fixes the economic size | INFERRED |
| PR-01 … PR-24 ([PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) §1–§2) | no ledger table (PR-01), fixed capital (PR-02), no per-position size (PR-03), no compounding (PR-04), losses reduce capacity not notional (PR-05), recomputed flat fee (PR-06), unrealized P&L ignores partial exits (PR-07), mixed-basis drawdown (PR-08), recovery epoch moves every baseline (PR-10), no reserved capital (PR-12), no lot rounding (PR-18), no daily mark-to-market series (PR-22) | as classed there |
| OQ-07 (REP:L1519) | is the 2 × $50 capacity intended? | owner question |

**Current location** (SOURCE_VERIFIED; `46578aa` = `bb7825f` for these files)

| Site | Location |
|---|---|
| Sizing constants | `shared/config.py:106` (`TRADE_AMOUNT_USDT`), `:142` (`RISK_CAPITAL_USDT`), `:150` (`RISK_CANARY_MAX_OPEN_TRADES`, default 1), `:159` (`MAX_OPEN_TRADES`) |
| Risk snapshot | `trade_tracker/main.py:920-1006 @ bb7825f` (`assess_new_trade_risk`): realized net since `effective_risk_start()` (L926-932, L947-955), unrealized mark per open trade on the full notional (L966-974), limits built from fixed capital (L976-988) |
| Equity and exposure | `shared/risk_management.py:78-93 @ 46578aa`: equity = capital + realized + unrealized; every percentage divides by the fixed capital; gross exposure = (open + 1) × fixed notional |
| Sizing multipliers | `shared/economic_halt_policy.py:18-20 @ bb7825f`: change capacity, not notional (RSK-02) |
| Close accounting | `trade_tracker/main.py:1409 @ bb7825f`; `shared/fees.py:52-61 @ 46578aa` |
| Unwired references | `lab/account.py` on unmerged `lab/l1-account-safeguards` (`c42e6ea`): pure Decimal per-strategy account with a hash-chained ledger, imported by nothing; `shared/shadow_opportunity.py` on unmerged `integration/rnd` |
| Existing tests | `tests/test_risk_management.py`, `tests/test_risk_epoch.py`, `tests/test_paper_economic_observation.py`, `tests/test_fees.py` |

**Consequences**
- *Opportunity discovery:* capacity (2 slots, one signal per cycle) limits what can be executed, not what is discovered. Refused candidates are lost (R6, OF-10).
- *Execution correctness:* equity used by the risk guard mis-states partially exited positions (PR-07) and mixes bases for drawdown (PR-08); a recovery epoch also re-bases drawdown (PR-10). INFERRED from SOURCE_VERIFIED code.
- *Profitability measurement:* there is no reconciled cash, committed, reserved, realized, unrealized and equity series, so neither portfolio return nor the A29 daily mark-to-market endpoint can be computed from runtime records (PR-22; `CH:L27`).
- *Compounding:* realized net profit never feeds future size, and losses do not reduce notional (PR-04, PR-05). The owner objective (`CH:L8`) is unmet by design, not by a defect.

**Sub-items and proposed changes** (change IDs from [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) §7)

| Sub-item | Finding | Proposed change | Change class |
|---|---|---|---|
| R7.a | no ledger contract | ledger, risk budget and sizing contract (PR-C01) | Documentation/design |
| R7.b | no ledger code | pure ledger library, legacy-mode adapter and reconciliation (PR-C02, PR-C03) | Safe development-only correction |
| R7.c | no ledger storage | additive migration, disposable-database only (PR-C04) | Safe development-only correction |
| R7.d | no runtime ledger | shadow ledger writer, default off, changes no decision (PR-C05) | Safe development-only correction |
| R7.e | daily equity series for the endpoint | daily UTC mark-to-market snapshots from the shadow ledger (PR-C12) | Safe development-only correction |
| R7.f | net-labelled counters | net counters beside the legacy gross counters (PR-C14; CON-09) | Safe development-only correction |
| R7.g | risk inputs mis-state equity (PR-06, PR-07, PR-17) | risk inputs from the ledger (PR-C07) | Strategy-version-changing correction |
| R7.h | no compounding, no risk-based size | `SizingDecision` engine: realized-net sizing base, loss de-risking, caps (PR-C08, PR-C09, PR-C11, PR-C13) | Strategy-version-changing correction |
| R7.i | research-cost valuation | shadow valuation at 0.40% and 0.60% (PR-C15) | Protected research or simulation |
| R7.j | activation on Paper | any flag, migration or image change for R7.d–R7.h (PR-C16) | Production/runtime change |

**OWNER DECISION REQUIRED.** Per-trade risk, sizing method, sizing base and settlement of gains, portfolio heat, exposure caps, maximum positions, cash reserve, liquidity cap, drawdown and loss ladders, re-basing at recovery and the genesis capital are owner decisions PR-OD1 to PR-OD22 ([PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) §6). No percentage, slot count or reserve is chosen here (`CH:L27`). Unrealized profit is never available cash.

**Tests and acceptance criteria.** PR-T01 to PR-T20 (synthetic events only). The tests that decide engineering closure are:
1. *Ledger invariants after every transition* (PR-T01): cash never negative, no leverage, Σ legs = filled quantity, equity = cash + marked open positions.
2. *Idempotency and replay* (PR-T02 to PR-T04): duplicate `event_id` is a no-op; a conflicting payload refuses; a restart gives exactly-once results.
3. *Unrealized never capital; compounding from realized net only* (PR-T06, PR-T07): marks do not change the sizing base; a net gain raises it only at settlement; a loss lowers it at close.
4. *Legacy parity* (PR-T09, PR-T10): legacy outputs byte-identical; the partial-exit divergence equals the PR-07 expression.
5. *Shadow non-interference* (PR-T19): admissions, results and outbox events identical with the writer off and on.
- Acceptance: as in [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) §9. Closing R7 establishes measurability, not an edge.

**Dependencies.** R4 (cost legs), R5.d (version identity in every ledger entry), R6 (portfolio-capacity rejections), R8 (the endpoint the daily series serves). **Owner gates.** PR-OD1 to PR-OD22; no live allocation change (`CH:L42`); a version boundary for every decision-changing change; real money is forbidden (DFP:L46). **Closure proof.** The §9 criteria of the portfolio document, cited by commit, test run and reconciliation record.

## R8. Economic viability of active hypotheses

**Charter row** (`CH:L43`): economic viability of B, C and other active hypotheses is INCONCLUSIVE; design theses, benchmarks, costs and power options; gate: OD-DF-1, OD-DF-2 and owner approval.

**Fix status: NOT_VERIFIED.** The ERG-01 verdict **INCONCLUSIVE** is preserved: existing evidence cannot resolve Candidate B versus Candidate C, and no candidate has been selected, pre-registered or tested (ERG:L5, L119-121, L205). **Type:** research. This is not a defect and has no "fix"; it has decisions and, after approval, evaluations.

**Original evidence**

| Reference | Content | Class |
|---|---|---|
| ERG-01 §5–§7 (ERG:L87-133) | G1–G5 verdicts and the ordered owner decisions | INFERRED; SOURCE_VERIFIED |
| G1-01, G1-02 (G1:L15, L19) | HIS-05 is MATERIALLY DIFFERENT from current momentum and from the successor concept | INFERRED |
| G2-01, G2-08 (G2:L21, L120) | no historical result is attributable to the deployed rules | INFERRED |
| G3-05, G3-06, G3-09 (G3:L28-29, L287-293) | all evidence embeds W3 and the alphabetical cut; no realized-impact measurement; each correction starts a version with no evidence | INFERRED; NOT_VERIFIED |
| G4-04, G4-05, G4-06 (G4:L36-38) | 365-day MDE SR 3.48 to 7.00; power for SR 0.5 / 1 / 2 at most 0.016 / 0.051 / 0.262; the horizon is binding | INFERRED (ILLUSTRATIVE inputs) |
| G5-01 … G5-07, G5-25 … G5-27 (G5:L40-46, L373-380) | neither candidate specified or evidenced; no dominance; D (pause) not dominated, D (stop) not supported | INFERRED |
| HIS-01 (REP:L1003), HIS-42 (REP:L1167), ECO-08 (REP:L1242) | pre-freeze Paper: gross PF 0.735, net PF 0.598 on 2,518 mixed-version trades; no robust net-positive real-data study; no profitability claim supported | HISTORICAL_REPORTED; INFERRED |
| STR-25 (REP:L434) | all outcome evidence of the current rules lies in the sealed holdout | INFERRED |
| GOV-02, GOV-03, GOV-13, GOV-16 (REP:L1288, L1296, L1351, L1354) | A29 HOLD; nothing has passed the ladder; S4 not tested; Design A not authorized | DOCUMENTED_ONLY |
| `CH:L13-18` | preserve external reviews and ERG-01; never transfer results of materially different strategies; never discard relevant negative evidence | DOCUMENTED_ONLY (policy) |

**Current location**
- *Candidate B and C:* no tracked specification at any commit (G1-09, G5-08; absence findings, SOURCE_VERIFIED as searched by ERG-01).
- *Benchmarks:* Design A only on unmerged `feature/design-a-v1` (`ebf8d8a`, BL-08); a benchmark or optional hypothesis, never the mandate (`CH:L15`, `CH:L23`).
- *Research code on `main`:* `research/mechanisms/` (refuses non-synthetic data without a `DatasetPermission`, HIS-15); `research/power/ladder_power.py` (ELP:L15).
- *Unmerged synthetic tooling:* `research/variant-ledger` (alpha ledger, synthetic); `integration/rnd` A45-G net evaluation (synthetic).

**Consequences**
- *Opportunity discovery:* none directly. Which strategies define "opportunity" is this item's open question.
- *Execution correctness:* none directly.
- *Profitability measurement:* no economic statement about any active hypothesis is possible today. Within 365 days a modest edge cannot be confirmed under the governed design (G4-06). Insufficient power is not evidence of no edge (ERG:L115).

**Sub-items and proposed changes**

| Sub-item | Content | Proposed change | Change class |
|---|---|---|---|
| R8.a | B (corrected 4h/1d momentum) unspecified | a written specification: thesis, universe, regime, timeframes, entry, invalidation, exits, holding, costs, failure and kill criteria, chosen W3 correction, selection rule, version boundary (ERG:L131) | Documentation/design |
| R8.b | C (regime-filtered trend pullback) unspecified | the same specification fields, its hypothesis source and its relation to Design A (G5-21, G5-22) | Documentation/design |
| R8.c | benchmarks | passive BTC/cash and Design A as declared benchmarks with the same cost model | Documentation/design |
| R8.d | power and horizon | present the OD-DF-2 options with their trade-offs (longer horizon, multi-candidate design, licensed history for qualification plus a prospective check); no choice here | Documentation/design |
| R8.e | cost basis | research baseline 0.40% and stress 0.60% round trip, fee 0.10% per side included, no double count (`CH:L25`), kept separate from the tracker's 0.30% (DFP:L61) | Documentation/design |
| R8.f | any evaluation | only after WP3 decisions and a pre-registration | Protected research or simulation |
| R8.g | HOLD scope D1/D2 vs D1–D5 (CON-36) | owner clarification (OQ-06) | Documentation/design |

**Tests and acceptance criteria** (design-level; nothing is run)
1. *Specification completeness:* every field of R8.a/R8.b is filled; any missing field blocks pre-registration.
2. *Pre-registration integrity:* endpoint, horizon, alpha, critical-value mode, cost model, benchmark and kill criteria are fixed before any data access; the A29 defaults stay unless the owner formally changes them (`CH:L52`).
3. *Synthetic-only tooling tests* may run in CI; no real or protected data without a recorded `DatasetPermission` (DFP:L42).
4. *Outcome vocabulary:* an inadequately powered result is reported INCONCLUSIVE, never re-labelled (`CH:L52`; G4-13).
- Acceptance: owner-approved specification and pre-registration documents. Viability itself is never "closed" by engineering.

**Dependencies.** R1, R2, R3 (B's prerequisites), R4.c and R7.e (cost basis and the daily equity series of the endpoint), R5.d (version identity). **Owner gates.** In ERG-01 order (ERG:L207-213): horizon, endpoint and validation design (G4 Q1, Q2, Q6; OD-DF-2); dataset permission (OD-DF-1, licence, `DatasetPermission`); capacity and book design (G4 Q4) and the route to planning inputs (G4 Q7); the program slot plan including Design A (E1–E8); candidate prerequisites; then alpha allocation (Q3) and calibration standard (Q5). Pre-registration and any test each need their own approval. **Closure proof.** Dated owner decisions in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md); after WP4, a pre-registered result reported with its failures and inconclusive findings.

## R9. Backups, runtime health and drift

**Charter row** (`CH:L44`): previous operational findings; independent health and safe remediation; gate: no unapproved production actions.

**Fix status: OPEN** for every sub-item; root causes NOT_VERIFIED. **Type:** engineering and operations. Nothing here touches the trading decision path except R9.d, which guards against an accidental one.

**Original evidence**

| Reference | Content | Class |
|---|---|---|
| VER-27 (ADD:L231-241); VER-31 item 6 (ADD:L293) | collector Docker-unhealthy for about 65 hours; health file fresh with state DEGRADED; 5 latched incidents (3 WARNING, 2 CRITICAL), one key `previous_run_stopped_failed`; CRITICAL cause NOT_VERIFIED; forward-data completeness must be checked before any analysis of that period | RUNTIME_VERIFIED; NOT_VERIFIED |
| RT-45 (REP:L359); CON-05 (REP:L1458); ARC-14 (REP:L205) | cause unknown at the audit; the Stage A record said HEALTHY; incidents latch until acknowledged | NOT_VERIFIED; CONTRADICTORY; SOURCE_VERIFIED |
| RT-01 … RT-05, RT-07 (REP:L244-250); RT-27 (REP:L308); HIS-45 (REP:L1081) | production checkout on `integration/research-pipeline` at `63da7d3`, no upstream, 267 commits behind `eba90dd`, uncommitted edits in 5 files matching no commit, 104 untracked entries, no `deploy/` or `ops/`; not executed by any running service | RUNTIME_VERIFIED; INFERRED |
| CON-02, CON-03 (REP:L1455-1456) | procedures assume `ops/compose-safe` in the production directory; blob-level parity only | CONTRADICTORY |
| CON-01 (REP:L1454); BL-17 | the canonical runbook's pin paragraph is stale | CONTRADICTORY |
| CON-08, CON-11 (REP:L1461, L1464); BL-18 | CLAUDE.md describes continuous learning and DB-over-`.env` precedence that do not hold on the live path | CONTRADICTORY |
| ARC-18, ARC-19, ARC-20 (REP:L214-216); LRN-03, LRN-05 (REP:L773, L775); CON-19 (REP:L1472); RT-11, RT-12 (REP:L271-272) | the learner builds from the production working tree; a restart would run undeployed code; the learner script is also inside the signal_engine image; the stopped state relies on a manual-stop flag and a profile | SOURCE_VERIFIED; INFERRED |
| VER-14, VER-29 (ADD:L106, L261-263); LRN-19 (REP:L789); VER-31 item 4 (ADD:L291) | configured learner loop 24 h, not 12 h; learned gates off but non-expiring, one throttled cell: one flag flips behaviour with no version boundary | RUNTIME_VERIFIED; INFERRED |
| RT-43, RT-44 (REP:L357-358); RT-35 (REP:L334) | bot services healthy at both audit samples; tracker WARN lines not inspected; DEPLOYED.json does not track health | RUNTIME_VERIFIED; NOT_VERIFIED |
| `docs/ops/BACKUP_MODEL_RD.md:L3-18 @ 46578aa`; DFP:L91, L116 | observations of 2026-10-20: the bot database is dumped nightly by another project's local job, never restore-tested for this database, nothing off-host; the bot's own nightly backup failing every night since 2026-10-10; a latent automatic deletion that conflicts with the R1.3 deletion rule; model PROPOSED as OD-DF-4 | DOCUMENTED_ONLY |
| RT-19 (REP:L295) | rollback images present locally | RUNTIME_VERIFIED |

**Current location** (SOURCE_VERIFIED at `46578aa` unless stated)

| Site | Location |
|---|---|
| Collector health check | `p2_forward/Dockerfile:16-17 @ 72c0bee` (as cited in ADD:L233) |
| Runbook pins and halt text | `docs/ops/COMPOSE_OPERATIONS.md:L40-48` (stale pins), L16-28 (PAPER_HALTED stated, with dated notes); its Class B image gate points to `deploy/aiohttp-3.14.3/IMAGES.md` (L114, L125) |
| CLAUDE.md statements | `CLAUDE.md:L3` (continuous learning), L37 (Class B from the production directory), L48 (DB over `.env`) |
| Learner service | `docker-compose.yml:L211-219` (`build` context `.`, `signal_engine/Dockerfile`, `profiles: ["learner"]`, `restart: unless-stopped`) |
| Optimizer service | `docker-compose.yml:L183-191` (`profiles: ["disabled"]`, `build` from the working tree) |
| Learner refusal | `ops/compose-safe` (refuses the learner, ARC-19); `tests/test_compose_safe.py` |
| Drift gate | `ops/provenance/drift_check.py:1-27` (D7 learner not running); `CLAUDE.md:L18` (a gate, not a scheduled service) |
| Backups | `ops/tsb-p1bg/tsb-p1bg-backup.sh`; `docs/ops/BACKUP_MODEL_RD.md`; `docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md`; `CLAUDE.md:L15-19` |
| Unmerged related work | `integration/rnd`: collector health tiering and integrity/coverage split (`dfa8f65`, `d23be24`), one alert per DEGRADED episode (`3693017`), backup verification of sealed days (`b225472`, `44ae384`), all default off; `safety/disable-auto-tune` (`3d1857d`); `feat/technical-halt-recovery` |

**Consequences**
- *Opportunity discovery:* none on the trading path; the collector is not on it (ARC-14).
- *Execution correctness:* the learner hazard (R9.d) could start undeployed code that writes learned gates, and one flag would then change selection without a boundary. INFERRED.
- *Profitability measurement:* forward collector data from a DEGRADED period may be incomplete (VER-31 item 6). A database loss without a tested restore would lose Paper evidence irrecoverably (`docs/ops/BACKUP_MODEL_RD.md:L25`). Stale runbooks raise the risk of an unsafe operation, and an unsafe operation threatens evidence integrity.

**Sub-items and proposed changes**

| Sub-item | Finding | Proposed change | Change class |
|---|---|---|---|
| R9.a | collector DEGRADED, CRITICAL cause unknown | owner-approved read of collector health metadata and incident keys, then a written remediation decision; acknowledgement only by the reviewed procedure (OQ-04) | Production/runtime change |
| R9.a2 | health tiering and alerting | review and integrate the default-off `integration/rnd` collector changes | Safe development-only correction |
| R9.b | stale production checkout | owner decision (OQ-05): document the checkout as non-source and keep it, or align it to `main` by a reviewed procedure that preserves the uncommitted edits as evidence | Production/runtime change |
| R9.c | stale runbook and CLAUDE.md statements (CON-01, CON-08, CON-11, PAPER_HALTED) | dated corrections; production-operation definitions need an independent review (DFP:L73) | Documentation/design |
| R9.d | learner and optimizer build from the working tree | design: pin the learner to a released image or remove its `build:`; require a version boundary record before `LEARNING_GATES_ENABLED` can be set; delete nothing without a named approval | Documentation/design |
| R9.d2 | static guards for R9.d | tests below | Safe development-only correction |
| R9.d3 | applying the Compose change | PR, then a separate owner-authorized install with `config --hash` verification (`CLAUDE.md:L44`) | Production/runtime change |
| R9.e | backup state | OD-DF-4 choice; one isolated restore test of the bot database (no outcome reads); retire the failing job only after a replacement works (`docs/ops/BACKUP_MODEL_RD.md:L31-60`) | Production/runtime change |
| R9.f | health not tracked in DEPLOYED.json; tracker WARN lines unread | add health and a redaction-safe warning category count to the observation record | Safe development-only correction |
| R9.g | the stale `docker-compose.yml.bak` still defines claude_review (ARC-18) | mark it historical by dated note; deletion only by named approval | Documentation/design |

**Tests and acceptance criteria**
1. *Runbook parity (static):* a test parses `docs/ops/COMPOSE_OPERATIONS.md` pin statements and `deploy/DEPLOYED.json` `image_ref` values and fails on any mismatch. It fails today (proving CON-01) and passes after R9.c.
2. *Build policy (static):* every Compose service with `build:` has a profile in an allow-list and is refused by `ops/compose-safe`; after R9.d3, `continuous_learner` has no `build:` (extends `tests/test_compose_safe.py`).
3. *Gate activation guard:* `LEARNING_GATES_ENABLED=true` without a matching boundary record fails a pre-deploy check (synthetic configuration).
4. *Collector health tiering:* the `integration/rnd` synthetic tests (`p2_forward/tests/test_health_view.py`, `test_monitor_episodes.py`, `test_backup_existing.py`) green before integration.
5. *Restore (R9.e, owner-approved):* an isolated restore passes structural checks only; no outcome read.
- Acceptance: 1–4 green in CI or the local CI equivalent; 5 and R9.a, R9.b as dated operation records under the absolute STOP rule (`CLAUDE.md:L45`).

**Dependencies.** R5 (drift and parity tooling); R8 (collector completeness before any forward analysis). **Owner gates.** OQ-04, OQ-05, OD-DF-4; every host action is Class B or a separately named approval; Class C stays forbidden (`CLAUDE.md:L40`). **Closure proof.** Merged documentation and static tests; dated records of the collector decision, the checkout decision, the restore test and the Compose install.

## Cross-item dependencies

| Item | Needs first | Unblocks |
|---|---|---|
| R5.d identity | — | R1.c, R2.e, R3.a, R4.b, R7.g–R7.h, R8 |
| R6.a–c observability | R5.d (fields) | measurable R1, R3 and R7 activations |
| R3 integrity | R5.d | R1.c (dedupe inside selection), R8.a |
| R1 selection | R5.d, R6, R3 | R8.a |
| R2 geometry | R2.a owner choice, R5.d, R2.d release | R4.b, R8.a |
| R4.a accounting | — | R7 cost legs, R8.e |
| R7 ledger | R4.a, R5.d | R7 sizing, the R8 endpoint series |
| R9.c, R9.d | — | safer execution of every Class B step above |

## NOT VERIFIED items

| ID | Question | Blocker |
|---|---|---|
| R-NV-1 | Do the running images contain the cited source (all items)? | image content not re-verified (RT-17; VER-28 item 1); owner approval |
| R-NV-2 | How often did the 200-row cut bind (R1)? | protected post-freeze records (G3-NV-03; OD-7) |
| R-NV-3 | Were same-bar repeats admitted as trades (R3.b)? | lifecycle data out of scope (G3-NV-07) |
| R-NV-4 | Realized impact of W3 and of the stop double count (R2, R4) | no admissible measurement (G3-NV-02; G3:L248) |
| R-NV-5 | When and how the pause was resumed between 2026-10-27 and 2026-10-31 (R5.f) | no tracked record on `main`; amendments unmerged (BL-12) |
| R-NV-6 | Root cause of the collector's CRITICAL incidents (R9.a) | incident text withheld; investigation not authorized (VER-28 item 2) |
| R-NV-7 | Current backup state (R9.e) | last observation 2026-10-20; host access out of scope |
| R-NV-8 | Any runtime value after 2026-10-31 | no observation in this phase (ADD:L257) |

## Inconsistencies noted while building the register

| Observation | Class |
|---|---|
| HIS-27 / CON-32: a test file calls the cooldown fail-open fixed, but the off path still returns an empty set (`signal_engine/signal_logic.py:431 @ ea8ae4f`, `:432 @ 46578aa`) | CONTRADICTORY |
| OF-07: eligible losers are labelled `not_selected_capacity`, although they lost on rank, not on capacity (`signal_engine/signal_logic.py:853 @ ea8ae4f`); the target code is `F6.rank_below_cap` (WP-IR-04) | SOURCE_VERIFIED |
| The `trade.closed` evidence event labels the result from gross P&L while the stored economic result is net (`trade_tracker/main.py:405-418 @ bb7825f`; CON-09) | CONTRADICTORY |
| The setup key in `shared/signal_identity.py` is anchored on `APP_VERSION`, which does not identify implementations (R3.d; G2-02) | INFERRED |
