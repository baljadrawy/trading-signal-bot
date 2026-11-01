# Consolidated Remediation and Design Pack (WP0 + WP1)

> **Status: documentation and design only (charter §5 WP0 and WP1, §8).** This pack is the immediate deliverable that the charter names: a baseline comparison, a deduplicated R1–R9 tracker, an opportunity-funnel specification, strategy, exit and cost contracts, an equity and compounding ledger design, a safe engineering plan and the explicit research decisions still pending (`CH:L71-72`). It is not another generic audit (`CH:L16`). Nothing in it was run, measured, simulated or deployed. Correcting an implementation defect is never evidence of profitability (`CH:L46`).

## Authority of this pack

**Owner approval of WP0/WP1 authorizes documentation only.** It does not authorize WP2 implementation, access to protected data, simulation, backtests, tuning or calibration, strategy activation, merging or deployment, and it does not authorize real-money trading (`CH:L3`, `CH:L51`, `CH:L80`). Each later step needs its own owner gate, consolidated in [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md). Disabled feature flags do not authorize activation (`CH:L51`). Integration into `main` is an owner decision outside this pack.

## Document control

| Field | Value |
|---|---|
| Pack directory | `docs/design/remediation-design-pack-20261101/` |
| Working branch | `docs/wp0-wp1-remediation-design-20261101` |
| Base | `main` at `46578aa1ad500456271557be0031d1ca1d826c1b` (46578aa), 2026-11-01 (BL-01 in [BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md)) |
| Audit package | `docs/audits/2026-10-31-trading-system-review/ @ 5d977f2`, branch `docs/trading-system-audit-20261031`, **not merged** (BL-02) |
| ERG-01 package | `docs/research/evidence-resolution-20261031/ @ 0729a5f`, branch `docs/evidence-resolution-20261031`, **not merged** (BL-02); verdict **INCONCLUSIVE** preserved |
| Pack state | written on 2026-11-01; uncommitted on the working branch |
| Governing documents | [charter](../../governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md), [CLAUDE.md](../../../CLAUDE.md), [Owner Operating Contract](../../governance/OWNER_OPERATING_CONTRACT.md), [Development-First Policy](../../governance/DEVELOPMENT_FIRST_POLICY.md), [Evidence Ladder parameters](../../strategy/EVIDENCE_LADDER_PARAMETERS.md) |

Alias: `CH` = `docs/governance/TRADING_SYSTEM_MASTER_CHARTER_2026-11-01.md @ 46578aa`. The other aliases (OOC, DFP, ELP, REP, ADD, ERG, G1–G5) are defined in each document's "Source aliases" table. Unmerged material is cited as `path @ commit` and never linked, because it does not exist on this branch.

## Purpose

The charter asks for one integrated design across all workstreams, built on the 2026-10-31 audit and ERG-01 instead of a fresh audit (`CH:L12-31`, `CH:L48-50`). This pack:
- reconciles current `main` with both unmerged packages and states runtime identity confidence per layer;
- carries R1–R9 as one tracker with evidence, status, change class, tests, gates and closure proof (`CH:L33-46`);
- specifies the opportunity funnel, the strategy, exit, holding and cost contracts, and the capital ledger with realized-profit compounding, as interfaces and invariants, not as tuned parameters (`CH:L20-31`);
- turns the proposed changes into a gated WP2-and-later work plan, with lanes, dependencies and canonical interface names;
- gathers every pending owner decision, maps the WP3 research gate and records the 2026-11-01 log entry and anti-drift check (`CH:L69`).

## Charter alignment statement (charter §7 items 1–7)

