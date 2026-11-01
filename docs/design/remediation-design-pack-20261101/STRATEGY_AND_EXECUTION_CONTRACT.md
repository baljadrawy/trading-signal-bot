# Strategy and Execution Contract

**Pack:** Consolidated Remediation & Design Pack (2026-11-01), WP1-B (strategy and signal architecture), WP1-C (economic and execution model) and WP1-E (evidence and reproducibility).
**Baseline:** `main` = `46578aa`. Code read at the documented-deployed commits `ea8ae4f` (analyzer, signal_engine, shared) and `bb7825f` (telegram, trade_tracker).
**Status:** Documentation/design only. Nothing here authorizes protected research, simulation, tuning, strategy activation, merging, deployment or real-money trading ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) authority note, L80 @ 46578aa).
**ID prefix:** `SE-`. Findings are SE-01 to SE-29, contract clauses SE-30 to SE-59, proposed changes SE-60 to SE-79, owner decisions SE-80 to SE-89.

## 0. Anti-drift statement (charter §7)

1. **Goal alignment.** The contract serves active daily opportunity discovery, net-of-cost spot long-only trading with strategy-specific holding, and compounding of realized net profits ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §1, L8). Discovery is not execution: the interface allows "no candidate" as a normal daily outcome, and no clause creates a trade quota.
2. **Branch and runtime identity confidence.** Source claims are SOURCE_VERIFIED at the named commits. Runtime claims are RUNTIME_VERIFIED only where the 2026-10-31 audit addendum says so (VER-xx). Running-image file content is NOT_VERIFIED (RT-17, VER-28; see SE-23).
3. **Scope.** WP1 design. R-items touched: R2 (W3 geometry), R3 (same-bar re-fire, identity part only), R4 (stop slippage accounting), R5 (provenance and lineage), R8 (hypothesis contracts and cost model). R1 and R6 (selection and funnel) belong to [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md); R7 (ledger, sizing, compounding) belongs to [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md); R9 is out of scope. The register itself is [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md).
4. **Evidence classes** follow charter §7.4: SOURCE_VERIFIED, RUNTIME_VERIFIED, DOCUMENTED_ONLY, HISTORICAL_REPORTED, INFERRED, NOT_VERIFIED, CONTRADICTORY.
5. **Permission class of this document:** Documentation/design. Each proposed change in §E5 carries exactly one change class; none implies another, and a default-off flag never authorizes activation ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §5 WP2, L51).
6. **Deliverables:** the interface contract (§B), the position state machine (§B6), the cost and fill model (§C), the evidence and reproducibility contract (§E), the change list with tests and acceptance criteria (§E5), and owner decisions (§F).
7. **DEVIATION ALERT.** None is raised for the charter itself. Two near-conflicts are recorded as reconciliation items, not deviations: the stress level of the Evidence Ladder (SE-19) and the absence of any generator for the freeze contract-hash field (SE-05).

No statement in this document is a profitability claim. Correcting W3, the stop-slippage double count or any other defect is an engineering correction and establishes nothing about net edge ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §4, L46; `shared/t1_cap.py:L13-16 @ 46578aa`).

## 1. Sources and citation keys

Unmerged material is cited as `path @ commit`. Long unmerged paths use these keys:

| Key | Path | Commit | On `main`? |
|---|---|---|---|
| REP | `docs/audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md` | `5d977f2` | no |
| VERA | `docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md` | `5d977f2` | no |
| ERG-RM | `docs/research/evidence-resolution-20261031/README.md` | `0729a5f` | no |
| ERG-G1 | `docs/research/evidence-resolution-20261031/HIS05_COMPARABILITY.md` | `0729a5f` | no |
| ERG-G2 | `docs/research/evidence-resolution-20261031/VERSION_EVIDENCE_LINEAGE.md` | `0729a5f` | no |
| ERG-G3 | `docs/research/evidence-resolution-20261031/DEFECT_IMPACT_ASSESSMENT.md` | `0729a5f` | no |
| ERG-G4 | `docs/research/evidence-resolution-20261031/POWER_AND_HORIZON_FEASIBILITY.md` | `0729a5f` | no |
| ERG-CDM | `docs/research/evidence-resolution-20261031/CANDIDATE_DECISION_MATRIX.md` | `0729a5f` | no |
| DA-SPEC | `docs/strategy/DESIGN_A_SPEC_v1.0.md` (branch `feature/design-a-v1`) | `ebf8d8a` | no (not an ancestor of `46578aa`) |

Governance keys, all at `46578aa`: CHARTER = `docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md`, OOC = `docs/governance/OWNER_OPERATING_CONTRACT.md`, DFP = `docs/governance/DEVELOPMENT_FIRST_POLICY.md`, ELP = `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md`. Where the text says "[charter] … Lx", it means `CHARTER:Lx @ 46578aa`.

Governance on this branch: [charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md), [owner operating contract](../../governance/OWNER_OPERATING_CONTRACT.md) (OOC), [development-first policy](../../governance/DEVELOPMENT_FIRST_POLICY.md) (DFP), [evidence ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md) (ELP), [version boundaries](../../../deploy/VERSION_BOUNDARY.md), [deployed-state schema](../../../deploy/DEPLOYED.md), [A47 execution realism](../../a47/A47_EXECUTION_REALISM.md), [A48 replay fidelity](../../a48/A48_REPLAY_FIDELITY.md) and [research temporal governance](../../research_temporal_governance.md), all at `46578aa`.

Related pack documents: [BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md) (baseline reconciliation), [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md) (R1–R9 status), [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) (eligibility, ranking, rejection stages upstream of strategies), [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) (`LedgerEntry`, `RiskBudget`, `SizingDecision`), [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) (WP2 branch plan) and [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) (consolidated owner decisions).

## 2. Summary of key findings

| ID | Finding | Class |
|---|---|---|
| SE-01 | The live path is one bundled policy: momentum is tested first, then reversion, in a single function; geometry is computed elsewhere. | SOURCE_VERIFIED |
| SE-03 | W3: for every momentum signal, the T1 cap reference equals the decision bar's own high. | SOURCE_VERIFIED (mechanism); economic impact UNKNOWN |
| SE-04 | The research contract hash covers 9 logic files; the W3 code, the selection query and the signal-identity module are outside it. | SOURCE_VERIFIED |
| SE-05 | No tracked code computes or verifies `freeze_strategy_contract_hash`; the frozen value cannot be reproduced from a clean tree. | NOT_VERIFIED |
| SE-08 | The runtime strategy label `sb-2026.08` predates the frozen rule change, so it does not identify the deployed rules. | CONTRADICTORY |
| SE-12 | Paper accounting charges stop slippage twice: once in the stop fill price and once inside the flat 0.30%. | SOURCE_VERIFIED |
| SE-15 | Exchange tick and lot filters are not applied in the runtime; only `minNotional` is read, for tranche merging. | SOURCE_VERIFIED |
| SE-17 | Execution realism is established at levels 1–2 only; level 3 (exchange realism) is not. | DOCUMENTED_ONLY |
| SE-25 | Every strategy-version boundary restarts the attributable sample, and the 365-day horizon is already the binding power constraint. | INFERRED |

# Part B. Strategy and signal architecture (WP1-B)

## B1. Current state

**SE-01. One bundled live policy.**
- `detect_trade_setup` evaluates momentum first and reversion second on the last row of the frame; if both match, momentum wins (SOURCE_VERIFIED; `analyzer/simple_entry.py:L5-13, L26-69 @ ea8ae4f`).
- It is called only when `LIVE_LEARNING_MODE` is true (SOURCE_VERIFIED; `analyzer/technical_analyzer.py:L68-73 @ ea8ae4f`). The flag is true at runtime (RUNTIME_VERIFIED; VERA:L93 @ 5d977f2, VER-01).
- The entry predicate lives in `simple_entry.py`. Stops and targets are computed in `_calculate_levels` (SOURCE_VERIFIED; `analyzer/technical_analyzer.py:L404-480 @ ea8ae4f`). Exits, partials, break-even, trailing and time stops live in the tracker (`shared/triple_barrier.py`, `shared/partial_exits.py @ bb7825f`).
- Consequence: no single module defines one strategy end to end, and "momentum" and "reversion" share every geometry and exit rule except their stop thesis level (INFERRED from the above).

**SE-02. Current rule content.** The audit records the rules and this document does not restate them in full (SOURCE_VERIFIED; REP:L429-498 @ 5d977f2, STR-05, STR-07, STR-08, STR-09).
- Momentum: bullish regime; close > EMA20 > EMA50; close > max of the prior 20 highs (decision bar excluded); volume > 1.2 × mean of the prior 20 (`analyzer/simple_entry.py:L28-39 @ ea8ae4f`).
- Reversion: sideways regime; RSI14 < 35; close > previous close; close > open; Bollinger position ≤ 0.20 (`analyzer/simple_entry.py:L50-58 @ ea8ae4f`).
- Stop: thesis level − 0.25 ATR, bounded by entry − 1 ATR, rejected above the per-timeframe risk cap of 2%/5%/3% for 15m/4h/1d (`analyzer/technical_analyzer.py:L425-443 @ ea8ae4f`; `shared/signal_stop.py:L16-46 @ ea8ae4f`).
- Targets: T1 = 1.0R, T2 = 1.8R, T3 = 2.2R (`analyzer/technical_analyzer.py:L454-461 @ ea8ae4f`).
- The thresholds are hand-set operational starting points, not evidence of edge (DOCUMENTED_ONLY; REP:L432 @ 5d977f2, STR-23). No pre-freeze economic evidence exists for them, and their outcomes lie in the sealed FORWARD_HOLDOUT (INFERRED; REP:L434 @ 5d977f2, STR-25).

**SE-03. W3: the T1 reference is the decision bar's own high.**
- `recent = df.tail(20)` includes the decision bar, and `resistance = max(recent.high)` (SOURCE_VERIFIED; `analyzer/technical_analyzer.py:L409-411 @ ea8ae4f`).
- If `T1 > resistance > entry` and `0.99 × resistance > entry`, then `T1 = 0.99 × resistance` (SOURCE_VERIFIED; `analyzer/technical_analyzer.py:L463-467 @ ea8ae4f`).
- A momentum entry requires `close > max(high[-21:-1])` (SOURCE_VERIFIED; `analyzer/simple_entry.py:L28, L38 @ ea8ae4f`). Therefore the 20-bar maximum is the breakout bar's own high for every momentum signal, whether or not the cap binds (MECHANICALLY INFERRED in ERG-G3:L60-68 @ 0729a5f, G3-01a; agrees with `shared/t1_cap.py:L6-9 @ 46578aa`).
- Not look-ahead. Reversion is not affected in the same way (ERG-G3:L70-72 @ 0729a5f).
- At `bb7825f` and `46578aa` the rule is selectable through `T1_CAP_POLICY`, default `legacy_window_v1`, which reproduces it (SOURCE_VERIFIED; `shared/config.py:L124 @ bb7825f`; `shared/t1_cap.py:L22-39, L66-74 @ 46578aa`). The running analyzer image is built from `ea8ae4f`, where the rule is hard-coded, and `T1_CAP_POLICY` is unset (RUNTIME_VERIFIED; VERA:L97 @ 5d977f2, VER-05).
- Realized economic impact: UNKNOWN; bias direction mixed (ERG-G3:L114-128 @ 0729a5f). The audit's severity labels disagree (CONTRADICTORY; REP:L1486 @ 5d977f2, CON-33).

