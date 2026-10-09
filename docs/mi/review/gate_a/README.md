# Phase 1S Gate A — decision documents (DRAFT, review location, not frozen, not committed)

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE** — Gate A review material. Nothing here is an owner approval or a frozen artefact, and nothing here may be loaded by any run.

**Prepared 2026-10-09** under the "Gate A Draft Only" authorization. **Updated 2026-10-09** (A8 added under the "Gate A / F9 A8 Scientific Documentation" authorization; documentation only).

**Untouched:**
- frozen files (`contracts_v1_0/*`, `contract.py`, `derive.py`, `timeline.py`, `folds.py`; protocol `412cb606…`; contract set `fdf33664…`, re-verified);
- the MI trial ledger (genesis `adcdc0b2…`, 0 trials) and the CPU budget ledger `f5983b83…`;
- the code at `df43073`, the runner and the host.

**No** commit, push, deploy, MI activation, campaign or reservation.

## Contents

| File | Content |
|---|---|
| `A1_PROTOCOL_v1_0_1_AMENDMENT_DRAFT.md` | Clause-by-clause amendment AM-1 / AM-2 / AM-3 (K or R) |
| `A2_INTERPRETATION_RECORD_DRAFT.md` | IR-1 … IR-9 (F1, F2, F6, F7, F8, F9, F10, F11, F14) with status PROPOSED / OPEN / COND |
| `A3_F3_T1_BREAK_ASSESSMENT.md` | Independent F3 assessment; both alternatives; unresolved |
| `A4_VERSIONING_PROVENANCE_DRAFT.md` | Additive v1.0.1 set; ledger genesis and budget ledger preserved; forking-path disclosure |
| `A5_ACCEPTANCE_TESTS_DRAFT.md` | Pre-declared acceptance tests AT-1 … AT-15 with tolerances |
| `A6_SCIENTIFIC_SUPPLEMENT_F3_F9_STOP.md` | Supplement (2026-10-09): F3 K / R / R+ matrix (R rejected; R+ or K), F9 deterministic detection analysis (λ = 0.36 → `LEAK_CANARY_WEAK` near-certain; HOLD + AM-4 redesign), derive-STOP governance policy, AT-16 … AT-19. **Corrects A3** on the B3-size effect |
| `draft/f9_leak_detection_analytic.py` | Deterministic quadrature behind A6 §2 (no sampling, no seeds) |
| `A7_T1_HYBRID_STATISTICAL_REVIEW.md` | Appendix (2026-10-09): T1 Hybrid statistical review. CI rule corrected (pointwise, conditional on variance validity), E2 persistence estimator HOLD, draft Phase 2 monitoring-state semantics, R+ ≠ K STOP correction, governance status (Gate A OPEN, Gate B not authorised) |
| `A8_F9_IDENTIFIABILITY_AND_STRUCTURAL_CANARY_REVIEW.md` | Appendix (2026-10-09): independent F9 mathematical audit. Three distinct leak mechanisms (frozen text / implementation w = 2 / IR-6 λ-leak); exact non-identifiability of the calibrated λ-leak at L1 for λ ≤ τ_u² (model-specific); corrections to A6 §2.3 / §2.4 and to the session F9 reports (Neyman–Pearson claim withdrawn, λ_min approximate and detector-specific, "universally impossible" withdrawn, w = 2 passes trivially); exact 95-of-100 binomial analysis with the shared-ceiling structure; literature with access levels; conceptual PIT injection positive control and negative-control conditions; syntactic vs scientific compatibility matrix; open decisions F9-D1 … F9-D4. **F9 stays HOLD** |
| `draft/*.DRAFT.json`, `draft/*.diff` | Exact machine drafts of protocol v1.0.1 (both F3 variants) and unified diffs against the frozen file |

## Consolidated decision matrix

