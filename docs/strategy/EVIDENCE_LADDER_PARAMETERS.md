# Evidence Ladder parameters and discrepancy register (S5-PWR-1)

**What this is.**
- A citation index of the Evidence Ladder parameters as they are written in the A29–A34 governance documents.
- A register of where those documents disagree.
- The named calculation scenarios used by `research/power/`.

**What it is not.**
- It does not change, adopt or replace any governance rule.
- It does not edit the roadmap.
- It does not lift any HOLD.

Where the documents disagree, this file records the disagreement and leaves it **unresolved**: no value here is binding by being written down.

Calculator: `research/power/ladder_power.py` (`s5-pwr-1-v2`). Owner decisions: `docs/strategy/S5_PWR_1_OWNER_DECISIONS.md`.

## 1. Source documents and provenance

The governing documents are **not on GitHub**. They exist only in the local, unpushed commit `54a6369` (branch `feature/mi-am4a-stage-b-prep-20261011`). That branch was held at Gate 1 because it also carries protected-holdout material and about 300 MB of research output.

| Document (path at `54a6369`) | Git blob | SHA-256 (verbatim bytes) | Commit(s) touching it |
|---|---|---|---|
| `docs/audits/2026-10-12/A29_QUALIFICATION_ARCHITECTURE_REVIEW.md` | `a6202232aa17` | `959d5071b8ff7d7c…` | `2510c77` |
| `docs/audits/2026-10-12/A30_PROSPECTIVE_EVIDENCE_ARCHITECTURE.md` | `5abdf3f49ddc` | `2b45d6e9093e6ec1…` | `30d80e4` |
| `docs/audits/2026-10-12/A31_PROSPECTIVE_VALIDATION_READINESS.md` | `ee660416abec` | `25971f8e1721b1df…` | `9c99c79` |
| `docs/audits/2026-10-12/A32_CLAIM_ALIGNMENT_AND_ALPHA.md` | `e3635449a7d7` | `dc64f7b4916c61e0…` | `c02f934` |
| `docs/audits/2026-10-12/A33_A_VALIDATION_PREREGISTRATION.md` | `92c582d4b87c` | `48925202015ee392…` | `554bbd1`, then `91306af` (run-time checkout note) |
| `docs/audits/2026-10-12/A34_B_VALIDATION_STATISTICAL_ADEQUACY.md` | `61f3e8b7060e` | `ca258dff07c20818…` | `ef7b9a2` |

Full digests are in §6. To reproduce on the host: `git show 54a6369:<path> | sha256sum`.

### 1.1 Why the documents are NOT imported in this PR

The S5-PWR-1 rule is: inspect for secrets, protected-outcome-derived values and restricted evidence, and **do not publish if uncertain**.

**Inspection done (2026-10-19):**
- A pattern scan for credentials, tokens, keys, chat IDs, IP addresses and connection strings found **nothing**.
- A keyword scan for W1/W2/W3, holdout, sealed, win rate, trade P&L and klines found **no** protected-period values.
- A line-by-line provenance classification was run on all five documents.

**Result: four items are UNCERTAIN, so the import is blocked.**

| ID | Location | Item | Finding |
|---|---|---|---|
| U1 | A29 §1 (critical diagnosis) | verdicts and power figures of the earlier governed confirmations (A25–A28) | Most likely runs on synthetic worlds. Whether "governed confirmation" results count as protected needs an owner ruling |
| U2 | A30 §4 A2; A33 §4 set C | the "TP/SL skew −1.44" generator | **Resolved: SYNTHETIC.** Stylized generator `a28_oc_study.py:40` at `54a6369`: 20 % at +4, 80 % at −1, plus 0.3·N(0,1); the left-skew variant is its negation |
| U3 | A29 §8 | lag-test retention "0.64–0.89" (A26) | Most likely planted synthetic edges. Not confirmed from the text |
| U4 | A30 §7 | tier-1 "STRESS + MES + MDE" bps figures | **Not resolvable without an owner ruling.** STRESS uses `p2_research/h1/costs.py` (at `54a6369`), whose header says the tier spread table is "MEASURED->ASSUMED 2026 P2-X1 tier spread table". If that table comes from forward-collector data, the figures are protected-derived |

A31 and A32 also name one collector symbol stream in their operational notes. That is operational metadata about the protected collector universe, not data, but it is noted.

