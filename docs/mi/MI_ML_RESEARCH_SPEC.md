# Market Intelligence ML — historical research specification (PROPOSED, not frozen)

**Status:** preparation stage, 2026-10-08; **revised in Phase 0.1** (documentation-only methodology corrections,
owner-approved 2026-10-08). Still not frozen, run or trained.

**Phase 0.1 change summary:**

| # | Correction | Where |
|---|---|---|
| C1 | Point-in-time timestamp model: close / availability / issuance / actionable / label window, with conservative latencies and boundary tests. This resolves the T2 contradiction (the breakout candle is the decision bar). | §1.1, §2–§4 |
| C2 | The 2025-01 → 2026-05 segment is renamed **Historical Locked Evaluation (HLE)**. Evidence classes E1 / E2 / E3 are separated, and the HISTORICAL_SKILL verdict becomes HISTORICAL_LOCKED_SKILL (non-confirmatory). | §1.2, §5 |
| C3 | ds-0928 is conditionally usable for **exploratory** research only. Results are split BTC/ETH vs alts, and alt claims are capped (rules DS-1…DS-9 in the inventory, §6). | §1, §5, inventory §6 |
| C4 | Requirements are split into mandatory integrity (A), statistical thresholds (B) and descriptive diagnostics (C). ECE is demoted to a diagnostic, minimum evidence becomes power-derived, and the bootstrap is protected. A synthetic-only calibration protocol is added. | §5, §5.1 |
| — | Decision matrix D1–D12 updated, and D13–D15 added. | §11 |

- Nothing here has been run, trained or frozen.
- Every number marked **[P]** is a *proposal for owner review*, not an approved threshold or gate.
- Governance: `MI_ML_GOVERNANCE_AMENDMENT.md` (MI-ADR-01…08). Data: `MI_ML_DATA_INVENTORY.md`.

## 1. Common design

### 1.1 Point-in-time timestamp model (C1)

All times are UTC, in integer milliseconds. Every Δ below is **[P]** (conservative, for owner review).

| Term | Definition |
|---|---|
| **Candle close time** `t_close(b)` | The canonical bar end `end(b) = open(b) + tf`. The raw archive close (end − 1 µs) and REST close (end − 1 ms) map to the same canonical end; the raw field is never used for ordering. |
| **Feature availability time** `t_avail(b)` | The earliest time a live process could hold the closed bar: `end(b) + Δ_avail`. Δ_avail = **120 s** for 15m / 1h / 4h and **300 s** for 1d. A candle is **never** assumed available at its close. Historical archives are published much later; this models a live REST poll after close. |
| **Forecast issuance time** `t_issue` | `end(decision bar) + Δ_avail + Δ_compute`, with Δ_compute = **60 s**. 4h forecasts are issued at 00:03, 04:03, …, 20:03; 1d forecasts at 00:06. |
| **Earliest actionable time** `t_act` | `t_issue + Δ_act`, with Δ_act = **60 s**. Used only for label start and utility diagnostics. |
| **Label observation window** | Only price observations made **after** `t_act`, for horizon h. Path-extreme labels (highs and lows can occur anywhere inside a bar) may use a bar only if `open(b) ≥ t_act`. Close-based labels may use a close only if `end(b) > t_act`. |

**Rules:**

1. **Features.** A feature may use bar b only if `t_avail(b) ≤ t_issue`. The decision bar itself is allowed
   (`end + Δ_avail < t_issue`); any later bar is not. This replaces the earlier "close < T" wording, which
   contradicted T2.
2. **Labels.** Labels follow the observation-window rule above. Movement between the decision-bar end and the label
   start is in neither the features nor the label, which is conservative.
3. **Fitted quantities.** Universe membership, expanding medians, scalers, HMM fits and baseline rates use only bars
   with `t_avail` at or before the start of their month or fold.
4. **Missing at issuance.** A bar missing at `t_issue` (a gap, or not yet available) makes the feature null with a
   reason. Later data is **never** back-filled into an earlier forecast.