| # | Finding | Route | Status | Recommendation | Main alternative | PASS direction | Tests |
|---|---|---|---|---|---|---|---|
| AM-1 / IR-1 | F1 null | Amendment + interpretation | PROPOSED; τ² OPEN | Equal-skill non-nested null gated; v1.0 null reported; τ² = 0.36 | Interpretation-only near-boundary nested null (short-memory d) | ↓ | AT-1–3 |
| IR-2 | F2 levels | Interpretation | PROPOSED | Null / ladder at α_step; power at α_step / 3 | All at α/3 (insensitive) | ↓ | AT-9 |
| IR-3 | F6 B3 | Interpretation | PROPOSED | Three CIs at 98.33%; G = non-empty blocks; t(G−1) | Three at 95% (nominal 10–14% > 7%) | Mixed | AT-4, AT-13 |
| IR-4 | F7 L2 | Interpretation | PROPOSED; dev length OPEN | Fitted baseline; dev = 517 days | Dev = real span (+≈1 500 CPU-s) | ↓ | AT-8 |
| IR-5 | F8 DM | Interpretation | COND | EWC as "HAC fixed-b"; pre-declared ν rule with mechanical fallback | Bartlett with Kiefer–Vogelsang critical values | ↓ or neutral | AT-5 |
| IR-6 | F9 leak | Interpretation | **HOLD** (A6 §2.4, A8); λ not retuned | λ = 0.36 (expected BSS 0.10–0.18, near the trip-wire); A8: the calibrated λ-leak is non-identifiable at L1 for λ ≤ τ_u²; what the class certifies is F9-D1 | λ = 0.10 / 0.20 (always below the ceiling) | ↓ | AT-6 |
| AM-2 / IR-7 | F10 B4/B6 | Amendment + interpretation | PROPOSED; pseudo-B4 OPEN | State the L1 scope; power is an upper bound | Signed deviation only | Neutral | AT-11 |
| IR-8 | F11 T3 | Interpretation | PROPOSED | Temperature scaling; T3 intercept variants N/A | Class-specific shift | ↓ | AT-7 |
| IR-9 | F14 ladder | Interpretation | PROPOSED | Exit 4 at ladder FAIL; continue only by decision | Run on (current) | Neutral | AT-10 |
| AM-3 | F3 break | Amendment (variant) | **OPEN** | See A6 §1: R rejected; R+ (retained engine gates + estimator) unless break robustness is a requirement (then K) | K: T1 `INSUFFICIENT_ALWAYS` a priori | R: ↑ T1 status, ladder unchanged | A3 |
| A4 | Provenance | Additive set | PROPOSED | Forward links; no ledger write | — | — | AT-12 |

## Owner decision checklist

**Route**

- [ ] **D1** — Adopt the v1.0.1 protocol amendment (AM-1 + AM-2 + one AM-3 variant) together with the interpretation record. Alternative: interpretation only, which means F1 falls back to the short-memory nested null and F10 becomes a signed deviation.

**Clause-level and parameter decisions**

- [ ] **D2** — **F3:** choose AM-3-K or AM-3-R. If R, also: the extended Phase 4 check, and a PIT-safe break-ratio estimator specified before Phase 2.
- [ ] **D3** — IR-1 τ²: 0.36 (recommended) or 0.24.
- [ ] **D4** — IR-2 levels (α_step for null and ladder; α_step / 3 for power).
- [ ] **D5** — IR-3: three CIs at 98.33%, non-empty-block G, t(G−1).
- [ ] **D6** — IR-4: fitted L2 baseline; dev length 517 days or the real span.
- [ ] **D7** — IR-5: accept EWC as "DM HAC fixed-b", and the pre-declared ν rule.
- [ ] **D8** — IR-6: λ = 0.36 (or another value); detection curve yes or no.
- [ ] **D9** — IR-7: pseudo-B4 diagnostic yes or no. IR-8 T3 treatment. IR-9 ladder checkpoint.

**F9 (A8 §9; numbered separately to avoid collision with D1–D13)**

- [ ] **F9-D1** — What the Phase 1S leak truth class certifies: (a) trip-wire sensitivity beyond the legitimate family, (b) counting path only (declared smoke test), (c) nothing at Phase 1S with structural canaries under Phase 2 acceptance, (d) structural injection inside Phase 1S (layer amendment).
- [ ] **F9-D2** — PIT injection fixture: Phase 2 acceptance test (no grid change) or Phase 1S scope amendment.
- [ ] **F9-D3** — Whether `LEAK_CANARY_WEAK` keeps its current meaning (follows from F9-D1).
- [ ] **F9-D4** — Whether bounded dependence (deff) and T3 / stress / break-cell analysis is needed before an amendment decision (only if F9-D1 = (a)).

**Provenance and tests**

- [ ] **D10** — A4 provenance approach: additive set, `parameter_spec.provenance` for future trials, no ledger writes.
- [ ] **D11** — A5 tolerances as pre-declared, and a Gate C offline CPU allowance of ≤ 10 CPU-min.

**Mechanics and boundary**

- [x] **D12** — Preserved on the review branch `docs/mi-phase1s-gate-a-review-20261009` (owner-authorised 2026-10-09: preservation only, no freeze, no implementation).
- [ ] **D13** — Separately and later: freeze v1.0.1 (writes `contracts_v1_0_1/`, push, verify). Then the Gate B GO. **Nothing beyond Gate A is authorised by this document.**

## Explicitly unresolved (no decision has been taken)

1. Final approval of protocol v1.0.1 (route D1, clauses AM-1 / AM-2 / AM-3).
2. F3: variant AM-3-K versus AM-3-R (D2).
3. Final scientific interpretation parameters (D3–D9). PROPOSED items are proposals, not approvals.
4. MI trial-ledger provenance and future trial handling (D10). The genesis `adcdc0b2…` and the CPU budget ledger
   `f5983b83…` stay untouched.
5. Gate B implementation authorisation.
6. Gate C statistical-validation authorisation (D11).
7. Gate D runner-integration authorisation.
8. Pilot and full-calibration authorisation.
9. F9 (A8): definition of a "fire", the mechanism the leak class certifies, and F9-D1 … F9-D4. F9 is HOLD; E2 is HOLD; F3/R+ is PROPOSED, not approved.