**Consequence:**
- This file quotes **only** design parameters, mathematical statements and synthetic-simulation results.
- It quotes **nothing** from U1, U3 or U4, and no σ or cost figures in bps.
- Publishing the documents themselves is owner decision OD-1.

## 2. Parameters as documented (citations, not adoption)

**Status vocabulary:**
- `CONSISTENT`: every document that states the parameter agrees.
- `LATEST_DOCUMENTED`: the most recent document's value, where earlier documents differ.
- `UNVALIDATED`: a value the documents themselves call provisional.

| Parameter | Value as written | Sources | Status |
|---|---|---|---|
| Claim | SUPPORTED_WINDOW: μ_W > 0 for the mean daily mark-to-market net excess over the observed 365-day window; no persistence or deployment claim | A31 §0, A32 §1–2, A33 §3 | LATEST_DOCUMENTED (A31 offered it as the resolution; A32/A33 adopt it) |
| Horizon | ≤ 365 days, no second-year extension | A30 scope, A31 owner baseline | CONSISTENT |
| Capacity | ≤ 3 simultaneous candidates | A30, A31 | CONSISTENT |
| Reserve | 20 % of slot-days, not 20 % of alpha | A30 §3, A32 §4, A33 §2 | CONSISTENT in target; the rule differs (DR-3) |
| Program FWER | 5 %, union bound under arbitrary dependence | A30 §4.2, A32 §4, A33 §7 | CONSISTENT |
| Admissions | ≤ 12 per 3-year program; unused alpha forfeited; no recycling | A30 §4 item 4, A31 §3, A32 §4, A33 §7 | CONSISTENT (A31 calls 12/3 years "provisional") |
| Alpha per admission | 1/240 for MAIN **and** RESERVE | A32 §4, A33 §7, A34-B §1 | LATEST_DOCUMENTED; reserve rule differs earlier (DR-1) |
| Calibration level | α_cal = α/1.15 = 1/276; allocation stays 1/240 | A33 §4, §8; A34-B §2 | LATEST_DOCUMENTED, not yet validated (DR-2) |
| Test statistic | HAC (Bartlett, L = 7) z of the daily net-excess mean | A30 §1, A31 §2, A33 §3 | CONSISTENT |
| Looks | efficacy at day 365 only; futility z < 0 at days 182/273, non-binding | A31 §2, A32 §5, A33 §3 | LATEST_DOCUMENTED; A30 used four OBF looks (DR-4) |
| Gates and flags | skewness ≥ −2.0 is a gate; Ljung–Box Q(10) > 23.209 is a flag only | A32 §3, A33 §3 | LATEST_DOCUMENTED; A30/A31 used Ljung–Box as a gate (DR-5) |
| ENCOURAGING | z ≥ 0.8416 at the final look, checks passed; non-confirmatory; about 20 % null rate | A31 §2, A32 §5, A33 §6 | CONSISTENT |
| Critical value c | envelope maximum over generator set C at α_cal | A33 §4 | **UNVALIDATED.** A31's 2.64/3.14/3.41 are in-sample (A31 §4, §9). The A33 validation was never run, and A34-B rates the A33 spec REVISE (DR-6) |
| Cost basis | STRESS costs (10 + 10 bps planning fee baseline, account fee unverified) plus an MES charge per position | A30 §1, A31 §2, A33 §3 | CONSISTENT in form; bps components not quoted (§1.1 U4) |

## 3. Discrepancy register

Each entry has a class, its evidence, and the scenario or label it maps to in `research/power/`.

**Classes:**
- **SUPERSEDED**: a later document withdrew it.
- **MATH**: an arithmetic or derivation error, or a value that does not reproduce from its stated inputs.
- **OWNER**: an unresolved owner choice.
- **UNVALIDATED**: stated as provisional or never verified.
- **GAP**: missing governance.

