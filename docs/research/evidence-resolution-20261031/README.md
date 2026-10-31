# ERG-01 Evidence Resolution Gate: package index

**Status.** Owner-approved, documentation-only and read-only phase, written 2026-10-31. This file indexes the package, summarises the five workstream verdicts, records a cross-workstream consistency check and states what the package does **not** authorize.

> **This package authorizes no candidate selection, no pre-registration and no test of any kind.** It makes no profitability claim. A corrected defect, dormant code or earlier research effort is not treated anywhere as evidence of an edge.

## Contents
- [1. Purpose](#1-purpose)
- [2. Baseline and governance verification](#2-baseline-and-governance-verification)
- [3. Evidence classes and scales used](#3-evidence-classes-and-scales-used)
- [4. Package contents](#4-package-contents)
- [5. Workstream verdicts](#5-workstream-verdicts)
- [6. Statistical feasibility verdict (G4)](#6-statistical-feasibility-verdict-g4)
- [7. Candidate comparison verdict (G5)](#7-candidate-comparison-verdict-g5)
- [8. Verified vs unresolved evidence](#8-verified-vs-unresolved-evidence)
- [9. Cross-workstream consistency check](#9-cross-workstream-consistency-check)
- [10. Process deviations disclosed](#10-process-deviations-disclosed)
- [11. Restrictions honoured](#11-restrictions-honoured)
- [12. What this package does not authorize, and the next owner approvals](#12-what-this-package-does-not-authorize-and-the-next-owner-approvals)

## 1. Purpose

ERG-01 is the Evidence Resolution Gate that follows the 2026-10-31 read-only trading-system audit ([audit package](../../audits/2026-10-31-trading-system-review/README.md)). Its job is to resolve, as far as tracked repository text allows, five evidence questions that the audit left open, before the owner decides anything about new strategy candidates:

| Workstream | Question |
|---|---|
| G1 | Is the 9-year target-policy study (audit HIS-05) comparable with the current momentum setup or with a corrected 4h/1d momentum successor? |
| G2 | Which implementation produced each historical result (HIS-01, HIS-09, HIS-14), and can any of it be attributed to the deployed rules? |
| G3 | What do the documented implementation defects (W3 T1 cap, alphabetical candidate cut, same-bar re-fire, double-counted stop slippage) do to the evidence? |
| G4 | Can the A29 Evidence Ladder, as governed, detect a modest edge within its 365-day maximum horizon? |
| G5 | How do Candidate B (Derived Momentum Successor), Candidate C (Regime-Filtered Trend-Pullback) and option D (pause or stop) compare, and what must the owner decide first? |

The phase is **documentation-only**: it reads tracked text with `git show`, `git log`, `git grep`, `sed` and `grep`, and writes only the seven files of this directory. Audit finding IDs (HIS-05, STR-25, GOV-02 and others) are the 2026-10-31 historical baseline defined in [REVIEWER_EVIDENCE_PACK.md](../../audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md) and [FULL_SYSTEM_AUDIT_AR.md](../../audits/2026-10-31-trading-system-review/FULL_SYSTEM_AUDIT_AR.md). New findings carry local IDs G1-01 … G5-27.

## 2. Baseline and governance verification

Each row was re-checked for this README with read-only `git` commands on local objects (no network access). Classes follow §3.

| Item | Verified value | Class |
|---|---|---|
| Repository | `baljadrawy/trading-signal-bot` (private), as recorded by the clone's `origin` remote. The spelling `baltjadrawy` (with an extra "t") that appeared in task instructions is **wrong** and is not used anywhere in this package | SOURCE_VERIFIED (remote configuration) |
| `main` | `eba90ddf4ae60641f80627472098e34650915d28` (`eba90dd`, 2026-10-27), as held in the local remote-tracking ref `origin/main`. Unchanged by this phase: nothing was committed, pushed or merged. The clone's local branch named `main` is a stale 2026-06-28 ref (`0a396c2`), an ancestor of `eba90dd`; it is not the repository's `main` and was not touched | SOURCE_VERIFIED |
| Pinned audit commit | `5d977f2f851b952f6fd0de026d9222d2ef092f41` (`5d977f2`), tip of `docs/trading-system-audit-20261031` locally and on `origin`. `git diff --name-only eba90dd 5d977f2` lists only files under `docs/audits/2026-10-31-trading-system-review/` | SOURCE_VERIFIED |
| Working branch | `docs/evidence-resolution-20261031`, created from `5d977f2f851b952f6fd0de026d9222d2ef092f41` (branch reflog: "Created from" that SHA); HEAD is still `5d977f2`. The branch has no remote-tracking ref | SOURCE_VERIFIED |
| Audit documents at `5d977f2` | eight files: [README.md](../../audits/2026-10-31-trading-system-review/README.md), [FULL_SYSTEM_AUDIT_AR.md](../../audits/2026-10-31-trading-system-review/FULL_SYSTEM_AUDIT_AR.md), [REVIEWER_EVIDENCE_PACK.md](../../audits/2026-10-31-trading-system-review/REVIEWER_EVIDENCE_PACK.md), [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](../../audits/2026-10-31-trading-system-review/RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md), [STRATEGIES_INDICATORS_CALIBRATION.md](../../audits/2026-10-31-trading-system-review/STRATEGIES_INDICATORS_CALIBRATION.md), [MARKET_CONTEXT_AND_ASSET_SELECTION.md](../../audits/2026-10-31-trading-system-review/MARKET_CONTEXT_AND_ASSET_SELECTION.md), [RUNTIME_AND_PARITY.md](../../audits/2026-10-31-trading-system-review/RUNTIME_AND_PARITY.md), [RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md](../../audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md) | SOURCE_VERIFIED (`git ls-tree`) |
| Owner Operating Contract (OOC) | [OWNER_OPERATING_CONTRACT.md](../../governance/OWNER_OPERATING_CONTRACT.md), last changed `c3bb74c` (2026-10-26). §1 L10: 0.10% fee per side (0.20% round trip) plus spread and slippage; PAPER_ONLY. §4 L35: A29 Evidence Ladder in force with D1/D2 HOLD, up to a 365-day prospective horizon, at most 3 simultaneous candidates, 20% forward capacity reserved, 5% familywise error, ENCOURAGING non-confirmatory. §4 L36: version boundaries, no retroactive attribution | SOURCE_VERIFIED |
| Development-First Policy (DFP) | [DEVELOPMENT_FIRST_POLICY.md](../../governance/DEVELOPMENT_FIRST_POLICY.md), last changed `37fbaec` (2026-10-26). §3 L63: geometry, selection and integrity-mode changes are declared strategy-version boundaries. §5 L84: Evidence Ladder α = 1/240, final look only, FWER, ≤ 3 candidates, 20% reserve, CONFIRMATORY-ONLY (D3). §7 L113-114: OD-DF-1 and OD-DF-2 proposed | SOURCE_VERIFIED |
| Evidence Ladder parameters (ELP) | [EVIDENCE_LADDER_PARAMETERS.md](../../strategy/EVIDENCE_LADDER_PARAMETERS.md), last changed `1432a90` | SOURCE_VERIFIED |
| Research freeze record | `research/governance/research_freeze.json`, added and last changed at `b1c804d` (2026-09-27). At `eba90dd` it records `freeze_git_sha` = `63da7d3`… (`63da7d31daef2b952c695b256f81cf174b6451a8`), `freeze_git_dirty` = true, and `knowledge_cutoff` equal to `research_freeze_timestamp_utc`. That instant falls on **2026-08-19** and is the same instant that DFP §3 line 57 states; the equality was checked by string comparison without printing the time of day | SOURCE_VERIFIED |
| Freeze boundary | Everything after the 2026-08-19 research freeze (instant recorded in `research_freeze.json`) is FORWARD_HOLDOUT: sealed, with no outcome, count or timestamp reads (OD-7). No workstream read such material | DOCUMENTED_ONLY (policy); compliance as disclosed by each writer |
| Runtime context | Live path active (`LIVE_LEARNING_MODE=true`); momentum and reversion on code-default parameters on 15m/4h/1d; capacity 2 × $50 of $500; flat 0.30% cost; learned gates off ([runtime addendum](../../audits/2026-10-31-trading-system-review/RUNTIME_CONFIG_VERIFICATION_ADDENDUM.md)) | RUNTIME_VERIFIED (cited from the audit only) |

**Retrospective freeze record.** The freeze record was committed on 2026-09-27, 39 days after the freeze it records, from a dirty tree whose difference from `63da7d3` is not recorded (G2-12 · INFERRED). Its `freeze_strategy_contract_hash` covers files that do not exist at `63da7d3` (G3 §6.1 · INFERRED from SOURCE_VERIFIED facts). Neither point changes the freeze date; both limit how exactly "the frozen strategy" can be reproduced.

## 3. Evidence classes and scales used

| Class | Meaning in this package |
|---|---|
| SOURCE_VERIFIED | Read in a tracked file at a named commit. Not proof of deployed behaviour; image parity is documented only |
| DOCUMENTED_ONLY | Stated in a document or record, not independently verified |
| HISTORICAL_REPORTED | A past result or verdict, not recomputed |
| INFERRED | A reasoned conclusion from other evidence |
| NOT_VERIFIED | Evidence absent or the question blocked; the blocker is stated |
| CONTRADICTORY | Sources disagree |
| RUNTIME_VERIFIED | Used only when citing the audit's runtime observations |

Additional scales:
- **G1 comparability:** MATERIALLY EQUIVALENT / PARTIALLY OVERLAPPING / MATERIALLY DIFFERENT / NOT VERIFIED.
- **G3 impact:** MEASURED (an authorised measurement of realized effect exists) / MECHANICALLY INFERRED (follows from the code, size unmeasured) / UNKNOWN (neither size nor sign can be established here). No G3 item is MEASURED.
- **G4 labels:** ILLUSTRATIVE marks tables built on hypothetical, hand-typed inputs. INVALID / SUPPORTED_WINDOW / NOT_SUPPORTED_AT_δ_min / INCONCLUSIVE (with an ENCOURAGING flag) is a **PROPOSED** outcome rule (G4 §9), not in force.
- **G5 decision matrix:** ordinal Favourable / Mixed / Unfavourable / Not determinable / Not applicable, with no weights and no sum. INCONCLUSIVE in G5 is a **decision-state** label, distinct from G4's proposed test-outcome label.

## 4. Package contents

| File | Workstream | What it answers | Key local IDs |
|---|---|---|---|
| [HIS05_COMPARABILITY.md](HIS05_COMPARABILITY.md) | G1 | Comparability of the HIS-05 9-year target-policy study with the current momentum setup and the successor concept | G1-01 … G1-11 |
| [VERSION_EVIDENCE_LINEAGE.md](VERSION_EVIDENCE_LINEAGE.md) | G2 | Which implementation produced HIS-01, HIS-09 and HIS-14; attribution to the deployed rules | G2-01 … G2-14 |
| [DEFECT_IMPACT_ASSESSMENT.md](DEFECT_IMPACT_ASSESSMENT.md) | G3 | Mechanism, affected versions and evidence impact of W3, the alphabetical cut, same-bar re-fire and double-counted stop slippage; version identity and the contract hash | G3-01 … G3-15, G3-NV-01 … 08 |
| [POWER_AND_HORIZON_FEASIBILITY.md](POWER_AND_HORIZON_FEASIBILITY.md) | G4 | Alpha derivation, endpoint, dependence, minimum detectable effects, horizon, a proposed INCONCLUSIVE rule, owner questions Q1–Q7 | G4-01 … G4-15, G4-N1 … N7, G4-I1 … I5 |
| [CANDIDATE_DECISION_MATRIX.md](CANDIDATE_DECISION_MATRIX.md) | G5 | Candidates B and C and option D against seven criteria; Design A distinctness; ordered owner decisions | G5-01 … G5-27, G5-NV-01 … 10, G5-O1 … O6 |
| [FINAL_OWNER_DECISION_BRIEF_AR.md](FINAL_OWNER_DECISION_BRIEF_AR.md) | synthesis | Arabic decision brief for the owner, readable without the other files | cites the IDs above |
| README.md (this file) | synthesis | Index, verification, cross-workstream consistency check, restrictions | — |

Governing sources used across the package: [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md), [Development-First Policy](../../governance/DEVELOPMENT_FIRST_POLICY.md), [Evidence Ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md), [S5-PWR-1 owner decisions](../../strategy/S5_PWR_1_OWNER_DECISIONS.md), [strategy evolution roadmap](../../strategy/STRATEGY_EVOLUTION_ROADMAP.md), [version boundaries](../../../deploy/VERSION_BOUNDARY.md).

## 5. Workstream verdicts

**G1: HIS-05 comparability ([HIS05_COMPARABILITY.md](HIS05_COMPARABILITY.md)).** HIS-05 is **MATERIALLY DIFFERENT** from the current momentum setup (G1-01 · INFERRED): its entry is the legacy five-indicator mean-reversion score, admitted only in bearish or sideways regimes and below both the Bollinger middle and EMA20, while current momentum is a bullish-regime breakout above the prior 20-bar high with volume confirmation; the two entry predicates are mutually exclusive on the same bar (close < EMA20 versus close > EMA20). It is also MATERIALLY DIFFERENT from the corrected 4h/1d successor concept, most of whose predicates are not specified anywhere (G1-02 · INFERRED; G1-09 · NOT_VERIFIED). HIS-05 informs only exit geometry attached to the legacy entry, and even there arm A differs from the current stack in stop rule, holding horizon, partial exits and fill order (G1-03 · INFERRED); the same T1-cap formula is triggered by different conditions after a breakout (G1-11 · INFERRED). Its documented parameters conflict across sources: universe 595 / 301 / 598, "including delisted" unsupported by the engine, "about 110k trades" total versus per arm (G1-04 · CONTRADICTORY); the audit's "every arm × year gross-negative" overstates an engine whose per-year table is net of 0.6% (G1-08 · INFERRED). Run date, code version run, symbol list and per-arm results are in no tracked file (G1-05 · NOT_VERIFIED). Two different W3 corrections are documented (G1-10 · CONTRADICTORY). HIS-05 remains HISTORICAL_REPORTED and cannot support any statement about breakout momentum or a conclusion that the momentum family failed.

**G2: version and evidence lineage ([VERSION_EVIDENCE_LINEAGE.md](VERSION_EVIDENCE_LINEAGE.md)).** None of HIS-01, HIS-09 or HIS-14 can be attributed to the deployed strategy (analyzer and signal_engine `ea8ae4f`, tracker `bb7825f`) (G2-01, G2-08 · INFERRED). The momentum and reversion predicates, regime classifier, indicator definitions and per-timeframe expiry changed at `63da7d3` (2026-08-19); signal-aware stops and partial exits arrived at `c4a623c` (2026-08-18); all three evaluation windows end earlier (G2-09 · SOURCE_VERIFIED). STR-25's inputs are SOURCE_VERIFIED (G2-05), and selection and tracking also changed after `63da7d3` (G2-06 · SOURCE_VERIFIED). Version labels do not identify implementations: `APP_VERSION` is `sb-2026.06` in code but `sb-2026.08` at runtime, and `sb-2026.08` predates the rule change (G2-02 · CONTRADICTORY); the "clean cohort `sb-2026.08`" is a date cohort (G2-03 · CONTRADICTORY); HIS-01's "15m/4h" label and window are not in its report (G2-04 · CONTRADICTORY); the runtime phase label is set by no tracked file (G2-14 · CONTRADICTORY). The three samples are disjoint by date but cover different implementations, so they are not replications (G2-07 · INFERRED). Reported figures are HISTORICAL_REPORTED only (G2-11). The freeze record is retrospective and does not pin a reproducible tree (G2-12 · INFERRED).

**G3: defect impact ([DEFECT_IMPACT_ASSESSMENT.md](DEFECT_IMPACT_ASSESSMENT.md)).** The W3 self-referential T1 cap (G3-01) and the alphabetical 200-row candidate cut with lexical tie-breaks (G3-02) are both **MECHANICALLY INFERRED** in mechanism and **UNKNOWN** in realized economic impact. For every momentum signal the cap's "resistance" is the breakout bar's own high (G3-01a · INFERRED from SOURCE_VERIFIED code); the net P&L sign is not determined by the mechanism. Both defects are present in the freeze source `63da7d3` and in every later documented version, so all Paper evidence of this implementation embeds them (G3-05 · INFERRED). No tracked document measures their realized impact over a window shown to end before the freeze (G3-06 · NOT_VERIFIED). Secondary defects: same-bar re-fire on 4h/1d inflates per-signal n, with the fix active only under `SIGNAL_INTEGRITY_MODE=enforce` while runtime is `off` (G3-03 · MECHANICALLY INFERRED for evidence validity, UNKNOWN economically); stop slippage is counted twice, so a stop exit costs about 0.40% instead of 0.30% (G3-04 · direction MECHANICALLY INFERRED as conservative, size UNKNOWN). `freeze_strategy_contract_hash` would not register the T1-policy switch or the selection-cut fix (G3-07, G3-08 · INFERRED). Each correction defines a new strategy version with no outcome evidence of its own (G3-09 · INFERRED).

**G4: power and horizon ([POWER_AND_HORIZON_FEASIBILITY.md](POWER_AND_HORIZON_FEASIBILITY.md)).** α = 1/240 is the 5% program FWER divided by 12 admissions per 3-year program, not a consequence of the 3-candidate cap (G4-01 · SOURCE_VERIFIED as restated in ELP and code; A32 original NOT_VERIFIED). The governed claim is one-sided (G4-02) and its endpoint is a daily HAC z on the portfolio-level mark-to-market net excess, which the per-trade planning MDEs of A42/A45 do not test (G4-03 · SOURCE_VERIFIED endpoint, INFERRED bridge). The 365-day minimum detectable annualized Sharpe ratio at 80% power is 3.48 to 7.00 (9.04 at lrv 5) (G4-04 · INFERRED); the horizon, not the alpha allocation, is binding (G4-06 · INFERRED). Dependence (ICC, design effect, lrv) is unmeasured (G4-10), frequency is regime-dependent (G4-11), executable trades are capacity-bound (G4-08, G4-09). No INCONCLUSIVE outcome is governed; one is PROPOSED (G4-13). CON-44 is a difference of unstated assumption subsets, not of formula (G4-14), and GOV-03 / DR-7 reproduce (G4-15). Details in §6.

**G5: candidate decision matrix ([CANDIDATE_DECISION_MATRIX.md](CANDIDATE_DECISION_MATRIX.md)).** Neither Candidate B nor Candidate C has any attributable repository evidence, and neither has a tracked specification (G5-01 · INFERRED; G5-08, G5-NV-01, G5-NV-02 · NOT_VERIFIED). B is a new strategy version, not a continuation of the deployed setup, and its distinctness from tested hypotheses is low (G5-02, G5-11 · INFERRED). C is meaningfully distinct from Design A but may nest a Design-A-like regime filter (G5-21, G5-22 · INFERRED). Neither is confirmable at a plausible effect size within 365 days (G5-04 · INFERRED). At 0.40% / 0.60% round trip the break-even gross edge is 0.40% / 0.60% per trade, i.e. 0.08R / 0.12R at the 4h stop cap and 0.133R / 0.20R at the 1d cap, more for smaller R (G5-05 · INFERRED). No option dominates between B and C (G5-06, G5-25 · INFERRED). Verdict: **INCONCLUSIVE** (G5-07, G5-27 · INFERRED). Details in §7.

## 6. Statistical feasibility verdict (G4)

**Verdict (G4 bottom line · INFERRED).** The A29 design as governed cannot plausibly distinguish an annualized Sharpe ratio of 0.5–2 from noise within its 365-day maximum horizon. A per-trade net edge of +0.1% to +0.5% is distinguishable only in combinations of low σ, high executable turnover and low dependence that together imply an annualized SR of about 3.5 or more. Whether such combinations apply to any candidate is unknown, because σ, executable n and dependence have not been measured through an authorised route (G4-N2 · NOT_VERIFIED).

| Point | Content | Source |
|---|---|---|
| Alpha | 1/240 per admission = 0.05 / 12 admissions per 3-year program, MAIN and RESERVE alike; calibration level α_cal = 1/276 is not validated | G4-01; G4 §2.2 |
| MDE at 365 days, 80% power | SR 3.48 (normal theory, lrv 1) to 7.00 (A33 envelope plus α_cal shift, lrv 3); 9.04 at lrv 5 | G4-04; G4 §7.1 (ILLUSTRATIVE inputs) |
| Power at true SR 0.5 / 1 / 2 | at most 0.016 / 0.051 / 0.262 (best documented case); 0.003 / 0.014 / 0.115 under the A33 envelope | G4-05; G4 §7.2 |
| Binding constraint | the horizon: even one test at one-sided α = 0.05 has a 365-day MDE of SR 2.49; 80% power for SR 2 needs about 3.0 years, for SR 1 about 12.1 years (lrv 1) | G4-06; G4 §7.3–7.4 |
| Per-trade route | detectable only if (μ/σ)·√n_eff ≥ 3.48–4.04, the same as an implied SR ≥ 3.48–4.04 | G4-07; G4 §7.7 |
| Executable n | ≤ 2 · 8760 · occupancy / mean holding hours; time stops are maxima; mean holding time and occupancy NOT_VERIFIED | G4-08, G4-09 |
| Planning risk | realized n_eff at half the planned value cuts power from 0.80 to 0.43 | G4-11 |
| Outcome vocabulary | no governed INCONCLUSIVE label; a PROPOSED rule (§9) would leave about 95% of 365-day runs INCONCLUSIVE (flagged or not) whether true SR is 0 or 1, at δ_min = SR 1 | G4-13 |
| R0 reconsideration | condition 4 (power over the whole declared range) cannot hold for SR ≤ 2 within 365 days under any documented critical-value mode; conditions 2 and 3 are also unmet today | G4-15; G4 §10.2 |

Insufficient power is not evidence of no edge, and adequate power would not be evidence of an edge (`docs/strategy/EVIDENCE_LADDER_PARAMETERS.md:L157-161 @ 1432a90`, cited by G4 · SOURCE_VERIFIED). All G4 numbers are governance constants or arithmetic on hypothetical inputs; none is an observed variance, turnover, Sharpe ratio or correlation.

## 7. Candidate comparison verdict (G5)

**Verdict: INCONCLUSIVE (G5-07, G5-27 · INFERRED).** Existing evidence cannot resolve Candidate B versus Candidate C. Neither dominates (G5-25): B is better on data availability and engineering effort; C is better on distinctness and governance risk; both are Unfavourable on evidence support and on feasibility under A29 power; cost robustness is Unfavourable for B and Not determinable for C. Choosing between them would require weighting criteria, which is an owner value judgement, not an evidence question.

Under the unchanged 365-day daily-endpoint design, option D in its **pause** form is not dominated on any criterion; D in its **stop** form is not supported, because the record is absence of evidence, not evidence of absence (G5-26 · INFERRED). If that design stays unchanged, G5 records both candidates as "not confirmable by design" (the wording of G4 Q1) and reads D (pause) as the evidence-consistent option for the confirmatory track (G5 §9).

**Ordered owner decisions (G5 §9), none of which is an evidence question:**

| Order | Decision | G4/G5 source |
|---|---|---|
| 1 | Horizon and endpoint (G4 Q1, Q2), the validation design for realistic effects (OD-DF-2), and whether to adopt a preregistered INCONCLUSIVE outcome rule (G4 Q6) | G4 §11; DFP L114 |
| 2 | Dataset permission: OD-DF-1, licence clearance (A18/A19) and a recorded `DatasetPermission` | DFP L42, L113 |
| 3 | Capacity and book design for up to 3 candidates on 2 Paper positions (G4 Q4), and the authorised route to planning inputs σ, n, holding time and dependence (G4 Q7) | G4 §11 |
| 4 | Program slot plan: the disposition of Design A (its E1–E8 gate), whether it serves as a control for C, and the use of the 3-candidate cap and the 12 admissions | G5 §6; G4-01 |
| 5 | Candidate prerequisites. B: which W3 correction (G1-10), the selection rule replacing the alphabetical cut, the timeframe set, a declared version boundary and an identity record beyond the contract hash (G3-08), and at most one of the overlapping refinements (A45 H1–H3, A46 G3). C: a written specification (horizon, regime-filter form, entry, exits, stops, universe, benchmark, filter-isolating control), its hypothesis source and its relation to Design A | G1-09, G1-10, G3-08, G3-09; G5 §5 |

G4 also poses Q3 (alpha allocation) and Q5 (calibration standard), which G5 does not place in its order; see §9 item X-02.

## 8. Verified vs unresolved evidence

**Verified (SOURCE_VERIFIED at named commits, with the scope stated in each file):**
- the rule-change commit `63da7d3` (2026-08-19), its ancestry to `ea8ae4f` and `bb7825f`, and byte-identity of the entry and exit modules from `63da7d3` to the deployed commits (G2-05, G2-09);
- the selection and tracking changes after `63da7d3` (G2-06);
- the W3 cap code and its presence from `d922cfc` through `ea8ae4f`, the dormant `T1_CAP_POLICY` switch absent from `ea8ae4f`, the alphabetical cut from `2d11780` to `eba90dd`, the re-fire cooldown, the double stop-slippage charge and the contract-hash source list (G3 §3–§6);
- the alpha derivation and governed parameters as restated in ELP and `research/power/ladder_power.py @ 1432a90`, read and not run (G4-01, G4 §2.1);
- the HIS-05 engine as committed code (G1 §3) and the current momentum predicates at `ea8ae4f` / `bb7825f` (G1 §4);
- the absence of any tracked specification for Candidates B and C (G1-09, G5-08; absence findings).

**Unresolved (NOT VERIFIED, with blockers):**

| Workstream | Items | Blocker |
|---|---|---|
| G1 | G1-05 run date, code version run, symbol list, per-arm counts and per-year results; G1-06 delisted coverage; G1-07 "wide R:R" and "partial TP" arms; G1-09 successor specification | outputs and symbol list never tracked; arms not in the engine; no successor document exists |
| G2 | timeframes analysed in the HIS-01/HIS-14/HIS-09 windows; version or commit running in each window; HIS-01 exits before 2026-05-16 and partial handling for HIS-09/HIS-14; HIS-14 cost and gross definition; content of the dirty tree at the freeze; any outcome of the current rules | not stated in reports; `.env` untracked and not read; no tracked deployment record for 2026-04 → 08; sealed FORWARD_HOLDOUT |
| G3 | G3-NV-01 image content vs source; NV-02 W3 binding frequency and realized effect before the freeze; NV-03 200-row cut frequency before the freeze; NV-04 database sort collation; NV-05 recomputed contract hash; NV-06 contamination registry content; NV-07 same-bar repeats admitted before the freeze; NV-08 rationale of `ORDER BY symbol` | image hashing needs authorisation (RT-17); counts only from windows not verified pre-freeze; no database access; recomputation would run repository code; JSONL artefact out of scope |
| G4 | G4-N1 A29–A34 original wording and the "excess" reference series; N2 σ, executable n, holding time, occupancy, ICC/deff, lrv; N3 book design for concurrent candidates; N4 annualised counts in A42/A45; N5 DR-8/DR-9 re-derivation; N6 account fee level; N7 runtime behaviour of cooldown and one-per-symbol rule | originals only at unpushed `54a6369` held by OD-1; trade-level data out of scope and post-freeze data sealed (OD-7); count withheld (window not verified pre-freeze) |
| G5 | G5-NV-01/02 what C and B exactly are; NV-03 output of the 1d MA20/MA50 pullback script; NV-04 contribution of HIS-07's BTC regime filter; NV-05 planning inputs; NV-06 4h/1d momentum signal supply; NV-07 degree of C–Design A nesting; NV-08 level-3 execution validity; NV-09 consistency with the A29 originals; NV-10 hypothesis-source registry entries | no specification exists; untracked CSV and JSONL artefacts; no authorised measurement route; originals held under OD-1 |

## 9. Cross-workstream consistency check

The five files were read in full and compared on dates, commit IDs, counts, evidence classes, stated verdicts, and whether any passage implies profitability or authorizes testing. The five files were **not edited**. Where a point could be settled by a read-only `git` command, the check is noted.

**Result.** No factual contradiction between workstreams was found on dates, commit IDs, counts or verdicts. The items below are gaps, framing or precision differences, class-label differences and citation variants. None changes a workstream verdict. This agrees with G5 §12 ("No error was found in G1–G4").

| ID | Type | Observation | Disposition |
|---|---|---|---|
| X-01 | Precision | G2 §3.2 gives the HIS-09 window as exit time ≥ 2026-07-20, run on 2026-08-17 "with no explicit upper bound"; G5 §3.2 writes "Window 2026-07-20 → 08-17" | Read G5's end date as the run date. Both are pre-freeze; no effect |
| X-02 | Gap | G5 §9 orders G4 Q1, Q2, Q4, Q6 and Q7 but does not place G4 Q3 (alpha allocation) or Q5 (calibration standard), although G4 §10.2 shows R0 conditions 2 and 3 depend on them | §7 above and the Arabic brief list Q3 and Q5 after G5's five decisions, unranked, as G4 states them |
| X-03 | Gap, settled here | G3-01 and G3-05 date W3 from `d922cfc` (2026-06-25), which covers the HIS-14 and HIS-09 momentum cohorts; G2 §3.1 lists those cohorts' exit rules without the T1 cap | Checked for this README: `analyzer/technical_analyzer.py` at `d922cfc` (L386-388, L424) and `605a962` (L396-398, L434) contains the same `df.tail(20)` window and a 0.99 resistance factor · SOURCE_VERIFIED. The exact application condition at those commits was not re-read, so W3 self-reference in those cohorts is INFERRED. This strengthens G2-08; no conclusion changes |
| X-04 | Framing | G3 §3.3 calls A46 G1 (`independent_swing_v1`) "the corrected reference"; G1-10 and G5-10 record two documented W3 corrections (A45 L191 and A46 G1), none chosen | G1-10 governs: no correction has been chosen. G3's wording refers to the one that is implemented as dormant code |
| X-05 | Link not drawn | G3-04 dates the double stop-slippage charge from `5792cd3` (2026-07-15), inside the HIS-09 window; G2 §3.2 records HIS-09 costs (0.30% including about 0.1% slippage, plus a 0.1% stop fill) without naming the double count | HIS-09 net figures plausibly carry the same conservative bias on stop exits (direction only, size UNKNOWN · INFERRED). They remain HISTORICAL_REPORTED and non-attributable (G2-08) |
| X-06 | Class label | The ≤ 3 simultaneous-candidate cap and 20% slot-day reserve are SOURCE_VERIFIED in G4 §2.1 (ELP L70-71, OOC L35) but DOCUMENTED_ONLY in G5 §6 | The policy text is SOURCE_VERIFIED as text; its application is a documented rule. No substantive difference |
| X-07 | Different loops | G4 §6.1 cites "one signal per ~60 s cycle" (audit UNI-18); G3 §4.4 cites a 300 s scan interval (VER-07) | They describe the live selection cycle and the scanner interval respectively; not a contradiction, but the two must not be equated |
| X-08 | Range quoted | G5's upstream table and §3.8 quote the 365-day MDE as SR 3.48–7.00; G4-04 also gives 9.04 at lrv 5, outside the calculator's canonical table | Consistent; G5 uses the canonical range |
| X-09 | Cost bases | G1–G4 use the tracker's flat 0.30% (about 0.40% on stop exits, G3-04); G5 uses 0.40% / 0.60% planning values equal to Design A BASELINE / STRESS; OOC §1 sets 0.10% fee per side plus spread and slippage | Reconciled in G5 §7.1 and G5-O4. 0.40% is not the tracker's general charge |
| X-10 | Citation commits | The same files are cited at different commits: A45 at `f95e01d` (G4) and `eba90dd` / `5d977f2` (G1, G3, G5); A42 at `675f7d1` (G4) and `eba90dd` (G3); the roadmap at `23d1d88` (G4) and `5d977f2` (G5); S4 Phase 1 at `f6dcae1` (G4) and `5d977f2` (G1, G5); OOC at `c3bb74c` (G4) and `eba90dd` (G3) | Checked for this README: each file's blob is identical at both commits (the earlier commit is the file's last change). Line numbers are comparable |
| X-11 | Citation lines | The A46 break-even T1 thresholds (0.275% / 0.376%) are cited at L72-79 and L91 by G3 and at L81 by G5 | Both correct: L72-79 is the table, L81 the prose statement |
| X-12 | Verdicts | G5's upstream table restates G1-01/02/09/10, G2-01/07/08, G3-01/02/08/09 and G4-04/06/07/13 | Restated correctly |

**Profitability and authorization check.** No file claims profitability, and none authorizes selection, pre-registration or testing. G1, G4 and G5 state this explicitly. Three passages need careful reading: G4 §6.6 (return-on-capital identities on hypothetical μ and n, labelled ILLUSTRATIVE and "not projections"); G4 §8 and G5 §3.8 ("within arithmetic reach", a conditional arithmetic statement); and G5 §3.1 / §4.1 (general literature, labelled non-repository and disclaimed for this market net of costs).

**Intra-document observations (not cross-workstream):**
- **I-01 (G1).** The method note says the study "ran in 2026-06", while G1-05 marks the run date NOT_VERIFIED. The dating rests on the summary first committed at `3aed157` (2026-06-26) and the `[HR 2026-06-24]` tag; the study's pre-freeze status holds either way.
- **I-02 (G2).** The timeline dates `4f84717` 2026-06-30 (its commit date), while §3.1 says the preference flipped on 06-29 per `docs/canary_state.md:L95`, which dates the switch to 06-29 UTC. Commit date versus event date; no effect.
- **I-03 (G5).** The lower trade bound for C is 13 a year in §4.5 and §4.8 but 12 in §4.7 and the §7.3 table (2 · 8760 / 1344 h = 13.0). Rounding only.

## 10. Process deviations disclosed

- **G3** parsed `research/governance/research_freeze.json` with `python3` only to list its keys.
- **G1/G2:** the writer used one Python string replacement to edit its own output file.
- **Shared self-check:** it initially lacked its register file, so the writers ran identical copies of it.
- **Self-check scope (disclosed for completeness by this README):** the mandated self-check imports the module-level regex definitions of the repository file `ops/provenance/protected_scan.py`; that module's `main` is not invoked. No other repository code was loaded.
- **G4** used Python with the standard `math` module only (scipy was unavailable), on hand-typed numbers, as the brief permits; the repository calculator was read, not run.
- **This README:** the freeze-instant equality (JSON record vs DFP line 57) was checked by shell string comparison on the governance JSON, printing only the date and the match result. All refs were read from local objects; no network command was used.

## 11. Restrictions honoured

As disclosed by the writers and for this README:
- no backtest, simulation, replay, optimisation, calibration or ablation;
- no read of FORWARD_HOLDOUT outcomes, counts or timestamps, and no other protected data; counts from windows not shown to be pre-freeze are written as "count withheld (window not verified pre-freeze)";
- no access to the production database or to logs; no Docker, database-client or network command;
- no repository script or module executed (see §10 for the self-check's regex import);
- no code, configuration or deployment change; no `git add`, commit or push; no other branch changed;
- no merge and no deployment;
- no A29 slot or alpha consumed, and no parameter tuned or selected.

## 12. What this package does not authorize, and the next owner approvals

**Not authorized.** This package does not select a candidate, does not pre-register any hypothesis and does not authorize any test, Paper window, defect correction, measurement or deployment. Its INCONCLUSIVE verdict is a decision state, not negative evidence about Candidate B, Candidate C or any strategy family (G5 §8.2, G4 header).

**Owner approval required next, in G5's order:**
1. Horizon, endpoint, validation design and the proposed INCONCLUSIVE rule (G4 Q1, Q2, Q6; OD-DF-2).
2. Dataset permission (OD-DF-1, licence clearance, a recorded `DatasetPermission`).
3. Capacity and book design (G4 Q4) and the authorised route to planning inputs (G4 Q7; any measurement on the sealed stream needs separate authorisation under OD-7).
4. The program slot plan, including the disposition of Design A.
5. Candidate prerequisites for B and C.
6. Unranked, from G4: alpha allocation (Q3) and the calibration standard (Q5).

Only after those decisions could a candidate be specified, and any selection, pre-registration or test would then need its own explicit owner approval. Activating any defect correction (W3 policy, selection cut, integrity mode) is a declared strategy-version boundary that needs operational approval (G3-09; DFP L63; OOC L36). Verifying running-image content needs authorisation (RT-17; G3-NV-01).

**Status of this package.** The seven files sit uncommitted in the working tree of branch `docs/evidence-resolution-20261031`. Committing, pushing or opening a review of them is a separate owner-approved step; no merge to `main` is part of this phase.
