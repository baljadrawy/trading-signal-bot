# A9 — Point-in-time structural leakage acceptance fixture: scientific specification (Phase 2 acceptance-test proposal)

> **DRAFT — NOT APPROVED — NOT FROZEN — NOT EXECUTABLE** — Gate A review material. This is a documentation-only specification of a **proposed Phase 2 acceptance test**. Nothing here is implemented, executed, approved or frozen; nothing here may be loaded by any run; no protocol, contract, derivation-map, code or ledger change is implied. **A9 does not resolve Phase 1S F9.**

**Recorded** 2026-10-09 on `docs/mi-phase1s-gate-a-review-20261009` (base `89cb29b0`). Appendix to A8 §6–§8. The Phase 2 fixture is the **preferred research direction** for structural leakage control; it is not an approved implementation.

**Labels:** **[F]** verified fact · **[M]** exact reasoning from frozen text · **[L]** literature (FT full text reviewed, AB abstract reviewed, MD bibliographic metadata only) · **[A]** assumption · **[R]** recommendation.

## 0. Baseline and errata

### 0.1 Baseline [F]

| Item | State |
|---|---|
| Branch / HEAD | `docs/mi-phase1s-gate-a-review-20261009` at `89cb29b0aab89690155e092a1e297fc8f52ac39c`; remote identical; tree clean |
| Frozen set | seven files match; set `fdf3366480976db6ada1ac90b62f6b6db1edc35a59d1f3527cfcd6fcbf28e157`; protocol `412cb606…`; derivation map `9311b86d…`; `timeline.py` `a2fd01c2…`; `folds.py` `54b5fea3…` |
| Gate A | A1–A8 present |
| MI trial ledger | genesis `adcdc0b2…` only; 0 trials |
| CPU budget ledger `f5983b83…` | 7 events, hash chain verified; cumulative charged **66.882077 CPU-s** (sum of the three charge events, cap 28 800), remaining **28 733.117923 CPU-s**; latest charge event 6.882077 CPU-s (seq 6, 2026-10-08T23:34Z); checkpoint head = last event hash, self-hash verified; anchor copy identical to the checkpoint |

### 0.2 Errata to earlier documents (earlier documents are **not** edited)

| Source | Erroneous statement | Correction (verified against the frozen contract `pit` block and task definitions [F/M]) |
|---|---|---|
| **A8 §6.3, row P1** | "decision-bar inclusion: a feature uses the decision bar itself (t_avail = end + δ_avail > t_issue by δ_compute)" | For a T1/T2 4-hour decision bar ending at T: δ_avail(4h) = 120 s, δ_compute = 60 s, so **t_issue = T + 180 s** (contract T1: "t_issue": "T + 180 s") and t_act = T + 240 s. The decision bar's own availability is **T + 120 s ≤ T + 180 s, so the decision bar is admissible** (contract features are "through t"). The correct P1 is the **first subsequent bar**: the 15m bar ending T + 15 min (available T + 17 min), the 1h bar ending T + 1 h, or the 4h bar ending T + 4 h, all with t_avail > t_issue. A **1d bar ending at T** (midnight decisions) is **inadmissible** because δ_avail(1d) = 300 s gives t_avail = T + 300 s > T + 180 s. §5 and §6 below use the corrected definition |
| A8 §6.1 | none; consistent with the above | — |

## 1. Scope and scientific evidence

### 1.1 What the fixture targets

The fixture tests **timestamp and feature-lineage leakage**: use, at decision time, of bars, fitted quantities or training rows that the frozen point-in-time rules declare unavailable. It is **not** a universal leakage detector. Outcome proxies with valid timestamps, label-definition errors, hypothesis or parameter selection after seeing outcomes, vendor rewrites without ingestion hashes, and forward monitoring are outside its scope (§3.4).

### 1.2 Evidence

