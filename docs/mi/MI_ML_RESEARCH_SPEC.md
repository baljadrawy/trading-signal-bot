# Market Intelligence ML — historical research specification (PROPOSED, not frozen)

**Status:** preparation stage, 2026-10-08.

- Nothing here has been run, trained or frozen.
- Every number marked **[P]** is a *proposal for owner review*, not an approved threshold or gate.
- Governance: `MI_ML_GOVERNANCE_AMENDMENT.md` (MI-ADR-01…08). Data: `MI_ML_DATA_INVENTORY.md`.

## 1. Common design

**Decision time.** T is the close of a 4h bar (00, 04, … 20 UTC). Features use only bars with close < T (strictly
closed). Labels use only bars with open ≥ T.

**Universe U(T)** [P]:

- BTCUSDT and ETHUSDT;
- plus the top 30 Binance spot USDT pairs by trailing-30-day median daily quote volume, recomputed monthly from data
  before the month start;
- each member needs ≥ 200 closed 1d bars;
- excluded: stablecoin bases (USDC, FDUSD, TUSD, …) and leveraged tokens (UP, DOWN, BULL, BEAR);
- delisted symbols stay in while their data exists.

Results are always reported separately for **BTC / ETH** (no survivorship) and **alts**.

**Periods** [P]. Data before 2019-01-01 has too few symbols; it is lookback only.

| Segment | Range | Use |
|---|---|---|
| Development | 2019-01-01 → 2024-12-31 | expanding walk-forward, quarterly folds from 2021-Q1; all specification choices allowed by the predeclared rules happen here |
| Validation (held out) | 2025-01-01 → 2026-05-31 | **single look** per task after the dev lock; primary historical evidence (explored earlier by other studies, disclosed) |
| W2 consistency | 2026-06-01 → 2026-08-19T09:33:46Z, right-censored at the freeze | single look; sign and calibration consistency only, because it is too short for significance |
| W3 | sealed | never |

**Purge and embargo.**

- Training rows whose label window overlaps the evaluation fold are purged.
- The embargo after each evaluation fold is max(label horizon, 1 day). T3 uses 7 days.

**Independence.** Outcomes on the same UTC day are one cluster: they share the BTC factor. The bootstrap is a block
bootstrap by day (T1/T2) or a 7-day block bootstrap (T3). Effective-episode counts are reported next to row counts.

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

**Verdicts per task.** HISTORICAL_SKILL, FRAGILE, NO_SKILL, INSUFFICIENT_EVIDENCE, INVALID_EVIDENCE. HISTORICAL_SKILL
always carries "prospective shadow required"; nothing is ever VALIDATED or PROVEN.

## 2. T1 — downside-risk probability

**Target.**

- D24 = 1 if min(low of the 15m bars with open in [T, T+24h)) ≤ close_T × (1 − θ24). **[P] θ24 = 6 %.**
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

- A breakout at T requires close_T > L = max(high of the previous 20 bars), **and** close_T − L ≥ 0.25 · ATR14(4h).
- Only the first event per symbol counts until it resolves: no new event within 6 bars. This is the clone defence.

**Target** [P]: FB = 1 if any 4h close within the next **6 bars (24 h)** is ≤ L, i.e. the price closes back inside
the prior range.

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

**Observed regime on day d** (BTCUSDT 1d; data ≤ d only) [P]:

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

**Power caveat.** Validation covers about 520 days, i.e. about 74 non-overlapping 7-day windows. Transitions are
fewer. T3 may well end INSUFFICIENT_EVIDENCE, and that is an acceptable, honest outcome.

## 5. Acceptance criteria per task [P] (owner approval required; frozen before any result)

HISTORICAL_SKILL requires all of the following on the **validation** segment:

1. **BSS > 0** against the strongest baseline, with a one-sided 95 % block-bootstrap lower bound > 0 after Holm
   (m = 2).
2. **Log-loss** improvement with the same sign.
3. **Calibration:** Cox slope point estimate in [0.8, 1.25] with its 95 % CI including 1; ECE ≤ 0.02 (T1 / T2) or
   ≤ 0.05 (T3).
4. **Stability:** BSS > 0 in ≥ 2/3 of the dev walk-forward folds, **and** in both the BTC / ETH and alt subsets
   (T1 / T2) or in both volatility states (T3).
5. **Minimum evidence:**
   - T1 / T2: ≥ 300 positive events on ≥ 100 distinct event-days in validation;
   - T3: ≥ 30 observed transitions.

   Otherwise the verdict is INSUFFICIENT_EVIDENCE.
6. **W2 consistency:** BSS point estimate ≥ 0 and slope CI including 1. A failure downgrades the verdict to FRAGILE.
7. **Adversarial checks** (any failure → INVALID or FRAGILE):
   - label time-shift placebo (labels moved by whole-day blocks) gives BSS ≤ 0;
   - a feature-delay canary (features lagged one extra bar) shows no implausible collapse or gain;
   - a shuffled-feature placebo gives BSS ≤ 0;
   - the implausibility trip-wire fires on validation BSS > 0.5 (leak audit).

**Utility evidence is separate.** It is never part of HISTORICAL_SKILL, and it is never a strategy or Alpha claim.

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
- Synthetic tests must pass before any real-data run:
  - PIT boundary;
  - a label that never reads bars before T;
  - a feature that never reads bars at or after T;
  - W3 refusal;
  - gap censoring;
  - deterministic rebuild.