5. **Freeze.** A bar with `end(b) > 2026-08-19T09:33:46Z` is a hard failure in features **and** labels (the P2-B
   guard). This covers W3.

**Synthetic boundary tests** (Phase 1, synthetic fixtures only):

- a bar with `t_avail == t_issue` is admitted, and at `t_issue + 1 ms` it is refused;
- µs-archive and ms-REST closes give the same canonical end;
- a T1 label never reads the decision bar or any 15m bar with open < `t_act`; a 15m bar opening exactly at the label
  start is included;
- the T2 level L excludes the breakout bar;
- a T2 label reads the close of t+1 only if `end(t+1) > t_act`, and never reads the breakout bar's close;
- T3: at 00:06 the day-d bar is admitted and day d+1 is refused;
- universe and scaler refits at a month or fold boundary use only prior data;
- a gap at issuance gives a null feature, and a late-arriving bar is not back-filled;
- any bar ending after the freeze is a hard failure in both features and labels;
- a +1-bar timestamp shift of the inputs must change the features (canary);
- doubling every Δ changes only the expected boundary cases.

The Δ values may later be checked against forward-Collector REST timing, under a separate approval; that data is not
read in this track's historical phases.

**Universe U(T)** [P]:

- BTCUSDT and ETHUSDT;
- plus the top 30 Binance spot USDT pairs by trailing-30-day median daily quote volume, recomputed monthly from data
  before the month start;
- each member needs ≥ 200 closed 1d bars;
- excluded: stablecoin bases (USDC, FDUSD, TUSD, …) and leveraged tokens (UP, DOWN, BULL, BEAR);
- delisted symbols stay in while their data exists.

Results are always reported separately for **BTC / ETH** (no survivorship) and **alts**.

Universe-derived features and the alt universe are subject to the dataset-eligibility rules DS-1…DS-9 (inventory
§6).

### 1.2 Periods and evidence classes (C2) [P]

Data before 2019-01-01 has too few symbols; it is lookback only.

| Segment | Range | Evidence class |
|---|---|---|
| Development | 2019-01-01 → 2024-12-31 | **E1, development evidence.** Expanding walk-forward, quarterly folds from 2021-Q1. All specification choices permitted by the predeclared rules are made here. |
| **Historical Locked Evaluation (HLE)** | 2025-01-01 → 2026-05-31 | **E2, historical locked evaluation.** One pre-registered look per task after the development lock. This period, and labels related to all three tasks, were **explored before** by other studies (inventory §5). It is **not pristine and not independently confirmatory.** |
| W2 consistency | 2026-06-01 → freeze, right-censored | **E2b.** One locked look, **BTC/ETH only** (DS-4). Partly explored, to about 2026-06-25. Consistency only. |
| W3 | sealed | never (guards unchanged) |
| Prospective shadow | forward data after 2026-10-04T15:26:43.497803Z, under a separately approved protocol | **E3, the only genuinely independent evidence.** Not part of this track's historical phases (MI-ADR-06). |

E1 supports only development statements. E2 supports at most **HISTORICAL_LOCKED_SKILL**, which is never called
confirmation or validation. Independent confirmation requires E3.

**Purge and embargo.**

- Training rows whose label window overlaps the evaluation fold are purged.
- The embargo after each evaluation fold is max(label horizon, 1 day). T3 uses 7 days.

**Independence.** Outcomes on the same UTC day are one cluster: they share the BTC factor. Inference uses the
protected rule in §5 B1. Effective-episode counts are always reported next to row counts.

**Model classes** [P]:

- the baselines in each task;
- L2 logistic regression (multinomial for T3);
- shallow gradient boosting (≤ 200 trees, depth ≤ 3, fixed learning rate; no tuning beyond a predeclared grid of
  at most 3 points, chosen on dev only);
- T3 only: a 2- or 3-state Gaussian HMM for identification.

