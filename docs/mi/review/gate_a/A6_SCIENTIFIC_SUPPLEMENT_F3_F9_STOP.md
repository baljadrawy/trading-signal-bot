# A6 — Scientific supplement: F3, F9 and derive-STOP governance

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE** — Gate A review material. Nothing here is an owner approval or a frozen artefact, and nothing here may be loaded by any run.

**Revision r2 (2026-10-09).**
- Corrects the R+ vs K STOP-equivalence claims (§1.3).
- Updates the F9 status (§2.4).
- Removes the automatic "MI-C v2.0" rule (§3).
- The T1 Hybrid statistical review is in **A7** (appendix).

**Scope.** Prepared 2026-10-09 on `docs/mi-phase1s-gate-a-review-20261009` (base `3add796`). It supplements A1–A5 and corrects A3 where noted. Nothing was frozen or implemented; no run, campaign, budget reservation or ledger write took place.

**Labels:** **[F]** verified fact · **[M]** exact mathematics · **[N]** numerical approximation (deterministic) · **[A]** assumption · **[R]** recommendation.

**Baseline re-verified [F]:**
- branch clean at `3add796` (remote identical);
- all 7 frozen files match `FROZEN_SHA256SUMS.json` (contract set `fdf33664…`, protocol `412cb606…`);
- budget ledger, checkpoint and anchor unmodified since 2026-10-08T23:34Z;
- trial ledger directory holds only `MI_LEDGER_GENESIS.json`.

---

## 1. F3 — T1 break cells: K, R or R+

### 1.1 What each variant tests

| Variant | Hypothesis encoded in T1's minimum-evidence (n\*) requirement |
|---|---|
| **K** | "With enough positives, the frozen rule certifies locked T1 skill even when the HLE base rate doubles relative to dev." Break robustness is a certification **requirement** |
| **R** | "The frozen rule certifies T1 skill in the no-break world." Break cells are reported, and a real break is handled by an applicability check |
| **R+** | As R for n\* only. **Every other gate on the 6 break cells is retained**, enforced by the engine before `derive()` is called |

### 1.2 Which gates remain, move or disappear (6 cells `T1|pi∈{.01,.05,.2}|phi=0|rho∈{0,.5}|brk=1`)

| Gate | K (frozen `derive()`) | R | R+ |
|---|---|---|---|
| Null control → ladder selection | in `derive()` | removed | engine STOP if any break cell fails at the step `derive()` selects (slightly **stricter** than K, see §1.3) |
| B3 size (`b3_reject_k ≤ 70/1000`) | in `derive()` | **removed** | engine STOP, same rule and same data |
| B3 power (miscal slope 0.7 / 1.4 ≥ 80 %) | in `derive()` | removed | engine STOP, same rule |
| Leak canary | all cells | all cells | all cells |
| Power / n\* | in `derive()`: break cells included | excluded | **excluded (the only change)** |
| Exclusions list | stress cells failing null | unchanged (break cells pass null) | unchanged |

### 1.3 Quantified effects

| Quantity | K | R | R+ |
|---|---|---|---|
| Break-cell power at every n | ≈ 0 [M/A]: O/E ≈ 2, \|log 2\| = 0.69 vs a 98.33 % CI half-width ≈ 2.4·√(deff/positives) ≤ 0.6 for positives ≥ 62, if deff ≤ 4 [A] | not required | not required |
| T1 n\* / status | **INSUFFICIENT_ALWAYS with probability ≈ 1** [M]: every positives level contains break cells | from the 12 no-break cells (unknown until the full run) | same as R |
| Null-control / ladder pass probability | product over 18 cells; break-cell FPR ≈ 0 [A: B3 rejects every dev-calibrated forecast] | product over 12 | **not equal to K**: if a break cell fails at the step selected by the 12 no-break cells (event E), K advances the ladder while R+ STOPs, so P_STOP(R+) = P_STOP(K) + P(E). P(E) is small for π ≥ 0.05 but **not negligible at π = 0.01 under heavy dependence** (A7 §D) |
| B3-size STOP-free probability [M, exact binomial, independent cells] | true size 6 %: **0.208**; 6.5 %: **0.0076** | **0.351**; **0.0387** (an unjustified relaxation) | **identical to K** |
| FPR protection | baseline | unchanged (break-cell FPR ≈ 0) | unchanged |

