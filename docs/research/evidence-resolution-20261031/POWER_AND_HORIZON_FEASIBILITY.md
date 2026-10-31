# Power and horizon feasibility (ERG-01 workstream G4)

**Status.** Documentation-only, read-only analytical assessment, written 2026-10-31 for the ERG-01 Evidence Resolution Gate.
- It runs no trading experiment, backtest, replay, simulation or calibration, and it executes no repository module. The calculator in `research/power/` was **read**, not run.
- It reads no trade-level data, no result dump and nothing after the 2026-08-19 research freeze (instant recorded in `research_freeze.json`). Every number below is either a governance parameter cited from a tracked file, or pure arithmetic on **hypothetical inputs typed in by hand** (§12 gives the code).
- It changes no parameter, admits nothing, consumes no alpha and authorises no test. Where power is inadequate it states the governance question for the owner (§11).
- **No profitability claim.** Insufficient power is not evidence of no edge, and adequate power is not evidence of an edge (`docs/strategy/EVIDENCE_LADDER_PARAMETERS.md:L157-161 @ 1432a90` · SOURCE_VERIFIED).

**Reading guide.**
- Every table marked **ILLUSTRATIVE** uses stated hypothetical inputs. No row is an observed variance, turnover, Sharpe ratio or correlation.
- σ (per-trade net standard deviation), n (trades per year), ρ (correlation), `deff` (design effect) and `lrv` (long-run variance ratio) are free parameters throughout.
- Citations use `path:Lx-Ly @ commit` plus an evidence class. Audit finding IDs (GOV-03, CON-44, STR-09 and others) refer to the 2026-10-31 audit baseline in [the reviewer evidence pack](../../audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md). They are distinguished from what this file verifies now.