No deep learning, no automated feature search, and no use of all 40 features.

**Probability quality metrics:**

- Brier score and **Brier skill score (BSS)** against the strongest baseline;
- log loss;
- reliability diagrams with 10 equal-count bins;
- the Cox calibration slope and intercept;
- ECE;
- sharpness;
- for T1/T2, precision / recall and false-alarm rate at a predeclared probability cut, the 80th percentile of dev
  predictions.

**Multiple testing.**

- Each task has at most **2 candidate models** against **1 strongest baseline**. The strongest baseline is chosen on
  dev by the lowest Brier score; that choice rule is frozen.
- Holm within a task; Bonferroni across the 3 tasks for any headline statement.
- Every trial, including baselines, is registered in the MI Ledger.

**Verdicts per task and scope** (S-MAJ = BTC/ETH, S-ALT = alts; DS-2):

- HISTORICAL_LOCKED_SKILL (E2, non-confirmatory);
- FRAGILE;
- NO_SKILL;
- INSUFFICIENT_EVIDENCE;
- INVALID_EVIDENCE;
- EXPLORATORY_ONLY (the S-ALT ceiling, DS-3).

Every verdict carries "historical, previously explored period; prospective shadow (E3) required". Nothing is ever
VALIDATED, CONFIRMED or PROVEN.

## 2. T1 — downside-risk probability

**Target.**

- Timing (§1.1): the decision bar is the 4h bar ending at T; `t_issue = T + 180 s`, `t_act = T + 240 s`;
  p0 = close of the decision bar. The label start is ceil_15m(`t_act`) = T + 15 min, so the first 15 minutes after
  T are excluded.
- D24 = 1 if min(low of the 15m bars with open in [T + 15 min, T + 15 min + 24 h)) ≤ p0 × (1 − θ24).
  **[P] θ24 = 6 %.**
- Secondary: D4 with **[P] θ4 = 3 %** over 4h.
- These equal the P2-C `DECLINE_THRESHOLD`, which was predeclared without outcome data. Reusing them avoids a new
  degree of freedom.
- Reported, not gated: the volatility-scaled variant D24σ (θ = 2·σ̂24h).

**Labelling.** Censored (excluded and counted) when a 15m bar in the horizon is missing or the horizon crosses a
segment end. Ties (low exactly at the threshold) count as events.

**Features** [P]: 7, all candle-only.

| Feature | Why |
|---|---|
| `vol.rv_1h_24` | volatility clustering |
| `vol.atr_norm_1h_14` | range-based volatility |
| `vol.vol_ratio_15m_16_96` | volatility acceleration |
| `mom.dist_high_15m_96` | recent drawdown from the 24h high |
| `ctx.btc_rv_1h_24` | market-factor volatility |
| `ctx.btc_ret_1h_1` → replaced by the BTC 24h log return | market drift |
| historical `universe_ret_24h_median` | market breadth |

**Baselines:**

- B0: expanding unconditional rate.
- B1: expanding rate by liquidity-rank bucket.
- **B2:** analytic volatility-scaled probability, P = 2·Φ(−θ / (σ̂·√h)), where σ̂ is an EWMA (λ 0.94) of 1h returns
  (reflection principle).
- **B3:** logistic regression on log σ̂ only.

B2 and B3 are expected to be strong, because downside probability is largely a volatility forecast. **MI skill
means beating them, not B0.**

**Candidates:** M1 logistic on the 7 features; M2 shallow gradient boosting on the same 7.

## 3. T2 — false-breakout probability

**Event** [P], on 4h bars:

- The breakout bar **is** the decision bar t (ending at T). Its close is a legitimate input, because
  `t_avail = T + 120 s ≤ t_issue = T + 180 s`.
- L = max(high of the 20 bars **before** t). ATR14 uses bars up to and including t.
- A breakout requires close_t > L **and** close_t − L ≥ 0.25 · ATR14(4h).
- Only the first event per symbol counts until it resolves: no new event within 6 bars. This is the clone defence.