**SE-04. Contract-hash coverage gap.**
- `current_contract()` hashes parameter values plus the bytes of 9 `logic_sources`: `analyzer/simple_entry.py`, `shared/regime.py`, `shared/signal_stop.py`, `shared/triple_barrier.py`, `shared/partial_exits.py`, `shared/risk_management.py`, `shared/strategy_math.py`, `scanner/scanner_logic.py`, `signal_engine/signal_logic.py` (SOURCE_VERIFIED; `research/foundation/contract.py:L15-18, L68-75, L106-111 @ 46578aa`).
- Outside the hash: `analyzer/technical_analyzer.py` (where W3 lives), `shared/t1_cap.py`, `shared/signal_identity.py` (integrity mode, `setup_key`), `signal_engine/main.py` (the `LIMIT 200` query) and `trade_tracker/main.py` (cost booking) (SOURCE_VERIFIED by comparing the list with the file locations above).
- So W3, the alphabetical cut and integrity mode can change without changing the contract hash. ERG-01 reached the same conclusion for the T1 switch, the selection cut and enforce mode (INFERRED; ERG-G3:L268-277 @ 0729a5f, G3-07/G3-08).

**SE-05. The frozen contract hash cannot be regenerated.**
- The field name `freeze_strategy_contract_hash` occurs only in `research/governance/research_freeze.json` (SOURCE_VERIFIED by file-name search at `46578aa`; the JSON content was not opened). No tracked code computes, reads or verifies a field with that name; the generator is NOT FOUND.
- The JSON was committed by `b1c804d` as a byte-preserved copy of a local record (DOCUMENTED_ONLY; commit message of `b1c804d`). It records `freeze_git_sha` `63da7d3` with `freeze_git_dirty` true, dated 2026-08-19 (DOCUMENTED_ONLY; ERG-RM:L49-53 @ 0729a5f).
- `contract.py` is absent at `63da7d3`, so the hash was computed on a descendant tree whose difference is not recorded (INFERRED; ERG-G3:L259-264 @ 0729a5f).
- The legacy contract is snapshotted with `preserved_hash = contract_hash(legacy_contract)` and source `research/governance/research_freeze.json` (SOURCE_VERIFIED; `research/p0r.py:L123-129 @ 46578aa`). Whether the freeze field equals that preserved hash is INFERRED, not checked.
- Class: NOT_VERIFIED. Blocker: reading the JSON value and recomputing it is a data-artefact read and a recomputation; ERG-01 also did not run it (ERG-G3:L304 @ 0729a5f, NV-05).

**SE-06. Regime and BTC context.**
- `classify_regime` is per symbol and per timeframe on the symbol's own frame: bullish (ADX ≥ 25, positive 5-bar EMA20 slope, close > EMA20), bearish (mirror), sideways (ADX < 20 and ATR percentile ≤ 0.75), otherwise volatile. It needs at least 100 bars and has no BTC input (SOURCE_VERIFIED; `shared/regime.py:L10-70 @ ea8ae4f`).
- BTC enters only through the macro gate: BTC 4h change over 18 bars ≤ −5% or a fast-rising USDT dominance blocks every candidate in the cycle, and stale macro data blocks too (SOURCE_VERIFIED; `shared/macro_context.py:L24-25, L36-41, L104-110 @ ea8ae4f`; `signal_engine/signal_logic.py:L722-727 @ ea8ae4f`).
- The macro input is not point-in-time, so the gate cannot be replayed (INFERRED; REP:L513 @ 5d977f2, STR-12).

**SE-07. Same-bar 4h/1d re-fire and the existing identity key.**
- The analyzer re-upserts each (symbol, timeframe) every cycle and resets `signal_generated` (SOURCE_VERIFIED; `analyzer/main.py:L165-174 @ ea8ae4f`). Only a 2 h cooldown and the open-trade exclusion guard the default path (`signal_engine/signal_logic.py:L25-26, L745-746 @ ea8ae4f`), so a 4h or 1d bar can emit again after 2 h (SOURCE_VERIFIED; REP:L837 @ 5d977f2, EXE-17).
- The fix exists only under `SIGNAL_INTEGRITY_MODE=enforce`: `setup_key = "sk_" + sha256([identity_version, symbol, timeframe, candle_open_ms, trade_type, direction, APP_VERSION, setup_policy])[:40]`, insert-once, and refusal once the setup is one bar old (SOURCE_VERIFIED; `shared/signal_identity.py:L64-88, L176-200 @ ea8ae4f`). Runtime mode is `off` (RUNTIME_VERIFIED; VERA:L94 @ 5d977f2, VER-02).
- The target key is defined in [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) (F4); this document adds only the version-boundary rule SE-36.

**SE-08. Strategy label versus rules.**
- `strategy_version` is written as `config.APP_VERSION`, code default `sb-2026.06` (SOURCE_VERIFIED; `shared/config.py:L45 @ ea8ae4f`; `signal_engine/signal_logic.py:L261, L988 @ ea8ae4f`). The runtime value is `sb-2026.08` (RUNTIME_VERIFIED; VERA:L105 @ 5d977f2, VER-13).
- `sb-2026.08` predates the rule change at `63da7d3`, and `EVIDENCE_PHASE_ID` is set by no tracked file (CONTRADICTORY; ERG-G2:L26-29 @ 0729a5f, G2-02). The label therefore does not identify the deployed predicates.
- No `StrategyVersion` type, `source_hash` or `DecisionRecord` exists in code at `46578aa` or `ea8ae4f` (SOURCE_VERIFIED by repository search; absence result).

**SE-09. Dormant and partly wired modules.** None of these is imported by a runtime service at `ea8ae4f`; `t1_cap.py` is imported by the analyzer source at `46578aa`, but not by the deployed `ea8ae4f` analyzer image (SOURCE_VERIFIED; import search over analyzer, signal_engine, scanner, telegram and trade_tracker).

| Module | Purpose and status | Citation |
|---|---|---|
| `shared/trade_geometry.py` | A46 geometry engine: baseline bracket, T1-cap provenance (`window_high_is_decision_bar`), G1–G3 alternatives, per-leg exit ledger, break-even requirements, cost-feasible target. Docstring: nothing in production imports it. | `shared/trade_geometry.py:L14, L99-114, L141-203, L261, L297, L361 @ ea8ae4f` |
| `shared/t1_cap.py` | Versioned T1 reference policy (`legacy_window_v1`, `independent_swing_v1`); fails closed on unknown values. Absent at `ea8ae4f`. | `shared/t1_cap.py:L1-74 @ 46578aa` |
| `shared/setup_diagnostics.py` | A45 explanation of setup decisions and geometry diagnostics; disabled gates `MarketStateGate`, `ExtensionCap`, `SeasonalVolumeConfirmation`. Never decides. | `shared/setup_diagnostics.py:L3-12, L60, L118, L224-286 @ ea8ae4f` |
| `shared/signal_quality.py` | A42 cost and quality diagnostics: `CostModel`, `required_win_rate`, `CostCoveragePolicy`, `cost_aware_rank_key`, `CorrelatedExposurePolicy`, `signal_staleness`, `bar_gaps`. | `shared/signal_quality.py:L3, L46-76, L178, L285, L308, L358, L414, L428 @ ea8ae4f` |
| `research/mechanisms/` | S4 mechanism research: cost model, `TimeSeriesMomentum`, `CrossSectionalMomentum`, `DatasetPermission`, daily portfolio simulator; "never imported by production". Absent at `ea8ae4f`. | `research/mechanisms/__init__.py:L1-8 @ 46578aa`; `research/mechanisms/costs.py:L33, L61 @ 46578aa` |
| `shared/exchange_rules.py` | Tick, step and notional checks (`check_order`, `round_to`, `plan_bracket_orders`); not imported by production. | `shared/exchange_rules.py:L1-18, L85, L93-134, L159 @ 46578aa` |

**SE-10. Exit and holding mechanics (deployed tracker).**
- Time stops per timeframe, as (maximum, stalled after T1, no T1) hours: 15m (48, 24, 12), 4h (96, 48, 24), 1d (240, 120, 72); any other timeframe gets (48, 24, 24) (SOURCE_VERIFIED; `shared/triple_barrier.py:L30-50 @ bb7825f`). `hours_open` is wall-clock since `opened_at` (REP:L820-826 @ 5d977f2, EXE-11).
- After T1 the stop moves to the net break-even level `min(T1, entry × (1 + 0.003) / (1 − 0.001))` (SOURCE_VERIFIED; `shared/triple_barrier.py:L92-96, L117-119 @ bb7825f`).
- After T2 the stop trails at `max(T1, peak × (1 − 2.5%))` (SOURCE_VERIFIED; `shared/triple_barrier.py:L30, L113-116 @ bb7825f`).
- Partial exits are 25/50/25 at T1/T2/T3, with sub-minimum tranches merged into T2 (SOURCE_VERIFIED; `shared/partial_exits.py:L14-44 @ bb7825f`).
- The stop already in force is tested before target events in the same step ("hard-stop priority"), and a gap fills at the lower observed price (SOURCE_VERIFIED; `shared/triple_barrier.py:L194-202 @ bb7825f`).
- Pre-T1 closed-candle thesis invalidation is applied on the REST path only (SOURCE_VERIFIED; `shared/signal_stop.py:L49-55 @ ea8ae4f`; `trade_tracker/main.py:L1147-1169 @ bb7825f`), so whether it fires depends on which price path observed the bar (INFERRED).
- The stall exit label `T1_expired_24h` is hard-coded for all timeframes (CONTRADICTORY; REP:L1471 @ 5d977f2, CON-18).

## B2. Contract principles