## Contents
- [1. Summary of conclusions](#1-summary-of-conclusions)
- [2. Governing parameters](#2-governing-parameters)
- [3. Endpoint: per-trade expectancy vs portfolio-level returns](#3-endpoint-per-trade-expectancy-vs-portfolio-level-returns)
- [4. Effective sample size and dependence](#4-effective-sample-size-and-dependence)
- [5. Minimum detectable effect formulas](#5-minimum-detectable-effect-formulas)
- [6. Sample size: signals, executable trades, holding time, horizon](#6-sample-size-signals-executable-trades-holding-time-horizon)
- [7. Illustrative scenarios](#7-illustrative-scenarios)
- [8. Feasibility verdict for modest edges](#8-feasibility-verdict-for-modest-edges)
- [9. Proposed INCONCLUSIVE classification rule](#9-proposed-inconclusive-classification-rule)
- [10. Reconciliation with CON-44, GOV-03 and DR-7](#10-reconciliation-with-con-44-gov-03-and-dr-7)
- [11. Governance questions for the owner](#11-governance-questions-for-the-owner)
- [12. Reproducibility](#12-reproducibility)
- [13. NOT VERIFIED items and inconsistencies](#13-not-verified-items-and-inconsistencies)

## 1. Summary of conclusions

| ID | Conclusion | Class |
|---|---|---|
| G4-01 | α = 1/240 is the 5 % program familywise budget divided by 12 admissions per 3-year program (0.05 / 12 = 1/240), applied equally to MAIN and RESERVE. It is **not** derived from "≤ 3 simultaneous candidates". The A29–A34 source texts are not on GitHub and were not opened | SOURCE_VERIFIED (as restated in ELP and code); the A32 §4 original is NOT_VERIFIED |
| G4-02 | The governed claim is **one-sided** (μ > 0). A two-sided test at the same α would raise the MDE multiplier by 6.5 % (3.480 to 3.707) | SOURCE_VERIFIED (one-sidedness); INFERRED (arithmetic) |
| G4-03 | The governed endpoint is a daily HAC z on the **portfolio-level** mark-to-market net excess. The per-trade MDEs in A42/A45 are not that test (DR-11). Under linear aggregation the two share one noncentrality: SR_ann ≈ (μ/σ) · √(n_eff per year) | SOURCE_VERIFIED (endpoint); INFERRED (bridge) |
| G4-04 | At the 365-day final look and 80 % power, the minimum detectable annualized Sharpe ratio is **3.48** (normal theory, lrv 1) to **7.00** (A33 envelope plus α_cal shift, lrv 3); 9.04 at lrv 5 | INFERRED (formula SOURCE_VERIFIED in `ladder_power.py`) |
| G4-05 | Power within 365 days for a true SR_ann of 0.5 / 1.0 / 2.0 is at most 0.016 / 0.051 / 0.262 (best case: normal theory, lrv 1), and 0.003 / 0.014 / 0.115 under the A33 envelope mode | INFERRED |
| G4-06 | **The horizon, not the alpha allocation, is binding.** Even a single test at one-sided α = 0.05 has a 365-day MDE of SR 2.49. At α = 1/240, 80 % power needs about 3.0 years for SR 2 and about 12.1 years for SR 1 (lrv 1) | INFERRED |
| G4-07 | A per-trade edge of +0.1 % to +0.5 % is detectable in 365 days only when (μ/σ) · √n_eff ≥ 3.48–4.04, which is the same as an implied SR_ann ≥ 3.48–4.04. "Modest per trade" and "modest annualized" are therefore different hypotheses; only the first can ever be in reach, and only at high executable turnover | INFERRED |
| G4-08 | With 2 concurrent positions, executable trades per year are bounded by n ≤ 2 · 8760 · occupancy / h̄ (h̄ = mean holding hours). The time stops (15m 48/24/12 h, 4h 96/48/24 h, 1d 240/120/72 h) are **maxima**; the mean holding time is NOT_VERIFIED here | SOURCE_VERIFIED (capacity, time stops); INFERRED (bound) |
| G4-09 | Signal counts are not executable portfolio trades. Signals compete for 2 slots, a 2-hour symbol cooldown and one open trade per symbol; ≤ 3 candidates sharing those slots would split n further unless each has its own book | SOURCE_VERIFIED (limits); INFERRED (consequence); NOT_VERIFIED (book design) |
| G4-10 | No measured ICC, day-clustering design effect or long-run variance ratio exists (DR-10). Each is a free parameter; plausible values of 1.5–3 move the MDE by a factor of √1.5–√3 (1.22–1.73) | SOURCE_VERIFIED (gap); INFERRED |
| G4-11 | Frequency uncertainty matters: if realized n_eff is half the planned value, power at the planned MDE falls from 0.80 to 0.43. Regime-gated entry (STR-09) makes n regime-dependent | INFERRED |
| G4-12 | ≤ 20 % capital utilisation does not change a Sharpe ratio (scale-free) but fixes the economic size: annual return on capital ≈ n · μ / 10 with 2 slots of $50 on $500 | RUNTIME_VERIFIED (audit addendum, capacity); INFERRED (arithmetic) |
| G4-13 | No governed INCONCLUSIVE label exists in the files read. §9 proposes one (PROPOSED, not in force). Under it, a 365-day run at α = 1/240 with a minimum meaningful effect of SR 1 would end INCONCLUSIVE or ENCOURAGING with probability about 0.95 under a true SR of 0 or 1 | INFERRED |
| G4-14 | CON-44 is a difference of **assumption subsets**, not of formula: 3.5–5.0 matches normal theory at lrv 1–2 (3.48–4.92); 3.5–7.0 spans normal theory at lrv 1 to the A33 envelope at lrv 3 (3.48–7.00) | INFERRED |
| G4-15 | GOV-03 and DR-7 reproduce: 4.042 / 3.480 = 1.161 (about 16 % optimistic). Condition 4 of R0 (power at target across the whole declared range) cannot hold for SR ≤ 2 within 365 days under any documented critical-value mode | INFERRED |

**Bottom line (INFERRED).** The current A29 design cannot plausibly distinguish an annualized Sharpe ratio of 0.5–2 from noise within the 365-day maximum horizon. A per-trade net edge of +0.1 % to +0.5 % is distinguishable only in combinations of low σ, high executable turnover and low dependence that together imply SR_ann ≥ about 3.5. Whether such combinations apply to any candidate is unknown, because σ, n and dependence are unmeasured through an authorised route. The decision on horizon, endpoint, alpha allocation and candidate structure belongs to the owner (§11); none is changed here.

## 2. Governing parameters

### 2.1 Parameters as documented

| Parameter | Value | Citation | Class |
|---|---|---|---|
| Claim | SUPPORTED_WINDOW: μ_W > 0 for the mean daily mark-to-market net excess over the observed window; no persistence or deployment claim | `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md:L68 @ 1432a90` | SOURCE_VERIFIED (as restated from A31–A33) |
| Horizon | ≤ 365 days, no second-year extension | ELP `:L69 @ 1432a90`; `docs/governance/OWNER_OPERATING_CONTRACT.md:L35 @ c3bb74c`; `research/power/ladder_power.py:L25 @ 1432a90` | SOURCE_VERIFIED |
| Simultaneous candidates | ≤ 3 | ELP `:L70`; OOC `:L35` | SOURCE_VERIFIED |
| Reserve | 20 % of **slot-days**, not 20 % of alpha | ELP `:L71`; OOC `:L35` ("20% forward capacity reserved") | SOURCE_VERIFIED |
| Program FWER | 5 %, union bound under arbitrary dependence | ELP `:L72`; `ladder_power.py:L29`; OOC `:L35` | SOURCE_VERIFIED |
| Admissions | ≤ 12 per 3-year program; unused alpha forfeited; no recycling ("provisional" in A31) | ELP `:L73`; `ladder_power.py:L28` | SOURCE_VERIFIED |
| Alpha per admission | 1/240 for MAIN and RESERVE | ELP `:L74`; roadmap `docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md:L18 @ 23d1d88`; DFP `docs/governance/DEVELOPMENT_FIRST_POLICY.md:L84 @ 37fbaec` | SOURCE_VERIFIED |
| Calibration level | α_cal = α / 1.15 = 1/276; allocation stays 1/240; not validated | ELP `:L75`, DR-2 `:L97` | SOURCE_VERIFIED; status UNVALIDATED |
| Test statistic | HAC (Bartlett, L = 7) z of the daily net-excess mean | ELP `:L76` | SOURCE_VERIFIED |
| Looks | efficacy at day 365 only; futility z < 0 at days 182/273, non-binding | ELP `:L77`; DFP `:L84` ("final look only") | SOURCE_VERIFIED |
| ENCOURAGING | z ≥ 0.8416 at the final look; non-confirmatory; about 20 % null rate | ELP `:L79`; OOC `:L35` | SOURCE_VERIFIED |
| Critical value c | envelope maximum over generator set C at α_cal; **UNVALIDATED** (A31 in-sample 2.64 / 3.14 / 3.41 at α 1.25 / 0.42 / 0.21 %) | ELP `:L80`; `ladder_power.py:L72-86` | SOURCE_VERIFIED; status UNVALIDATED (DR-6) |
| Classification | Evidence Ladder is CONFIRMATORY-ONLY (D3), not a development gate | DFP `:L44`, `:L84` | SOURCE_VERIFIED |
| Holds | A29 ladder in force with D1/D2 HOLD (OOC); all governed experiments on HOLD (roadmap S5) | OOC `:L35`; roadmap `:L121` | SOURCE_VERIFIED; HOLD scope wording is CONTRADICTORY across documents (audit CON-36) |
| Weaker standards | "weaker standards are never adopted to rescue power" | roadmap `:L117 @ 23d1d88` | SOURCE_VERIFIED |

### 2.2 Where α = 1/240 comes from

**G4-01.** The derivation is a union (Bonferroni) split of the program familywise budget:

```
α_admission = FWER_program / max_admissions = 0.05 / 12 = 1/240 ≈ 0.4167 %
union bound: Σ α_j = 12 × 1/240 = 0.05, valid under arbitrary dependence between tests
```

- The two inputs are stated together in `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md:L72-74 @ 1432a90` (FWER 5 %, ≤ 12 admissions per 3-year program, 1/240 per admission) and as constants in `research/power/ladder_power.py:L28-29 @ 1432a90` (`PROGRAM_MAX_ADMISSIONS = 12`, `PROGRAM_FWER = Fraction(1, 20)`). The roadmap states "FWER 5 % over 12 admissions, α = 1/240 each" (`docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md:L18 @ 23d1d88`) · SOURCE_VERIFIED.
- The governing originals (A32 §4, A33 §7, A34-B §1) exist only at the local, unpushed commit `54a6369` (ELP `:L19`). Owner decision OD-1 holds their publication (`docs/strategy/S5_PWR_1_OWNER_DECISIONS.md:L47 @ 1432a90`), and four items in them are classified UNCERTAIN (ELP `:L41-48`). This file therefore does **not** open them: the original wording is NOT_VERIFIED by this workstream.
- **Not the candidate cap.** α does not depend on "≤ 3 simultaneous candidates". The cap limits concurrency; the alpha ledger counts admissions over the 3-year program. Three concurrent admissions consume 3/240 = 1/80 of the 5 % budget (INFERRED). The figure 1/80 also appears as one of the three α levels at which A31 reported envelope critical values (`ladder_power.py:L85`); the files read do not say why · INFERRED.
- **Reserve.** The 20 % reserve is of slot-days, and RESERVE admissions carry the same 1/240 as MAIN (ELP `:L71`, `:L74`). The earlier half-weight reserve (1/480; "0.21 %") is SUPERSEDED (DR-1, ELP `:L96`).
- **Calibration level.** The critical value is calibrated at α_cal = 1/276 while the ledger allocation stays 1/240 (ELP `:L75`). OD-3 keeps both 1/240 and 1/276 as labelled scenarios, not an approved standard (`S5_PWR_1_OWNER_DECISIONS.md:L49`) · SOURCE_VERIFIED.

### 2.3 One-sided vs two-sided testing

**G4-02.**
- The governed claim is one-sided: μ > 0 (ELP `:L68`). The screen "refuses non-positive or sign-straddling effects (the claim is one-sided, μ > 0)" (ELP `:L147`), and the MDE result records "one-sided, final look" (`ladder_power.py:L240 @ 1432a90`) · SOURCE_VERIFIED.
- Consequence for the multiplier at 80 % power (INFERRED, §12):

| Test | Critical z | z_{1−α} + z_{0.80} | Relative to one-sided |
|---|---|---|---|
| one-sided, α = 1/240 | 2.6383 | 3.4799 | 1.000 |
| one-sided, α_cal = 1/276 | 2.6853 | 3.5269 | 1.013 |
| two-sided, α = 1/240 (1/480 per tail) | 2.8653 | 3.7069 | 1.065 |

- A one-sided test cannot confirm a negative edge. Under the documented design, evidence of harm appears only through the non-binding futility looks (z < 0 at days 182/273, ELP `:L77`) and through descriptive reporting. That is appropriate for a "does it have positive net excess" claim; it also means a negative final z is a non-confirmation, not a proof of no edge.

## 3. Endpoint: per-trade expectancy vs portfolio-level returns

**What the governed test measures (SOURCE_VERIFIED).**
- The claim is about the mean **daily mark-to-market net excess** of the candidate's book over the window (ELP `:L68`), tested by a HAC z with Bartlett L = 7 (ELP `:L76`).
- The calculator's governed approximation returns the minimum detectable annualized Sharpe ratio (√365 scaling) of that daily series (ELP `:L114-116`; `ladder_power.py:L233-237 @ 1432a90`).
- The per-trade functions "reproduce the A42/A44/A45 planning arithmetic", carry `approximates_governed_test = False`, and "their units do not map onto" the governed test (ELP `:L124-127`). The unit mismatch is registered as gap DR-11 (ELP `:L106`).
- The reference series of "excess" (cash, a benchmark arm or a market return) is not defined in the files read: **NOT_VERIFIED** (blocker: the A31–A33 originals are not opened, §2.2).

**A bridge between the two units (INFERRED, planning only).** Let a candidate's executable book close n trades in T years, with per-trade net return r_i (fraction of the position notional), mean μ and standard deviation σ, each position carrying weight w of capital.
- The window's cumulative net P&L is w · Σ r_i. The daily mark-to-market series d_t telescopes to the same total, so its mean over the window is fixed by the trades.
- If the long-run variance of d_t captures all dependence, Var(Σ d_t) ≈ w² · σ² · n · deff_total, where deff_total collects within-day clustering and cross-day dependence.
- Then the daily z is approximately √n · (μ/σ) / √deff_total, and since z ≈ SR_ann · √T / √lrv:

```
SR_ann ≈ (μ / σ) · √(n_per_year / deff_total)        (w cancels: a Sharpe ratio is scale-free)
```

- **Caveats.** (a) Mark-to-market swings of open positions that cancel by exit add daily variance and negative autocorrelation; Bartlett L = 7 days is shorter than the 1d maximum hold of 240 h (10 days, §6.3), so part of that cancellation may not be captured. (b) Idle days contribute zero to mean and variance alike. (c) The excess reference is unknown (above). (d) Costs shift μ: the owner standard is 0.10 % per side plus spread and slippage (`docs/governance/OWNER_OPERATING_CONTRACT.md:L10 @ c3bb74c` · SOURCE_VERIFIED), while the tracker books a flat 0.30 % (roadmap `:L13`; `docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md:L292 @ 5d977f2` · RUNTIME_VERIFIED).
- The bridge is consistent with DR-11: it is not a documented mapping, only an approximation that holds when trade P&L aggregates linearly and the HAC estimator captures the dependence.

**Per-signal expectancy vs executed-portfolio expectancy (INFERRED).**
- A per-trade hypothesis can be stated over **all signals** (requiring outcomes for non-executed signals through a calibrated counterfactual replay, the A44/A48 prerequisite in roadmap `:L113`) or over the **executed book** (capacity-limited Paper trades).
- These are different estimands. Executed trades are a non-random subset: the live path takes one signal per cycle after ordering by spread and other keys, and the candidate set is truncated alphabetically (audit UNI-18, UNI-16 · SOURCE_VERIFIED in the audit, not re-verified here). A positive per-signal edge does not imply the same executed-portfolio edge, and vice versa.
- The governed endpoint is the executed book's daily series. A per-signal endpoint would need its own preregistration and mapping (owner question Q2, §11).

## 4. Effective sample size and dependence

**Design effect for clustered trades (per-trade statistics).**

```
n_eff = n / deff,   deff = 1 + (m − 1) · ρ      (equal variances, exchangeable correlation only)
conservative bound for any within-cluster correlation: deff ≤ max cluster size m_max
```

- The exchangeable formula is "valid only for equal variances and exchangeable correlation"; heteroskedastic clusters can exceed it (ELP `:L179`). The count-only bound max(m) needs zero covariance between clusters and must count all trades of all arms in a cluster (ELP `:L173-178`) · SOURCE_VERIFIED.

**Serial dependence (daily endpoint).**

```
lrv = 1 + 2 · Σ_{k≥1} ρ_k        (long-run variance / variance of the daily series)
AR(1) with coefficient φ:  lrv = (1 + φ) / (1 − φ)
```

- For the daily endpoint, within-day clustering is already inside the daily variance; what inflates the variance of the mean is correlation **across** days, entered as `lrv_ratio` (ELP `:L180-183`) · SOURCE_VERIFIED.

**Sources of dependence specific to this book (INFERRED).**
- **Cross-asset clustering.** Crypto spot returns share a common market factor. With at most 2 concurrent positions, a day on which both are open has variance proportional to 2 · (1 + ρ_pair) instead of 2, so the two positions carry 2 / (1 + ρ_pair) independent bets. ρ_pair is not measured.
- **Overlapping holds.** Positions held over several days create cross-day covariance; the per-trade cluster bounds "no longer hold, and the per-trade MDE can be optimistic by an unknown factor" (ELP `:L184` · SOURCE_VERIFIED).
- **Regime clustering.** If an edge exists only in some market states, the information is the number of regime episodes, not trades. The register already marks A45 H1 inadmissible because its effective n is the episode count (`docs/strategy/S5_PWR_1_OWNER_DECISIONS.md:L34 @ 1432a90` · SOURCE_VERIFIED). The momentum entry requires a bullish regime (audit STR-09 · SOURCE_VERIFIED in the audit), so trade arrivals themselves cluster in time; persistent regimes make lrv > 1.
- **No measurement exists.** "No ICC or day-clustering model is documented"; the design effects assumed in planning documents were 1 / 1.5 (A30), 2–3 (A42) and 3–10 (A45) (DR-10, ELP `:L105` · SOURCE_VERIFIED). Measuring them on the sealed stream needs a separate authorisation (OD-7, `S5_PWR_1_OWNER_DECISIONS.md:L53`).

**ILLUSTRATIVE dependence factors** (hypothetical m, ρ and φ; §12):

| m (trades per cluster) | ρ = 0.1 | ρ = 0.3 | ρ = 0.5 | ρ = 0.8 |
|---|---|---|---|---|
| 2 | 1.10 | 1.30 | 1.50 | 1.80 |
| 3 | 1.20 | 1.60 | 2.00 | 2.60 |
| 5 | 1.40 | 2.20 | 3.00 | 4.20 |

| AR(1) φ of the daily series | 0.1 | 0.2 | 0.3 | 0.5 |
|---|---|---|---|---|
| lrv = (1 + φ)/(1 − φ) | 1.222 | 1.500 | 1.857 | 3.000 |

The MDE scales with √deff or √lrv: a factor of 1.5 adds 22 %, a factor of 3 adds 73 % (G4-10).

## 5. Minimum detectable effect formulas

All forms are one-sided, normal-approximation, final look only (INFERRED derivation; the daily form is SOURCE_VERIFIED in `ladder_power.py:L233-248 @ 1432a90`).

```
k = c + z_{1−β}               c = z_{1−α_cal} (normal theory) or an envelope critical value

Per-trade, one sample:        MDE_μ  = k · σ / √n_eff,          n_eff = n / deff
Per-trade, two arms:          MDE_Δ  = k · σ · √(deff · (1/n1 + 1/n2))       (ELP :L126)
Required trades:              n      = deff · (k · σ / μ)²
Annualized Sharpe (daily):    SR_MDE = k · √lrv / √T_years       (T_years = days / 365 ≤ 1)
Power at true SR:             power  = Φ(SR · √T_years / √lrv − c)
Horizon for target power:     T      = (k · √lrv / SR)²
Bridge (§3):                  SR_ann ≈ (μ / σ) · √(n_per_year / deff_total)
```

**Multipliers k at 80 % power (z_{0.80} = 0.8416).** Values of c are cited from `ladder_power.py:L72-86` and ELP DR-6/DR-7; the arithmetic is INFERRED (§12).

| Critical-value mode | c | k | Status of c |
|---|---|---|---|
| NORMAL_THEORY, α = 1/240 | 2.6383 | 3.480 | analytic, not envelope-calibrated |
| NORMAL_THEORY, α_cal = 1/276 | 2.6853 | 3.527 | analytic, calibration level not validated |
| A31_ENVELOPE_IN_SAMPLE (1/240) | 3.14 | 3.982 | PROVISIONAL, in-sample, unvalidated |
| A33_ENVELOPE_PLUS_ALPHA_CAL_SHIFT | 3.20 | 4.042 | interpolated, unvalidated |

- Normal theory reproduces the 3.48 used in A30 §6, A42 and A45 (DR-7, ELP `:L102`). The envelope modes raise c because the governed test is calibrated against a set of non-normal generators (ELP `:L80`).
- The calculator documents that the normal approximation slightly understates simulated power under the envelope modes (0.42–0.44 against a simulated 0.46–0.56 at a true SR of 3; ELP `:L122` · HISTORICAL_REPORTED, synthetic). This file's arithmetic gives 0.444 (c = 3.14) and 0.421 (c = 3.20) at SR 3, lrv 1, which matches that statement (INFERRED).

## 6. Sample size: signals, executable trades, holding time, horizon

### 6.1 Limits on the executable book (as cited)

| Limit | Value | Citation | Class |
|---|---|---|---|
| Concurrent positions | effective capacity min(10, 2) = 2 | `docs/audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md:L104 @ 5d977f2` (VER-12); RSK-02, RSK-03 | RUNTIME_VERIFIED (audit) |
| Position size and capital | 2 positions of $50 on $500, utilisation at most 20 % | same addendum `:L292` | RUNTIME_VERIFIED (audit) |
| Symbol cooldown | 2 hours after any signal (`COOLDOWN_SQL`) | `signal_engine/signal_logic.py:L25-26 @ ea8ae4f` | SOURCE_VERIFIED |
| One open trade per symbol | engine excludes symbols with an open trade | audit UNI-18 (`REVIEWER_EVIDENCE_PACK.md:L700 @ 5d977f2`) | SOURCE_VERIFIED (audit) |
| Signals per cycle | one signal per ~60 s cycle on the live path; no daily cap | audit UNI-18 | SOURCE_VERIFIED (audit) |
| Time stops (max / T1-stall / no-T1 hours) | 15m 48 / 24 / 12; 4h 96 / 48 / 24; 1d 240 / 120 / 72; other timeframes 48 / 24 / 24 | `shared/triple_barrier.py:L31-33, L38-42 @ bb7825f` (identical lines at `ea8ae4f`) | SOURCE_VERIFIED |
| Trade amount, flat cost defaults | $50; 0.003 round trip | `shared/triple_barrier.py:L34, L36 @ bb7825f` | SOURCE_VERIFIED |

The function returning the triple is documented as "max, T1-stall and no-T1 hours" (`shared/triple_barrier.py:L45-46 @ bb7825f` · SOURCE_VERIFIED). These are **upper limits on holding time**, not averages: a trade can end at its stop or a target within minutes.

### 6.2 Signal count vs executable portfolio trades (INFERRED)

- The signal engine can emit up to one signal per cycle, so the **signal** count is not limited by capacity. The **executed** count is limited by the two slots, the cooldown and the one-per-symbol rule.
- With many symbols, the 2-hour cooldown binds per symbol, not on the portfolio. The binding portfolio constraint is the two slots.
- **Capacity bound.** With K = 2 slots, mean holding time h̄ hours and occupancy (fraction of time slots are filled) q:

```
n_executable per year ≤ K · 8760 · q / h̄          (equality at occupancy q)
```

- Historical maximum capacity-constrained counts can be derived only as upper bounds from this expression; this file quotes no observed trade count, occupancy or mean holding time.
- **Sharing among candidates.** OOC §4 allows ≤ 3 simultaneous candidates (`OWNER_OPERATING_CONTRACT.md:L35`). If candidates share the same two Paper slots, each candidate's n falls roughly in proportion to its share of slot-time. If each has a separate virtual book, or if non-executed signals are evaluated through calibrated counterfactual replay (the A45 H2 protocol uses this for capacity- or cooldown-excluded setups, `docs/a45/A45_SETUP_RESEARCH.md:L166 @ f95e01d` · DOCUMENTED_ONLY), n is not split, but the endpoint changes (§3). Which design applies is **NOT_VERIFIED**: no governed book design for concurrent candidates is in the files read.

### 6.3 Maximum vs average holding time (INFERRED)

**ILLUSTRATIVE full-occupancy throughput** (K = 2; hypothetical h̄ and q):

| Mean holding h̄ | q = 1.0 | q = 0.5 | q = 0.25 | Matches |
|---|---|---|---|---|
| 2 h | 8760 | 4380 | 2190 | |
| 6 h | 2920 | 1460 | 730 | |
| 12 h | 1460 | 730 | 365 | 15m no-T1 stop |
| 24 h | 730 | 365 | 182.5 | 15m T1-stall, 4h no-T1 |
| 48 h | 365 | 182.5 | 91.2 | 15m max, 4h T1-stall |
| 96 h | 182.5 | 91.2 | 45.6 | 4h max |
| 240 h | 73 | 36.5 | 18.2 | 1d max |

- If every trade ran to its timeframe's maximum and slots were always full, a pure 15m book would close 365 trades a year, a 4h book 182.5 and a 1d book 73. Because averages are below maxima, real throughput can be higher; because occupancy is below 1 and entries are regime-gated, it can be lower. **The mean holding time and occupancy are NOT_VERIFIED** (blocker: they need trade-level data, outside this phase, and any post-freeze value is sealed under OD-7).
- Trade counts from A42 l.238 and A45 l.169 are annualised from observed windows. Count withheld (window not verified pre-freeze). Their σ = 1.5 % is labelled an **assumption** in both documents (`docs/a42/A42_STRATEGY_SIGNAL_QUALITY.md:L238 @ 675f7d1`; `docs/a45/A45_SETUP_RESEARCH.md:L169 @ f95e01d` · DOCUMENTED_ONLY), not an observation.

### 6.4 Annual trade-frequency uncertainty (INFERRED)

- n is random and regime-dependent. Planning on an expected n overstates power when the realized n_eff is lower. For an effect equal to the MDE at the planned n (normal theory, α = 1/240, 80 % target):

| Realized n_eff / planned | 1.00 | 0.75 | 0.50 | 0.25 |
|---|---|---|---|---|
| Power | 0.800 | 0.646 | 0.430 | 0.185 |

- Planning should therefore use a preregistered **lower** bound on n_eff, and the final classification should record whether that bound was met (§9).

### 6.5 The 365-day maximum horizon

- The horizon is a hard upper limit: "≤ 365 days, no second-year extension" (ELP `:L69`), enforced in the calculator (`ladder_power.py:L25`, refusal in `_daily_core` at `:L224-230`) · SOURCE_VERIFIED.
- For the daily endpoint the MDE falls only as 1/√T, so 365 days is the most favourable case the governance allows. A shorter window (for example a reserve admission started late) can only raise the MDE. A shorter planning horizon "does not imply confirmation readiness" (ELP `:L117`).

### 6.6 Two simultaneous positions and ≤ 20 % utilisation (INFERRED)

- **Sharpe is unaffected by scale.** Holding 2 × $50 on $500 scales mean and standard deviation of the daily series by the same weight, so the governed z and the SR MDE do not depend on utilisation.
- **Concurrency limits diversification.** With at most 2 positions, the book cannot average many simultaneous bets; per-day variance is that of ≤ 2 correlated positions (§4).
- **Economic magnitude is small.** Annual net return on capital ≈ n · $50 · μ / $500 = n · μ / 10:

| ILLUSTRATIVE μ per trade | n = 73 | n = 182.5 | n = 365 | n = 730 | n = 1460 |
|---|---|---|---|---|---|
| +0.1 % | 0.73 % | 1.82 % | 3.65 % | 7.30 % | 14.6 % |
| +0.2 % | 1.46 % | 3.65 % | 7.30 % | 14.6 % | 29.2 % |
| +0.5 % | 3.65 % | 9.12 % | 18.3 % | 36.5 % | 73.0 % |

These are arithmetic identities on hypothetical μ and n, not projections.

## 7. Illustrative scenarios

**Every table in this section is ILLUSTRATIVE.** Inputs are hypothetical and typed in by hand: lrv ∈ {1, 1.5, 2, 3, 5}; deff ∈ {1, 2, 3, 5}; σ ∈ {1, 1.5, 2, 3} % per trade (net); n from 50 to 2000 trades a year; true SR_ann from 0.5 to 4. None is an observed value. All are one-sided, final look only, normal approximation, 80 % target power unless stated (INFERRED; code in §12).

### 7.1 Scenario A: minimum detectable annualized Sharpe at 365 days

| Mode (k) | lrv 1 | lrv 1.5 | lrv 2 | lrv 3 | lrv 5 |
|---|---|---|---|---|---|
| NORMAL_THEORY 1/240 (3.480) | **3.480** | 4.262 | 4.921 | 6.027 | 7.781 |
| NORMAL_THEORY 1/276 (3.527) | 3.527 | 4.320 | 4.988 | 6.109 | 7.886 |
| A31 envelope 3.14 (3.982) | 3.982 | 4.876 | 5.631 | 6.896 | 8.903 |
| A33 envelope + shift 3.20 (4.042) | 4.042 | 4.950 | 5.716 | **7.000** | 9.037 |

The lrv columns 1 / 1.5 / 2 / 3 are those of the calculator's canonical table (`ladder_power.py:L337-352 @ 1432a90`); lrv 5 is added here.

### 7.2 Scenario B: power within 365 days for a true annualized Sharpe

| Mode, lrv | SR 0.5 | SR 1.0 | SR 1.5 | SR 2.0 | SR 3.0 | SR 4.0 |
|---|---|---|---|---|---|---|
| NORMAL_THEORY 1/240, lrv 1 | 0.016 | 0.051 | 0.128 | 0.262 | 0.641 | 0.913 |
| NORMAL_THEORY 1/240, lrv 2 | 0.011 | 0.027 | 0.057 | 0.110 | 0.303 | 0.575 |
| NORMAL_THEORY 1/240, lrv 3 | 0.009 | 0.020 | 0.038 | 0.069 | 0.182 | 0.371 |
| A31 envelope 3.14, lrv 1 | 0.004 | 0.016 | 0.051 | 0.127 | 0.444 | 0.805 |
| A33 envelope 3.20, lrv 1 | 0.003 | 0.014 | 0.045 | 0.115 | 0.421 | 0.788 |
| A33 envelope 3.20, lrv 3 | 0.002 | 0.004 | 0.010 | 0.020 | 0.071 | 0.187 |

For SR 0.5–1.0 the power is close to the size of the test itself (1/240 ≈ 0.004), that is, the test barely distinguishes these effects from zero.

### 7.3 Scenario C: horizon needed for 80 % power (beyond the 365-day limit, for scale only)

| Mode, lrv | SR 0.5 | SR 1.0 | SR 1.5 | SR 2.0 |
|---|---|---|---|---|
| NORMAL_THEORY 1/240, lrv 1 | 48.4 y | 12.1 y | 5.4 y | 3.0 y |
| NORMAL_THEORY 1/240, lrv 2 | 96.9 y | 24.2 y | 10.8 y | 6.1 y |
| A33 envelope 3.20, lrv 1 | 65.3 y | 16.3 y | 7.3 y | 4.1 y |
| A33 envelope 3.20, lrv 2 | 130.7 y | 32.7 y | 14.5 y | 8.2 y |

### 7.4 Scenario D: alpha sensitivity at lrv 1 (is alpha or horizon binding?)

| One-sided α | k | 365-day SR MDE | Power SR 1, 1 y | Power SR 2, 1 y | Years for SR 1 | Years for SR 2 |
|---|---|---|---|---|---|---|
| 1/240 (governed) | 3.480 | 3.48 | 0.051 | 0.262 | 12.1 | 3.03 |
| 1/60 (0.05 / 3) | 2.970 | 2.97 | 0.130 | 0.449 | 8.8 | 2.20 |
| 0.05 (single test) | 2.486 | 2.49 | 0.260 | 0.639 | 6.2 | 1.55 |

- **G4-06.** Even spending the entire 5 % program budget on one test leaves the 365-day MDE at SR 2.49. Alpha reallocation cannot bring SR ≤ 2 to 80 % power within 365 days. The binding constraint is the horizon (INFERRED).
- Cross-check: `docs/strategy/S4_PHASE1_SCIENTIFIC_COMPARISON.md:L99 @ f6dcae1` states power for SR 1.0 at α = 0.05/3 of "about 0.76" over 8 years and "about 0.13" over one year · DOCUMENTED_ONLY. This file's arithmetic reproduces 0.758 and 0.130 (INFERRED).

### 7.5 Scenario E: per-trade MDE in units of σ, k / √(n / deff)

| n trades | Mode | deff 1 | deff 2 | deff 3 | deff 5 |
|---|---|---|---|---|---|
| 100 | NT 1/240 | 0.348 σ | 0.492 σ | 0.603 σ | 0.778 σ |
| 250 | NT 1/240 | 0.220 σ | 0.311 σ | 0.381 σ | 0.492 σ |
| 500 | NT 1/240 | 0.156 σ | 0.220 σ | 0.270 σ | 0.348 σ |
| 1000 | NT 1/240 | 0.110 σ | 0.156 σ | 0.191 σ | 0.246 σ |
| 2000 | NT 1/240 | 0.078 σ | 0.110 σ | 0.135 σ | 0.174 σ |
| 100 | A33 env 3.20 | 0.404 σ | 0.572 σ | 0.700 σ | 0.904 σ |
| 500 | A33 env 3.20 | 0.181 σ | 0.256 σ | 0.313 σ | 0.404 σ |
| 2000 | A33 env 3.20 | 0.090 σ | 0.128 σ | 0.157 σ | 0.202 σ |

Multiply by a hypothetical σ to obtain percent per trade; for example n = 500, deff 1, σ = 1.5 % gives 0.233 % (NT) or 0.271 % (A33 envelope).

### 7.6 Scenario F: trades required for a per-trade net edge (deff = 1; multiply by deff)

| σ per trade | Mode | μ = +0.1 % | μ = +0.2 % | μ = +0.3 % | μ = +0.5 % |
|---|---|---|---|---|---|
| 1.0 % | NT 1/240 | 1211 | 303 | 135 | 48 |
| 1.5 % | NT 1/240 | 2725 | 681 | 303 | 109 |
| 2.0 % | NT 1/240 | 4844 | 1211 | 538 | 194 |
| 3.0 % | NT 1/240 | 10899 | 2725 | 1211 | 436 |
| 1.0 % | A33 env 3.20 | 1633 | 408 | 181 | 65 |
| 1.5 % | A33 env 3.20 | 3675 | 919 | 408 | 147 |
| 2.0 % | A33 env 3.20 | 6534 | 1633 | 726 | 261 |
| 3.0 % | A33 env 3.20 | 14701 | 3675 | 1633 | 588 |

**Maximum mean holding time that delivers those trades in 365 days** at full occupancy with 2 slots (2 · 8760 / n_required; deff = 1):

| σ per trade | Mode | μ = +0.1 % | μ = +0.2 % | μ = +0.3 % | μ = +0.5 % |
|---|---|---|---|---|---|
| 1.0 % | NT 1/240 | 14.5 h | 57.9 h | 130.2 h | 361.7 h |
| 1.5 % | NT 1/240 | 6.4 h | 25.7 h | 57.9 h | 160.8 h |
| 2.0 % | NT 1/240 | 3.6 h | 14.5 h | 32.6 h | 90.4 h |
| 3.0 % | NT 1/240 | 1.6 h | 6.4 h | 14.5 h | 40.2 h |
| 1.5 % | A33 env 3.20 | 4.8 h | 19.1 h | 42.9 h | 119.2 h |

With deff > 1 or occupancy below 1, divide these hours by deff and multiply by occupancy.

### 7.7 Scenario G: the bridge, implied SR_ann = (μ/σ) · √n_eff per year

| σ, μ per trade | n_eff 73 | 182.5 | 365 | 730 | 1460 |
|---|---|---|---|---|---|
| σ 1.0 %, μ +0.1 % | 0.85 | 1.35 | 1.91 | 2.70 | 3.82 |
| σ 1.5 %, μ +0.1 % | 0.57 | 0.90 | 1.27 | 1.80 | 2.55 |
| σ 1.5 %, μ +0.2 % | 1.14 | 1.80 | 2.55 | 3.60 | 5.09 |
| σ 1.5 %, μ +0.5 % | 2.85 | 4.50 | 6.37 | 9.01 | 12.74 |
| σ 3.0 %, μ +0.2 % | 0.57 | 0.90 | 1.27 | 1.80 | 2.55 |
| σ 3.0 %, μ +0.5 % | 1.42 | 2.25 | 3.18 | 4.50 | 6.37 |

The n_eff columns 73 / 182.5 / 365 equal the full-occupancy throughputs at the 1d, 4h and 15m maximum holds (§6.3). A cell is detectable at 80 % power in 365 days only when it is ≥ 3.48 (NT, lrv 1) to ≥ 4.04 (A33 envelope); this is the same statement as Scenario F.

## 8. Feasibility verdict for modest edges

**Annualized Sharpe 0.5–2 (INFERRED).**
- Within 365 days the current design has power ≤ 0.262 for SR 2 and ≤ 0.051 for SR 1 in the most favourable documented case (normal theory, lrv 1), and lower under every envelope mode or lrv > 1 (Scenario B).
- 80 % power would need 3.0–8.2 years for SR 2 and 12.1–32.7 years for SR 1 across the documented modes at lrv 1–2 (Scenario C). The governance forbids a second year (ELP `:L69`).
- **Verdict: the A29 design cannot plausibly distinguish SR 0.5–2 from noise within 365 days.** This agrees with the existing DFP statement that "no realistic daily strategy can be confirmed in one window" (`docs/governance/DEVELOPMENT_FIRST_POLICY.md:L114 @ 37fbaec` · DOCUMENTED_ONLY).

**Per-trade net +0.1 % to +0.5 % (INFERRED).**
- Detectable only when (μ/σ) · √n_eff ≥ k. At σ = 1.5 % and deff = 1, +0.1 % needs 2725–3675 trades (mean holding ≤ 4.8–6.4 h at full occupancy), +0.2 % needs 681–919 (≤ 19–26 h), +0.5 % needs 109–147 (≤ 119–161 h) (Scenario F).
- These requirements are tighter by a factor deff and 1/occupancy, and the corresponding implied SR_ann is ≥ 3.48–4.04 by construction (Scenario G).
- **Verdict: a per-trade edge of +0.3 % to +0.5 % at σ ≈ 1–1.5 % with a few hundred weakly dependent executed trades is within arithmetic reach of a 365-day test; +0.1 % is not, unless σ is near 1 %, the mean holding time is at most about 14.5 h at full occupancy, and dependence is negligible.** Whether any candidate has such σ, turnover and dependence is NOT_VERIFIED, and must not be estimated from protected or research-exposed outcomes (ELP `:L161`).
- **Consistency.** A per-trade edge large enough to pass is equivalent to an annualized Sharpe of about 3.5 or more on the executed book. The two verdicts above therefore do not conflict: "+0.2 % per trade" is modest in percent but, if it held at 700+ independent trades a year, would be a large Sharpe ratio.

**Implication for R0 (INFERRED).** Condition 4 of the common reconsideration gate requires power at or above target "for the **whole** declared effect and dependence range" (`docs/strategy/S5_PWR_1_OWNER_DECISIONS.md:L23 @ 1432a90`). No declared range with SR ≤ 2 can meet it within 365 days under any documented critical-value mode, independently of conditions 1–3.

## 9. Proposed INCONCLUSIVE classification rule

**Status: PROPOSED for owner decision (Q6, §11); not in force.** The files read define SUPPORTED_WINDOW (ELP `:L68`), ENCOURAGING (non-confirmatory, ELP `:L79`) and non-binding futility looks (ELP `:L77`), and they state that "insufficient power is not evidence of no edge" (ELP `:L158`). They define no INCONCLUSIVE outcome and no minimum meaningful effect · SOURCE_VERIFIED for the files read; NOT_VERIFIED for the A29–A34 originals (§2.2). The roadmap's finding label "INSUFFICIENT EVIDENCE" (`docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md:L22 @ 23d1d88`) is a finding label, not a test outcome.

**Preregistered before the window** (all written down; none estimated from protected or research-exposed outcomes, ELP `:L161`):
- δ_min, the minimum economically meaningful effect in the endpoint's own units (SR_ann for the daily endpoint, net μ per trade for a per-trade endpoint);
- α, the critical-value mode and its status, target power, horizon T ≤ 365 days;
- planning ranges for lrv (and deff for per-trade endpoints) and the lower bound n_eff,min used in the power analysis;
- α_f, the level of the one-sided upper confidence bound used to reject δ_min (an owner choice, for example equal to α or 0.05).

**Classification at the final look, applied in order:**

1. **INVALID**: a declared invalidation condition occurred (version boundary, integrity failure, change to exits, costs or the counterfactual model during the window; for example `docs/a45/A45_SETUP_RESEARCH.md:L172 @ f95e01d`). Not a statistical outcome.
2. **SUPPORTED_WINDOW**: z ≥ c and every gate passes (existing rule).
3. **NOT_SUPPORTED_AT_δ_min**: z < c, the realized n_eff ≥ n_eff,min, **and** the upper bound is below δ_min:

```
SR_UCB = (z + z_{1−α_f}) · √lrv_hat / √T_years  <  δ_min        (daily endpoint)
μ_UCB  = μ_hat + z_{1−α_f} · SE_HAC(μ_hat)       <  δ_min        (per-trade endpoint)
```

   This is the only outcome that counts against an edge of at least δ_min. It says nothing about edges smaller than δ_min.
4. **INCONCLUSIVE**: every other case, namely z < c with an upper bound ≥ δ_min; or realized n_eff < n_eff,min; or a preregistered power at δ_min below target (then INCONCLUSIVE is the expected label from the outset, and admitting the candidate means "spending alpha on underpowered tests", the risk named in roadmap `:L118`). ENCOURAGING (z ≥ 0.8416) is a **flag** on an INCONCLUSIVE result, never a pass.

- A stop at a non-binding futility look is classified by the same rule with the data available at that look. The admission's alpha is consumed either way (unused alpha is forfeited, ELP `:L73`).
- None of the four labels is a statement about future profitability.

**ILLUSTRATIVE label probabilities** for a 365-day window (normal theory, α = 1/240, lrv 1; z ~ N(SR · √T / √lrv, 1); hypothetical δ_min and α_f; INFERRED, §12):

| δ_min | α_f | True SR | SUPPORTED | ENCOURAGING flag | INCONCLUSIVE, no flag | NOT_SUPPORTED_AT_δ_min |
|---|---|---|---|---|---|---|
| 1.0 | 1/240 | 0 | 0.004 | 0.196 | 0.749 | 0.051 |
| 1.0 | 1/240 | 1.0 | 0.051 | 0.512 | 0.433 | 0.004 |
| 1.0 | 1/240 | 2.0 | 0.262 | 0.615 | 0.123 | 0.000 |
| 1.0 | 0.05 | 0 | 0.004 | 0.196 | 0.540 | 0.260 |
| 2.0 | 1/240 | 0 | 0.004 | 0.196 | 0.538 | 0.262 |
| 2.0 | 0.05 | 0 | 0.004 | 0.196 | 0.161 | 0.639 |
| 2.0 | 0.05 | 2.0 | 0.262 | 0.615 | 0.073 | 0.050 |

- **G4-13.** With δ_min = SR 1 and α_f = 1/240, about 95 % of 365-day runs end INCONCLUSIVE (with or without the ENCOURAGING flag) whether the true SR is 0 or 1. A one-year window can neither confirm nor reject a modest edge.
- ENCOURAGING's documented "about 20 % null rate" (ELP `:L79`) reproduces: P(z ≥ 0.8416 | SR = 0) = 0.200 (INFERRED).

## 10. Reconciliation with CON-44, GOV-03 and DR-7

### 10.1 CON-44 (MDE ≈ 3.5–5.0 vs ≈ 3.5–7.0)

| Statement | Source | Class |
|---|---|---|
| "A 365-day annualized Sharpe MDE is ≈ 3.5–5.0 (illustrative)" | `docs/lab/REVIEW_PACKAGE_R1_QUANT.md:L19 @ 3e7324d` | DOCUMENTED_ONLY |
| "The 365-day daily-HAC Sharpe MDE is ≈ 3.5–7.0 (`research/power`, illustrative)" | `docs/governance/DEVELOPMENT_FIRST_POLICY.md:L114 @ 37fbaec` | DOCUMENTED_ONLY |
| Audit: CONTRADICTORY | CON-44 (`REVIEWER_EVIDENCE_PACK.md:L1497 @ 5d977f2`) | audit baseline |

**G4-14 (INFERRED).** Both ranges come from the same formula (c + z_{0.80}) · √lrv at 365 days (Scenario A):
- **3.5–5.0** matches normal theory at lrv 1–2 (3.48–4.92), or an envelope mode at lrv 1–1.5 (3.98–4.95).
- **3.5–7.0** matches the full non-superseded grid of the canonical table: normal theory at lrv 1 (3.48) to the A33 envelope plus shift at lrv 3 (7.00).
- Superseded half-weight reserve levels (1/480, DR-1) would extend the grid to about 7.36 (A31 in-sample 3.41 at lrv 3); they are excluded as SUPERSEDED.
- **Resolution.** The texts disagree only because neither states its lrv and critical-value assumptions. The arithmetic is not contradictory. The wider statement is the complete one for the documented grid; the lower end of 3.5 holds only with no serial dependence and an unvalidated normal-theory critical value. Both remain illustrative until a critical value is validated (OD-5, `S5_PWR_1_OWNER_DECISIONS.md:L51`).

### 10.2 GOV-03 ("None of these conditions can hold today") and DR-7

- **DR-7 reproduces (G4-15, INFERRED).** (3.20 + 0.8416) / (2.6383 + 0.8416) = 4.042 / 3.480 = 1.161: planning MDEs built on 3.48 are about 16 % optimistic against the latest documented calibration (ELP `:L102` · SOURCE_VERIFIED; audit GOV-03).
- **The four conditions** for `reconsideration_eligible` (ELP `:L149-155`; R0 in `S5_PWR_1_OWNER_DECISIONS.md:L19-25`), checked against this analysis:

| Condition | Status today | Class |
|---|---|---|
| 1. daily HAC endpoint | satisfiable by choice of endpoint | INFERRED |
| 2. governance-confirmed alpha scenario | not met: OD-3 keeps 1/240 and 1/276 as labelled scenarios | SOURCE_VERIFIED |
| 3. independently validated critical value | not met: A33 validation never run, A34-B REVISE, OD-5 | SOURCE_VERIFIED (as documented) |
| 4. power at target over the whole declared range | not met for any declared range with SR ≤ 2 within 365 days, under every documented mode (Scenarios A–D) | INFERRED |

- GOV-03's conclusion ("nothing has passed the ladder") stands, and this file adds a structural reason: even if conditions 2 and 3 were resolved, condition 4 would still fail for modest annualized edges within the horizon.
- **Wording note.** Read literally, "None of these conditions can hold today" overstates: condition 1 is a design choice that can hold. What cannot hold today is the conjunction. This is a minor imprecision, not a change of substance (INFERRED).

## 11. Governance questions for the owner

This file changes no parameter. The questions below are stated so the owner can decide them; none is a recommendation to run or authorise a test. Existing proposal OD-DF-2 ("longer prospective windows, a multi-candidate design, or long licence-cleared history for qualification plus a short prospective sanity check", `docs/governance/DEVELOPMENT_FIRST_POLICY.md:L114 @ 37fbaec`) already covers Q1–Q3 in part.

| ID | Question | Why it is needed (this file) |
|---|---|---|
| Q1 Horizon | Does the 365-day maximum (OOC §4; ELP `:L69`) remain the limit for confirmatory admissions whose declared effect range is at or below SR_ann 2, given that 80 % power at α = 1/240 needs about 3–8 years for SR 2 and 12–33 years for SR 1? If it remains, are such candidates to be recorded as "not confirmable by design" instead of admitted? | §7.2, §7.3, §8 |
| Q2 Endpoint | Is the confirmatory endpoint the daily HAC Sharpe of the executed book's mark-to-market net excess, or may a per-trade or per-signal endpoint be preregistered? If the latter: with which documented mapping (DR-11), which excess reference, and which dependence treatment? | §3, §8 |
| Q3 Alpha allocation | Is 1/240 per admission (5 % over 12 admissions in 3 years) kept, or is the 5 % allocated over fewer admissions? Reallocation alone cannot make SR ≤ 2 detectable in 365 days | §2.2, §7.4 |
| Q4 Candidates and capacity | How do up to 3 simultaneous candidates obtain executable trades under the 2-position Paper capacity: shared slots, separate virtual books, or calibrated counterfactual evaluation of all signals? Does the 20 % slot-day reserve apply to those books? | §6.2 |
| Q5 Calibration | Which calibration standard applies (α_cal = 1/276, or the 1/240 owner alternative with its stated 5.75 % bound; DR-2, OD-3), and is independent validation of a critical value (A34-B `a34-vs1`) a separate decision to be taken? | §5, §10.2 |
| Q6 INCONCLUSIVE | Does the ladder adopt a preregistered INCONCLUSIVE outcome with a written δ_min and upper-bound level α_f (§9), so that a non-confirmation is never reported as evidence of no edge? | §9 |
| Q7 Planning inputs | Through which authorised route may σ, executable n, holding time, occupancy and dependence (deff, lrv) be obtained for planning, given OD-7 and the sealed FORWARD_HOLDOUT? (Roadmap S5 deliverable 2: "measured signal rates and day-clustering design effect", `:L113`.) | §4, §6 |

## 12. Reproducibility

- Python 3, standard-library `math` only (scipy was not available on the host; `math.erfc` gives Φ and bisection gives Φ⁻¹). No file, database, network or environment access; every input is typed in.
- The repository calculator `research/power/ladder_power.py @ 1432a90` was **read, not executed** (brief restriction). Its blob is identical on branch `feat/s5-pwr-1-ladder-power` (`86a8f8c`) and on `main` (squash-merged as `1432a90`, PR #58) · SOURCE_VERIFIED by blob comparison. The formulas below match its `daily_hac_sharpe_mde`, `power_daily_hac` and the per-trade one-sample form (`:L233-248`, `:L265-268`).
- Running the block prints the values used in Scenarios A–G, §6.4, §9 and §10.2.

```python
import math

def Phi(x):                      # standard normal CDF
    return 0.5 * math.erfc(-x / math.sqrt(2.0))

def zq(p):                       # inverse CDF by bisection (math only)
    lo, hi = -12.0, 12.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if Phi(mid) < p else (lo, mid)
    return (lo + hi) / 2

ZB = zq(0.80)                                            # 0.8416
MODES = {"NT 1/240": zq(1 - 1/240), "NT 1/276": zq(1 - 1/276),
         "A31 env": 3.14, "A33 env+shift": 3.20}         # c values: ladder_power.py L72-86

def sr_mde(c, lrv, T=1.0):       # daily endpoint, annualized Sharpe
    return (c + ZB) * math.sqrt(lrv) / math.sqrt(T)

def sr_power(c, lrv, sr, T=1.0):
    return Phi(sr * math.sqrt(T) / math.sqrt(lrv) - c)

def years_needed(c, lrv, sr):
    return ((c + ZB) * math.sqrt(lrv) / sr) ** 2

def trade_mde(c, sigma, n, deff=1.0):                   # per trade, one sample
    return (c + ZB) * sigma / math.sqrt(n / deff)

def trades_needed(c, sigma, mu, deff=1.0):
    return deff * ((c + ZB) * sigma / mu) ** 2

def capacity_bound(hbar, occ=1.0, K=2):                 # executable trades per year
    return K * 8760 * occ / hbar

def implied_sr(mu, sigma, n_eff):                        # bridge, section 3
    return (mu / sigma) * math.sqrt(n_eff)

def labels(sr, dmin, af, c=MODES["NT 1/240"], lrv=1.0, T=1.0):
    m = sr * math.sqrt(T / lrv)
    thr = dmin * math.sqrt(T / lrv) - zq(1 - af)        # z below thr -> UCB < dmin
    sup = 1 - Phi(c - m)
    enc = Phi(c - m) - Phi(0.8416 - m)
    ns = Phi(thr - m)
    return sup, enc, 1 - sup - enc - ns, ns

for name, c in MODES.items():                             # Scenario A
    print(name, [round(sr_mde(c, r), 3) for r in (1, 1.5, 2, 3, 5)])
for name, c in MODES.items():                             # Scenario B
    print(name, [round(sr_power(c, 1, s), 3) for s in (0.5, 1, 1.5, 2, 3, 4)])
print([round(years_needed(MODES["NT 1/240"], 1, s), 1) for s in (0.5, 1, 1.5, 2)])   # Scenario C
for a in (1/240, 1/60, 0.05):                             # Scenario D
    c = zq(1 - a)
    print(round(c + ZB, 3), round(sr_power(c, 1, 1), 3), round(sr_power(c, 1, 2), 3),
          round(years_needed(c, 1, 1), 1), round(years_needed(c, 1, 2), 2))
print(round(Phi(math.sqrt(8) - zq(1 - 1/60)), 3), round(Phi(1 - zq(1 - 1/60)), 3))   # S4 L99 check
print([round(trade_mde(MODES["NT 1/240"], 1.0, n, d), 3) for n in (100, 500) for d in (1, 3)])  # Scenario E
print([round(trades_needed(MODES["NT 1/240"], 1.5, mu)) for mu in (0.1, 0.2, 0.3, 0.5)])        # Scenario F
print([round(capacity_bound(h), 1) for h in (12, 24, 48, 96, 240)])                            # section 6.3
print([round(implied_sr(0.2, 1.5, n), 2) for n in (73, 182.5, 365, 730, 1460)])                # Scenario G
print([round(Phi((MODES["NT 1/240"] + ZB) * math.sqrt(f) - MODES["NT 1/240"]), 3) for f in (1, .75, .5, .25)])
print([round(x, 3) for x in labels(0.0, 1.0, 1/240)], [round(x, 3) for x in labels(1.0, 1.0, 1/240)])
print(round(sr_mde(3.20, 1) / sr_mde(MODES["NT 1/240"], 1), 4), round(zq(1 - 1/480) + ZB, 4))  # DR-7, two-sided
```

Expected first lines: `NT 1/240 [3.48, 4.262, 4.921, 6.027, 7.781]` and `A33 env+shift [4.042, 4.95, 5.716, 7.0, 9.037]`; last line `1.1614 3.7069`.

## 13. NOT VERIFIED items and inconsistencies

**NOT VERIFIED (with blockers).**

| ID | Item | Blocker |
|---|---|---|
| G4-N1 | Original wording of A29–A34 for the alpha split, the "excess" reference series and any outcome vocabulary beyond ELP | Documents only at unpushed `54a6369`; OD-1 holds publication and U1/U3/U4 are unresolved (ELP `:L19`, `:L41-48`). Not opened, to avoid widening access |
| G4-N2 | Per-trade net σ, executable trades per year, mean holding time, slot occupancy, ICC / design effect and daily lrv for any candidate | Needs trade-level data, outside this phase; post-freeze values are sealed (OD-7). Every such quantity is a free parameter here |
| G4-N3 | Book design for up to 3 concurrent candidates under the 2-position capacity, and how the 20 % slot-day reserve maps onto it | Not documented in the files read |
| G4-N4 | Annualised setup and bracket counts in A42 l.238 and A45 l.169 | Count withheld (window not verified pre-freeze) |
| G4-N5 | DR-8 (A45 "0.12 %" vs 0.136–0.142 %) and DR-9 (A42 0.133 reproduces) | Not re-derived: their inputs include the withheld counts; cited as HISTORICAL_REPORTED from ELP `:L103-104` |
| G4-N6 | Account fee level behind the cost basis | ELP `:L81` itself says "account fee unverified" |
| G4-N7 | Runtime behaviour of the cooldown and one-per-symbol rule in the deployed images | Code is SOURCE_VERIFIED; deployed parity is documented by the audit only |

**Inconsistencies found.**

| ID | Inconsistency | Disposition |
|---|---|---|
| G4-I1 | CON-44: R1 `:L19` "≈ 3.5–5.0" vs DFP `:L114` "≈ 3.5–7.0" | Same formula, different unstated assumption subsets (§10.1); the arithmetic does not conflict · INFERRED |
| G4-I2 | ELP `:L155` "None of these conditions can hold today" | Condition 1 can hold by design choice; the conjunction cannot (§10.2) · INFERRED, minor |
| G4-I3 | HOLD scope: OOC `:L35` "D1/D2" vs DFP `:L85` and `S5_PWR_1_OWNER_DECISIONS.md:L6` "D1–D5" vs roadmap `:L23` "D2–D5" | Already recorded as audit CON-36; unchanged · CONTRADICTORY |
| G4-I4 | Per-trade planning MDEs in A42/A45 use the normal-theory 3.48 and per-trade units | About 16 % optimistic against the envelope (DR-7) and not in the governed units (DR-11); not comparable with the SR MDE without the §3 bridge · INFERRED |
| G4-I5 | Roadmap `:L18` states "FWER 5 % over 12 admissions, α = 1/240 each" without the 3-year program period or α_cal | Already registered as DR-12 (ELP `:L107`) · SOURCE_VERIFIED |

**Related package documents.** Candidate-level consequences are for [the candidate decision matrix](CANDIDATE_DECISION_MATRIX.md) and [the owner decision brief](FINAL_OWNER_DECISION_BRIEF_AR.md); the package index is [README.md](README.md). Governing sources: [Evidence Ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md), [S5-PWR-1 owner decisions](../../strategy/S5_PWR_1_OWNER_DECISIONS.md), [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md), [Development-First policy](../../governance/DEVELOPMENT_FIRST_POLICY.md), [strategy roadmap](../../strategy/STRATEGY_EVOLUTION_ROADMAP.md), [R1 quant review package](../../lab/REVIEW_PACKAGE_R1_QUANT.md).