**Dependence [M].** Cells use disjoint seed streams, so gate outcomes are independent across cells and the products are exact. Within a cell, null `fp`, `b3_reject` and skill share the generator but feed different gates. R+ keeps the B3-size and B3-power gate outcomes identical to K's (same gates, same data). It is **not** STOP-equivalent: it is weakly stricter through event E (A7 §D). The earlier wording "STOP probability unchanged" is withdrawn.

**Correction to A3 [F/M].** A3 called R's B3-size effect "slight" with "no information lost". R in fact raises the B3-size STOP-free probability from 0.208 to 0.351 at a true size of 6 %. Break-cell B3 size is measured on the HLE-calibrated twin, which has the same distribution as the break = 0 cell. **R is rejected.**

### 1.4 Post-hoc selection and frozen-contract compatibility

- [F] The decision is made before any calibration output. Only the bounded diagnostics in A4 §6 have been seen.
- [M] R+ changes exactly one quantity: whether break cells enter n\*. The justification is construct validity: n\* is defined as the evidence needed for power, and under a locked-model break power **falls** as evidence grows, so the requirement is a validity condition, not an evidence condition. This argument does not depend on the PASS outcome.
- [F] The derivation map and `derive.py` are unchanged. R+ needs a protocol amendment (the stress flags, plus the engine-enforced retained gates and the break-ratio clause) and an implementation change (pre-derive gate check). The contract JSON is untouched.

### 1.5 Phase 4 break-ratio estimator (proposed clause, R+ only)

| Element | Specification |
|---|---|
| Inputs | T1 D24 labels (frozen label definition), inference scope S-MAJ, only rows passing the frozen PIT / censoring rules (A2, A6) |
| Rates | r_dev = positives / eligible rows over the development segment (2018-01-01 … 2024-12-31, label_end ≤ segment end); r_hle = the same over the HLE (2025-01-01 … 2026-05-31, label_end < 2026-06-01) |
| Statistic | log R = log(r_hle / r_dev) |
| Confidence limits | 95 % CI on log R by the delta method with cluster-robust variances, clusters = contiguous blocks of the T1 CDP `block_mean_days` (final step) |
| Timing | Computed once, in Phase 4, after the model-lock hash and the single HLE look; downgrade-only; never used for model selection |
| Decision (fail-closed) | **Downgrade T1 unless the entire CI lies inside (log(1/1.5), log 1.5).** A break in either direction counts |
| Missing data / failure | Coverage below the frozen DS / A6 manifest requirements, zero positives in either segment, or a non-finite or unavailable estimate → **downgrade** |
| Record | R, CI, cluster count, rows, positives and the code hash, recorded in the Phase 4 evidence |

### 1.6 Recommendation

**[R] R+, unless you define robustness to a ×2 locked-model break as a T1 certification requirement, in which case K.** R is rejected. R+ is valid **only together with** the retained engine gates and the §1.5 estimator. Without them it collapses to R.

---

## 2. F9 — leakage-canary strength

### 2.1 Mechanism [F/M]

- **Frozen requirement:** protocol `truth_classes.leak` ("the label enters one feature with weight w"), meta-acceptance `leak_fire_min_pct = 95`, and `derive()` STOPs with `LEAK_CANARY_WEAK` if any cell has fire_k < 95 / 100.
- **Not frozen:** the definition of a "fire" is not in `derive.py`. It is the engine's A7 implementation (the trip-wire: realised BSS > task ceiling = maximum of `max_bss` over levels and non-stress cells).
- **Proposed leak (IR-6):** ℓ ~ N(0, λ) is part of the label's own outcome shock; the leaky forecast Φ((μ + s_b + s_k + ℓ)/√(1 + τ_u² − λ)) is exactly calibrated.

### 2.2 Deterministic detection analysis

**Method [N].** Script `draft/f9_leak_detection_analytic.py`:
- the mean and standard deviation of realised BSS are obtained by the delta method from exact per-row Brier moments, integrated by 25-point-per-dimension trapezoid quadrature;
- rows are **iid**, the most favourable case; a design effect (deff) of 3 is shown as a stress case;
- the ceiling distribution is the exact maximum of independent normals (200 reps × 3 levels × cells);
- P(all cells fire ≥ 95) = E_ceiling[∏ cells P(Bin(100, p_cell) ≥ 95)], so the dependence through the **common** ceiling is handled exactly.
- **No sampling and no seeds.**

**Results** (T1: the 12 no-break non-stress cells; T2: the 15 non-stress cells):

