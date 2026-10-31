# Trading Signal Bot — Master Direction & Execution Charter
**Version:** 1.0 | **Approved by owner:** 2026-11-01
**Status:** Approved strategic direction; NOT authorization for protected research, strategy activation, merge, deployment or live trading.
**Repository:** baljadrawy/trading-signal-bot
**Priority:** This charter governs project direction; existing specific scientific, security and deployment controls remain binding. If conflict exists, STOP the affected action and ask the owner; never silently override research governance.

## 1. Binding owner objective
Build an **active, spot-only, long-only, unleveraged, exchange-agnostic** system that scans for opportunities daily **without forcing daily trades**. Evaluate trades for credible **net-of-cost** economics; select strategy-specific entry, exit and holding periods (intraday, swing, position) rather than a fixed duration. Use risk-aware available capital and **compound realized net trading profits** into future position sizing; losses must also reduce sizing. Compounding does not mean external deposits, all-in exposure, or spending unrealized gains as free cash. After robust economic and operational validation, replication into an independently governed environment may be considered, subject to separate approval.

**Non-goals:** daily trade quotas, fixed 14-day holds, mandatory BTC-only scope, SMA200 as sole production strategy, automatic deployment, changing a strategy to improve historical metrics without pre-registration.

## 2. External reviews and scientific decisions: preserve, do not reset
- Independent audit 2026-10-20: **no demonstrated net trading edge**; mixed-version paper evidence (2,518 trades; gross PF ~0.735), walk-forward PF ~1.05, ML no-go. Comparability/version limitations are material.
- External reviewer debate: do not expand infrastructure or fish for strategies without causal economic thesis, reproducible rules, benchmarks, bounded preregistered trials, power analysis, and kill criteria. Of three reviewers, two preferred evidence resolution first and one C preregistration; reviewer vote does NOT select a strategy.
- Design A: BTC/USDT weekly long/cash SMA200, now benchmark or optional hypothesis, NOT the active-trading mandate. B: corrected 4h/1d Momentum breakout. C: regime-filtered trend pullback. No proven winner, and no automatic promotion.
- Comprehensive source audit 2026-10-31 already covered scanner, analyzer, signals, regime, candidate selection, trade geometry, cost, runtime parity and research. **Do not repeat a generic audit.**
- ERG-01 2026-10-31 verdict **INCONCLUSIVE**. HIS-05 nine-year mean-reversion policy is materially different from current Momentum; historical outcomes cannot be reliably attributed to documented deployed implementations. W3 T1 self-reference and alphabetic LIMIT 200 candidate truncation are source-confirmed; realized economic impact UNKNOWN. Same-bar 4h/1d re-fire and stop slippage accounting issues identified. A29 daily portfolio excess/HAC endpoint has low power for modest effects within 365 days under illustrative assumptions. ERG-01 selected, preregistered and tested **no** candidate.
- Never transfer negative results from materially different strategies as proof of failure; never discard relevant negative evidence merely because it is inconvenient. Source-verified is not runtime-image-verified.

## 3. Integrated design: all workstreams together
**A. Opportunity funnel:** point-in-time feed → exchange eligibility/universe → liquidity, spread and volatility → regime → setup → score/rank → execution eligibility → order decision. Document discarded candidates, reasons, freshness, closed candles, same-bar duplicates, alphabetical cut, BTC/regime disagreement, and concentration. Counts from protected data require permission.

**B. Strategy:** Momentum, Reversion, B and C are separate versioned hypotheses. Design A and passive BTC/cash are benchmarks, not mandatory strategy choices. Define rationale, universe, regime, timeframe, entry, thesis invalidation, exit, holding policy, cost and failure criteria **before** tuning. Do not treat arbitrary RSI/EMA/ATR thresholds as proven.

**C. Execution and costs:** validate W3, stops/targets, duplicate signals, closed-candle timing, ambiguous intrabar fills, partial fills, fees, spread, slippage, adverse selection and liquidity. Proposed research baseline **0.40% all-in round trip**, stress **0.60%**, including standard **0.10% fee per side**; do not double count. Keep legacy runtime accounting separate.

**D. Capital and compounding:** reconciled ledger of cash, committed notional, fees, realized and unrealized P&L, equity and available balance. Reinvest **realized net** gains through future risk-based sizing; losses reduce sizing. Define per-trade risk, portfolio heat, correlation, exposure, max positions, reserve, liquidity capacity, minimum orders, drawdown pauses and kill switch. No default percentage or slots becomes policy without owner approval. Unrealized profit is not available free cash.

**E. Traceability:** deterministic decide(state,snapshot) where practical; timestamped closed-candle features, accepted/rejected opportunities and reasons, signal/strategy versions, orders/fills, fees, portfolio snapshots, and source/image/config parity. No economic success claim without attributable comparable evidence.

**F. Replication:** only after validated net performance, operational stability, ledger reconciliation and explicit deployment approval. Immutable artifact, manifest, independent secrets/data/capital and rollback; never replicate experimental state as proven.

