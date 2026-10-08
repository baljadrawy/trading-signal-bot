# MI ML — final owner-decision package: D4–D7, D13–D15 (2026-10-08)

**Baseline:** Phase 0.1 @ `4c2e4b99dc7e3a62918d73a0a0fa8f1b2bdaa997`; decision package @ `ee374e2`.

**Owner direction (2026-10-08):**

- D4 option b is accepted.
- D5 and D6 / D14 are accepted subject to corrections K1 / K2.
- The D7 A / B / C structure and the D15 logic are accepted.
- D13 is accepted in principle. **No compute is authorized.**

Corrections K1–K5 are applied below, each marked **[K#]**. Decision-focused; nothing is run, frozen or
registered here.

All values are proposals. Approval authorizes only drafting the Phase 1 contract (§9). No real outcome or W3 data
was read to set any value.

---

## D6 + D14 — point-in-time timeline and task definitions

### Proposed values

- Latencies (D14): **Δ_avail = 120 s** (15m / 1h / 4h), **300 s** (1d); **Δ_compute = 60 s**; **Δ_act = 60 s**.
- `end(b) = open(b) + tf` (canonical; the raw close field is ignored).
- **Feature rule:** use bar b only if `end(b) + Δ_avail ≤ t_issue`.
- **Label rule:** path-extreme labels use bars with `open ≥ t_act`; close-based labels use closes with `end > t_act`.
- **Freeze:** any bar with `end > 2026-08-19T09:33:46Z` is a hard failure (features and labels).

| Step | T1 downside (4h grid) | T2 false breakout (4h) | T3 regime (BTC 1d) |
|---|---|---|---|
| Decision bar | 4h bar [T−4h, T) | breakout bar t = [T−4h, T) | day d = [d 00:00, d+1 00:00) |
| Candle available | T + 2 min | T + 2 min | d+1 00:05 |
| Other inputs | bars ending ≤ T | L = max high of the 20 bars before t; ATR14 through t | bars ending ≤ d+1 00:00 |
| Forecast issued | **T + 3 min** | **T + 3 min** | **d+1 00:06** |
| Earliest actionable | T + 4 min | T + 4 min | d+1 00:07 |
| Reference | p0 = close of the decision bar | L | R_d |
| Label eligible | 15m bars with open in **[T+15 min, T+15 min+24 h)** (secondary 4h: [T+15 min, T+4 h 15 min)) | closes of **t+1 … t+6** (at T+4 h … T+24 h; all > t_act) | **R_{d+7}** from 1d bars ending ≤ d+8 00:00 |
| Event | min low ≤ p0·(1−6 %) (secondary 3 % / 4h) | any close ≤ L | R_{d+7}; transition 1[R_{d+7} ≠ R_d] |
| Event definition | — | breakout = close_t > L and close_t − L ≥ 0.25·ATR14; no new event for that symbol within 6 bars | z30 ±0.5 trend × σ20 ≥ 1.25 × 365d median → 6 states |
| Purge / embargo | purge training rows whose label end > fold start; embargo 1 day | the same; embargo 1 day | purge; embargo 7 days |

Fitted quantities (universe, medians, scalers, baseline rates, HMM) use only bars available before their month or
fold start. Nothing is back-filled.

### Rationale

- **No candle is ever treated as available at its close.** 2 / 5 min is conservative relative to a live REST poll
  of closed klines.
- The T2 breakout close is needed by definition, and it is available before issuance.
- **T1 skips the first 15 minutes,** so no label credit is given for moves before the earliest actionable time.
- The thresholds reuse the predeclared P2-C `DECLINE_THRESHOLD` (no new degree of freedom).

### Alternatives

1. Zero latency: rejected, leak risk.
2. Larger Δ (e.g. 15 min): changes nothing material on a 4h grid, but loses intraday resolution.
3. A volatility-scaled primary T1 threshold (2σ): this gives a stable base rate and more power, but it changes the
   task to "tail risk beyond volatility". It is kept as a secondary, descriptive variant.
4. Only the T2 label variant that excludes t+1: more conservative, with a later start.

### Consequence of approval

- These definitions are frozen verbatim in Phase 1 contract v1.0.
- The 11 synthetic boundary tests (spec §1.1) become Phase 1 exit criteria.

**[K2] T1 measures reference-close risk, not executable-entry risk.**

- D24 / D4 are measured from **p0 = the decision-bar close**. That is a *reference* price, observable at `t_issue`.
  It is **not** an executable entry price.
- A real entry could fill at the earliest at `t_act` (T + 4 min), at the ask, after spread and slippage. The price may
  already have moved in the excluded first 15 minutes.
- **Executable-entry-price risk** would be the minimum low relative to the actual fill, plus costs. It is **not
  modelled** in this track: historical book and fill data are unavailable, and P2-X impact is UNAVAILABLE.
- Consequently:
  - T1 skill is reported only as *forecasting skill for a reference-close market-state event*;
  - no historical result (forecasting skill or the U1–U3 utility diagnostics) may be described as achievable trading
    PnL, achievable drawdown reduction or an executable edge;
  - U1–U3 are counterfactuals on reference closes with assumed fees, labelled `REFERENCE_PRICE_COUNTERFACTUAL`.
- Any later change is a new version, made before Phase 2.

---

## D4 — evaluation universe

### Proposed rule

- **Inferential claims: S-MAJ = BTCUSDT + ETHUSDT only**, for T1 and T2. T3 is BTC-based with ETH as a feature.
- **Alts (S-ALT)** use the PIT top-30 rule (trailing-30d median quote volume, monthly, ≥ 200 1d bars, stablecoin and
  leveraged bases excluded, delisted symbols kept to their last bar).
  - They are computed in development and HLE but are **strictly EXPLORATORY_ONLY** (DS-3), with no verdict beyond
    that.
  - Pooled results are never reported alone.
- **Universe-derived features** (breadth / dispersion) are allowed in S-MAJ models only together with the DS-7
  without-variant and the FRAGILE cap.

### Rationale

- BTC/ETH have no survivorship or delisting problem and continuous history from 2017.
- The alt universe in ds-0928 is inferred (177 inferred delistings, 0 confirmed), and p2b is decision-selected.

### Alternatives

| Option | Effect |
|---|---|
| (a) BTC/ETH only, with no alt computation at all | simplest; loses exploratory information; removes breadth features unless built from alts anyway |
| **(b) S-MAJ inferential + S-ALT exploratory (recommended)** | as above |
| (c) pooled inferential | rejected by DS-3 |
| (d) a "liquid survivors" set | rejected: survivorship by construction |

### Consequences of approval

- **Power is lower.** T1 S-MAJ has about 2 × 3 100 HLE decisions, with clustered events. T2 S-MAJ has few breakouts
  (an order of magnitude of hundreds over the HLE). Either may end INSUFFICIENT_EVIDENCE; D15 handles this before
  any real outcome is seen.
- D9 (alt acquisition) stays deferred.
- No altcoin-market claim is possible in this track until DS-3's R1–R3 conditions are met.

---

## D5 — segments and evidence classes

### Proposed values

| Segment | Range | Class | Rules |
|---|---|---|---|
| Lookback | 2017-08 → 2018-12 | — | features and fits only |
| Development | 2019-01-01 → 2024-12-31 | **E1** | Expanding walk-forward; minimum 2 years of training; quarterly evaluation folds from 2021-Q1 (16 folds); all predeclared selection (strongest baseline, ≤ 3-point gradient-boosting grid) happens here. |
| **HLE** | 2025-01-01 → 2026-05-31 (labels must end < 2026-06-01; right-censored) | **E2** | Single locked look per task and scope after the model-lock hash is pushed. Not pristine, not confirmatory. |
| W2 check | 2026-06-01 → freeze (right-censored) | **E2b** | S-MAJ only; single look; consistency, not significance. |
| W3 | sealed | — | never |
| Prospective shadow | post-2026-10-04T15:26:43.497803Z | **E3** | separate protocol and approval |

### Rationale

- Expanding windows maximize the training data available.
- Quarterly folds give a stability measure.
- HLE is the most recent fully pre-W2 period.

### Alternatives

- A rolling window of 3 years (better under drift, noisier).
- Moving the HLE start to 2025-07 (fewer explored months, less power).
- Dropping the W2 check (simpler; loses an out-of-period sign check).

### Consequence of approval

Fixed in v1.0. The HLE can be looked at only once, and only after the model lock. Any second look counts as a new,
more conservative version.

### [K1] Fold-boundary assertions (synthetic, Phase 1 exit criterion; fail-closed)

For each task (T1 / T2 / T3), each scope, and each of the **16** quarterly development folds (2021-Q1 … 2024-Q4),
computed from the frozen calendar and the label and purge rules only (no data), the test asserts all of the following:

1. **Eligible training span ≥ 730 days** between the first and last training decision time. Eligible rows are those
   whose decision bar lies inside the training window **and** whose label window ends ≤ (fold start − max(purge,
   embargo)).
2. No training row's label window reaches the evaluation fold.
3. No evaluation row's label window crosses its fold end. Rows that would are censored and counted.
4. The last development fold's evaluation labels end before 2025-01-01, the HLE start. HLE evaluation labels end
   before 2026-06-01.
5. The final HLE model is trained only on development rows whose labels end ≤ 2025-01-01 − embargo.
6. Folds are contiguous, non-overlapping and exactly 16.

**This assertion FAILS under the current D5 dates.** With development starting 2019-01-01, fold 1 (2021-Q1) has only
**729.7 days (T1), 729.8 days (T2) and 723.0 days (T3)** of eligible training after purging (calendar arithmetic, no
data). Phase 1 cannot pass until the owner chooses (blocker **B1**):

| Option | Change | Fold-1 span | Consequence |
|---|---|---|---|
| **a (recommended)** | Development training for S-MAJ starts **2018-01-01**. BTC/ETH have certified data from 2017-08-17 (about 137 days of lookback). S-ALT stays exploratory from 2019-01-01. | T1 1094.7 / T2 1094.8 / T3 1088.0 days | 16 folds kept; one more year of training for the inferential scope |
| b | First evaluation fold moves to 2021-Q2 | about 820 days | **15 folds**, contradicting "16" |
| c | The threshold is redefined to "2 years before purge" | — | weakens the requirement; not recommended |

S-ALT is exploratory, so it is exempt from assertion 1. It must still pass assertions 2–6.

---

## D7 — requirement classes and utility

### Proposed rule

- **A (integrity):** A1–A8 as in spec §5. Any failure means INVALID_EVIDENCE. Fixed in v1.0.
- **B (statistics):** **structure fixed in v1.0; parameters calibrated in Phase 1S** (see §8).
  - B1: one-sided Brier-differential test, p = max(stationary block bootstrap, Diebold–Mariano HAC fixed-b); Holm
    within task (m ≤ 2); Bonferroni × 3 across tasks.
  - B2: log-loss differential with the same sign.
  - B3: Cox slope CI ∋ 1, intercept CI ∋ 0, and calibration-in-the-large CI ∋ 1.
  - B4: development-fold sign consistency ≥ 2/3; T3 must hold in both volatility states.
  - B5: n*.
  - B6: W2 S-MAJ consistency, or FRAGILE.
- **C (descriptive):** ECE (debiased, with a consistency-resampling null), reliability diagrams, sharpness,
  precision / recall at the development q80 cut, per-fold and per-regime BSS, HMM stability, block-length
  sensitivity, S-ALT, and the DS-6 / DS-7 variants.
- **Utility (descriptive, never part of skill):**
  - U1: exposure overlay `1 − 0.5·1[p > q80_dev]` versus a matched-mean-exposure volatility-targeting overlay;
    fee 2 × 10 bps, +20 bps stress; CVaR95, maximum drawdown, Sharpe, turnover.
  - U2: net 24h forward return by predicted-FB quintile.
  - U3: regime-conditional versus unconditional volatility targeting.

### Rationale

- Integrity is not negotiable, and statistical thresholds must not be guessed.
- Utility must not leak into skill claims.

### Alternatives

1. Freeze the provisional B values now: rejected, because they are uncalibrated.
2. Use ECE as a gate: rejected (spec §5 review).
3. Make U1 a gate: rejected (it would turn this into Alpha research).

### Consequence of approval

A and C are fixed. B waits for the Phase 1S-calibrated values (contract v1.1).

---

## D13 — synthetic calibration protocol (Phase 1S)

### Design

Synthetic data only. Stdlib Python, following the F0 precedent, so there is **no dependency on D8**. Two layers:

- **L1, forecast-level simulation** (primary). Simulate the true probability p_t, the baseline forecast, the candidate
  forecast and the outcomes, then apply rules B1–B6 exactly as frozen. No model fitting, so it is cheap.
- **L2, model-fit check.** In 4 representative cells × 200 reps, forecasts come from fitting a logistic surrogate on
  simulated features. This confirms that L1 rates hold when there is estimation and selection noise.

**Grid.** T1 / T2 sizes match the D4 / D5 S-MAJ scale.

| Task | Factors | Cells |
|---|---|---|
| T1 | base rate {1 %, 5 %, 20 %} × latent log-odds AR φ {0, 0.95} × factor loading ρ {0, 0.5} × structural break at the HLE start {no, ×2 rate}; 6× horizon overlap; 2 series × 6 per day × 517 days | 24 |
| T2 | events {150, 400, 1 500} × base rate {0.3, 0.5} × day clustering ρ {0, 0.5} | 12 |
| T3 | 6-state Markov, diagonal persistence {0.85, 0.95, 0.99}; 517 days; 7-day target; 2 transition-skill shapes | 6 |

**Truth classes per cell.**

| Class | Construction | Reps |
|---|---|---|
| Null | candidate = baseline + noise | **1 000** |
| Skill | BSS {0.01, 0.02, 0.05} | 200 each |
| Miscalibrated | slope 0.7 / 1.4, intercept ±0.3 | 200 |
| Leak | the label enters with weight w | 100 |

**Bootstrap.** 999 resamples inside the synthetic loops; the real protocol uses 2 000. The difference in p-value
resolution is negligible at α = 0.05.

### Meta-acceptance (frozen in v1.0, before any synthetic run)

1. **Null control.** In every non-stress cell, the false-positive rate of the full B rule is ≤ 5 % (point estimate)
   **and** its Wilson-95 upper bound is ≤ 7 %. The stress cells are φ = 0.95 with a break; they are reported, and they
   define the applicability region.
2. **Calibration test size.** The B3 false-rejection rate under perfectly calibrated forecasts is ≤ 7 %. B3 must
   reject miscalibrated cells with power ≥ 80 % at slope 0.7 / 1.4.
3. **Leak control.** A7 fires in ≥ 95 % of leak reps.
4. **Power.** Power is reported, not required. **n*** is the smallest effective sample with power ≥ 80 % at BSS_min
   (T1 / T2 0.02, T3 0.05), interpolated from the cells.

### Failure handling (predeclared ladder, at most 2 steps, applied to the whole grid) [K4]

1. **Step 1:** double the mean block length; α stays 0.05.
2. **Step 2:** keep the doubled block length; α = 0.025.

The whole null grid is re-run at each step, never just the failing cells.

**[K4] Rules for failing cells:**

1. **Preserved.** Every cell that fails at any step is kept in the sealed Phase 1S output: its reps, FPR, Wilson
   bounds and the rule version. No cell is dropped, rerun with a new seed, or re-labelled as stress after the fact.
2. **Stress cells are predeclared in v1.0** (T1: φ = 0.95 × break; T2: ρ = 0.5 × 1 500 events; T3: persistence
   0.99). Every other cell is non-stress.
3. **Applicability exclusions are fixed in v1.1, before any historical outcome:**
   - **A non-stress cell that still fails after step 2** sets that task × scope to **DESCRIPTIVE_ONLY** in v1.1. The
     reason: real data cannot be shown, before outcomes, to lie outside a plausible failing condition.
   - **A failing stress cell** is written into v1.1 as a named exclusion (task, factor levels, observed FPR).
     - At Phase 4, the frozen applicability check estimates the corresponding real-data characteristics (the lag-1
       autocorrelation of the loss differential; the break test at the HLE start). It **only downgrades**, to
       DESCRIPTIVE_ONLY, when they fall within the excluded class. It never upgrades.
     - The thresholds for "within the class" are frozen in v1.0 (φ̂ ≥ 0.9; break ratio ≥ 1.5).
4. **No broader inference.** A verdict may claim only:
   - the certified task × scope × horizon;
   - the certified grid region;
   - the HLE period.

   It may not claim other symbols, horizons, thresholds, periods, a pooled universe, or "robust to dependence"
   beyond the passing cells.
5. Anything outside the ladder goes back to the owner.

### CPU budget

Estimated **about 4–7 CPU-h**:

- T1 about 45 k reps at about 0.4 s each;
- T2 / T3 under 1 CPU-h;
- L2 about 1 CPU-h.

**[K3] Enforcement.** Nothing runs until a separate compute authorization (none exists today).

1. **Cap.** Cumulative cgroup CPU ≤ **28 800 CPU-s** (8 CPU-h) across all Phase 1S jobs, including the pilot,
   failed, frozen and killed jobs, and ladder re-runs.
2. **Measurement.** The source of truth is `cpu_s_cgroup` from each research-runner `job_record.json`. It is
   appended to an append-only `phase1s_budget.jsonl` (job id, profile, planned CPU-s, actual CPU-s, cumulative,
   status), with the file hash in the evidence seal.
3. **Pilot.** One R1 job runs 10 reps per cell, with `max_runtime_s` = 1 800 (a CPU bound of ≤ 7 200 CPU-s under
   CPUQuota 400 %). The full-grid projection is:

   P = Σ_cells (pilot CPU per rep × planned reps) × **1.25**, plus the ladder reserve (one full null-grid re-run).

   If P + pilot actual > 28 800, **STOP** and report to the owner. Nothing proceeds.
4. **Per-job limit (physical).** Jobs are split by task / layer. Each job gets `max_runtime_s = ⌈budget_job / 4⌉`
   under R1's CPUQuota of 400 %, so the cgroup bounds its CPU to ≤ budget_job. A job may be submitted only if
   cumulative actual + budget_job ≤ 28 800.
5. **Stop conditions:**
   - the cumulative cap would be exceeded;
   - a job hits its `RuntimeMaxSec`, or is killed by the watchdog;
   - after the first full job, actual CPU per rep exceeds the pilot by more than 50 %;
   - a host-gate refusal persists for more than 24 h;
   - any freeze-guard or integrity failure.

   On STOP, partial outputs are sealed and marked `INCOMPLETE`. They **cannot** be used to derive v1.1 (K5).
6. **No silent scope reductions.** Any change to cells, reps, bootstrap count, layers or the grid is a **protocol
   amendment** (v1.0.x). It needs owner approval and a push **before** it runs. There are no automatic reductions;
   the earlier "predeclared reduction order" is now only a list of options the owner may choose from (drop T1 ρ = 0
   cells; power reps 200 → 100). Null reps are never reduced.
7. Never concurrent with G5, F0 v3 calibration or any G6 change. R1 admission gates and protected windows apply.

### Alternatives

1. A numpy implementation: faster, but needs D8 first.
2. Fewer null reps (300): cannot certify a 5 % rate (the F0 v3 C4 lesson).
3. Skipping Phase 1S and freezing provisional values: rejected.

### Consequence of approval

The protocol is frozen in v1.0. Running it needs a separate GO (D10 for Phase 1S).

---

## D15 — pre-outcome feasibility and fallback rules

### Proposed rules

All of these are applied before any real outcome is seen, and are deterministic.

1. **T3.** If L1 power at BSS 0.05 in the reference cell (persistence 0.95, 517 days) is < 50 %, T3 is fixed
   **DESCRIPTIVE_ONLY** in v1.1. HMM identification is always descriptive.
2. **T2 S-MAJ.** Breakout *events* are defined from feature-side data only. Phase 2 therefore counts them in the
   HLE without reading any label. If that count < ⌈n*_T2 / 0.3⌉, T2 S-MAJ is fixed DESCRIPTIVE_ONLY before
   Phase 3. **[K5]** The divisor is the **lowest** grid base rate (0.3). The earlier "0.5" was not the conservative
   choice; see blocker B2.
3. **T1 S-MAJ.** The decision count is calendar-determined, so there is no pre-outcome cap. B5 is applied
   mechanically at Phase 4: below n* gives INSUFFICIENT_EVIDENCE.
4. **Applicability region.** Inherited from D13 failure handling.

### Rationale

This avoids the misleading "inevitable INSUFFICIENT" outcome, without looking at outcomes.

### Alternatives

- Always attempt inference and accept INSUFFICIENT.
- Drop T3: rejected, because it is an approved task.

### Consequence of approval

Some task × scope combinations may become descriptive-only before any real evaluation. This is recorded in v1.1 or
in the Phase 2 record.

---

## §8. How Phase 1 and Phase 1S fit together (versioned, precommitted)

| Version | Created in | Content | Rule |
|---|---|---|---|
| **MI-C v1.0** | Phase 1 | Everything except the calibration-dependent parameters (CDP): PIT model, tasks, labels, features, universe, segments, DS rules, A, C, utility, model classes and grids, B *structure*, the full Phase 1S protocol (grid, meta-acceptance, ladder, budget, reductions), and the **derivation map** CDP ← Phase 1S outputs | Pushed before Phase 1S starts |
| **MI-C v1.1** | Phase 1S close | Only the CDP, computed by the **frozen derivation map** below from the sealed, complete Phase 1S output | Pushed before Phase 2. Any value not produced by the map is invalid. |
| v1.2+ | owner-approved only | any other change | Allowed only before Phase 2. After Phase 2 starts, changes may only be more conservative and add a second verdict (F0 anti-retroactive rule). v1.0 / v1.1 are kept byte-identical. |

### [K5] Derivation map v1.0 → v1.1 (a pure function, frozen and tested in Phase 1)

**Input.** Exactly one sealed Phase 1S output manifest. Its SHA-256 must match the evidence seal.

**Fail-closed STOP preconditions.** Any one of the following means no v1.1, and STOP to the owner:

- the hash mismatches;
- the status is `INCOMPLETE`;
- any planned cell × truth class is missing, or has fewer reps than planned;
- any required field is absent or non-finite;
- the budget log shows a cap breach;
- the L2 null FPR point estimate is > 7.5 % (model-fit inflation);
- the map raises an error, or any CDP below evaluates to UNRESOLVED.

The map distinguishes **UNRESOLVED**, which means STOP, from **resolved-infeasible**, which deterministically
becomes DESCRIPTIVE_ONLY or INSUFFICIENT.

| CDP | Deterministic rule |
|---|---|
| Ladder step k_task | The smallest k ∈ {0, 1, 2} at which **every non-stress null cell** of the task meets FPR ≤ 5 % and Wilson UB ≤ 7 %. If none: `k = FAIL` → task × scope DESCRIPTIVE_ONLY (K4). |
| Block mean | T1 / T2: 5 d × 2^min(k, 1); T3: 28 d × 2^min(k, 1) |
| α_task | 0.05 if k ≤ 1; 0.025 if k = 2 |
| n*_T1 (positive events) | Among the grid event counts N·π, with N = 2 × 6 × 517 = 6 204 and π ∈ {1 %, 5 %, 20 %} → {62, 310, 1 241}: the smallest count whose power at BSS 0.02 is ≥ 0.80 in **every** non-stress cell at that π, under the final rule. If none: resolved-infeasible → B5 can never pass → T1 S-MAJ INSUFFICIENT_EVIDENCE |
| n*_T2 (positive events) | The same rule over {150, 400, 1 500} × {0.3, 0.5} positive counts. If none: T2 S-MAJ DESCRIPTIVE_ONLY |
| n*_T3 / T3 flag | Power at BSS 0.05, 517 days, persistence 0.95 (reference cell): < 0.50 → T3 DESCRIPTIVE_ONLY. Otherwise n*_T3 = 517 days if power ≥ 0.80 in every non-stress cell, else INSUFFICIENT at Phase 4 |
| T2 count threshold | ⌈n*_T2 / 0.3⌉ breakout events (D15 rule 2) |
| Trip-wire ceiling_task | The maximum BSS over all skill-class reps in all non-stress cells of the task, under the final rule. A real HLE BSS above it triggers an A7 leak audit |
| Applicability exclusions | Every failing stress cell after step 2, listed verbatim (K4) |

**Ties and numerics.** Comparisons use the stored exact counts (k / n), with no floating-point rounding before the
comparison. Ties are resolved toward the more conservative value. The map is recorded with its own SHA-256 in v1.0.

**Phase 1 exit criterion.** The map is tested on synthetic fixture outputs covering every branch: a pass, a ladder
step 1, step 2, a FAIL, infeasible n*, every STOP precondition, and tie handling.

**MI Ledger.** The instance and genesis anchor are created in Phase 1. **Real-data trials are registered after v1.1
is pushed and before Phase 2,** binding the v1.1 hash. Synthetic runs are recorded in their own sealed manifests, not
as real-data trials.

## §9. GO / NO-GO by phase

| Phase | GO requires | Exit (PASS) | NO-GO / STOP on |
|---|---|---|---|
| **1** Contract v1.0 | owner approval of D4–D7 and D13–D15 **and resolution of blockers B1–B2** | v1.0 JSON + SHA256SUMS pushed and remote-verified; 11 PIT boundary tests, the **K1 fold assertions** and the **K5 derivation-map fixture tests** pass; ledger genesis created; zero real-data reads | any definition needing data to decide; any real-data read; a K1 assertion failing |
| **1S** Synthetic calibration | v1.0 on remote; separate compute GO (D10 / D13); host admission gates; no G5 / F0 v3 / G6 overlap | meta-acceptance evaluated; v1.1 derived and pushed; budget ≤ 8 CPU-h | any K3 stop condition; a K5 STOP precondition; any unapproved protocol change (no silent reductions) |
| **2** Environment and builder | v1.1 on remote; D8 approved **and** an install separately approved; real trials registered | deterministic builder (hash-identical rebuild); coverage / null / censoring report with **no outcome statistics**; T2 pre-outcome event counts and D15 flags recorded | any label value or base rate exposed; any eligibility (DS) violation; a W3 or freeze violation |
| **3** Development (E1) | Phase 2 PASS; compute GO | strongest baseline selected by rule; model-lock hash pushed | any HLE / W2 access before the lock |
| **4** HLE + W2 (E2 / E2b) | lock on remote; compute GO | one look; verdicts per task × scope; A7; utility descriptive; full report including negatives | a second look; any non-registered analysis presented as evidence |
| Shadow (E3) | separate protocol and approval (MI-ADR-06) | — | — |

## §9a. Unresolved blockers (owner)

**Phase 1 update (2026-10-08):**

- B1 is resolved (S-MAJ development from 2018-01-01).
- B2 is resolved (0.3, verified in Phase 1S by the derivation map).
- **K3 item 4 is superseded.** The CPU cap is bounded by *measured* cgroup CPU (protocol G1–G7), not by
  wall-clock time.
- New **B5**: the runner lacks fail-closed CPU enforcement.

See `MI_PHASE1_CONTRACT.md`. The original table follows.

| ID | Blocker | Recommended resolution |
|---|---|---|
| **B1** | The K1 fold assertion fails under D5 (fold-1 training 723–730 days) | Option a: S-MAJ development training starts 2018-01-01 |
| **B2** | The D15 T2 count rule said "base rate 0.5 (conservative)"; the conservative divisor is the lowest grid rate, 0.3 | Confirm 0.3 (applied provisionally) |
| B3 (not blocking Phase 1) | Phase 1S compute is not authorized | A separate D10 / D13 compute decision after v1.0 is pushed |
| B4 (not blocking Phase 1) | Python environment (D8) and the W2 alt acquisition (D9) | Unchanged: design only / deferred |

## §10. Approval request

Approve, amend or reject each of: **D4 (option b), D5, D6 + D14, D7, D13, D15.**

On approval, Phase 1 drafting of contract v1.0 may start. It is still subject to the Phase 1 GO in §9.
