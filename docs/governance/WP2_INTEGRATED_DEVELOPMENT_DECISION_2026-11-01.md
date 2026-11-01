# Owner decision — integrated development in the existing bot (2026-11-01)

**Status: APPROVED for source-level integrated development.** This decision supersedes the WP2 implementation preference for creating dormant libraries that cannot be integrated until a later phase. It does not supersede scientific, data-protection or shared-host operational controls.

## Intent
The existing trading-signal-bot is the development target. Improve its actual code paths, not a replacement bot or a parallel infrastructure stack. Implement fixes in place, wire tested modules into the existing services, and validate end-to-end behavior in development. Use versioned, reversible changes, with clear strategy-version boundaries when decisions or economics change.

## Authorized by owner
- Change existing source and service integration code, tests, configs for development, and documentation; keep the repository as source of truth.
- Replace unnecessarily dormant scaffolding with direct integration where safe, including opportunity selection, signal integrity, cost accounting, portfolio ledger and observability.
- Use deterministic unit/integration tests, disposable synthetic fixtures, CI and isolated development containers.
- Commit and push small reviewable development changes under existing Git policy. Continue independent work when a specific gate blocks another task.
- Record exactly what is Implemented, Integrated, Tested, Merged, Deployed and Runtime-Validated. None implies the next.

## Important distinction: current host
The owner describes the bot as in R&D and using the same environment for prior development. However, current repository records describe a **shared running host**, a live Paper service, shared PostgreSQL and other projects. R&D status alone does not prove isolation. Accordingly:
- **Isolated disposable development containers** without shared/live DB, protected datasets, production secrets or live service dependencies may be started/restarted for development testing, with rollback and cleanup.
- **Existing running/shared-host bot containers, live Paper paths, shared PostgreSQL, on-host builds, learner and service restarts/recreates remain subject to COMPOSE_OPERATIONS.md and explicit operation-specific authorization.** Do not treat this decision as blanket Class B approval.
- Before proposing any host action, identify the exact host, container/service, DB dependency, blast radius, rollback and required gate. If a truly isolated dev environment cannot be established, continue source integration and local/synthetic testing, and present the minimal specific operational request.

## Preserved scientific and safety gates
- PAPER_ONLY; no real-money trading.
- A29 D1/D2 and all protected holdout/research restrictions remain binding.
- No production database writes, resets, historical evidence mutation or unapproved data access.
- Hash-pinned research contracts and freeze records remain unchanged unless separately approved; version boundaries must be explicit.
- Strategy behavior changes may be developed and tested with synthetic inputs, but activation on the running Paper path requires the appropriate owner/version/operations decision.
- No learner activation, automatic release or claim of profitability.

## Implementation priority
1. Fix R1–R4 directly in existing decision paths, subject to pinned-file/version gates; avoid changing active selection/strategy behavior without the separate activation decision.
2. Integrate transparent rejection/funnel observability and identity/provenance.
3. Integrate cost and portfolio accounting with reconciliation, avoiding double-counting and using realized-net profits only for compounding.
4. Test integrated flows and prepare the scientifically governed strategy-evaluation stage. Do not extend WP2 indefinitely for low-value architecture.

## Required Claude Code behavior
Read this decision, the master charter, OWNER_OPERATING_CONTRACT.md, DEVELOPMENT_FIRST_POLICY.md and COMPOSE_OPERATIONS.md before every WP2 execution. Prefer direct integration into the existing bot; do not generate standalone dormant modules as the default deliverable. If an old WP2 task says 'no production imports' or 'dormant only', treat it as superseded **for development source integration only**, not as permission to deploy/activate. Report remaining approval gates precisely and never silently bypass them.

**Decision owner:** project owner, in conversation, 2026-11-01.