1. **Goal alignment.** The pack serves active daily opportunity discovery, net-of-cost profitability measurement and safe compounding of realized net profit, with losses reducing size (`CH:L8`, `CH:L61`). Daily discovery is not daily execution; no trade quota exists anywhere in the pack. Holding periods are strategy-specific, BTC SMA200 is a benchmark or candidate only, and unrealized profit is never free cash (`CH:L10`, `CH:L15`, `CH:L27`).
2. **Branch, SHA and runtime identity.** Branch `docs/wp0-wp1-remediation-design-20261101` from `main` 46578aa. Runtime behaviour is SOURCE_VERIFIED at the documented-deployed commits (`ea8ae4f` for analyzer and signal_engine, `bb7825f` for telegram and trade_tracker); image content parity is DOCUMENTED_ONLY; runtime values are RUNTIME_VERIFIED for 2026-10-31 only; anything later is NOT_VERIFIED (BL-11 and [section 5 of BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md#5-runtime-identity-confidence)).
3. **Scope.** WP0 and WP1 only (`CH:L49-50`), covering R1–R9 (`CH:L36-44`). WP2–WP5 appear only as planned, gated work. Exclusions: no generic re-audit, no protected data, no backtest, simulation, replay, optimisation or calibration, no code, configuration or deployment change.
4. **Evidence class.** Every material claim carries one class from charter §7.4 (`CH:L64`): SOURCE_VERIFIED, RUNTIME_VERIFIED (by citing the audit or its addendum only), DOCUMENTED_ONLY, HISTORICAL_REPORTED, INFERRED, NOT_VERIFIED, or CONTRADICTORY where sources disagree.
5. **Permission class.** The pack itself is read-only documentation. Every proposed change carries exactly one change class: Documentation/design; Safe development-only correction; Strategy-version-changing correction; Protected research or simulation; Production/runtime change. None implies another (`CH:L65`).
6. **Deliverables, acceptance, gates, rollback.** The eight files below. Acceptance for this phase is a clean self-check of each file and owner review. Every proposed change lists its deterministic synthetic tests, acceptance criteria, owner gate and rollback in [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md) and [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md). Rollback for this phase is discarding the uncommitted files.
7. **DEVIATION ALERT.** The anti-drift check across the seven pack documents is in [DECISIONS_AND_GATES.md section 4](DECISIONS_AND_GATES.md). Its result is summarised below under "Anti-drift result".

## The eight files

| # | File | ID prefix | Work package | Content |
|---|---|---|---|---|
| 1 | [README.md](README.md) | — | index | purpose, charter alignment, authority, reading order |
| 2 | [BASELINE_AND_EVIDENCE.md](BASELINE_AND_EVIDENCE.md) | BL- | WP0 | `main` versus audit and ERG-01; branch inventory; evidence inventory and permitted use; runtime identity confidence; what is not re-audited |
| 3 | [REMEDIATION_REGISTER.md](REMEDIATION_REGISTER.md) | R1–R9, sub-items R1.a … | WP0 | the deduplicated R1–R9 tracker: evidence, fix status, consequences, sub-items with change class, tests, dependencies, gates, closure proof, priority tiers P0–P3 |
| 4 | [OPPORTUNITY_FUNNEL.md](OPPORTUNITY_FUNNEL.md) | OF- | WP1 | current funnel trace and silent-drop register; target funnel stages with `RejectionRecord`, eligibility, freshness and ranking; change register OF-T*; funnel owner decisions |
| 5 | [STRATEGY_AND_EXECUTION_CONTRACT.md](STRATEGY_AND_EXECUTION_CONTRACT.md) | SE- | WP1 | strategy hypotheses as separate versioned contracts; `StrategyVersion` identity; geometry invariants including W3; exit and holding policy; cost and fill model; decision traceability |
| 6 | [PORTFOLIO_RISK_AND_COMPOUNDING.md](PORTFOLIO_RISK_AND_COMPOUNDING.md) | PR- | WP1 | reconciliation of current capital handling; target ledger and invariants; risk budget, sizing and realized-profit compounding; owner decisions PR-OD*; changes PR-C*; tests PR-T* |
| 7 | [IMPLEMENTATION_WORKPLAN.md](IMPLEMENTATION_WORKPLAN.md) | WP- | WP1 plan for WP2+ | implementation tasks in parallel lanes; per-task class, files, dependencies, tests, acceptance, gate, rollback; gated items not scheduled; dependency graph and critical path; interface reconciliation |
| 8 | [DECISIONS_AND_GATES.md](DECISIONS_AND_GATES.md) | DG- | WP1 for WP3 | consolidated owner-decision table; WP3 research-gate map; decision and remediation log entry of 2026-11-01; anti-drift check |

## Reading order

1. **This README**, for scope and authority.
2. **BASELINE_AND_EVIDENCE.md**, to know which source, commit and evidence class each later claim rests on.
3. **REMEDIATION_REGISTER.md**, the summary table and priority ordering first, then the item of interest.
4. **OPPORTUNITY_FUNNEL.md**, **STRATEGY_AND_EXECUTION_CONTRACT.md** and **PORTFOLIO_RISK_AND_COMPOUNDING.md**, the three WP1 designs, in that order (funnel, then strategy and execution, then capital), which follows the decision flow of `CH:L21-27`.
5. **IMPLEMENTATION_WORKPLAN.md**. Its interface reconciliation section fixes the canonical names where documents 4–6 diverge; it governs at interface level only and does not edit them.
6. **DECISIONS_AND_GATES.md**, the decisions that unlock each lane and the WP3 research gate.

An owner who wants only the decisions can read this README, then DECISIONS_AND_GATES.md, then the REMEDIATION_REGISTER.md summary.

## Preserved positions

- The 2026-10-20 audit conclusion of no demonstrated net trading edge and the ERG-01 verdict **INCONCLUSIVE** stand (`CH:L13`, `CH:L17`). No document selects, pre-registers or tests a candidate, and none names a winner among Momentum, Reversion, B, C or other hypotheses (`CH:L15`, `CH:L23`).
- Results of materially different strategies are not transferred as proof of failure, and relevant negative evidence is not discarded (`CH:L18`).
- A29 D1/D2 remain on HOLD; the approved endpoint and error rates stand unless the owner formally changes governance (`CH:L52`).
- The charter's proposed research cost baseline of 0.40% round trip, with a 0.60% stress and including the standard 0.10% fee per side, is used for research design only; legacy runtime accounting is kept separate, and the Paper accounting choice remains an owner decision (OQ-08) (`CH:L25`).
- No risk percentage, slot count or other parameter is chosen; each appears as OWNER DECISION REQUIRED with options (`CH:L27`).

## Anti-drift result

The nine mandatory checks (shift away from active opportunity discovery, forced daily trade targets, unjustified BTC-only restriction, fixed holding-period mandate, unrealized profits used as free cash, unregistered parameter tuning, misuse of old strategy results, bypass of research or deployment governance, unnecessary repetition of completed audits) were run line by line over the seven pack documents and this README. Every check is **PASS** for every file, and **no DEVIATION ALERT is raised**. The evidence for each check (file, section and lines) and the notes are in [DECISIONS_AND_GATES.md section 4](DECISIONS_AND_GATES.md). Two of those notes are open owner topics, not deviations: an exposure denominator on mark-to-market equity would loosen percentage caps while sizing stays on realized capital (PR-OD10), and edits to the hash-pinned logic files during WP2 (WP-OD-01). Inconsistencies between pack documents are listed in DECISIONS_AND_GATES.md section 5 and in IMPLEMENTATION_WORKPLAN.md section 11; the canonical interface names are fixed in IMPLEMENTATION_WORKPLAN.md section 8.