| ID | Principle | Source of the requirement |
|---|---|---|
| SE-30 | **Separate hypotheses.** Momentum, Reversion, Candidate B and Candidate C are separate versioned hypotheses with their own `strategy_id`. Design A and passive BTC/cash are benchmarks unless the owner admits Design A as a candidate. | [charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §3 B, L23 |
| SE-31 | **Specification before tuning.** Each version declares rationale, universe, regime use, timeframe, entry, invalidation, exit, holding policy, cost model and failure criteria before any evaluation. No threshold is presented as proven. | CHARTER:L23 @ 46578aa; DFP:L63 @ 46578aa |
| SE-32 | **Pure and deterministic.** A strategy reads only its arguments. No network, database, environment, file or wall-clock access; no randomness. Identical inputs give byte-identical canonical outputs. | CHARTER:L29 @ 46578aa (§3 E) |
| SE-33 | **Closed candles only.** Decisions use bars whose exchange close time is at or before `as_of`; the forming bar is never an input. | CLAUDE.md:L49 @ 46578aa; `shared/ohlcv.py:L26-51 @ ea8ae4f` |
| SE-34 | **No silent drop.** Every negative outcome returns a `RejectionRecord` with a stable reason code. | Pack glossary (`RejectionRecord`); [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) principles |
| SE-35 | **Shared execution, strategy-specific rules.** Fills, costs, exchange filters, ledger and risk are shared infrastructure; the strategy supplies only the rules listed in §B7. | CHARTER:L23-27 @ 46578aa (§3 B–D) |

## B3. Interface (Python-level contract)

The contract below is a design specification. It is not code on any branch; the existing building blocks it reuses are named in §B5. Field names follow the pack glossary.

```python
from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, Sequence

Timeframe = Literal["15m", "1h", "4h", "1d", "1w"]

@dataclass(frozen=True)
class StrategyVersion:
    strategy_id: str          # stable hypothesis name, e.g. "momentum_breakout"
    version: str              # semantic version MAJOR.MINOR.PATCH (rules in SE-38)
    source_hash: str          # sha256 over the sorted (path, sha256(bytes)) of the declared source closure
    config_hash: str          # sha256(canonical_json(resolved effective parameters))
    contract_hash: str        # sha256(canonical_json(StrategyContract descriptor))
    lineage: tuple[str, ...]  # identities this version descends from; never a claim of inherited evidence

@dataclass(frozen=True)
class CandleSet:
    symbol: str
    timeframe: Timeframe
    bars: tuple                # closed bars only, ascending open time, exchange timestamps
    last_close_time: int       # ms, exchange clock
    completeness: Literal["complete", "gap", "duplicate", "insufficient_history"]
    source: str                # feed identity, e.g. "binance_spot_klines_rest"
    content_hash: str          # sha256 of canonical bars; enters DecisionRecord

@dataclass(frozen=True)
class RegimeContext:
    provider_id: str           # e.g. "classify_regime@<hash>", "macro_context@<hash>"
    labels: Mapping[str, str]  # e.g. {"symbol_regime": "bullish", "btc_4h_trend": "flat"}
    as_of: int
    staleness_ms: int
    point_in_time: bool        # False for inputs that cannot be replayed (SE-06)

@dataclass(frozen=True)
class MarketSnapshot:
    as_of: int
    source: str
    filters: Mapping[str, Mapping[str, str]]  # per symbol: tickSize, stepSize, minNotional, raw exchangeInfo filter set
    book: Mapping[str, tuple[str, str]]       # per symbol: best bid, best ask, when available
    content_hash: str

@dataclass(frozen=True)
class Candidate:
    symbol: str
    timeframe: Timeframe
    strategy_id: str
    strategy_version: StrategyVersion
    setup_key: str             # defined in OPPORTUNITY_FUNNEL.md (F4)
    bar_close_time: int
    features: Mapping[str, float | str]
    risk_plan: "RiskPlan"      # entry reference, stop, targets, holding policy (B6)

@dataclass(frozen=True)
class RejectionRecord:
    stage: str                 # "strategy.regime", "strategy.entry", "strategy.geometry", ...
    reason_code: str
    symbol: str
    timeframe: Timeframe
    strategy_id: str
    as_of: int
    detail: Mapping[str, float | str]

class Strategy(Protocol):
    version: StrategyVersion
    def required_inputs(self) -> "InputSpec": ...            # timeframes, minimum closed bars, regime providers
    def evaluate(self, candles: Sequence[CandleSet], regime: RegimeContext,
                 market: MarketSnapshot) -> Candidate | RejectionRecord: ...
    def manage(self, position: "PositionView", event: "PositionEvent") -> Sequence["PositionAction"]: ...
```

Contract clauses:
- **Single entry point per decision.** `evaluate` returns exactly one `Candidate` or one `RejectionRecord` for a (symbol, timeframe, `bar_close_time`). A strategy never returns both, and never returns nothing.
- **Input guards before rules.** `completeness != "complete"`, fewer bars than `required_inputs()` declares, or a regime input whose `staleness_ms` exceeds the declared bound produce a `RejectionRecord` at stage `strategy.input` (reason codes `incomplete_candles`, `insufficient_history`, `stale_regime`). This covers the immature EMA200 case, where only 200 bars are fetched (INFERRED; REP:L431 @ 5d977f2, STR-22).
- **Point-in-time flag.** A strategy that uses a `RegimeContext` with `point_in_time = False` is replayable only from forward-captured inputs, and its contract says so (SE-06).
- **`manage` is also pure.** It maps (position view, one event) to actions: move stop, exit fraction, close. It cannot fetch a price; the shared tracker supplies the event (§B6).
- **No sizing.** A strategy proposes a `risk_plan` in price terms; quantity, notional and capital are the `SizingDecision` of [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md).
- **Ranking.** A strategy may expose a `score` feature with a declared direction. Cross-strategy ranking into `Opportunity` is a funnel function ([OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md), F6), not a strategy function.

## B4. StrategyVersion identity and its relation to the freeze and to version boundaries

**SE-37. Hash definitions.**
- `source_hash` covers the declared **closure** of every module that can change a `Candidate`, `RejectionRecord` or `PositionAction` of that strategy: entry, regime provider, geometry and T1 policy, identity, exit and holding code. The current 9-file list (SE-04) is not sufficient: under this contract the closure for the current families must also include `analyzer/technical_analyzer.py` (or the module that replaces `_calculate_levels`), `shared/t1_cap.py` and `shared/signal_identity.py`.
- `config_hash` covers the **effective** parameter values, wherever they come from. Live thresholds held in the database override `.env` (CLAUDE.md:L48 @ 46578aa; contradicted for some keys, REP:L1464 @ 5d977f2, CON-11), and these tables have no lineage (SOURCE_VERIFIED; REP:L762 @ 5d977f2, CAL-09). A config hash computed from environment values alone would therefore be incomplete (INFERRED).
- `contract_hash` covers the `StrategyContract` descriptor: input specification, output schema versions, regime providers, `cost_model_id`, `fill_model_id`, holding policy and the declared failure criteria. It changes when the promise changes, even if the code is identical.
- All three use the existing canonical JSON (`sort_keys`, compact separators, ASCII) and sha256 (`research/foundation/contract.py:L106-111 @ 46578aa`), so the scheme stays comparable with the research contract.

**SE-38. Semantic-version rules.**

| Change | Version step | Strategy-version boundary? |
|---|---|---|
| Any change that can alter a `Candidate`, `RejectionRecord`, `PositionAction`, fill or measured P&L: entry predicate, regime use, geometry (W3), identity key, exit, holding, cost model or fill model used for measurement | MAJOR | Yes (DFP:L63 @ 46578aa: geometry, selection and integrity changes are declared boundaries) |
| Additional recorded fields that no decision reads | MINOR | No, if the golden replay (SE-71) is byte-identical on decisions |
| Refactor proven byte-identical by the golden replay | PATCH | No |

A version whose `source_hash`, `config_hash` or `contract_hash` differs from the declared identity is treated as a different, undeclared version. That is a stop condition for the affected stream ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §6, L57: "unversioned strategy change").

**SE-39. Mapping onto the frozen research contract.**
- The frozen contract is one bundle covering both momentum and reversion (SOURCE_VERIFIED; `research/foundation/contract.py:L15-75 @ 46578aa`; `research/p0r.py:L123-129 @ 46578aa`).
- Under this interface it maps to two identities, `momentum_breakout 1.0.0` and `reversion_rsi_bb 1.0.0`. Each carries `lineage = ("legacy_research_contract", <preserved legacy hash>)`, where the preserved hash is the one recorded by `research/p0r.py`. The `freeze_strategy_contract_hash` field is referenced, never rewritten.
- The split is an identity mapping only. It creates no new evidence, and the sealed FORWARD_HOLDOUT outcomes of the bundle are not re-attributed to either identity (DFP:L57 @ 46578aa; `research/data_governance/governance.py:L86-89 @ 46578aa`).
- `research_freeze.json` stays byte-unchanged. A future freeze is a new, content-addressed artefact (`docs/research_temporal_governance.md:L5-9 @ 46578aa`).

**SE-36. Version boundaries in Paper.**
- [VERSION_BOUNDARY.md](../../../deploy/VERSION_BOUNDARY.md) is append-only; versions are never pooled without stratification, and nothing is attributed retroactively (SOURCE_VERIFIED; `deploy/VERSION_BOUNDARY.md:L3-5 @ 46578aa`). Its only entry, VB-2026-10-27-01, is a risk-policy boundary whose `config_hash_after` and `code_sha_after` are still PENDING (SOURCE_VERIFIED; `deploy/VERSION_BOUNDARY.md:L7-35 @ 46578aa`).
- A strategy boundary entry adds: `boundary_id`, `strategy_id`, version before and after, the three hashes before and after, `fill_model_id`, `cost_model_id`, the activation minute, the admission-authority service, image identifiers and the stratification rule.
- **No re-fire across a boundary.** A new version evaluates only bars whose `bar_close_time` is at or after its activation minute. A bar already evaluated under the old version is never re-evaluated under the new one. This prevents a version change from re-keying, and so re-emitting, the same candle, a risk that exists today because `APP_VERSION` is part of the enforce-mode key (SOURCE_VERIFIED; `shared/signal_identity.py:L75, L86-88 @ ea8ae4f`).
- An entry is written only for an owner-approved activation. This document creates no entry.

## B5. Mapping the existing families onto the interface

This section maps; it does not rank. ERG-01's verdict on B versus C is **INCONCLUSIVE**, and D-pause is not dominated (INFERRED; ERG-CDM:L46, L373-374, L380 @ 0729a5f; G5-25, G5-26). That verdict is a decision state, not negative evidence about any family (ERG-RM:L205 @ 0729a5f). No negative result from a materially different strategy transfers to these families ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §2, L18); HIS-05 is materially different from current momentum (INFERRED; ERG-G1:L15-18 @ 0729a5f, G1-01).

