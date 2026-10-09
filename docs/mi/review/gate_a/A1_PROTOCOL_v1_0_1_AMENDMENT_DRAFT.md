# A1 — Phase 1S protocol amendment MI-P1S-AM-1 (v1.0.0 → v1.0.1) — DRAFT, NOT FROZEN

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE** — Gate A review material. Nothing here is an owner approval or a frozen artefact, and nothing here may be loaded by any run.

| | |
|---|---|
| Status | Gate A draft for owner review. **Not frozen, not committed, not usable for any run.** |
| Amends | `mi_phase1s_protocol_v1_0.json` v1.0.0, sha256 `412cb6062ea5b4f4c9b8bd9fa34cf0d449b4f8abcab4c173858791a9f9464202` |
| Contract set | MI-C v1.0 `fdf3366480976db6ada1ac90b62f6b6db1edc35a59d1f3527cfcd6fcbf28e157` — **unchanged and never edited** |
| Legal basis | protocol `budget.scope_changes`: *"protocol amendment (v1.0.x) approved by the owner and pushed before it runs"*; contract `versioning.immutability`: v1.0 stays byte-identical (this amendment is additive, see A4) |
| Pre-registration position | No Phase 1S calibration output exists under v1.0. The only synthetic numbers seen are bounded development diagnostics (listed in A4 §5). |
| Machine drafts | `draft/mi_phase1s_protocol_v1_0_1.F3-KEEP.DRAFT.json` (sha256 `76a7d17c…`), `draft/mi_phase1s_protocol_v1_0_1.F3-RECLASSIFY.DRAFT.json` (`1ff232a6…`) and their unified diffs against the frozen file. Both carry a `draft_status` field that is removed at freeze, so the frozen v1.0.1 hash will differ. |

The amendment has three clauses. AM-1 and AM-2 are recommended. **AM-3 is open (F3), with two variants**; see A3.

Everything outside these clauses is unchanged byte-for-byte:
- cells (apart from the T1 stress flags under AM-3-R) and reps;
- the bootstrap count, ladder and steps;
- meta-acceptance, budget, L2 cells and reps;
- skill levels, bss_min, generators, the T2 / T3 references;
- the output record.

## Clause-by-clause diff

### Header (both variants)

| Field | v1.0.0 | v1.0.1 draft |
|---|---|---|
| `version` | `"1.0.0"` | `"1.0.1"` |
| `amends` | — (new) | `{record: tsb.mi.phase1s_protocol, protocol_version: 1.0.0, protocol_sha256: 412cb606…, contract_set_sha256: fdf33664…, amendment_record: MI-P1S-AM-1, basis: scope_changes …}` |
| `draft_status` | — | review marker only; **deleted at freeze** |

### AM-1 — gated null class (finding F1)

**v1.0 `truth_classes.null`, verbatim:**
> candidate = strongest baseline + independent noise (no incremental skill)

**v1.0.1 `truth_classes.null`:**
> equal-skill boundary null (gated): the strongest baseline and both candidates are each calibrated forecasts built on
> mutually independent, exchangeable information signals of equal variance and identical dependence (T1/T2:
> equal-variance latent signals with the cell AR(phi) / factor rho / overlap structure; T3: independent
> state-observation channels of equal accuracy), so every forecast pair has exactly equal expected Brier score
> (E[d] = 0, the H0 boundary of B1) and the loss differential inherits the cell persistence; no incremental skill

**New `truth_classes.null_nested_reported`:**
> v1.0 null definition, reported only and never a gate: candidate = strongest baseline + independent noise, evaluated
> on the same simulated worlds as the gated null

**Why.** The v1.0 null is *interior* to H0: a noisy copy of a calibrated baseline is strictly worse in expectation.

| Evidence | Measured |
|---|---|
| DM t-statistic means, 20 reps, implementation `df43073` | −2.71 / −1.47 / −0.79 / −0.48 SE below the boundary |
| Same, exact-boundary construction | −0.15 to +0.13 |

So the v1.0 null control is vacuous in large cells and cannot detect an anti-conservative test. A noise-only boundary null would fix the location but not the purpose: its loss differential inherits only the outcome-residual memory (≤ 1 day), so the φ / ρ / overlap stress dimensions would be inert. Equal-skill forecasts built on persistent, non-nested signals give an exact boundary *and* a persistent loss differential — the least-favourable configuration the stress grid is meant to probe.

