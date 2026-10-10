# A10 — AM-4-A Stage A record: offset surrogates, independent oracle, bounded development verification

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE AS A PHASE 1S COMPONENT** — Stage A development evidence under the owner's bounded Stage A authorisation (2026-10-10). Nothing here is wired into the Phase 1S engine, nothing touches a frozen artefact, and nothing here is scientific validation of AM-4-A: passing engineering tests show the solvers compute what they claim, not that the canary is a valid leakage certificate. Stage B (exploratory pilot) and Stage C (confirmatory Phase 1S) remain NOT AUTHORISED.

**Labels:** **[F]** verified fact · **[M]** mathematical result · **[N]** numerical result · **[S]** statistical observation (sampling variability applies) · **[A]** assumption · **[R]** recommendation.

## 1. Baseline and branch [F]

| Item | Value |
|---|---|
| Gate A documentation HEAD (unchanged) | `a9204670ac7d19ed6f3175caee3a688d88ad50a3` on `docs/mi-phase1s-gate-a-review-20261009`; remote identical; that worktree clean |
| Implementation baseline | `df43073f6d313cd7b6f524a2d124821133a4ab77` (`feature/mi-phase1s-impl-20261009`, remote identical) |
| Stage A branch | `feature/mi-am4a-stage-a-20261010`, created from `df43073` in a new worktree `/home/tradmin/tsb-am4a-worktree`; no existing worktree or branch altered |
| Frozen set, before and after | all seven files match; set `fdf3366480976db6ada1ac90b62f6b6db1edc35a59d1f3527cfcd6fcbf28e157`; protocol `412cb606…`; map `9311b86d…` |
| Phase 1S code tree | baseline `1095b4fc…`; after Stage A `904c3ad61b9213133fc254c5e38a18806412010abe1fec3c92621628424b3f53` (new modules added; every pre-existing module byte-identical) |
| MI trial ledger | genesis `adcdc0b2…` only, 0 trials, unchanged |
| CPU budget ledger `f5983b83…` | 7 events, chain verified; charged 66.882077, remaining 28,733.117923, no reservations; file hashes unchanged (`66f7ca6d…`, `30d49aef…`) |
| Concurrency | no research or MI units; Paper R2, Collector and production containers untouched |

Note: the Stage A branch is based on `df43073`, which predates the Gate A review branch, so A1–A9 are **not** present on it; this file is placed at the suggested path so that a later documentation merge is trivial.

## 2. Mathematical assumptions verified before coding

**Binary tasks [M/F].** In `gen.t1_world` / `gen.t2_world`, y = 1[μ_y + s_b + s_x + z > 0] with s_x ~ N(0, τ_x²) and z of unit variance, independent of s_b. The baseline forecast is b = Φ((μ_f + s_b)/√(1 + τ_x²)).
- When μ_f = μ_y (every T2 cell and every T1 cell with brk = 0): b = P(y = 1 | s_b) exactly, so b is a valid conditional prior. The leak feature x = w_f(2y − 1) + e depends on y only; the noise features are `factor_series` draws independent of (s_b, s_x, z). Bayes: P(y = 1 | b, x, z) has logit = logit b + 2w_f x exactly, with zero coefficients on z. **Exact specification holds in 36 of 48 cells.**
- **Mismatch [F]:** in the 12 T1 break cells (brk = 1, `t1_break_mode = dev_calibrated`), μ_f = Φ⁻¹(π/2)·tot ≠ μ_y, by frozen design (OD-2): the baseline carries the pre-break rate while outcomes occur at π. Then b ≠ P(y = 1 | s_b); the calibrated quantity is `w.b_cal`. The offset identity with coefficient 1 on logit b is therefore **misspecified by a probit-scale shift** in those cells. This does not affect the solvers (the offset is an arbitrary input vector), but it must not be described as exact there. **Resolved by the owner (r2, §12.1): Option A, form E — logit(w.b) everywhere; w.b_cal is never a candidate input.**

