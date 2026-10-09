# A2 — Phase 1S scientific interpretation record (draft) — NOT FROZEN

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE** — Gate A review material. Nothing here is an owner approval or a frozen artefact, and nothing here may be loaded by any run.

**Purpose.** This record fixes how frozen text that leaves a choice open is implemented. It never overrides frozen text; where frozen text must change, that belongs in the amendment (A1).

**Binding.** At freeze, a machine-readable copy (`mi_phase1s_interpretation_v1_0_1.json`) is:
- covered by the v1.0.1 sums file (A4);
- loaded by the engine and copied into the output meta;
- bound into the plan hash.

**Status vocabulary:**

| Status | Meaning |
|---|---|
| **PROPOSED** (not approved) | A proposed direction, drafted because the Gate A authorisation asked for it (F1, F2, F6, F7, F8, F9, F10, F11, F14). It is still not binding until you approve the freeze |
| **OPEN** | An explicit sub-decision for you |
| **COND** | A pre-declared decision rule that is resolved mechanically by a Gate C test, never by judgement after seeing results |

**Not in this record:** F3 (open, A3); F4, F5, F12, F13, F16, F17 (correctness fixes with no semantics).

---

## IR-1 — Implementation of the AM-1 equal-skill null (F1) — PROPOSED; parameter value OPEN

