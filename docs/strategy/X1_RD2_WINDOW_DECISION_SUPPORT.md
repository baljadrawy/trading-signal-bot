# X1 look window: power and trade-off for owner decision RD-2 (DRAFT, synthetic only)

**Status: DRAFT decision support (D0), written 2026-10-27 on `research/variant-ledger` (PR #94).** Every number
below comes from series **generated inside a simulation** from stated parameters (`evidence_class = SYNTHETIC`). No
market data, kline or pickle file, holdout, W3 / prospective window or Paper DB was opened. Nothing here is frozen,
registered or authorized, no alpha is spent, and the window is **not** chosen: RD-2 is the owner's decision. The
recommendation in §5 is a recommendation, not a decision. No profitability is claimed for any hypothesis.

Code: `research/power_sim/x1_single_look.py` (`x1-pwr-sim-v1`); tests: `tests/test_x1_single_look_power.py`
(vectorized HAC t, DSR and bootstrap are cross-checked against `research/stats/inference.py` and
`research/stats/sharpe_deflation.py`; costs reuse `research/mechanisms/costs.py`). Reproduce (stdout only, about
20 minutes on one core):

```text
python -m research.power_sim.x1_single_look --reps 2000 --seed 20261027        # add --json for every field
```

## 1. What is simulated

**Candidate windows** (`NEXT_LICENSED_DATA_STEP.md` §7–§8): **(a)** 2023-01-01 → 2026-08-18, 1,326 UTC days;
**(b)** 2019-01-01 → 2026-08-18, 2,787 UTC days. Both end strictly before the 2026-08-19 freeze instant.

**Primary series** (PM-1 notion (c)): the daily active net return a_t = R_t − B_t of HR-04 vs the PIT EW B&H.
"True Sharpe" is its annualized mean / marginal sd (√365.25), **net of costs** by default. Shocks: normal, Student-t
df 3 / 4 / 5 (scaled to unit variance), AR(1) 0.1 / 0.2, GARCH(1,1) (0.10, 0.85). 2,000 replications per cell
(Monte Carlo SE ≤ 0.011).

**Pass rule.** PM-1 as written in `docs/strategy/PROFITABILITY_ROADMAP_2026-10-24.md` §9.1 (PR #91, Draft): *active
net vs EW B&H > 0 with HAC t ≥ 2 (lag 7) and bootstrap 95 % CI excluding 0; DSR ≥ 0.95 with N = all logged
variants; (a) mean net > 0 under ×2 cost stress; none of the five S4 failure criteria triggered.*

- **core** = HAC t ≥ 2 (Bartlett, lag 7) **and** stationary-bootstrap (mean block 20 d, 499 resamples) 95 % CI
  lower bound > 0 **and** DSR ≥ 0.95 with N = 3 variants (the contract's candidate cap; the two other variants are
  simulated with correlation 0.8 [ASM] and the same true Sharpe).
- **full** = core **and** absolute net mean > 0 under ×2 stress **and** none of: cost drag > 50 % of gross;
  MDD worse than EW B&H without a Sharpe gain; > 50 % of net P&L from the best 5 months; sign reversal of the active
  mean under ×2 stress. Not simulable with one series: the "1 coin" concentration test (so *full* is an upper bound
  there).

**Costs** (`s4-mech-v1`): fee 0.10 % per side, half-spread 0.01 % (BTC / ETH) and 0.04 % (other top-20), slippage
0.05 % per side, blended 2 / 18 names: **0.187 % per side**; ×2 stress on spread and slippage only, never on the
fee: **0.274 % per side**. Turnover for HR-04 is **not documented** in the repository, so it is a parameter
([ASM] strategy 0.10 / day, benchmark 0.005 / day, i.e. 6.6 %/yr active cost drag at base costs).

**Other [ASM] parameters** (outcome-free; none taken from any data): active vol 40 %/yr; benchmark vol 75 %/yr,
benchmark drift 0 (a drift chosen from known market history would be outcome-informed), correlation of active and
benchmark −0.5.

**Ambiguities in the documents, parameterized rather than resolved:** (1) PM-1 says HAC t ≥ 2, while
`NEXT_LICENSED_DATA_STEP.md` §8 and the S4 power table use the family split 0.05 / 3 (z ≈ 2.13); (2) PM-1 does not
say on which series the DSR or the 5-month concentration test is computed (simulated: DSR on the active series;
concentration on absolute net P&L as in roadmap §1.4 (a), and on active P&L as a sensitivity); (3) PM-1 says DSR
N = logged variants, while A19 §4 (held branch commit `8cb5c9e`, not on `main`) recommended an imputed N = 10⁴ for
exposed history.

## 2. Power table (core / full), and false-positive rate at true Sharpe 0

| Window | Shocks | SR 0 (FPR) | SR 0.5 | SR 1.0 | SR 1.5 | Normal ref. SR 1.0 (t ≥ 2) |
|---|---|---|---|---|---|---|
| (a) | normal iid | 0.017 / 0.000 | 0.134 / 0.003 | 0.416 / 0.013 | 0.772 / 0.070 | 0.46 |
| (a) | t5 iid | 0.018 / 0.000 | 0.129 / 0.001 | 0.433 / 0.018 | 0.770 / 0.071 | 0.46 |
| (a) | t3 iid | 0.018 / 0.000 | 0.138 / 0.002 | 0.434 / 0.012 | 0.779 / 0.067 | 0.46 |
| (a) | t4, AR 0.1 | 0.021 / 0.000 | 0.124 / 0.002 | 0.373 / 0.013 | 0.710 / 0.064 | 0.39 |
| (a) | t4, AR 0.2 | 0.029 / 0.000 | 0.129 / 0.001 | 0.339 / 0.010 | 0.642 / 0.057 | 0.33 |
| (a) | t4, GARCH | 0.017 / 0.000 | 0.128 / 0.001 | 0.446 / 0.016 | 0.781 / 0.071 | 0.46 |
| (b) | normal iid | 0.017 / 0.001 | 0.230 / 0.015 | 0.730 / 0.202 | 0.973 / 0.551 | 0.78 |
| (b) | t5 iid | 0.020 / 0.000 | 0.237 / 0.021 | 0.751 / 0.198 | 0.975 / 0.561 | 0.78 |
| (b) | t3 iid | 0.016 / 0.001 | 0.246 / 0.014 | 0.746 / 0.177 | 0.968 / 0.557 | 0.78 |
| (b) | t4, AR 0.1 | 0.022 / 0.000 | 0.204 / 0.018 | 0.681 / 0.194 | 0.956 / 0.562 | 0.69 |
| (b) | t4, AR 0.2 | 0.024 / 0.000 | 0.187 / 0.015 | 0.615 / 0.165 | 0.920 / 0.533 | 0.60 |
| (b) | t4, GARCH | 0.018 / 0.000 | 0.245 / 0.023 | 0.762 / 0.198 | 0.970 / 0.568 | 0.78 |

Reading:
- **False-positive rate** of the core rule is 0.016–0.029 (nominal one-sided ≈ 0.023 for t ≥ 2); positive
  autocorrelation inflates it slightly, because lag 7 does not absorb all of it. The full rule is ≤ 0.001.
- **Core power at a true Sharpe of 1.0**: about 0.34–0.45 on (a) and 0.62–0.76 on (b). Fat tails alone barely change
  it (the mean test is robust at these n); serial dependence lowers it.
- **The full rule is far stricter.** Almost all of the gap comes from the best-5-month concentration test on
  absolute net P&L: at a true Sharpe of 1.0 it fails in 96–97 % of the replications in which the core passed on
  (a), and in 72–76 % on (b). With 43 months, the best 5 months of a volatile, Sharpe-1 series nearly always exceed 50 % of the
  total. On (a) the full rule is essentially unpassable at a Sharpe ≤ 1.5 (≤ 0.07).

## 3. Sensitivities (t4, AR 0.1; core / full at true Sharpe 0 and 1.0)

| Variation | (a) SR 0 | (a) SR 1.0 | (b) SR 0 | (b) SR 1.0 |
|---|---|---|---|---|
| Baseline (from §2) | 0.021 / 0.000 | 0.373 / 0.013 | 0.022 / 0.000 | 0.681 / 0.194 |
| HAC t ≥ 2.128 (family split 0.05 / 3) | 0.021 / 0.000 | 0.365 / 0.009 | 0.019 / 0.000 | 0.655 / 0.172 |
| DSR with null trial variance, N = 3 | 0.011 / 0.001 | 0.317 / 0.008 | 0.009 / 0.000 | 0.592 / 0.162 |
| DSR with null trial variance, **N = 10⁴ (A19)** | 0.000 / 0.000 | **0.000 / 0.000** | 0.000 / 0.000 | **0.005 / 0.001** |
| Strategy turnover 0.05 / day | 0.017 / 0.000 | 0.393 / 0.013 | 0.021 / 0.001 | 0.669 / 0.185 |
| Strategy turnover 0.20 / day | 0.019 / 0.000 | 0.371 / 0.008 | 0.017 / 0.000 | 0.659 / 0.169 |
| True Sharpe defined **gross** (before costs) | 0.007 / 0.000 | 0.284 / 0.006 | 0.009 / 0.001 | 0.517 / 0.107 |
| Concentration test on **active** P&L | 0.020 / 0.001 | 0.372 / 0.071 | 0.023 / 0.004 | 0.686 / **0.539** |
| Benchmark drift −30 %/yr | 0.021 / 0.000 | 0.373 / 0.004 | 0.015 / 0.000 | 0.670 / 0.025 |
| Benchmark drift +30 %/yr | 0.026 / 0.001 | 0.377 / 0.056 | 0.022 / 0.002 | 0.676 / 0.494 |

- Turnover matters little when the Sharpe is defined net; defined gross, the base cost drag of about 6.6 %/yr
  removes roughly a quarter of the power.
- **The full rule's power depends strongly on the market's drift in the window** (absolute-net and absolute
  concentration conditions): 0.03 to 0.49 on (b) for −30 % to +30 %/yr. A nomination under the full rule is
  therefore partly a statement about the benchmark's path, not only about the active effect.
- **At the A19 imputed N = 10⁴, nothing realistic can pass in either window.**

## 4. Trade-off of the longer window (b)

**Power.** (b) roughly doubles core power at a Sharpe of 0.5–1.0 and is the only window in which the full rule has
non-negligible power. (a) spends the single exploratory look with an expected outcome of INCONCLUSIVE.

**Regime heterogeneity** (stylized, window (b), t4 AR 0.1; core / full):

| True effect | No guard | Guard: HAC t ≥ 0 on 2023-01-01 → 2026-08-18 | Guard: HAC t ≥ 1.0 on 2023-01-01 → 2026-08-18 |
|---|---|---|---|
| Sharpe 1.0 throughout | 0.681 / 0.194 | 0.691 / 0.181 | 0.631 / 0.165 |
| Sharpe 1.0 in 2019–2022, **0 from 2023** (decay) | 0.234 / 0.015 | 0.205 / 0.016 | 0.117 / 0.007 |
| 0 in 2019–2022, Sharpe 1.0 from 2023 (emergence) | 0.201 / 0.019 | 0.208 / 0.018 | 0.188 / 0.017 |

(Guard rows use their own seeds, so differences of about 0.01 from the no-guard column are Monte Carlo noise.)

A long window cannot tell a decayed effect from a current one: an effect that was present only in 2019–2022 is
"nominated" by the core rule about 23 % of the time. A [PROP] recency guard (HAC t ≥ 1.0 on the 2023-01-01 →
2026-08-18 part, preregistered) halves that (0.234 → 0.117) at a cost of about 5 points of power for a constant
effect (0.681 → 0.631); a sign-only guard (t ≥ 0) does almost nothing. The opposite case also matters: an effect
that **emerged** only from 2023 is diluted by (b) (core 0.20) and would be found more often by (a) (core 0.37 for a
Sharpe of 1.0 over all of (a)). The 2019–2022 span also contains different market regimes (A18 §13 item 2, held branch commit
`8cb5c9e`: "2019–2021 retail bull markets, the 2022 collapse (LUNA, FTT), and post-2024 ETF flows").

**Delisting and survivorship.** The EW benchmark always holds a coin up to its delisting; long/cash HR-04 holds it
only when its signal is long. Each delisting exit therefore shifts the active return by about
(1 − p_hold) × weight × loss, i.e. an annualized active-Sharpe shift of (1 − p) × w × L × events per year / active
vol (`delisting_sr_shift`). With w = 1/20, L = 1 (the −100 % stress), active vol 40 %/yr:

| Delisting exits per year in the PIT top 20 [ASM] | p_hold 0 | 0.3 | 0.6 |
|---|---|---|---|
| 0.5 | 0.06 | 0.04 | 0.03 |
| 1 | 0.13 | 0.09 | 0.05 |
| 3 | 0.38 | 0.26 | 0.15 |

So the delisting rule (last close vs −100 %) and the completeness of delisted pairs can move the active Sharpe by
an amount comparable to the effect sizes of interest, and the effect is concentrated in a few events. The longer
window contains more such events and depends more on listing / delisting dates inferred from file presence (A18
§13 item 4: "presence-based lifecycle cannot date listings; delisted symbols are present only while archived").
LIC-1 question 5 (coverage of delisted pairs) matters more for (b). The "1 coin" concentration test of PM-1, not
simulated here, is the guard for this.

**Governance of pre-W3 history (exact sources).**
- `docs/governance/OWNER_OPERATING_CONTRACT.md` §4 (on `main`): protected / sealed holdouts stay sealed; A29
  Evidence Ladder with D1/D2 HOLD; max 3 candidates; 5 % familywise error; ENCOURAGING is non-confirmatory.
- W3 is the sealed post-freeze holdout (`research/governance/holdout_status.json`: SEALED, freeze 2026-08-19, zero
  looks; `research/governance/w3_holdout_guard.json` and `W3_CONTAMINATION_DISCLOSURE.md` on branch
  `docs/p2-g0-w3-holdout-guard-20261002`). **Both** candidate windows are pre-W3; neither touches W3 or
  FORWARD_HOLDOUT.
- `research/governance/contamination_registry.jsonl`: 2017-08-01 → 2022-12-31 **LIKELY_RESEARCHED** ("cannot prove
  this period remained unseen"); 2023-01-01 → 2025-12-31 and 2026-07-01 → freeze **KNOWN_RESEARCHED**; 2026-01 → 06
  is not registered (gap recorded in `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md` §4). A18 §1 (held commit
  `8cb5c9e`): "No historical interval before W3 is untouched … Every month from 2017-08 to 2026-06 was used by at
  least one documented study". Window (b) adds LIKELY-researched rather than KNOWN-researched years; it is not
  cleaner evidence, only differently exposed.
- `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md` §4 and `docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md` (S-stage
  "Scientific gates"): historical results are **exploratory qualification only** (A29 historical triage); historical
  data "may be used for qualification only, under separate approval". No document forbids using 2019–2022 for the
  look; the S4 draft reserved it for specification sanity (no tuning). Choosing (b) removes that real-data sanity
  pass; specification checks then run on synthetic data only (`NEXT_LICENSED_DATA_STEP.md` §8).
- A19 §1 and §4 (held commit `8cb5c9e`): history "can qualify a candidate; it cannot confirm one, and it can never
  show the edge is current"; results labelled `HISTORICAL_EXPOSED`; a candidate restating an item of
  `research/governance/pre_existing_knowledge.json` is `REPLICATES_PRIOR_KNOWLEDGE` and "qualifies only on forward
  evidence". That file lists "Momentum historically looked better than Reversion", "1d historically looked stronger
  than 15m" and "A volatile historical slice looked stronger". HR-04 (daily momentum) restates the first two, in
  **either** window.
- The window must be chosen on these design grounds only. Choosing it from beliefs about which years favoured
  momentum would be outcome-informed selection.

## 5. Recommendation to the owner (a recommendation, not a decision)

1. **If X1 is run, preregister window (b), 2019-01-01 → 2026-08-18, as the single look**, with
   specification checks on synthetic data only. Window (a) gives a core power of about 0.34–0.45 and a full-rule
   power of about 0.01 at a true Sharpe of 1.0, so it would very likely spend the one exploratory look on an
   INCONCLUSIVE result. The cost of (b) is accepted knowingly: it dilutes an effect that emerged only recently
   (§4), mixes regimes and depends more on delisting handling.
2. Pair (b) with a preregistered **sub-period report** (2019–2022 and 2023-01-01 → 2026-08-18, descriptive) and the
   [PROP] **recency guard** (HAC t ≥ 1.0 on 2023-01-01 → 2026-08-18) as an additional NOMINATE condition, to limit
   nominations of an effect that has already decayed.
3. **Fix the readings PM-1 leaves open before any data** (outcome-free): the series of the 5-month concentration
   test (absolute vs active; it is the binding condition: full power on (b) at a Sharpe of 1.0 is about 0.19 vs
   0.54), the HAC threshold (2.0 vs 2.13), and the DSR N (logged variants vs A19's 10⁴).
4. **If the owner adopts A19's N = 10⁴ as a gate, do not run X1**: in neither window can a realistic effect pass;
   go to the prospective / fallback path (`NEXT_LICENSED_DATA_STEP.md` §9, F5) instead.
5. Whatever the window, a pass is "nominated" only. Because HR-04 replicates recorded pre-existing knowledge, the
   historical look adds little scientific weight (A19 §4 item 3); the decisive evidence remains a governed
   prospective test after the D1/D2 HOLD is lifted.

## 6. Owner decisions still open for RD-2

- Window (a) or (b) (§5 item 1), and whether to add the sub-period report and the recency guard.
- PM-1 readings: concentration series, HAC threshold, DSR N (§5 items 3–4); primary notion (c) confirmed.
- Turnover expectation and the delisting rule (first / last bar, −100 % stress) frozen in the preregistration.
- Whether X1 is worth running at all, given `REPLICATES_PRIOR_KNOWLEDGE` (§4) and the licence status (LIC-1, NOT
  SENT, NOT CLEARED).
- Acceptance of the §11 preregistration skeleton in `NEXT_LICENSED_DATA_STEP.md` (DRAFT, not frozen).
