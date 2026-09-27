# Owner Decision Log / سجل القرارات
This is an append-only decision register. Do not silently rewrite approved intent. New proposals belong in IDEA_REGISTER until approved; implementation approvals are separate from conceptual approval.

| ID | Date | Decision | Status | Implementation gate |
|---|---|---|---|---|
| ADR-001 | 2026-09-27 | Preserve PAPER_HALTED, PAPER_ONLY, B3 fail-closed and sealed holdout; no live activation without separate owner approval. | Approved | No restart or deployment authorized. |
| ADR-002 | 2026-09-27 | Prioritize P1 forward instrumentation, independent P2 market intelligence, then paper readiness, prospective data and shadow ML. | Approved direction | P1 branch work only under existing Claude prompt; merge/deploy separately approved. |
| ADR-003 | 2026-09-27 | Defer integration with separate `trading-bot`; keep repositories independent and audit execution mechanics later. | Deferred | No live credentials or order connectivity. |
| ADR-004 | 2026-09-27 | Build historical pattern discovery and probabilistic upside/downside, drawdown, false-breakout and regime forecasts. History is not deterministic. | Approved direction | Data audit, predeclared labels, temporal tests and prospective shadow validation. |
| ADR-005 | 2026-09-27 | Future ML market-risk advice should reduce new positions/exposure under high downside risk; when conditions improve, restore/increase eligible opportunities subject to existing risk limits. | Approved concept | **No activation now**; independent deterministic policy gate, prospective paper tests and explicit owner approval. Above-baseline risk needs separate approval. |
| ADR-006 | 2026-09-27 | Future web command center for operations, trade/pattern/ML review and approvals; Telegram for alerts and limited commands. | Approved direction | Start with reports/Grafana; custom UI after reliable data. |
| ADR-007 | 2026-09-27 | P0 PostgreSQL least-privilege design tested in isolated environment; production rollout deferred. | Deferred rollout | No new SUPERUSER research connections; reassess before paper resumption. |
| ADR-008 | 2026-09-27 | Track future ideas in GitHub with status, rationale, evidence, risks and phase; no scope creep into an active phase without owner approval. | Approved process | See IDEA_REGISTER and CLAUDE.md. |\n| ADR-009 | 2026-09-27 | After Claude's P1 response, review all dependency versions against the latest stable, supported and secure compatible releases available at review time. | Approved direction | Inventory and separate upgrade proposal/PR; ARM64/Python compatibility, reproducible pins, security review and decision parity required; no upgrades to active P1 or production without separate approval. |

| ADR-010 | 2026-09-27 | Development and production share a single host; Git worktrees and disposable containers are logical isolation only, not a separate staging environment. | Owner-confirmed constraint | Post-P1 dependency audit is read-only; no tests/builds or disposable infra without separate approval and host resource/isolation review. See SINGLE_HOST_SAFETY.md. |

## Owner approval model
- **Idea** ≠ approved product direction ≠ authorized code change ≠ approved deployment ≠ authorized paper restart ≠ authorized live trading.
- Each ADR change must link a dated owner decision, impact on risk/strategy, acceptance tests and rollback.
- Claude and contributors must read PROJECT_CHARTER, DECISION_LOG and IDEA_REGISTER before proposing scope changes.
- For an unresolved conflict, preserve the safer current behavior and ask the owner; do not silently reconcile old documents.
