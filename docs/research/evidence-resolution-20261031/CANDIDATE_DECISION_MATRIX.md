# Candidate decision matrix (ERG-01 workstream G5 and final decision framework)

**Phase:** ERG-01 Evidence Resolution Gate. Documentation-only and read-only.
**Pinned tree:** `5d977f2` (= `main` `eba90dd` plus the 2026-10-31 audit package; `git diff --name-only eba90dd 5d977f2` lists only files under `docs/audits/2026-10-31-trading-system-review/`, so every other file cited `@ 5d977f2` is identical at `eba90dd`). Design A was read on `feature/design-a-v1` at `ebf8d8a` with `git show`.
**Audit baseline:** finding IDs (HIS-07, HIS-09, STR-09, ECO-05, GOV-02 and others) are the 2026-10-31 historical baseline in [REVIEWER_EVIDENCE_PACK.md](../../audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md) and [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](../../audits/2026-10-31-trading-system-review/RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md). They are kept apart from what this workstream re-read.

**Upstream workstreams (sources; this file does not contradict them):**

| Workstream | File | Conclusion used here |
|---|---|---|
| G1 | [HIS05_COMPARABILITY.md](HIS05_COMPARABILITY.md) | HIS-05 is MATERIALLY DIFFERENT from the current momentum setup and from the successor concept (G1-01, G1-02); no successor specification exists (G1-09); two W3 corrections are documented (G1-10) |
| G2 | [VERSION_EVIDENCE_LINEAGE.md](VERSION_EVIDENCE_LINEAGE.md) | no historical result is attributable to the deployed `ea8ae4f` / `bb7825f` rules (G2-01, G2-08); earlier samples are different implementations, not replications (G2-07) |
| G3 | [DEFECT_IMPACT_ASSESSMENT.md](DEFECT_IMPACT_ASSESSMENT.md) | W3 and the alphabetical cut are MECHANICALLY INFERRED, economic impact UNKNOWN (G3-01, G3-02); each correction is a new strategy version with no outcome evidence (G3-09); the contract hash does not detect two of the corrections (G3-08) |
| G4 | [POWER_AND_HORIZON_FEASIBILITY.md](POWER_AND_HORIZON_FEASIBILITY.md) | 365-day MDE about SR_ann 3.48–7.00 (G4-04); the horizon, not alpha, is binding (G4-06); a per-trade edge is detectable only if it implies SR_ann ≥ about 3.5 (G4-07); an INCONCLUSIVE rule is PROPOSED, not in force (G4-13, §9) |

**Method and limits.**
- Only tracked Markdown, Python source and governance text were read, with `git show`, `git log`, `git grep`, `sed` and `grep`. Nothing was executed. No data artefact, result dump, CSV or JSON output was opened.
- No FORWARD_HOLDOUT outcome, count or timestamp after the 2026-08-19 research freeze (instant recorded in `research_freeze.json`) is read or reproduced. Counts from documents whose data window is not shown to end before the freeze are written as "count withheld (window not verified pre-freeze)".
- The arithmetic in §7 is hand arithmetic on governance constants, source-verified stop caps and hypothetical values; no variance, turnover, Sharpe ratio, win rate or correlation is estimated or invented.
- Literature is cited only as general, non-repository knowledge, and labelled so. Nothing in it is taken to hold in this market net of costs.

> **This documentation phase does not authorize selecting, pre-registering or testing any hypothesis.** It ranks nothing for admission, consumes no alpha and changes no parameter. Every option below is framed for an owner decision.