| Proposed `strategy_id` | Source and status | Interface mapping | Specification gaps that must close before any evaluation | Evidence status |
|---|---|---|---|---|
| `momentum_breakout` 1.0.0 | Current live rule (SE-02). Frozen contract. | `evaluate` = momentum branch of `detect_trade_setup` + `_calculate_levels` with `legacy_window_v1`; `manage` = current tracker rules (SE-10). Regime provider `classify_regime` (accepts `bullish`) plus macro veto. | Declared rationale and failure criteria; holding ceilings per timeframe stated as policy, not defaults; W3 status recorded as a known defect of 1.0.0. | No pre-freeze economic evidence; outcomes sealed in FORWARD_HOLDOUT (STR-25). No historical result attributable to it (ERG-G2:L21-25 @ 0729a5f, G2-01). |
| `reversion_rsi_bb` 1.0.0 | Current live rule (SE-02). Frozen contract. | Reversion branch; stop thesis = 20-bar low; same targets and exits. Regime `sideways`. | As above. W3 does not apply in the same way (ERG-G3:L72 @ 0729a5f). | As above. |
| `momentum_successor` (Candidate B) | Concept only: 4h/1d breakout continuation with corrected geometry and corrected selection (ERG-CDM:L52-62 @ 0729a5f). | New `strategy_id` with `lineage` pointing to `momentum_breakout 1.0.0` for code ancestry only; "frozen version identity, no inherited claims". | W3 reference choice (SE-80), selection rule, timeframe set, regime beyond routing, entry parameters, friction, boundary record, at most one refinement (ERG-CDM:L388 @ 0729a5f). | None. Materially different from the concept HIS-05 tested (ERG-G1:L19 @ 0729a5f, G1-02). |
| `trend_pullback` (Candidate C) | Concept only: medium-term trend continuation entered after a pullback (ERG-CDM:L52-62 @ 0729a5f). | New `strategy_id`; likely daily closes; holding class swing or position. | Horizon, filter form, entry, exits, stops, universe, benchmark and a filter-isolating control (ERG-CDM:L388, L434-435 @ 0729a5f). EMA200, RSI 40–50 and ATR 2 are explicitly **not** assumed. | None. Possibly nested with Design A (ERG-CDM:L260-261 @ 0729a5f, G5-21/G5-22). |
| `btc_sma200_weekly` (Design A) | Benchmark or optional hypothesis, not the active-trading mandate ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) L15, L23). Review-only branch, D0, synthetic evidence only (DOCUMENTED_ONLY; DA-SPEC:L3-8, L40-61 @ ebf8d8a). | `evaluate` on 200 completed UTC daily closes, weekly decision: `LONG` if the Sunday close is above SMA200, else `FLAT`, equality `FLAT`; execution at the Tuesday open, at most 72 h deferral (DA-SPEC:L95-146 @ ebf8d8a). No stop or targets: `manage` handles only the regime flip. Its own ledger exists (`research/design_a/ledger.py @ ebf8d8a`). | Benchmark role versus candidate role is an owner decision (Design A decision memo E1–E8, `docs/strategy/DESIGN_A_PROFITABILITY_DECISION_MEMO.md:L3-20 @ ebf8d8a`). | Benchmarks B0–B5 documented, never computed (DA-SPEC:L656-673 @ ebf8d8a). |
| `btc_buy_hold`, `cash` | Passive benchmarks (DA-SPEC:L656-673 @ ebf8d8a, B1 primary). | Degenerate strategies: constant `LONG` or constant `FLAT`; same cost and fill model as the strategy they benchmark. | Benchmark definition per hypothesis at preregistration. | Not computed. |

Dormant modules map onto shared services or optional, separately versioned rules. None becomes active by being mapped.

| Module | Role under the interface | Activation path |
|---|---|---|
| `shared/t1_cap.py` | T1 reference policy registry used by the geometry of momentum and reversion (SE-40). | Strategy-version boundary; owner decision SE-80. |
| `shared/trade_geometry.py` | Reference implementation for geometry provenance (`references`, `window_high_is_decision_bar`), the G1–G3 alternatives and the per-leg exit ledger; the source of the W3 invariant tests (SE-64). | Library for tests and research replays; any production use is a boundary. |
| `shared/setup_diagnostics.py` | Explanation payload for `RejectionRecord.detail` (`explain_setups`, `setup_geometry`). The three disabled gates are each a separate candidate rule, never a silent default. | Diagnostics: Safe development-only. Each gate: a new MAJOR version of the strategy that adopts it. |
| `shared/signal_quality.py` | Input to the funnel's `expected_cost` and feasibility stage (`CostModel`, `required_win_rate`, `CostCoveragePolicy`, `cost_aware_rank_key`) and to correlated-exposure limits (`CorrelatedExposurePolicy`, see [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md)). Its `tracker_accounting` = 0.2 fee + 0.1 slippage is the legacy model (`shared/signal_quality.py:L74-76 @ ea8ae4f`). | Funnel and portfolio documents own activation. |
| `research/mechanisms/` | Research-only cost model and two momentum signal classes (`TimeSeriesMomentum`, `CrossSectionalMomentum`) plus `DatasetPermission`. These signal classes are **not** among the charter's hypotheses; using them would require their own specification and preregistration. | Protected research or simulation, after OD-DF-1. |
| `shared/exchange_rules.py` | Shared `OrderIntent` validation and rounding (SE-50). | Safe development-only until wired; wiring into Paper is a measurement boundary. |

## B6. Position state machine

The state machine is shared infrastructure. The strategy supplies its parameters through `risk_plan` and its decisions through `manage`. Current equivalents are named so the mapping can be tested.

**States.**

| State | Meaning | Current equivalent |
|---|---|---|
| `PLANNED` | `OrderIntent` built from a `Candidate` and a `SizingDecision`; not yet sent. | signal admitted by the tracker |
| `WORKING` | Entry order resting or waiting (do-not-chase). | `paper_entry_orders.status = 'working'` (`trade_tracker/main.py:L579-610 @ bb7825f`) |
| `OPEN` | Filled quantity > 0; initial stop and all targets live. | `active_trades.status = 'open'` |
| `PARTIAL_T1`, `PARTIAL_T2` | One or two target tranches filled; stop moved per policy. | `highest_target` 1 or 2 (`shared/triple_barrier.py:L113-119 @ bb7825f`) |
| `CLOSED` | Terminal; quantity 0; `exit_reason` set. | `active_trades.status = 'closed'` |
| `REJECTED` | Terminal before fill: invalidated, infeasible after rounding, or refused by risk. | `paper_entry_orders.status = 'rejected'` |
| `EXPIRED_UNFILLED` | Terminal before fill: entry wait elapsed. | `entry.expired` evidence event (`trade_tracker/main.py:L233-439 @ bb7825f`) |

**Transitions.** Each transition is one `DecisionRecord` (§E2).

| From | Event | Guard | Action | To | Owner |
|---|---|---|---|---|---|
| `PLANNED` | entry observation | price ≤ max(stop, invalidation) | reject `signal_invalidated_before_fill` | `REJECTED` | shared (current rule, `shared/entry_execution.py:L12-20 @ bb7825f`) |
| `PLANNED` | entry observation | price ≤ planned entry | fill under the active fill model | `OPEN` | shared |
| `PLANNED` | entry observation | price > planned entry | rest at planned entry | `WORKING` | strategy declares chase policy; shared executes |
| `WORKING` | time | wait > declared entry window | cancel | `EXPIRED_UNFILLED` | strategy declares window |
| `PLANNED`/`WORKING` | rounding | quantity < stepSize or notional < minNotional | reject `below_exchange_minimum` | `REJECTED` | shared (SE-50) |
| `OPEN`/`PARTIAL_*` | price ≤ effective stop | — | exit remaining quantity at the stop fill model | `CLOSED` | shared mechanics; strategy sets level |
| `OPEN` | closed bar | close ≤ invalidation (pre-T1) | exit remaining at next observation | `CLOSED` | strategy rule, evaluated on closed bars on **one** path (fixes the REST-only split in SE-10) |
| `OPEN` | price ≥ T1 | target fill rule met | sell T1 fraction; apply post-T1 stop policy | `PARTIAL_T1` | shared fill; strategy fraction and stop policy |
| `PARTIAL_T1` | price ≥ T2 | target fill rule met | sell T2 fraction; apply post-T2 stop policy | `PARTIAL_T2` | as above |
| `PARTIAL_T2` | price ≥ T3 | target fill rule met | sell remainder | `CLOSED` | as above |
| any open state | time | `hours_open` ≥ declared ceiling | exit remaining at next observation | `CLOSED` | strategy declares ceiling (SE-43) |
| any open state | `manage` action | strategy-specific thesis exit (for example a Design A regime flip) | exit as instructed | `CLOSED` | strategy |

**SE-41. Same-observation conflicts.** When one observation or bar satisfies both the stop and a target, the stop already in force wins. This is the current convention (SOURCE_VERIFIED; `shared/triple_barrier.py:L194-202 @ bb7825f`) and is pessimistic. A research replay on bars must instead use a declared interval model; the A48 `ohlc_uncertainty_v1` mode is the existing candidate (DOCUMENTED_ONLY; [A48](../../a48/A48_REPLAY_FIDELITY.md), `docs/a48/A48_REPLAY_FIDELITY.md:L87-140 @ 46578aa`).

**SE-42. Stops, break-even and trailing.**
- The initial stop comes from the strategy's thesis level and buffer, bounded by the strategy's maximum structural risk; a plan above the bound is a `RejectionRecord` (`structural_risk_exceeds_cap`), as today (`shared/signal_stop.py:L16-46 @ ea8ae4f`).
- Break-even after T1 is allowed only where the strategy declares it. Under a research cost model, the net break-even level is `entry × (1 + c_entry) / (1 − c_exit)`, with `c_entry` and `c_exit` the per-side costs of §C2. The current formula `entry × 1.003 / 0.999` embeds the R4 double count (SE-12) and belongs to the legacy model only.
- Trailing is allowed only where the strategy declares it with a rationale, and its distance is part of `config_hash`. The current 2.5% trail after T2 is a hand-set value, not evidence (STR-23).
- Partial fractions are strategy parameters, sum to 1, and are validated against exchange minimums after rounding. A tranche below the minimum merges as today (`shared/partial_exits.py:L14-44 @ bb7825f`); unsold dust is inventory, not cost (`docs/a48/A48_REPLAY_FIDELITY.md:L142-174 @ 46578aa`).

