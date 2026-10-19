# S5-PWR-1: candidate status register and owner decisions

**Scope.**
- Planning record only.
- It admits, rejects, confirms or allocates nothing.
- It leaves the S1–S6 roadmap (`docs/strategy/STRATEGY_EVOLUTION_ROADMAP.md`) and every HOLD unchanged: A34-VS1, MI Stage B, B2, P2-D1, Paper R2, D1–D5, and all governed experiments.

Parameters and discrepancies are in `docs/strategy/EVIDENCE_LADDER_PARAMETERS.md` (DR-*). Numbers below come from `research/power/` with the scenario stated. No protected, research-exposed or historical outcome was read to produce them.

## 1. Candidate status register (proposed; pending owner decision OD-6)

**Statuses:**
- **DEFERRED**: plausibly testable later, once named prerequisites exist.
- **CURRENTLY_INADMISSIBLE**: under the documented assumptions it would be underpowered or lacks a mechanism argument. It is **not rejected**, and it can be reconsidered when the criteria are met.
- **NOT_A_CLAIM**: an engineering correction that makes no performance claim.

**Insufficient power is not evidence of no edge.** None of these statuses is a statement about whether an edge exists.

| Candidate | Source (main) | Proposed status | Why (documented assumptions only) | Reconsideration criteria |
|---|---|---|---|---|
| Current 15m/4h momentum + reversion family, as an S5 claim | A42-B, A45-B/C, A46-C | CURRENTLY_INADMISSIBLE (stays the Paper baseline arm) | Economic design concerns: 15m fee burden 0.22–0.43 R per trade, T1 hit rate ≥ 0.81–0.96 needed (A46-C), horizon mismatch with the literature (A45 W1). No declared effect size exists | A written mechanism argument at the family's own horizon; a declared effect range that screens POWERED or INDETERMINATE under the latest scenario; costs measured through an approved route |
| A42 C1 cost-coverage gate | A42 l.238–239, l.282 | CURRENTLY_INADMISSIBLE | Documented effect below its MDE (0.13 %/trade iid, before DEFF 2–3), and its sign is theoretically ambiguous | A sign argument plus a declared effect ≥ the MDE at a **measured** design effect |
| A42 C2 correlated-exposure (beta) cap | A42 l.255 | DEFERRED | A risk-control validation (variance or non-inferiority endpoint), not an alpha claim. This calculator does not model variance endpoints | A preregistered power analysis for its own endpoint |
| A42 C3 funding / crowding | A42 l.266 | DEFERRED | Needs a data licence and contract; effective n is the number of funding episodes | Licence cleared (A18/A19), data contract approved, episode-count power analysis |
| A44 ranking (`execution_quality_v2`, `cost_per_risk_v1`) | A44 l.168–180 | DEFERRED | Power unknown until the contested-cycle rate is measured on the `enforce` stream; A44 expects underpowered | Enforce window running (separate approval); measured contested-cycle rate; paired within-cycle power analysis |
| A45 H1 market-state momentum | A45 l.138, l.158 | CURRENTLY_INADMISSIBLE | Effective n = number of regime episodes, too small within 365 days | A design whose effective n is not episode-bound, or an explicit episode-count power analysis |
| A45 H2 extension cap, **or** A46 G3 (same mechanism; test at most one) | A45 l.166–174, A46 l.152 | DEFERRED | MDE ≤ 0.2 %/setup is required (A45 l.173). This holds only if the measured design effect is ≤ **2.09** (NORMAL_THEORY, α_cal 1/240) or ≤ **1.55** (A33 envelope + α_cal shift). A45 assumed 3–10. The stated 0.12 % base does not reproduce (DR-8) | Enforce-era measured setup rate and design effect; an instrument decision (A48 D1–D4); one of H2/G3 chosen |
| A45 H3 slot-adjusted volume | A45 l.138 | DEFERRED | Needs a new data contract | Data contract approved; power analysis |
| A46 G1 T1-cap correction | A46 l.150 | NOT_A_CLAIM | A declared correction version with no performance claim (A46). Any claim that it *improves* returns needs an admission | Owner wiring and version-boundary approval (S2/S6) |
| A46 G2 gate | A46 l.151 | CURRENTLY_INADMISSIBLE | Small affected share; documented "inadequate" | A larger affected population or a better-powered paired design |
| S4 alternative families | roadmap S4 | NOT SPECIFIED | No family chosen; licence decisions pending | Owner chooses a family (roadmap S4 entry) |

The H2/G3 thresholds are reproduced by `max_dependence_for_mde(unit="per_trade_illustrative", target_mde=0.2, sigma=1.5, n1=6400/3, n2=6400*2/3, power=0.8, ...)`. They are illustrative per-trade arithmetic, not the governed daily test (DR-11).

## 2. Owner decisions required (only items that cannot be resolved independently)

| ID | Decision | Options | Why it is needed |
|---|---|---|---|
| OD-1 | Publish the A29–A34 governance documents to GitHub? | (a) publish verbatim after rulings OD-2; (b) publish with documented redaction of U4 (and U1/U3 if ruled protected); (c) keep local only | The roadmap cites them as binding, but they are unreviewable on GitHub (DR-12). Import was **blocked** here under "do not publish if uncertain" (parameters doc §1.1) |
| OD-2 | Rule on U1, U3 and U4 | U1/U3: are synthetic governed-validation verdicts protected? U4: is the P2-X1 tier spread table forward-collector data (protected) or not? | Resolves OD-1 |
| OD-3 | Calibration level | α_cal = 1/276 (A33; certified bound ≈ 4.35 %) or the A33 owner alternative α_cal = 1/240 with tolerance 1.15α (certified bound 5.75 %, stated as such) | DR-2. The calculator keeps both as named scenarios until decided |
| OD-4 | Mark the superseded A30/A31 rules (half-weight reserve alpha, OBF looks, Ljung–Box gate, elapsed-day reserve rule) as superseded in the governance record | confirm / reject | DR-1, DR-3, DR-4, DR-5. The original documents stay unedited |
| OD-5 | Planning standard for critical values | normal theory (optimistic), or the A33 interpolated envelope, until the A34-B validation (`a34-vs1`, separately approved) is run | DR-6, DR-7. No value is binding until validated |
| OD-6 | Accept the candidate status register (§1) | accept / amend | The statuses are proposals; none is permanent |
| OD-7 | Sealed-stream policy for outcome-free design-effect inputs | count/timestamp-only reads of the post-freeze stream permitted, or only a fresh enforce-era capture | `deff_upper_bound()` needs cluster sizes only, but where they may come from is a governance question |

## 3. Reproducibility evidence

```
python -m research.power.ladder_power            # deterministic canonical table (stdout only)
python -m pytest -q -p no:cacheprovider tests/test_s5_pwr1_ladder_power.py
```

The CI default suite runs the same test file. The PR records the commit, the canonical-table SHA-256 and the CI run ID.
