# A8 — F9: independent mathematical audit, non-identifiability of the L1 leak, and structural PIT canary design review

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE** — Gate A review material. Nothing here is an owner approval, a protocol amendment or a frozen artefact, and nothing here may be loaded by any run. The control designs in §6–§7 are **conceptual specifications**: not implemented, not tested, not validated on real data.

**Recorded** 2026-10-09 on `docs/mi-phase1s-gate-a-review-20261009` (base `1d3df75`). Appendix to A6 §2 and to the earlier F9 session reports. It **supersedes** the F9 statements listed in §0.2 where they conflict.

**Labels:** **[F]** verified fact · **[M]** exact mathematics · **[N]** deterministic numerics (approximate: quadrature, delta method, normal approximation) · **[A]** assumption · **[L]** literature · **[R]** recommendation.

## 0. Baseline, scope and corrections

### 0.1 Baseline [F]

| Item | State at recording |
|---|---|
| Branch / HEAD | `docs/mi-phase1s-gate-a-review-20261009` at `1d3df750f5657ee619a44b0a0260ae237782e87f`; remote identical; working tree clean |
| Frozen set | all seven files match `FROZEN_SHA256SUMS.json`; set hash `fdf3366480976db6ada1ac90b62f6b6db1edc35a59d1f3527cfcd6fcbf28e157`; protocol `412cb606…`; derivation map `9311b86d…` |
| Gate A documents | A1–A7 present |
| MI trial ledger | genesis `adcdc0b2…` only; `trials.jsonl` absent; 0 trials |
| CPU budget ledger `f5983b83…` | 7 events (seq 0–6), hash chain verified event by event (SHA-256 of the sorted compact JSON body, `prev` links intact). **Latest charge event** (seq 6, campaign `d4r-smoke`): 6.882077 CPU-s against a 30 CPU-s reservation. **Cumulative charged** (sum of the three charge events): 66.882077 CPU-s. These are different quantities; neither is inferred from the other. Remaining: 28 733.117923 of 28 800 CPU-s |
| Checkpoint | `budget.checkpoint.json`: seq 6, events 7, `charged_cpu_s` = `committed_cpu_s` = 66.882077, head = hash of event 6, no open reservations, `self_sha256` verified |
| Anchor | `backups/micpu-d4r-completion-20261008T2333Z/anchor_copy.json` is byte-for-byte the same record as the checkpoint |
| Implementation | unchanged since `df43073` |

### 0.2 Corrections to earlier statements (earlier documents are **not** edited)

| Source | Statement | Correction recorded here |
|---|---|---|
| A6 §2.3 item 1; F9 feasibility session report (2026-10-09, not a repo document) | "With a meaningful leak (λ = 0.36) the frozen 95 % requirement … is essentially unattainable" / "the frozen 95 % rule can't be met by any skill-magnitude detector" | True only for the **IR-6 λ-leak at λ = 0.36** under the A6 assumptions. The frozen count rule is met **trivially** by the implementation's w = 2 canary (§3.4). The requirement is not universally impossible (§3.3) |
| F9 feasibility session report | "Exact limit [M] (Neyman–Pearson)" for the magnitude-only class | Overstated for the composite null (§3.1). The exact statement that survives is the non-identifiability identity of §2 |
| F9 feasibility session report | λ_min table presented as the minimum detectable leak for the class | λ_min is approximate and **specific to the threshold-on-BSS detector** (§3.2) |
| A6 §2.4 "Contract impact" | "`derive.py` and the derivation map are unchanged (they read only fire_k / n)" | Syntactically true; **scientifically insufficient**: `derive()` compatibility in meaning requires a frozen definition of a "fire" (§8) |
| A2 IR-6 | "The current w = 2 gives 0.31–0.85" (expected BSS) | My quadrature at κ(0.02) gives 0.376 (π 0.01), 0.603 (0.05), 0.833 (0.2), 0.913 (0.5) (§3.4). The ranges differ (different cells or a sampled diagnostic); both place w = 2 far above every ceiling. To be reconciled, not a contradiction |

### 0.3 What this appendix is not

No protocol amendment, no implementation, no simulation campaign, no calibration, no λ or threshold retuning, no new frozen probability target. The only computations are the deterministic ones described in §11, run outside the MI slice, charged to no ledger.

## 1. Three distinct leakage mechanisms

| # | Mechanism | Definition | Calibrated | Layer | Source |
|---|---|---|---|---|---|
| M-F | **Frozen text** | `truth_classes.leak`: "the label enters one feature with weight w (A7 canaries must fire)" | undefined | names a **feature**: representable only where features exist (L2) | protocol v1.0 [F] |
| M-I | **Implementation** (OD-4) | binary tasks: f = σ(logit f_κ(bss_min) + w·(2y − 1)), w = 2; T3: + w on the log-probability of the realised class, renormalised | **No**: f is a direct function of the realised label y | L1 | `rules.run_leak`, `params.GEN["leak_weight"]` [F] |
| M-λ | **Gate A IR-6 λ-leak** | the outcome shock is z = ℓ + z′ with ℓ ~ N(0, λ); f = Φ((μ + s_b + s_k + ℓ)/√(1 + τ_u² − λ)) built on the bss_min skill candidate | Yes (§2.2) | L1 | A2 IR-6, A6 §2.1 |