**SE-43. Holding policy: a ceiling, not a mandate.**
- Each strategy declares a holding class (intraday, swing or position; [charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §1, L8) and a `max_holding` **ceiling**. A position may close earlier on any declared exit. No minimum holding period exists, and no strategy is required to hold to its ceiling.
- Stall rules (current: close if T1 is hit but T2 is not reached within a set time, or if T1 is not reached at all) are optional strategy rules. They are declared, versioned and labelled per timeframe; the hard-coded `T1_expired_24h` label (CON-18) is replaced by a label that carries the actual rule.
- A position-class strategy such as Design A may declare no time ceiling and exit only on its thesis signal. A ceiling is never imposed by the shared layer, and none is inferred from the 14-day figure the charter lists as a non-goal (L10).
- Values are not chosen here. Current values (SE-10) remain the legacy policy of `momentum_breakout 1.0.0` and `reversion_rsi_bb 1.0.0`.

## B7. Shared execution infrastructure versus strategy-specific rules

| Concern | Shared infrastructure (one implementation, versioned once) | Strategy-specific (declared in each `StrategyContract`) |
|---|---|---|
| Market data | Closed-candle construction from exchange close times, gap and duplicate checks (`shared/ohlcv.py:L26-83 @ ea8ae4f`), `CandleSet.content_hash` | Timeframes and minimum history in `required_inputs()` |
| Universe | `MarketSnapshot`, `EligibilityResult` ([OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md)) | Optional narrower universe (for example BTC/USDT only for Design A) |
| Regime | Providers (`classify_regime`, macro context) with `provider_id`, `as_of`, `staleness` | Which labels it accepts, and whether each series is a veto, a filter, a ranking feature or unused |
| Setup | — | Entry predicate, invalidation level, `score` and its direction |
| Geometry | T1 policy registry, invariant checks (SE-40) | Stop thesis and buffer, risk bound, target references and multiples, fallback |
| Exit management | State machine (§B6), observation handling, conflict rule (SE-41) | Partial fractions, break-even and trailing declarations, stall rules, holding ceiling, thesis exits |
| Orders and fills | `OrderIntent`, exchange-filter rounding (SE-50), fill model (`fill_model_id`), partial fills, latency | Entry order type and chase policy, entry wait window |
| Costs | Cost model (`cost_model_id`, §C2), single booking | None; a strategy cannot choose a cheaper cost model |
| Capital and risk | `LedgerEntry`, `RiskBudget`, `SizingDecision` ([PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md)) | A per-trade risk plan in price terms only |
| Identity and evidence | `StrategyVersion` hashing, `setup_key`, `DecisionRecord`, hash chain (§E) | The declared source closure and parameters |

Rule: a strategy contract may not override a shared component. A strategy that needs a different shared behaviour (for example a different fill model) requires a new version of that shared component, which is a boundary for every strategy that uses it.

## B8. W3 geometry invariant (R2)

**SE-40. Invariant.** For every target derived from a market-structure reference:
1. **Independence.** The reference is computed only from bars that closed **before** the decision bar, or from a declared independent source. It is never the decision bar's own high, low or close.
2. **Provenance.** Every `risk_plan` records `t1_reference_policy`, `t1_reference_value`, `t1_reference_bar_close_time` (or `none`) and `t1_source` ∈ {`structure`, `r_multiple_fallback`}.
3. **Defined fallback.** When no admissible reference above entry exists, T1 takes the declared fallback; the fallback is part of the contract, never an implicit default.
4. **Ordering.** `stop < entry < T1 < T2 < T3` after exchange rounding; otherwise `RejectionRecord` (`invalid_geometry`).
5. **Cost feasibility.** T1 must lie above the net break-even level of the active cost model. If it does not, the outcome is either a `RejectionRecord` (`t1_not_cost_feasible`) or a declared fallback; which one is an owner decision (SE-80). Today T1 can sit below net break-even (SOURCE_VERIFIED; REP:L527-531 @ 5d977f2, STR-21).

**Available references** (CONTRADICTORY: two corrections are documented, ERG-G1:L192-195 @ 0729a5f, G1-10):

| Option | Rule | Consequence for momentum (INFERRED from the code cited) |
|---|---|---|
| a. Prior window | Max high of the 20 bars before the decision bar (A45 correction). | For a breakout, this maximum is the breakout level, which is below entry, so `resistance > entry` never holds and the cap never binds: T1 is always 1R (`shared/t1_cap.py:L66-74 @ 46578aa` applied to `analyzer/simple_entry.py:L28, L38 @ ea8ae4f`). Option a is therefore equivalent to removing the cap for momentum. |
| b. Independent swing | `independent_swing_v1`: the nearest confirmed swing high above entry among bars closed before the decision bar (two bars each side); none → T1 = 1R (`shared/t1_cap.py:L10-11, L42-54 @ 46578aa`). | The cap binds only where an earlier swing high above entry exists. Because the breakout close exceeds every high of the prior 20 bars, any qualifying swing high is more than 20 bars old. |
| c. No structure cap | T1 = fixed R multiple. | Same targets as option a for momentum, stated explicitly. |

**Change class.** Implementing a policy behind a default-off flag that is byte-identical at its default is a Safe development-only correction (DFP:L87 @ 46578aa; the existing `T1_CAP_POLICY` follows this pattern). Activating any option in Paper is a Strategy-version-changing correction: it creates `momentum_breakout 2.0.0` (and `reversion_rsi_bb 2.0.0` if reversion is switched), needs owner approval, and is recorded in [VERSION_BOUNDARY.md](../../../deploy/VERSION_BOUNDARY.md) (`shared/t1_cap.py:L13-16 @ 46578aa`; ERG-G3:L132-134 @ 0729a5f). It is not a step toward a profitability claim.

# Part C. Economic and execution model (WP1-C)

## C1. Current Paper-runtime assumptions

**SE-11. Flat round-trip charge on a fixed notional.**
- `FEE_ROUNDTRIP_PCT` defaults to `0.3` (percent), with the comment "0.1%/side fee + ~0.1% slippage … consistent with STOP_SLIPPAGE=0.1%" (SOURCE_VERIFIED; `shared/config.py:L88-90 @ ea8ae4f`, `shared/config.py:L90-92 @ bb7825f`). Runtime value 0.3 (RUNTIME_VERIFIED; VERA:L111 @ 5d977f2, VER-19).
- The charge is `TRADE_AMOUNT_USDT × FEE_ROUNDTRIP_PCT / 100` on the fixed configured notional, not on executed per-leg notional (SOURCE_VERIFIED; `shared/fees.py:L20-24 @ bb7825f`).
- Net = rounded gross − that charge; the label policy is `net_after_modeled_cost_v1` (SOURCE_VERIFIED; `shared/fees.py:L41, L52-60 @ bb7825f`), applied at close (`trade_tracker/main.py:L1348-1350 @ bb7825f`) and in the `trade.closed` evidence event (`trade_tracker/main.py:L409-416 @ bb7825f`). Gross values are stored as gross on purpose (`shared/fees.py:L1-8 @ bb7825f`).
- The same flat deduction feeds the risk guard's realized-result history (SOURCE_VERIFIED; `trade_tracker/main.py:L947-953 @ bb7825f`). Accounting therefore influences admission and is not a pure reporting choice (INFERRED).
- Spread is a selection filter (`MAX_SPREAD_PCT` 0.15), never a cost (SOURCE_VERIFIED; REP:L723, L833 @ 5d977f2, IND-03, EXE-13).

**SE-12. Stop slippage counted twice (R4).**
- `STOP_SLIPPAGE` defaults to `0.001` (SOURCE_VERIFIED; `shared/config.py:L107 @ bb7825f`); runtime 0.001 (RUNTIME_VERIFIED; VER-19). It is passed to the barrier with `roundtrip_cost = FEE_ROUNDTRIP_PCT / 100` (`trade_tracker/main.py:L1207-1211 @ bb7825f`).
- A stop exit fills at `stop × (1 − 0.001)` (SOURCE_VERIFIED; `shared/triple_barrier.py:L308-322 @ bb7825f`), and the flat 0.3%, which already contains a 0.1% slippage allowance, is deducted afterwards (SE-11).
- The repository states this itself: "slippage on the stop fraction is charged twice: once in the fill price, once in the flat allowance. Targets are filled exactly at the target, so their share of the allowance is a pure cushion" (SOURCE_VERIFIED; `shared/execution_calibration.py:L349-362 @ bb7825f`).
- Net effect: about 0.40% on stop exits versus 0.30% on target exits (INFERRED; REP:L835 @ 5d977f2, EXE-15; ERG-G3:L243-251 @ 0729a5f, G3-04). Direction conservative; realized size UNKNOWN.
- The double count is also inside the geometry: the post-T1 break-even stop is `entry × (1 + 0.003) / (1 − 0.001)` ≈ entry × 1.004 (SOURCE_VERIFIED; `shared/triple_barrier.py:L92-96 @ bb7825f`). Correcting the accounting alone would leave this level unchanged; correcting the level changes geometry. This is why the charter separates the R4 accounting correction from stop-geometry corrections ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §4, L41).

**SE-13. Entry fills: `observed_price_v0`.**
- Default fill model `observed_price_v0`; `resting_limit_v1` exists but is off (SOURCE_VERIFIED; `shared/config.py:L112 @ bb7825f`; `shared/entry_execution.py:L30-40 @ bb7825f`). Runtime default confirmed (RUNTIME_VERIFIED; VERA:L103 @ 5d977f2, VER-11).
- The fill price is the REST last-trade price (SOURCE_VERIFIED; `trade_tracker/main.py:L1430-1450 @ bb7825f`). The bracket is rebased proportionally to the fill (`shared/execution.py:L4-21 @ bb7825f`).
- The model's own description: a waiting limit order "fills at the first observed price at or below the limit, which may be well below it. That is price improvement a resting limit order does not get", and it "drops adversely selected entries" (SOURCE_VERIFIED; `shared/entry_execution.py:L35-40 @ bb7825f`). A42 estimated it at about 13 bps optimistic (HISTORICAL_REPORTED; `docs/a42/A42_STRATEGY_SIGNAL_QUALITY.md:L42, L64 @ 46578aa`).
- Not modelled: bid/ask, latency, partial fills, tick and lot rounding, entry slippage (SOURCE_VERIFIED; REP:L812 @ 5d977f2, EXE-07). The effective fill model at runtime is NOT_VERIFIED (REP:L813 @ 5d977f2, EXE-08; blocker: image content, SE-23).

**SE-14. Targets and time exits.** Targets fill exactly at the target price on a touch (`high >= T`) (SOURCE_VERIFIED; `shared/triple_barrier.py:L209-214 @ bb7825f`). Time and invalidation exits fill at the observed price with no slippage (SOURCE_VERIFIED; REP:L820-826 @ 5d977f2, EXE-11). No queue position or adverse selection is modelled for target fills (INFERRED).

**SE-15. Exchange constraints.** The tracker reads `minNotional` (filter type `NOTIONAL` or `MIN_NOTIONAL`) from `exchangeInfo`, with fallback `MIN_ORDER_NOTIONAL_USDT = 5`, and uses it only for tranche merging (SOURCE_VERIFIED; `trade_tracker/main.py:L1453-1477 @ bb7825f`; `shared/config.py:L108 @ bb7825f`). `tickSize` and `stepSize` appear only in `shared/exchange_rules.py`, which production does not import (SOURCE_VERIFIED; SE-09). Runtime price and quantity rounding: NOT FOUND.

