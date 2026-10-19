# S5-PWR-1: candidate status register and owner decisions

**Scope.**
- Planning record only.
- It admits, rejects, confirms or allocates nothing.
- It leaves the S1–S6 roadmap (`docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md`) and every HOLD unchanged: A34-VS1, MI Stage B, B2, P2-D1, Paper R2, D1–D5, and all governed experiments.

Parameters and discrepancies are in `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md` (DR-*). Numbers below come from `research/power/` (`s5-pwr-1-v2`) with the scenario stated. Every number is **illustrative until validated** (OD-5). No protected, research-exposed or historical outcome was read to produce them.

## 1. Candidate status register (provisional, OD-6)

**Statuses:**
- **DEFERRED**: plausibly testable later, once named prerequisites exist.
- **CURRENTLY_INADMISSIBLE**: under the documented assumptions it would be underpowered or lacks a mechanism argument. It is **not rejected**, and it can be reconsidered when the criteria are met.
- **NOT_A_CLAIM**: an engineering correction that makes no performance claim.

**Insufficient power is not evidence of no edge.** None of these statuses is a statement about whether an edge exists, and none is permanent.

**Common reconsideration gate (R0).** It applies to every power-based criterion below. A screen result can support reconsideration only when `reconsideration_eligible` is `True`, which requires **all** of:
1. the daily HAC endpoint (`unit = "daily_hac_sharpe"`), never the illustrative per-trade arithmetic;
2. a governance-confirmed alpha scenario, never a SUPERSEDED or unresolved one;
3. a critical value that has passed independent validation (none has: OD-5, DR-6);
4. status `POWER_AT_OR_ABOVE_TARGET_UNDER_STATED_ASSUMPTIONS` for the **whole** declared effect and dependence range. A range that only reaches the target at its upper end (`POWER_VERSUS_TARGET_DEPENDS_ON_ASSUMPTIONS`) never qualifies.

The declared range must have a written source (literature, mechanism arithmetic or a frozen spec), never protected or research-exposed outcomes. Meeting R0 only allows the owner to reconsider. It **never authorizes an admission** or alpha use.

| Candidate | Source (main) | Provisional status | Why (documented assumptions only) | Reconsideration criteria (plus R0 where power-based) |
|---|---|---|---|---|
| Current 15m/4h momentum + reversion family, as an S5 claim | A42-B, A45-B/C, A46-C | CURRENTLY_INADMISSIBLE (stays the Paper baseline arm) | Economic design concerns: 15m fee burden 0.22–0.43 R per trade, T1 hit rate ≥ 0.81–0.96 needed (A46-C), horizon mismatch with the literature (A45 W1). No declared effect size exists | A written mechanism argument at the family's own horizon; a sourced daily effect range meeting R0; costs measured through an approved route |
| A42 C1 cost-coverage gate | A42 l.238–239, l.282 | CURRENTLY_INADMISSIBLE | Documented effect below its MDE (0.13 %/trade iid, before DEFF 2–3), and its sign is theoretically ambiguous | A sign argument; a sourced daily effect range meeting R0 at a design effect obtained through an authorized route (OD-7) |
| A42 C2 correlated-exposure (beta) cap | A42 l.255 | DEFERRED | A risk-control validation (variance or non-inferiority endpoint), not an alpha claim. This calculator does not model variance endpoints | A preregistered power analysis for its own endpoint |
| A42 C3 funding / crowding | A42 l.266 | DEFERRED | Needs a data licence and contract; effective n is the number of funding episodes | Licence cleared (A18/A19), data contract approved, episode-count power analysis |
| A44 ranking (`execution_quality_v2`, `cost_per_risk_v1`) | A44 l.168–180 | DEFERRED | Power unknown until the contested-cycle rate is measured on the `enforce` stream; A44 expects underpowered | Enforce window running (separate approval); contested-cycle rate measured through an authorized route; paired power analysis meeting R0 |
| A45 H1 market-state momentum | A45 l.138, l.158 | CURRENTLY_INADMISSIBLE | Effective n = number of regime episodes, too small within 365 days | A design whose effective n is not episode-bound, or an explicit episode-count power analysis meeting R0 |
| A45 H2 extension cap, **or** A46 G3 (same mechanism; test at most one) | A45 l.166–174, A46 l.152 | DEFERRED | Illustrative per-trade arithmetic only: MDE ≤ 0.2 %/setup (A45 l.173) holds only if the design effect is ≤ **2.09** (NORMAL_THEORY, α_cal 1/240) or ≤ **1.55** (A33 envelope + α_cal shift). A45 assumed 3–10. The stated 0.12 % base does not reproduce (DR-8) | Enforce-era setup rate and design effect obtained through an authorized route (OD-7); an instrument decision (A48 D1–D4); one of H2/G3 chosen; a daily-endpoint analysis meeting R0 |
| A45 H3 slot-adjusted volume | A45 l.138 | DEFERRED | Needs a new data contract | Data contract approved; power analysis meeting R0 |
| A46 G1 T1-cap correction | A46 l.150 | NOT_A_CLAIM | A declared correction version with no performance claim (A46). Any claim that it *improves* returns needs an admission | Owner wiring and version-boundary approval (S2/S6) |
| A46 G2 gate | A46 l.151 | CURRENTLY_INADMISSIBLE | Small affected share; documented "inadequate" | A larger affected population or a better-powered paired design meeting R0 |
| S4 alternative families | roadmap S4 | NOT SPECIFIED | No family chosen; licence decisions pending | Owner chooses a family (roadmap S4 entry) |