## 7. Dependencies

| Dependency | State | Needed for |
|---|---|---|
| ds-0928, p2b | present, certified (ds-0928 certificate FAIL on dominance / survivorship; accepting it needs owner decision MI-D3) | Phases 2–4 |
| Isolated Python env (pyarrow, numpy, pandas, scikit-learn; optional lightgbm) | **missing** (no pyarrow) | Phase 2+ (MI-D8) |
| P2-C ledger and feature formulas | on unmerged branches; used by commit pin, not by merge | Phase 1+ |
| P2-B freeze guard and acquisition | unmerged `3335228` | only if new W2 archives are approved (MI-D9) |
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
| **Total, Phases 2–4** | | **≈ 4–8 CPU-h**: about 1–3 h wall under R1 (4 workers), peak memory ≤ 4 GiB (LIGHT / R1 envelope) |

## 9. Phased plan (each phase separately approved, with a GitHub checkpoint for Saved / Merged / Deployed / Validated)

| Phase | Content | Reads real outcomes? | Compute |
|---|---|---|---|
| **0 (this)** | Governance amendment, inventory, specification | no | none |
| **1** Contract freeze | Freeze task specs as JSON plus SHA256SUMS; register every planned trial (baselines and candidates) in the MI Ledger; synthetic unit tests for the label, feature and split code | no | trivial |
| **2** Environment and builder | Approved venv; deterministic panel builder from ds-0928 / p2b; coverage, null and censoring report (**no base rates, no outcome statistics**); pilot timing | label *coverage counts* only | about 1 CPU-h |
| **3** Development | Walk-forward on 2019–2024; baseline-selection rule; model lock (hash) | dev only | about 2–4 CPU-h |
| **4** Held-out evaluation | Single look on validation and W2; adversarial checks; U1–U3; full report including negatives; verdicts | validation and W2, once | about 1–2 CPU-h |
| 5 (separate track) | Prospective shadow protocol: design only, then its own approval (MI-ADR-06) | — | — |

## 10. Risks

1. **Explored data:** W1 and early W2 are not pristine (inventory §5). Historical skill is development evidence
   only.
2. **Trivial skill:** T1 can look skilful simply by forecasting volatility. The vol-scaled baselines B2 / B3 are the
   bar.
3. **Survivorship and selection:** the ds-0928 universe is inferred, and p2b is decision-selected. Hence the split
   reporting and MI-D4 / MI-D9.
4. **Forking paths:** T2 / T3 definitions have many degrees of freedom. The definitions and grids are frozen in
   Phase 1, with at most 2 candidates per task.
5. **Low power for T3:** an INSUFFICIENT verdict is likely.
6. **Misreading:** "skill" will be read as "trading edge". Utility is reported separately, and no Alpha claim is
   made.
7. **Environment:** a package install is a host change; it is isolated and needs approval.
8. **Host contention:** never concurrent with G5 or F0 v3 calibration.
9. **Regime drift:** 2019–2024 crypto may differ from 2025–2026. Fold-level stability is required.

## 11. Owner decisions required before any historical experiment

| # | Decision | Recommended default |
|---|---|---|
| MI-D1 | Approve MI-ADR-01…08; record them as the reference until PR #3, then transcribe as ADR-022…029 | approve |
| MI-D2 | W3 for MI includes **market candles** in [2026-08-19T09:33:46Z, 2026-10-04T15:26:43Z) | yes (sealed) |
| MI-D3 | Accept ds-0928 despite certificate FAIL (dominance / macro unused; survivorship disclosed) | accept, with split reporting |
| MI-D4 | Universe rule (BTC / ETH plus PIT top 30, monthly, exclusions) | approve |
| MI-D5 | Segments: dev 2019–2024, validation 2025-01 → 2026-05 single look, W2 consistency | approve |
| MI-D6 | Task definitions and [P] thresholds (θ24 6 %, θ4 3 %; breakout 20-bar / 0.25 ATR / 6 bars; regime z30 ±0.5, vol 1.25× over 365d, 7-day horizon) | approve or amend **before** Phase 1 |
| MI-D7 | Acceptance criteria §5 and the utility protocol | approve or amend before Phase 1 |
| MI-D8 | Isolated venv with pyarrow / numpy / pandas / scikit-learn (lightgbm optional) | approve, pinned versions, outside production paths |
| MI-D9 | Public-archive acquisition of W2 candles for the PIT top 30 under the P2-B freeze guard (otherwise the W2 check is BTC / ETH only) | approve (a small download) |
| MI-D10 | Compute: R1 via the research runner; about 4–8 CPU-h over Phases 2–4; never with G5 / F0 v3 / G6 | approve per phase |
| MI-D11 | MI Ledger: separate instance using the P2-C ledger code pinned by commit (no merge needed) | approve |
| MI-D12 | Model classes limited to logistic / shallow gradient boosting / HMM (identification) | approve |

## 12. Recommendation

- **GO** for the owner to review and approve the governance amendment and MI-D1…D12. The next phase after that is
  **Phase 1** (contract freeze and ledger registration): no real data values, no outcomes.
- **NO-GO** for any experiment, data build or package install until those decisions are approved.
