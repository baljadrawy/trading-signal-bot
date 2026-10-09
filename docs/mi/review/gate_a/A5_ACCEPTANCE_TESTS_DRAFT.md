# A5 — Pre-declared acceptance tests for Gates B / C (draft)

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE** — Gate A review material. Nothing here is an owner approval or a frozen artefact, and nothing here may be loaded by any run.

**Rules:**
1. Every tolerance below is fixed **now, before any Gate C run**.
2. A failure is a STOP to the owner. Parameters are never retuned to pass.
3. IR-5 is the only mechanical decision rule.
4. **Gate C CPU:** offline under `nice 19`, outside the MI slice, not charged to the MI budget, total ≤ 10 CPU-min. This needs approval as part of the Gate C GO.

| AT | Item | Setup | Pass criterion | CPU |
|---|---|---|---|---|
| AT-1 | AM-1 / IR-1 boundary null | (a) Unit test: baseline, c1 and c2 are built by the same function with the same parameters (role symmetry). (b) 100 reps each of `T1\|pi=0.2\|phi=0\|rho=0\|brk=0` and `T2\|n=1500\|pi=0.5\|rho=0`, real scale | \|mean DM t\| ≤ 0.30 in both cells (≈ 3 SE) | ≈ 15 s |
| AT-2 | IR-1 calibration | The same reps, each forecast pooled into deciles | \|ȳ − f̄\| ≤ 4·SE in every bin with n ≥ 300 | 0 |
| AT-3 | IR-1 persistence | 20 reps of `T1\|pi=0.05\|phi=0.95\|rho=0.5\|brk=0` vs `…\|phi=0\|rho=0…` | Day-level lag-1 autocorrelation of d: φ = 0.95 cell ≥ φ = 0 cell + 0.10 | ≈ 3 s |
| AT-4 | IR-3 B3 at 98.33% | (a) iid calibrated logistic data, n = 2 000, singleton clusters, 1 000 reps. (b) Pooled one-vs-rest sum-to-one degenerate case | (a) Rejection ≤ 6.9% (4.9% + 3 SE). (b) The calibration-in-the-large and intercept CIs pass | ≈ 25 s |
| AT-5 | IR-5 DM-EWC size | Synthetic daily series, n = 517, 2 000 reps per setting. AR(1) ρ ∈ {0, 0.5, 0.75} with L ∈ {5, 10}; AR(1) ρ = 0.9 with L ∈ {28, 56}; MA(1) θ = 0.8 with L = 5 | Size at 5% nominal within [3.0%, 7.0%] in **every** setting → keep the default ν; otherwise apply the IR-5 fallback and re-run once. A fallback failure → STOP | ≈ 90 s |
| AT-6 | IR-6 leak | λ = 0.36: 100 reps per π level on T1 φ = 0, ρ = 0, break = 0 cells; T3 analogue on `T3\|persistence=0.95\|shape=uniform` | Mean realised BSS within ±3 SE of the analytic value | ≈ 60 s |
| AT-7 | IR-8 T3 temperature scaling | Unit tests, plus 200 days × 20 reps | Rows sum to 1 ± 1e-12; pooled slope estimate: slope_0.7 < 1 < slope_1.4 | ≈ 2 s |
| AT-8 | IR-4 L2 fitted baseline | Unit test: the baseline is fitted on the dev draw (never `ev.b`). 100 reps of `T2\|n=400\|pi=0.3\|rho=0` | Mean DM t (noise-only candidate vs fitted baseline) ≤ +0.30 | ≈ 10 s |
| AT-9 | IR-2 levels | Test-scale full grid; unit tests on the `derive()` field mapping | `fp_k` = α_step decisions; `pass_k` = α_step/3 decisions; per rep fp(α/3) ≤ fp(α) | ≈ 15 s |
| AT-10 | IR-9 ladder checkpoint | A fabricated failing null grid | Exit code 4 + `ladder_fail_stop` journal; resumes only with the flag, journaled | < 1 s |
| AT-11 | AM-2 / IR-7 | Test-scale output | Meta `rules_simulated` / `rules_omitted` present; pseudo-B4 (if approved) absent from `derive()` inputs | 0 |
| AT-12 | A4 provenance | Loader tests | v1.0 still verifies `fdf33664…`; v1.0.1 verifies its parent and itself; tampering with any file in either set → refusal; `derive()` round trip with the v1.0.1 protocol and hashes; a test-scaled output never verifies against the v1.0.1 hashes | < 2 s |
| AT-13 | IR-3 clusters | T2 n = 150 world | G = number of non-empty blocks; df = G − 1 | < 1 s |
| AT-14 | F4 / F5 / F12 / F16 / F17 | Subprocess probes and unit tests | `/proc/self/{root,cwd}/…` denied; CLI with a denied `PYTHONPATH` entry → 0 violations; a second engine on the same output dir → `OUTPUT_LOCKED`; interpreter, platform, commit and evidence hash bound; zero DM variance → p = 1 | ≈ 10 s |
| AT-15 | Regression | The existing 38 MI Phase 1 tests plus the full Phase 1S suite under `-W error::ResourceWarning` | 100% pass, 0 skipped | ≈ 45 s |

**Statistical caveat.** Passing AT-1 … AT-15 shows the constructions behave as specified at small scale. It is not evidence of full-scale FPR, power or B3 size; those come only from the full Phase 1S run.
