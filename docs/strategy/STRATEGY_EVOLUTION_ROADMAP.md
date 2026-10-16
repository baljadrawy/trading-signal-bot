# Strategy Evolution Roadmap

**Living document.** Owner-approved structure (A46). It records *what* must be true before each strategy step, not when. There are no dates and no profitability targets.

## Ground rules (apply to every workstream)

- **Production baseline:** `59297305`, schema 9. It is the comparison arm for every change.
- **Hard boundaries:**
  - experimental logic is pure, versioned and disabled, and production code never imports it (`tests/experimental_modules.py`);
  - no real historical backtests, protected outcome reads, outcome-based parameter selection, prospective trials or budget use without a separate approval;
  - push, merge, deployment, migration and service restart are separate owner approvals.
- **Costs:** 20 bps round-trip fee baseline (0.10 % per side). Spread, slippage and other execution costs are modelled **separately**. The tracker's 0.3 % flat accounting is reported beside it, never instead of it.
- **Evidence classes:**
  - **engineering** (tests);
  - **economic plausibility** (arithmetic and literature);
  - **exploratory** (research-exposed; never confirmation);
  - **prospective confirmation** (Evidence Ladder only: ≤ 365 days, ≤ 3 simultaneous candidates, 20 % reserve, FWER 5 % over 12 admissions, α = 1/240 each);
  - **deployment readiness** (owner).

  Synthetic profitability is never evidence of an edge.
- **Labels for findings:** CONFIRMED IMPLEMENTATION DEFECT / ECONOMIC DESIGN CONCERN / RESEARCH HYPOTHESIS / INSUFFICIENT EVIDENCE.
- **Current HOLDs (unchanged):** A34-VS1, MI Stage B, B2, P2-D1, Paper R2, D2–D5.

## Completed foundation (do not redo)

| Work | Branch / commit | Contribution |
|---|---|---|
| A38 Paper execution integrity | `fix/a38-paper-execution-integrity` `fb1d40e` | durable entry orders, defer ≠ attempt, alerted dead letters, economic labels, fill-model guard |
| A42 signal quality | `feature/a42-signal-quality` `675f7d1` | live decision map; cost/R; exit-path payoffs; counterfactual replay (`a42-cf-bar-v1`); C1–C3 specs |
| A43 signal integrity | `feature/a43-signal-integrity` `7fd18fe` | same-candle re-emission, duplicate executions, stale signals, cooldown fail-open, selection biases verified |
| A44 integration candidate | `feature/a44-integration` `eb68e42` / `4375c94` | A38 + A43 wired behind `SIGNAL_INTEGRITY_MODE` (off by default); migration 011; source-level compatibility matrix; ranking spec |
| A45 setup research | `feature/a45-setup-research` `f95e01d` | production setup map; 25-source literature review; W1–W14; H1–H3 specs; H2 protocol; REVISE STRATEGY |
| A46 roadmap + geometry | `feature/a46-trade-geometry` | this roadmap; `shared/trade_geometry.py` (`a46-tg-v1`); G1–G3; A46 report |

---

## S1 — Strategy Diagnosis

