# MI ML — final owner-decision package: D4–D7, D13–D15 (2026-10-08)

**Baseline:** Phase 0.1 @ `4c2e4b99dc7e3a62918d73a0a0fa8f1b2bdaa997`. Decision-focused; nothing is run, frozen or
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

### Failure handling (predeclared ladder, at most 2 steps, applied to the whole grid)

1. **Step 1:** double the mean block length.
2. **Step 2:** α = 0.025.
3. If the rule still fails after step 2, inference is capped in that cell class. Any real segment whose measured
   dependence or base rate falls in a failing class is capped at DESCRIPTIVE_ONLY at Phase 4. That check is
   mechanical and uses the frozen rule.
4. Every attempt is versioned and kept.
5. Anything outside the ladder goes back to the owner.

### CPU budget

Estimated **about 4–7 CPU-h**:

- T1 about 45 k reps at about 0.4 s each;
- T2 / T3 under 1 CPU-h;
- L2 about 1 CPU-h.

Controls:

- **Hard cap 8 CPU-h**, enforced through the research runner (R1, per-job `max_runtime`, jobs split per task).
- A 10-rep timing pilot runs per cell first.
- If the pilot projects more than the cap, the reductions apply in a predeclared order: (i) T1 ρ = 0 cells
  dropped, (ii) power reps 200 → 100. **Null reps are never reduced.**
- Never concurrent with G5, F0 v3 calibration or any G6 change.

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
   HLE without reading any label. If that count < n*_T2 (at the conservative base rate 0.5), T2 S-MAJ is fixed
   DESCRIPTIVE_ONLY before Phase 3.
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
| **MI-C v1.1** | Phase 1S close | Only the CDP, derived mechanically from the Phase 1S outputs: n*_T1/T2/T3, block lengths, α after the ladder, trip-wire ceiling (the 99.9th percentile of BSS under the strongest skill cell), T3 / T2 fallback flags, applicability region | Pushed before Phase 2. No discretion: any value not produced by the map is invalid. |
| v1.2+ | owner-approved only | any other change | Allowed only before Phase 2. After Phase 2 starts, changes may only be more conservative and add a second verdict (F0 anti-retroactive rule). v1.0 / v1.1 are kept byte-identical. |

**MI Ledger.** The instance and genesis anchor are created in Phase 1. **Real-data trials are registered after v1.1
is pushed and before Phase 2,** binding the v1.1 hash. Synthetic runs are recorded in their own sealed manifests, not
as real-data trials.

## §9. GO / NO-GO by phase

| Phase | GO requires | Exit (PASS) | NO-GO / STOP on |
|---|---|---|---|
| **1** Contract v1.0 | owner approval of D4–D7 and D13–D15 | v1.0 JSON + SHA256SUMS pushed and remote-verified; 11 PIT boundary tests and synthetic unit tests pass; ledger genesis created; zero real-data reads | any definition needing data to decide; any real-data read |
| **1S** Synthetic calibration | v1.0 on remote; separate compute GO (D10 / D13); host admission gates; no G5 / F0 v3 / G6 overlap | meta-acceptance evaluated; v1.1 derived and pushed; budget ≤ 8 CPU-h | the ladder is exhausted in non-stress cells (back to owner); budget overrun after reductions; a protocol change needed |
| **2** Environment and builder | v1.1 on remote; D8 approved **and** an install separately approved; real trials registered | deterministic builder (hash-identical rebuild); coverage / null / censoring report with **no outcome statistics**; T2 pre-outcome event counts and D15 flags recorded | any label value or base rate exposed; any eligibility (DS) violation; a W3 or freeze violation |
| **3** Development (E1) | Phase 2 PASS; compute GO | strongest baseline selected by rule; model-lock hash pushed | any HLE / W2 access before the lock |
| **4** HLE + W2 (E2 / E2b) | lock on remote; compute GO | one look; verdicts per task × scope; A7; utility descriptive; full report including negatives | a second look; any non-registered analysis presented as evidence |
| Shadow (E3) | separate protocol and approval (MI-ADR-06) | — | — |

## §10. Approval request

Approve, amend or reject each of: **D4 (option b), D5, D6 + D14, D7, D13, D15.**

On approval, Phase 1 drafting of contract v1.0 may start. It is still subject to the Phase 1 GO in §9.