| λ | T1 ceiling median (iid) | P(T1 all fire) iid / deff 3 | T2 ceiling median (iid) | P(T2 all fire) iid / deff 3 | Weakest cell (iid): leak BSS ± sd |
|---|---|---|---|---|---|
| **0.36** (proposed) | 0.109 | **0.000 / 0.000** | 0.175 | **0.000 / 0.000** | T1 π 0.01: 0.101 ± 0.029; T2 n150 π 0.2: 0.168 ± 0.069 |
| 0.6 | — | 0.941 / 0.000 | — | 0.108 / 0.000 | 0.192 ± 0.041; 0.282 ± 0.081 |
| 1.0 (≈ full label shock) | — | 1.000 / 1.000 | — | 1.000 / 0.755 | 0.481 ± 0.053; 0.530 ± 0.085 |

**Caveats:**
- [A] normal approximation of realised BSS (it is skewed at small n and π);
- [A] iid rows (real T1 overlap and factors give deff > 1, which makes detection **harder**);
- [A] T3, the stress cells and the break cells are not computed. All three can only add cells that must fire, or raise the ceiling.

### 2.3 Conclusions

1. **[N] With a meaningful leak (as strong as the strongest legitimate signal, λ = 0.36), the frozen 95 % requirement with the task-wide trip-wire is essentially unattainable.** `LEAK_CANARY_WEAK` is then a near-certain STOP of the whole derivation.
2. **[N] Only near-total leaks (λ ≈ 1) pass**, and even then not robustly in T2 under dependence. Choosing λ ≈ 1 would turn the gate into a test of trivial leaks.
3. **[M] The cause is the ceiling's multiplicity.** It is a maximum over about 7 200 (T1) or 9 000 (T2) noisy realised skill scores, so it sits about 3.5–4.5 sd above the skill levels in the noisiest cells. This is a property of the canary definition, not of λ.
4. **[R] Do not tune λ.** Raising it until the gate passes is tuning-to-pass.

### 2.4 Recommendation: HOLD λ, plus a principled redesign by protocol amendment