| Field | Content |
|---|---|
| Objective | Know exactly what the active setups do, why each entry should have positive expected net value, and where the logic contradicts its intent |
| Evidence / completed | A42-A/B (live path); A43-A (decision path, defects); A45-A/B/C (setups, literature, W1–W14); A46-B (full geometry audit) |
| Open questions | Is there *any* horizon or universe where the current momentum trigger has economic support (A45 W1)? How large is the regime-dependence (W6) once integrity is enforced? |
| Deliverables | an up-to-date setup map (A45-A + A46-B); a classified weakness register (A45-C + A46-E); setup explanation tooling (`setup_diagnostics`) |
| Dependencies | none (source and literature only) |
| Entry | always open |
| Exit | every active rule has a stated mechanism, a classification and a falsification route |
| Scientific gates | none (diagnosis makes no edge claim) |
| Risks | treating hypotheses as causes; data snooping from repeated looks (A45 #15) |
| Approvals | none for source-level work; any outcome look needs separate approval |
| Independent progress | yes |
| HOLD | any analysis that uses protected outcomes |

## S2 — Trade Geometry Engineering

| Field | Content |
|---|---|
| Objective | Entry, stop and target geometry with explicit cost and risk assumptions that is internally consistent across setups and TFs |
| Evidence / completed | A42 exit-path payoffs; A45 W2/W3/W7; **A46**: geometry audit, exact per-leg ledger, break-even requirements, G1–G3 (disabled), 30-scenario validation |
| Open questions | Is the 25/50/25 + break-even design economically coherent at small R (A46-C: it needs ≳ 81 % T1 hits for the T1 path alone)? Should targets be R-multiples or volatility- or structure-anchored? |
| Deliverables | `shared/trade_geometry.py` (baseline parity + alternatives); a G1 correction spec as a **new strategy version**; one coherent geometry candidate (A46-E) |
| Dependencies | S1 (done for the current setups) |
| Entry | open |
| Exit | a single versioned geometry proposal with a frozen rule and an evaluation route |
| Scientific gates | geometry changes alter Paper behaviour. A **correction** (G1) needs a declared version boundary; an **economic change** (G3) needs S5 admission before any claim |
| Risks | multiple-testing burden from many geometry variants; selecting by outcomes; counterfactual bias |
| Approvals | owner for any wiring, version switch or deployment |
| Independent progress | engineering, synthetic tests, specs |
| HOLD | activation of any alternative; evaluation on outcomes |

## S3 — Signal Selection Quality

| Field | Content |
|---|---|
| Objective | Select among eligible setups on economically relevant, decision-time information; control dependence |
| Evidence / completed | A43 selection-integrity analysis; A44 staged pipeline, frequency-neutral rankers (`execution_quality_v2`, `cost_per_risk_v1`), ranking research spec; A42 C2 beta cap |
| Open questions | the real rate of contested cycles (≥ 2 ranked candidates) under `enforce`; correlation structure of simultaneous candidates |
| Deliverables | measured contested-cycle rate (after A44 enforce); a decision on whether ranking is worth one admission |
| Dependencies | **S6: A44 deployed with `enforce`**; counterfactual calibration (S5 prerequisite) |
| Entry | A44 enforce window running |
| Exit | the ranking spec either admitted or deferred, based on a measured power analysis |
| Scientific gates | one admission at most (A44-E) |
| Risks | ranking changes are invisible without counterfactuals; slot substitution effects |
| Approvals | owner (A44 deployment); S5 admission |
| Independent progress | pipeline and diagnostics engineering |
| HOLD | activating any ranker |

## S4 — Alternative Strategy Development

| Field | Content |
|---|---|
| Objective | Independent strategy families with a credible mechanism at their own horizon |
| Evidence / completed | A45-B: crypto momentum evidence is strongest at days–weeks in liquid large caps; intraday shows momentum *and* reversal. A42 C3 funding-crowding spec. Internal history: no post-fee edge in 40+ price-indicator studies (context only) |
| Open questions | which mechanism: daily time-series momentum, funding / basis crowding, or something else? This is **not** decided in favour of daily trend-following; each candidate needs its own mechanism argument |
| Deliverables | at most one written family spec at a time: mechanism, literature-fixed parameters, universe, sizing, exits, cost model, baseline comparison, falsification |
| Dependencies | S1 conclusions; data-licence decisions (A18/A19 Vision terms; funding data for C3) |
| Entry | owner chooses the family to specify |
| Exit | a frozen spec ready for S5 design review |
| Scientific gates | the spec must not be fitted on research-exposed data; historical data may be used for qualification only, under separate approval |
| Risks | importing equity daily evidence to crypto; capacity and illiquidity; licence restrictions |
| Approvals | owner (family choice, data licence) |
| Independent progress | literature and spec drafting |
| HOLD | any backtest or outcome-based selection |

## S5 — Scientific Evaluation

| Field | Content |
|---|---|
| Objective | Governed, prospective confirmation of at most a few pre-registered changes |
| Evidence / completed | Evidence Ladder and FWER design (A29–A33); protocols drafted: A42 C1–C3, A44 ranking, A45 H2, A46 geometry candidate |
| Open questions | power: every drafted refinement has an expected effect at or below its MDE (A42/A44/A45/A46) |
| Deliverables | **prerequisites first**: (1) counterfactual replay calibrated against tracker polls (paired-difference bias ≈ 0); (2) measured signal rates and day-clustering design effect; (3) **one** pre-registered admission |
| Dependencies | S6 (A44 enforce window); counterfactual calibration |
| Entry | prerequisites met **and** owner authorises an admission |
| Exit | final-look decision per protocol |
| Scientific gates | α = 1/240 per admission; final look only; no pooling across declared windows; weaker standards are never adopted to rescue power |
| Risks | spending alpha on underpowered tests; counterfactual model bias; regime drift |
| Approvals | owner per admission and per budget |
| Independent progress | calibration harness engineering (synthetic), power-analysis code |
| HOLD | **all** governed experiments, A34-VS1 / MI budgets |

## S6 — Controlled Deployment and Monitoring

| Field | Content |
|---|---|
| Objective | Move verified engineering into Paper safely, with evidence separation |
| Evidence / completed | A41 recovery rehearsal; A44-F deployment sequence; A44 source-level compatibility matrix |
| Open questions | **image-level validation of A44** (build the images and run the 3 telegram-image-only tests); production lock contention at migration time |
| Deliverables | verified images; fresh verified recovery point; migrations 010 → 011; per-service recreate with `SIGNAL_INTEGRITY_MODE=off`; then `enforce` as a declared window; health and evidence monitoring |
| Dependencies | owner approvals; a fresh verified recovery point (not mere file existence) |
| Entry | owner approves each step |
| Exit | integrated candidate running; post-change Paper window declared |
| Scientific gates | every behaviour change is a new Paper window; never pool across windows |
| Risks | partial deployment states (tested source-level only); stale in-flight signals at cutover |
| Approvals | image build; recovery point; migrations; each service; enforce activation |
| Independent progress | runbook refinement only |
| HOLD | everything operational until approved |

---

## Dependency summary

```
S1 ──► S2 ──► (geometry candidate) ─┐
S1 ──► S4 ──► (family spec) ────────┤
S6: A44 images → recovery point → migrate → services(off) → enforce window
                                    │
S5 prerequisites: counterfactual calibration + measured rates ◄─ enforce window
                                    ▼
S5: one pre-registered admission (owner) ──► S6 deployment of the confirmed change
S3 depends on the enforce window and S5 prerequisites
```

**Critical path to any scientific claim:** A44 image validation → enforce window → counterfactual calibration → power analysis → one admission.