**Why they are not interchangeable [M/F].**
- M-F describes a feature-level object. L1 has no features and no timestamps; L2 has simulated noise features but no timestamps. Neither L1 construct (M-I, M-λ) contains a feature, so neither *implements* M-F; both are forecast-level proxies for it.
- M-I and M-λ differ in kind, not in strength. M-I's forecast reveals the label deterministically (two forecast values per row, one for each y); it is miscalibrated by construction (a calibration regression of y on logit f separates perfectly, so slope → ∞ [M], not computed). M-λ is exactly calibrated and, as §2 shows, indistinguishable from legitimate skill over a range of λ.
- The parameters w and λ live on different scales. They can be matched only through the expected BSS each induces (§3.4), and even then the realised-BSS distributions differ.
- Consequently, a result proven for one mechanism (e.g. the λ-leak non-identifiability) does not transfer to another, and a count of fires obtained under M-I says nothing about M-λ or M-F.

## 2. Non-identifiability of the calibrated λ-leak at L1

### 2.1 Generator (binary tasks T1 / T2) [F]

From the frozen implementation (`gen.binary_design`, `gen.t1_world`, `gen.skill_forecast`), with τ_b = τ_x = 0.6 (`params.GEN`):

- Row latent: **y = 1{ μ + s_b + s_k + s_u + z > 0 }** with independent s_b ~ N(0, τ_b²) (baseline-visible), s_k ~ N(0, κ τ_x²) (skill-visible), s_u ~ N(0, τ_u²), τ_u² = (1 − κ) τ_x² (unobserved signal), z ~ N(0, 1) (outcome shock); μ = Φ⁻¹(π) √(1 + τ_b² + τ_x²).
- Baseline forecast: **b = Φ((μ + s_b)/√(1 + τ_x²))**.
- Legitimate skill forecast at skill share κ: **f_κ = Φ((μ + s_b + s_k)/√(1 + τ_u²))**. κ(π, level) is solved so that E[BSS] equals the level (`gen.kappa_for`).
- In T1 the row shocks z are built from overlapping sums of iid innovations (six-step overlap) and the signals are AR(φ) factor series; in T2 events are day-clustered with factor loading ρ. The derivation below is **per row**; see §2.5 for what this means.

### 2.2 The calibrated λ-leak model (IR-6) and its calibration [M]

Split the shock as z = ℓ + z′ with ℓ ~ N(0, λ), z′ ~ N(0, 1 − λ), independent, 0 ≤ λ ≤ 1. The leaky forecaster observes I_λ = (s_b, s_k, ℓ). The unobserved remainder is s_u + z′ ~ N(0, τ_u² + 1 − λ). Hence

**P(y = 1 | I_λ) = Φ((μ + s_b + s_k + ℓ)/√(1 + τ_u² − λ)) = f_λ.**

So f_λ is the exact conditional probability given its own information set: it is calibrated.

### 2.3 The equivalent legitimate model [M]

Take a legitimate forecaster with skill share κ′ defined by

**κ′ τ_x² = κ τ_x² + λ**, equivalently **τ_u′² = (1 − κ′) τ_x² = τ_u² − λ.**

Its information set is I′ = (s_b, s′) with s′ ~ N(0, κ′ τ_x²), its remainder is s_u′ + z ~ N(0, τ_u′² + 1) = N(0, 1 + τ_u² − λ), and its calibrated forecast is

**f_{κ′} = Φ((μ + s_b + s′)/√(1 + τ_u² − λ)).**

### 2.4 Equality of the joint laws [M]

Under M-λ the pair (s_b, s_k + ℓ) is a pair of independent normals with variances (τ_b², κ τ_x² + λ). Under the legitimate model (s_b, s′) is a pair of independent normals with the same variances. The forecast is the **same function** of that pair in both models (same μ, same denominator √(1 + τ_u² − λ)), the baseline b is the same function of s_b, and in both models y | (b, f) ~ Bernoulli(f) by calibration. Therefore

**Law(b, f_λ, y) = Law(b, f_{κ′}, y)**  for every row.

**Valid range.** κ′ ≤ 1 and τ_u′² ≥ 0 require **λ ≤ τ_u² = (1 − κ) τ_x²**. Beyond that range no legitimate member of the generator family reproduces the leaky law: the leak is then "sharper than legitimately possible".

**Consequences (exact).**
- E[BSS(κ, λ)] = E[BSS(κ′, 0)]: the λ-leak's expected skill is that of a legitimate forecaster with a larger skill share. In particular, with κ = 0, the leak that fakes bss_min = 0.02 satisfies **λ_harm = κ(π, 0.02) τ_x²**.
- Every statistic computed from per-row (baseline, candidate, outcome) triples with exchangeable treatment of rows (Brier and log-loss differentials, bootstrap or DM p-values of them, calibration slope / intercept / in-the-large tests, realised BSS and its maximum over reps) has the **same distribution** under the two models.

### 2.5 What L1 exposes, and why equal laws block detection [F/M]

The frozen L1 layer is "forecast-level simulation: true p_t, baseline forecast, candidate forecast, outcomes; rules B1–B6 applied exactly as frozen; no model fitting". The rules see per-row triples (b, f, y). By §2.4 any decision rule applied to those triples has identical operating characteristics under M-λ (κ, λ) and under legitimate skill κ′. A detector can therefore only "detect" the leak with the same probability with which it falsely accuses the legitimate forecaster of level BSS(κ′). This holds for **any** detector operating on the L1 observables, not only magnitude detectors.