| Reference | Access | Finding | Role for A9 |
|---|---|---|---|
| Kaufman, Rosset, Perlich, Stitelman (2012). Leakage in data mining: formulation, detection, and avoidance. *ACM TKDD* 6(4):1–21. doi:10.1145/2382577.2382579 | AB | Leakage = "the introduction of information about the data mining target that should not be legitimately available to mine from"; avoidance by data management and learn-predict separation | **Direct**: the fixture audits legitimacy as availability under frozen rules. Detection details not verified |
| Kapoor, Narayanan (2023). Leakage and the reproducibility crisis in machine-learning-based science. *Patterns* 4(9):100804. doi:10.1016/j.patter.2023.100804 | FT | [L2] features that are not legitimate; [L3.1] temporal leakage; each feature's availability at prediction time must be argued; detection "requires domain knowledge" and access to code and data; "subtle cases of leakage might slip under the radar" | **Direct**: the lineage audit mechanises the per-feature availability argument; it cannot catch proxies |
| Lipsitch, Tchetgen Tchetgen, Cohen (2010). Negative controls. *Epidemiology* 21(3):383–388. doi:10.1097/EDE.0b013e3181d61eeb | FT | A negative control must be U-comparable and not causally linked; detects bias without sizing it; false positives from control-specific artefacts | **Methodological analogy** for the clean cases C1–C5 |
| Ljungqvist, Malloy, Marston (2009). Rewriting history. *J. Finance* 64(4):1935–1960. doi:10.1111/j.1540-6261.2009.01484.x | MD | Historical database records are revised after the fact under their original dates | **Contradictory case**: a timestamp audit is blind to rewrites unless content is hashed at ingestion (P6 on HOLD) |
| Bergmeir, Hyndman, Koo (2018). *CSDA* 120:70–83. doi:10.1016/j.csda.2017.11.003; Roberts et al. (2017). *Ecography* 40:913–929. doi:10.1111/ecog.02881 | MD | Validity of time-series validation depends on dependence handling | Analogy for the embargo and purge cases |
| Arnott, Harvey, Markowitz (2019). *J. Fin. Data Science* 1(1):64–74. doi:10.3905/jfds.2019.1.064 | MD | Backtesting protocol | Analogy; selection and snooping are out of scope |

None of these works evaluates this fixture; they motivate its design and bound its claims. **They do not prove its detection performance.**

### 1.3 Assumptions specific to this system [A]

Binance spot candles are immutable once closed; the ds-0928 archive content is identified by its upstream checksums; exchange time is the reference clock; the frozen δ parameters (120 s / 300 s / 60 s / 60 s) represent availability; PRNG streams seeded from distinct SHA-256-derived integers are independent.

### 1.4 Known limitations and contradictory cases in this dataset [F]

