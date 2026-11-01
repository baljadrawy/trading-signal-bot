# WP2 Activation Plan (2026-11-01)

> **Status: documentation and design only.** This file plans how the default-off WP2 features of branch `feature/wp2-foundation-20261101` could be activated, one bounded change at a time. It executes nothing, approves nothing and chooses no parameter. **The owner's progressive-activation directive of 2026-11-01 sets the order and the cycle; it is not a Class B approval** for any build, Compose install, recreate or database read named below (section 6). Every step still needs the owner's approval of that specific operation on that specific service (COPS:L92-93; WID:L18). Merged, Deployed and Runtime-Validated are NO for every feature here ([WP2_ENGINEERING_FOUNDATION_STATUS.md](WP2_ENGINEERING_FOUNDATION_STATUS.md) section 7.4). Activating a feature is never evidence of profitability (`CH:L46`).

## Document control

| Field | Value |
|---|---|
| This file | `docs/design/remediation-design-pack-20261101/WP2_ACTIVATION_PLAN.md`; change class Documentation/design |
| Baseline | branch `feature/wp2-foundation-20261101` at `c82558b`, which merges `main` `e0c9395` (PR #98) into the branch. Against `6ae70a2` it adds only the functional-activation decision and its CLAUDE.md entry (`git diff --stat 6ae70a2 c82558b`: 2 files). Code citations are `path:Lx @ 6ae70a2` unless another commit is named; service files being edited in the working tree by other WP2 tasks are not cited |
| Governing decision | [WP2_FUNCTIONAL_INCREMENTAL_PAPER_ACTIVATION_2026-11-01.md](../../governance/WP2_FUNCTIONAL_INCREMENTAL_PAPER_ACTIVATION_2026-11-01.md) (alias FIPA), APPROVED as the method; it grants no blanket authorization to deploy, restart or change shared PostgreSQL (FIPA:L3, L20) |
| Directive | owner, 2026-11-01, progressive activation: Implement, Test, Review risks, Activate ONE bounded change, Observe, Validate, Continue (DOCUMENTED_ONLY, relayed in this session). Where an earlier relayed phase order differed, the committed FIPA order governs (main agent's instruction in this session); this plan follows FIPA:L8-13 |
| Runtime facts | relayed from the main agent's read-only Class A inspection of 2026-11-01, with the environment filtered to an allow-list (RUNTIME_VERIFIED by that observation; this writer ran no host command). Section 1 |
| Review state | owner review PENDING; independent review PENDING. A review in the session that wrote this file is not independent ([WP2_INDEPENDENT_REVIEW_HANDOFF.md](WP2_INDEPENDENT_REVIEW_HANDOFF.md)) |
| Companions | [COMPOSE_OPERATIONS.md](../../ops/COMPOSE_OPERATIONS.md); [PAPER_ADMISSION_CHANGE_RUNBOOK.md](../../ops/PAPER_ADMISSION_CHANGE_RUNBOOK.md) (DRAFT, not authorized for use); [VERSION_BOUNDARY_TEMPLATE.md](../../../deploy/VERSION_BOUNDARY_TEMPLATE.md); [VERSION_BOUNDARY.md](../../../deploy/VERSION_BOUNDARY.md); [DEPLOYED.json](../../../deploy/DEPLOYED.json); [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md); [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) |

### Anti-drift statement (charter §7)

1. **Goal alignment.** The first increment makes every drop in the signal engine's F2 to F6 stages visible; it adds no signal, forces no trade and changes no decision. Discovery stays daily, and an empty cycle stays a valid outcome (`CH:L8`, `CH:L10`).
2. **Branch, SHA, runtime identity.** As in document control. None of the running images contains this branch's code (section 1).
3. **Scope.** Activation planning for the integrated WP2 flags (R1, R3, R4, R6, R7). Excluded: running anything, choosing a version label, retention period, observation length or any parameter.
4. **Evidence class.** Each material claim carries its class; code facts are SOURCE_VERIFIED at `6ae70a2`; sizes measured on synthetic fixtures are labelled as such.
5. **Permission class.** This file is documentation. Each step it describes is a Production/runtime change, and a later phase may also be a Strategy-version-changing correction. No class implies another (`CH:L65`).
6. **Acceptance and rollback.** Acceptance of this file: clean self-check, owner review and independent review. Rollback: revert its commit.
7. **DEVIATION ALERT.** None raised. Section 7 lists gaps and prerequisite mismatches; none conflicts with the charter.

### Source aliases

| Alias | Path @ commit |
|---|---|
| CH, DFP | `docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md`, `docs/governance/DEVELOPMENT_FIRST_POLICY.md`, both `@ 46578aa` |
| WID | `docs/governance/WP2_INTEGRATED_DEVELOPMENT_DECISION_2026-11-01.md @ f0c560d` |
| FIPA | `docs/governance/WP2_FUNCTIONAL_INCREMENTAL_PAPER_ACTIVATION_2026-11-01.md @ e0c9395` |
| COPS | `docs/ops/COMPOSE_OPERATIONS.md @ 46578aa` (unchanged at `6ae70a2`) |
| DEP | `deploy/DEPLOYED.json @ 46578aa` (unchanged at `6ae70a2`) |
| DC | `docker-compose.yml @ 46578aa`, blob `d1a4b197`, the blob DEP records for production (DEP:L4) |
| VB, VBT | `deploy/VERSION_BOUNDARY.md @ 46578aa`; `deploy/VERSION_BOUNDARY_TEMPLATE.md @ 9c0aecc` |
| PACR | `docs/ops/PAPER_ADMISSION_CHANGE_RUNBOOK.md @ 9588f45` |
| WFS | [WP2_ENGINEERING_FOUNDATION_STATUS.md](WP2_ENGINEERING_FOUNDATION_STATUS.md) `@ 6ae70a2` |
| DGT, WPL | [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) and [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) `@ 6ae70a2` |
| SEM, TT, TG | `signal_engine/main.py`, `trade_tracker/main.py`, `telegram/main.py @ 6ae70a2` |
| FRT, PIM | `tests/test_funnel_records.py @ 6ae70a2`; `deploy/paper-observe-bb7825f/IMAGES.md @ 46578aa` (the overlay-build precedent) |
| ADM, FH, FF, AF | `shared/admission_capacity.py`, `shared/funnel_hooks.py`, `shared/funnel_flags.py`, `shared/accounting_flags.py @ 6ae70a2` |
| EV2, CFG | `shared/evidence_v2.py`, `shared/config.py @ 6ae70a2` |
| SID, SCS | `shared/strategy_identity.py`, `shared/strategy_config_snapshot.py @ 6ae70a2` |
| TTI | `tests/test_wp2_tracker_integration.py @ 6ae70a2` |

## 1. Runtime starting point

**Running services (RUNTIME_VERIFIED, main agent, Class A, 2026-11-01).**

| Service | Running image | Started | Evidence v2 | Source of the running code |
|---|---|---|---|---|
| scanner | `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z` (DEP:L202) | 2026-10-19 | no `EVIDENCE_V2_ENABLED`, no evidence-v2 mount (also DC:L37-66, SOURCE_VERIFIED) | assembled from older commits, 23 files traced (DEP, scanner provenance; DOCUMENTED_ONLY) |
| analyzer | `tsb-a561-analyzer:rel-ea8ae4f-r2` (DEP:L67) | 2026-10-19 | `true`, bind mount present | `ea8ae4f` |
| signal_engine | `tsb-a561-signal_engine:rel-ea8ae4f-r2` (DEP:L249) | 2026-10-19 | `true`, bind mount present | `ea8ae4f` |
| trade_tracker | `tsb-obs-trade_tracker:bb7825f-20261027-r2`, image `sha256:8e609ca84740…` (DEP:L327-356) | 2026-10-27 | `true`, bind mount present; `PAPER_ECONOMIC_HALT_MODE=observe` | `bb7825f` |
| telegram | `tsb-obs-telegram:bb7825f-20261027-r2`, image `sha256:d665388a9092…` (DEP:L273-302) | 2026-10-27 | `true`, bind mount present; `PAPER_ECONOMIC_HALT_MODE=observe` | `bb7825f` |

All services run with `LIVE_LEARNING_MODE=true`, `LEARNING_GATES_ENABLED=false`, `PAPER_TRADING=true`, `TIMEFRAMES` 15m,4h,1d and `APP_VERSION` `sb-2026.08`. PostgreSQL is the shared upstream image. The collector is unhealthy, which is unrelated to this plan. The current halt and pause state is NOT_VERIFIED here; every Class B pre-gate reads it from the database (COPS:L19-28).

**No running image contains this branch's code** (RUNTIME_VERIFIED, as above). Every activation in this plan therefore starts with a new release image built from a reviewed commit or a reviewed overlay (section 4.6). A flag set on a running image would be unknown to its code and would have no effect.

**Drift from the running code, per service (SOURCE_VERIFIED, `git merge-base` and `git diff --stat`).**
- `bb7825f` is an ancestor of `main` `46578aa`, with no difference in `shared/`, `trade_tracker/` or `telegram/`. A tracker or telegram image built from this branch differs from the running one **only by the WP2 commits**, which are parity-tested byte-identical at their defaults (WFS section 3, row `9bc6f2e`).
- An analyzer or signal_engine image would also carry `main`'s changes since `ea8ae4f`: `a4a7561` (T1-cap policy, default legacy), `758b94f`, `a593e5b`, `bb7825f` (economic observation and the price-fetch retry), `6b0f226` (telemetry rate limit), one line in the pinned `signal_engine/signal_logic.py` and 27 lines in `shared/strategy_math.py` (`git diff --stat ea8ae4f 46578aa`, 10 files, 441 insertions). That is not one bounded change.
- The scanner image is assembled, so its base source is not proven (DEP scanner `reproducibility`, DOCUMENTED_ONLY).

**Strategy identity.** The closure of SID declares the tracker file whole (`_f("trade_tracker/main.py", …)`, file scope, SID:L757) and the new capacity and cost modules as ACTIVE (SID:L786-815). Any image of this branch therefore moves `source_hash`, and `drift_check strategy` reports DRIFT on both families (WFS L119, L153; SOURCE_VERIFIED). The telemetry and shadow modules are OBSERVE_ONLY and hashed into `inactive_hash` only (SID:L817-829), and their switches are excluded from `config_hash` (SCS:L262-263).

## 2. Inventory of the default-off features

Every flag below is read from the environment, and an unknown value refuses at start-up (WFS L194-203; SOURCE_VERIFIED). None is set in DC, which is unchanged. "Boundary" follows the classification of VBT:L7-13 and the `drift_check` strategy mode (VBT:L15): a flag whose key is in `config_hash` (SCS:L265-280) or whose activation changes the closure is a strategy-version boundary when it flips; an OBSERVE_ONLY switch is not (SCS:L262-263). **Independently of any flag, the first image of this branch on a service is itself a boundary** (section 1, "Strategy identity").

The common rollback form, used in every row: set the flag back to its default in a reviewed DC change, install it as its own owner-authorized step with `config --hash` verification (COPS:L49-51), and recreate the one service with the canonical Class B form on the image named in the approved plan, with the same gates and captures (COPS:L100-103, L108-125). Where the image itself must go back, the prior image is the one the plan names. Rollback runs only if it was pre-approved in the plan; otherwise a needed rollback is a STOP (COPS:L121-122). A rollback that crosses a boundary is itself a new boundary entry; the forward entry is never rewritten (PACR:L177).

### 2.1 FUNNEL_RECORDING (WP-B01, R6.a, R6.c; telemetry)

| Item | Content |
|---|---|
| Services and image | scanner F0–F2, analyzer F4, signal_engine F2–F6, trade_tracker F7, telegram F7 delivery gate (WFS L35). Images today: those of section 1; each needs a release image of a reviewed commit |
| Runtime dependencies | `FUNNEL_RECORDING=on` plus `EVIDENCE_V2_ENABLED=true`; `on` without the store refuses to start (FF:L36-45). The store is the per-service evidence-v2 recorder: daily JSONL files behind an in-memory queue (EV2:L183-196, L268-330). No database table. The scanner has neither the flag nor the mount today (section 1) |
| Behavioural change | none in decisions or economics: OBSERVE_ONLY (SID:L818-822). Side effects with `on`: evidence events `funnel.rejection`, `funnel.rejection_series_closed`, `funnel.cycle` (FH:L34-37); on the tracker, a `wp2` block in the heartbeat metadata and a start-up warning that the flags are not at their legacy values (TT:L99-101, L146-147); on the signal engine, one extra read of the candidate query when the legacy cut can bind (`signal_engine/main.py:L187-191`) |
| Boundary | the flag flip: none (excluded from `config_hash`, SCS:L262-263; INFERRED from the rule). The release image that carries the code: yes (section 1) |
| Operational benefit | every drop at the instrumented stages becomes a record with a canonical reason code, and each cycle carries a conservation check, so a silent drop is detectable (OF-05; R6). On the tracker, the reason for an idle admission loop (capacity, pause, risk state, no price) becomes visible in the evidence store |
| Rollback | common form, flag `off`; the records already written stay as written (evidence is never deleted, DFP:L106) |
| Approval still required | WP-G19 (WPL:L797), with DG-34 retention, compaction, storage budget and read access (DGT:L210) and DG-67 for each release (DGT:L216); the Class B recreate per service; DFP:L104 where admission is touched (WPL:L797; PACR:L44). Reading counts of the records is a protected measurement, DG-33 and WP-G18 (DGT:L202; WPL:L796) |

### 2.2 LEDGER_SHADOW (WP-E02, R7.b; shadow)

| Item | Content |
|---|---|
| Services and image | trade_tracker only (TT:L1550-1552); image `tsb-obs-trade_tracker:bb7825f-20261027-r2` today |
| Runtime dependencies | `LEDGER_SHADOW=on` (AF:L14, L109); evidence v2 for the `ledger.reconciliation` events (TT:L486-488, L550), logs otherwise. No database table; persistence is WP-E03 and WP-E04 (WFS L62-63) |
| Behavioural change | none: after each close, reconciles ledger realized net with the net just booked; never a decision or a database write (WFS L61; TT:L478-481). Adds counters to the heartbeat `wp2` block (TT:L482-483) |
| Boundary | no (OBSERVE_ONLY, SID:L823-825; excluded from `config_hash`) |
| Operational benefit | an independent check that each booked close equals the ledger's realized net under `legacy_tracker_v1`; a mismatch is logged with its reason code (TT:L546-549) |
| Rollback | common form, flag `off` |
| Approval still required | DG-67 (shadow-ledger activation, PRC:L554 cited at DGT:L216); Class B recreate of trade_tracker. A persistent ledger is WP-G28 with DG-40 and DG-41 (WPL:L806; DGT:L134-135) |

### 2.3 POSITION_STATE_SHADOW (WP-D03, R4, R7; shadow)

| Item | Content |
|---|---|
| Services and image | trade_tracker only (TT:L1432-1433, L1548-1549) |
| Runtime dependencies | `POSITION_STATE_SHADOW=on` (AF:L15, L110); evidence v2 for `position_state.shadow` events (TT:L486-488, L501) |
| Behavioural change | none: validates target hits and closes against the pure state machine and records refusals. Known legacy differences (T1/T3 tranche merge, zero-size T1, three uncovered rules, the fill-time risk refusal) produce expected refusals (WFS L247). Enforce mode does not exist (AF:L27) |
| Boundary | no for the shadow (OBSERVE_ONLY, SID:L826-829). Any enforce use would be a boundary (WFS L203) |
| Operational benefit | lifecycle transitions that the target state machine would refuse become visible before any enforce design is decided |
| Rollback | common form, flag `off` |
| Approval still required | DG-67-type release approval for a shadow (DGT:L216); Class B recreate of trade_tracker |

### 2.4 PAPER_COST_LABEL_POLICY (WP-E07, R4.a, R4.e; economics)

| Item | Content |
|---|---|
| Services and image | trade_tracker (AF:L12, L18-22) |
| Runtime dependencies | `PAPER_COST_LABEL_POLICY=net_single_count_legacy_v1`; refuses a non-default cost basis (TTI:L569-576) |
| Behavioural change | changes the stored economic fields of new `trade_results` rows (fee once per leg on executed notional, stop slippage once); no decision changes and the risk-guard input stays on the legacy label (WFS L66, L200; TTI:L402-416) |
| Boundary | yes: the key is in `config_hash` (SCS:L274) |
| Operational benefit | booked net figures stop double-counting the flat round trip on partial exits (R4.a, R4.e), so later accounting reads are cleaner. Not a claim about results |
| Rollback | common form, label policy back to `net_after_modeled_cost_v1`; rows booked under the alternative keep their label and are never rewritten |
| Approval still required | WP-G07 (WPL:L785), DG-37 (DGT:L152), DG-68 (DGT:L155), DG-38 packaging (DGT:L153), an owner-declared window and a boundary entry |

### 2.5 PAPER_BREAK_EVEN_POLICY (R4.b, WP-G06 slice; exits)

| Item | Content |
|---|---|
| Services and image | trade_tracker; passes a derived round-trip cost into the unchanged pinned break-even formula (WFS L201; TT:L1356-1361) |
| Runtime dependencies | `PAPER_BREAK_EVEN_POLICY=single_count_legacy_v1`; same cost-basis refusal (TTI:L569-576) |
| Behavioural change | moves the post-T1 break-even stop, so exits change (AF:L23-24; TTI:L434) |
| Boundary | yes: strategy-version change, key in `config_hash` (SCS:L275) |
| Operational benefit | the break-even stop is computed from the declared single-count cost rather than the flat round trip (R4.b) |
| Rollback | common form; positions opened under the alternative keep their attribution |
| Approval still required | WP-G06 (WPL:L784), DG-37, DG-68, DG-38, window and boundary entry |

### 2.6 SELECTION_POLICY (WP-B05, R1.b–d; selection)

| Item | Content |
|---|---|
| Services and image | signal_engine (`shared/selection_policy.py:L1-30`); image `tsb-a561-signal_engine:rel-ea8ae4f-r2` today, which carries none of `main`'s changes since `ea8ae4f` either (section 1) |
| Runtime dependencies | `SELECTION_POLICY=rank_then_limit_v1` plus owner-declared `SELECTION_VERSION` and `SELECTION_SCORE_KEY`; it refuses to start without them (`shared/selection_policy.py:L14-20`) |
| Behavioural change | which fresh rows reach the selector when there are more than `SELECTION_LIMIT` (200): ranked by the declared score instead of the alphabetical tail (R1). With at most 200 fresh rows both policies hand over the same set (`shared/selection_policy.py:L22-24`) |
| Boundary | yes: `SELECTION_POLICY`, `SELECTION_VERSION` and `SELECTION_SCORE_KEY` are `config_hash` keys (SCS:L269-273) |
| Operational benefit | the cut stops depending on symbol names; with funnel recording on, every row below the cut is recorded with its rank |
| Rollback | common form, `legacy` |
| Approval still required | WP-G01 (WPL:L779), DG-29, DG-30, DG-31 (DGT:L130-131, L150), DG-68, DG-38; a signal_engine release (DG-67) |

### 2.7 SIGNAL_INTEGRITY_MODE (A44, pre-existing; R3)

| Item | Content |
|---|---|
| Services and image | analyzer, signal_engine and trade_tracker read it (`integrity_mode(` in those files; `shared/signal_identity.py:L25-33`); already present in the running images (A44 predates `ea8ae4f`; INFERRED from the deployed tracker code calling it, TT:L104) |
| Runtime dependencies | `SIGNAL_INTEGRITY_MODE=enforce` (CFG:L120); off at runtime (VER-02 cited at WFS L117) |
| Behavioural change | enforce-mode identity, freshness refusal at admission and the A44 integrity path (DORMANT regions, SID:L739-744, L759-760) |
| Boundary | yes: key in `config_hash` (SCS:L276) |
| Operational benefit | same-bar re-fires and stale setups are refused by identity (R3) |
| Rollback | common form, `off` |
| Approval still required | the split of WP-C01 (EB-0 to EB-4), WP-G05 and WP-G12 (WPL:L783, L790), DG-27 (DGT:L128), DG-68, DG-38. The `setup_key` part is on HOLD (DG-35, DGT:L133) |

### 2.8 T1_CAP_POLICY (W3, `a4a7561` on `main`; R2)

| Item | Content |
|---|---|
| Services and image | analyzer (`shared/t1_cap.py:L1-17 @ 6ae70a2`); `a4a7561` is not in `ea8ae4f` (`git merge-base`), so the running analyzer does not contain the switch (SOURCE_VERIFIED) |
| Runtime dependencies | `T1_CAP_POLICY=independent_swing_v1` (CFG:L124) |
| Behavioural change | T1 geometry of momentum and reversion setups (`shared/t1_cap.py:L10-17`) |
| Boundary | yes: key in `config_hash` (SCS:L277) |
| Operational benefit | T1 is no longer capped by the decision bar's own wick (W3) |
| Rollback | common form, `legacy_window_v1` |
| Approval still required | the analyzer release at the legacy default is WP-G04 (WPL:L782; DG-67); activation is WP-G03 with DG-36 (DGT:L151), DG-68, DG-38. Not placed in the directive's order; the owner places it |

### 2.9 EVIDENCE_V2_ENABLED on the scanner

The four other services already run it (section 1). On the scanner it is absent, and DC gives the scanner no evidence-v2 volume (DC:L37-66). Turning it on is a DC change (environment and a bind mount) plus a scanner release, which is WP-G10 (WPL:L788; DG-67). It is a precondition for scanner funnel recording, not a separate phase here.

**Not in this plan.** `LEARNING_GATES_ENABLED` and the learner need their own authorization (COPS:L30-32). `RISK_PRICE_FETCH_RETRIES` (default 0) is already in the running tracker image (`bb7825f`) and is not a WP2 feature. The capacity authority in legacy mode and the `legacy_tracker_v1` cost binding are not flags: they ship in the first tracker release (increment TR-1, section 5.3) and are parity-tested byte-identical (WFS L56, L67).

## 3. Phase order and the increment cycle

**Order.** This plan follows the functional order of FIPA:L8-13. That decision was committed on `main` at `e0c9395` and governs where earlier relayed instructions differed. The order is:
1. discovery and signal generation (scanner, analyzer, signal engine), with R1 selection, R2 diagnosis, funnel observability, eligibility, macro context and closed candles;
2. signal integrity and delivery;
3. trade tracking and execution economics;
4. portfolio and risk;
5. evaluation.

Within a phase, telemetry and behaviour-changing selection are gated separately (FIPA:L9).

**Cycle.** Each increment runs the owner's cycle: Implement, Test, Review risks, Activate ONE bounded change, Observe, Validate, Continue. FIPA:L15-22 states it in detail:
- capture the baseline identity;
- take an independent review before activation;
- prepare the services, blast radius, boundary, flag values, metrics, success and failure criteria and rollback;
- obtain a specific owner authorization of the Class B operation;
- change one service at a time;
- observe, then accept, fix or roll back.

An increment is complete only when its own acceptance criteria hold. If no real Paper event occurs in the observation window, the increment reports **insufficient runtime evidence**, not success (FIPA:L29). The increment labels below (SE-1, SE-2, …) are local to this plan; they are not STRATEGY_AND_EXECUTION_CONTRACT.md items.

| Phase (FIPA) | Increments, in order | Services | Boundary at the flag flip |
|---|---|---|---|
| 1 Discovery and signal generation | **SE-1** `FUNNEL_RECORDING` on the signal engine (SE-1a overlay at the defaults, SE-1b recording on); **SE-2** analyzer funnel; **SE-3** R1.c selection; **SE-4** scanner store and funnel; **SE-5** R2 / W3 (`T1_CAP_POLICY`) | signal_engine, analyzer, scanner | SE-1, SE-2, SE-4: no (their images: yes); SE-3, SE-5: yes |
| 2 Integrity and delivery | **IN-1** `SIGNAL_INTEGRITY_MODE`, split per WP-C01; the `setup_key` part stays on HOLD | analyzer, signal_engine, trade_tracker | yes |
| 3 Tracking and economics | **TR-1** tracker release at the defaults; **TR-2** tracker F7 recording; **TR-3** `POSITION_STATE_SHADOW`; **TG-1** telegram release and F7 delivery records; **TR-4** `PAPER_COST_LABEL_POLICY`; **TR-5** `PAPER_BREAK_EVEN_POLICY` | trade_tracker, telegram | TR-2, TR-3, TG-1: no (the images: yes); TR-4, TR-5: yes |
| 4 Portfolio and risk | **PF-1** `LEDGER_SHADOW`; **PF-2** persistent ledger; **PF-3** target-mode capacity, ledger risk inputs, sizing | trade_tracker, telegram | PF-1: no; PF-2, PF-3: yes |
| 5 Evaluation | version-separated monitoring of operational and net economic performance | none new | not applicable |

Section 4 gives SE-1 in full. Section 5 gives the acceptance criteria and rollback of every later increment.

## 4. Phase 1, first increment SE-1: FUNNEL_RECORDING on the signal engine

### 4.1 Design: a minimal overlay of the running image

SE-1 is built as a **minimal overlay**. It starts from the contents of the running `tsb-a561-signal_engine:rel-ea8ae4f-r2` and replaces or adds exactly six files from the reviewed branch commit:
- `signal_engine/main.py`;
- `shared/funnel_flags.py`;
- `shared/funnel_hooks.py`;
- `shared/funnel_records.py`;
- `shared/funnel_recorder.py`;
- `shared/selection_policy.py`.

It is **not** rebuilt from `main`, so the `ea8ae4f..main` drift of section 1 is not carried. The evidence for this design:
- **Only WP2 changes in the service file.** `signal_engine/main.py` differs from `ea8ae4f` by the WP2 commit only: 57 insertions and 7 deletions, all for the funnel tap and the selection switch (`git diff ea8ae4f 6ae70a2 -- signal_engine/main.py`; SOURCE_VERIFIED). `main` did not change that file.
- **Import closure.** The four funnel modules import only `shared.evidence_v2`, `shared.config` and each other, besides the standard library. `shared/selection_policy.py` imports only the standard library (import lines of each file @ `6ae70a2`; SOURCE_VERIFIED).
- **Tests on the overlay tree.** The main agent reports that the overlay tree imports cleanly with `ea8ae4f`'s configuration, and that the `ea8ae4f` test suite gives 1064 passed and 847 skipped on both the pristine `ea8ae4f` tree and the overlay tree. These were local runs relayed in this session and were not repeated by this writer (SOURCE_VERIFIED as relayed).
- **Precedent.** The method follows the precedent of 2026-10-27, an overlay `FROM` the running release image, verified by image ID first. That precedent copied from a clean `git archive`, kept the running owners and file modes, and was built with `--network none --pull=false`, so the dependency set stayed the base image's (PIM:L30-33).

**What the overlay is not.** It is not a canonical Dockerfile build, and the tree it produces never existed as one commit. It has three consequences:
- **Provenance** is a composite: `ea8ae4f`, plus six files at the reviewed commit. It has to be recorded file by file, with the blob of each file (section 4.6, O1).
- **Strategy identity.** The ACTIVE closure (SID:L705-716) includes `signal_engine/main.py` as a whole file and `shared/selection_policy.py`, so the overlay moves `source_hash` and is a boundary even at the defaults (section 1, "Strategy identity").
- **Build preflight.** The canonical-build preflight requires an immutable `FROM` digest and a committed lock (`ops/provenance/build_preflight.py:L14-35 @ 6ae70a2`). An overlay build is expected to fail that check. The running images rely on the legacy transition exception recorded in DEP (signal_engine `reproducibility`). Whether that exception covers SE-1 is an owner ruling (AR-3). WP-A06 is extending this preflight now (section 8).

### 4.2 Steps

| Step | Change | Expected behaviour | Observe and validate |
|---|---|---|---|
| **SE-1a** | the overlay image, with `FUNNEL_RECORDING` and `SELECTION_POLICY` both absent, which means `off` and `legacy` (FF:L29; `shared/selection_policy.py:L6-8`). DC changes only in the signal_engine `image:` line (DC:L108) | **Decisions identical.** The legacy candidate query is byte-for-byte unchanged (SEM:L166-176), and nothing in the funnel or selection modules runs on that path. **New start-up refusals:** an unknown `FUNNEL_RECORDING`, `SELECTION_POLICY`, or a non-legacy policy without its declarations refuses to start (SEM:L109-113) | V1–V7 |
| **SE-1b** | `FUNNEL_RECORDING: "on"` in the signal_engine environment, on the SE-1a image; evidence v2 is already on there (section 1) | **Decisions identical** (section 4.5). **New effects:** funnel events (section 4.4); a `funnel` key in the heartbeat metadata (SEM:L277, L305); the instance's ranking-key method is wrapped, returning the key unchanged (FH:L652-667); and one extra database read when the cut can bind (section 4.3) | V1–V10 |

**Combining SE-1a and SE-1b.** The owner may combine the two steps into one DC change and one recreate. That saves one Class B operation. It has these costs:
- an anomaly can no longer be attributed to the new code or to the recording;
- the at-default baseline of SE-1a is never observed;
- a rollback has to return to the running image, not to SE-1a.

The plan recommends two steps. Combining is an owner choice; it is not recommended.

### 4.3 Disclosed runtime effect: the extra read on the shared PostgreSQL

| Item | From code (SOURCE_VERIFIED at `6ae70a2` unless marked) |
|---|---|
| Query | `_FUNNEL_LEGACY_ORDER_SQL` (SEM:L37-40) reads `symbol`, `timeframe` and two JSON fields (`trade_type`, `pit.candle_close_time_ms`) from `analysis_results`. It uses the candidate query's WHERE clause (SEM:L29-32: not yet generated, analysed in the last 30 minutes, no open trade on the symbol) and its order (`symbol`, then `total_score` descending). It has **no LIMIT**, so it returns every eligible row |
| When | only with `FUNNEL_RECORDING=on`, the legacy policy, a cycle that has results, and a candidate query that returned `SELECTION_LIMIT` = 200 rows, that is, when the cut can bind (FH:L692-701; SEM:L187-191, L28). Below 200 rows the tap only counts and reads nothing |
| How often | at most once per cycle with results. The loop sleeps 60 s after such a cycle (SEM:L279, L308) and 30 s after an idle one, which has no funnel cycle (SEM:L195-203). So it runs at most 1440 times a day (INFERRED upper bound). How often the cut binds at runtime is NOT_VERIFIED: it would need a count, which is a protected measurement (DG-33) |
| Context | the deployed code already runs two read-only queries in exactly the same situation when evidence v2 is on: a `count(*)` and an `OFFSET 200 LIMIT 500` read of the same WHERE clause (SEM:L55-62; present in `ea8ae4f` as `_v2_truncation`). SE-1b adds a third read of the same rows. All three run on the signal engine's existing connection |
| Failure | an exception in the read is caught. The cycle is marked `legacy_cut_read_failed` and the decision proceeds (FH:L719-720). The read is awaited before the decision step, so a slow read delays that cycle's decision by its duration (INFERRED). No statement timeout specific to this read exists in the code; a pool-level timeout is NOT_VERIFIED |
| Existing guards | the below-limit short-circuit (FH:L697-701); `FUNNEL_RECORDING=off` (the parity test asserts that `off` never issues the read, FRT:L534); the try/except |
| Guard options (development; not chosen) | (a) reuse the rows `_v2_truncation` already reads (at most 500 beyond the cut), so there is no third read; rows beyond 700 would then be an annotated, incomplete cut. (b) Cap the read with a LIMIT; the cap value is an owner parameter. (c) Keep the read as written and disclosed. Options (a) and (b) change `signal_engine/main.py` or `shared/funnel_hooks.py`, so the six-file set would need a new review and the parity tests a re-run (AR-4) |

### 4.4 Storage growth and latency (from code; no database row or evidence file was counted)

**What one cycle emits with SE-1b on** (SOURCE_VERIFIED):
- **Envelope.** One `funnel.cycle` envelope per cycle that has results. The tap opens only when results exist (SEM:L187-188) and closes at the end of the cycle or on an error (SEM:L272-277, L301-305, L312; FH:L839-850).
- **Records.** One `funnel.rejection` record per dropped symbol at F3 to F5, at symbol scope, and one `F6.rank_below_cap` per eligible loser (FH:L774-833). On a macro veto, one cycle-scope F3 record replaces the per-symbol records (FH:L780-790). When the cut binds, one `F6.legacy_alphabetical_cut` record is added for each row beyond 200 (FH:L703-713).
- **Bound per cycle.** At most S + C records, where S is the number of distinct symbols among the at most 200 rows and C is the number of rows beyond the cut (INFERRED from the code above).
- **No compaction, and repeats.** `SignalEngineTap` builds `FunnelService("signal_engine")` with no compact stages (FH:L652-653). An evaluated row keeps `signal_generated=false`, because the evaluation only sets `processing_status` (SEM:L219-226). So it is read and recorded again on every cycle until it leaves the 30-minute window, which is up to 30 cycles at the 60 s sleep (INFERRED).

**Bytes per event.** These sizes were measured by this writer on the repository's synthetic signal-engine fixtures (FRT `engine_scenario`, seeds 0 to 24, through `run_engine`), with each JSON Lines record exactly as the recorder serializes it (EV2:L300-313), plus a newline. The fixture identity fields have the real width. This is a local synthetic run; real lines may be somewhat longer or shorter (INFERRED).

| Event | Lines measured | Bytes per line, synthetic |
|---|---|---|
| `funnel.cycle` | 23 | 1439–1862 (mean 1704) |
| `funnel.rejection` | 1059 | 1412–1585 (mean 1488) |

**Bound per day** (INFERRED arithmetic, not a forecast):
- cycles with results: at most 1440 per day;
- bytes per day: at most 1440 × (1862 + (S + C) × 1585);
- illustration, S + C = 50: about 117 MB per day;
- the ceiling, S = 200 with no cut: about 459 MB per day.

The runtime S and C are NOT_VERIFIED, because measuring them is a count (DG-33). Retention on disk is not bounded by the code. The sink appends one file per service and UTC day (EV2:L183-196), and nothing deletes them. The retention period, compaction and storage budget are DG-34 (DGT:L210). The state-change compaction that the scanner uses (FH:L179-213) would cut the repeats, but enabling it for the signal engine's stages is a code change (AR-4). Free disk space on the host is NOT_VERIFIED.

**Latency.** Each emit runs on the event loop and does three things (EV2:L268-330):
- serializes one record of about 1.5 KB to canonical JSON (EV2:L313);
- takes a lock and appends the line to an in-memory deque (EV2:L319);
- on a full queue, drops the event and counts it, without blocking or raising (EV2:L297, L316).

There is no file I/O on the loop. The flusher writes batches through `asyncio.to_thread` (EV2:L411, L429), every 2 s in batches of 500, with a queue of at most 10000 (CFG:L68-70). The recorder measures its own emit latency as `emit_latency_ms_p50`, `p95` and `p99` (EV2:L457-475). The funnel events share the queue with the signal engine's existing P1 events. At (S + C + 1) events per cycle of at least 60 s, against a 2 s flush, the queue fills only if the flusher stalls (INFERRED). A stall would show as `queue_depth` and `dropped` in the heartbeat (SEM `_with_ev2`; EV2:L477-482). The extra read of section 4.3 adds one database round trip to a binding cycle.

### 4.5 Failure isolation: what the tests prove and what they do not

| Claim | Evidence (SOURCE_VERIFIED at `6ae70a2`) |
|---|---|
| Off and on give the same database trace (excluding the disclosed extra read), the same saved signals and the same heartbeat health apart from the `funnel` key. Off issues no extra read and no funnel event | FRT:L526-565, `test_signal_engine_decisions_identical_off_and_on_and_conserved`, 25 seeds |
| A store whose emit raises, a failing publish and a failing record each leave the trace and the saved signals unchanged, and the failures are counted | FRT:L567-585, `test_broken_store_or_recorder_never_changes_decisions` |
| Off equals the pre-change tree | FRT:L632-634, `test_signal_engine_off_equals_pre_change_tree`, 25 seeds; opt-in through `WP2_BEFORE_TREE` (WFS L217: 150 passed with the selection tests) |
| An unknown flag refuses before any I/O | FRT:L43-44, `test_unknown_flag_refuses_before_any_io` |
| The recorder never raises; a broken writer leaves decisions unchanged | `tests/test_wp2_funnel_observability.py:L517-549` |
| `ea8ae4f` behaviour on the overlay tree | the main agent's relayed run: the `ea8ae4f` suite, 1064 passed and 847 skipped on both trees (section 4.1) |
| The funnel parity tests above **on the overlay tree** | run by the main agent on the `95bc28c` overlay tree: the `ea8ae4f` suite gives 1064 passed / 847 skipped on both the pristine and the overlay tree; the signal-engine funnel and selection tests (including before-tree parity against `ea8ae4f`) pass on the host and inside the deployed image `sha256:c5be4e34…` (76 passed; one harness-only failure: a child process loses the mounted pytest path). Must be re-run on the rebuilt release commit after the AP-09 volume fix |

**Expected integration failures.** The labels `open_trade_exists` and the learned-gate labels have no taxonomy-v1 mapping. With recording on they mark the cycle invalid (WFS L244; FRT:L542 allows exactly `legacy_label_unmapped:open_trade_exists` on the synthetic cases). This is a recording gap, not a decision effect. The acceptance criteria tolerate only these documented kinds.

### 4.6 Exact operations and their gates

Nothing below is authorized by this file or by FIPA (FIPA:L20). Each operation is one owner request in section 6.

| # | Operation | Rules it follows |
|---|---|---|
| **O1** | **Build the overlay image.** Build in an isolated clone or a clean export, never in the production checkout. That is Class C: the production checkout per COMPOSE_OPERATIONS.md is dirty, and a build there overwrites rollback tags (COPS:L147-149, L167). The base is the running image, verified by its image ID (`sha256:c5be4e34c064…`, DEP signal_engine `observed`). Copy exactly the six files of section 4.1 from a `git archive` of the reviewed commit, keeping the running owners and modes, with `--network none --pull=false` (PIM:L30-33). Give the image a new, unique tag; no existing tag is rebuilt, retagged, pulled or overwritten (COPS:L47-48). Record the WP-A06 / R1.4-B preflight result as it stands, with the refusal expected for an overlay (section 4.1). Record the image ID, the six paths with their blob hashes and the base image ID, and verify the content with `ops/provenance/runtime_manifest.py`, as the precedent did (PIM:L35-40) | WID:L18; COPS:L40-48, L147-149, L167 |
| **O2** | **Compose changes through review.** SE-1a changes the signal_engine `image:` line (DC:L108), with its rollback comment. SE-1b adds `FUNNEL_RECORDING: "on"` to the environment block (DC:L115-123), with a rollback comment. Each change goes through a PR. Integration into `main` is the reviewer's and owner's step, never Claude's push. Installing the merged file in production is its own owner-authorized step, with offline `config --hash` verification (COPS:L49-51). A full render is never printed (COPS:L80-88) | COPS:L49-51, L80-88 |
| **O3** | **Class B recreate of signal_engine only**, from the production checkout per COMPOSE_OPERATIONS.md, in the one canonical form (COPS:L103): `docker compose -p trading-signal-bot -f docker-compose.yml up -d --no-deps --no-build --pull never --force-recreate signal_engine`. **Before:** capture the identity of the target and of every other bot container into a mode-700 evidence folder (container ID, image ID and reference, `StartedAt`, `RestartCount`, network addresses, config-hash label). Then the pre-gates: the PAPER_HALTED/B3 and pause state read from the database by an approved read, never from a document; the learner stopped; the D3 check of COPS:L113-114 as written (its service list is NOT_VERIFIED here); the rendered config hash equal to the expected one; the approved image. Run exactly one command. **After:** the expected image and config hash with a new container ID; every other container unchanged in every captured field; `healthy` on two consecutive fresh reads; a log review; the halt and pause state and the learner verified again (COPS:L108-122) | COPS:L19-28, L29, L92-125 |
| **O4** | **Version-boundary record.** `drift_check strategy` reports DRIFT for the overlay (section 4.1), so an entry from VBT is written right after the activating step. Its fields are set as follows. **Entry and version:** `entry_kind` `strategy_boundary`; `version_before` and `version_after` are the owner's labels. **Golden replay:** a PATCH or MINOR label needs a byte-identical golden replay, otherwise the step is MAJOR (VBT:L9). Whether the parity tests of section 4.5 serve as that replay is an owner ruling (AR-5). **Source commit:** the composite of section 4.1, `ea8ae4f` plus six files at the reviewed commit. **Images:** the new image ID; `rollback_images` is the running image. **PENDING fields** are filled by amendment, never by rewriting (VBT:L49). A hash that changes under the same label is a STOP (VBT:L11). SE-1b needs no new entry, because the flag is excluded from `config_hash` (SCS:L262-263). Its activation minute is still recorded as an amendment, for version-separated evidence (INFERRED from FIPA:L21, L27) | VBT:L7-49; VB:L3-5 |
| **O5** | **Validation reads** (section 4.7). The heartbeat metadata is read from the database; evidence-v2 recorder statistics are read from the service's evidence directory. Both are reads that need owner approval (DFP:L106), limited to the named health fields. No outcome, trade count or record count is read (DG-33) | DFP:L106; DGT:L202, L210 |
| **O6** | **Rollback** (section 4.8), pre-approved as part of the plan, or else a STOP | COPS:L121-125 |

### 4.7 Validation and acceptance

| Check | SE-1a | SE-1b | Source |
|---|---|---|---|
| V1 identity | the new image ID and the expected config hash; a new container ID | the same image as SE-1a; the new config hash | COPS:L117-118 |
| V2 other containers | unchanged in every captured field | as SE-1a | COPS:L118-119 |
| V3 health | two consecutive fresh `healthy` reads | as SE-1a | COPS:L119 |
| V4 logs | no start-up refusal; no `SELECTION_POLICY` warning, which appears only when the policy is not legacy (SEM:L111-113); no new error lines | as SE-1a | COPS:L120; PIM:L45-47 |
| V5 settings in effect | `FUNNEL_RECORDING` and `SELECTION_POLICY` absent, `EVIDENCE_V2_ENABLED=true`, `PAPER_TRADING=true`, from a filtered environment view | `FUNNEL_RECORDING=on`; the rest unchanged | PACR:L163; COPS:L80-88 |
| V6 recorder health in the heartbeat `evidence_v2` block | `dropped`, `errors`, `hook_errors`, `flush_failures` do not rise; `last_flush_ok_at` stays fresh | as SE-1a | EV2:L477-482 |
| V7 safety state | halt and pause unchanged by the operation; learner stopped | as SE-1a | COPS:L120 |
| V8 funnel health in the heartbeat `funnel` block | key absent | `not_recorded` and `publish_failures` stay 0; invalid cycles only for the documented label gap (section 4.5). Record counts are not read (DG-33, DG-34) | SEM:L277, L305; FH:L159-160 |
| V9 emit latency | baseline `emit_latency_ms_p95` from the recorder statistics | p95 compared with the SE-1a baseline; no threshold is chosen here (owner) | EV2:L457-475 |
| V10 downstream | telegram and trade_tracker stay healthy, with no new error lines; signals still pass the existing `signal.ready` path | as SE-1a | COPS:L29; FIPA:L21 |

**Acceptance.** V1 to V10 hold over the owner-declared observation period. Its length is an owner decision, and none is chosen here. If no cycle with results occurs in the period, the result is **insufficient runtime evidence** (FIPA:L29). Behavioural identity of decisions is test evidence (section 4.5), never claimed from the runtime (FIPA:L29). The report gives Implemented, Integrated, Tested, Independently Reviewed, Merged, Deployed, Activated and Runtime-Validated as separate states (FIPA:L28).

**Rollback triggers.** Any failure of V1 to V7 is a STOP (section 4.9). Under SE-1b, the following are rollback triggers under the pre-approved plan:
- a rise in `dropped`, `errors` or `flush_failures`;
- a `not_recorded` or `publish_failures` above 0;
- an invalid cycle of an undocumented kind;
- a latency change the owner's plan names as unacceptable.

### 4.8 Rollback

- **From SE-1b.** Two routes, each one service at a time with the full gates (COPS:L29, L124-125):
  - `FUNNEL_RECORDING` back to off (remove the line, or set `"off"`), with a reviewed DC change, an install and a Class B recreate on the SE-1a image;
  - or directly back to the running image, as below.
- **From SE-1a.** The DC `image:` line goes back to `tsb-a561-signal_engine:rel-ea8ae4f-r2`, the image running today (DEP:L249), with the same install and recreate. That image is kept as it is; it is never rebuilt or retagged (COPS:L47-48).
- **Boundary.** A rollback across the SE-1a boundary is a new entry; the forward entry is never deleted or rewritten. Signals emitted under the overlay stay attributed to it (PACR:L177; VB:L3-5).
- **Records.** Funnel records already written stay; evidence is never deleted (DFP:L106).
- **Not part of a rollback.** A rollback clears no pause or halt and touches no trade or risk record (PACR:L178).

### 4.9 STOP rule

If anything is unexpected, STOP and return to the owner. Do not diagnose and continue, and do not improvise a workaround (COPS:L52-54). Keep the evidence (COPS:L121). It applies in particular to:
- a hash or image mismatch, or an unexpected diff;
- a change to any other container;
- a failing pre-gate, including a halt or pause state that differs from the plan;
- a secret in any output;
- a start-up refusal of the new image;
- a hash change under an unchanged version label (VBT:L11);
- a boundary entry that cannot be written;
- a needed rollback that was not pre-approved.

A STOP resumes only on a new owner decision (PACR:L191).

## 5. Later increments: acceptance criteria and rollback

Every increment below follows the cycle of section 3 and the operations O1 to O6 of section 4.6, adapted to its service. Each one also needs the identity, health, log, settings and safety checks V1 to V7. Only the specific criteria are listed. "Rollback" means the common form of section 2 unless stated otherwise. No criterion reads outcomes, trade counts or record counts, and no profitability claim follows from any of them (`CH:L46`).

### 5.1 Phase 1, discovery and signal generation (after SE-1)

| Increment | Content and dependencies | Acceptance criteria | Rollback | Approvals still required |
|---|---|---|---|---|
| **SE-2** analyzer funnel | F4 bar and data records (`analyzer/main.py`, `analyzer/technical_analyzer.py`, section 2.1). The branch's `technical_analyzer.py` also carries `a4a7561` (section 1). A minimal overlay therefore needs a WP2-only version of that file, which is NOT_VERIFIED to exist (gap AP-04) | analyzer writes identical with recording off and on (FRT:L351, 8 seeds; WFS L97); `funnel` health in the analyzer heartbeat with `not_recorded` 0; recorder health as V6 | analyzer back to `tsb-a561-analyzer:rel-ea8ae4f-r2`, flag off | WP-G19 slice, DG-34, DG-67 or WP-G04 (WPL:L782), Class B on analyzer, boundary entry |
| **SE-3** R1.c selection | `SELECTION_POLICY=rank_then_limit_v1` with owner-declared `SELECTION_VERSION` and `SELECTION_SCORE_KEY` (section 2.6); after SE-1 is accepted, so that F6 cut records show the effect | the start-up warning names the declared version (SEM:L111-113); every row below the cut has an `F6.rank_below_cap` record carrying the declared version; signals carry the new identity from the activation minute; no pooling across the boundary (VB:L3-5) | `legacy`, plus a boundary entry for the rollback | WP-G01 (WPL:L779); DG-29, DG-30, DG-31, DG-68, DG-38; window declaration |
| **SE-4** scanner store and funnel | `EVIDENCE_V2_ENABLED` and an evidence-v2 bind mount for the scanner in DC, then a scanner release (section 2.9), then F0 to F2 records with state-change compaction (FH:L35-37) | scanner decisions identical off and on (FRT:L185, 25 seeds); the store writes with recorder health as V6; compacted series as designed | flag off; scanner back to its running image | WP-G10 (WPL:L788), DG-67, DG-34, the DC change, Class B on scanner |
| **SE-5** R2 diagnosis and W3 | evidence-based diagnosis first. Then `T1_CAP_POLICY` (section 2.8) on an analyzer release that carries `a4a7561` at the default (WP-G04), then the switch itself (WP-G03) | after WP-G04: T1 geometry unchanged at `legacy_window_v1`; after WP-G03: new signals carry the declared version and T1 policy; stratified evidence only | `legacy_window_v1`, plus a boundary entry | WP-G04, WP-G03 (WPL:L781-782), DG-36, DG-68, DG-38; WP-D02 is in development (section 8) |

### 5.2 Phase 2, integrity and delivery

| Increment | Content and dependencies | Acceptance criteria | Rollback | Approvals still required |
|---|---|---|---|---|
| **IN-1** integrity | `SIGNAL_INTEGRITY_MODE=enforce` (section 2.7), split per the WP-C01 options EB-0 to EB-4. The `setup_key` composition stays on HOLD (DG-35), and pinned files stay unchanged (DG-71) | no same-bar re-fire under the new identity; freshness refusals recorded as F4 records (when SE-1 and SE-2 are active); the reliable `signal.ready` hand-off unchanged; boundary entry with the no-re-fire rule (VBT:L39-41) | `off`, plus a boundary entry | WP-G05, WP-G12 (WPL:L783, L790), DG-27, DG-28, DG-68, DG-38; DG-35 and DG-71 decisions where the split needs them |

### 5.3 Phase 3, trade tracking and execution economics

The tracker and telegram images of this branch differ from the running ones only by the WP2 commits (section 1). So their first release is one bounded change.

| Increment | Content and dependencies | Acceptance criteria | Rollback | Approvals still required |
|---|---|---|---|---|
| **TR-1** tracker release at the defaults | an image built from a reviewed commit (canonical or overlay, as for O1); DC `image:` line (DC:L149). New fail-closed start-up checks: an unknown flag, or an invalid cost configuration, refuses to start (TT:L86-95) | decisions and booked economics are test-identical: 160 risk, 120 admission and 200 exit-and-close cases against the pre-change sources (TTI:L155-189, L259-271, L388-399). No start-up warning about flags (TT:L99-101); no `wp2` heartbeat block (TT:L146-147) | back to `tsb-obs-trade_tracker:bb7825f-20261027-r2` (DEP:L356) | DG-67, Class B on trade_tracker, boundary entry (the tracker file is ACTIVE at file scope, SID:L757), and the DFP:L104 ruling (AR-6) |
| **TR-2** tracker F7 recording | `FUNNEL_RECORDING=on` on TR-1. Per pass of the admission loop (at least the 30 s code default, CFG:L134), it emits one `funnel.cycle` and one record per refused signal (ADM:L115-178). There is no compaction (ADM:L198-201), and a refused signal that is not made terminal is re-recorded every pass for up to its 2-hour window (TT:L834-843). Measured on the synthetic tracker fixtures by this writer: envelope 1288–1389 bytes, record 1455–1529 bytes. Upper bounds: about 4.0 MB per day for envelopes alone, and about 0.37 MB per persistently refused signal (INFERRED) | the TR-1 criteria still hold; recorder health as V6; funnel health not observable in the tracker heartbeat (gap AP-02) | flag off on TR-1 | WP-G19 slice (WPL:L797), DG-34, the DFP:L104 / PACR:L44 ruling (AR-6), Class B on trade_tracker; **precondition: gap AP-01 closed** |
| **TR-3** `POSITION_STATE_SHADOW` | section 2.3 | `shadow_errors` 0; refusals only of the documented legacy-difference kinds (WFS L247; TTI:L461-477) | flag off | DG-67-type shadow release; Class B on trade_tracker |
| **TG-1** telegram release and F7 delivery records | release at the defaults, then recording on; one cycle and one record per refused delivery (ADM:L181-195) | gate answers test-identical with recording on (TTI:L518-523); recorder health as V6 | back to `tsb-obs-telegram:bb7825f-20261027-r2` (DEP:L302), flag off | DG-67, WP-G19 slice, DG-34, Class B on telegram, boundary entry if `telegram/main.py`'s ACTIVE regions changed (SID:L746-752) |
| **TR-4** cost labels | section 2.4 | new rows carry `net_single_count_legacy_v1`; the risk-guard input unchanged (TTI:L402-416); existing rows never rewritten (FIPA:L11) | label back to legacy, plus a boundary entry | WP-G07, DG-37, DG-68, DG-38, window declaration |
| **TR-5** break-even stop | section 2.5 | only the post-T1 stop moves (TTI:L434); positions are attributed by version | legacy, plus a boundary entry | WP-G06, DG-37, DG-68, DG-38, window declaration |

### 5.4 Phase 4, portfolio and risk; Phase 5, evaluation

| Increment | Content and dependencies | Acceptance criteria | Rollback | Approvals still required |
|---|---|---|---|---|
| **PF-1** `LEDGER_SHADOW` | section 2.2, on the TR-1 image | `ledger_mismatches` 0, or every mismatch explained by a documented difference; `shadow_errors` 0; the realized-net compounding base is never fed by unrealized gains (WFS L21) | flag off | DG-67 shadow-ledger activation; Class B on trade_tracker |
| **PF-2** persistent ledger | a disposable-database migration and a shadow writer (WP-E03 in development, WP-E04) | migration idempotent and backward compatible on a disposable database, never on production (WPL:L574); the shadow writer changes no decision | writer off; the migration's own rollback | WP-G28 (WPL:L806), DG-40, DG-41, a migration approval |
| **PF-3** portfolio controls | target-mode capacity (WP-G23), ledger risk inputs (WP-G21), sizing (WP-G22), clusters and ladders (WP-G24 to WP-G26). Not built | per PR-T tests and the version contract; the version is fixed before any governed window (WPL:L800) | legacy mode, plus a boundary entry | WP3 → WP5 gates (WPL:L799-804); PR-OD decisions |
| **Evaluation** | monitoring by immutable version boundary (FIPA:L13) | no protected experiment and no holdout access; insufficient runtime evidence reported as such (FIPA:L29) | not applicable | WP3 decisions for any governed evaluation |

## 6. Approval sufficiency and the exact requests

**What is approved today.** These approvals exist:
- the integrated-development decision (WID), for source integration and isolated disposable development containers;
- FIPA, as the development and staged-activation **method**;
- DG-70, development-only;
- DG-69, for completion and review.

**None of them is a Class B authorization.** FIPA says so itself: approval of the method is not the authorization of a particular Class B shared-host operation (FIPA:L3, L20). WID says the same (WID:L18). The owner's progressive-activation directive is also a method instruction. It does not authorize the build, the Compose install, the recreate or any database read below. Each request is separate and covers one operation on one service.

**Prerequisites that are still open:** independent review PENDING for every WP2 commit ([WP2_INDEPENDENT_REVIEW_HANDOFF.md](WP2_INDEPENDENT_REVIEW_HANDOFF.md)); no merge or integration of the deployable commit; no release image built.

| Request | Exact content | Gate |
|---|---|---|
| **AR-1** independent review | review of the SE-1 deployable set: the six files at one named commit, the overlay recipe of O1, the parity evidence of section 4.5 and this plan's runtime effects (section 4.3) | FIPA:L19; DFP:L73 |
| **AR-2** merge or integration | the owner decides whether the six files must reach `main` before release, or whether a pushed, reviewed branch commit is enough. A merge never authorizes a deployment (PACR:L70). The DC PRs of O2 are integrated into `main` by the reviewer, as in the precedent (PIM:L16) | DFP:L41; PACR:L70 |
| **AR-3** release-image build | an isolated overlay build per O1, with its location (never the production checkout), base image ID, six files, unique tag and content verification. Also a ruling on whether the legacy transition exception covers an overlay that the build preflight refuses (section 4.1) | WID:L18; COPS:L147-149, L167; DG-67 |
| **AR-4** extra-read guard and compaction | before SE-1b: choose option (a), (b) or (c) of section 4.3, and say whether signal-engine records are compacted. Any code change goes back to AR-1 | DG-34; FIPA:L19 |
| **AR-5** version boundary | the before and after version labels; whether the parity tests of section 4.5 count as the byte-identical golden replay for a PATCH or MINOR label (VBT:L9), or the step is MAJOR; how the composite runtime identity is computed (AP-05); approval to write the entry of O4 | DG-68, DG-69; VBT:L7-13 |
| **AR-6** admission ruling (Phase 3) | whether recording in the admission authority is an admission change under DFP:L104 and PACR:L44, given that the tests show no admission change; if it is, the runbook needs owner and independent review first (PACR:L3) | DFP:L104; WPL:L797 |
| **AR-7** Compose install, SE-1a | install of the merged DC blob that changes only the signal_engine `image:` line, with offline `config --hash` verification | COPS:L49-51 |
| **AR-8** Class B recreate, SE-1a | one recreate of signal_engine per O3, with rollback to `tsb-a561-signal_engine:rel-ea8ae4f-r2` pre-approved | COPS:L92-125 |
| **AR-9** database and evidence reads | the halt and pause state read for every pre-gate; heartbeat `evidence_v2` and `funnel` health fields; the recorder statistics file. Health fields only, no outcome or record count | COPS:L19-28; DFP:L106; DG-33 |
| **AR-10** observation values | the length of the observation period and any latency limit for V9; both are owner values, and none is chosen here | FIPA:L19 |
| **AR-11** SE-1b | the ruling that SE-1b is a signal-engine slice of WP-G19 although not all of its prerequisites are complete (AP-06); DG-34 retention, compaction, storage budget and read access; the DC change and its install; one Class B recreate of signal_engine | WPL:L797; DGT:L210; COPS:L92-125 |

## 7. Gaps found while writing this plan

These are engineering and governance gaps for the owners of the named files. This file changes none of them.

| ID | Gap | Affects | Proposed handling |
|---|---|---|---|
| AP-01 | No tracker-level broken-store test. The broken-store test covers the signal engine only (FRT:L567-585). The tracker's F7 path is protected by code-level guards (ADM:L108-178), not by a test | TR-2 | add a tracker test in which `evidence_v2.emit`, `FunnelService.publish` and `FunnelCycle.add` raise, with the admission database log byte-identical (pattern FRT:L567-585) |
| AP-02 | The tracker heartbeat carries no funnel health. The signal engine and the analyzer include `tap.health()` (SEM:L277, L305). The tracker's `wp2` block holds only flags and shadow counters (TT:L146-147) | TR-2 validation | add the funnel health fields to the tracker heartbeat, without record counts if DG-34 restricts them |
| AP-03 | Closed for `95bc28c` (see §4); re-run required on the rebuilt release commit | SE-1 | re-run on the rebuilt overlay tree, on the host and inside the deployed image |
| AP-09 | Signal-engine funnel records are re-emitted every cycle for a fresh row (about 30 times) and the legacy-order shadow read has no LIMIT | SE-1b | fix in progress: record deduplication, per-cycle bound, bounded or zero-extra read; then rebuild the release commit |
| AP-04 | The branch's `analyzer/technical_analyzer.py` also carries `a4a7561`, so a minimal analyzer overlay needs a WP2-only version that is not on the branch | SE-2 | prepare and test that file, or take the analyzer release under WP-G04 instead |
| AP-05 | The closure spans every service, while each image ships its own `shared/`. `drift_check strategy` hashes one checkout (`ops/provenance/drift_check.py`, strategy mode). For a mixed deployment (`ea8ae4f`, `bb7825f`, an overlay) the before and after identity is not defined | every boundary entry | an owner rule under DG-69: per-service closure subsets, or one composed tree per deployment |
| AP-06 | WP-G19 lists WP-A05 and WP-B01 to WP-B04 as prerequisites (WPL:L797). WP-B02 is blocked by DG-71, WP-A05 and WP-B04 are partial (WFS L33, L38), and WP-B03 is not in the overlay | SE-1b | owner ruling (AR-11) |
| AP-07 | The funnel read has no LIMIT or statement timeout. Signal-engine records are not compacted, and a fresh row is re-recorded on about 30 cycles. On-disk retention is unbounded | SE-1b | AR-4 and DG-34 |
| AP-08 | No golden replay suite covers the signal-engine main loop or the tracker. The registered suites are the WP2 composite replay and the A44 integrity step (`tests/golden_replay.py:L4-10`) | the PATCH or MINOR route | AR-5, or a golden suite adapter for each service path |

## 8. In development (not yet in this plan)

These tasks are being built in parallel. Some already have commits on the branch after this file's baseline, for example `f028ebd` (WP-B03), `774b0b7` (WP-E03) and `c518eb0` (WP-A06). Their activation steps will be added here by the main agent. Until then, none of them is part of any increment above.

| Task | Topic | Relation to this plan |
|---|---|---|
| WP-A06 | build-provenance refusal in the preflight and the service Dockerfiles (R5.b) | gate of O1 and AR-3; it may change whether an overlay build is acceptable |
| WP-D02 | W3 invariants and options (R2.b) | SE-5 |
| WP-E06 | net-labelled counters (R7.f, R4.d) | Phase 3 |
| WP-B03 | `MarketSnapshot` adapter in shadow in the scanner (`MARKET_SNAPSHOT_SHADOW`) | SE-4; replaces the `snapshot_hash` placeholder (FH:L60) |
| WP-E03 | disposable-database migration for ledger persistence (R7.c) | PF-2 |
