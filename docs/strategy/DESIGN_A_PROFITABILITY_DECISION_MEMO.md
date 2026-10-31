# Design A v1.0: profitability-first scientific decision memo

**Status.** A read-only review for the owner, dated 2026-10-31.
- **No access, no experiment.** No market data, holdout, protected record or trading outcome was accessed, and no experiment was run.
- **No decisions.** Every recommendation here is PROPOSED for an owner decision.

**Labels:**
- **VERIFIED**: checked against the repository record cited.
- **INFERRED**: reasoned from verified facts or general knowledge, and not tested.
- **NOT TESTED**.

**Mission.** The goal is a genuinely profitable, economically viable BTC/USDT spot strategy. Engineering quality, reproducibility and integrity are supporting controls, not the success criterion.

## Bottom line

- **The software is ready for review, and it says nothing about profit.**
- **Profitability is unknown.** No real-data evaluation can start: no dataset has a recorded permission (VERIFIED, `docs/governance/DEVELOPMENT_FIRST_POLICY.md` §2).
- **A first evaluation will most likely be statistically inconclusive** (VERIFIED power arithmetic, §2.5). Its value is falsification, a cheap rejection of a bad design, not confirmation.
- **The largest scientific gap is separating timing value from lower BTC exposure** (§2.3), together with an unfrozen outcome classification (§2.5). Execution convention and costs matter less.
- **Eight owner decisions (E1–E8, §3) gate the first evaluation.** Most other open items can wait (§4).

## 1. Three questions, kept apart

| Question | Status today | Basis |
|---|---|---|
| **Software correctness** | **Established for the synthetic scope.** The package computes what the specification says: signal, timing, fills, costs, weekly retries, candle integrity, deterministic digests. | `docs/strategy/DESIGN_A_V1_EVIDENCE.md` |
| **Scientific validity** | **Not yet attainable.** No dataset may be used. The availability policy, the timing-versus-exposure test, the outcome classification and the hypothesis source are undecided. | spec §19 items 1–4, 7, 8, 16 |
| **Net economic profitability** | **Unknown.** No real-data result exists. Synthetic results carry no economic information. | `OWNER_OPERATING_CONTRACT.md` §1: "No assertion of profitability without credible prospective independent evidence" |

Passing tests moves only the first row.

## 2. Findings

### 2.1 Does the Tuesday-open reference introduce execution optimism?

- **No look-ahead (VERIFIED, spec §4, §7 and tests).**
  - The signal uses the Sunday close known at Monday 00:00 UTC plus 30 s.
  - The fill uses the next Tuesday open and is booked when that candle completes.
  - No candle opening at or before the decision is ever a reference.