| Task | Construction |
|---|---|
| **T1 / T2** | Truth index = μ_y + s₀ + s₁ + s₂, with three mutually independent latent signals of equal variance τ². T1 signals carry the cell's AR(φ) at the 4h step, factor ρ and 6× label overlap; T2 signals carry the day factor ρ. The baseline knows s₀, c1 knows s₁, c2 knows s₂. Each forecast is the exact calibrated probit Φ((μ_f + s_i)/√(1 + 2τ²)) |
| **Base rate** | μ_y = Φ⁻¹(π)·√(1 + 3τ²); with a break (dev-calibrated forecasts), μ_f follows A3 / AM-3 exactly as now |
| **T3** | The true chain is as now. Each forecaster observes the current state through its own independent symmetric channel (correct with probability a, otherwise uniform over the other 5 states) and issues the calibrated posterior predictive Σ_s P(s_d = s \| o_d)·P⁷[s, ·] with the stationary prior. a is solved analytically so that the forecast's expected BSS against climatology equals that of the skill-world baseline |
| **B3 size** | Applied to the calibrated baseline-information forecast, as now. Under a break: the HLE-calibrated twin, as now |
| **Reported, not gated** | The v1.0 nested null (baseline + noise, sd 0.1, the cell's dependence) on the same worlds. Its `fp_k` goes to `diagnostics.null_nested_reported` |

**OPEN — τ²:**
- **Recommended: τ² = τ_b² = 0.36**, so every forecaster's information equals the skill-world baseline's, keeping the baselines comparable across truth classes.
- Alternative: τ² = 0.24 (total latent variance 0.72, as in skill worlds).

**Statistical implications:**
- E[d] = 0 exactly, by exchangeability.
- The loss differential inherits φ / ρ persistence.
- The expected path is ladder tightening (see A1 AM-1).

**Reproducibility:**
- Seeds unchanged in form; the generator version is bumped to `mi-p1s-gen-1.1.0`.
- The worlds differ from `df43073` (new tree hash).

## IR-2 — Levels for null control, ladder and power (F2) — PROPOSED

| Decision | Level |
|---|---|
| Null `fp_k` (fed to `derive()` / the ladder) | Full rule B1 (Holm m=2 at **α_step**) ∧ B2 ∧ B3 |
| Skill `pass_k` (fed to `derive()` / n\*) | Full rule at **α_step / 3** (contract B1 Bonferroni ×3 across tasks — the level a Phase 2 claim faces) |
| Diagnostics, non-gating | FPR at α_step/3 (compared with α_step/3); power at α_step |

**Rationale:**
1. The frozen ladder (α 0.05 → 0.025) with a fixed 5% criterion is only coherent if Phase 1S evaluates at α_step.
2. Holm rejections at α/3 are a subset of those at α, so FPR(α/3) ≤ FPR(α) in every rep.
3. The derivation map's "alpha" CDP is the base level, with Bonferroni applied on top.

**Limitation:** neither level verifies the 1.67% tail directly; that would need an acceptance amendment, which is not proposed.

**PASS direction: ↓** on both gates.

## IR-3 — B3 interval construction (F6) — PROPOSED

1. The three frozen CIs (Cox slope ∋ 1, offset-model intercept ∋ 0, calibration-in-the-large O/E ∋ 1) are each two-sided at **1 − 0.05/3 (98.33%)**.
2. Clusters are contiguous blocks of round(L_step) days. **G = the number of non-empty blocks.** CR1 sandwich; critical value **t(G − 1)** at the 0.99167 quantile.
3. A structurally degenerate point CI contains its target iff within 1e-9.
4. T3 is pooled one-vs-rest.

**Why:** with three 95% CIs, the exact-Gaussian nominal size is 10.4–14.3% even with perfect intervals (intercept / CITL correlation 0.99 → 0), against the frozen 7% gate. That is a manufactured `B3_SIZE_FAIL`. At 98.33% the nominal size is 3.6–4.9%.

**Rejected alternative:** a joint Wald test, because it changes contract-level B3 text, which the versioning rules forbid before v1.1.

**PASS direction: mixed** — ↑ on the B3-size gate, ↓ on the B3-power gate (risk N2 in π = 0.01 cells; a `B3_POWER_FAIL` STOP is a legitimate outcome).

## IR-4 — L2 fitted baseline (F7) — PROPOSED; dev length OPEN

**Construction:**
- Binary: the baseline is a logistic regression of y on [1, qb], fitted on the dev draw.
- T3: the baseline is a conditional logit with class intercepts and β·log b_k, fitted on the dev draw.
- Candidates are unchanged (nested: baseline index plus 6 / 2 noise features).

**OPEN — dev-draw length:**
- **Recommended: 517 days** (current).
- Alternative: the real dev span (S-MAJ 2018–2024, ≈ 2 557 days). This adds about 4–5× to L2 CPU (≈ +1 500 CPU-s) and makes fitting noise realistic.

**PASS direction: ↓** (removes the oracle-baseline bias that kept L2 FPR low).

## IR-5 — DM variance and degrees of freedom (F8) — COND

1. **Kernel.** The Diebold–Mariano "HAC fixed-b" is implemented with the EWC long-run variance and a Student-t(ν) reference (fixed-smoothing asymptotics; Lazarus–Lewis–Stock–Watson 2018, Coroneo–Iacone 2020). **Owner acceptance of this reading is required.**
2. **Pre-declared rule.**
   - **Default:** keep ν = max(2, ⌊3·n_days/(4L)⌋).
   - **Fallback:** if acceptance test AT-5 finds DM-EWC size outside [3.0%, 7.0%] at a 5% nominal level in **any** pre-declared setting, switch to ν = max(2, min(⌊0.4·n_days^(2/3)⌋ / block_factor, ⌊3·n_days/(4L)⌋)).

   The rule is fixed now; Gate C applies it mechanically.

## IR-6 — Leak-strength calibration (F9) — PROPOSED; λ value and detection curve OPEN

**Leak model** — "the label enters one feature":
- **T1 / T2:** the label's own outcome shock is z = ℓ + z′ with ℓ ~ N(0, λ), the leaked component. The leaky forecast is the exact calibrated Φ((μ_f + s_b + s_k + ℓ)/√(1 + τ_u² − λ)), built on the bss_min skill candidate.
- **T3:** a leak channel reveals the target state with probability θ (otherwise uniform), combined with the skill candidate by Bayes' rule (calibrated). θ is set so that the channel alone has the same expected BSS against climatology as the strongest legitimate signal.

**Canary:** the frozen derivation-map trip-wire. A rep fires if its realised BSS is strictly greater than the task ceiling.

**OPEN — λ:**
- **Recommended: λ = τ_b² = 0.36**, a leak as strong as the strongest legitimate signal.
- Analytic expected BSS (Simpson quadrature):

| π | 0.01 | 0.05 | 0.20 | 0.30 | 0.50 |
|---|---|---|---|---|---|
| Expected BSS at λ = 0.36 | 0.101 | 0.131 | 0.168 | 0.178 | 0.184 |

- These sit near the trip-wire ceilings (≈ 0.06–0.20), which is the point: the test is near the threshold, not trivial. The current w = 2 gives 0.31–0.85.
- Alternatives: λ = 0.20 (0.058–0.110) or 0.10 (0.037–0.064). These sit below the ceilings, so the canary would essentially always fail and would add no information beyond "the trip-wire misses small leaks".

**OPEN — non-gating detection curve:** λ ∈ {0.10, 0.20} at 100 reps per cell; about 400–600 CPU-s; not required.

**PASS direction: ↓.** `LEAK_CANARY_WEAK` becomes plausible in T2, whose ceiling is driven by the n = 150 cells. That would be a legitimate negative outcome about the frozen trip-wire.

## IR-7 — B4 / B6 at L1 (F10, implementing AM-2) — PROPOSED; pseudo-B4 diagnostic OPEN

- **Output meta records:** `rules_simulated: [B1, B2, B3]`, `rules_omitted: {B4: "no dev folds at L1", B6: "no W2 segment at L1"}`, `power_bound: "upper bound w.r.t. B4/B6"`.
- **OPEN — pseudo-B4 diagnostic:** the sign of the mean Brier differential in each third of the sample, with a 2/3 consistency count. Recorded per skill rep, non-gating, never fed to `derive()`. CPU is negligible. It quantifies how much a B4-like gate would cut power.

## IR-8 — T3 miscalibration variants (F11) — PROPOSED

- **Gated slope variants (T3):** temperature scaling, softmax(log q / s), with s ∈ {0.7, 1.4}. Rows sum to 1.
- **Reported intercept variants (`int_±0.3`):** recorded as `not_applicable` for T3. A uniform logit shift on forecasts that sum to one cancels under renormalisation, and pooled one-vs-rest calibration-in-the-large is structurally 1. They are never gated, and `derive()` reads only the gated variants.
- **Why:** per-class transforms without renormalisation give row sum 0.824 (O/E 1.21), so calibration-in-the-large artificially inflated T3 B3 power.
- **PASS direction: ↓** (B3-power gate in T3).

## IR-9 — Ladder FAIL checkpoint (F14) — PROPOSED

**Rule.** In full mode, a task whose null grid fails at k2:
- journals `ladder_fail_stop`;
- exits with code 4 **before** computing its step-2 final classes (about 3 000 CPU-s for T1).

Continuation needs `--continue-after-ladder-fail`, used only after your decision and journaled. `derive()` semantics are unchanged: FAIL → `DESCRIPTIVE_ONLY`, final classes at step 2.

**Basis:** protocol `ladder.beyond_ladder: "STOP to owner"`. **PASS direction:** neutral (CPU governance).

---

## Reproducibility requirements (all items)

- The interpretation JSON, generator version, method identifiers, interpreter version and platform are bound into the plan hash and the output meta.
- Every choice above is fixed **before** Gate C. Gate C tests may apply only the pre-declared IR-5 rule; any other test failure is a STOP to the owner, never a retune.
- `df43073` results are never reused under v1.0.1.
