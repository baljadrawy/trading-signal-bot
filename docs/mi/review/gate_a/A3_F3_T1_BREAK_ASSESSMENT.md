# A3 — F3: T1 ×2 base-rate break — independent assessment (UNRESOLVED; owner decision)

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE** — Gate A review material. Nothing here is an owner approval or a frozen artefact, and nothing here may be loaded by any run.

## 1. Facts (verified in the frozen documents and `df43073`)

| # | Fact | Source |
|---|---|---|
| 1 | The T1 generator includes an "optional ×2 base-rate structural break at the HLE start"; L1 has "no model fitting" | protocol `generators.T1`, `layers.L1` |
| 2 | HLE evaluation is of **locked** models ("after: model-lock hash pushed", 1 look) | contract `segments.hle` |
| 3 | Stress = φ 0.95 and break 1, so break=1 with φ = 0 is **non-stress** (6 cells) | `stress_rule.T1` |
| 4 | n\* (T1) is upward-closed: every non-stress, non-verification cell with positives ≥ c must have power ≥ 80% | derivation map `n_star_T1_T2` |
| 5 | Exclusions = stress cells **failing null control**; the Phase 4 `break_ratio_min 1.5` check is "for failing stress cells" | `derive.py`; `applicability_thresholds.use` |
| 6 | B3-size and B3-power gates apply to non-stress cells only; the leak gate applies to all cells | `derive.py` |
| 7 | Implementation: forecasts carry the dev rate π/2 and HLE outcomes occur at π, so O/E ≈ 2. B3 calibration-in-the-large rejects every forecast. Development diagnostic: skill pass 0/8 with the break versus 5/8 without | `gen.binary_design`; dev diagnostic |
| 8 | In a break cell, B3 size is measured on the HLE-calibrated twin, which has the same distribution as in the break = 0 cell with the same (π, φ, ρ) | `gen.t1_world` (`b_cal` uses μ_y) |

**Consequence of 4 + 7.** With 62–1 241 positives, log(O/E) = 0.69 is far beyond any 98.33% CI half-width (≈ 2.4 × 1/√62 ≈ 0.30 even before dependence inflation). Power in the 6 break cells is therefore ≈ 0 at every evidence level. Each positives level (62 / 310 / 1 241) contains break cells, so **no c satisfies the n\* rule** and T1 is `INSUFFICIENT_ALWAYS` with near certainty.

## 2. The scientific question

Is the n\* requirement "power ≥ 80% in break cells" a meaningful statement about **how much evidence** T1 needs?

n\* answers: *"how many positives are needed for the frozen rule to detect skill of size bss_min?"* That question presupposes that power rises with evidence. Under a break facing locked forecasts it does the opposite: the more positives, the more surely B3 rejects. **Power is unattainable by construction, not for lack of evidence.** Folding these cells into n\* conflates two different conclusions:
- "insufficient evidence";
- "a locked model is invalid under a regime break".

The second is a validity / applicability matter. The protocol already handles that kind of condition with stress cells plus a real-data applicability check. This is the case for reclassifying.

**The case for keeping:**
1. The stress designation was frozen deliberately. Changing it after its consequences became visible risks a forking-path decision, even though no calibration run exists and the motivation is structural (analytic), not empirical.
2. The designers may have *intended* T1 to be certified only if it is robust to a ×2 break. If so, T1 `INSUFFICIENT_ALWAYS` is the honest result: no locked T1 model can be certified, because its calibration cannot survive a break.
3. Breaks with ratio between 1 and 1.5 are not simulated under either variant.

## 3. Alternatives and consequences

| | **F3-K — keep** | **F3-R — reclassify, with extended applicability check** |
|---|---|---|
| Protocol change | Disclosure field only (inside v1.0.1) | `stress_rule.T1 = break=1`; 6 cell flags; `applicability_thresholds.use` extended (A1 AM-3-R) |
| T1 stress / non-stress | 6 / 18 | 12 / 12 (total stress cells 11 → 17) |
| Null control / ladder | Break cells pass trivially (FPR ≈ 0, all forecasts rejected by B3), so they never decide the ladder | **Identical outcome:** removing cells that always pass changes nothing |
| B3-size gate | 18 T1 gates, of which 6 statistically duplicate their break=0 twins (fact 8) | 12 gates. Fewer chances of a `B3_SIZE_FAIL` STOP, but **no information lost** (the twins stay gated). Disclosed as a PASS-direction effect |
| B3-power gate | Break cells: B3 rejects the miscalibrated variants anyway, so they pass | Removed; the twins remain |
| n\* / T1 status | `INSUFFICIENT_ALWAYS` ≈ certain, whatever the real data look like | Decided by power in the 12 no-break cells; break-cell power still computed and **reported** (≈ 0, descriptive) |
| Protection against a real break | Implicit: T1 can never be certified | (a) real-data B3 rejects a miscalibrated locked model; (b) Phase 4: an observed HLE/dev base-rate ratio ≥ 1.5 downgrades T1, now applied to **all** break cells even though they pass null control (without this extension, fact 5 means the check would never trigger) |
| Residual risk | — | Breaks of ratio 1.0–1.5 are not simulated (same under F3-K); the Phase 4 break-ratio estimator must be defined before Phase 2 |
| PASS direction | — | ↑ T1 status (from certain INSUFFICIENT to data-dependent); ↑ slightly on B3-size STOP risk (fewer duplicate gates); **no change** to false-positive protection or the ladder |
| Governance | Minimal | Protocol-level amendment; the derivation map and code are untouched |
| CPU | Unchanged | Unchanged (the cells still run) |

**Rejected options:**
- **Expanding-window intercept recalibration:** contradicts L1 "no model fitting" and the locked-model HLE. It would need a contract-level change to the Phase 2 model specification.
- **Excluding break cells from n\* only:** needs a change to `derive.py`, which is frozen code.

## 4. Independent judgement (for your decision; not a resolution)

- **F3-R is scientifically justified only together with the extended applicability check**, and only because:
  1. the power requirement it removes is unattainable by construction, so its removal does not weaken any false-positive or calibration protection;
  2. the removed B3 gates duplicate retained twins;
  3. a real break stays covered by real-data B3 and an explicit Phase 4 downgrade;
  4. the decision is taken before any calibration output and is disclosed in the amendment record, together with the bounded development diagnostics that revealed the issue.
- **F3-R without the extension is weaker** (protection rests on real-data B3 alone) and is not recommended.
- **F3-K is internally consistent but uninformative.** It fixes T1's outcome a priori from a hypothetical scenario rather than from evidence. It is the right choice only if you intend "certifiable under a ×2 break of locked models" to be a hard requirement for T1.

## 5. Approval needed

Choose **F3-K** or **F3-R (with the extended check)**. If F3-R: also approve that the Phase 4 break-ratio estimator (HLE / dev D24 base rate, PIT-safe) is specified before Phase 2.
