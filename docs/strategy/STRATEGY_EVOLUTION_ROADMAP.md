# Strategy Evolution Roadmap

**Living document.** Owner-approved structure (A46). It records *what* must be true before each strategy step, not when. There are no dates and no profitability targets.

## Ground rules (apply to every workstream)

- **Production baseline:** `59297305`, schema 9. It is the comparison arm for every change.
  *Dated note (2026-10-20):* stale. The deployed release is A56.5 `ea8ae4f` (schema 11, `deploy/a561-rel-ea8ae4f/`). Activity classes and approvals: `docs/governance/DEVELOPMENT_FIRST_POLICY.md` (proposed). The "no real historical backtests" boundary stays in force; a change is proposed there as OD-DF-1. S4 planning: `docs/strategy/S4_MECHANISM_COMPARISON.md` (Draft PR #60). G1 as a flag defaulting to current behaviour: Draft PR #59.
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
| Deliverables | **prerequisites first**: (1) counterfactual replay calibrated against tracker polls (paired-difference bias ≈ 0) — **A48: met for `tracker_event_v1` given observations (27/27 exact); bar-only counterfactuals use `ohlc_uncertainty_v1` conditional intervals, whose use is a design-review decision**; (2) measured signal rates and day-clustering design effect; (3) **one** pre-registered admission |
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

---

## Progress log

### A47 — Execution realism & replay calibration (`feature/a47-execution-realism`, `b94c59f`; report `docs/a47/A47_EXECUTION_REALISM.md`)

**Delivered:**
- `shared/execution_calibration.py`: tracker poll model, held equal to the **real** tracker on 6/6 paths;
- `shared/exchange_rules.py`: Binance Spot filters, conservative rounding, dust;
- the cost-overlap analysis.

**Calibration status:**
- 0 unexplained discrepancies;
- **the replay prices stops at the level while the tracker prices them at the first observed poll beyond it, so the replay is optimistic by the overshoot**;
- entry-on-touch, expiry timing, intrabar gaps and arrival-order processing are classified model differences.

**Execution assumptions in force:**
- `observed_price_v0` only;
- no tick or lot rounding in Paper;
- flat 0.3 % accounting (it double-counts slippage on stop exits, which is conservative and unchanged).

**Remaining realism gaps:**
- the replay's stop-fill policy (next step);
- poll cadence;
- real order-book and queue data;
- live filter values.

**Dependencies:**
- **G1/G2/G3, A45 H2 and candidate ranking all depend on a corrected replay stop-fill policy plus re-calibration.** Real-data calibration additionally needs an owner-approved forward capture.
- **Replay ready for scientific design: NO.**

**Decision:** REVISE EXECUTION MODEL.

### A48 — Replay fidelity & cost accounting (`feature/a48-replay-fidelity`; criteria `a7b21da`, code `92c0553`; report `docs/a48/A48_REPLAY_FIDELITY.md`)

**Replay versioning** (`shared/replay_execution.py`, `a48-rx-v1`):

| Mode | Version | Role |
|---|---|---|
| `legacy_bar_v1` | `a42-cf-bar-v1`, unchanged | regression only; its stop fills are optimistic |
| `tracker_event_v1` | `a48-tev-v1` | the Paper tracker's decisions on ordered observations; engineering reference, not exchange truth |
| `ohlc_uncertainty_v1` | `a48-ohlc-v1` | research default for bars: feasible path branches plus conditional fill intervals, never a point value; `INSUFFICIENT_INFORMATION` when bounds are not defensible |

**Now calibrated (levels 1–2):**
- Mode 2 equals the **real** tracker on 27/27 deterministic scenarios across entry, stops, partials, expiry, stream deduplication, restarts, candle invalidation, rounding and min-notional.
- Five A47 tracker-model gaps were fixed, including the candle-invalidation exit, stream id deduplication and the admission boundary.
- Mode 3 contains the full-information tracker outcome in 100 % of seeded cases where its assumptions hold, and it widens monotonically as bars coarsen.

**Cost convention** (`a48-cost-v1`):
- fees at 0.10 %/side on executed notional;
- spread separate;
- slippage realized once, inside the execution price;
- the 0.1 % allowance is a **stress** adjustment;
- the legacy A38 flat-0.3 % label is reproduced exactly and reconciled term by term.

**Still uncertain (level 3 not established):**
- the real poll cadence and latency, which A_OBS_IN_BAR depends on;
- queueing and partial fills;
- spread;
- live filters.

Synthetic bias rows show the legacy replay is optimistic by speed × ½ poll + gap whenever the exit reason agrees. It can be **pessimistic** when a target and the stop share a bar. Neither is a market-frequency estimate.

**Finding for the owner:** the tracker books a NaN price at expiry as a NaN-P&L BREAKEVEN row. This is latent (Binance never sends NaN). A guard is recommended; it is not applied. **A49:** fixed on the development stack (`fix/a38` `f3104c2`, merged into A44–A48). Not deployed.

**Implications:**
- **G1 / G2 / G3 and A45 H2:** counterfactual evaluation must use Mode 2 (needs recorded observation streams, which needs owner approval of a forward capture) or Mode 3 (conditional intervals). Legacy-replay numbers from A42–A46 that involve stop exits are optimistic and must not be reused as evidence.
- **G1 as a correction version is unaffected:** it is a geometry fix, not an evaluation.
- **Before any scientific evaluation**, a design review must decide three things:
  1. the input route (observation capture vs bars);
  2. whether A_OBS_IN_BAR is acceptable without a measured cadence;
  3. how conditional intervals enter a protocol — stress end as a sensitivity bound, never an expectation.

  The FWER budget, α = 1/240 per admission and the 365-day horizon are unchanged. No admission is recommended.
- **Shortest path back to strategy quality:**
  1. a design-review decision on (1)–(3);
  2. return to S2 / S3 signal and geometry work, using `ohlc_uncertainty_v1` for engineering diagnostics and the A46 ledger with `a48-cost-v1` for costs.

  No further replay infrastructure is planned unless the review asks for it.

**Decision:** READY FOR SCIENTIFIC DESIGN REVIEW.