Two qualifications keep this precise:
- The "true p_t" of the generator is itself f_λ under M-λ and f_{κ′} under the legitimate model, so it adds nothing. A simulation can of course *know* that it injected ℓ, but that knowledge is not an observable available on real data.
- **Serial structure.** The identity is per row. In T1 the leaked component ℓ inherits the six-step moving-average dependence of the shock, whereas legitimate signals are AR(φ). A detector of the candidate's serial dependence would not be covered by the identity. It is not among the frozen rules, and on real data it would require knowledge of the legitimate dependence family, which is unknown (E2 is on HOLD for the same reason).

### 2.6 Numerical confirmation [N]

Independent re-implementation (§11; 41-node trapezoid on ±6 sd per dimension, versus 25 nodes on ±5 in `draft/f9_leak_detection_analytic.py`):

| π | κ(π, 0.02)·τ_x² | λ_harm by bisection | τ_u² at κ(0.02) | max legitimate E[BSS] (κ = 1) | E[BSS] at λ = 0.36 (A2 IR-6) |
|---|---|---|---|---|---|
| 0.01 | 0.1509 | 0.1509 | 0.209 | 0.060 | 0.101 |
| 0.05 | 0.0840 | 0.0840 | 0.276 | 0.101 | 0.131 |
| 0.2 | 0.0535 | 0.0535 | 0.307 | 0.144 | 0.168 |
| 0.3 | 0.0485 | 0.0485 | 0.312 | 0.155 | 0.178 |
| 0.5 | 0.0456 | 0.0456 | 0.314 | 0.163 | 0.184 |

The first two columns agree to four decimals, as the identity predicts. λ = 0.36 exceeds τ_u² in every cell, so the IR-6 leak lies **outside** the legitimate family and is detectable in principle; the obstacle for the frozen trip-wire is the ceiling's multiplicity (A6 §2.3 item 3: T1 ceiling median 0.109 exceeds the family maximum 0.060 at π = 0.01).

### 2.7 The result is model-specific

It holds for the probit latent generator of `gen.py` with the IR-6 calibrated shock-share leak, for λ ≤ τ_u², per row. It is **not** a statement about: leaks with λ > τ_u²; the implementation's M-I shift (miscalibrated, hence distinguishable by calibration tests); feature-level leaks at L2 (although a noisy feature proxy of y, once fitted by a calibrated surrogate, reduces to the same situation); T3; structural information such as timestamps or feature lineage; or detectors that use the serial structure. It must not be generalised to "all leakage is undetectable".

## 3. Statistical corrections

### 3.1 The Neyman–Pearson claim was overstated [M/L]

Neyman & Pearson (1933) establish that for a **simple** null against a **simple** alternative the best critical region consists of the sample points with the largest likelihood ratio, and they note that uniformly most powerful tests do not in general exist for composite hypotheses (full text reviewed, §5). The F9 null is composite: legitimate skill with κ anywhere in [0, κ(π, 0.05)]. The threshold-on-BSS detector is uniformly most powerful only in the idealisation of a normal location shift with common variance (monotone likelihood ratio). The leak alternative has a larger realised-BSS variance (e.g. 0.029 vs 0.019 at π = 0.01, λ = 0.36), so strictly no UMP test exists and the earlier "exact NP bound for the class" is withdrawn. The exact statement that remains is §2.

### 3.2 λ_min is approximate and detector-specific [N/A]

λ_min(cell) was defined as the smallest λ such that m_leak − z_{p*} s_leak ≥ m_legit(0.05) + z_{1−α′} s_legit, i.e. the **threshold-on-realised-BSS test** with false alarm α′ against the top legitimate level reaches per-rep power p*. It rests on: the delta-method variance of a ratio of sums; a normal approximation to realised BSS (weakest at π = 0.01 and n = 150); iid rows with a design effect applied as a pure variance multiplier; T3, stress and break cells not computed. With p* = 0.9736 (the per-rep power that gives a 95 % cell-pass probability, §4):

| Cell | λ_harm | λ_min, deff 1 (α′ 0.05 / 0.001) | deff 3 | deff 6 |
|---|---|---|---|---|
| T1 π 0.01, n 6204 | 0.151 | 0.506 / 0.587 | 0.728 / 0.816 | 0.886 / 0.963 |
| T1 π 0.05, n 6204 | 0.084 | 0.248 / 0.296 | 0.361 / 0.438 | 0.475 / 0.571 |
| T1 π 0.2, n 6204 | 0.053 | 0.142 / 0.166 | 0.194 / 0.238 | 0.250 / 0.311 |
| T2 π 0.2, n 150 | 0.053 | 0.581 / 0.705 | 0.896 / none | none / none |
| T2 π 0.2, n 400 | 0.053 | 0.373 / 0.465 | 0.611 / 0.739 | 0.810 / 0.943 |
| T2 π 0.2, n 1500 | 0.053 | 0.217 / 0.268 | 0.338 / 0.422 | 0.461 / 0.570 |