**Target** [P]: FB = 1 if any 4h close with `end(b) > t_act`, among bars t+1 … t+6 (24 h), is ≤ L, i.e. the price
closes back inside the prior range.

- The close of t+1 is observed at T + 4 h > `t_act`, so it is admissible.
- The breakout bar's own close is never part of the label.

**Features** [P]: 6.

- breakout margin (close_T − L) / ATR;
- bar body ratio;
- `act.rel_volume` at the breakout (4h analogue);
- range compression before the breakout (20-bar range / ATR);
- BTC 24h return;
- historical breadth.

**Baselines:**

- B0: expanding base rate.
- B1: base rate by margin tercile.
- B3: logistic on margin only.

**Candidates:** M1 logistic; M2 shallow gradient boosting.

## 4. T3 — market regime identification and transitions

**Timing** (§1.1): the decision bar is the 1d bar of day d; `t_issue = end(d) + 360 s`. The target R_{d+7} is
computed from 1d bars ending ≤ end(d+7), all of which are observed after `t_act`.

The target's 30–60-day lookback overlaps the features. That is why the persistence and Markov baselines are mandatory,
and why skill means beating persistence.

**Observed regime on day d** (BTCUSDT 1d; bars with `t_avail ≤ t_issue` only) [P]:

- **Trend:** z30 = ln(C_d / C_{d−30}) / (σ60 · √30), where σ60 is the stdev of daily log returns over 60 days.
  - **up** if z30 ≥ +0.5;
  - **down** if z30 ≤ −0.5;
  - **range** otherwise.
- **Volatility:** **high** if σ20 ≥ 1.25 × the trailing-365-day median of σ20 (an expanding median until 365 days
  exist); otherwise **normal**.
- So the regime takes one of **6** states.

**Targets** [P]:

- R_{d+7}, the regime 7 days ahead (multiclass);
- TR = 1[R_{d+7} ≠ R_d] (transition).

**Features** [P]: 5.

- z30;
- σ20 / median;
- historical breadth (fraction of U with close above its 20-day mean);
- cross-sectional dispersion;
- BTC – ETH 30-day return spread.

**Baselines:**

- B0: unconditional frequencies.
- **B1:** persistence, smoothed as P(R_d) = 1 − ε, with ε fit on dev.
- **B2:** an expanding empirical Markov transition matrix over 7-day steps.

**Candidates:** M1 multinomial logistic; M2 shallow gradient boosting. The **HMM** (identification) is reported for
state stability (adjusted Rand index of state assignments across refits, and dwell times). It is not gated.

**Power caveat.** HLE covers about 520 days, i.e. about 74 non-overlapping 7-day windows. Transitions are
fewer. T3 may well end INSUFFICIENT_EVIDENCE, and that is an acceptable, honest outcome.

## 5. Requirements, thresholds and diagnostics (C4) [P] (owner approval required; frozen before any result)

Requirements fall into three classes. **No threshold is ever set or adjusted using real historical outcomes.** Final
statistical values come only from the synthetic calibration in §5.1.

**A. Mandatory integrity requirements.** These are not statistical: any failure means INVALID_EVIDENCE.

1. **A1** Trial registered in the MI Ledger before the run; specification hashes bound; anti-retroactive versioning.
2. **A2** PIT rules §1.1 enforced, and every synthetic boundary test passes.
3. **A3** Zero freeze or W3 violations in features and labels.
4. **A4** Dataset-eligibility rules DS-1…DS-9 applied, with a coverage manifest.
5. **A5** Deterministic rebuild: identical content hashes.
6. **A6** Censoring and null counts reported for every segment and scope.
7. **A7** Leak canaries pass:
   - the label time-shift placebo (whole-day blocks) shows no skill;
   - the shuffled-feature placebo shows no skill;
   - the feature-delay canary shows no implausible change;
   - the implausibility trip-wire: BSS above a synthetic-calibrated ceiling (provisional 0.5) triggers a leak audit.