| ID | Class | Discrepancy | Evidence | Calculator handling |
|---|---|---|---|---|
| DR-1 | SUPERSEDED | Reserve alpha at half weight, 0.025/N (A30 §3, §4 item 4), and "RESERVE at half: 0.21 %" (A31 §3) vs equal 1/240 for both streams. A32 §4: "A31's 0.21 % reserve level is **withdrawn**". A30/A31 are not marked as superseded in the files themselves | A30 §3; A31 §3; A32 §4 | scenarios `A30_HALF_WEIGHT_RESERVE` and `A31_RESERVE_0_21_PCT`, status `SUPERSEDED`, kept for comparison only |
| DR-2 | OWNER | α_cal = 1/276 (A33's program bound *if its validation passes*: 12/276 ≈ 4.35 %) vs the A33 owner alternative: α_cal = 1/240 with tolerance CP upper ≤ 1.15α (bound 5.75 %, which must be stated in those words if adopted). Neither is certified: the validation was never run. OD-3: both stay labelled scenarios, not an approved calibration standard. The roadmap (main, l.17) cites only "α = 1/240 each" | A33 §8; A34-B §2, §4 | scenarios `A33_EQUAL_1_240_CAL_1_276` (`LATEST_DOCUMENTED_NOT_GOVERNANCE_CONFIRMED`) and `A33_OWNER_ALTERNATIVE_CAL_1_240` (`UNRESOLVED_OWNER_ALTERNATIVE`); `program_bound` reports `certified_bound = None` |
| DR-3 | SUPERSEDED / OWNER | Reserve allocation rule. The A30/A31 elapsed-day deficit rule gives about a 25 % share; the A33 committed-length nearest-to-target rule gives 0.201, with a preregistered all-null check of mean closure share in [0.18, 0.22]. It is bound in the A33 spec, which was never authorized | A33 §2; A34-B §1 | not computed; a documentation-only rule |
| DR-4 | SUPERSEDED | Four O'Brien–Fleming looks (A30 §1 item 2) were replaced by final-look-only efficacy (A31 §2). The A30 §6 MDE table includes about a 3 % OBF boundary cost (3.48 × 1.03 ≈ 3.58) | A30 §1, §6; A31 §2 | the calculator models the final look only |
| DR-5 | SUPERSEDED | Ljung–Box Q(10) is a validity gate in A30/A31 but an interpretation flag only in A32 §3 | A30 §1 item 4; A31 §2 item 4; A32 §3 | not modelled (its power cost is 0–4 points, A31 §2) |
| DR-6 | UNVALIDATED | Critical values are in-sample envelope calibrations. A31 §9 item 2 says "Envelope calibration is empirical and in-sample here". The A33 validation (`a33-vs1`, `dae3cf90…`) was never run; A34-B rates it **REVISE** and proposes `a34-vs1` (`1247aace…`), also not run. The +0.06 shift for α_cal is "interpolated from the A31 table" (A33 §8) | A31 §2, §4, §9; A33 §8; A34-B verdict | modes `A31_ENVELOPE_IN_SAMPLE` (`PROVISIONAL_IN_SAMPLE_UNVALIDATED`) and `A33_ENVELOPE_PLUS_ALPHA_CAL_SHIFT` (`INTERPOLATED_APPROXIMATION_UNVALIDATED`); `NORMAL_THEORY` as the analytic comparison |
| DR-7 | MATH | The MDE multiplier used in the A30 §6, A42 l.238 and A45 l.169 planning tables is the normal-theory 3.48 (= z(1 − 1/240) + z(0.8)). Under the latest documented calibration (c ≈ 3.20) it becomes ≈ 4.04, so those MDEs are about 16 % optimistic for the final design | A31 §2; A33 §8 | mode `NORMAL_THEORY` reproduces 3.48; test `test_envelope_multiplier_is_about_4_04_and_labelled_unvalidated` |
| DR-8 | MATH | A45 l.169 states an iid MDE of "≈ 0.12 %/setup" from ~6,400 setups/year, about 1/3 above the cap, σ = 1.5 %. These inputs give **0.136–0.142 %**. Its "0.2–0.4 %" range (√3–√10 × 0.12) becomes about 0.24–0.44 % | A45 l.169 (main) | test `test_a45_h2_stated_0_12_does_not_reproduce_from_its_inputs` |
| DR-9 | MATH (reproduces) | A42 l.238 C1 "≈ 0.13 %/trade iid" reproduces (0.133) from its stated inputs | A42 l.238 (main) | test `test_a42_c1_planning_mde_reproduces` |
| DR-10 | GAP | No ICC or day-clustering model is documented. Assumed design effects are 1 / 1.5 (A30 §6), 2–3 (A42 l.238) and 3–10 (A45 l.169) for overlapping populations | as cited | `deff`/`lrv_ratio` are explicit inputs with low/high ranges. The count-only bound is `deff_bound_any_within_cluster` = max(m), valid under heteroskedasticity given independent clusters. The exchangeable formula is labelled homoskedastic-only (§4). Neither is a measurement |
| DR-11 | GAP | Unit mismatch: the governed test is a daily HAC z on mark-to-market net excess, while the A42/A44/A45/A46 MDEs are per trade or per setup. No mapping is documented | A33 §3 vs A42/A45 | per-trade outputs are labelled `approximates_governed_test=False`, "ILLUSTRATIVE ONLY" |
| DR-12 | GAP | The roadmap (main, l.17) omits the 3-year program period and α_cal. Its binding sources (A29–A34) are not on GitHub | roadmap l.17; §1 | OD-1, OD-3 |
| DR-13 | OWNER | Admission gate: B2 gate v2 CALIBRATED on a ≥ 2,000-day historical series (A30 §1 item 4; A31 §2 item 5). Its applicability to S4 families and to `enforce`-era candidates is undefined | as cited | not modelled |

## 4. Governed-test approximation vs illustrative per-trade arithmetic

Every result carries `illustrative_until_validated = True`. No critical value has passed independent validation (DR-6; owner decision OD-5), and the result classes refuse to be built otherwise.

**Approximates the governed test:** `daily_hac_sharpe_mde(scenario, stream, cv_mode, power, days, lrv_ratio)` and `power_daily_hac(...)`.
- They set `approximates_governed_test = True`, with `endpoint = "daily_hac_sharpe"`.
- They return the minimum detectable annualized Sharpe (√365 scaling) of the daily net-excess series, (c + z_power) · √lrv_ratio · √(365/days), or the normal-approximation power Φ(S · √(days/365) / √lrv_ratio − c).
- `days` must lie in [30, 365].
- **Limitations:**
  - normal approximation;
  - ignores the non-binding futility looks, the skewness gate and finite-sample HAC bias;
  - `lrv_ratio` (long-run variance / variance) is an assumption.
- Simulated power in the source documents (A31 §5, A32 §6) is the reference. At a true Sharpe of 3 this approximation gives 0.42–0.44 under the envelope modes, against a simulated 0.46–0.56.

**Illustrative only:** `per_trade_mde_illustrative`, `power_per_trade_illustrative`, `required_trades_illustrative`.
- They set `approximates_governed_test = False`.
- They reproduce the A42/A44/A45 planning arithmetic, k · σ · √(deff · (1/n1 + 1/n2)) or the one-sample form, assuming equal σ and independent arms.
- They are **not** the governed test, and their units do not map onto it (DR-11).
- n ≥ 2 is required. A caveat is added when n/deff < 30.

**Screen statuses (`admissibility_screen.screen`)** compare implied power with the **declared** target power:
- `POWER_AT_OR_ABOVE_TARGET_UNDER_STATED_ASSUMPTIONS`
- `POWER_BELOW_TARGET_UNDER_STATED_ASSUMPTIONS`
- `POWER_VERSUS_TARGET_DEPENDS_ON_ASSUMPTIONS`
- `UNKNOWN_INPUTS`

Each result reports `implied_power_min` / `implied_power_max` and records every effective input:
- scenario and its status;
- stream;
- critical-value mode and its status;
- endpoint and target power;
- effect and dependence ranges;
- days, σ, n1 and n2.

The screen also:
- refuses SUPERSEDED scenarios;
- refuses fields the chosen endpoint does not use;
- refuses non-positive or sign-straddling effects (the claim is one-sided, μ > 0).

`reconsideration_eligible` is `False` with explicit `reconsideration_blockers` unless all of these hold:
- the endpoint is the daily approximation;
- the scenario is governance-confirmed;
- the critical value is independently validated;
- power is at or above target for every stated assumption.

None of these conditions can hold today. Even then, eligibility only allows the owner to reconsider. It never authorizes an admission.

**Interpretation rules, enforced by tests:**
1. Insufficient power is not evidence of no edge.
2. "Power at or above target under stated assumptions" is not evidence of an edge, not an admission, and consumes no alpha.
3. No output is a governance decision.
4. Declared effects are written assumptions and must never be estimated from protected or research-exposed outcomes.

**Program bound (`program_bound`)** returns these quantities separately:
- `governance_allocation` (Σ allocated α);
- `union_bound_at_test_levels` (Σ calibration levels per stream from `test_level`);
- `bound_stated_if_alternative_adopted` (A33 owner alternative only: n × 1.15 × α, e.g. 5.75 % for 12 admissions);
- `certified_bound`, which is always `None` because no calibration is validated.

**Design-effect functions:** these take synthetic cluster sizes only. Real cluster counts or timestamps from the sealed stream need separate authorization (OD-7).
- `deff_bound_any_within_cluster(sizes) = max(m)` is valid for **any** within-cluster correlation and **any** heteroskedastic variances, provided clusters are independent. Proof: Var(S_c) ≤ (Σσᵢ)² ≤ m_c Σσᵢ² by Cauchy–Schwarz.
- `n_eff_lower_bound_any_within_cluster(sizes) = N / max(m)`. With unequal clusters it can fall below the number of clusters K. In the homoskedastic ρ = 1 case n_eff = (Σm)²/Σm² ≤ K, with equality only for equal sizes.
- `deff_exchangeable_homoskedastic(sizes, icc) = 1 + (m_w − 1)·icc`, with m_w = Σm²/Σm, is valid **only** for equal variances and exchangeable correlation. Heteroskedastic clusters can exceed it: sizes [1, 9] with standard deviations 1 and 10 give an exact DEFF of 8.99 against the formula's 8.2.
- Cross-cluster dependence (overlapping positions, regimes) is not covered by any of them.
- A DEFF computed from counts is a planning bound, never a measured variance-inflation factor.

## 5. Isolation: what is tested, and the security boundary

**Boundary.**
- The package is a planning calculator for trusted synthetic inputs. It is **not a sandbox**.
- The AST checks and the audit-hook test are defense-in-depth test instruments that catch regressions in this package's own code. They cannot make it safe to run hostile Python code.
- Python audit hooks do not see environment-variable reads; the static check covers those.
- To keep caller-supplied code from running, inputs are restricted to exact `int`/`float`/`Fraction` values (no subclasses, no conversion methods) and plain `str` labels.

`tests/test_s5_pwr1_ladder_power.py` and `tests/test_s5_pwr1_remediation.py` verify:
- **Imports:** only `from <module> import <name>` from an allowlist: `dataclasses.dataclass`, `fractions.Fraction`, `math.isfinite`/`sqrt`, `statistics.NormalDist` and the package itself. No module object from outside the package is ever bound, so attribute chains such as `dataclasses.sys.modules[...]` cannot be written.
- **No dunder access, aliasing or introspection:** no dunder names or attributes (other than the `__name__` guard), and no use of `open`, `exec`, `eval`, `compile`, `__import__`, `getattr`, `globals`, `vars` or `__builtins__` even as plain names. The static checker is tested against nine known bypass snippets (positive controls).
- **Runtime:** in a separate process, an audit hook records `open`, `import`, `exec`, `compile`, `socket.*`, `subprocess.*`, `os.*`, `sqlite3.*`, `urllib.*`, `http.*` and similar events while **every public function** is exercised. It must record none. A positive control (a real `open`) must be recorded, so the hook is not vacuous.
- **Inputs:** refused inputs include
  - paths, file objects, strings and bytes as numbers;
  - booleans, numeric subclasses and objects with `__float__` (and the `__float__` is not called);
  - NaN and infinity;
  - values that overflow a float, and outputs that would be non-finite;
  - fields unused by the chosen endpoint;
  - empty labels;
  - unknown scenario, stream or mode labels.
- **No production caller:** no production file imports or references the package. This is checked by AST (`from research import power`) and by text search across `.py`, `.sh`, `.yml`, `.toml`, `.cfg`, `.ini`, `.json` and `.txt` files. Dynamically constructed import strings cannot be detected statically; that is a limitation.
- **No defaults:** scenario, stream, critical-value mode and target power must always be given.

## 6. Full digests

```
959d5071b8ff7d7ce9669ded6de58a1feee365eb459732aed6fda5bb46e02e92  A29_QUALIFICATION_ARCHITECTURE_REVIEW.md
2b45d6e9093e6ec118a73e271b56905f4e0e6ed168d953fc802eaf3871f4b1e8  A30_PROSPECTIVE_EVIDENCE_ARCHITECTURE.md
25971f8e1721b1df2c6f679624b1928701cfdac913d6753107c5160e1dad4aba  A31_PROSPECTIVE_VALIDATION_READINESS.md
dc64f7b4916c61e04504e57bba89fa583171c622b8aece1594c913e37bafd05e  A32_CLAIM_ALIGNMENT_AND_ALPHA.md
48925202015ee3926d28116665e4dfc84b090b8425c0f63d69a9cc2666066726  A33_A_VALIDATION_PREREGISTRATION.md
ca258dff07c20818141f0d9bab2d8202bbacbf3888e47985d4dea4877ae4d950  A34_B_VALIDATION_STATISTICAL_ADEQUACY.md
```
