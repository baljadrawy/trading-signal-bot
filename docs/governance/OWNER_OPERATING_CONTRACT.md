# Trading Signal Bot — Owner Operating Contract

**Status:** APPROVED by owner, consolidated 2026-10-26.
**Purpose:** Single short entrypoint for Claude Code and reviewers. Read this file at the start of every development, research, release or operations task. This is a decision register, not evidence that runtime changes have already been deployed.

## 1. North star

This project is **R&D / PAPER_ONLY**. The goal is to discover and independently validate an economically robust **net-profitable** crypto strategy, not maximize gross signals, apparent backtest returns or procedural activity. No live-money execution, credentials enabling it, or exchange order placement.

Use conservative standard spot fees: **0.10% per side (0.20% round trip)**, independent of account discounts, plus spread, slippage and other realistic execution costs. Report gross and net results, turnover, drawdown, sample sizes, regimes, uncertainty and failure cases. No assertion of profitability without credible prospective independent evidence.

## 2. Workflow — approved 2026-10-26

- **Continuous Development + PR-on-Demand:** `main` is canonical; use only the minimum necessary temporary branch, preferably no branch for ordinary low-risk changes. No automatic Draft PR per task. Relevant CI, security and regression checks still apply.
- Claude Code implements in source files, validates, **pushes the exact candidate commit to GitHub before deployment**, then (only when authorized) builds and deploys from that same commit; no in-container source patching.
- ChatGPT/reviewers assess GitHub commits, tests, documented runtime checks and divergence. Do not claim server parity from GitHub alone. Report **Saved / Integrated / Deployed / Validated** separately and capture deployed SHA, image digests and post-deploy parity evidence.
- **Automatic deployment** only to proven isolated development/lab environments or verified isolated low-risk components after tests, smoke checks and rollback. A shared server, production Compose project or live Paper service is not an isolated lab.
- Live host container deployment, restart, database mutations and Paper strategy activation require their applicable explicit operational approval. A merged commit is not a deployment authorization.
- Deployment blockers must not freeze independent development, and development blockers must not freeze safely authorized operations. External review is advisory for ordinary low-risk R&D development, not a standing gate.
- Existing branches/PRs are consolidated **incrementally** after inventory and verification that unique work and evidence are preserved. No bulk deletion, force-push, secret exposure or history rewrite.

## 3. Paper economic-loss policy — approved 2026-10-26

- During R&D, a negative P&L, consecutive losses, drawdown or low Profit Factor is an **economic observation** to record, alert on and analyze, not by itself an automatic reason to end simulated prospective trade collection.
- Preserve the full historical loss/trade record, strategy version, signals, time, assumptions, execution costs, and failures. No resetting loss counters, backfilling fabricated fills, changing prior outcomes or silently mixing strategy versions.
- Technical data-integrity and operational safeguards remain fail-closed (bad/stale prices, corrupt or missing data, duplicate events, database failures, uncertain service state, explicit administrative stop). If unsafe to generate reliable Paper trades, continue collecting safe market observations only.
- The owner approved **development and tests** to separate economic loss guards (`loss_streak_halt` / `loss_streak_reduce`) from technical halt guards, **not** immediate `/resume`, a forced halt override, restart, live service deployment or technical-safety bypass. Verify actual state from authoritative evidence first.
- Trade-level stop-loss/risk sizing and trading-strategy changes are separate from the research collector's economic-loss stop policy; do not silently remove position controls.

## 4. Strategy research and scientific separation

- Continue the **A45-G REVISE STRATEGY** work, including signal/entry/exit quality, market regime, risk/reward, turnover, net costs and out-of-sample robustness. The earlier gross PF 0.735 on 2,518 Paper trades is historical review evidence, not a current profitability claim.
- Read the existing strategy roadmap (including PR #91), candidate/hypothesis and statistical accounting work (including PR #94), Paper-monitor/recovery work (#87/#89), and related accepted records. Check whether work is merged or still draft; do not treat PR plans as implemented code.
- Keep exploratory, synthetic engineering tests separate from licensed, explicitly permitted historical-data analysis and **governed confirmatory** tests. Protected/sealed holdouts remain sealed; no unauthorized data reads, peeks, alpha consumption or prospective-window changes.
- A29 Evidence Ladder remains in force with **D1/D2 HOLD** for governed confirmation, up to 365-day prospective horizon, max 3 simultaneous candidates, 20% forward capacity reserved, 5% familywise error control; ENCOURAGING is non-confirmatory. No technical shortcut may silently change these decisions.
- Significant Paper strategy changes create explicit version boundaries and require operational approval for activation; never retroactively attribute prior outcomes to a new version.

## 5. Operational safety and precedence

- Never enable live money; keep `PAPER_TRADING=true`. Keep continuous learner stopped unless separately authorized.
- Production Compose safety is governed by `docs/ops/COMPOSE_OPERATIONS.md`: shared host, one-service-at-a-time restrictions, read-only inspection versus owner-authorized operations. No destructive/bulk Compose commands, protected-evidence deletion, or unauthorized production DB writes.
- Per-release successful backup/rollback policy and protected evidence retention remain active; do not delete historical recovery/evidence without named authorization.
- Read `docs/governance/DEVELOPMENT_FIRST_POLICY.md`, `docs/ops/BRANCH_RELEASE_POLICY.md`, `docs/ops/EVENT_DRIVEN_RECOVERY_GOVERNANCE.md` and relevant strategy/science records as needed.
- **Precedence:** Explicit later owner decision for the same subject > this consolidated contract > older conflicting workflow prose. However, a workflow simplification does **not** implicitly repeal production safety, access restrictions, scientific protection or a required operation-specific approval. If records conflict, identify the exact conflict, follow the narrower safety gate and continue independent permitted work; do not hide the conflict.

## 6. Start/finish checklist

At task start: (1) read this contract and `CLAUDE.md`; (2) check latest `main` and relevant documents/PR status; (3) inspect runtime only when needed and authorized; (4) classify ordinary D0, research, isolated deploy or live-host operation; (5) preserve existing work and evidence.

At task finish: provide an Arabic summary with exact changed file paths, GitHub SHA, test/CI outcome, research significance and cost assumptions when applicable, deployed image digest/actual runtime status if applicable, outstanding safety gates and next independent tasks. **Never state that a documentation approval means code has been implemented or containers resumed.**

## 7. Change control

Add a dated owner-decision entry to this contract whenever the owner revises these rules; update `CLAUDE.md` entrypoint and any directly conflicting policy, rather than distributing instructions through chat alone. New decisions must distinguish development authorization from live operational authorization.