**SE-16. Clock, latency and price path.** Candle closure uses the host clock without exchange time sync (SOURCE_VERIFIED; REP:L809-810 @ 5d977f2, EXE-05/EXE-06). Monitoring uses a trade stream with a REST check every 30 s, and ticks can be dropped (SOURCE_VERIFIED/INFERRED; REP:L843-844 @ 5d977f2, EXE-18/EXE-19). Latency between bar close, decision and fill is not modelled (INFERRED).

**SE-17. Execution realism level.** A47 and A48 establish level 1 (mathematical correctness) and level 2 (agreement with the Paper tracker) only; "Level 3 (real-world execution validity) is not established" (DOCUMENTED_ONLY; [A47](../../a47/A47_EXECUTION_REALISM.md), `docs/a47/A47_EXECUTION_REALISM.md:L9 @ 46578aa`; `docs/a48/A48_REPLAY_FIDELITY.md:L23 @ 46578aa`; `docs/a48/A48_ACCEPTANCE_CRITERIA.md:L9-15 @ 46578aa`). Level 3 needs a forward capture under an owner-approved Paper window (`docs/a47/A47_EXECUTION_REALISM.md:L105-114 @ 46578aa`). A47 kept the double count as a conservative model assumption (`docs/a47/A47_EXECUTION_REALISM.md:L67-71 @ 46578aa`); the A48 cost ledger `a48-cost-v1` books slippage once, inside the execution price, with the 0.1% allowance used as stress only (DOCUMENTED_ONLY; `docs/a48/A48_REPLAY_FIDELITY.md:L142-174 @ 46578aa`; `shared/execution_calibration.py:L407-445 @ 46578aa`). Replay stop fills are optimistic at the level and on gaps (DOCUMENTED_ONLY; REP:L1150 @ 5d977f2, HIS-32).

**SE-18. Cost figures in use across the repository.**

| Context | Figure | Citation | Class |
|---|---|---|---|
| Owner standard | 0.10% fee per side plus spread and slippage | OOC:L10 @ 46578aa; DFP:L9, L61 @ 46578aa | DOCUMENTED_ONLY |
| Paper tracker | flat 0.30% + 0.1% stop fill ≈ 0.40% on stop exits | SE-11, SE-12 | SOURCE_VERIFIED |
| Learner target | profit% − 0.3 | REP:L776 @ 5d977f2, LRN-06 | SOURCE_VERIFIED |
| Walk-forward scripts | flat 0.30%, no freeze cutoff | REP:L1156 @ 5d977f2, HIS-38 | SOURCE_VERIFIED |
| S4 tiered model | fee 0.10%/side, half-spread 0.01% (BTC/ETH) or 0.04% (others), slippage 0.05%/side → 0.32%/0.38% round trip; stress ×2 → 0.44%/0.56% | ERG-CDM:L294 @ 0729a5f; REP:L920-932 @ 5d977f2, HIS-15 | DOCUMENTED_ONLY |
| Design A | fee 0.10%/side; half-spread 0.05%/0.10%; slippage 0.05%/0.10% → about 0.40% baseline, 0.60% stress | DA-SPEC:L151-156, L524-527 @ ebf8d8a | DOCUMENTED_ONLY |
| Evidence Ladder | STRESS costs (10 + 10 bps planning fee baseline, account fee unverified) plus an MES charge per position | ELP:L81 @ 46578aa | DOCUMENTED_ONLY |
| HIS-05 engine | flat 0/0.3/0.6%, stops fill exactly | ERG-G1:L103-104, L243 @ 0729a5f | HISTORICAL_REPORTED |

**SE-19. Reconciliation item: the stress level.** The charter's proposed 0.60% stress is above every documented stress level of the S4 model (ERG-CDM:L294, L454 @ 0729a5f). The Evidence Ladder defines STRESS differently, with an MES charge per position (ELP:L81 @ 46578aa), and the half-spread figures conflict between sources (CONTRADICTORY; REP:L1498 @ 5d977f2, CON-45). The charter asks for reconciliation at WP3 (L57); this is recorded as an owner decision (SE-81), not as a DEVIATION ALERT.

## C2. Research cost model (proposed; OWNER DECISION REQUIRED, SE-81)

**SE-44. Per-side decomposition without double counting.** For each executed leg *i* with executed notional *N_i*:

`cost_i = N_i × (f + h + s)`

- *f*: exchange fee per side. 0.10% is the owner standard (OOC:L10 @ 46578aa; DFP:L9 @ 46578aa). The actual account fee tier is NOT_VERIFIED (ERG-G4:L557 @ 0729a5f, G4-N6), and no discounted-fee optimisation is allowed (DFP:L61 @ 46578aa).
- *h*: half-spread, the distance from mid to the touch that a taker pays.
- *s*: slippage beyond the touch (impact and adverse movement between decision and fill).

| Scenario | f | h | s | Per side | Round trip |
|---|---|---|---|---|---|
| Research baseline (proposed) | 0.10% | 0.05% | 0.05% | 0.20% | 0.40% |
| Stress (proposed) | 0.10% | 0.10% | 0.10% | 0.30% | 0.60% |

This decomposition reproduces the charter's 0.40%/0.60% with the standard 0.10% fee per side ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §3 C, L25) and matches the Design A specification (DOCUMENTED_ONLY; DA-SPEC:L151-156, L524-527 @ ebf8d8a). Whether *h* is flat or tiered by liquidity (S4: 0.01% for BTC/ETH, 0.04% for others) is part of SE-81.

**SE-45. Single-booking rule.** Each cost component is booked exactly once per leg, in exactly one place:
- *h* and *s* are inside the modelled execution price: a buy fills at `reference × (1 + h + s)`, a sell at `reference × (1 − h − s)`, where `reference` is the mid (or the last trade when no book is available, with that fact recorded in the `Fill`).
- *f* is an explicit fee entry on executed notional.
- No flat allowance is added on top. The stress scenario is a separate evaluation, never an addition to the baseline. This is the a48-cost-v1 convention (`docs/a48/A48_REPLAY_FIDELITY.md:L142-174 @ 46578aa`) and the ledger invariant PR-I11 in [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md).

**SE-46. Fill rules by order type** (research fill model; one `fill_model_id`).
- **Entry (taker).** First observation after `decision_time + latency`; fills at that reference adjusted by *h* + *s*. The decision bar's close is a reference for planning only, never a fill price.
- **Entry (resting limit).** Fills only when the price trades **through** the limit; the fill is at the limit, not at a better observed price. This removes the price improvement that `observed_price_v0` grants (SE-13).
- **Targets (resting sell limits).** Fill at the target only on trade-through. A touch-only fill is a sensitivity case, not the baseline (it is the current tracker convention, SE-14).
- **Stops (market on trigger).** Trigger when an observation is at or below the stop. Fill reference = `min(stop, first observation after trigger)`. A gap-through therefore fills at the gap price, not at the stop (the current tracker already does this, `shared/triple_barrier.py:L198-200 @ bb7825f`). Then *h* + *s* apply once. Whether stop slippage should exceed *s* in stress is part of SE-87.
- **Time and thesis exits.** Taker fills at the next observation, with *h* + *s*. The current zero-slippage time exit (SE-14) is legacy only.
- **Bar-based replays.** Intrabar ordering is unknown; the replay uses the A48 interval mode or the declared pessimistic convention (SE-41), never a target-first order like the HIS-05 engine's (ERG-G1:L127, L242 @ 0729a5f).

**SE-47. Partial fills.** An `OrderIntent` may yield several `Fill` records. `Position` quantity is the sum of filled quantity. Target tranches are recomputed from filled quantity and rounded to `stepSize`. A residual below `minNotional` merges into the next tranche or remains as inventory. The paper simulation may assume a full fill only while notional stays within a declared participation limit of recent traded volume; the limit is owner-decided capacity policy ([PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md)).

**SE-48. Latency and clock.** Every `DecisionRecord` carries `bar_close_time` (exchange), `decision_time`, `intent_time` and `fill_time`. Candle closure uses the exchange close time from the kline itself, not the host clock (fixes SE-16 for decisions). The latency used by the research fill model is a declared parameter; level-3 calibration of it needs the forward capture of SE-74.

**SE-49. Cost in R units.** For a stop distance *r* (fraction of entry), the round-trip cost in R is `c_RT / r`. At the 4h cap of 5% this is 0.08R (baseline) and 0.12R (stress); at the 1d cap of 3%, 0.133R and 0.20R (INFERRED arithmetic; ERG-CDM:L298-308 @ 0729a5f); at the 15m cap of 2%, 0.20R and 0.30R (same arithmetic). The audit reports 15m fees of 0.22–0.43R per trade under the legacy model (DOCUMENTED_ONLY; REP:L1236-1240 @ 5d977f2, ECO-06). These are cost facts, not evidence about any strategy's edge.

## C3. Binance spot order constraints

**SE-50. `OrderIntent` validation against `MarketSnapshot.filters`.**
- Source: the `exchangeInfo` filters captured in `MarketSnapshot` with its `as_of`. The filter set is recorded by hash in the `DecisionRecord`, so a replay uses the filters in force at decision time.
- `LOT_SIZE.stepSize`: quantity is floored to a multiple of `stepSize`. Exposure is never rounded up.
- `PRICE_FILTER.tickSize`: limit and stop prices are rounded to a multiple of `tickSize` in the direction that does not improve the plan's P&L. The direction per order type is part of the fill model version and is covered by tests.
- `NOTIONAL` / `MIN_NOTIONAL.minNotional`: an intent below the minimum after rounding is a `RejectionRecord` (`below_exchange_minimum`), never a silent resize.
- Any other filter present in `exchangeInfo` is either enforced or listed in the fill model as "not modelled". There is no implicit pass.
- The reference implementation is `shared/exchange_rules.py` (`check_order`, `round_to`, `plan_bracket_orders`; SE-09). Wiring it into Paper changes fills and geometry after rounding, so it is a measurement boundary (SE-69).

## C4. Which model applies where

| Context | Cost model | Fill model | Status | Who may change it |
|---|---|---|---|---|
| Paper runtime (tracker `bb7825f`) | `legacy_tracker_v1` (proposed identifier for the existing rule): flat 0.30% on `TRADE_AMOUNT_USDT` + `STOP_SLIPPAGE` 0.001 in stop fills (SE-11, SE-12) | `observed_price_v0`; touch-fill targets; stop-first; gap at observed price | In force (RUNTIME_VERIFIED, VER-11, VER-19) | Owner only: a strategy-version and measurement boundary (SE-68) |
| Paper reporting | Legacy net, labelled `net_after_modeled_cost_v1` | as above | In force | Same as above. A research-model view of Paper trades admitted after the freeze would read FORWARD_HOLDOUT outcomes and is forbidden without an OD-7 unlock (DFP:L57 @ 46578aa) |
| Research replays (A48 harness) | `a48-cost-v1` | `legacy_bar_v1`, `tracker_event_v1`, `ohlc_uncertainty_v1` | Levels 1–2 only (SE-17) | Protected research or simulation; needs OD-DF-1 for real data (DFP:L42, L113 @ 46578aa) |
| Preregistered evaluation (WP4) | Research baseline 0.40% and stress 0.60% (SE-44), once adopted | Research fill model (SE-46) | Proposed only | Owner, at preregistration (charter §5 WP3, L52) |
| Design A | Its own 0.40%/0.60% decomposition | Tuesday-open execution with deferral | Unmerged, review only | Owner decisions E1–E8 |
| Evidence Ladder admissions | STRESS + MES per position (ELP:L81 @ 46578aa) | Not specified | CONFIRMATORY-ONLY, HOLD | Owner; reconcile at WP3 (SE-19) |

