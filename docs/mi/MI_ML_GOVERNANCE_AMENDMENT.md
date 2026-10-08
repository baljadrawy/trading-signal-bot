# Market Intelligence ML — governance amendment (PROPOSED, additive)

**Status:** proposal for owner approval (STOP POINT 1), 2026-10-08. **Phase 0.1 (2026-10-08):** D1 / D2 are
approved *in principle*. That is not authorization to execute any phase. MI-ADR-01…08 text is unchanged; see the
annex.

**What it does.** It adds decisions and changes no earlier decision. It does not edit any existing file:

- `docs/product/DECISION_LOG.md` lives on unmerged PR #3 (`d41f317`; last entry ADR-011).
- The P2 governance entries P2G-ADR-01…10 are already proposed there as ADR-012…021.

Following the same precedent (`docs/p2/ROADMAP_AND_RESEARCH_GOVERNANCE.md` @ `a4b633d`), the entries below are
numbered **MI-ADR-01…08**. They are proposed for verbatim transcription as **ADR-022…029** when PR #3 lands; until
then this file is the reference.

**Owner instruction this implements (2026-10-08).** Start a separate, historical-only Market Intelligence ML research
track, limited to research planning, reproducible offline development and historical evaluation. The instruction
does not authorize:

- production integration or deployment;
- live or Paper decisions;
- risk-policy changes;
- any use of W3.

## Documents reconciled (read, not modified)