("none": not reachable at λ = 1.) The A6-era values (p* = 0.98, 25 nodes) differ by 3–5 %, which is the expected sensitivity to those choices. Dependence alone moves λ_min by a factor of about 1.4–1.8 (deff 3) and up to unreachable (deff 6, plausible for T1's six-fold label overlap, unmeasured [A]). Read as: **for this detector**, under these assumptions, the smallest detectable leak exceeds the harmful leak by a factor of roughly 3 to 17 in every computed cell.

### 3.3 The frozen requirement is not universally impossible [M/F]

The frozen rule is a count (§4A). Whether it is met depends entirely on what produces the fires. Under M-I it is met trivially (§3.4); under M-λ at λ = 0.36 with the task-wide trip-wire it is essentially never met (A6 §2.2); under a deterministic structural audit (§6) it would be met by construction. The earlier wording that the requirement "cannot be met" conflated the rule with one particular leak model and one particular detector.

### 3.4 The implementation's w = 2 canary passes without establishing sensitivity [N/M]

Expected realised BSS of the M-I candidate (κ at level 0.02; quadrature over (s_b, s_k) with the two forecast values per row conditioned on y; delta-method sd; iid):

| Cell | w = 2 | w = 1 | w = 0.5 | w = 0.25 | w = 0.1 |
|---|---|---|---|---|---|
| T1 π 0.01, n 6204 | 0.376 ± 0.030 | 0.183 ± 0.020 | 0.102 ± 0.014 | 0.062 ± 0.012 | 0.037 ± 0.011 |
| T1 π 0.05, n 6204 | 0.603 ± 0.013 | 0.332 ± 0.010 | 0.185 ± 0.008 | 0.106 ± 0.007 | 0.055 ± 0.006 |
| T1 π 0.2, n 6204 | 0.833 ± 0.004 | 0.550 ± 0.005 | 0.321 ± 0.005 | 0.180 ± 0.004 | 0.087 ± 0.004 |
| T2 π 0.2, n 150 | 0.833 ± 0.027 | 0.550 ± 0.034 | 0.321 ± 0.030 | 0.180 ± 0.027 | 0.087 ± 0.026 |
| T2 π 0.5, n 400 | 0.913 ± 0.006 | 0.658 ± 0.011 | 0.396 ± 0.013 | 0.223 ± 0.013 | 0.104 ± 0.014 |

Against ceiling medians of about 0.109 (T1) and 0.175 (T2) (A6 §2.2), the w = 2 candidate sits 7 to 180 standard deviations above the ceiling, so the per-rep fire probability is indistinguishable from 1 and every cell records 100/100. A Phase 1S run on `df43073` would therefore pass `LEAK_CANARY_WEAK` while having tested only a gross, miscalibrated, structurally implausible leak. This is a **smoke test of the counting path**, not evidence of leakage sensitivity.

### 3.5 λ = 0.36 must not be retuned [R]

Raising λ until the count rule passes selects the leak to fit the detector (tuning-to-pass, A6 §2.3 item 4). Lowering α′ or the ceiling has the same effect from the other side. The principled questions are *which object* the leak class certifies and *what a fire is* (§9), not what value of λ produces 95/100.

## 4. Exact 95-of-100 analysis

### 4.1 Four quantities that must not be confused

| | Quantity | Status |
|---|---|---|
| **A** | **Frozen observed-count criterion** [F]: `fire_k · 100 ≥ 95 · n` with n = `reps.leak` = 100, checked by `derive()` in **every one of the 48 cells** (stress and T3 included; the check precedes the stress skip), else STOP `LEAK_CANARY_WEAK` | frozen |
| **B** | Per-repetition detection probability p_i(C): the probability that one leak rep in cell i fires, given the ceiling C | depends on the leak model, the detector and the cell; not frozen |
| **C** | Cell-level pass probability P(K_i ≥ 95 \| C) | derived from B |
| **D** | All-cell pass probability P(every cell passes) | derived from C and the shared ceiling |

No probability target for B, C or D is frozen, and **none is introduced here**.

### 4.2 Exact binomial tail for independent repetitions [M]

For n = 100 independent repetitions with common detection probability p,

**P(K ≥ 95) = Σ_{k=95}^{100} C(100, k) p^k (1 − p)^{100−k}.**

Verified by exact rational arithmetic (`fractions.Fraction`) before recording:

| p | 0.90 | 0.95 | 0.97 | 0.98 | 0.99 |
|---|---|---|---|---|---|
| P(K ≥ 95) | 0.0576 | 0.6160 | 0.9192 | 0.9845 | 0.9995 |

| Required cell-pass probability | minimum p |
|---|---|
| 0.90 | 0.9682 |
| 0.95 | 0.9736 |
| 0.99 | 0.9819 |

A per-rep power equal to the count fraction itself (p = 0.95) passes a cell only 61.6 % of the time.

### 4.3 The shared ceiling: cells are not unconditionally independent [F/M]

The trip-wire ceiling C is **one** random quantity per task: the maximum of `max_bss` over 200 skill reps × 3 levels × all non-stress cells (about 7 200 draws in T1, 9 000 in T2). Every leak rep of every cell of that task is compared with the same C. Fire events are therefore dependent unconditionally, even if they are independent given C. The correct structure is

**P(all pass) = E_C[ ∏_i P(cell_i passes | C) ],**

and **not** ∏_i P(cell_i passes). A high draw of C lowers p_i in all cells at once, which the product of marginals would miss.

### 4.4 Conditional independence must be established, not assumed [F/A]

Distinct seed strings (`seed_hex(contract_sha | cell | kind | level | rep)`) give distinct PRNG states. That is necessary but not sufficient. Conditional independence given C holds only if, in the actual generator, (i) the leak reps share no random input with each other or with the skill reps that define C other than through C itself, and (ii) the PRNG streams seeded from distinct 64-bit integers are independent to the precision that matters. Inspection of `engine.compute_unit` and `rules.run_leak` shows each leak rep draws its own world and forecast from its own stream, and C is computed from separately seeded skill reps; the only shared quantities are deterministic (cell parameters, κ). Point (ii) is a property of the PRNG and is **assumed** [A]. Any future change that reuses worlds across reps, caches a world, or seeds from a shared counter would break the structure and must be re-examined.

### 4.5 Sensitivity to dependence between repetitions [N]

If reps were exchangeably correlated with pairwise correlation ρ (beta-binomial), the cell-pass probability would be:

| p | ρ = 0 | 0.02 | 0.05 | 0.10 | 0.30 |
|---|---|---|---|---|---|
| 0.95 | 0.616 | 0.629 | 0.659 | 0.700 | 0.802 |
| 0.98 | 0.985 | 0.912 | 0.885 | 0.884 | 0.918 |
| 0.99 | 0.999 | 0.970 | 0.948 | 0.943 | 0.959 |

Positive dependence **lowers** the pass probability where p is high and raises it where p is low. The shared ceiling acts in the same direction. Beyond these bounds, results for dependent reps are not identifiable without a specified dependence model.

### 4.6 Illustration of D (not a target) [N]

If 48 cells were conditionally independent with equal cell-pass probability q, P(all) = q⁴⁸: q = 0.95 gives 0.085; p = 0.98 gives 0.473; p = 0.99 gives 0.975. For P(all) ≥ 0.95 one would need q ≥ 0.99893, i.e. p ≥ 0.9886 in every cell. These are consequences of the frozen count, shown for understanding only.

## 5. Literature evidence

Access levels: **FT** full text reviewed this session · **AB** abstract reviewed · **MD** bibliographic metadata only (Crossref) · **NV** not independently verified.

| Reference | Access | Finding relevant to F9 | Evidence type |
|---|---|---|---|
| Neyman, J., Pearson, E. S. (1933). On the problem of the most efficient tests of statistical hypotheses. *Phil. Trans. R. Soc. A* 231:289–337. doi:10.1098/rsta.1933.0009 | **FT** (public PDF copy; publisher page returned 403) | Best critical region = largest likelihood ratio for simple vs simple; UMP tests do not generally exist for composite hypotheses | **Direct** for §3.1; it does not address the F9 power calculations |
| Kaufman, S., Rosset, S., Perlich, C., Stitelman, O. (2012). Leakage in data mining: formulation, detection, and avoidance. *ACM TKDD* 6(4):1–21. doi:10.1145/2382577.2382579 (conference version KDD 2011, doi:10.1145/2020408.2020496) | **AB** (Crossref abstract; full text 403) | Leakage defined as "the introduction of information about the data mining target that should not be legitimately available to mine from"; avoidance via data management and learn-predict separation; detection methods when collection is uncontrolled | **Direct** support for legitimacy-based (structural) detection; detection details **NV** |
| Kapoor, S., Narayanan, A. (2023). Leakage and the reproducibility crisis in machine-learning-based science. *Patterns* 4(9):100804. doi:10.1016/j.patter.2023.100804 (PMC10499856) | **FT** | Taxonomy L1–L3; [L2] "model uses features that are not legitimate" (e.g. a proxy for the outcome); [L3.1] temporal leakage; model info sheets require arguing why each feature is legitimate and available at prediction time; detecting leakage "requires domain knowledge" and access to code, data and environment; "subtle cases of leakage might slip under the radar" | **Direct**: performance alone does not identify leakage; availability audits do |
| Lipsitch, M., Tchetgen Tchetgen, E., Cohen, T. (2010). Negative controls: a tool for detecting confounding and bias in observational studies. *Epidemiology* 21(3):383–388. doi:10.1097/EDE.0b013e3181d61eeb (PMC3053408) | **FT** | A negative control must be "U-comparable" (same set of common causes) and not causally linked; an association signals bias but "the magnitude of bias … cannot generally be inferred"; "a sensitive, but blunt, tool"; false positives from confounders specific to the control, false negatives from partial coverage; requires subject-matter knowledge | **Methodological analogy** (causal epidemiology → synthetic forecasting); conditions transfer to §7 |
| Roberts, D. R. et al. (2017). *Ecography* 40:913–929. doi:10.1111/ecog.02881 | MD | Dependence across folds inflates validation skill; blocked validation | Analogy (dependence) |
| Bergmeir, C., Benítez, J. M. (2012). *Information Sciences* 191:192–213. doi:10.1016/j.ins.2011.12.028 | MD | Cross-validation choices for time series | Analogy |
| Politis, D. N., Romano, J. P. (1994). *JASA* 89:1303–1313. doi:10.1080/01621459.1994.10476870; Kiefer, N. M., Vogelsang, T. J. (2005). *Econometric Theory* 21:1130–1164. doi:10.1017/S0266466605050565; Lazarus, E. et al. (2018). *JBES* 36:541–559. doi:10.1080/07350015.2018.1506926; Diebold, F. X., Mariano, R. S. (1995). *JBES* 13:253–263. doi:10.1080/07350015.1995.10524599 | MD | Variance estimation and testing under serial dependence | Analogy; basis for treating deff as unmeasured |
| White, H. (2000). *Econometrica* 68:1097–1126. doi:10.1111/1468-0262.00152; Hansen, P. R. (2005). *JBES* 23:365–380. doi:10.1198/073500105000000063; Romano, J. P., Wolf, M. (2005). *Econometrica* 73:1237–1282. doi:10.1111/j.1468-0262.2005.00615.x | MD | Data snooping and selection across many models inflate apparent skill | Neutral: "too good" is a selection signal, not proof of leakage |
| Bailey, D. H. et al. (2014). *Notices AMS* 61:458–471. doi:10.1090/noti1105; Bailey et al. (2016). *J. Comp. Finance*. doi:10.21314/JCF.2016.322; Bailey, D. H., López de Prado, M. (2014). *J. Portfolio Mgmt* 40(5):94–107. doi:10.3905/jpm.2014.40.5.094 | MD | Backtest overfitting; deflate by the number of trials | Neutral |

**Limits [L/A].** None of these works addresses the power of a skill-magnitude leakage canary, and none validates the numbers in §3; those rest on the generator of §2 alone. Lipsitch's conditions come from causal inference with known exposure structures; in financial series "common causes" are latent factors and persistence that are rarely known. Kapoor's framework assumes a static dataset; here availability is a per-bar timestamp inequality. No systematic search was run; the list is the set verified so far.

## 6. Structural positive control: PIT leakage-injection acceptance fixture (conceptual, non-executable)

**Purpose.** Establish that an independent point-in-time audit detects deliberately injected look-ahead violations of the frozen availability rules. **It does not establish detection of leakage in general** (§6.9).

### 6.1 Time definitions (frozen `timeline.py`, contract `pit`) [F]

| Symbol | Definition |
|---|---|
| end(b) | canonical bar end = open + tf; archive and REST closes map to the same end |
| t_avail(b) | end(b) + δ_avail(tf): 120 s for 15m / 1h / 4h, 300 s for 1d |
| t_issue | decision-bar end + δ_avail(tf) + δ_compute (60 s) |
| t_act | t_issue + δ_act (60 s) |
| admissible bar | t_avail(b) ≤ t_issue, and, when an arrival time is recorded, arrived ≤ t_issue; any bar ending after the W3 freeze is a hard failure |
| label window | T1: path bars with open ≥ t_act through the horizon; T2: closes with end > t_act; T3: 7-day window; label available only after `label_end` |
| fitted quantities | use only bars available before their month or fold start; universe membership uses bars at or before the month start |

### 6.2 Feature lineage

For each feature value used at a decision time: the list of (bar end, tf, source, arrival time if recorded) it was computed from, any fitted quantity it depends on with that quantity's fold start, and the derived scalars `max_input_end`, `max_input_avail`, `max_fitted_input_end`. **The lineage must be reconstructed from the raw source bars by the auditor, never read from the feature pipeline (§6.6).**

### 6.3 Look-ahead injection classes

| Class | Injection | Violated rule |
|---|---|---|
| P1 decision-bar inclusion | a feature uses the decision bar itself (t_avail = end + δ_avail > t_issue by δ_compute) | admissibility |
| P2 label-window inclusion | a feature uses the first bar of its own label window | admissibility, label leakage |
| P3 late-arrival back-fill | a bar whose recorded arrival exceeds t_issue is used | arrival rule |
| P4 fitted leakage | a fitted quantity (scaler, bucket boundary, baseline rate) uses bars after its fold start | fitted-quantity rule |
| P5 universe leakage | month membership uses bars after the month start | universe rule |
| P6 boundary | injected bar with t_avail = t_issue exactly, and t_issue + 1 ms | inequality direction (A2 boundary tests) |

Each injection acts on the **inputs** (which bars enter the computation), never on the lineage record, and the injected feature is otherwise an ordinary feature. The injected class, feature, decision time and offset are drawn from a **sealed seed** fixed after the audit logic is frozen.

### 6.4 Independent detection procedure

1. The auditor receives the raw bar archive, the decision times, and the feature values with their declared inputs.
2. It recomputes end(b), t_avail(b), t_issue and t_act with the frozen `timeline.py` functions from the raw bars, and rebuilds each feature's lineage from the declared computation graph and the raw bars.
3. It reports a **violation** for a feature at a decision time iff `max_input_avail > t_issue`, or an arrival time exceeds t_issue, or `max_fitted_input_end ≥ fold start`, or a universe input ends after the month start, or any bar ends after the freeze.
4. It never uses forecasts, outcomes or skill.

### 6.5 Outcomes

| Outcome | Definition | Objective (to be fixed before any run; none fixed here) |
|---|---|---|
| detection | an injected violation is reported at the injected (feature, decision time) | high, to be pre-declared |
| miss | an injected violation is not reported | reported, with class |
| false alarm | a violation reported on a blind (no-injection) rep or on a non-injected feature | low, to be pre-declared |
| misattribution | reported at the wrong feature or time | counted as a miss |

Blind reps (no injection, unknown to the auditor) are part of the fixture: without them the detection rate is uninformative.

### 6.6 Self-validation risk and its mitigation

The risk: if the injector writes the lineage that the auditor then reads, the audit confirms the injector's bookkeeping, not the pipeline's point-in-time behaviour; detection becomes guaranteed by the same mechanism that creates the violation. Required mitigations:
- the auditor reconstructs lineage from **raw source bars** and the computation graph, with no read access to the injector's records;
- audit logic and injector live in separately hashed modules; the audit module's hash is recorded **before** the sealed injection seed is drawn;
- injection parameters are revealed to the auditor only after it has reported;
- the fixture reports misses and false alarms separately, never a single pass rate;
- any shared helper between injector and auditor is limited to the frozen `timeline.py` functions, which are themselves under the frozen set hash.

### 6.7 Boundary cases

t_avail = t_issue exactly (admissible), t_issue + 1 ms (not admissible); archive close end − 1 µs vs REST close end − 1 ms mapping to the same end; a 1d bar's larger δ_avail; a bar ending exactly at the freeze; a fold start coinciding with a bar end; an arrival time recorded as `None`.

### 6.8 Missed-detection scenarios (structurally undetectable by this fixture)

A proxy feature whose inputs are all legitimately available but which encodes the outcome through an external channel; clock or timezone errors common to raw bars and auditor; a label definition that itself uses post-decision information consistently (a label error, not a feature error); leakage through the choice of hypotheses or parameters after seeing outcomes (snooping, §5); leakage inside a third-party feature whose computation graph is not declared.

### 6.9 Provenance and reproducibility

Sealed manifest with: raw-bar archive hash; audit module hash; injector module hash; sealed seed; the list of injections (revealed after audit); per-rep outcomes; the frozen set hash `fdf33664…`. Deterministic replay from the manifest must reproduce every outcome. Detection of injected timestamp violations shows sensitivity to **those classes only**; it is not proof of detection of all leakage, and the fixture must be described that way wherever it is reported.

## 7. Negative controls

### 7.1 Frozen mechanisms [F]

| Layer | Mechanism | What it is a control for |
|---|---|---|
| L1 `null` class | candidate = strongest baseline + independent noise (`null_noise_sd` 0.1) | the B1 test's false-positive rate under no incremental information, with the cell's persistence and factor structure in the baseline and outcomes |
| L2 `l2_null` | logistic surrogate fitted on the baseline index plus noise features drawn from `factor_series` with the cell's φ and ρ (6 and 2 noise features) | model-fit inflation: the null FPR point must be ≤ 7.5 % |

### 7.2 Expected behaviour and acceptance [F]

L1: fp ≤ 5/100 and Wilson-95 UB ≤ 0.07 in every non-stress cell at the ladder step (stress cells reported). L2: FPR point ≤ 75 ‰. These are the frozen objectives; **no replacement threshold is proposed**.

### 7.3 Assumptions for comparable dependence (U-comparability)

A negative control is informative only if it shares the dependence structure of the real candidate while carrying no information about the label: same autocorrelation (φ), same cross-sectional factor loading (ρ), same label overlap, same sample size and evaluation window. The frozen generators satisfy this by construction because the noise features are drawn from the same `factor_series` family as the signals. On real data (Phase 2) the comparable structure must be argued, not assumed.

### 7.4 Confounding by persistence and shared factors

If the control retains any genuine information link to the label (through persistence of the label process, a shared market factor, or overlapping label windows), its "null" distribution is not null: the control's rejection rate rises and would be misread as pipeline inflation, or, used as a leak canary, as a leak. The earlier finding that a time-shift canary is confounded with legitimate persistence (A6 §2.4) is an instance.

### 7.5 Why naïve shuffling and time shifting may invalidate the null

- **Row-wise shuffling** of labels or features destroys autocorrelation and overlap; the effective sample size changes, the test's size under the null is no longer the one that applies to the real candidate (U-comparability fails in the other direction).
- **Time shifting** by less than the dependence range (AR(0.95) at the 4h step has a memory of roughly 20 steps; T1 labels overlap 6 steps) leaves genuine information in the shifted pairing. Shifting across symbols that share a factor does the same.
- **Shuffling within blocks** preserves some structure but still breaks the between-block dependence that the block bootstrap is meant to capture.

### 7.6 What negative controls can and cannot establish

They can show that the pipeline produces no spurious skill under a specified no-information construction, at a stated size. They cannot identify the form of a bias when they fail, cannot quantify it (Lipsitch et al.), cannot detect a leak that enters through a legitimately structured feature, and cannot substitute for the structural audit of §6.

## 8. Frozen compatibility and governance

**Syntactic** compatibility = the frozen code and records accept the inputs without change. **Scientific** compatibility = the frozen meaning of the gate is preserved.

| Frozen element | Structural positive control (§6) | Negative controls (§7) | Amendment needed? |
|---|---|---|---|
| L1 (forecasts, outcomes; no features, no timestamps) | not representable | already present (null class) | positive control cannot enter L1 without redefining the layer |
| L2 (surrogate on simulated features, 4 cells, no timestamps) | not representable as frozen (no timestamps, no lineage) | already present | adding timestamps or lineage to L2 is a layer change ("any change to cells, reps, bootstrap count, layers or grid is a protocol amendment") |
| 48-cell grid | unaffected if the fixture lives outside the grid; if the leak class moves to L2, `derive()` still requires a leak block with n = 100 in every one of the 48 cells, while L2 covers 4 | unaffected | yes, if the leak class changes layer or cell coverage |
| Leak truth class ("the label enters one feature with weight w") | consistent in wording with a feature-level violation; inconsistent with the current L1 forecast-level proxies | n/a | yes: the class must state which mechanism and which layer it certifies |
| Contract A7 (label time-shift, shuffled features, feature delay, trip-wire ceiling from v1.1) | matches "feature delay" and "label time-shift" intent | matches "shuffled features" only if U-comparable (§7.3) | no change to A7 wording needed; its Phase 1S *validation* is not currently defined |
| Derivation map (`trip_wire_ceiling`, `leak: {fire_k, n}`) | syntactically unaffected | unaffected | no, in form; the map does not define a fire |
| `derive()` and `LEAK_CANARY_WEAK` | syntactically unaffected (counts only); **scientifically** the STOP's meaning changes from "trip-wire insensitive" to "audit missed injections" | unaffected | the protocol or interpretation record must define "fire" (an AM-4-type clause); otherwise the STOP has no fixed meaning |
| Phase 2 PIT integrity (contract `pit`, A2 "PIT rules + boundary tests", `timeline.py`) | **natural home**: the fixture is an acceptance test of the frozen PIT implementation | n/a | no amendment if scoped as an acceptance test (A5-style); the fixture's objectives must still be pre-declared and owner-approved |
| Phase 4 / E3 shadow | out of scope; separate protocol and approval | out of scope | no |

**What would require a future protocol amendment (scope only, not drafted):** (i) a definition of a "fire" for the Phase 1S leak class; (ii) a statement of which mechanism (M-F, M-I, M-λ or a structural injection) the class certifies and at which layer; (iii) if the class moves to L2 or outside the grid, the corresponding change to layers, cells or `reps.leak`; (iv) if the trip-wire becomes descriptive, the interpretation of `trip_wire_ceiling` as reported CDP. The 48 cells, `derive()`, the derivation map and the contract need no change for a fixture scoped under Phase 2 acceptance testing.

## 9. Open owner decisions (not resolved here)

To avoid collision with the README's D1–D13, these are labelled **F9-D1 … F9-D4** (the owner's D1–D4 of the A8 directive).

