# A7 — T1 Hybrid: focused statistical review (appendix to A6)

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE** — Gate A review material. Nothing here is an owner approval, a protocol amendment or a frozen artefact, and nothing here may be loaded by any run. The procedures below are **draft Phase 2 design text**: not production-ready and **not validated on real market data**.

**Recorded** 2026-10-09 on `docs/mi-phase1s-gate-a-review-20261009` (base `f9a5168`).

**Labels:** **[F]** verified fact · **[M]** exact mathematics · **[N]** exact deterministic computation · **[A]** assumption · **[R]** recommendation.

**Baseline [F]:**
- contract set `fdf3366480976db6ada1ac90b62f6b6db1edc35a59d1f3527cfcd6fcbf28e157`; protocol `412cb606…`; all 7 frozen files match the manifest;
- implementation unchanged since `df43073`;
- budget ledger, checkpoint and anchor unmodified since 2026-10-08T23:34Z;
- trial ledger: genesis only.

**Context.** You selected the **Hybrid** (certify T1 only inside a pre-specified operating envelope, and fail closed outside it or when validity can't be established) as the **preferred research direction**. It is not approved.

**Frozen inputs [F]:**
- `inference_scope`: "a verdict covers only the certified task × scope × horizon × grid region × HLE period".
- `applicability_thresholds`: `break_ratio_min 1.5`, `phi_hat_min 0.9`, "Phase 4 downgrade-only check for failing stress cells". **No estimator is frozen for either.**

## A. Confidence-interval rule for the HLE / dev base-rate ratio

### A.1 The earlier claim is corrected

The earlier statement "false IN ≤ 2.5 % by construction" is **rejected as an unconditional guarantee**. It holds only under the assumptions below.

### A.2 Proposed estimator (draft Phase 2 text)

- log R̂ = log r̂_hle − log r̂_dev, where r̂ = positives / eligible rows (T1 D24 labels, S-MAJ, PIT / censoring rules).
- **Per-segment cluster-robust variance** on contiguous blocks of length b ≥ the label horizon (proposed: the T1 CDP block length):
  Var̂(r̂) = G/(G−1) · Σ_g (k_g − r̂·n_g)² / n². G ≈ 103 for the HLE and ≈ 511 for dev at b = 5 days.
- Var(log R̂) = Var̂_hle / r̂_hle² + Var̂_dev / r̂_dev².
- **CI:** log R̂ ± t_{ν, 1−α/2} · √Var, with ν = G_hle − 1 (conservative), α = 0.05.
- **Classification of the CI:**
  - inside (−log 1.5, log 1.5) → `IN`;
  - entirely outside → `SHIFT`;
  - otherwise → `UNRESOLVED`;
  - an endpoint exactly on the edge is **not** inside (fail-closed).

### A.3 Error properties

| Quantity | Result | Basis |
|---|---|---|
| False IN at R = 1.5 (pointwise, one dimension) | ≤ α/2 if log R̂ is approximately normal and the variance is **correct** | [M] |
| Same, iid, exact binomial sums (dev and HLE both random) | π_hle 0.01: **0.0209**; 0.05: **0.0239**; 0.2: **0.0242** — supports the bound, slightly conservative at rare events | [N] |
| False SHIFT at R = 1 | ≪ α/2 (iid exact: 2.4e-6 at π = 0.01, ≈ 0 otherwise); the earlier "2.5 %" figure was wrong | [N] |
| Variance underestimated by a factor c | False IN = Φ(−1.96/√c): **0.055** (c = 1.5), **0.083** (c = 2), **0.129** (c = 3) | [M] |
| Overall no-inference probability (UNRESOLVED or SHIFT) | **Not controlled.** It grows as precision falls (rare events, high deff, sub-windows). Earlier deterministic tables: e.g. π = 0.01 → ≈ 1 for deff ≥ 3 | [N/A] |

### A.4 Assumptions (all unvalidated on real data)

| Assumption | Content |
|---|---|
| A1 | Approximate normality of log R̂. Unreliable at small expected HLE positives (roughly < 100·deff), where log R̂ is skewed |
| A2 — **critical** | The block-cluster variance is adequate under T1's 6× overlapping labels and co-moving symbols. **Bonferroni or any other multiplicity correction does not fix a misestimated variance or a misspecified model** |
| A3 | Dev and HLE segments are independent (separated in time by more than b) |
| A4 | A block length b ≥ the label horizon captures the dependence |

**Rare-event fallback.** The exact conditional (binomial-on-total, Clopper–Pearson) interval is exact **only** for iid Poisson counts. The deff-inflated version under dependence is **approximate**, not exact.

### A.5 Multiplicity

- **False IN** [M]: IN is an **intersection** over dimensions and windows, so the family-wise false IN is bounded by the pointwise rate of the truly shifted dimension. There is no inflation; with Bonferroni-widened windows the bound is α/(2W) per window.
- **No-inference** is a **union** (any SHIFT or UNRESOLVED blocks). It is **not controlled**; Bonferroni widening increases it.
- **Pointwise versus family-wise:** all guarantees are pointwise, conditional on the shifted dimension.

### A.6 Monitorability criterion

The earlier "no-shift false downgrade ≤ 10 %" criterion is **removed as a mandatory gate**. It is a value judgement, not statistically derivable, and it doesn't affect error guarantees, because the state rule already fails closed. It is kept only as an **optional, dev-only, pre-registered planning disclosure**: the expected probability of being able to infer.

### A.7 Unresolved

1. **Validation of variance estimation** under overlap and dependence (A2), on dev data only.
2. **Sub-window design:** W, Bonferroni, and whether an UNRESOLVED window blocks.
3. The quality of the rare-event fallback under dependence.

## B. Persistence estimator (E2): HOLD

- **[F] Frozen meaning of φ:** the AR(1) coefficient of the **latent log-odds** process at the 4h step (protocol `generators.T1`), the property that makes the loss differential persistent.
- **[M] Lag-1 autocorrelation of locked-model predicted log-odds is not established as an estimator of latent φ.** Confounders:
  - **feature overlap** (e.g. 24h rolling features sampled every 4h carry about 1 − 4/24 ≈ 0.83 autocorrelation mechanically): upward bias;
  - **forecast noise / limited information:** attenuation toward the signal share, a downward bias;
  - **model smoothing and overlapping prediction horizons:** extra autocorrelation unrelated to φ;
  - **irregular sampling or gaps:** no frozen handling rule.
- Sampling bias (Kendall ≈ −(1+3φ)/n ≈ −0.001) is negligible next to these structural biases.
- **[F] No link from 0.9 to 0.95:** the frozen documents give no derivation connecting `phi_hat_min 0.9` to the φ = 0.95 stress cells, and no observable quantity is identified that maps to latent φ.
- **Decision: E2 remains HOLD.**
  - No replacement estimator is introduced.
  - The frozen 0.9 threshold is not changed.
  - **Persistence is not removed from the certified scope.** Under the state semantics in §C, E2 = `NOT_EVALUATED`, which **blocks inference** until you either approve a validated estimator or explicitly decide (with disclosure) to scope persistence-regime validity out of the claim.

## C. Monitoring-state semantics (DRAFT Phase 2 design; not implemented, not a frozen rule)

**1. Findings and reason codes.** Several can coexist; **every code is preserved** in the record.
- Per dimension and window: `IN`, `SHIFT`, `UNRESOLVED`, `NOT_EVALUATED`, `INVALID`.
- Global: `INTEGRITY_FAIL` (coverage, PIT, censoring, hash or non-finite values).
- The frozen B1–B6 gate outcomes, unchanged.

**2. Final permission.** Deterministic, fail-closed, first match wins. **No new contract verdicts.**

| # | Condition | Permission | Existing frozen verdict |
|---|---|---|---|
| 1 | Any `INTEGRITY_FAIL` or `INVALID` (even if another dimension shows SHIFT) | No inference | INVALID_EVIDENCE |
| 2 | Otherwise, any `SHIFT` (even if another dimension is `UNRESOLVED`) | No inference | DESCRIPTIVE_ONLY |
| 3 | Otherwise, any `UNRESOLVED` or `NOT_EVALUATED` among required dimensions (E2 currently) | No inference | INSUFFICIENT_EVIDENCE |
| 4 | Otherwise | Defer to the **unchanged** frozen B1–B6 gates (e.g. a B3 failure gives the contract's own verdict) | As frozen |
| 5 | All required evidence `IN` and all frozen gates pass | Scoped historical inference only (`inference_scope`: the certified grid region) | HISTORICAL_LOCKED_SKILL |

Each CI's findings partition its position (inside / outside / straddle), so the same evidence can't classify two ways. Ties fail closed.

## D. Corrections and governance status

**Correction to A3 and A6 [M/N].** R+ is **not** STOP-equivalent to K:
- The B3-size and B3-power gates on break cells are identical (same rule, same data).
- Null control differs. If a break cell fails at the step selected by the 12 no-break cells (event E), **K advances the ladder while R+ STOPs**. So P_STOP(R+) = P_STOP(K) + P(E): R+ is **weakly stricter**.
- P(E) depends on the probability that B3 *accepts* a dev-calibrated break-cell forecast (O/E ≈ 2):

| π | deff 1 | deff 6 |
|---|---|---|
| 0.05 | — | ≤ 0.005 |
| 0.01 | 0.001 | **0.566** |

  So P(E) is not negligible at π = 0.01 under heavy dependence (deff unverified [A]).

**Status:**
- The Hybrid remains the **preferred research direction** (not approved).
- **F3 / R+:** proposed, **not approved** (weakly stricter than K).
- **F9:** **HOLD**. Updated evidence in A6 §2.4: per-cell trip-wire P(all pass) = 0.000 at λ = 0.36; the time-shift canary is confounded with legitimate persistence.
- **E2:** **HOLD**.
- **Separation of responsibilities:**
  - **Phase 1S:** R+ components only (stress flags, retained gates, applicability clause);
  - **Phase 2:** the envelope estimators, the CI rule, the state semantics and the verdict mapping;
  - **Phase 4 / E3:** forward monitoring and re-entry, under a separately approved protocol.
- **Gate A: OPEN. Gate B: NOT AUTHORISED.**