| Element | Proposal |
|---|---|
| Leak strength | **Pre-register λ = 0.36** (substantive, independent of results) |
| Canary for the Phase 1S leak gate | Replace the task-wide trip-wire-only "fire" with a pre-registered A7 battery evaluated per cell: (a) a **per-cell** trip-wire (ceiling = the cell's own upper skill quantile at the top level, Bonferroni-adjusted over its reps), and (b) a **label time-shift** canary. The task-wide trip-wire fire rate is reported, not gated |
| Contract impact | `derive.py` and the derivation map are unchanged (they read only fire_k / n). The **protocol** must define what a fire is → amendment clause AM-4. Phase 2 must use the same battery for consistency, so the A7 battery definition becomes part of the v1.0.1 interpretation record and the Phase 2 specification |
| Status (r2) | Evaluated afterwards, documentation-only. A per-cell trip-wire with a pre-registered α′ = 0.001 gives **P(all 27 T1/T2 cells pass) = 0.000** at λ = 0.36 (iid and deff 3). The label time-shift canary is **confounded with legitimate persistence** (at φ = 0.95 legitimate signals keep more shifted skill than the leak). **The AM-4 battery is not scientifically justified, so F9 is HOLD** |
| If you reject the redesign | Keep λ = 0.36 with the trip-wire only, and accept that Phase 1S will very likely STOP with `LEAK_CANARY_WEAK` (handled by §3) |

---

## 3. Derive-STOP governance policy (default: fail-closed)

| Condition | Class | Retry under the frozen rules? | Evidence to preserve | Requires | Prohibited |
|---|---|---|---|---|---|
| HASH_MISMATCH, UNPARSEABLE, WRONG_RECORD, PROTOCOL_MISMATCH, INCOMPLETE_STATUS / GRID / REPS, UNRESOLVED_FIELD / LADDER, FINAL_STEP_MISMATCH | Integrity / infrastructure | `derive()` is pure: re-running it on the **same sealed output** is not a trial. Recomputing shards is allowed only as a deterministic resume (same plan, code tree and seeds) | Output, shards, journal, plan, CPU reports, STOP code and detail, sealed | Owner authorisation for any recompute; a code defect needs a new tree hash and a full re-run disclosed as such | New seeds; editing output; mixing old and new shards |
| REPRO_MISMATCH, sandbox violation, store / journal error, guard KILL, runtime limit | Infrastructure | No automatic retry. Charged CPU stays charged (no free retry) | The above plus guard ledger copies and the violation log | Owner authorisation; budget from the contingency | Resetting ledgers; deleting shards to "clean" |
| BUDGET_NOT_ENFORCED, BUDGET_BREACH | Governance / infrastructure | NOT_ENFORCED: `derive()` re-run after genuine INT-2 evidence. BREACH: none | Evidence file and ledger copies | Owner | Fabricated or edited evidence |
| **LEAK_CANARY_WEAK** | Scientific: the canary is insensitive | **No.** v1.1 cannot be derived from this output | Full sealed output; the cell-level fire rates | A new protocol version (e.g. AM-4) with the failure disclosed as prior exposure, plus a **full new Phase 1S** | Raising λ, excluding cells, new seeds, a lower threshold |
| **B3_SIZE_FAIL** | Scientific: B3 oversize | **No** | Same | A new protocol or contract version (B3 CI construction) + a new Phase 1S | Dropping the cell, changing the CI level post hoc |
| **B3_POWER_FAIL** | Inconclusive: B3 cannot detect miscalibration at this n | **No** | Same | A new version (e.g. a different minimum evidence for B3) + a new Phase 1S | Same |
| L2_MODEL_FIT_INFLATION, B2_REFERENCE_NOT_CONSERVATIVE | Scientific | **No** | Same | A new version + a new Phase 1S | Same |
| Ladder FAIL (not a `derive()` STOP; leads to DESCRIPTIVE_ONLY) | Valid scientific outcome | Not applicable | Ladder history | IR-9 checkpoint: your decision before spending CPU on step-2 final classes | A step beyond k2 |

**Governance gap [F].** The contract's versioning allows v1.2+ only *after* v1.1. A scientific STOP means v1.1 never exists.

**[R] Pre-register now** that a scientific STOP closes this Phase 1S as **FAILED_CALIBRATION**, and that the failed run is preserved and recorded as prior exposure. **Any continuation, and which version it takes (protocol v1.0.x or a new contract), is a separate owner governance decision. It is not automatic.** The MI trial ledger stays untouched, since synthetic runs are not trials.

STOP classes are distinguished as follows:
- **genuine scientific failure:** B3_SIZE_FAIL, L2_MODEL_FIT_INFLATION, B2_REFERENCE_NOT_CONSERVATIVE;
- **inadequate or underpowered validation procedure:** LEAK_CANARY_WEAK, B3_POWER_FAIL;
- **insufficient evidence** (valid outcomes): INSUFFICIENT / DESCRIPTIVE_ONLY;
- **infrastructure or integrity failure.**

---

## 4. Acceptance-test additions (extend A5)

| AT | Purpose | Criterion |
|---|---|---|
| AT-16 | R+ parity | For a fabricated output, the engine STOPs exactly when a break cell fails B3 size, B3 power or null control at the selected step; the n\* input excludes break cells only; the stress-flag count is 12 / 17 |
| AT-17 | Break-ratio estimator | Unit tests on synthetic rate series: CI contains the true log R at the nominal rate (deterministic fixtures); a missing or zero-positive segment → downgrade |
| AT-18 | F9 analytic reproduction | `draft/f9_leak_detection_analytic.py` reproduces the §2.2 table to 3 decimals |
| AT-19 | STOP policy | Every `derive()` STOP code maps to the §3 class; no code path retries automatically, changes seeds, or deletes shards after a STOP |
| AT-1 … AT-15 | As revised in the previous review | (AT-1 adds T1 φ = 0.95 and T3 cells; AT-2 cluster-robust SE; AT-5 adds ρ = 0.94; fixed seed namespace `gate-c\|<AT>\|rep`) |

## 5. Remaining owner decisions

1. **F3:** R+ (with retained engine gates and the §1.5 estimator) or K. Is break robustness a T1 certification requirement?
2. **F9:** approve λ = 0.36 as pre-registered, **and** choose between the AM-4 canary redesign (then authorise the bounded battery-power analysis) and the trip-wire only with a likely `LEAK_CANARY_WEAK` STOP.
3. **Derive-STOP:** adopt the §3 policy and the FAILED_CALIBRATION closure rule (any continuation is a separate governance decision).
4. Earlier open items: τ², F2, F6 (Wald), F7 (real dev span recommended), F8 (AT-5 change), F10 pseudo-B4, F11, F14, the provenance manifest and registration wrapper, committing the audit and plan reports.

## 6. Blockers to Gate A closure

1. F9 is unresolved; under the current design the derivation is expected to STOP.
2. The FAILED_CALIBRATION closure rule is not adopted.
3. The F3 decision is open.
4. The provenance manifest design and the audit / plan reports are not in Git.
