# Implementation Roadmap / خطة التنفيذ
**As of 2026-09-27.** This roadmap documents intent, not authorization to run services, migrate production or trade.

| Phase | Work | Exit gate |
|---|---|---|
| P1 | Forward instrumentation: candidate IDs, append-only decision events, rejected geometry, no-trade/macro cycles, B3 admission, Telegram refusals, NO_FILL, quality/reconciliation. | Frozen strategy decision parity; complete isolated tests; review before merge/deploy. |
| P2 | Historical snapshot audit and independent forward market collector; PIT macro/breadth/liquidity coverage and Parquet/DuckDB as-of research layer. | Document gaps, lineage, coverage and quality; no sealed-holdout access. |
| P2 Research | Define and label drawdown/rally/breakout/regime events over predeclared horizons; historical neighbor search; simple probabilistic baselines. | Time-purged walk-forward evaluation; independent episode counts; reproducible artifacts. |
| P3 | Paper readiness: B3/risk recovery tests, operational monitoring, data quality, P0 risk review, backup and failure drills. | Owner separately approves any paper restart. |
| P4 | Prospective paper observation and prediction shadow logging. | Predeclared duration, quality and risk gates; independent outcome measurement. |
| P5 | Shadow ML for regime, historical similarity, downside/upside and candidate quality. | Calibrated, prospective benefit over baselines; no production decision influence. |
| P6 (future) | Versioned `RiskRecommendation` + deterministic `RiskPolicyGate`; first shadow counterfactuals, then owner-approved paper A/B or sequential evaluation. | Demonstrated net risk-adjusted benefit, stable failure modes, explicit owner activation. |
| P7 (future) | Web command center/ML Lab and operator approval workflows. | Secure authorization, auditability and reliable underlying data. |
| Separate future track | Execution-bot integration/live gateway. | Separate architecture review, execution parity, safety/reconciliation and explicit live authorization. |

## Phase-change rules
- Complete and verify the current phase before expanding scope; parallel independent P2 data collection is allowed if it does not change production.
- Research data/labels from old strategy versions may inform **market studies**, not train a current-strategy trade-quality model without policy-version controls.
- High predicted downside: proposed reduction in *new* trade count/stake/exposure; high predicted upside: proposed restoration of suppressed opportunities within existing caps. Both are **advice only** until P6 approval.
- Failure of ML or missing/stale context must never weaken B3, resume halted paper, or enable live trading.
- Record every new idea in IDEA_REGISTER and every owner-approved change in DECISION_LOG before modifying the roadmap.

## Dependency modernization checkpoint (owner-approved 2026-09-27)
After Claude delivers the P1 report, inventory actual service dependencies and verify the latest stable supported compatible releases **at that date**. Follow [DEPENDENCY_POLICY](DEPENDENCY_POLICY.md). Keep upgrades in a separate branch/PR from P1 instrumentation; test ARM64 compatibility, B3 and strategy parity, security and rollback. Do not silently upgrade production, restart services or resume paper trading.

## P1 delivery checkpoint — reported 2026-09-27
Claude reports `feature/forward-instrumentation@23dea904a852` implemented and pushed (22 changed files), with 999 passed/3 skipped in both recorder modes and 24 Telegram-environment tests. GitHub confirms the branch and changed files; **independent test reproduction, rebuilt-image validation, owner merge approval and deployment are still pending**. The branch is default-off; production paper trading remains HALTED. The additive `analysis_data.pit` and `features_snapshot.identity` JSON changes should be reviewed as distinct from the recorder toggle. V1 remains active for comparison until v2 forward data and backup/retention are validated. See [initial post-P1 dependency inventory](DEPENDENCY_AUDIT_2026-09-27_INITIAL.md) and [dependency policy](DEPENDENCY_POLICY.md).

## Single-host constraint (owner-confirmed 2026-09-27)
Development and production share one host; do not call disposable containers an independent staging environment. Post-P1 dependency audit is read-only and must not install, rebuild, test under load or touch running services. Any future isolated test/build on the shared host requires a separately approved resource-bounded plan with unique networks/ports/volumes, synthetic data, verified host headroom and rollback. See [single-host safety](SINGLE_HOST_SAFETY.md).