8. **A8** Every registered trial is reported, negatives included.

**B. Statistical success thresholds.** These gate HISTORICAL_LOCKED_SKILL on HLE per scope; the values are
provisional until §5.1.

1. **B1 Primary test.** One-sided test of the Brier-loss differential (candidate vs the strongest baseline).
   - p = **max** of the stationary block bootstrap (mean block 5 days for T1/T2, 28 days for T3) and the
     Diebold–Mariano HAC test (fixed-b).
   - This is the F0 v2 lesson: single small-n components run anti-conservative.
   - Holm over the ≤ 2 candidates within a task. Bonferroni × 3 for any cross-task statement.
   - Secondary horizons and variants are descriptive only.
2. **B2** Log-loss differential has the same sign.
3. **B3 Calibration.**
   - Cox recalibration slope CI includes 1, and its intercept CI includes 0.
   - Calibration-in-the-large (mean p ÷ observed rate) CI includes 1.
4. **B4 Stability.**
   - Development-fold sign consistency ≥ 2/3.
   - T1/T2: each scope is judged separately (DS-2).
   - T3: holds in both volatility states.
5. **B5 Minimum evidence.** The power-derived minimum n* (effective events for ≥ 80 % power at BSS_min = 0.02 for
   T1/T2 and 0.05 for T3, at the observed base rate and dependence), taken from the §5.1 tables.
   - Below n*, the verdict is INSUFFICIENT_EVIDENCE.
   - The earlier floors stay only as provisional lower bounds: ≥ 300 positive events and ≥ 100 event-days (T1/T2),
     ≥ 30 transitions (T3).
6. **B6 W2 consistency** (S-MAJ only, DS-4): BSS point estimate ≥ 0 and slope CI includes 1. Otherwise the verdict
   becomes FRAGILE.

**C. Descriptive diagnostics.** These are never gates.

- Reliability diagrams.
- ECE (debiased), with a consistency-resampling null under the model's own probabilities.
- Sharpness.
- Precision, recall and false-alarm rate at the development q80 cut.
- BSS per fold and per regime.
- HMM state stability.
- Block-length sensitivity.
- S-ALT results (DS-3 ceiling).
- The DS-6 / DS-7 sensitivity variants.
- Utility U1–U3.

**Review of the Phase 0 proposals.**

| Phase 0 proposal | Problem | Phase 0.1 treatment |
|---|---|---|
| ECE ≤ 0.02 (T1/T2), ≤ 0.05 (T3) | Biased upward at small n and bin-dependent. Its meaning changes with the base rate (0.02 is 67 % of a 3 % rate, and loose at 30 %). Not tied to any decision. | **Demoted to a diagnostic**, replaced by B3 calibration CIs. Its null distribution is reported. |
| ≥ 300 events / ≥ 100 event-days | Arbitrary and not power-based. Event-days are not independent (volatility clustering). | **Power-derived n\*** from §5.1; the old values are provisional floors. |
| ≥ 30 regime transitions | Transitions are autocorrelated; 6 states over 7 days give few effective transitions. | Power-derived. **Pre-registered fallback:** if synthetic power < 50 % at the expected HLE size, T3 is declared DESCRIPTIVE_ONLY **before** any real result (D15). |
| One-sided 95 % block-bootstrap bound | F0 C1 showed small-n block bootstraps run hot (11–18 % at nominal 5 %). | B1 max-p rule; coverage verified synthetically. |
| Holm m = 2 | Adequate within a task. | Kept, plus Bonferroni across tasks; secondary analyses descriptive. |
| BSS > 0.5 trip-wire | Arbitrary. | Synthetic-calibrated ceiling; 0.5 is provisional. |

### 5.1 Synthetic-only calibration protocol (proposed; needs its own approval; Phase 1S)

**Purpose.** Estimate, for rules B1–B6, the false-positive rate, power, interval coverage and the minimum-evidence
n*, under rarity, dependence and regime change. Rules are adopted or tightened **before** Phase 3. No real outcome is
read.

