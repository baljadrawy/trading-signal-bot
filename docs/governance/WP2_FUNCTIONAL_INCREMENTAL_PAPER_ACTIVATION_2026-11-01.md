# Owner decision — Functional incremental Paper activation (2026-11-01)

**Status: APPROVED as the development and staged-activation method.** This supersedes WP2 dormant-only delivery and blanket deferral of activation until WP2 completion. It does **not** grant blanket authorization to deploy, restart services, change shared PostgreSQL, access protected research, or activate any particular strategy change.

## Objective
Develop improvements directly in the existing trading-signal-bot, verify them, activate a small coherent functional increment on the running **Paper-only** bot when its specific gates are met, observe its live operational effects, then accept, correct or roll back before proceeding. No multi-week accumulation of inactive changes without seeking runtime feedback. Do not mistake more signals for economic improvement.

## Functional order
1. **Opportunity discovery and signal generation:** Scanner → Analyzer → Signal Engine, including R1 selection, evidence-based R2 diagnosis, funnel observability, eligibility, macro context, closed candles and downstream compatibility. Deliver smaller activatable increments within this phase; telemetry and behavior-changing selection must be gated separately.
2. **Signal integrity and delivery:** setup identity, no unintended re-fire, freshness, deduplication and reliable downstream handoff. DG-35 and DG-71 HOLD remain binding.
3. **Trade tracking and execution economics:** cost/slippage accounting (R4), exits, stops, targets, and position state; do not rewrite historical Paper evidence.
4. **Portfolio and risk:** ledger, capacity, position sizing, realized-net compounding and reconciliation.
5. **Evaluation:** monitor operational and net economic performance by immutable strategy/version boundary; no unapproved protected experiments or holdout access.

## Mandatory increment cycle
1. Capture authorized read-only baseline and deployed source/image/config identity; verify parity.
2. Implement the smallest coherent change in existing services, with focused regression and synthetic/integration tests.
3. Independently review deployable code before activation; document evidence, known limitations and rollback.
4. Prepare exact affected service(s), dependency/blast-radius assessment, strategy-version boundary, config/flag values, monitoring metrics, success/failure criteria and rollback commands.
5. Obtain **specific owner authorization for the particular Class B shared-host operation** under COMPOSE_OPERATIONS.md. Owner approval of this *method* is not that authorization. Use one service at a time and preserve backup/recovery governance.
6. Activate only the approved increment on Paper, verify health and source/runtime parity, and observe live signals, rejects, errors, latency and downstream effects with version-separated evidence.
7. Accept, fix or roll back based on evidence; proceed to the next functional increment. Continue unrelated safe development while an approval is pending.

## Non-negotiable controls
- PAPER_ONLY, spot long-only; no live-money execution.
- Preserve A29 Evidence Ladder, D1/D2 HOLD, protected holdouts, hash-pinned research contracts and freeze records.
- No silent strategy or economics changes; no historical evidence mutation or cross-version P&L mixing.
- Separate Implemented, Integrated, Tested, Independently Reviewed, Merged, Deployed, Activated and Runtime-Validated in every report.
- Never claim runtime improvement from tests alone. If no real Paper events occur during an observation window, report **insufficient runtime evidence**, not success.
- Do not block all source development for a single operational gate, but do not bypass that gate.

## Immediate instruction to Claude Code
Continue current WP2 work, starting with the **smallest safe, independently reviewable Phase 1 increment**. Implement and test authorized changes now, prepare a specific activation request, and seek live Paper feedback as soon as the applicable review, version and operational gates are satisfied. Avoid repeated general audits and excessive architecture. The repository and current runtime evidence remain the source of truth.

**Owner approval:** in conversation, 2026-11-01.