**T3 [M/F].** `gen.t3_world`: y_i = state_{lag+i+7}, b_i = P^{7+lag}[state_{lag+i}], so b_{i,k} = P(y_i = k | state at the baseline lag) exactly (Markov). With lag = None the baseline is the stationary vector, which is the marginal of y under the stationary start. Noise sets are AR(p) series independent of the chain; x depends on y only. Hence P(y = k | b, x, z) ∝ b_k exp(w_f x_k): **exact in all six T3 cells.** All baseline entries are strictly positive (minimum 1.2e-5 at 0.99 adjacent).

## 3. Implemented specifications

**C2 binary (`firth.py`).** logit P(y = 1) = offset_i + x_iᵀβ; no intercept, no baseline coefficient (β has exactly the design's column count). Jeffreys-penalised objective ℓ* = ℓ + ½ log det I, I = XᵀWX; adjusted score U*_j = Σ_i (y_i − μ_i + h_i(½ − μ_i)) x_ij with hat diagonals h_i = w_i x_iᵀI⁻¹x_i; Fisher scoring step I⁻¹U*; deterministic step-halving on ℓ* (≤ 20 halvings); Cholesky with relative pivot floor 1e-12; stable log-sigmoid; predictions clipped to [1e-12, 1 − 1e-12]. FLIC is **not** implemented (comparator status only, per the directive). Unpenalised fit is available only as a diagnostic (`ml_separation_diagnostic`).

**C1 T3 (`clogit_offset.py`).** P(y_i = k) = b_{i,k} exp(θᵀc_{i,k}) / Σ_j b_{i,j} exp(θᵀc_{i,j}); log b is a fixed offset (coefficient 1, never estimated); no class constants; all K alternatives retained on every day; log-sum-exp normalisation; score c_{i,y} − Σ_k p_{i,k} c_{i,k}; information Σ_i Σ_k p_{i,k}(c − c̄)(c − c̄)ᵀ; Newton with step-halving; maximum likelihood (no penalty, per C1).

**Features (`leakfeat.py`).** w_f = 2 fixed as a module constant, not an argument. Binary x_i = 2(2y_i − 1) + e_i; T3 x_{i,k} = 2·1[k = y_i] + e_{i,k}; e from the frozen `gen.normals`. Designs: binary rows [x, z_1..z_6] with offset logit b; T3 rows C[i][k] = [x_{i,k}, z_{1,k,i}..z_{6,k,i}] with offset log b_{i,k}.

**Status taxonomy (both solvers).** CONVERGED (max|score| < tol_grad = 1e-8); FP_FLOOR (no ascent step exists at double precision while max|score| < 1e-6 but ≥ tol_grad: a finite iterate at the objective's floating-point floor, **not** a certified optimum); ITER_CAP (100 iterations); NUMERICAL_FAIL (singular or ill-conditioned information, non-finite values, stalled line search with a large gradient); DIVERGED (unpenalised comparator only: vanishing score with |β| ≥ 30, i.e. separation, no MLE). A step-size check (1e-10) is reported but never suffices for CONVERGED on its own. No path returns zero coefficients as a success; every result carries status, iterations, objective, gradient norm, condition estimate and the objective trace.

**Harness (`am4a_dev.py`).** Seed namespace `am4a-dev` (sha256 of `am4a-dev|test|case|rep|role`, 16 hex digits, duplicate-seed registry), disjoint from the Phase 1S seeds (`contract_sha|cell|kind|level|rep`). Fixtures use the frozen generators read-only (`t2_world`, `t3_world`) with independent `dev` and `eval` draws and separate leak-noise streams. It never reads the frozen 48-cell grid, never computes a ceiling and never counts fires.

## 4. Files added (dev branch only) [F]

| File | SHA-256 | Lines |
|---|---|---|
| `p2_research/mi/phase1s/firth.py` | `20bdc65bb701d2acc3d68c109752d403f30a16466c27e983fb61747ceef898e3` | 310 |
| `p2_research/mi/phase1s/clogit_offset.py` | `44ef902f02f454f5948b55eca66719f1e967f7fdd057969a324f62ef23ffc40d` | 173 |
| `p2_research/mi/phase1s/leakfeat.py` | `f50a40b01395bbb2534c398e37b4b7b1cf0dd2e0e9a5edcfd03f42a728e2db10` | 61 |
| `p2_research/mi/phase1s/am4a_dev.py` | `0415551a4da9b0c75c693d54d9fd5b1920aaa7025053d6c2b96dd883d4b08dcc` | 164 |
| `p2_research/tests/am4a_oracle.py` | `5fa953ce2ae902b0d8b913763ebc2c25947a96a21cabe494705231ba746276b5` | 159 |
| `p2_research/tests/test_mi_am4a_stage_a.py` | `f4498d081908dd6e0a3ece75fbc695662db622d9f92acca61bc7acc00415e724` | 342 |
| `docs/mi/review/gate_a/A10_STAGE_A_RECORD.md` | this file | — |

**No-touch verification [F]:** `git diff --name-only HEAD` over the seven frozen files, all pre-existing `phase1s` modules (`gen`, `rules`, `engine`, `l2`, `stats`, `params`, `release`, `sandbox`, `store`, `__main__`, `__init__`), and the existing MI tests is empty. `rules.run_leak`, `engine.fire_count`, `params.GEN["leak_weight"]`, the 95-of-100 rule, the task-wide ceiling, the STOP codes and the 48-cell grid are unchanged. Dependencies: standard library only (test 19 asserts the new modules import nothing from `engine`, `rules`, `l2`, `sandbox`, `store`, `release`, `subprocess` or `sqlite`, and that the oracle imports only `__future__` and `math`).

## 5. Independent oracle methodology

`p2_research/tests/am4a_oracle.py` shares no code with the implementation: logistic log-likelihood as y·η − log(1 + e^η) with the max-shift identity log(1 + e^t) = max(t, 0) + log1p(e^{−|t|}); μ by direct e^η/(1 + e^η); Fisher information by explicit double loops; determinants by cofactor expansion; the Firth objective as ℓ + ½ log det; a scalar-case adjusted score; conditional-logit probabilities by direct exponentiation; expanded-form Brier scores; central finite differences; bisection and golden-section search for the worked examples. Closed-form anchors (β = 0, offset 0: ℓ = n log ½, I = ¼XᵀX) are checked against both the implementation and the oracle.

## 6. Deterministic test results [F]

`python3 -m unittest p2_research.tests.test_mi_am4a_stage_a`: **19 passed, 0 failed** (CPU 0.9 s).

| Directive item | Test | Evidence |
|---|---|---|
| 1 objective vs oracle | 01, 03 | relative error < 1e-10 for ℓ and ℓ*, binary and conditional logit; closed forms to 12 and 10 places |
| 2 score and Hessian vs independent finite differences | 02, 03 | adjusted score vs ∇ of the oracle Firth objective < 1e-6 relative; information vs −∇² of the oracle log-likelihood < 1e-5; same for the conditional logit |
| worked examples | 04 | Firth p = 1 with offset: implementation root equals the oracle's bisection root of the adjusted score to 8 places (fit at tol_grad 1e-10) and the golden-section maximiser to 6; default-tolerance fit within 1e-6. Conditional logit p = 1, K = 6: golden-section maximiser to 6 places |
| 3 fixed offsets cannot be fitted | 05 | β has exactly p entries; shifting the offset by c shifts every logit by exactly c; doubling the offset changes the fit (it is used, not absorbed); T3 θ has exactly p entries |
| 4 normalisation | 06 | T3 rows sum to 1 within 1e-12 with six positive entries; binary predictions within [1e-12, 1 − 1e-12] |
| 5 T3 uniform baseline | 07 | frozen 0.85-uniform world: lag = None, offsets constant across alternatives; information at θ = 0 non-singular; fit CONVERGED |
| 6 T3 missing class | 08 | class 5 absent from a 300-day dev draw: CONVERGED, two parameters, evaluation rows keep six alternatives with positive probability for class 5 |
| 7 complete separation | 09 | Firth CONVERGED with finite coefficients (|β| < 20); the unpenalised comparator reports DIVERGED (vanishing score, |β| ≥ 30) and the diagnostic flags separation |
| 8 near-separation | 10 | CONVERGED, finite, finite condition estimate |
| 9 singular information | 11 | duplicate column, zero column, and an alternative-constant T3 covariate all give NUMERICAL_FAIL with a singular message |
| 10 iteration cap | 12 | max_iter = 1 gives ITER_CAP for both solvers, never CONVERGED |
| 11 line-search monotonicity | 13 | objective trace non-decreasing within 1e-12 |
| 12 overflow / underflow | 14 | offsets to ±1000 and coefficients ±800: finite objective, bounded probabilities, exact log-sigmoid limits, normalised T3 rows |
| 13 byte-identical replay | 15 | identical SHA-256 of the fitted and predicted outputs across two runs |
| 14 seed namespace and duplicates | 16 | `am4a-dev` seeds differ from the Phase 1S `seed_hex` for the same labels; duplicate seeds raise; dev and eval leak streams differ |
| 15 Brier and ranges; features; isolation | 17, 18, 19 | Brier equals the oracle's expanded forms to 14 places; multiclass Brier in [0, 2]; leak-feature class means within 0.15 of ±2 (binary) and 2 / 0 (T3); modules unwired |

Existing suites on the same tree: `test_mi_phase1` **38 passed** (CPU 0.4 s); `test_mi_phase1s` **43 passed** (CPU 24.6 s). Both runs happened after the last code edit.

## 7. Statistical development checks [S]

Harness manifest (second run; the first run gave bit-identical coefficients and statuses):

| Check | Fixture (dev namespace, not a frozen cell) | Status | θ_x (target) | SE | Deviation | Noise coefficients / SE | Eval Brier cand. / base | Eval BSS |
|---|---|---|---|---|---|---|---|---|
| S1 | T2-type world, n = 20,000, π = 0.3, no skill, 6 noise features | CONVERGED (12 it., grad 2.8e-10) | 4.0167 (4) | 0.101 | +0.17 SE | 0.56, 2.25, −0.79, −0.68, 1.01, −0.56 | 0.0142 / 0.184 | 0.923 |
| S2 | T3 world, 20,000 days, p = 0.95 adjacent (lag 2) | CONVERGED (7 it., grad 9.5e-13) | 1.9987 (2) | 0.020 | −0.06 SE | 2.79, −0.27, −0.38, −1.87, 0.70, −2.21 | 0.187 / 0.519 | 0.640 |
| S3 | T3 world, 3,000 days, p = 0.85 uniform (lag None, constant offset) | CONVERGED (7 it., grad 1.4e-13) | 2.0145 (2) | — | — | — | — | — |

Calibration-in-the-large on the S1 evaluation draw: mean μ − mean y = 0.0004. Expected sampling variability: with 12 noise t-ratios, a maximum |t| of 2.79 has about 6 % probability under the null of zero coefficients, so nothing here is anomalous; these are observations, not property tests, and no seed was changed after viewing results. The S1 and S2 BSS values are diagnostics on development fixtures; no ceiling exists for them and no fire was counted.

## 8. Numerical stability and convergence findings

- Both solvers converged in 7–12 iterations on 20,000-row fixtures with gradient norms below 1e-9.
- **Finding 1 (fixed during Stage A, disclosed):** the unpenalised comparator on completely separated data reached a vanishing score with diverging coefficients; it would have reported CONVERGED. This is the textbook separation signature (Heinze 2006), so the comparator now reports DIVERGED whenever the score vanishes with |β| ≥ 30. The primary Firth fit was finite and CONVERGED on the same data from the start.
- **Finding 2 (fixed, disclosed):** the initial tiny-step rule classified a fit as NUMERICAL_FAIL when the requested gradient tolerance (1e-12) lay below the floating-point floor of the objective. The rule now continues iterating after a tiny step, and a stalled line search with a gradient below 1e-6 is reported as FP_FLOOR, distinct from both CONVERGED and NUMERICAL_FAIL. The worked example is run at tol_grad = 1e-10, where CONVERGED is reached and matches the independent root to 8 places.
- The unpenalised Newton in the frozen `stats.logistic_fit` has no line search and only an exact-zero pivot check; nothing was changed there.
- Edge cases documented: Cholesky relative pivot floor 1e-12 (ill-conditioning is reported as singular); probabilities clipped at 1e-12; T3 offsets as low as −27.6 after clipping are handled by log-sum-exp.

## 9. CPU usage and accounting [F]

| Rule applied | Source |
|---|---|
| Offline development and synthetic unit tests are "tiny CPU, no budget" | `docs/mi/MI_PHASE1S_READINESS.md` B1 row; MI_PHASE1_CONTRACT.md ("unit tests only"); the protocol's `budget` block charges Phase 1S **jobs** under `cgroup_cpu_budget_guard_v1` |
| Same treatment as the `df43073` development diagnostics | A4 §6 forking-path list; the budget ledger holds only the guard smoke campaigns |
| Owner bound for Stage A | ≤ 500 CPU-s, low priority, outside protected windows (this directive) |

Measured with `resource.getrusage` (no external tools on the host), all runs under `nice -n 19`, outside the hourly :12–:25 and daily protected windows, no other MI campaign running:

| Run | CPU-s | Peak RSS |
|---|---|---|
| Stage A tests (3 runs during development) | 0.94 + 0.86 + 0.89 | 22 MB |
| Harness (2 runs) | 15.85 + 15.54 | 140 MB |
| `test_mi_phase1` (2 runs) | 0.38 + 0.41 | 22 MB |
| `test_mi_phase1s` (2 runs) | 24.77 + 24.63 | 29 MB |
| **Total** | **≈ 84.3 CPU-s** | ≤ 140 MB |

No MI-slice execution, no reservation, no ledger write, no trial-ledger write. The budget ledger files are byte-identical before and after.

## 10. Reproducibility

From the repository root on branch `feature/mi-am4a-stage-a-20261010`:
```
PYTHONPATH=. python3 -m unittest p2_research.tests.test_mi_am4a_stage_a -v
PYTHONPATH=. python3 -m p2_research.mi.phase1s.am4a_dev --out <dir>
```
The harness manifest records interpreter, platform, tolerances, every seed used and the per-check results; coefficients and statuses reproduced bit-identically across two runs (timing fields differ, so the manifest hash differs). Interpreter: `/usr/bin/python3` 3.12 on aarch64.

## 11. Limitations, open items and verdicts

| Item | Verdict | Note |
|---|---|---|
| Solver correctness (objective, derivatives, worked examples, failure taxonomy) | **ACCEPT** (VERIFIED implementation property) | §6 |
| Offset identity, binary non-break cells and all T3 cells | **ACCEPT** [M] | §2 |
| **Offset identity in the 12 T1 break cells** | **HOLD** | misspecified by design (dev-calibrated baseline); owner decision on logit b vs logit b_cal required before Stage B |
| Firth uniqueness on these designs | assumption [A] | not tested; a restart test is a candidate addition |
| T3 finite-sample separation in seven dimensions | assumption [A] | negligible analytically; detected by DIVERGED/ITER_CAP if it occurs |
| Coefficient recovery | statistical observation [S] | consistent with targets at the 0.2 SE level on one fixture each; not a property test |
| Scientific validity of AM-4-A as a leakage certificate | **not established** | Stage A cannot establish it; A8 §2 non-identifiability stands |
| FLIC | not implemented | comparator only; separate approval |
| Future protocol text (proposed, not drafted) | — | AM-4-A item 1 must state the offset form (log b with coefficient 1) and name the break-cell treatment; C6 definition for T3 |

**Stage B readiness:** the solvers and feature generator are implementation-ready for the exploratory pilot design (A8–A9 lineage, pre-registration in the Stage A directive). **Stage B is not authorised and should not start** until (1) the break-cell offset decision, (2) the budget amendment (the pilot plus the eventual confirmatory run may exceed the remaining 28,733 CPU-s), and (3) the pre-registration hash are approved.

Governance unchanged: F9 HOLD; F3/R+ PROPOSED; E2 HOLD; Gate A OPEN; Gate B NOT AUTHORISED beyond this Stage A permission; MI-C v1.0, Phase 1S protocol and derivation map FROZEN; no automatic MI-C v2.0.

---

## 12. Revision r2 (2026-10-10): T1 break decision record and targeted hardening

Authorised by the owner directive "Stage A Targeted Hardening and T1 Break Decision Record". Base: Stage A commit `f6a74c4…` (parent `df43073…`). Baseline re-verified before the edits: Gate A HEAD `a9204670…` clean; frozen set `fdf33664…`; trial ledger genesis only; budget ledger 7 events, chain intact, 66.882077 charged, 28,733.117923 remaining, no reservations; no engine wiring; no active research units.

### 12.1 T1 break decision as recorded (owner approval: Option A, form E)

1. **Fixed-offset rule, every binary T1/T2 cell:** offset_i = logit(w.b_i), coefficient exactly 1. No free baseline coefficient, no fitted intercept, no regime correction, no break-specific parameter. The Firth solver's statistical specification is unchanged. w_f = 2 unchanged.
2. **w.b_cal is rejected as an AM-4-A candidate input.** Its only permitted roles are reference analysis and its existing frozen use in the null B3 size test (`rules.py:138`).
3. **Exactness scope [M/F]:** in the 36 cells with μ_f = μ_y (all 18 T2 cells, the 12 T1 brk = 0 cells, and the 6 T3 cells under their own identity) the offset posterior identity logit P(y = 1 | b, x, z) = logit b + 2w_f x is exact under the verified generator assumptions. In the **12 T1 break cells** (`T1|…|brk=1`, `t1_break_mode = dev_calibrated`) the offset is point-in-time admissible but the surrogate is **misspecified** relative to the generator's post-break conditional prior.
4. **Frozen probit-shift relation [M, generator-only analysis quantity]:** Φ⁻¹(w.b_cal) = Φ⁻¹(w.b) + δ with δ = (μ_y − μ_f)·sf, μ_y = Φ⁻¹(π)·tot, μ_f = Φ⁻¹(π/2)·tot, sf = 1/√(1 + τ_x²). δ depends on the post-break rate π and is **not** information available to the candidate; it is recorded for analysis only and no reference posterior built from it is an admissible candidate forecast.
5. **Not established:** the F9 detection margin in break cells. No claim is made that it is unaffected; the magnitude and consequences of the misspecification remain unverified until a separately authorised exploratory evaluation.
6. **Scope of the exactness-versus-admissibility conflict:** it follows from the information available and the design choices in this frozen synthetic setup; it is not a universal statement about forecasting systems.
7. Stage A code already used w.b (`am4a_dev.py` fixtures, `leakfeat.binary_offset`); the harness manifest now records the rule verbatim (`offset_rule`).

### 12.2 Hardening tests H1–H5 (all deterministic; `HardeningR2` in `test_mi_am4a_stage_a.py`)

| Item | Fixture and branch exercised | Result |
|---|---|---|
| **H1 FP_FLOOR** | natural fixture: strict acceptance rule `ls_tol = 0.0` with `tol_grad = 1e-14` on a 1,000-row design (seed 41) reaches the FP_FLOOR branch (gradient 2.7e-7, 8 iterations, 49 halvings); no internal manipulation | status FP_FLOOR, never CONVERGED; β, objective and gradient finite; message discloses the gradient; `am4a_dev.fit_is_success` is False and `fit_record` propagates status and message verbatim; `SUCCESS_STATUSES == ("CONVERGED",)`. The same fixture under the default scale-aware rule converges (coefficients within 1e-6), so the floor is a property of the strict rule, not of the optimum |
| **H2 SEs / inverse diagonal** | `inverse_diag` vs the oracle's cofactor inverse on a 3×3 SPD matrix and a 2×2 closed form; `standard_errors` vs √diag of the cofactor inverse of the oracle's own information matrix; column permutation; non-PD and near-singular matrices; a duplicated-column design | agreement ≤ 1e-12 (3×3), 14 places (2×2), ≤ 1e-10 relative (SEs); ordering follows the columns; SEs finite and positive; `SingularError` raised in all refused cases; no self-comparison |
| **H3 line-search singular branch** | documented fault-injection seam `firth_fit(objective=…)`: (a) the first trial point raises `SingularError` once; (b) every trial point raises | (a) the trial is rejected, the step halved (`halvings_total ≥ 1`), the fit converges to the reference optimum within 1e-7, and the accepted trace stays monotone; (b) NUMERICAL_FAIL ("stalled"), β remains the untouched start iterate, `halvings_total = MAX_HALVINGS + 1`, never CONVERGED. Limitation: a non-injected fixture could not be constructed because Fisher scoring with step-halving from a positive-definite start is scale-invariant and does not reach a singular trial point on realistic designs |
| **H4 offset clipping** | `logit_clipped` / `log_clipped` at 0, 1e-13, 1e-12 (lower boundary), 2e-12, 1 − 2e-12, 1 − 1e-12 (upper boundary), 1.0, 1.5; NaN and ±inf; a fit with both boundaries clipped | clipping to [1e-12, 1 − 1e-12] as policy; logits finite (±27.63 at the boundaries); non-finite inputs raise `ValueError` (never clipped or reinterpreted); the offset coefficient stays 1 (exact 0.25 logit shift on every interior row). **Disclosed numerical property:** near the upper boundary the logit inherits the representation error of 1 − p, bounded by u/(1 − p) (≈ 5.5e-5 at p = 1 − 2e-12); T1/T2 baselines (π ≤ 0.5) never approach that boundary; the clip is a safeguard, not a probabilistic identity at the boundary |
| **H5 acceptance tolerance** | review of `llp2 >= llp − 1e-12` | **Changed** to a scale-aware tolerance (§12.3). Tests: tolerance values (< 1e-13 at n = 24, < 2e-10 at n = 4,000, < 1e-8 at n = 20,000); an injected material decrease of 1e-6 below the current objective is never accepted (NUMERICAL_FAIL, start iterate untouched); a 4,000-row fit converges with 0 halvings and a monotone trace; the strict rule on the same problem produces no false convergence; the conditional logit uses the same rule |

### 12.3 Numerical change and rationale (H5)

Old rule: accept a trial if llp2 ≥ llp − 1e-12 (absolute). The objective is a sum of n same-sign log-probability terms plus a small penalty; the forward error of floating summation is bounded by (n − 1)·u·Σ|t_i| ≈ n·u·|ℓ| in the worst case and behaves like √n·u·|ℓ| for random rounding (u = 1.1e-16). At n = 2·10⁴, |ℓ| = 10⁴ that is ~10⁻¹⁰, so the absolute 1e-12 could reject valid steps at large |ℓ| (and, under strict acceptance, produced the H1 floor), while being needlessly loose at small |ℓ|. New rule (`firth.ls_tolerance`): accept if llp2 ≥ llp − 4·eps·√n·(|llp| + 1). This is ~10⁻¹³ relative: it conceals no material decrease (material decreases in these problems are ≥ 10⁻⁶) and tracks the resolvable rounding noise of comparing two evaluations. The same tolerance is used by the conditional logit with n = number of days. `ls_tol` remains available as an explicit absolute override (0.0 = strict). Effect on the r1 harness fixtures: S1 converged in 11 instead of 12 iterations with max |Δθ| = 2.9e-12; S2 and S3 bit-identical.

Other code changes in r2: `firth_fit(objective=…)` fault-injection seam (default `penalised_loglik`; never set by the harness); `leakfeat._finite_prob` rejects non-finite probabilities; `am4a_dev.fit_is_success` / `fit_record` / `SUCCESS_STATUSES` and the `offset_rule`, `success`, `non_success_checks` manifest fields; harness version `am4a-stage-a-1.1.0`; oracle `inverse_cofactor`. The DIVERGED, ITER_CAP and NUMERICAL_FAIL semantics are unchanged.

### 12.4 Results, CPU and integrity

| Suite / run | Result | CPU-s |
|---|---|---|
| Stage A tests (19 original + 5 hardening) | **24/24 pass** (two runs after the final edits) | 2.7, 2.7 |
| `test_mi_phase1` (frozen) | 38/38 pass | 0.4 |
| `test_mi_phase1s` (frozen) | 43/43 pass | 24.4 |
| Harness (S1–S3) | all CONVERGED, `non_success_checks = []`, θ_x 4.0167 / 1.9987 / 2.0145 | 15.5 |
| Development probe for the H1 fixture | — | 2.5 |
| Earlier iteration runs of the suite during development | — | 1.1 |
| **Total r2** | | **≈ 49 CPU-s** of the 150 allowed; peak RSS 140 MB |

Accounting: same rule as r1 (offline development and synthetic unit tests, "tiny CPU, no budget", `MI_PHASE1S_READINESS.md` B1); all runs under `nice -n 19`, outside the hourly :12–:25 and daily protected windows, no other MI campaign; no MI-slice execution, no reservation, no ledger write. Budget and trial ledgers byte-identical before and after (`66f7ca6d…`; genesis only).

Frozen set verified before and after: `fdf33664…`. No pre-existing `phase1s` module, frozen file or existing test changed (`git diff` over those paths is empty). Code tree after r2: `767b637d082a3ab5022344c8f8cb5f708d80d10fbaf525c43321fab642b661bf`. File hashes (first 16 hex): `firth.py` fe7de76ff6d13458, `clogit_offset.py` 9dfeb4b161775587, `leakfeat.py` 1a63c48580059c96, `am4a_dev.py` 3974ba782c5b1035, `am4a_oracle.py` 65a18be92c572105, `test_mi_am4a_stage_a.py` cfab70d5ec48e014.

### 12.5 Remaining assumptions and limitations after r2

- The break-cell misspecification effect on BSS and on θ_x (the leak feature has mean w_f(2π − 1) ≠ 0, so part of the missing shift can be absorbed by θ_x) is **unquantified** [A].
- Firth uniqueness on these designs remains an assumption [A]; the H1 fixture shows strict and scale-aware rules reach the same optimum, which is consistent with uniqueness but not a proof.
- The line-search singular branch is covered by fault injection only (§12.2 H3).
- Passing Stage A establishes implementation properties only; it does **not** establish leakage-detection sensitivity (A8 §2 non-identifiability stands).

Verdicts: T1 break rule (Option A, form E) **recorded** as approved; solver hardening H1–H5 **ACCEPT**; Stage A implementation **implementation-ready for the Stage B design**; Stage B **HOLD** pending the budget amendment, the pre-registration hash and a Stage B GO.