The H2/G3 thresholds are reproduced by `max_dependence_for_mde(unit="per_trade_illustrative", target_mde=0.2, sigma=1.5, n1=6400/3, n2=6400*2/3, power=0.8, ...)`. They are per-trade arithmetic and **cannot by themselves satisfy R0**.

## 2. Owner decisions (recorded 2026-10-19, from the owner's review instruction for PR #58)

| ID | Status | Decision | Effect on this package |
|---|---|---|---|
| OD-1 | DECIDED | HOLD publication of the raw A29–A34 documents until U1/U3/U4 are classified | None imported; cited by commit, blob and SHA-256 only (parameters doc §1) |
| OD-2 | DECIDED | Do not assume uncertain source material is safe | Nothing from U1/U3/U4 is quoted. Protected material is not inspected to resolve them; they remain unresolved |
| OD-3 | DECIDED | Keep 1/240 and 1/276 as explicitly labelled scenarios, not a newly approved calibration standard | Scenarios `A33_EQUAL_1_240_CAL_1_276` and `A33_OWNER_ALTERNATIVE_CAL_1_240` keep non-binding statuses |
| OD-4 | DECIDED | Document verified precedence and discrepancies without rewriting historical governance | Discrepancy register DR-1..DR-13; source documents unedited; superseded scenarios kept for labelled comparison only and refused by the screen |
| OD-5 | DECIDED | Critical-value calculations remain illustrative until calibration is independently validated | Every result has `illustrative_until_validated = True`, enforced by the result classes; `certified_bound` is always `None` |
| OD-6 | DECIDED | Candidate states are provisional; no permanent rejection | §1 statuses are provisional, with reconsideration criteria and gate R0 |
| OD-7 | DECIDED | No access to sealed-stream counts or timestamps without separate authorization | Design-effect functions take synthetic inputs only here. Any real cluster counts need a separate authorization |

**Still open:**
- the classification of U1, U3 and U4;
- the alpha calibration standard (OD-3 leaves both scenarios labelled);
- independent validation of any critical value (A34-B `a34-vs1`, separately approved).

## 3. Reproducibility evidence

```
python -m research.power.ladder_power            # deterministic canonical table (stdout only)
python -m pytest -q -p no:cacheprovider tests/test_s5_pwr1_ladder_power.py tests/test_s5_pwr1_remediation.py
```

The CI default suite runs both test files. The PR records the commit, the canonical-table SHA-256 and the CI run ID.