Explicit statement: the legacy Paper accounting stays exactly as it is until the owner approves a change. Changing it, including removing the R4 double count, changing the notional basis, adding spread or wiring exchange rounding, is a strategy-version and measurement boundary. Results before and after such a change are never pooled, and historical counters and labels are not rewritten (OOC:L24-28, L36 @ 46578aa; `deploy/VERSION_BOUNDARY.md:L3-5 @ 46578aa`). The research model is never retrofitted onto stored Paper rows as if it had been in force.

# Part E. Evidence and reproducibility (WP1-E)

## E1. Identity chain and runtime provenance

The chain that makes a decision attributable is: `StrategyVersion` (three hashes) → resolved configuration → source commit → image → container → `DecisionRecord`. Each link has a current state.

**SE-20. Deployed-state record.** `deploy/DEPLOYED.json` (schema `tsb-deployed/1`) records what was observed running: container id, image id, image reference, state, start time, restart count and Compose `config_hash`, plus provenance and a reproducibility level L0/L1/L2. It is not deployment intent and not a reproducibility claim (DOCUMENTED_ONLY; [DEPLOYED.md](../../../deploy/DEPLOYED.md), `deploy/DEPLOYED.md:L3-28 @ 46578aa`). It matched 8 of 8 containers on 2026-10-31 (RUNTIME_VERIFIED; REP:L334 @ 5d977f2, RT-35).

**SE-21. Runtime manifests.** `ops/provenance/runtime_manifest.py` generates `RUNTIME_MANIFEST.json` (schema `tsb-runtime-manifest/1`) with a per-file `sha256`, `git_blob` and size, classified as match, assembled, unknown or dormant, plus image id, digests and labels (SOURCE_VERIFIED; `ops/provenance/runtime_manifest.py:L1-18, L93-96, L125-139, L150-167 @ 46578aa`). The recorded parity is analyzer 46/46 and signal_engine 56/56 at `ea8ae4f`, telegram 50/50 and trade_tracker 51/51 at `bb7825f`, with 8 of 23 scanner files differing (DOCUMENTED_ONLY; REP:L292 @ 5d977f2, RT-16).

**SE-22. Labels and digests.** Only the observe-mode images carry a revision label; others show `revision=unknown`, no labels or a dirty revision, and no registry digest exists (RUNTIME_VERIFIED; REP:L277-294 @ 5d977f2, RT-14, RT-15, RT-18).

**SE-23. Image content is not runtime-verified.** No running image filesystem was hashed, so "no code behaviour … is runtime-verified" (NOT_VERIFIED; REP:L293 @ 5d977f2, RT-17). Hashing image files by streaming them with `docker cp` and comparing them with the 238 per-file hashes of the manifest is feasible, but `docker cp` is not a Class A command and "needs a separate owner decision" (NOT_VERIFIED; VERA:L245-257 @ 5d977f2, VER-28; CLAUDE.md:L36 @ 46578aa). This document requests no such operation; SE-85 presents it as an owner decision.

**SE-24. Existing evidence records.**
- Evidence recorder v2 envelope: `schema`, `schema_version`, `event_id`, `event_type`, `service`, `boot_id`, `seq`, event and record times, `restated`, identity (`strategy_version`, `code_sha`, `config_hash`, `build_revision`, `phase_id`), `subject`, `state`, `payload`; deterministic `candle_id`, `candidate_id` and `event_id`; JSONL sink, one file per service per UTC day (SOURCE_VERIFIED; `shared/evidence_v2.py:L37-38, L101-119, L171-186, L303-312 @ 46578aa`). Code default off (`shared/config.py:L62-73 @ 46578aa`); on at runtime except in the scanner (RUNTIME_VERIFIED; VERA:L112 @ 5d977f2, VER-20).
- Emitted events include `candidate.analyzed`, `candidate.evaluated`, `signal.refused`, `signal.ready`, `selection.truncation`, `admission.decision`, `entry.attempt`, `trade.opened`, `trade.target_hit`, `trade.closed` (SOURCE_VERIFIED; `docs/evidence_v2/EVENT_SCHEMA.md:L58-70 @ 46578aa`).
- Research `OpportunityRecord` with `strategy_version`, `strategy_contract_hash`, `git_sha`, `accepted`, `rejection_code` (21 codes) and `rejection_detail` (SOURCE_VERIFIED; `research/foundation/opportunity.py:L11-32, L58-84 @ 46578aa`).
- No `DecisionRecord` schema and no hash chain exist (SOURCE_VERIFIED; absence result). The charter's single decision/remediation log has no schema either ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) L69).

## E2. `DecisionRecord` contract

**SE-51. Schema.** A `DecisionRecord` is a payload type carried in the evidence v2 envelope. It extends the envelope; it does not replace it.

| Field group | Fields |
|---|---|
| Identity | `decision_id` = sha256(canonical inputs + `decision_type` + `StrategyVersion` identity); `decision_type` ∈ {`candidate`, `rejection`, `opportunity_rank`, `sizing`, `order_intent`, `fill`, `position_transition`, `ledger_entry`} |
| Version | the five `StrategyVersion` fields; `cost_model_id`; `fill_model_id`; selection version for funnel decisions |
| Inputs | `candle_set_hash`s, `regime_context_hash` with `point_in_time`, `market_snapshot_hash` with `as_of` and `source`, `filters_hash`, `ledger_state_hash` for sizing |
| Runtime | `code_sha`, `image_id`, `runtime_manifest_hash`, Compose `config_hash`, `boot_id` |
| Times | `bar_close_time`, `decision_time`, `recorded_at` (SE-48) |
| Output | canonical output (`Candidate`, `RejectionRecord`, `Opportunity`, `SizingDecision`, `OrderIntent`, `Fill`, transition or `LedgerEntry`) |
| Chain | `prev_record_hash` per (service, UTC day); `record_hash` = sha256(canonical record without `record_hash`) |

**SE-52. Opportunity and rejection logs.** Every `Candidate` and every `RejectionRecord` is logged, with no sampling. Strategy-stage reason codes extend the funnel's list ([OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md)) and reuse the research `RejectionCode` names where they exist (`REJECT_REGIME`, `REJECT_ENTRY`, `REJECT_STOP_DISTANCE`, `NOT_ELIGIBLE_INSUFFICIENT_HISTORY`, `REJECT_DATA_QUALITY`). New strategy-stage codes: `incomplete_candles`, `stale_regime`, `structural_risk_exceeds_cap` (existing string), `invalid_geometry`, `t1_not_cost_feasible`, `below_exchange_minimum`, `duplicate_setup_key`, `bar_before_version_activation` (SE-36).

**SE-53. Signal and order audit trail.** `Candidate` → `Opportunity` → `SizingDecision` → `OrderIntent` (side, type, quantity, price, rounding applied, `filters_hash`) → `Fill` (quantity, price, reference price and source, *f*, *h*, *s* amounts, partial flag, `fill_time`) → position transitions (§B6) → `LedgerEntry`. Each arrow is a `DecisionRecord` that cites the parent's `decision_id`. The ledger side, including reconciliation with stored Paper results, is specified in [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) (PR-I11, PR-I13) and not repeated here.

## E3. Reproducibility requirements

**SE-54. Deterministic replay inputs.** A decision is reproducible only if all of these are retained or recoverable by hash: the closed candle sets as fetched (with source and fetch time), the `MarketSnapshot` including filters, the `RegimeContext` including macro inputs, the resolved configuration including database-held values, and the code identity. Inputs with `point_in_time = False` (the macro gate today, SE-06) are reproducible only from forward capture; such decisions are flagged as not historically replayable.

**SE-55. Replay acceptance.** Given the recorded inputs, a replay produces byte-identical `DecisionRecord` outputs and identical `record_hash` values. A mismatch is a defect of the identity chain, recorded in the discrepancy register of R5, never a tolerated difference.

**SE-56. Chain verification.** A daily verifier recomputes the chain per service and day. A missing link, a reordered `seq` or a `restated` record without a cited predecessor fails verification. The verifier is an offline tool on development data, not a scheduled production service (CLAUDE.md:L18 @ 46578aa; `docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md:L32-42 @ 46578aa`).

## E4. Scientific evidence boundaries

- **Freeze and holdout.** Everything after the 2026-08-19 freeze is FORWARD_HOLDOUT, sealed by default and excluded from discovery outcomes, labels and aggregates; unlocking is a one-way owner decision (DOCUMENTED_ONLY; `docs/research_temporal_governance.md:L19-23, L39-51 @ 46578aa`; DFP:L57 @ 46578aa; SOURCE_VERIFIED for the partition rule, `research/data_governance/governance.py:L44-60, L86-89 @ 46578aa`). Nothing in this contract reads, counts or re-costs holdout trades.
- **A29.** The Evidence Ladder remains in force with D1/D2 HOLD: horizon ≤ 365 days, ≤ 3 candidates, 20% reserve, 5% familywise false confirmation, one-sided α = 1/240, daily mark-to-market net excess endpoint with HAC (Bartlett L = 7), efficacy at day 365 only (DOCUMENTED_ONLY; OOC:L35 @ 46578aa; ELP:L66-81 @ 46578aa). The original A29 documents are local only (ELP:L17-41 @ 46578aa). Design changes here never alter these settings.
- **No attribution across versions.** Outcomes of one `StrategyVersion` never count for another, including its own lineage parent (`deploy/VERSION_BOUNDARY.md:L3-5 @ 46578aa`; OOC:L36 @ 46578aa). None of the historical samples is attributable to the deployed rules (INFERRED; ERG-G2:L21-25, L120-128 @ 0729a5f, G2-01, G2-08).
- **Defect fixes are not evidence.** Correcting W3, re-fire, the alphabetical cut or the double count changes measurement and behaviour; it does not establish a net edge ([charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md) §4, L46).

**SE-25. Version boundaries and statistical power interact.** Within 365 days the minimum detectable annualised SR at 80% power is 3.48 to 7.00 under illustrative assumptions, so the horizon is the binding constraint (INFERRED; ERG-G4:L36-38, L272-283 @ 0729a5f, G4-04). Each strategy-version boundary restarts the attributable sample for that strategy (follows from the no-pooling rule). Shipping R2, R3, R4 and the R1 selection change as separate sequential boundaries would fragment a sample that is already underpowered; bundling them prevents per-fix attribution. This trade-off is owner decision SE-83 (INFERRED).