## Contents
- [1. Bottom line](#1-bottom-line)
- [2. The two candidates as given](#2-the-two-candidates-as-given)
- [3. Candidate B: Derived Momentum Successor](#3-candidate-b-derived-momentum-successor)
- [4. Candidate C: Regime-Filtered Trend-Pullback](#4-candidate-c-regime-filtered-trend-pullback)
- [5. Is Candidate C distinct from Design A?](#5-is-candidate-c-distinct-from-design-a)
- [6. Shared constraints: multiple testing and A29 slots](#6-shared-constraints-multiple-testing-and-a29-slots)
- [7. Cost break-even arithmetic](#7-cost-break-even-arithmetic)
- [8. Decision matrix](#8-decision-matrix)
- [9. Recommendation](#9-recommendation)
- [10. Findings register (G5)](#10-findings-register-g5)
- [11. NOT VERIFIED items](#11-not-verified-items)
- [12. Inconsistencies and observations](#12-inconsistencies-and-observations)

## 1. Bottom line

- **G5-01 · INFERRED.** Neither candidate has any repository evidence attributable to it. Both are concepts with no tracked specification (B: G1-09; C: no document found, §4.2). Adjacent evidence is either inconclusive (Phase 3 momentum, HIS-09, CI containing 0) or concerns different implementations whose results do not transfer (G1-03, G2-08).
- **G5-02 · INFERRED.** Candidate B is a new strategy version, not a continuation of the deployed momentum setup. Each of its corrections (geometry, selection, timeframe set) is a declared version boundary (G3-09), so it starts with no outcome evidence and inherits no claim.
- **G5-03 · INFERRED.** Candidate C is materially different from Design A in signal type (a pullback entry inside a trend versus a trend-state filter), universe (multi-asset versus BTC/USDT only) and decision frequency. It overlaps Design A, the HIS-07 BTC regime filter and A45 H1 in its macro-regime component. Whether that overlap is nesting cannot be decided until C's regime filter is specified (§5).
- **G5-04 · INFERRED.** Under the A29 design as documented, neither candidate is confirmable at a plausible effect size within 365 days (G4-06, G4-07). The constraint is common to both. It discriminates between them only through executable trade frequency: B can plausibly reach more trades than C, so it fails the constraint by less, but only under a per-trade endpoint that the owner has not adopted (G4 Q2).
- **G5-05 · INFERRED.** At 0.40% and 0.60% round trip, a trade must earn at least 0.40% or 0.60% gross to break even. At the source-verified stop caps that is 0.08R / 0.12R for 4h (R ≤ 5%) and 0.133R / 0.20R for 1d (R ≤ 3%), and more for any smaller R (§7). Candidate C's lower friction per year is an unproven design objective: turnover has never been reported for any study (HIS-19).
- **G5-06 · INFERRED.** The decision matrix (§8) has no dominant option between B and C. B is stronger on data availability and engineering effort, weaker on distinctness and governance risk; cost robustness is unfavourable for B and not determinable for C; they tie (both unfavourable) on evidence support and on power feasibility.
- **G5-07 · INFERRED. Recommendation: INCONCLUSIVE.** Existing evidence cannot resolve B versus C. The choice depends first on owner decisions that are not evidence questions: the horizon and endpoint (G4 Q1, Q2, Q6; OD-DF-2), dataset permission (OD-DF-1, `DatasetPermission`), capacity and book design (G4 Q4), and the disposition of Design A within the A29 slot budget. If the 365-day daily-endpoint design stays unchanged, the evidence-consistent option for the confirmatory track is D in its **pause** form, not a permanent stop (§9).

## 2. The two candidates as given

Both are concepts stated in the ERG brief. Nothing below selects, tunes or tests a parameter.

| Element | Candidate B: Derived Momentum Successor | Candidate C: Regime-Filtered Trend-Pullback |
|---|---|---|
| Idea | 4h/1d breakout continuation | medium-term trend continuation, entered after a pullback |
| Direction and venue | long-only spot (as the current bot) | long-only spot |
| Exits | corrected exit geometry, e.g. an independent swing T1 cap (A46 G1, `T1_CAP_POLICY=independent_swing_v1`) | not specified |
| Asset selection | corrected; no alphabetical cut | not specified; a 50-asset universe is **not** assumed |
| Regime handling | not specified beyond the current `classify_regime` routing (STR-09) | macro regime filtering, form not specified; EMA200 is **not** assumed |
| Entry parameters | not specified (G1-09) | not specified; RSI 40–50 and ATR 2 are **not** assumed |
| Friction | not stated | reduced transaction friction as an **unproven** design objective |
| Identity | frozen version identity; no inherited profitability claims | not specified |
| Repository specification | none (G1-09 · NOT_VERIFIED) | none found (G5-08 · NOT_VERIFIED, §4.2) |

## 3. Candidate B: Derived Momentum Successor

### 3.1 Economic mechanism

- **General, non-repository knowledge.** The time-series momentum literature reports that an asset's own past return over weeks to months predicts its next returns in diversified futures. Breakout rules are one practical way to express that trend persistence. That literature does not show that a 4h/1d breakout rule on Binance Spot altcoins earns a positive return net of 0.40% round trip, and this document does not assume it.
- **What the repository's own literature review records** (DOCUMENTED_ONLY):
  - crypto momentum is horizon-sensitive, positive at up to about 2 weeks and reversing at 4 weeks or more (Dobrynskaya, as cited); it is concentrated in large, liquid coins and crash-prone (`docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md:L53-57 @ 5d977f2`);
  - the classic time-series momentum alpha is contested and largely a volatility-scaling effect (same file, L33-34);
  - the deployed setup's rationale "is weakest at its own horizon"; momentum evidence is strongest at days to weeks in liquid large caps, while at 15m/4h the literature shows both momentum and reversal (`docs/a45/A45_SETUP_RESEARCH.md:L181 @ 5d977f2`).
- **G5-09 · INFERRED.** Dropping 15m moves B toward the horizon the literature favours, but the 4h leg remains in the mixed-evidence zone, and a 20-bar breakout trigger is not the trailing-return sign rule that the literature tests. A45's own track 2 proposes 1d time-series momentum "with **no** intraday breakout trigger" (`docs/a45/A45_SETUP_RESEARCH.md:L192 @ 5d977f2` · DOCUMENTED_ONLY). B keeps the trigger, so it is not that track.

### 3.2 Historical evidence in this repository, and contradictions

| Evidence | What it says | Bearing on B | Class |
|---|---|---|---|
| Phase 3 momentum (HIS-09) | n 162, net expectancy +0.123% with 95% CI [−0.433%, +0.679%], PF 1.10, NO-GO (`docs/phase3_entry_hypothesis_review_2026-08-17.md:L15 @ 5d977f2`). Window 2026-07-20 → 08-17, pre-freeze (G2 §3.2) | June predicates (blob `7755075`), no regime gate, legacy stop, all timeframes, pre-`c4a623c` exits: a different implementation (G2-08). Inconclusive, not negative | HISTORICAL_REPORTED |
| Phases 5, 6, 9 (HIS-10 to HIS-12) | the same cohort reused (HIS-13); every net-positive figure non-robust (HIS-42) | no independent information beyond HIS-09 | HISTORICAL_REPORTED |
| Canary A-R2 (HIS-14) | 88 Layer-2 trades are reversion; REFUTED | not momentum evidence | HISTORICAL_REPORTED |
| 9-year target study (HIS-05) | legacy mean-reversion score entry | MATERIALLY DIFFERENT from B (G1-02); says nothing about breakout entries (G1 §8) | INFERRED (G1) |
| Cross-sectional momentum (HIS-07) | long/short weekly; 94% of P&L from the short leg; long-only ≈ market (`S4_PHASE1_SCIENTIFIC_COMPARISON.md:L16 @ 5d977f2`) | different mechanism (relative ranking, weekly rebalance, short leg not executable) | HISTORICAL_REPORTED |
| S4 Phase 1 ranking | "Existing 15m/4h strategy + corrected T1": "none demonstrated (AUC ≈ 0.50)", **BASELINE ARM ONLY**, "evaluate the T1 fix as a correction, never as an edge" (`S4_PHASE1_SCIENTIFIC_COMPARISON.md:L65 @ 5d977f2`) | the closest documented ranking of a B-like design: baseline, not a candidate | DOCUMENTED_ONLY |
| A45 H1–H3 | market-state gate, extension cap, slot volume: specified, not executed; "second-order gates" that "cannot create an edge, only shift frequency" (`docs/a45/A45_SETUP_RESEARCH.md:L136-152, L182 @ 5d977f2`). Frequency effects: count withheld (window not verified pre-freeze) | refinements of the same family; any of them inside B would be an additional researcher choice | DOCUMENTED_ONLY |
| A46 G1–G3 | G1 independent swing cap; G2 cost-feasible target; G3 volatility-consistent entry; "geometry v2 = G3 entry + G1 targets" as the one future geometry candidate; prospective power "inadequate" or "probably inadequate" (`docs/a46/A46_TRADE_GEOMETRY.md:L123-125, L148-158 @ 5d977f2`) | B's "corrected exit geometry" is G1 at minimum; adding G3 makes it geometry v2 | DOCUMENTED_ONLY |
| Current momentum outcomes | sealed FORWARD_HOLDOUT; never read (STR-25) | no accessible evidence either way | NOT_VERIFIED (by governance) |

**Contradictions that B must resolve before any specification (G5-10 · CONTRADICTORY):**
- two W3 corrections are documented (A45 L191: prior 20 bars, excluding the current bar; A46 G1: confirmed swing high), G1-10;
- W3 severity is labelled differently in A42 and A45 (G3-10);
- `main` carries `T1_CAP_POLICY` but the documented-deployed analyzer `ea8ae4f` does not (G3-11).

### 3.3 Distinctness from previously tested hypotheses

- **G5-11 · INFERRED. Low.** B keeps the breakout-continuation entry family that the deployed setup (STR-07), the June predicates (HIS-09, HIS-14) and the A45/A46 work all share. Its changes are corrections (geometry, selection) and a narrowing (4h/1d). These are material for **version identity** (G3-09) but they do not introduce a new economic mechanism.
- "Derived" also means that B's design choices are made after seeing the family's pre-freeze results. Under the temporal-governance taxonomy that the Design A spec cites (`PRE_EXISTING`, `DISCOVERY_DERIVED` or `EXTERNAL_THEORY`; `docs/strategy/DESIGN_A_SPEC_v1.0.md:L79-86 @ ebf8d8a` · DOCUMENTED_ONLY), B would most plausibly be declared `DISCOVERY_DERIVED`. The declaration is an owner decision; it is not made here (INFERRED).

### 3.4 Data requirements

| Route | Requirement | Status | Class |
|---|---|---|---|
| Exploratory history (D1) | a dataset with a recorded `DatasetPermission`: licence cleared, holdout excluded, a named reference (`research/mechanisms/simulate.py:L33-44 @ 5d977f2`) | "Today no dataset has one" (A18/A19 licence HOLD); OD-DF-1 is proposed, not decided (`docs/governance/DEVELOPMENT_FIRST_POLICY.md:L42, L113 @ 5d977f2`) | SOURCE_VERIFIED (code, policy text) |
| Pre-freeze vs prospective | history must end strictly before the freeze; all of it is research-exposed (`S4_PHASE1_SCIENTIFIC_COMPARISON.md:L69 @ 5d977f2`) | so history can only qualify, never confirm | DOCUMENTED_ONLY |
| Universe without the alphabetical cut | a point-in-time universe definition; S4's top-20 point-in-time universe is defined for H1/H2, not for the breakout setup (G1 §5) | not specified | NOT_VERIFIED |
| Prospective Paper (D2) | an owner-declared window and a version boundary (`DEVELOPMENT_FIRST_POLICY.md:L43 @ 5d977f2`) | not declared | DOCUMENTED_ONLY |
| Non-executed signals | a calibrated counterfactual replay (A46-F prerequisite 2; `docs/a46/A46_TRADE_GEOMETRY.md:L166-168 @ 5d977f2`) | calibration not done | DOCUMENTED_ONLY |

### 3.5 Expected trade frequency (ranges and stated assumptions only)

- **Capacity bound (G4-08).** With 2 positions, executable trades a year n ≤ 2 · 8760 · occupancy / h̄, where h̄ is the mean holding time in hours. The 4h and 1d time stops are maxima of 96 h and 240 h (G4-08), so h̄ ≤ 96 h or ≤ 240 h.
- **Implication (INFERRED).** At full occupancy the capacity bound is at least 182.5 trades a year for a 4h-only book and at least 73 for a 1d-only book, and higher if trades exit before the time stop. These are bounds, not forecasts.
- **Supply.** Signal supply is regime-gated (bullish only, STR-09), so it varies with the market state and can be near zero for long periods (INFERRED). Measured signal rates exist only in documents whose window is not verified pre-freeze: count withheld (window not verified pre-freeze).
- **Range stated (G5-12 · INFERRED).** From near zero in non-bullish regimes up to the capacity bound (≥ 73 to ≥ 182.5 a year at full occupancy; more with early exits), divided further if up to 3 candidates share the 2 slots (G4-09). Realized n_eff at half the planned value cuts power from 0.80 to 0.43 (G4-11).

### 3.6 Execution realism

- A47 and A48 establish level 1 (mathematical correctness) and level 2 (agreement with the Paper tracker) only; **level 3 (real-world execution validity) is not established** (`docs/a47/A47_EXECUTION_REALISM.md:L9 @ 5d977f2`; `docs/a48/A48_REPLAY_FIDELITY.md:L23 @ 5d977f2` · DOCUMENTED_ONLY).
- B depends on triggered stop fills, where the replay is documented as optimistic at the level and on gaps (HIS-32 · DOCUMENTED_ONLY). If B adopts A46 G3 (limit entry at L + 0.75 ATR), fill rates are unknown: "no real price paths, so fill rates under G3 are unknown" (`docs/a46/A46_TRADE_GEOMETRY.md:L139-142 @ 5d977f2` · DOCUMENTED_ONLY).
- Stop slippage is charged twice in the tracker, so a stop exit costs about 0.40% (G3-04): conservative in direction, size UNKNOWN.

### 3.7 Cost sensitivity

See §7 for the arithmetic. For B specifically (INFERRED):
- at the 4h cap (R = 5%) the 0.40% / 0.60% round trip is 0.08R / 0.12R; at the 1d cap (R = 3%) it is 0.133R / 0.20R; every trade with a smaller R carries more cost per R, because the stop is at least 1 ATR below entry and the cap only rejects wider risk (`shared/signal_stop.py:L38-45 @ 5d977f2` · SOURCE_VERIFIED);
- a T1-only winner can be a net loser when T1 is small: A46 finds the T1→break-even path net-negative below a T1 of about 0.275% (20 bps) or 0.376% (30 bps) (`docs/a46/A46_TRADE_GEOMETRY.md:L81 @ 5d977f2` · DOCUMENTED_ONLY);
- at high turnover the annual drag is large relative to capital: n · c / 10 with 2 × $50 on $500 (G4-12), for example 29.2% / 43.8% of capital a year at 730 trades (§7.3).

### 3.8 Statistical feasibility (from G4)

- Under the governed daily endpoint, any candidate needs a true SR_ann of about 3.48 (normal theory, lrv 1) to 7.00 for 80% power at 365 days (G4-04); for SR 0.5–2 power is at most 0.016–0.262 (G4-05).
- Under a per-trade endpoint (not adopted; G4 Q2), detectability requires (μ/σ) · √n_eff ≥ 3.48–4.04 (G4-07). B's higher feasible n is the only arithmetic route to that bound among the two candidates (§7.4), and G4's §8 verdict places +0.3% to +0.5% per trade at σ ≈ 1–1.5% with a few hundred weakly dependent trades "within arithmetic reach". Whether B has such σ, n and dependence is NOT_VERIFIED.
- **G5-13 · INFERRED.** B's feasibility is therefore conditional on two owner decisions (endpoint, and the authorised route to planning inputs, G4 Q7), not on evidence.

### 3.9 Engineering complexity

| Piece | Status | Class |
|---|---|---|
| `shared/t1_cap.py` (`independent_swing_v1`) | exists, dormant; switching it "is a declared strategy-version boundary"; absent from the documented-deployed analyzer `ea8ae4f` (G3-11) | SOURCE_VERIFIED (dormant) |
| `shared/trade_geometry.py` (A46 engine, G1–G3) | exists, research-only; documented as unimportable in the `ea8ae4f` images (STR-37) | SOURCE_VERIFIED; STR-37 INFERRED |
| `shared/setup_diagnostics.py` (A45 gates) | pure functions, "DISABLED specifications" (`shared/setup_diagnostics.py:L1-14 @ 5d977f2`) | SOURCE_VERIFIED |
| Selection fix for the alphabetical cut | not implemented on any commit read (G3-02) | SOURCE_VERIFIED (absence) |
| Version identity | the contract hash does not register the T1 policy switch or the selection fix (G3-08); identity must come from a declared boundary record | INFERRED (G3) |

- **G5-14 · INFERRED. Moderate.** Most geometry pieces exist; the selection fix, the image build and validation, the boundary record and the counterfactual calibration do not. Existing code is counted only as lower **future** effort. Its past cost is not a criterion.

### 3.10 Governance risks

- **Inherited-claim risk.** B is the closest relative of the running Paper strategy. Pre-freeze momentum figures (HIS-09) and any later look at the sealed holdout would invite pooling or retroactive attribution, both prohibited (`deploy/VERSION_BOUNDARY.md:L3-5 @ eba90dd`, via G3 §6.3 · DOCUMENTED_ONLY).
- **Holdout.** The sealed FORWARD_HOLDOUT holds outcomes of the defective implementation (G3-05). It cannot be used to design, tune or pre-screen B (OD-7; GOV-04).
- **HOLDs.** D1/D2 HOLD remains for governed confirmation (GOV-02); the HOLD scope wording differs across documents (CON-36).
- **Slot.** Pre-registering B would consume one of 12 admissions at α = 1/240 (§6).

## 4. Candidate C: Regime-Filtered Trend-Pullback

### 4.1 Economic mechanism

- **General, non-repository knowledge.** Trend-following and time-series momentum studies in other asset classes report persistence of medium-term trends. A separate literature reports short-horizon reversal. A pullback entry inside a trend combines the two, buying a short-term dip while betting on the longer trend. Neither literature establishes that the combination earns a net return on Binance Spot at 0.40% round trip, and this document does not assume it.
- **What the repository records for crypto** (DOCUMENTED_ONLY): momentum at up to about 2 weeks, insignificant at 2–4 weeks, **reversal at 4 weeks or more** (Dobrynskaya, as cited in `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md:L54 @ 5d977f2`).
- **G5-15 · INFERRED.** "Medium-term" is therefore not a neutral word for C. If it means weeks, C sits on the same horizon as S4 M1 and A45 track 2. If it means months, the crypto evidence the repository cites points the other way. C's specification must state the horizon and its own mechanism argument, as the Design A memo already requires of a 200-day filter: "It is a regime filter, not that mechanism" (`docs/strategy/DESIGN_A_PROFITABILITY_DECISION_MEMO.md:L124 @ ebf8d8a` · DOCUMENTED_ONLY).
- **Long-only.** A long/cash trend rule is "mostly timed beta", so its baseline must be buy-and-hold, not cash (`docs/strategy/S4_MECHANISM_COMPARISON.md:L25, L76 @ 5d977f2` · DOCUMENTED_ONLY).

### 4.2 Historical evidence in this repository, and contradictions

A `git grep` for pullback, trend-continuation, TSMOM, EMA200 and SMA200 across tracked Markdown and Python found the items below. **No tracked document specifies Candidate C or reports a trend-pullback result** (G5-08 · NOT_VERIFIED; blocker: no such document exists).

| Evidence | What it says | Bearing on C | Class |
|---|---|---|---|
| `research/skill_application/scripts/ma2050_uptrend_bt.py:L1-15 @ 5d977f2` (added `4e3eb0a`, 2026-09-27, "preserve research scripts") | a 1d MA20/MA50 "strong uptrend" rule with a trend variant and a **pullback** variant (low touches MA20 within a tolerance, close back above), exit below MA50, fees 0.3% / 0.6% round trip | the only pullback rule found in tracked code. No tracked Markdown result exists; its output is an untracked CSV, not opened. Run date, data window and outcome are NOT_VERIFIED | SOURCE_VERIFIED (code); outcome NOT_VERIFIED |
| `analyzer/MODEL_FROZEN_SPEC.md:L5-16 @ 5d977f2` (HIS-07's frozen model, 2026-06-08) | cross-sectional long/short momentum **with a regime filter: trade only if BTC > EMA50 and BTC > EMA200, else cash** | a BTC trend filter has already been used in this repository; its own contribution is not isolated in any tracked record | HISTORICAL_REPORTED; isolation NOT_VERIFIED |
| Same file, L31-32 | "rejected definitively": RSI, Bollinger, Stoch, EMA, volume and similar OHLCV indicators, AUC ≈ 0.50 | concerns indicator signals in the legacy research, not a trend-pullback combination; C must say why its combination differs | HISTORICAL_REPORTED |
| Legacy score (IND-07) | RSI bands < 30 / 30–40 / 40–50 carried weights 1.5 / 1.0 / 0.3 (`docs/audits/2026-10-31-trading-system-review/STRATEGIES_INDICATORS_CALIBRATION.md:L279 @ 5d977f2`); that family showed AUC ≈ 0.50 (HIS-03) | an RSI 40–50 condition is not new here, although it was a score component, not a pullback trigger | SOURCE_VERIFIED (audit); HISTORICAL_REPORTED |
| Regime filters on other implementations (HIS-24) | the pre-freeze audit lists "regime" among failed directions; Phases 3–6 list regime selection as failed | legacy score path and June predicates: non-transferable (G2-08) | HISTORICAL_REPORTED |
| Phase 3 regime cells (HIS-09) | bullish cell −0.085% (n 73), volatile +0.862% (n 55, labelled post-hoc) (`docs/phase3_entry_hypothesis_review_2026-08-17.md:L27-28 @ 5d977f2`) | pooled over both entry types and the legacy regime detector, which does not map onto any current regime (G2-08 point 2) | HISTORICAL_REPORTED |
| A45 H1 market-state gate | BTC 3-day change ≥ 0; "its effective n is too small for any credible test within 365 days" (`docs/a45/A45_SETUP_RESEARCH.md:L142, L158 @ 5d977f2`) | the same structural problem applies to any market-wide regime filter in C | DOCUMENTED_ONLY |
| S4 M1 TSMOM / Phase 1 H1 | specified; NOT TESTED; code refuses non-synthetic data (HIS-15) | nearest documented trend hypothesis; no market evidence | SOURCE_VERIFIED (HIS-15) |
| Design A | synthetic only; profitability UNKNOWN (HIS-16, HIS-43) | no market evidence for the BTC trend filter either | SOURCE_VERIFIED (HIS-16) |

**Contradictions and gaps (G5-16 · INFERRED):**
- the horizon conflict in §4.1;
- the register line for HIS-07 does not mention the BTC EMA50/EMA200 regime filter recorded in `MODEL_FROZEN_SPEC.md:L16` (an omission, §12);
- `analyzer/research/entry_methodology_report.md:L106 @ 5d977f2` labels some momentum names with "pullback entry after a rise" as a qualitative note; it is not a test, and its numbers are not reproduced (count withheld (window not verified pre-freeze)).

### 4.3 Distinctness from previously tested hypotheses

- **G5-17 · INFERRED. Moderate.** The pullback-in-trend entry has no tracked result, so in that sense it is untested. But its two components are not new:
  - the **trend** component overlaps S4 M1 / H1 and Design A;
  - the **macro regime** component overlaps HIS-07's BTC filter, A45 H1 and Design A.
- **Relative to the current router (INFERRED).** `classify_regime` sends bullish states only to the breakout setup and sideways states only to the reversion setup (STR-09). A dip-buy inside a bullish regime is a combination the deployed code never emits, so C is distinct from both current setups. That distinctness is structural and says nothing about returns.

### 4.4 Data requirements

| Need | Status | Class |
|---|---|---|
| Daily (or 4h) klines for a multi-asset universe, ending strictly before the freeze, with a recorded `DatasetPermission` | none recorded; OD-DF-1 proposed (§3.4) | SOURCE_VERIFIED (policy, code) |
| A point-in-time universe (listing age, liquidity, delisted assets kept) | not specified; S4 drafted one for H1/H2 (`S4_PHASE1_SCIENTIFIC_COMPARISON.md:L71 @ 5d977f2`) | DOCUMENTED_ONLY |
| Macro regime inputs | only **price-derived** inputs can be replayed. CoinGecko BTC.D / USDT.D are not point-in-time, so a gate built on them cannot be replayed (ECO-02) | INFERRED (ECO-02) |
| Prospective route | no current Paper path computes a pullback setup; a declared D2 window would need a new implementation and an owner-declared window | INFERRED |

### 4.5 Expected trade frequency (ranges and stated assumptions only)

- C's holding time is unspecified. **Assumption, for illustration only:** a mean hold of 2 to 8 weeks (336–1344 h). The G4-08 bound with 2 positions at full occupancy then gives at most about 52 down to 13 trades a year.
- A regime filter lowers occupancy during non-qualifying regimes, which lowers the bound further (INFERRED). Separate virtual books or more slots would scale it; that is the open book-design question (G4 Q4).
- **Range stated (G5-18 · INFERRED).** About 0 to the low tens of executable trades a year per 2-slot book under these assumptions. The effective number is lower still: cross-asset correlation and a market-wide regime filter make the sample closer to the number of independent trend episodes (`docs/strategy/S4_MECHANISM_COMPARISON.md:L27 @ 5d977f2`; `docs/strategy/DESIGN_A_SPEC_v1.0.md:L707 @ ebf8d8a` · DOCUMENTED_ONLY).

### 4.6 Execution realism

- Level 3 is not established for any execution model in the repository (§3.6).
- If C decides on closed daily bars and fills at a scheduled next open, it avoids the triggered-fill optimism the replay audits document, as the Design A memo argues for scheduled orders (`DESIGN_A_PROFITABILITY_DECISION_MEMO.md:L34-46 @ ebf8d8a` · INFERRED there). Any triggered stop in C would carry the same gap (HIS-32). The order type is unspecified, so the net effect is NOT_VERIFIED.
- A position-holding design may need a target-position order path, which the Paper engine lacks today (`docs/lab/STRATEGY_LAB_ARCHITECTURE.md:L25-29 @ 5d977f2` · DOCUMENTED_ONLY).

### 4.7 Cost sensitivity

- The per-trade break-even is the same as for B: a gross edge of 0.40% or 0.60% per round trip (§7.1).
- C's stops are unspecified. A wider stop lowers cost per R but raises the loss per stopped trade in percent; the net effect on viability is unknown (INFERRED).
- Fewer trades lower the **annual** drag (n · c / 10 of capital: about 0.5% to 2.1% a year at 12–52 trades and 0.40%, §7.3). That is the content of "reduced friction", and it is unproven: no study in the repository reports turnover (HIS-19).

### 4.8 Statistical feasibility (from G4)

- The daily-endpoint requirement (SR_ann ≥ about 3.48–7.00 at 365 days) is the same for every candidate (G4-04).
- Under a per-trade endpoint, C's lower n makes the bound harder: at 13–52 trades a year the per-trade signal-to-noise μ/σ must be at least about 0.48–1.12 (deff 1; §7.4), against about 0.13–0.15 at 730 trades.
- If C is benchmarked against buy-and-hold of its universe, as the repository requires of long/cash trend rules, the endpoint becomes an active return, whose signal is a fraction of the total return (INFERRED; no value is estimated).
- **G5-19 · INFERRED.** C is at least as horizon-bound as B, and more so under any per-trade endpoint.

### 4.9 Engineering complexity

| Piece | Reusable? | Class |
|---|---|---|
| `research/mechanisms/` (`TimeSeriesMomentum`, `CrossSectionalMomentum`, `simulate.run` with `DatasetPermission`, a cost floor) | the permission gate, cost model and harness; no pullback signal (`research/mechanisms/signals.py:L53, L97 @ 5d977f2`) | SOURCE_VERIFIED |
| Design A package (`research/design_a/`, `feature/design-a-v1` @ `ebf8d8a`) | data contract, timing, candle integrity and ledger patterns; BTC-only weekly long/cash, so the signal is not reusable | SOURCE_VERIFIED (branch) |
| `shared/regime.py` (`classify_regime`), `MarketStateGate` (disabled) | per-symbol and BTC 3-day regime logic exist; C's macro filter is undefined | SOURCE_VERIFIED |
| Pullback trigger, exits, stops, universe, tests, Paper wiring | none exist | SOURCE_VERIFIED (absence) |

- **G5-20 · INFERRED. High** relative to B: the entry, exit, universe and regime pieces are all new.

### 4.10 Governance risks

- A hypothesis-source declaration is required (`PRE_EXISTING`, `DISCOVERY_DERIVED` or `EXTERNAL_THEORY`). The BTC trend-filter component is research-exposed here (`DESIGN_A_SPEC_v1.0.md:L719 @ ebf8d8a` · DOCUMENTED_ONLY), so C cannot be presented as an independent discovery in that component.
- Running C next to Design A would spend two admissions on correlated hypotheses (§6).
- D1/D2 HOLD and the sealed holdout apply exactly as for B (GOV-02, GOV-04).

## 5. Is Candidate C distinct from Design A?

Design A was read at `ebf8d8a` on `feature/design-a-v1` (`docs/strategy/DESIGN_A_SPEC_v1.0.md`, `docs/strategy/DESIGN_A_PROFITABILITY_DECISION_MEMO.md`). Both files are absent from `5d977f2`, so they are cited as code-formatted paths.

| Dimension | Design A v1.0 | Candidate C (concept) | Reading |
|---|---|---|---|
| Universe | BTC/USDT spot only; no cross-sectional rotation (spec F1–F2, `L95-96` · SOURCE_VERIFIED) | a multi-asset spot universe, unspecified (a 50-asset universe is not assumed) | different |
| Decision frequency | weekly: Monday 00:00 UTC plus 30 s, on the Sunday close (F7, `L107`) | unspecified; per-asset pullback triggers imply decisions on every 1d (or 4h) bar | different (INFERRED) |
| Signal type | a **trend-state filter**: LONG iff the Sunday close > SMA200, equality FLAT, no other indicator (F5–F6, `L103-105`) | a **pullback entry inside a trend**, gated by a macro regime filter of unspecified form | different in kind. C's regime gate may be the same kind of object as Design A's whole rule |
| Exposure | 100% BTC or cash (F9, `L114`) | per-asset positions sized by the book (2 × $50 under current Paper capacity, unless G4 Q4 decides otherwise) | different |
| Exits | the filter flip only | stops, targets, time limits: unspecified | different |
| Costs | BASELINE 0.20% per side (≈ 0.40% round trip), STRESS 0.30% per side (≈ 0.60%) (spec §10, `L526-527`) | 0.40% / 0.60% round trip planning values (§7) | identical rates; annual drag differs with turnover |
| Benchmark | B1 BTC buy-and-hold primary; B0–B5 defined, never computed (spec §14, `L656-676`) | none; repository practice requires buy-and-hold of the same universe (`S4_MECHANISM_COMPARISON.md:L76 @ 5d977f2`) | C would also need a control that isolates the regime filter (INFERRED) |
| Evidence status | synthetic only; profitability UNKNOWN; outcome classification NOT DEFINED (spec `L730`; memo `L14-20`) | no specification and no evidence (G5-08) | equal: none |
| Code | offline package and 83 synthetic tests (HIS-16) | none | different engineering state |
| Research exposure | "BTC 200-day-average regime behaviour is research-exposed here" (spec `L719`) | the same exposure applies if C's macro filter is a BTC long-horizon trend state | overlapping |
| Mechanism argument | owed: "It is a regime filter, not that mechanism" (memo `L124`) | owed (G5-15) | both open |

- **G5-21 · INFERRED. Meaningfully distinct, with one overlapping component.** Design A times the exposure of one asset; C times entries across many assets. They differ in universe, decision frequency, signal type, exposure and exits.
- **G5-22 · INFERRED. Possibly nested.** If C's macro filter were a long-horizon BTC trend state, C would be "a Design-A-like regime × an altcoin pullback entry". Its incremental claim would then be only the entry and the universe, and a result could not be separated from the Design A signal unless the design isolates the filter, for example with a filter-only control arm. The filter form is unspecified (EMA200 is not assumed), so the degree of nesting is **NOT_VERIFIED**.
- **G5-23 · INFERRED. Shared weaknesses.** Both are long-only spot rules, so both are exposed to the "timed beta" objection and need a buy-and-hold benchmark. Both have few independent episodes. The Design A memo already expects a first evaluation to be "most likely statistically inconclusive" (memo `L18` · DOCUMENTED_ONLY).

## 6. Shared constraints: multiple testing and A29 slots

| Constraint | Content | Source | Class |
|---|---|---|---|
| Alpha per admission | 1/240 = 0.05 / 12 admissions per 3-year program; MAIN and RESERVE alike; unused alpha forfeited | G4-01; G4 §2.1 | SOURCE_VERIFIED (as restated) |
| Simultaneous candidates | at most 3; 20% of slot-days reserved | GOV-02; G4 §2.1 | DOCUMENTED_ONLY |
| Looks | final look at day 365 only; futility looks non-binding | G4 §2.1 | SOURCE_VERIFIED |
| Weaker standards | "never adopted to rescue power" | `docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md:L117 @ 5d977f2` | SOURCE_VERIFIED |
| Named risk | "spending alpha on underpowered tests" | same file, `L118` | SOURCE_VERIFIED |
| Prior search | 40+ studies on overlapping history; post-hoc cells; no multiple-testing correction across studies | HIS-37; ECO-05 | DOCUMENTED_ONLY |
| Overlapping mechanisms | three admissions "would triple the FWER cost for overlapping mechanisms"; "Test at most one of H2/G3" | `docs/a46/A46_TRADE_GEOMETRY.md:L152-155 @ 5d977f2` | DOCUMENTED_ONLY |

**Implications (INFERRED):**
- One admission of B or C spends 1/240. Both together spend 2/240 = 1/120. B, C and Design A together spend 3/240 = 1/80 and fill the 3-candidate cap, leaving no simultaneous slot.
- The ladder's FWER covers admissions, not the exploratory search that produced a candidate. Selecting a candidate after 40+ studies is itself part of the multiplicity, which is why the repository asks for a deflated Sharpe with N counting every variant run (`S4_PHASE1_SCIENTIFIC_COMPARISON.md:L91-92 @ 5d977f2`) and for every Design A configuration to be reported (spec §18).
- By A46's own logic, B can carry at most one of A45 H1–H3 / A46 geometry v2 as a single admission, and C overlaps Design A and A45 H1 in its regime component.
- Shared slots divide n: up to 3 candidates on 2 Paper positions split the executable sample unless each has its own book (G4-09).
- Under the PROPOSED INCONCLUSIVE rule, an admission whose preregistered power at δ_min is below target is expected to end INCONCLUSIVE from the outset, and its alpha is consumed either way (G4 §9).

## 7. Cost break-even arithmetic

All rows are arithmetic identities on stated inputs. None is an estimate of any strategy's win rate, payoff, variance or turnover.

### 7.1 Required gross edge per trade

- With round-trip cost c, a trade breaks even only if its gross return is at least c. **c = 0.40% (baseline) or 0.60% (stress)**, so the required gross edge per trade is 0.40% or 0.60%, and every 0.20 pp of extra friction raises it one for one.
- **Where the values sit (INFERRED from cited inputs):**
  - they equal Design A's BASELINE and STRESS (0.20% and 0.30% per side; spec `L526-527 @ ebf8d8a` · SOURCE_VERIFIED);
  - the owner floor is 0.10% fee per side plus spread and slippage (ECO-09);
  - the tracker books a flat 0.30%, about 0.40% on stop exits (G3-04);
  - the S4 tiered model (fee 0.10% per side, half-spread 0.01% BTC/ETH or 0.04% others, slippage 0.05% per side; HIS-15) gives 0.32% / 0.38% round trip, and 0.44% / 0.56% under its ×2 stress. The 0.60% stress is therefore above every documented stress level.

### 7.2 In R units at the stop caps

The stop caps are 1d 3% and 4h 5% (`analyzer/technical_analyzer.py:L425 @ ea8ae4f`; `shared/strategy_math.py:L59 @ 5d977f2` · SOURCE_VERIFIED). The cap is a **maximum**: the stop is at least 1 ATR below entry, and setups whose structural risk exceeds the cap are rejected (`shared/signal_stop.py:L38-45 @ 5d977f2` · SOURCE_VERIFIED). So cost in R at the cap is the most favourable case, and any smaller R costs more. The 2% and 1% rows are illustrative.

The break-even hit rate is for a single bracket that exits the whole position at +b·R or −1R, with c charged once: p* = (1 + c/R) / (1 + b). It ignores partial exits, break-even stops and extra stop slippage. It is a demand on any strategy, not a forecast. b = 1 and b = 2.2 are the current T1 and T3 multiples (G2 §3.1).

| R | c/R at 0.40% | c/R at 0.60% | p* (b = 1) at 0.40% / 0.60% | p* (b = 2.2) at 0.40% / 0.60% |
|---|---|---|---|---|
| no cost (reference) | 0 | 0 | 0.500 | 0.3125 |
| 5% (4h cap) | 0.080R | 0.120R | 0.540 / 0.560 | 0.338 / 0.350 |
| 3% (1d cap) | 0.133R | 0.200R | 0.567 / 0.600 | 0.354 / 0.375 |
| 2% (illustrative) | 0.200R | 0.300R | 0.600 / 0.650 | 0.375 / 0.406 |
| 1% (illustrative) | 0.400R | 0.600R | 0.700 / 0.800 | 0.438 / 0.500 |

- For the current 25/50/25 bracket with a break-even stop, A46 computes its own break-even demands: a T1 hit rate of at least 0.81–0.96 when winners stop at T1 (ECO-06 · DOCUMENTED_ONLY). Candidate B's corrected geometry would need the same calculation on its own bracket; this file does not redo it.

### 7.3 Annual cost on capital

With 2 × $50 on $500 (G4-12), the annual cost as a share of capital is n · c / 10. It is the gross return on capital needed just to cover friction (an identity, not a projection):

| n trades a year | 12 | 26 | 52 | 73 | 182.5 | 365 | 730 |
|---|---|---|---|---|---|---|---|
| at 0.40% | 0.48% | 1.04% | 2.08% | 2.92% | 7.30% | 14.60% | 29.20% |
| at 0.60% | 0.72% | 1.56% | 3.12% | 4.38% | 10.95% | 21.90% | 43.80% |

### 7.4 Per-trade signal-to-noise needed for a 365-day test

From G4-07, a per-trade net edge is detectable at 80% power only if (μ/σ) · √n_eff ≥ k, with k = 3.48 (normal theory, lrv 1) to 4.04. With deff = 1 the minimum per-trade μ/σ is k / √n (multiply by √deff for dependence):

| n_eff a year | 13 | 26 | 52 | 73 | 182.5 | 365 | 730 |
|---|---|---|---|---|---|---|---|
| k = 3.48 | 0.965 | 0.682 | 0.483 | 0.407 | 0.258 | 0.182 | 0.129 |
| k = 4.04 | 1.120 | 0.792 | 0.560 | 0.473 | 0.299 | 0.211 | 0.150 |

- μ is the **net** mean, so the gross mean per trade must be at least c + (k / √n_eff) · σ. σ is unmeasured for both candidates (G4 Q7), so the requirement stays symbolic.
- **G5-24 · INFERRED.** Low turnover (C) shrinks the annual cost (§7.3) but raises the per-trade signal-to-noise demand (§7.4). High turnover (B) does the reverse. Neither profile escapes the constraint; they trade one burden for the other.

## 8. Decision matrix

### 8.1 Options, criteria and scale

**Options.**
- **B:** select the Derived Momentum Successor for pre-registration.
- **C:** select the Regime-Filtered Trend-Pullback for pre-registration.
- **D:** stop or pause strategy research. The two forms are assessed separately where they differ: *pause* (no selection for pre-registration until named owner decisions are taken) and *stop* (end the research line).
- **INCONCLUSIVE:** existing evidence cannot resolve the choice. This is a **decision-state** label. It is not the PROPOSED test-outcome label of G4 §9, which is not in force.

**Criteria** (each asks a forward-looking question; none counts sunk cost, reviewer votes or expected profit):

| Criterion | Question |
|---|---|
| Evidence support | Does attributable or closely comparable pre-freeze evidence support taking this option? |
| Distinctness | Would a result add information beyond hypotheses already tested? |
| Feasibility under A29 power | Can the option yield a confirmatory answer at plausible effect sizes within the governed design (G4)? |
| Cost robustness | Does viability survive the move from 0.40% to 0.60% round trip (§7)? |
| Data availability | Are the data the option needs permitted and available now? |
| Engineering effort | How much future work stands between the option and a pre-registrable state? |
| Governance risk | How exposed is the option to version mixing, inherited claims, holdout contact or wasted slots? |

**Scale** (ordinal; no weights and no sum): **Favourable**, **Mixed**, **Unfavourable**, **Not determinable** (evidence absent), **Not applicable** (the criterion does not apply to the option).

### 8.2 Matrix

Repository paths in the matrix are cited `@ 5d977f2`; each cell's evidence class is the one given for the same item in §3–§7.

| Criterion | B: Momentum Successor | C: Trend-Pullback | D: pause / stop | INCONCLUSIVE |
|---|---|---|---|---|
| Evidence support | **Unfavourable.** Nothing attributable (G2-08, G1-02). Adjacent outcome evidence is inconclusive (HIS-09: CI [−0.433%, +0.679%]). The closest documented rankings classify a B-like design as "BASELINE ARM ONLY" (`S4_PHASE1_SCIENTIFIC_COMPARISON.md:L65`) and the A45 verdict is REVISE STRATEGY (`A45_SETUP_RESEARCH.md:L178-182`) | **Unfavourable.** Nothing attributable and no tracked trend-pullback result (G5-08). Its components appear among failed directions only on other implementations, which do not transfer (HIS-24, HIS-03) | **Pause: Favourable.** No net-positive, robust real-data study exists (HIS-42), nothing is attributable (G2-08) and nothing is confirmable at SR ≤ 2 in 365 days (G4 §8). **Stop: Unfavourable.** Insufficient power and non-attributable negatives are not evidence of no edge (G4 header; G2-08) | **Favourable.** B and C are both unsupported, so the evidence does not discriminate between them (G5-01) |
| Distinctness | **Unfavourable.** Same entry family as the deployed and June setups; changes are corrections and a narrowing (G5-11) | **Mixed.** The pullback-in-trend entry is untested; the trend and regime components overlap S4 M1, HIS-07, A45 H1 and Design A (G5-17, G5-21, G5-22) | Not applicable | Not applicable; records that the two differ in distinctness without deciding between them |
| Feasibility under A29 power | **Unfavourable.** Needs SR_ann ≥ about 3.48–7.00 (G4-04). A per-trade route exists only if the owner adopts such an endpoint and B reaches a few hundred weakly dependent trades (G5-13, §7.4) | **Unfavourable, more binding.** Same daily requirement; at 13–52 trades a year the per-trade μ/σ needed is about 0.48–1.12 (§7.4); effective n ≈ trend episodes (G5-18, G5-19) | Not applicable; spends no alpha and avoids "spending alpha on underpowered tests" (roadmap `L118`) | **Favourable.** Consistent with G4-06: the binding constraint is common to both candidates |
| Cost robustness | **Unfavourable.** 0.08R–0.20R at the caps, more at smaller R; T1-only paths net-negative at small T1 (A46-C); annual drag up to n · c / 10 of capital (§7.2–7.3) | **Not determinable.** Same per-trade break-even; lower annual drag; stops unspecified; turnover never measured (HIS-19) | Not applicable | Not applicable; cost moves the burden between frequency profiles without resolving the choice (G5-24) |
| Data availability | **Mixed.** Historical route blocked (no `DatasetPermission`; OD-DF-1 undecided). A prospective route uses the existing pipeline, but needs a version boundary, an owner-declared window, image validation and counterfactual calibration (§3.4) | **Unfavourable.** Historical route blocked as for B; no prospective path computes the setup; universe and macro data contracts undefined; CoinGecko inputs are not replayable (ECO-02) | Not applicable; needs no data | Not applicable |
| Engineering effort | **Mixed.** Geometry pieces exist but are dormant or absent from the deployed images; the selection fix, boundary record and calibration do not exist (G5-14) | **Unfavourable.** Entry, exits, universe and regime filter are all new; only harness and data-contract patterns are reusable (G5-20) | **Favourable.** None required | **Favourable.** Documentation only |
| Governance risk | **Unfavourable.** Inherited-claim and pooling risk next to the running Paper version; the contract hash misses two corrections (G3-08); the sealed holdout holds outcomes of the defective implementation (G3-05) | **Mixed.** Needs a hypothesis-source declaration; the BTC trend component is research-exposed; overlap with Design A spends correlated slots (§4.10, §6) | **Mixed.** No slot is used. Risk that a pause is misread as "the family failed", which the evidence does not show. Paper keeps running the defective implementation, and its evidence stays attributed to that version only (G3-09) | **Favourable**, provided it is never reported as negative evidence about either candidate |

### 8.3 Reading the matrix

- **B versus C (G5-25 · INFERRED).** Neither dominates. B is better on data availability and engineering effort; C is better on distinctness and governance risk; both are unfavourable on evidence support and power feasibility; cost robustness is unfavourable for B and not determinable for C. Choosing between them would require weighting the criteria, which is an owner value judgement, not an evidence question. **The evidence does not resolve the choice.**
- **B or C versus D (G5-26 · INFERRED).** Under the governed design as documented, every candidate is unfavourable on power feasibility, and selecting one would consume alpha on a test expected to end INCONCLUSIVE (G4 §9). D in its **pause** form is not dominated by either candidate on any criterion. D in its **stop** form is not supported, because the evidence is absence of evidence, not evidence of absence.
- **What changes the reading.** The feasibility row depends on owner decisions (§9). If the horizon, endpoint or validation design change, that row and the data row must be reassessed before any selection; the rest of the matrix stays as written.
- **What the matrix does not use.** Reviewer votes, the number of earlier studies as a score, sunk engineering cost, the existence of dormant code as a reason to choose, and any expectation of profitability.

## 9. Recommendation

**G5-27 · INFERRED. INCONCLUSIVE: existing evidence cannot resolve B versus C.** The conditional recommendation is that no candidate be selected for pre-registration until the owner has taken the decisions below, in this order. Each is a governance or design decision, not an evidence question. Paths in the table are cited `@ 5d977f2` (DOCUMENTED_ONLY for policy text).

| Order | Owner decision | Why it comes first | Source |
|---|---|---|---|
| 1 | Horizon and endpoint (G4 Q1, Q2), the validation design for realistic effects (OD-DF-2) and a preregistered INCONCLUSIVE outcome rule (G4 Q6) | decides whether **any** candidate is confirmable; a per-trade endpoint would favour higher executable n (B), a long-history qualification design would favour low-turnover designs (C, Design A) | G4 §11; `DEVELOPMENT_FIRST_POLICY.md:L114` |
| 2 | Dataset permission: OD-DF-1, licence clearance (A18/A19) and a recorded `DatasetPermission` | without it neither candidate can leave the concept stage | `DEVELOPMENT_FIRST_POLICY.md:L42, L113` |
| 3 | Capacity and book design (G4 Q4) and the authorised route to planning inputs: σ, n, holding time, dependence (G4 Q7) | fixes n for both candidates; no planning input may come from protected or research-exposed outcomes | G4 §11 |
| 4 | Program slot plan: the disposition of Design A (its E1–E8 gate), whether it would serve as a control for C, and the use of the 3-candidate cap and 12 admissions | B, C and Design A together would fill the cap and spend 1/80 (§6) | memo §3; G4-01 |
| 5 | Candidate prerequisites. **B:** which W3 correction (G1-10), the selection rule replacing the alphabetical cut, the timeframe set, a declared version boundary and an identity record beyond the contract hash (G3-08), and which overlapping refinements (A45 H1–H3, A46 G3) it includes, at most one admission among them. **C:** a written specification (horizon, regime-filter form, entry, exits, stops, universe, benchmark, a filter-isolating control), its hypothesis source and its relation to Design A | turns each concept into something that can be judged for distinctness and power at all | G1-09, G1-10, G3-08, G3-09; §5 |

**Conditional readings (none is a selection):**
- **If the 365-day daily-endpoint design stays unchanged:** record both candidates as "not confirmable by design" (the wording G4 Q1 offers) and take D in its **pause** form. Engineering corrections that are declared boundaries remain separate owner decisions and are not evidence (G3-09).
- **If a per-trade endpoint with a documented mapping is adopted (G4 Q2):** B's higher feasible n becomes relevant, but B still carries low distinctness and the version-boundary work.
- **If long licence-cleared history for qualification plus a short prospective check is adopted (OD-DF-2):** low-turnover designs become assessable at the qualification stage. C still needs a specification, and its nesting with Design A must be resolved first.
- In every case, a corrected defect, existing dormant code or earlier research effort is **not** evidence for selecting a candidate.

> **This documentation phase does not authorize selecting, pre-registering or testing any hypothesis.** The recommendation above orders owner decisions; it does not rank any candidate for admission.

## 10. Findings register (G5)

| ID | Class | Finding |
|---|---|---|
| G5-01 | INFERRED | Neither candidate has attributable evidence; both are unspecified concepts; adjacent evidence is inconclusive or non-transferable |
| G5-02 | INFERRED | B is a new strategy version (G3-09) with no inherited evidence or claim |
| G5-03 | INFERRED | C is materially different from Design A in signal type, universe and frequency, and overlaps it in the macro-regime component |
| G5-04 | INFERRED | Neither candidate is confirmable at plausible effects within 365 days; frequency is the only discriminating factor, and only under a per-trade endpoint |
| G5-05 | INFERRED | Break-even gross edge 0.40% / 0.60% per trade; 0.08R / 0.12R at the 4h cap and 0.133R / 0.20R at the 1d cap; more for smaller R |
| G5-06 | INFERRED | No dominant option between B and C |
| G5-07 | INFERRED | Recommendation INCONCLUSIVE; owner decisions first; D (pause) if the design stays unchanged |
| G5-08 | NOT_VERIFIED | No tracked document specifies Candidate C or reports a trend-pullback result |
| G5-09 | INFERRED | Dropping 15m moves B toward the favoured horizon, but its breakout trigger is not the trailing-return rule of the literature or of A45 track 2 |
| G5-10 | CONTRADICTORY | Two W3 corrections (G1-10), two W3 severity labels (G3-10), and `T1_CAP_POLICY` on `main` but not in `ea8ae4f` (G3-11) |
| G5-11 | INFERRED | B's distinctness from tested hypotheses is low |
| G5-12 | INFERRED | B's executable n ranges from near zero to the capacity bound (≥ 73 to ≥ 182.5 a year at full occupancy), divided by shared slots |
| G5-13 | INFERRED | B's feasibility is conditional on owner decisions (endpoint, planning-input route), not on evidence |
| G5-14 | INFERRED | B's engineering effort is moderate |
| G5-15 | INFERRED | "Medium-term" conflicts with the repository-cited crypto reversal at 4 weeks or more unless C fixes its horizon and mechanism argument |
| G5-16 | INFERRED | C-related gaps: the horizon conflict, the HIS-07 regime-filter omission, and a qualitative "pullback" note that is not a test |
| G5-17 | INFERRED | C's distinctness is moderate: the entry is untested, its components are not |
| G5-18 | INFERRED | C's executable n is about 0 to the low tens a year per 2-slot book under a stated 2–8-week holding assumption |
| G5-19 | INFERRED | C is at least as horizon-bound as B, and more so under a per-trade endpoint |
| G5-20 | INFERRED | C's engineering effort is high relative to B |
| G5-21 | INFERRED | C is meaningfully distinct from Design A as a hypothesis |
| G5-22 | INFERRED | C may nest a Design-A-like regime filter; the degree of nesting is NOT_VERIFIED until the filter is specified |
| G5-23 | INFERRED | C and Design A share the timed-beta objection and a small number of independent episodes |
| G5-24 | INFERRED | Low turnover lowers annual cost but raises the per-trade signal-to-noise demand; high turnover does the reverse |
| G5-25 | INFERRED | B versus C cannot be resolved by evidence; a choice would rest on owner weighting of criteria |
| G5-26 | INFERRED | Under the unchanged design, D (pause) is not dominated; D (stop) is not supported |
| G5-27 | INFERRED | INCONCLUSIVE, with an ordered list of owner decisions that must come first |

## 11. NOT VERIFIED items

| ID | Question | Blocker |
|---|---|---|
| G5-NV-01 | What exactly is Candidate C (horizon, regime filter, entry, exits, universe)? | No specification exists in any tracked file |
| G5-NV-02 | What exactly is Candidate B? | No specification exists (G1-09) |
| G5-NV-03 | What did the 1d MA20/MA50 pullback script produce, on which data and when? | Its output is an untracked CSV, outside the read scope; no tracked Markdown result |
| G5-NV-04 | What did HIS-07's BTC EMA50/EMA200 regime filter contribute on its own? | No tracked record isolates it |
| G5-NV-05 | σ, executable n, mean holding time, occupancy and dependence (deff, lrv) for either candidate | No authorised measurement route (G4 Q7); post-freeze data sealed; research-exposed outcomes may not be used for planning |
| G5-NV-06 | Signal supply of 4h/1d momentum setups | Documented rates come from windows not verified pre-freeze: count withheld (window not verified pre-freeze) |
| G5-NV-07 | Degree to which C nests Design A | C's regime filter is unspecified |
| G5-NV-08 | Real-world execution validity (level 3) for either candidate | Needs a forward capture under an owner-approved Paper window (`docs/a47/A47_EXECUTION_REALISM.md:L114 @ 5d977f2`) |
| G5-NV-09 | Whether either candidate is "consistent with A29" in the originals' wording | A29–A34 originals are at local commit `54a6369`, held under OD-1 (as in G4 §2.2) |
| G5-NV-10 | Existing hypothesis-source registry entries | `research/governance/hypotheses.jsonl` and `pre_existing_knowledge.json` are data artefacts outside the read scope; the Design A spec reports the first as empty (`DESIGN_A_SPEC_v1.0.md:L80-85 @ ebf8d8a` · DOCUMENTED_ONLY) |

## 12. Inconsistencies and observations

**Upstream workstreams.** No error was found in G1–G4. Every conclusion used here was checked against the sources it cites where this workstream re-read them: A45 L191-192 and A46 G1 (G1-10), S4 Phase 1 L65 and L76 (G1 §5), the time stops and capacity (G4-08), the stop-slippage charge (G3-04), and the alpha derivation (G4-01).

| ID | Observation | Class |
|---|---|---|
| G5-O1 | The audit's HIS-07 line describes cross-sectional long/short momentum but does not mention its BTC > EMA50 and BTC > EMA200 regime filter (`analyzer/MODEL_FROZEN_SPEC.md:L16 @ 5d977f2`). The filter matters for Candidate C and Design A because it shows the BTC trend filter is research-exposed | SOURCE_VERIFIED (file); omission INFERRED |
| G5-O2 | HIS-07 gives "250 coins"; the frozen model gives a top-30-by-volume universe (`MODEL_FROZEN_SPEC.md:L10`). This is plausibly a candidate pool versus a selected universe, but the files read do not say so | NOT_VERIFIED |
| G5-O3 | HIS-23 lists studies with code but no result document. The 1d MA20/MA50 pullback script belongs on that list | SOURCE_VERIFIED (code present, no result document) |
| G5-O4 | The brief's 0.40% / 0.60% round trip equals Design A's BASELINE / STRESS and exceeds the S4 ×2 stress (0.44% / 0.56%). No contradiction | INFERRED |
| G5-O5 | A45 track 2 (1d time-series momentum, no breakout trigger) is not Candidate B, which keeps the trigger. This is consistent with G1 §5 | DOCUMENTED_ONLY |
| G5-O6 | The brief's stop caps (4h 5%, 1d 3%) match the source; they are maxima, not typical risk | SOURCE_VERIFIED |

## Repository sources

Read for this workstream (all `@ 5d977f2` unless stated): `docs/strategy/S4_MECHANISM_COMPARISON.md`; `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md`; `docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md`; `docs/a45/A45_SETUP_RESEARCH.md`; `docs/a46/A46_TRADE_GEOMETRY.md`; `docs/a47/A47_EXECUTION_REALISM.md`; `docs/a48/A48_REPLAY_FIDELITY.md`; `docs/phase3_entry_hypothesis_review_2026-08-17.md`; `docs/governance/DEVELOPMENT_FIRST_POLICY.md`; `docs/lab/STRATEGY_LAB_ARCHITECTURE.md`; `docs/claude/strategy-history.md`; `analyzer/MODEL_FROZEN_SPEC.md`; `research/skill_application/out/REPORT.md` (Markdown only); `research/skill_application/scripts/ma2050_uptrend_bt.py` (docstring and constants only); `research/mechanisms/simulate.py`; `research/mechanisms/signals.py`; `shared/signal_stop.py`; `shared/strategy_math.py`; `shared/t1_cap.py`; `shared/setup_diagnostics.py`; `shared/trade_geometry.py`; `analyzer/technical_analyzer.py @ ea8ae4f`; `docs/strategy/DESIGN_A_SPEC_v1.0.md @ ebf8d8a`; `docs/strategy/DESIGN_A_PROFITABILITY_DECISION_MEMO.md @ ebf8d8a`; the audit package files linked above.