**What changes semantically:**
- the configuration the null FPR (and therefore the ladder) is measured under;
- the v1.0 construction is still computed and reported.

**What does not change:** the acceptance rule (5/100 point, Wilson UB ≤ 0.07), reps (1 000), the ladder, `derive()`.

**Statistical implications.** A correctly sized test now sits near the 5% criterion, which has no point tolerance. Exact binomial pass probabilities per cell:

| True FPR | Per-cell pass probability | All 18 T1 non-stress cells pass | All 12 cells pass |
|---|---|---|---|
| 4 % | 0.951 | 0.40 | 0.55 |
| 4.5 % | 0.80 | 0.019 | — |

Tightening the ladder to k2 (α = 0.025) is therefore the expected path for a well-calibrated procedure.

**PASS direction: ↓.** Null control becomes sensitive. Expected CDP: α = 0.025, block ×2.

**CPU.** Null reps cost about 10–20% more (extra signal processes; bootstraps are now triggered near the boundary). The worst-case ladder path (+2 null grids) becomes the expected one.

**Implementation detail** is in the interpretation record, A2 IR-1.

**Acceptance tests:** A5 AT-1, AT-2, AT-3.

### AM-2 — L1 rule scope (finding F10)

**v1.0 `layers.L1`, verbatim:**
> forecast-level simulation: true p_t, baseline forecast, candidate forecast, outcomes; rules B1-B6 applied exactly as
> frozen; no model fitting

**v1.0.1 `layers.L1`:**
> forecast-level simulation: true p_t, baseline forecast, candidate forecasts, outcomes; rules B1-B3 applied exactly as
> frozen; B4 (dev-fold sign consistency) and B6 (W2 S-MAJ check) are not simulable at L1 (no dev folds and no W2
> segment are simulated) and are omitted, so simulated power is an upper bound with respect to them; B5 (n*) is the
> calibration-dependent parameter produced by the frozen derivation map; no model fitting

**Why.** "B1–B6 exactly as frozen" cannot be honoured at L1. B4 needs the 16 dev folds and B6 needs the W2 segment, and neither exists in a 517-day HLE-like synthetic sample. The v1.0 text and the only feasible implementation contradict each other (a frozen-protocol inconsistency).

**What changes semantically:** this states the scope truthfully; no computation changes.

**Statistical implications:**
- The null FPR is an upper bound with respect to B4 / B6 (conservative).
- Power, and therefore n\*, is optimistic (anti-conservative for the minimum-evidence CDP). This is disclosed in the output meta and in v1.1.

**PASS direction:** neutral (documentation of an existing limitation).

**Acceptance test:** AT-11.

### AM-3 — T1 break cells (finding F3): OPEN, two variants

| Field | v1.0 | AM-3-K (KEEP) | AM-3-R (RECLASSIFY) |
|---|---|---|---|
| `stress_rule.T1` | `phi=0.95 and break=1` | unchanged | `break=1` |
| `cells[*].stress` | 6 T1 stress cells | unchanged | +6: `T1\|pi={0.01,0.05,0.2}\|phi=0\|rho={0,0.5}\|brk=1` become `true` → **T1 12 stress, 17 in total** |
| `applicability_thresholds.use` | `Phase 4 downgrade-only check for failing stress cells` | unchanged | `…; for T1 the break_ratio_min check applies to every break=1 stress cell whether or not it fails null control` |
| `t1_break_disclosure` (new) | — | Discloses that T1 n\* is expected to be infeasible (`INSUFFICIENT_ALWAYS`) independently of the evidence | Discloses that break cells are reported only, and that protection rests on real-data B3 plus the extended Phase 4 check |

The scientific assessment and the consequences of each variant are in **A3**. Neither variant is recommended *here*; F3 stays unresolved as instructed.

## What freezing v1.0.1 would involve (later, separately approved — not done)

1. Choose the AM-3 variant.
2. Remove `draft_status`.
3. Write `p2_research/mi/contracts_v1_0_1/` with:
   - the protocol;
   - the machine-readable interpretation record (A2);
   - the amendment record;
   - a new sums file (A4).
4. Push and verify the remote SHA. v1.0 files are not touched.