## 4. Consolidated remediation register
| ID | Finding | Current evidence | Next action | Gate |
|---|---|---|---|---|
| R1 | Alphabetical LIMIT 200 candidate cut | Source-confirmed; realized impact UNKNOWN | Verify current source; design ranked selection, deterministic tie-breaks and rejection explanations | Strategy selection/version change |
| R2 | W3 momentum T1 uses breakout candle high | Source-confirmed; impact UNKNOWN | Define independent geometry, invariants, tests | Geometry/version change |
| R3 | Same 4h/1d candle re-fire | Source/runtime-mode audit | Idempotent symbol/strategy/candle key and regression tests | Integrity/version change |
| R4 | Stop slippage double-accounting | Mechanism confirmed; realized impact UNKNOWN | Separate accounting from stop-geometry corrections | Geometry gated |
| R5 | Source/runtime/image parity and historical lineage | Not fully verified | Read-only provenance inventory and discrepancy register | No restart |
| R6 | Filter rejection, freshness, ranking transparency | Economic effects unverified | Full funnel specification and safe observability plan | Protected data requires permission |
| R7 | Equity ledger and realized-profit compounding | Owner goal clear; implementation not fully verified | Reconcile existing implementation, design risk/capital contract | No live allocation change |
| R8 | Economic viability of B/C/other active hypotheses | INCONCLUSIVE | Design theses, benchmarks, costs, power options | OD-DF-1/2, owner approval |
| R9 | Backups, runtime health and drift | Previous operational findings | Independent health and safe remediation | No unapproved production actions |

Every item must record evidence reference/commit, OPEN/FIXED/NOT_VERIFIED, dependencies, owner decision, change class, tests, gate and closure proof. Fixing an implementation defect is not evidence of profitability.

## 5. Work packages — advance independent authorized tasks in parallel
- **WP0 — Baseline reconciliation NOW:** current default-branch SHA vs 2026-10-31 audit and ERG-01; deduplicated R1–R9 tracker; no new generic audit.
- **WP1 — Integrated design PARALLEL with WP0:** end-to-end opportunity funnel, strategy interfaces, exit/holding, cost/fills, capital ledger, compounding, risk, telemetry, benchmarks; document contracts, tests and open owner decisions, not parameter optimization.
- **WP2 — Safe remediation:** approved dev-branch changes with deterministic tests, CI and review. Selection/geometry/integrity changes are new strategy-version boundaries. Disabled feature flags do NOT authorize activation, governed experiments or production changes.
- **WP3 — Research decision gate:** explicit owner decision on OD-DF-1 dataset permission, OD-DF-2 endpoint/horizon/power, candidate slots, preregistration and cost/fill model. A29 D1/D2 HOLD; prospective horizon ≤365 days, ≤3 simultaneous candidates, 20% reserved forward capacity, 5% familywise false confirmation. Preserve approved daily mark-to-market net portfolio excess endpoint/HAC L=7, one-sided α=1/240 unless owner formally changes governance. Inadequate power means INCONCLUSIVE, not silent relaxation.
- **WP4 — Authorized evaluation ONLY:** after approval, contamination-aware reproducible pre-registered tests, realistic net costs/fills, dependence-aware uncertainty, protected holdout discipline; report failures and inconclusive findings.
- **WP5 — Operational validation and replication:** separate paper/runtime validation, backup/security/rollback, deployment approval, then independently governed replication after demonstrated success.

## 6. Acceptance and stop conditions
Engineering: correct eligible-symbol selection, no stale or incomplete-bar decisions, no duplicate candle signal, reconciled ledger, correct costs, traceable code/image/config, deterministic tests and recovery. Economics: net expectancy, portfolio return, PF_net, drawdown, turnover, capacity, concentration, exposure, regime stability and uncertainty vs benchmarks. Earlier suggested PF_net >1.15, 90% lower bound >1, DSR ≥0.95 and cluster t >2 are **not** substitutes for approved A29 confirmation; reconcile at WP3. Stop/escalate the affected stream on protected-data boundary, unexpected drift, unversioned strategy change, order/ledger mismatch, inadequate power or missing approval; keep unrelated safe work moving.

## 7. Mandatory anti-drift protocol — for every Claude task and future conversation
Start with **READ THIS CHARTER FIRST** and the governing files below. Every task must explicitly state:
1. Goal alignment: active daily opportunity discovery, net profitability and safe realized-profit compounding.
2. Current branch/SHA and runtime identity confidence.
3. WP0–WP5 and R1–R9 IDs, scope and exclusions.
4. Evidence class: SOURCE_VERIFIED, RUNTIME_VERIFIED, DOCUMENTED_ONLY, HISTORICAL_REPORTED, INFERRED, NOT_VERIFIED.
5. Permission class: read-only / safe dev / strategy-version change / protected experiment / deployment; none implies another.
6. Deliverables, acceptance tests, owner gate and rollback if applicable.
7. **DEVIATION ALERT** before work that changes the objective, treats a different strategy's result as transferable, adds unregistered tuning, forces trades, mandates BTC-only, treats unrealized gains as cash or bypasses A29.

At each milestone update a single decision/remediation log with date, SHA, evidence, decision and open items. Do not silently rewrite this charter. Owner approval required to change goal, risk policy or scientific governance.

## 8. Immediate deliverable
**Consolidated Remediation & Design Pack**, not another generic audit: baseline comparison; deduplicated R1–R9 tracker; opportunity-funnel spec; strategy/exit/cost contracts; equity/compounding ledger; safe engineering branch plan; explicit research decisions pending. Prepare independent work concurrently without protected data, backtests, optimization or deployment.

## 9. Source anchors
- `docs/audits/2026-10-31-trading-system-review/` at `5d977f2f851b952f6fd0de026d9222d2ef092f41`
- `docs/research/evidence-resolution-20261031/` at `0729a5fc99ded3c9eb517c4251670dcbb2b2d6e8`
- `governance/OWNER_OPERATING_CONTRACT.md`, `governance/DEVELOPMENT_FIRST_POLICY.md`, `strategy/EVIDENCE_LADDER_PARAMETERS.md` (verify current SHA)
- Owner direction 2026-11-01: active daily scanning, risk-controlled spot trading, realized-profit compounding, integrated parallel work, reuse external reviewer findings and ERG-01.

**Authority note:** owner approval of this charter approves its direction and documentation. It does NOT approve protected data access, simulation, tuning, strategy activation, merging, deployment or real-money trading.