## E5. Proposed changes

Each row has exactly one change class. "Tests" are tests to be written later; nothing was run for this document.

| ID | Change | Change class | R-item | Tests | Acceptance criteria | Owner decision |
|---|---|---|---|---|---|---|
| SE-60 | Adopt this interface, identity scheme and state machine as the design baseline | Documentation/design | R5, R8 | Not applicable | Owner review; no conflict with [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) or [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) field names | Review only |
| SE-61 | Interface types and `StrategyVersion` hashing as a library that production does not import | Safe development-only correction | R5, R8 | Canonical-JSON stability; same input → same hash; any edit in the declared closure changes `source_hash`; purity test (network, database, environment and clock access raise); import-graph test that no runtime service imports it | All tests green on synthetic fixtures; import graph unchanged for the five services | None to build; activation is separate |
| SE-62 | Adapters exposing `momentum_breakout 1.0.0` and `reversion_rsi_bb 1.0.0` over the existing functions | Safe development-only correction | R2, R8 | Golden parity on synthetic frames against `detect_trade_setup` and `_calculate_levels` (including the W3 legacy behaviour, labelled as such) | 100% identical candidates, levels and rejection outcomes on the fixture set | None |
| SE-63 | Contract hash v2: closure-based `source_hash` (adds `technical_analyzer.py`, `t1_cap.py`, `signal_identity.py`, selection and cost-booking code) computed beside the existing hash | Safe development-only correction | R5 | Mutation test per added file; the v1 hash of `current_contract()` unchanged | v1 and v2 reported side by side; `research_freeze.json` byte-unchanged | None |
| SE-64 | W3 invariant tests and policy options a, b, c behind `T1_CAP_POLICY` (default `legacy_window_v1`) | Safe development-only correction | R2 | Property tests over synthetic breakouts: reference bar closes before the decision bar; provenance fields set; ordering; fallback path; cost feasibility; default byte-identical (DFP:L87 @ 46578aa) | Every invariant of SE-40 holds for options a–c; legacy default reproduces SE-03 exactly | Activation is SE-65 |
| SE-65 | Activate a W3 option in Paper (`momentum_breakout 2.0.0`) | Strategy-version-changing correction | R2 | SE-64 suite plus boundary-entry check and the no-re-fire rule (SE-36) | Boundary entry written; first post-activation candidates carry the new identity; no pre-activation bar re-evaluated | SE-80, SE-83 |
| SE-66 | Pure position state-machine function with the transition table of §B6 | Safe development-only correction | R4, R7 | Exhaustive transition table; illegal transitions rejected; stop-and-target same observation (SE-41); gap-through; partial sums; parity with `shared/triple_barrier.py` under the legacy configuration | Parity on synthetic paths; no runtime import | None |
| SE-67 | Research cost model `research_baseline_v1` / `research_stress_v1` (SE-44 to SE-46) | Safe development-only correction | R4, R8 | Round trip 0.40%/0.60% for symmetric fills; a stop exit charged once; per-leg notional; agreement with `a48-cost-v1` on synthetic legs | Single booking holds (PR-I11) | SE-81, SE-87 to adopt |
| SE-68 | Change Paper accounting (R4): book stop slippage once, per-leg notional, optional spread | Strategy-version-changing correction | R4 | Default byte-identical; new policy charges slippage once; risk-guard input unchanged unless explicitly versioned (SE-11) | Boundary entry; legacy rows untouched; old and new never pooled | SE-82 |
| SE-69 | Exchange-filter validation and rounding of `OrderIntent` from `MarketSnapshot.filters` | Safe development-only correction | R7 | Floor to `stepSize`; tick rounding per order type; below-minimum rejection; unknown filter → explicit "not modelled" | All filter cases covered on synthetic filter sets | Wiring into Paper is a boundary under SE-82 |
| SE-70 | `DecisionRecord` payload, hash chain and offline verifier on evidence v2, default off | Safe development-only correction | R5, R6 | Deterministic `decision_id`; chain break detection; replay yields identical hashes (SE-55) | Verifier passes on synthetic days and fails on each injected break | Enabling in Paper needs owner approval |
| SE-71 | Golden replay harness for interface parity (synthetic data only) | Safe development-only correction | R5 | Byte-identical outputs across two runs and two machines | Used as the PATCH/MINOR gate of SE-38 | None |
| SE-72 | `VERSION_BOUNDARY.md` strategy-boundary template (SE-36) | Documentation/design | R5, R8 | Not applicable | Template reviewed; no entry created | Review only |
| SE-73 | Runtime image parity by hashing container files against `RUNTIME_MANIFEST.json` | Production/runtime change | R5 | Read-only procedure; identity captured before and after | Per-file match report; any mismatch stops the stream (CLAUDE.md:L45 @ 46578aa) | SE-85 |
| SE-74 | Level-3 execution calibration from a forward capture of tracker observations | Protected research or simulation | R8 | Preregistered capture spec | A48 level 3 claim supported or refuted | SE-86 |
| SE-75 | Bundled versus sequential boundaries for R1–R4 corrections | Documentation/design | R1–R4 | Not applicable | Decision recorded in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) | SE-83 |

# Part F. Owner decisions

Every item below is **OWNER DECISION REQUIRED**. No option is chosen here; [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) consolidates them.

| ID | Decision | Options and trade-offs |
|---|---|---|
| SE-80 | W3 reference policy and T1 fallback (R2) | a. Prior window: simple, but removes the cap for momentum entirely. b. `independent_swing_v1`: keeps a structural cap, needs swing detection on bars more than 20 bars old. c. No cap: explicit and simplest; T1 always 1R. Fallback when T1 is not cost-feasible: reject (fewer trades) or fixed-R fallback (keeps trades whose first target may not cover costs). |
| SE-81 | Research cost baseline and stress (SE-44) | a. Adopt 0.40%/0.60% flat. b. Adopt S4 tiered half-spread. c. Evaluate under both and report both. The stress level must also be reconciled with the Evidence Ladder STRESS + MES definition (SE-19). The account fee tier stays NOT_VERIFIED until checked. |
| SE-82 | Paper accounting (R4) | a. Keep the legacy accounting unchanged and apply the research model only in research replays. b. Add a versioned, single-booking net beside the legacy fields, as a new label policy and a boundary. c. Replace the legacy accounting at a boundary. Options b and c change the risk-guard input unless that input is held on the legacy model (SE-11); option a leaves a known conservative bias in Paper. |
| SE-83 | Boundary packaging for R1–R4 (SE-25) | a. One bundled boundary: one sample restart, no per-fix attribution. b. Sequential boundaries: per-fix attribution, several restarts inside a horizon that is already binding. |
| SE-84 | Setup-key composition | Keep the funnel's key, which includes the `StrategyVersion` identifier ([OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) F4), with the activation-minute rule of SE-36; or exclude the version from the key and rely on lineage-level uniqueness. The first keeps per-version uniqueness; the second blocks cross-version duplicates by construction. |
| SE-85 | Image-content parity (SE-73) | Authorize a read-only `docker cp` hashing procedure per service; or keep RT-17 open and limit runtime claims to configuration and recorded manifests. |
| SE-86 | Level-3 calibration (SE-74) | Declare a forward-capture Paper window and its preregistered measurements; or keep level 3 NOT_VERIFIED and treat all fill models as assumptions. |
| SE-87 | Research fill conventions | Targets: trade-through (baseline) or touch. Stops: same *s* as entries or a larger stress *s*. Latency value. Each choice changes `fill_model_id`. |
| SE-88 | Holding ceilings and stall rules per strategy (SE-43) | Keep the legacy per-timeframe values for 1.0.0 versions; declare new ceilings per holding class for new versions at preregistration; or allow thesis-only exits with no ceiling for position-class strategies. No value is proposed here. |
| SE-89 | Design A role | Benchmark only, or also an admitted candidate inside the ≤ 3-candidate limit; governed by memo items E1–E8 at `ebf8d8a`. |

# Part G. NOT VERIFIED items

| Item | Blocker |
|---|---|
| Value and generator of `freeze_strategy_contract_hash` (SE-05) | Reading the JSON data artefact and recomputing the hash are outside this phase |
| Running-image file content and effective fill model (SE-13, SE-23) | Needs the owner-gated parity operation (SE-85) |
| Account fee tier | Not recorded in any tracked file (ERG-G4:L557 @ 0729a5f) |
| Actual spreads and slippage per symbol | Measurement would need protected or production data (ELP:L48 @ 46578aa, U4) |
| Collation used by `ORDER BY symbol` | Database setting, not in tracked source (ERG-G3:L189 @ 0729a5f); owned by [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) |
| Realized economic impact of W3, re-fire and the double count | Requires holdout outcomes (OD-7) |

# Part H. Inconsistencies recorded

- Two W3 corrections are documented: the A45 prior-window rule and the A46 G1 swing rule (CONTRADICTORY; ERG-G1:L192-195 @ 0729a5f, G1-10). SE-80 lists both, and shows that the prior-window rule is a no-op cap for momentum.
- W3 severity differs between A42 and A45 (CONTRADICTORY; REP:L1486 @ 5d977f2, CON-33).
- Code and runtime strategy labels differ, and the runtime label predates the rules (CONTRADICTORY; SE-08).
- A47 reports zero implementation defects, while A48 lists defects (CONTRADICTORY; REP:L1487 @ 5d977f2, CON-34).
- Half-spread values conflict across cost sources (CONTRADICTORY; REP:L1498 @ 5d977f2, CON-45).
- The cost-constant line numbers differ by commit: `FEE_ROUNDTRIP_PCT` is at L88-90 at `ea8ae4f` and L90-92 at `bb7825f`. Both are correct for their commits; the audit's EXE-13 cites the later layout.
- `TIMEFRAMES_LL` (`15m,4h,1d`) is defined but not read; the runtime set comes from `TIMEFRAMES` (SOURCE_VERIFIED; `shared/config.py:L36, L75 @ ea8ae4f`; RUNTIME_VERIFIED, VER-06).

# Part I. Closure conditions for this document's items

- R2: closed only when SE-64 tests pass on a development branch **and** the owner has decided SE-80, with any activation recorded as a boundary (SE-65). Activation is not required for the design item to close.
- R4: closed only when SE-67 and SE-68 tests pass and SE-82 is decided. Under option a the defect remains, documented as a known conservative bias.
- R5 (strategy identity part): closed when SE-61, SE-63 and SE-70 pass and SE-85 is decided.
- R8 (contract part): closed when every hypothesis in §B5 has a complete `StrategyContract` before evaluation. Its economic part stays INCONCLUSIVE until an authorized WP4 evaluation reports.