- **No trigger selection (INFERRED from the repository's replay audits).** The documented replay optimism comes from *triggered* stop fills priced at the level or at a gap open (`docs/a48/A48_REPLAY_FIDELITY.md` rows 6–7; `docs/a47/A47_EXECUTION_REALISM.md`). Design A's orders are *scheduled* and never triggered by price, so that selection bias does not arise.
- **Remaining optimism (INFERRED, not measured):**
  - **The open is one print.** A live order at the boundary trades at the prevailing quote plus impact. Depth, partial fills and latency are not modelled (spec §20).
  - **The availability rule assumes publication within the 30-second offset** (spec §5). If live data arrive later, the live rule skips weeks that a historical run never skips, so a historical result would describe a rule that would not run.
  - **The one-day delay's direction of error is unmeasured** (spec §16).
- **Assessment (INFERRED).** For small BTC/USDT orders, the convention is unlikely to be the dominant error, because B1 uses the same reference (spec §14). The availability policy is the part to settle before evaluation (E3).

### 2.2 Does the SMA200 missing-data behaviour bias exposure?

- **Mechanics (VERIFIED, spec §5, §8).**
  - A gap freezes holdings for every decision whose 200-day window contains it: 28–29 weeks.
  - A missing Sunday skips one week.
  - A candle lost after a decision consumed it is refused.
  - Nothing is filled or interpolated (`docs/research_temporal_governance.md`).
- **Effect (INFERRED).**
  - The bias has no systematic sign, but it is path-dependent: a frozen period that spans a regime change keeps the old position through it.
  - With few independent episodes, one such period can dominate a result.
- **Relevance.** It depends on gaps in the evaluated series. The raw Binance source is not yet a certified snapshot (VERIFIED, temporal governance, "Dataset and correction policy"). If the certified BTC/USDT daily series has no gap in the evaluation period, the rules are never exercised, and the window rule (§19 item 16) can wait.
- **Requirement (PROPOSED).** Report every skip episode, with the position held through it.

### 2.3 Can the benchmark set separate strategy value from BTC exposure?

**Not as frozen (INFERRED).**
- **B1 (primary) conflates timing with exposure level.** Design A holds BTC only part of the time, so lower volatility and drawdown follow mechanically. The hypothesis itself says that this proves nothing ("Drawdown reduction alone does not prove timing skill", spec §1).
- **The certainty equivalent does not separate them either.** A higher CE at γ = 2 than B1 can arise with no timing at all: a constant partial BTC allocation can have a higher CRRA certainty equivalent than full exposure.
- **The other benchmarks cannot fill the gap:**
  - B3 (lagged 90-day exposure match) follows Design A's own recent exposure, so it partly inherits its timing;
  - B2 uses hindsight;
  - both are frozen as descriptive only (spec §14).

**Repository precedent (VERIFIED, `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md`):**
- long/cash trend rules are "mostly timed beta", and their hypothesis "must be risk-adjusted improvement over B&H, not alpha" (§3);
- unscaled time-series momentum is approximately buy-and-hold (Kim, Tse, Wald 2016, cited in §2).

**Proposed, for an owner decision (not adopted).** Keep B1 primary, and define in advance how timing value is separated from exposure. Two options:
- **Placebo null (simplest, outcome-free).** Random switch dates with Design A's time in market and number of transitions, under the same costs and execution.
- **Timing regression.** A declared secondary analysis, for example Treynor–Mazuy or Henriksson–Merton.

Either adds one pre-registered analysis, not a parameter.

### 2.4 Are the cost assumptions conservative enough?

- **Rates (VERIFIED, spec §10).**
  - Baseline: 0.20 % per side (fee 0.10 %, half-spread 0.05 %, slippage 0.05 %).
  - Stress: 0.30 % per side.
  - The fee is the owner's standard undiscounted spot fee (`OWNER_OPERATING_CONTRACT.md` §1).
- **Against repository practice (VERIFIED).** The S4 draft declares a 0.01 % half-spread for BTC/ETH (`S4_PHASE1…` §4), so Design A's baseline half-spread is five times larger. Both are declared assumptions: historical spread data are unavailable (temporal governance).
- **Materiality (INFERRED, not measured).** A weekly 200-day filter trades rarely. At 0.40 % per round trip, a few round trips a year cost roughly 1–2 % a year, which is small beside BTC's volatility. Timing and exposure, not these rates, will decide the economics.
- **Not modelled (VERIFIED, spec §20):**
  - market impact at size;
  - USDT issuer risk while FLAT;
  - cash yield.
- **Proposed.**
  - Treat the costs as adequate for a first exploratory evaluation.
  - Report both scenarios (frozen).
  - Declare in advance that a result which reverses under STRESS is not encouraging (as `S4_PHASE1…` §4, failure criterion 5).

### 2.5 Can the statistical thresholds prevent false profitability claims?

**The governed thresholds are strict (VERIFIED, `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md` §2):**
- α = 1/240 per admission, with a 5 % program FWER;
- a final look at 365 days, on a daily HAC z;
- `ENCOURAGING` is non-confirmatory, with about a 20 % null rate;
- the critical values are unvalidated (DR-6).

**At realistic effects they leave almost no power (VERIFIED, outcome-free).**
- **Governed test.** The 365-day minimum detectable annualized Sharpe is about 3.5–7:
  - 3.53 at a long-run variance ratio of 1, and 4.99 at a ratio of 2 (`S4_PHASE1…` appendix A3);
  - "≈ 3.5–7.0" in `DEVELOPMENT_FIRST_POLICY.md` OD-DF-2, which adds: "no realistic daily strategy can be confirmed in one window".
- **Exploratory test.** Even 2,922 days of history give an exploratory MDE of about 1.05 at α = 0.05/3 (same table).
- **INFERRED.** The information ratio of a long/cash filter against buy-and-hold is unlikely to reach that.
- **Consequence.** The likely outcome is inconclusive. Insufficient power is not evidence of no edge (`EVIDENCE_LADDER_PARAMETERS.md` §4, rule 1).

**False claims would come from elsewhere (INFERRED):**
1. **An unfrozen exploratory classification.** Spec §17 is NOT DEFINED, so today any historical result could be narrated as encouraging.
2. **Research-exposed history:**
   - every historical period is contaminated (temporal governance);
   - this repository has already studied a BTC EMA200 regime filter (spec §1);
   - the 200-day average is market folklore: selection at industry scale.
3. **Very few independent bull and bear episodes,** and sensitivity to start and end dates (spec §16).
4. **An exploratory "encouraging" presented as profitability.**

**Mechanism gap (VERIFIED source, INFERRED for Design A).**
- **What the review found.** The repository's literature review finds crypto momentum at ≤ 2 weeks and reversal at ≥ 4 weeks (Dobrynskaya, in `S4_PHASE1…` §2).
- **What a 200-day filter is.** It is a regime filter, not that mechanism.
- **What is owed.** Its own mechanism argument (roadmap S4: "each candidate needs its own mechanism argument").

**Proposed, before any data:**
- freeze the exploratory classification, with falsification criteria that can actually reject;
- report a deflated Sharpe whose N counts every configuration run, with the prior exposure disclosed;
- print the outcome-free MDE next to every result;
- never present any exploratory label as profitability.

## 3. Decisions essential before the first authorized economic evaluation

| # | Decision | Why it is essential | Source |
|---|---|---|---|
| E1 | Licence clearance and a recorded `DatasetPermission` for Binance Spot BTC/USDT daily klines ending strictly before the research freeze (the FORWARD_HOLDOUT boundary in `research/governance/research_freeze.json`), and OD-DF-1 (exploratory historical analysis allowed, never confirmatory) | No real-data evaluation is allowed without them, and no dataset has a permission today | `DEVELOPMENT_FIRST_POLICY.md` §2, §7; A18/A19 HOLD |
| E2 | A certified, content-addressed BTC/USDT daily snapshot (completeness and validity), and the holdout partition key | Reproducible, pre-freeze inputs. The raw source is not certified, and the partition guard is required before any real data (spec §3) | temporal governance; §19 item 7 |
| E3 | The data-availability policy, including a late Sunday at the decision instant | A frozen requirement before historical evaluation. It decides whether the evaluated rule is the rule that would run | spec §5; §19 item 1 |
| E4 | The hypothesis source (PRE_EXISTING, DISCOVERY_DERIVED or EXTERNAL_THEORY) and its registry entry | It fixes how a result may be described and how the prior EMA200 exposure counts | temporal governance; §19 item 2 |
| E5 | The primary endpoint and benchmark operationalisation: B1, the CE estimator, the excess reference, the time basis, and how timing is separated from exposure (§2.3) | Without it, the evaluation cannot test H-A: value after costs relative to passive exposure | §19 items 4, 8, 17 |
| E6 | A frozen exploratory outcome classification, with an owner ruling on "consistent with A29" | The main route to a false claim. The brief requires it before evaluation | spec §17; §19 item 3 |
| E7 | The bootstrap scheme and the leave-one-year-out fold unit | Both are in the frozen metric list, so they must be chosen before any result is seen | §19 items 5, 6 |
| E8 | An outcome-free power statement for the chosen endpoint | So that an inconclusive result is read correctly, as decided before the run | §19 item 14 |

**Conditional.** The window rule (§19 item 16) and the deferral reading (§19 item 11) become essential only if the certified series has missing days or Tuesdays in the evaluation period.

## 4. What can be deferred

| Item | Why it can wait | Needed before |
|---|---|---|
| Further performance work | Integrity checks are now fast enough for a single replay over the full pre-freeze history (evidence record) | workloads beyond that |
| Authenticity of saved records (MAC or signature) | One historical run over a content-addressed dataset needs consistency, not authenticity | multi-party or prospective record keeping |
| Revision detection for delivered but unconsumed candles across a cut | A historical evaluation is one replay call over a frozen dataset | incremental or live feeds |
| Live data adapter, scheduler, Paper wiring (roadmap S6) | No economic result justifies them yet | after an evaluation, with separate approval |
| Cost-tier measurement (§19 item 9, class B) | Needed only for a claim about cost realism; costs are not decisive at this turnover (§2.4) | any cost-realism statement |
| Minimum-order venue values (§19 item 10, class B) | With adequate starting cash, the minimums do not bind | small-account studies |
| Dust mark details (item 12) and Decimal tolerances (item 13, class B) | Negligible effect on the economic metrics | — |
| A validation design for small effects (OD-DF-2) and governed confirmation (D3) | Pointless until an exploratory result survives falsification | any prospective or Paper investment |

## 5. Minimal path to the first credible economic evaluation

Each gate needs the approval shown, and passing a gate authorizes nothing beyond it.

| Gate | Deliverable | Approval | Does not authorize |
|---|---|---|---|
| **G0 Decisions** | E1–E8 recorded, and a written Design A pre-registration: one primary endpoint, the benchmarks including the timing control, the frozen metrics, the classification and the power statement | owner | data access |
| **G1 Data** | Licence cleared; `DatasetPermission` recorded; a certified pre-freeze BTC/USDT daily snapshot with its content hash | owner (permission) | any result |
| **G2 Engineering** (D0, synthetic first) | Snapshot adapter with the permission path and the holdout guard; B0–B5 and the timing control; the metrics; a runner that logs every variant before any result exists | standing D0 authorization; independent code review | a real-data run |
| **G3 Freeze** | Hypothesis registered; protocol and code SHAs recorded | owner | a second look |
| **G4 One exploratory run** (D1) | All configurations and both cost scenarios reported, classified by the frozen procedure, with the MDE beside each result | owner, once | any profitability claim |
| **G5 Review** | Independent review. The owner then stops (falsified), or orders a prospective validation design (OD-DF-2) and possibly a declared Paper window (D2) | owner | live trading; the A29 ladder (D3) while the D1/D2 HOLD stands |

**What "credible" means here:**
- decisions taken before any data;
- one logged look;
- every variant reported;
- B1 plus an exposure control;
- both cost scenarios;
- the power statement;
- the contamination disclosure.

Even then, the result is exploratory. A profitability claim needs prospective, independent evidence through the A29 ladder after the D1/D2 HOLD is lifted. All of these are owner decisions.

## 6. Missing authoritative documents

| Document | Status | Consequence |
|---|---|---|
| A29–A34 raw texts | Only in the local, unpushed commit `54a6369`; publication is held (OD-1) and U1/U3/U4 are uncertain (OD-2). Not read for this memo | "Consistent with A29" cannot be checked. Nor can the reference of the governed claim's "net excess" for a long/cash strategy (cash or B1). This memo uses only the sanitized citations in `EVIDENCE_LADDER_PARAMETERS.md` |
| The A18/A19 licence decision | Cited as a HOLD; no decision record in the repository | E1 cannot be met |
| A dataset permission | None recorded (`DEVELOPMENT_FIRST_POLICY.md` §2) | D1 stays synthetic-only |
| The owner brief (2026-10-30) and the 2026-10-31 decisions | The repository holds only the specification's quotations | A reviewer cannot check FROZEN labels against the original text |
| `INCONCLUSIVE` and `NOT ENCOURAGING` | Defined nowhere (spec §17) | E6 |
| Measured spread or tier tables | Historical spread is unavailable, and the A30 tier figures are U4 | Costs stay declared assumptions |

## 7. What this memo does not do

- It runs nothing, reads no outcome and selects no parameter.
- It changes no frozen rule, cost or weekly-retry decision.
- It resolves no §19 item: every recommendation awaits the owner.