**Generator grid:**

- **Base rate π:** 0.5 %, 2 %, 5 %, 15 %, 35 %.
- **Temporal dependence:** AR(1) latent log-odds at the 4h step, φ = 0, 0.9, 0.98, plus overlapping horizons
  (24h labels on a 4h grid, i.e. 6× overlap).
- **Cross-section:** 32 series on one factor, loading ρ = 0, 0.3, 0.6.
- **Regime change:** a 2-state Markov latent with a 3× base-rate ratio, and a ×2 structural break at the HLE start.
- **T3:** a 6-state Markov chain with diagonal persistence 0.85 / 0.95 / 0.99 per day and a 7-day target.

**Truth classes:**

| Class | Construction | Expected behaviour |
|---|---|---|
| Null | candidate = baseline + noise | the rule must almost never pass |
| Skill | incremental BSS 0.005 / 0.01 / 0.02 / 0.05 / 0.10 | power curves |
| Miscalibrated skill | slope 0.7 / 1.4, intercept ±0.3 | B3 must catch it |
| Leak | the label enters a feature with weight w | A7 must fire |

**Sizes:** HLE-like (about 517 days; T1 with 32 symbols × 6 per day; T2 events 1k / 3k / 10k; T3 517 days).

**Meta-acceptance**, frozen before the synthetic run:

- the B rule is adopted only if the null false-positive point estimate is ≤ 5 % **and** its Wilson 95 % upper bound
  is ≤ 7 % in every non-stress cell;
- this needs ≥ 1000 null reps per cell (per the F0 v3 C4 lesson); power cells use ≥ 200 reps;
- if a rule fails, it is tightened (block length, α, n*) and re-run as a new version, with the old record kept.

**Compute.** The synthetic loops use a logistic surrogate, not gradient boosting. Estimate about 2–8 CPU-h; a timing
pilot runs first. Via R1 only, never concurrent with G5 / F0 v3 / G6, and needs its own approval (D13).

**Utility evidence is separate.** It is never part of HISTORICAL_LOCKED_SKILL, and it is never a strategy or Alpha claim.

- **U1 (T1):** an exposure overlay on the equal-weight U(T) long basket (exposure 1 − 0.5·1[p > q80]), compared with a
  **matched-mean-exposure volatility-targeting overlay**.
  - Metrics: CVaR95 of daily returns, maximum drawdown, Sharpe, turnover.
  - Costs: fee 2 × 10 bps, plus a +20 bps stress.
  - Verdict: positive / none / insufficient.
- **U2 (T2):** net 24h forward return of breakout events by predicted-FB quintile. Descriptive only.
- **U3 (T3):** regime-conditional versus unconditional volatility targeting. Descriptive only.

## 6. Reproducibility and integrity

- Every run binds a hashed manifest: code commit and tree hash, dataset ids and content hashes, feature version,
  label version, task-spec hash, seed, and the MI Ledger anchor.
- Outputs are deterministic and written once. Negative results are kept.
- Synthetic tests must pass before any real-data run: the §1.1 boundary-test list, W3 / freeze refusal, gap
  censoring and deterministic rebuild (A2, A3, A5).

## 7. Dependencies

| Dependency | State | Needed for |
|---|---|---|
| ds-0928, p2b | present. ds-0928 certificate FAIL is preserved; it is conditionally usable for exploratory research only (D3, DS-1…DS-9) | Phases 2–4 |
| Isolated Python env (pyarrow, numpy, pandas, scikit-learn; optional lightgbm) | **missing** (no pyarrow) | Phase 2+ (D8) |
| P2-C ledger and feature formulas | on unmerged branches; used by commit pin, not by merge | Phase 1+ |
| P2-B freeze guard and acquisition | unmerged `3335228` | only if new W2 archives are approved (D9) |
| P2-X costs | v2 `f20e22a5`; historically fee + stress only | utility diagnostics U1–U3 |
| P2-F0 statistics | `617cd797` (v2) | inference utilities only |
| Research runner R1 | deployed | all compute |
| Forward data | Collector (post-W3) | **not** in the historical phases; future shadow protocol only |
| G5 / F0 v3 calibration / G6 | separate gates | MI compute must not overlap them |