| Document | Version | What it says about ML | Effect of this amendment |
|---|---|---|---|
| `docs/product/PROJECT_CHARTER.md` §3C, §4 | `bd9766a` (PR #3) | Track C "Market prediction + risk throttling": predeclared events, baselines first, walk-forward, shadow before influence; MarketRiskAdvisor / RiskPolicyGate are an approved concept, NOT activated | The historical part of Track C becomes executable research; §4 stays NOT activated |
| `docs/product/IMPLEMENTATION_ROADMAP.md` | `bd9766a` | "P2 Research": event labels, neighbour search, simple probabilistic baselines; P5 Shadow ML; P6 RiskPolicyGate; "parallel independent P2 data collection is allowed" | Extends "parallel" to historical MI research only. P5 / P6 / P7 unchanged and gated |
| `docs/product/DECISION_LOG.md` ADR-001, 002, 004, 005, 006 | `bd9766a` | ADR-004 approved direction for probabilistic downside / false-breakout / regime forecasts; ADR-005 risk advice "No activation now" | Implements part of ADR-004 (historical research); ADR-001 / 005 unchanged |
| `docs/p2/ROADMAP_AND_RESEARCH_GOVERNANCE.md` | `a4b633d` | Sequence … Edge/Drift Monitoring → **ML Enhancement** → Live Readiness; each stage separately gated; Hypothesis → Trial → Evidence; no "all 40 features into ML" | **Not** the ML Enhancement stage (see MI-ADR-02). P2G-ADR-05 rules apply unchanged |
| `docs/p2/P2D_ALPHA_RESEARCH_PROTOCOL.md` §3 | `6db8ba5` | Excludes "ML, DL, RL, LLM trading decisions" from P2-D round 1 | **Unchanged.** MI models make no trading decisions and are not P2-D trials |
| `research/governance/w3_holdout_guard.json` | `407dcd2` (P2-G0) | W3 SEALED; model selection, feature selection etc. prohibited before an opening protocol | Unchanged, and extended to market candles inside W3 for MI (MI-ADR-03) |
| P2-A `p2a-contract-v1` / P2-B `p2b-market-v1` | `d517c6a` / `3335228` | W1 < 2026-06-01 ≤ W2 < 2026-08-19T09:33:46Z; post-freeze candle = hard failure | MI reads only these certified W1 / W2 stores |
| P2-C Trial Ledger | `p2_research/ledger.py` (this branch) | Trials registered before running; failed trials persist; periods overlapping W3 = [2026-08-19T09:33:46Z, 2026-10-04T15:26:43.497803Z) refused | MI trials use the same mechanism, in a separate ledger instance |
| P2-F0 v2 | `617cd797` | Adversarial battery for Alpha candidates; verdicts never say PROVEN | Its statistical methods are reused. The battery is not an MI gate (MI-ADR-06) |
| CLAUDE.md / COMPOSE_OPERATIONS / BACKGROUND_EXECUTION | current | Shared-host safety; all research through `research-run` (R1 default); STOP rule | Unchanged; MI compute obeys them (MI-ADR-07) |

## Proposed decisions

| ID | Decision | Status requested | Implementation gate |
|---|---|---|---|
| **MI-ADR-01** | **Historical MI ML research track.** A separate track that implements the *historical-research* part of Charter Track C and DECISION_LOG ADR-004. It may run in parallel with the P2-C → P2-D → P2-X → P2-RM → P2-F pipeline. Initial scope is limited to three predefined forecasting tasks: **T1 downside-risk probability**, **T2 false-breakout probability**, **T3 market-regime identification and transition**. Each task is defined in `MI_ML_RESEARCH_SPEC.md`. | Approve | Each phase of `MI_ML_RESEARCH_SPEC.md` §9 needs its own approval. Task specs are frozen and hashed before any experiment. |
| **MI-ADR-02** | **Relation to existing stages.** MI research is **not** the P2 "ML Enhancement" stage (P2G-ADR-04), **not** P5 Shadow ML, and **not** a P2-D Alpha trial. MI models produce probabilities about market states. They produce no entry, exit, sizing or strategy signal. The P2-D0 §3 exclusion of ML trading decisions is unchanged. Nothing here starts, shortens or reorders any P2 stage. | Approve | — |
| **MI-ADR-03** | **Data and holdout.** Allowed: only certified, pre-freeze public market data (W1 ds-0928; W2 p2b; and any new public-archive acquisition explicitly approved under the P2-B freeze guard). **W3 stays SEALED**, and for MI that includes *market* candles in [2026-08-19T09:33:46Z, 2026-10-04T15:26:43.497803Z), matching the P2-B and Ledger guards. Historical phases do not use forward-Collector data (after W3); it is reserved for a separately approved prospective shadow protocol. No Collector, production database or Paper change. Strategy outcome tables (signals / trades / results) are not MI inputs. W1 and W2 are disclosed as **previously explored** (MI_ML_DATA_INVENTORY §5): no historical result is called a pristine holdout. | Approve | Ledger and data-builder guards fail closed. |
| **MI-ADR-04** | **Pre-registration and integrity.** Every MI experiment is registered before it runs in a dedicated append-only MI Trial Ledger (P2-C ledger code; hypothesis ids `H-MI-…`; located outside the Collector tree). Labels, horizons, thresholds, feature subsets, model classes, splits, metrics and acceptance criteria are frozen and hashed before the first result. Failed, abandoned and negative results persist and are reported. A later version may only add a more conservative verdict (F0 anti-retroactive rule). The P2G-ADR-05 rule applies: no "all features into ML". | Approve | Contract freeze is a separate phase (§9, Phase 1). |
| **MI-ADR-05** | **Outputs are research artifacts only.** No service, Paper process, B3 path or Telegram command reads MI output. There is no `RiskRecommendation` object and no `MarketRiskAdvisor` / `RiskPolicyGate` implementation. The verdict vocabulary excludes PROVEN / VALIDATED / CONFIRMED. Historical skill is reported as "historical evidence; prospective shadow required". | Approve | Tests assert there is no import path from production code. |
| **MI-ADR-06** | **Separate gates stay closed.** Each of the following requires its own explicit owner approval, in this order, and none is implied by any MI result: (a) a prospective **shadow** protocol (forecast logging on forward data, predeclared duration and metrics); (b) **Shadow ML** operation (Charter P5); (c) `RiskRecommendation` / `RiskPolicyGate` (P6); (d) any **Paper** influence; (e) production or live use. | Approve | — |
| **MI-ADR-07** | **Shared-host safety.** All MI computation runs through `ops/research/bin/research-run` (R1 default, admission gates, protected windows, freeze watchdog). It never runs concurrently with G5, F0 v3 calibration or any G6 change. There are no background waiters. A new Python environment or package install is a separate owner decision (dependency policy). | Approve | Compute is authorized per phase. |
| **MI-ADR-08** | **Prior evidence.** The 2026-06 XGBoost / logistic daily-return experiments and the June live-learning system are **prior negative evidence for return / edge prediction**. They are neither a template nor proof that risk-state forecasting must fail. Their data periods count as explored (MI-ADR-03). | Approve | Disclosure carried in every MI report. |

## What does not change

- PAPER_ONLY, PAPER_HALTED/B3 state, the P2-D0 frozen protocol and its exclusions.
- P2-X / P2-RM / P2-F0 contracts, W3 SEALED, and the Collector.
- G5 status and G6 step 3, which stays separate and unapplied.
- Every existing approval boundary.

If a conflict is found later, the safer earlier rule wins and the owner is asked (DECISION_LOG approval model).

## Annex — Phase 0.1 clarifications (2026-10-08; MI-ADR text unchanged)

These clarify how MI-ADR-03 / 04 / 06 are applied. They add no authority.

1. **Evidence classes.**
   - **E1** development evidence;
   - **E2** Historical Locked Evaluation (HLE, 2025-01 → 2026-05) and **E2b** W2 consistency (S-MAJ only): locked
     and pre-registered, but previously explored, so **not pristine and not confirmatory**;
   - **E3** prospective shadow: the only independent evidence, under a separately approved protocol (MI-ADR-06).

   The strongest historical verdict is HISTORICAL_LOCKED_SKILL (`MI_ML_RESEARCH_SPEC.md` §1.2, §5).
2. **Dataset eligibility.** ds-0928 is usable for exploratory research only. Its FAIL certificate is preserved. There
   is a BTC/ETH vs alt split and an alt claim ceiling (`MI_ML_DATA_INVENTORY.md` §6, DS-1…DS-9).
3. **Point-in-time semantics** for all three tasks: close, availability, issuance, actionable time and label window,
   with conservative latencies (`MI_ML_RESEARCH_SPEC.md` §1.1).
4. **Requirement classes.**
   - mandatory integrity (A) → INVALID on failure;
   - statistical thresholds (B), whose final values come only from a synthetic calibration (Phase 1S), never from
     real outcomes;
   - descriptive diagnostics (C).

   Forecasting skill and trading utility stay separate.
5. **Decision statuses** are in the spec §11. "Approved in principle" ≠ approval to start Phase 1, Phase 1S, data
   processing, installation or compute.