| # | Decision | Options on record | Dependencies |
|---|---|---|---|
| **F9-D1** | What Phase 1S's leak truth class should certify | (a) trip-wire sensitivity to a leak beyond the legitimate family (λ > τ_u²); (b) the counting path only (smoke test, declared as such); (c) nothing at Phase 1S, with structural canaries certified under Phase 2 acceptance; (d) a structural injection inside Phase 1S (requires a layer amendment) | §2.6, §3.4, §8 |
| **F9-D2** | Whether the PIT injection fixture belongs in Phase 2 acceptance testing or requires a Phase 1S scope amendment | Phase 2 acceptance (no grid change) vs Phase 1S amendment (layer change) | §6, §8 |
| **F9-D3** | Whether `LEAK_CANARY_WEAK` can retain its current meaning | retain (then F9-D1 must be (a) or (b)); redefine by amendment (then F9-D1 (c) or (d)) | §8 |
| **F9-D4** | Whether bounded dependence (deff) and T3 / stress / break-cell analysis is scientifically necessary before an amendment decision | necessary if F9-D1 is (a) (the numbers in §3.2 are iid and T1/T2-only); not necessary for (b) or (c) | §3.2 |

**Recommended sequence [R], not an approval:** F9-D1 first, because it determines whether any magnitude number matters; then F9-D3 (it follows from F9-D1); then F9-D2; F9-D4 only if F9-D1 = (a). Under (c), the smallest next research step is a documentation-only specification of the §6 fixture with pre-declared detection and false-alarm objectives and the §6.6 independence design, followed by an A5-style acceptance-test entry; no computation is needed for that step.