## 8. Compute estimate (a priori; confirmed by a pilot in Phase 2)

| Item | Size | CPU |
|---|---|---|
| T1 panel | about 32 symbols × 6 decisions per day × about 2 700 days ≈ 0.5 M rows; labels from about 8 M 15m bars | ~10–20 CPU-min to build |
| T2 events | about 10–30 k breakout events | ~5 min |
| T3 panel | about 2 700 BTC days | seconds |
| Walk-forward | about 16 folds × (3–4 baselines + 2 models) per task | ~15–45 CPU-min per task |
| Bootstrap and placebos | 2 000 block resamples on stored predictions; about 20 placebo refits per task | ~1–2 CPU-h total |
| Synthetic calibration (Phase 1S) | about 60 cells; ≥ 1000 null reps or ≥ 200 power reps; logistic surrogate | ~2–8 CPU-h |
| **Total, Phases 2–4** | | **≈ 4–8 CPU-h**: about 1–3 h wall under R1 (4 workers), peak memory ≤ 4 GiB (LIGHT / R1 envelope) |

## 9. Phased plan (each phase separately approved, with a GitHub checkpoint for Saved / Merged / Deployed / Validated)

| Phase | Content | Reads real outcomes? | Compute |
|---|---|---|---|
| **0 / 0.1 (this)** | Governance amendment, inventory, specification; Phase 0.1 methodology corrections | no | none |
| **1** Contract freeze | Freeze task specs, PIT Δ values, DS rules and A/B/C requirements as JSON plus SHA256SUMS; register planned trials in the MI Ledger; synthetic unit tests (§1.1 list) | no | trivial |
| **1S** Synthetic calibration | §5.1; fixes n*, the bootstrap rule and the trip-wire ceiling before any real data | no (synthetic only) | ~2–8 CPU-h |
| **2** Environment and builder | Approved venv; deterministic panel builder; coverage, null and censoring report (**no base rates, no outcome statistics**); pilot timing | label *coverage counts* only | about 1 CPU-h |
| **3** Development | Walk-forward on 2019–2024 (E1); baseline-selection rule; model lock (hash) | development only | about 2–4 CPU-h |
| **4** Historical Locked Evaluation | One look on HLE and W2 (E2 / E2b); A7 canaries; U1–U3; full report including negatives; verdicts per scope | HLE and W2, once | about 1–2 CPU-h |
| 5 (separate track) | Prospective shadow protocol: design only, then its own approval (MI-ADR-06) | — | — |

## 10. Risks

1. **Explored data:** W1 and early W2 are not pristine (inventory §5). Historical skill is development evidence
   only.
2. **Trivial skill:** T1 can look skilful simply by forecasting volatility. The vol-scaled baselines B2 / B3 are the
   bar.
3. **Survivorship and selection:** the ds-0928 universe is inferred, and p2b is decision-selected. Hence the split
   reporting and D4 / D9.
4. **Forking paths:** T2 / T3 definitions have many degrees of freedom. The definitions and grids are frozen in
   Phase 1, with at most 2 candidates per task.
5. **Low power for T3:** an INSUFFICIENT verdict is likely.
6. **Misreading:** "skill" will be read as "trading edge". Utility is reported separately, and no Alpha claim is
   made.
7. **Environment:** a package install is a host change; it is isolated and needs approval.
8. **Host contention:** never concurrent with G5 or F0 v3 calibration.
9. **Regime drift:** 2019–2024 crypto may differ from 2025–2026. Fold-level stability is required.
10. **Latency assumptions:** the Δ values in §1.1 are assumptions, not measurements. A too-small Δ_avail would leak;
    hence the conservative values and the Δ-doubling test.