Universe listings are inferred (`PARTIALLY_POINT_IN_TIME_CONTROLLED`); vendor-precomputed rolling-24h columns carry no window-convention lineage; 237 `SOURCE_UNAVAILABLE` and 885 WARN files with later gap handling; no arrival timestamps in the historical archive; full-sample fitted quantities (e.g. T3's trailing-365d median) look timestamp-valid and are reachable only through fitting provenance.

## 2. Frozen time definitions used by this specification [F]

From the contract `pit` block, task definitions and the fold rule (quoted, not derived from code):

| Term | Frozen text |
|---|---|
| Canonical end | "canonical end = open + tf; raw close fields map to the same end (archive −1 us, REST −1 ms)" |
| Availability | "feature uses bar b only if end(b) + delta_avail <= t_issue; late arrivals never back-filled"; δ_avail: 15m 120 s, 1h 120 s, 4h 120 s, 1d 300 s; δ_compute 60 s; δ_act 60 s |
| Issue / action (T1, T2) | T1: "t_issue": "T + 180 s", "t_act": "T + 240 s" (T = 4h decision-bar end) |
| Issue (T3) | "t_issue": "d+1 00:06" |
| Labels | "path-extreme labels: bars with open >= t_act; close-based labels: closes with end > t_act"; T1 label bars open in [T + 15 min, T + 15 min + 24 h); T2 "the breakout close is never a label" |
| Fitted quantities | "fitted quantities use only bars available before their month / fold start" |
| Folds | "decision_time <= fold_start − embargo AND label_end <= fold_start; evaluation rows censored when the label crosses the fold end"; embargo T1/T2 1 day, T3 7 days |
| Freeze | "freeze: hard failure in features and labels" |

## 3. Threat model

**Integrity objective.** No feature value, fitted quantity or training row used for a decision at T (or for a fold starting at F) depends on information that the frozen rules declare unavailable at t_issue(T) (or ineligible for F).

**Error model.** Pipeline mistakes, metadata defects and vendor effects. No adversary.

### 3.1 Detectable from source timestamps alone

Future-bar inclusion (own or cross-symbol), label-window contamination, freeze breaches, and the equality boundaries, **provided** the auditor knows which bars entered each feature.

### 3.2 Detectable only with feature lineage or fitting provenance

Fitted quantities using post-boundary bars, training rows violating embargo or purge, universe membership, vendor rolling columns. These need a declared computation graph and fold metadata.

### 3.3 Classes on HOLD (not acceptance cases)

P3 late arrival (no arrival metadata in historical archives), P5-universe (inferred listings), P6 historical revision (no ingestion content hashes). They stay on HOLD until reliable metadata exists; their absence must be reported as a coverage gap, never as a pass.

### 3.4 Out of scope

Outcome proxies with valid timestamps, label-definition errors, selection and snooping, vendor rewrites without hashes, Phase 4 / E3 forward monitoring.

## 4. Independent acceptance oracle

### 4.1 Principle

The expected outcome of every case is fixed **in this table, from the frozen contract text**, before any auditor runs. The auditor's output is compared with the table by a reconciler (§8). The table is not derived by calling `timeline.py`, `folds.py` or any production code; where the production code and this table disagree, the disagreement is a finding, not a reason to edit the table.

**Outcome codes.** `CLEAN` · `VIOLATION` (forbidden future or ineligible information) · `INCONCLUSIVE` (provenance needed by the rule is missing) · `DATA_INTEGRITY_ERROR` (malformed timestamps or source metadata; raised before any availability judgement). An unverified provenance is **never** classified CLEAN.

### 4.2 Expected-outcome table

Notation: T = 4h decision end (T1/T2); t_issue = T + 180 s; t_act = T + 240 s; F = fold start; e = embargo (1 d). Synthetic inputs are allowed where the real grids cannot produce the boundary (marked S).

| # | Case | Inputs and assumptions | Contract rule | Expected | Explanation | Tests |
|---|---|---|---|---|---|---|
| O1 | Feature bar before decision | 4h bar ending T − 4 h; t_avail = T − 4 h + 120 s | availability ≤ t_issue | CLEAN | far inside the window | implementation boundary (trivial) |
| O2 | Decision bar itself | 4h bar ending T; t_avail = T + 120 s | same | CLEAN | 120 ≤ 180; features are "through t" | implementation boundary (A8 erratum) |
| O3 | Exact equality (S) | bar with end = t_issue − δ_avail, so t_avail = t_issue | "<=" | CLEAN | equality is permitted by the frozen text | implementation boundary |
| O4 | One millisecond late (S) | end = t_issue − δ_avail + 1 ms, so t_avail = t_issue + 1 ms | same | VIOLATION | strict exceedance | implementation boundary |
| O5 | Action time vs issue time (S) | bar with t_issue < t_avail ≤ t_act | availability is judged at t_issue; t_act governs labels only | VIOLATION | a feature may not use data arriving between issue and action | scientific assumption (issue/act separation) and boundary |
| O6 | First subsequent 15m bar | 15m bar ending T + 15 min; t_avail = T + 17 min | same | VIOLATION | corrected P1 | implementation boundary |
| O7 | 1d bar ending at T (midnight decision) | t_avail = T + 300 s > T + 180 s | δ_avail(1d) = 300 s | VIOLATION | per-timeframe lag | implementation boundary |
| O8 | Previous 1d bar at a midnight decision | 1d bar ending T − 1 d; t_avail = T − 1 d + 300 s | same | CLEAN | properly delayed (C4) | implementation boundary |
| O9 | Archive close normalisation | raw archive close = end − 1 µs | "archive −1 us" maps to end | CLEAN (mapping) | canonical end recovered | implementation boundary |
| O10 | REST close normalisation | raw REST close = end − 1 ms | "REST −1 ms" maps to end | CLEAN (mapping) | same end as O9 | implementation boundary |
| O11 | Malformed close | archive close not equal to end − 1 µs, or open not on the tf grid | canonical-end rule | DATA_INTEGRITY_ERROR | not a leakage judgement | implementation boundary |
| O12 | Embargo boundary, eligible | training row with decision_time = F − e exactly, label_end ≤ F | "decision_time <= fold_start − embargo" | CLEAN | equality permitted | implementation boundary |
| O13 | Embargo boundary, violated (S) | decision_time = F − e + 1 ms | same | VIOLATION | strict exceedance | implementation boundary |
| O14 | Label-end boundary, eligible | label_end = F exactly | "label_end <= fold_start" | CLEAN | equality permitted | implementation boundary |
| O15 | Label-end boundary, violated (S) | label_end = F + 1 ms | same | VIOLATION | purge | implementation boundary |
| O16 | Cross-symbol, available | ETH decision at T; BTC 1h bar ending T; t_avail = T + 120 s | same availability rule, symbol-independent | CLEAN | shared factor is not leakage (C3) | scientific assumption |
| O17 | Cross-symbol, future | ETH decision at T; BTC 1h bar ending T + 1 h | same | VIOLATION | P5 | implementation boundary |
| O18 | Legitimate persistence | feature = realised D24 outcome of the decision 24 h + 15 min earlier; its label bars end ≤ T − 15 min, t_avail ≤ t_issue | availability rule | CLEAN | persistence is information that was available (C2) | scientific assumption |
| O19 | Label-window contamination | feature uses a 15m bar with open ≥ T + 15 min | availability rule; label bars have open ≥ t_act | VIOLATION | future and label window (P2) | implementation boundary |
| O20 | Fitted quantity, post-boundary input | a scaler, bucket boundary or T3 trailing median fitted with a bar ending after F (or after its month start) | "fitted quantities use only bars available before their month / fold start" | VIOLATION | requires fitting provenance | lineage / scientific assumption |
| O21 | Missing provenance | a feature without a declared input set, or a fitted quantity without a fold start | rule cannot be evaluated | INCONCLUSIVE | never CLEAN | provenance handling |
| O22 | Freeze | any input bar ending after the W3 freeze | "hard failure" | DATA_INTEGRITY_ERROR | A3 | implementation boundary |
| O23 | Arrival equal to issue (S, metadata) | recorded arrival = t_issue, rule availability satisfied | "late arrivals never back-filled" | CLEAN [A] | equality is not late; the contract text does not state the inequality explicitly | scientific assumption (recorded as such) |
| O24 | Arrival after issue (S, metadata) | recorded arrival = t_issue + 1 ms | same | VIOLATION | late | P3 class, on HOLD for real data |

## 5. Positive-control cases

Common to all: source data = the sealed ds-0928 archive (S-MAJ, 4h decisions) or a synthetic bar set with the same schema; injection acts on the **input set** of a feature, training row or fitted quantity, never on lineage records; the auditor reconstructs lineage from raw bars and the declared computation graph (§8); the injector supplies no expected truth.

| Case | Violation injected | Expected outcome | Required evidence | Detectable from | Failure conditions | Blind spots |
|---|---|---|---|---|---|---|
| **P1** future bar | the first subsequent 15m / 1h / 4h bar, or the 1d bar ending at T at a midnight decision, enters vol.rv_1h_24, vol.atr_norm_1h_14 or vol.vol_ratio_15m_16_96 (O6, O7) | VIOLATION at (feature, T) | raw bars; declared input set | **timestamps** | off-by-one on ≤; δ_avail applied with the wrong tf; arrival field ignored | proxies; vendor rolling columns |
| **P2** label window | mom.dist_high_15m_96 uses 15m bars with open ≥ T + 15 min (O19) | VIOLATION; label-overlap flagged | raw bars; label window from the contract | timestamps | window start taken from t_issue instead of t_act | label-definition errors |
| **P4** fold and embargo | (a) training row with decision_time = F − e + 1 ms or label_end = F + 1 ms (O13, O15); (b) B3 baseline logistic or T3 trailing-365d median fitted with a bar ending after F (O20) | VIOLATION | fold metadata; **fitting provenance** for (b) | (a) timestamps + fold metadata; (b) **lineage** | undeclared fitted quantities; evaluation-row censoring confused with training eligibility | hyperparameter selection on evaluation folds |
| **P5** cross-symbol future | btc_logret_24h or ctx.btc_rv_1h_24 for an ETH decision uses a BTC bar ending after T (O17) | VIOLATION | BTC raw bars; declared input set | timestamps | per-symbol clocks assumed equal; symbol mix-ups | universe membership (HOLD) |
| **P7** equality and boundaries | the O3/O4, O9/O10/O11, O12/O13, O14/O15, O23/O24 pairs with synthetic timestamps | exactly as the table | synthetic inputs | timestamps | any drift between code and contract text | none beyond the inequalities |

**Not approved as acceptance cases (HOLD):** P3 late arrival, P5-universe membership, P6 historical revision or backfill.

## 6. Negative controls (clean cases)

Every clean case passes through the **same** ingestion, feature-construction and audit path as the injected cases, interleaved blind (§8).

| Case | Construction | Expected | Assumption |
|---|---|---|---|
| **C1** legitimately predictive feature | a synthetic world in which an admissible feature has very high skill (or, on real data, the admissible feature with the highest dev skill) | CLEAN | the oracle never reads forecasts, outcomes or skill |
| **C2** genuine persistence | O18 | CLEAN | persistence of an available quantity is not leakage |
| **C3** shared market factor | O16; hist.universe_ret_24h_median from admissible bars of listed symbols | CLEAN | cross-symbol ≠ future |
| **C4** properly delayed data | O8; O2 | CLEAN | δ_avail per timeframe |
| **C5** correctly bounded folds | O12, O14 and interior rows | CLEAN | embargo and purge both applied |

**Why high predictive skill must never trigger a structural violation.** The oracle's inputs are timestamps, lineage and rules. Skill is not an input. A8 §2 shows that at the forecast level a calibrated leak is indistinguishable from legitimate skill; a structural audit is valuable precisely because it does not depend on that distinction. Any design that lets skill influence a structural verdict re-imports the F9 magnitude problem and makes strong legitimate features false alarms.

**Shuffled or time-shifted labels are not used as nulls.** They break U-comparability (persistence, six-step label overlap, shared factors), so a non-null result would be uninterpretable (A8 §7.5).

## 7. Anti-self-validation design

| Safeguard | Specification | Guarantee |
|---|---|---|
| Independent expected outcomes | §4.2, fixed from contract text before any run; stored with its own hash | achievable |
| Raw-data reconstruction | the auditor reads only the sealed archive (file hashes recorded) and the declared computation graph; it recomputes ends, availabilities, label windows and fold eligibility itself | achievable |
| Injector / auditor separation | separate modules, separate hashes, no shared mutable state, no read access by the auditor to injector records | achievable, **not sufficient alone** |
| Auditor frozen first | the auditor module hash is recorded before the case-selection seed is drawn | achievable |
| Sealed case selection | class, feature, decision time, offset and clean/injected mix drawn from a sealed seed; revealed only after the auditor has reported | achievable |
| Blind interleaving | clean and injected cases indistinguishable to the auditor; proportions unknown to it | achievable |
| Reconciliation | a third component, hashed and frozen with the table, compares auditor outputs with §4.2 per case; neither injector nor auditor computes the pass/fail | achievable |
| Immutable manifest | archive hashes, table hash, auditor hash, injector hash, reconciler hash, seed, cases, outcomes, interpreter and platform; deterministic replay must reproduce every outcome | achievable |
| Mutation cases | M1: "≤" → "<" (must flip O3, O12, O14); M2: δ_avail removed (must flip O4, O7); M3: t_act used in place of t_issue (must flip O5); M4: arrival ignored (must flip O24). A mutant that flips none of its pre-named cases means the fixture cannot see that rule | achievable |
| **Shared dependencies (residual common-mode risk)** | the contract text itself; the frozen `timeline.py` and `folds.py` if the auditor reuses them; the archive and its checksums; the exchange clock; the interpreter | **assumption**: a defect common to the auditor and the production pipeline is invisible to the fixture. Mitigation: the §4.2 table is written from the contract text, and the auditor may be a second implementation of that text; even then the text is shared |

Different modules and different hashes establish separation of **artefacts**, not independence of **reasoning**; only the externally fixed table and the mutation set give evidence that the auditor's judgements are not an echo of the injector's.

## 8. Draft acceptance criteria (for owner review; none is frozen)

| # | Criterion | Draft requirement | Status of a failure |
|---|---|---|---|
| AC-1 | Detection of covered injected violations | every injected instance of P1, P2, P4, P5, P7 is reported as VIOLATION at the injected locus (feature, time or row). Stated as a **structural-correctness** criterion for the covered classes; it is not a statistical-power claim and the Phase 1S 95-of-100 count is **not** reused | STOP to owner, reported by class |
| AC-2 | Acceptance of covered clean cases | every C1–C5 instance is CLEAN; every exception classified under §4.1 codes before any conclusion | STOP |
| AC-3 | Incomplete provenance | every case lacking the provenance its rule needs is INCONCLUSIVE; zero silent CLEAN | STOP |
| AC-4 | Boundary correctness | all §4.2 pairs match the table exactly | STOP; a code-vs-text disagreement is a finding against the code |
| AC-5 | Mutation sensitivity | each of M1–M4 flips every one of its pre-named cases | STOP (the fixture is blind to that rule) |
| AC-6 | Reproducibility and evidence integrity | deterministic replay from the manifest reproduces all outcomes; all hashes present; auditor hash predates the seed | STOP |

A deterministic result of 100 % on AC-1 with AC-5 and blind interleaving is evidence that the auditor implements the covered rules correctly. It says nothing about leakage outside the covered classes and nothing about statistical power.

## 9. Frozen compatibility

| Frozen element | Relation to A9 | Class |
|---|---|---|
| MI-C v1.0 A2 "PIT rules + boundary tests" | A9 is a specification of those boundary tests | A: already required; A9 adds no requirement |
| A3 zero freeze violations | O22 | A |
| A7 "feature delay", "label time-shift" | structural form of both intents (P1, P2) | A (intent); B: Phase 1S *validation* of A7 is undefined |
| A7 "shuffled features" | not implemented by A9 (U-comparability undefined) | C if ever used as a gate |
| A7 "trip-wire ceiling from v1.1" | not addressed (magnitude) | D |
| Phase 1S L1 / L2 | no timestamps or lineage in either layer; A9 cannot run inside them | D (as frozen); C if the leak class were moved to a layer with lineage |
| 48-cell grid, `reps.leak` | untouched; A9 lives outside the grid | A (no change) |
| Leak truth class | unchanged; what it certifies is F9-D1 | C for any change |
| Derivation map, `derive()` | unaffected; A9 produces no `fire_k` | A (no interaction) |
| `LEAK_CANARY_WEAK` | semantics unchanged; A9 does not feed it | C if its meaning were redefined (F9-D3) |
| Phase 2 PIT requirements | A9 is their acceptance test | A (concept); B (real-archive false-alarm behaviour, lineage schema for fitted quantities) |
| Phase 4 / E3 | separate protocol | D (out of scope) |

**A9 is a proposed Phase 2 acceptance-test specification and does not resolve Phase 1S F9. No change to any frozen gate semantics is approved.**

## 10. Open issues and owner decisions

| # | Question | Not resolved here |
|---|---|---|
| F9-D1 | What the Phase 1S leak truth class must certify (A8 §9 options a–d) | — |
| F9-D2 | Whether the PIT fixture belongs in Phase 2 acceptance testing (A9's premise) or requires a Phase 1S scope amendment | — |
| F9-D3 | Whether `LEAK_CANARY_WEAK` retains its current semantics | — |
| F9-D4 | Whether further dependence and T3 / stress / break analysis is needed before an amendment decision | — |

Additional open items: a fitted-quantity provenance schema (not a contract object today); the O23 arrival-equality reading [A]; whether the auditor reuses `timeline.py` or is a second implementation of the contract text.

**Smallest next step [R], not initiated:** owner decision on F9-D1 and F9-D2. If F9-D2 confirms Phase 2 acceptance, the following step would be an A5-style acceptance-test entry referencing this appendix (documentation only), still without implementation.

## 11. Governance

F9 **HOLD** · F3/R+ **PROPOSED, NOT APPROVED** · E2 **HOLD** · Gate A **OPEN** · Gate B **NOT AUTHORISED** · MI-C v1.0 **FROZEN AND UNCHANGED** (`fdf33664…`) · Phase 1S protocol **FROZEN AND UNCHANGED** (`412cb606…`) · no automatic MI-C v2.0 or protocol revision.