## 10. Governance status

| Item | Status |
|---|---|
| F9 | **HOLD** |
| F3 / R+ | **PROPOSED, NOT APPROVED** |
| E2 | **HOLD** |
| Gate A | **OPEN** |
| Gate B | **NOT AUTHORISED** |
| MI-C v1.0 | **FROZEN AND UNCHANGED** (`fdf33664…`) |
| Phase 1S protocol v1.0 | **FROZEN AND UNCHANGED** (`412cb606…`) |
| MI-C v2.0 / protocol revision | **not automatic**; no version increment is implied by this appendix |

## 11. Method and provenance of the computations

- All numbers labelled [N] come from a deterministic pure-Python script in the session scratchpad (not committed; it imports nothing from the repository): closed-form probit moments integrated by 41-node trapezoid quadrature on ±6 sd per latent dimension; delta-method variance of the Brier ratio; κ(π, level), λ_harm and λ_min by bisection; exact binomial tails by `fractions.Fraction`; beta-binomial tails via log-gamma. The A6 script `draft/f9_leak_detection_analytic.py` remains the recorded reference for the ceiling distribution and the all-fire probabilities; this appendix re-derives the row moments and the thresholds independently of it.
- Runtime: seconds, under `nice 19`, outside `research-mi.slice`; no reservation, no ledger write, no seeds, no sampling.
- Anyone can reproduce the [N] values from the formulas in §2–§4 with any quadrature of comparable resolution; agreement to about 1 % is expected, exact agreement is not (the values are approximate by construction).