11. **Universe-feature contamination:** breadth and dispersion features inherit alt survivorship, even inside BTC/ETH
    models (DS-7).
12. **Evidence class creep:** E2 results risk being presented as confirmation. The verdict names and the E3
    requirement exist to prevent that.

## 11. Owner decision matrix (updated in Phase 0.1)

**"Approved in principle" is not authorization to execute any phase.**

Final decision package for D4–D7 and D13–D15 (exact values, alternatives, Phase 1 / 1S versioning and phase GO/NO-GO): `MI_ML_DECISION_PACKAGE_P01.md`.

| # | Decision | Status | Condition / what is still needed |
|---|---|---|---|
| D1 | Governance amendment MI-ADR-01…08 (reference until PR #3; then ADR-022…029) | **Approve now (in principle)** | No execution authority; each phase still needs its own approval |
| D2 | W3 for MI includes market candles in [2026-08-19T09:33:46Z, 2026-10-04T15:26:43.497803Z) | **Approve now (in principle)** | Guards unchanged |
| D3 | ds-0928 use | **Conditional approval** | Exploratory only, under DS-1…DS-9: FAIL certificate preserved, scope split, alt ceiling |
| D4 | Universe rule (BTC/ETH plus PIT top 30) | **Requires amendment** | Must align with DS-2 / DS-3 / DS-7 and the deferred D9; finalize before Phase 1 |
| D5 | Segments and evidence classes (E1 / HLE-E2 / E2b / E3) | **Requires amendment** | Revised in §1.2; owner final approval |
| D6 | Task definitions, [P] thresholds, PIT Δ values | **Requires amendment** | Revised in §1.1 and §2–§4; owner final approval |
| D7 | Requirements A / B / C and utility protocol | **Requires amendment** | Revised in §5; final B values only after Phase 1S |
| D8 | Python environment | **Conditional approval (design only)** | No installation; design to be documented later (pinned, hash-locked, outside production paths) |
| D9 | W2 public-archive acquisition | **Defer** | Pending the universe methodology (D4 / DS-3); the W2 check is BTC/ETH only meanwhile |
| D10 | Compute | **Conditional approval (planning only)** | No compute authorized; the estimates in §8 are planning figures |
| D11 | Separate MI Trial Ledger | **Approve now (in principle)** | Instance created only in an approved Phase 1 |
| D12 | Model families (logistic, shallow gradient boosting, HMM for identification) | **Conditional approval** | Subject to final specifications |
| D13 (new) | Phase 1S synthetic calibration protocol (§5.1) and its compute | **Requires amendment / approval** | Owner review of the grid and meta-acceptance |
| D14 (new) | PIT latency values Δ_avail / Δ_compute / Δ_act | **Requires amendment / approval** | Part of D6 |
| D15 (new) | T3 DESCRIPTIVE_ONLY fallback if synthetic power < 50 % | **Requires amendment / approval** | Must be decided before any real T3 result |

**Unresolved decisions and ambiguities:**

1. D4 / D9: how to build a PIT alt universe, including delistings, without new data. Until resolved, there are no alt
   skill claims.
2. The final Δ values (D14). They could be cross-checked against forward-Collector REST timing, but only under a
   separate approval.
3. n*, the block lengths and the trip-wire ceiling. These depend on Phase 1S (D13).
4. Whether T3 stays inferential or becomes descriptive-only (D15).
5. Where the Phase 1 contract files and the MI Ledger instance will live (path outside the Collector tree; D11).
6. Transcription of MI-ADR into DECISION_LOG depends on PR #3.

## 12. Recommendation

- **GO** for a separately approved **Phase 1 contract freeze**, but only after D4–D7, D13–D15 are amended and approved.
  Phase 1 reads no real data and no outcomes.
- **NO-GO** for Phase 1S, Phase 2 or any data build, install or compute until their own approvals (D8 / D10 / D13).
