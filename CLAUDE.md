> **2026-09-27 GOVERNANCE OVERRIDE — READ FIRST:** [Product Charter](docs/product/PROJECT_CHARTER.md), [Decision Log](docs/product/DECISION_LOG.md), [Idea Register](docs/product/IDEA_REGISTER.md), [Implementation Roadmap](docs/product/IMPLEMENTATION_ROADMAP.md). This file contains historical statements about active live learning that are STALE: current bot is PAPER_HALTED, retired learner/optimizer are OFF, and live trading is FORBIDDEN. Owner-approved product direction is NOT approval to implement, deploy, resume paper, modify B3, or connect live execution. Record all new ideas in IDEA_REGISTER and owner decisions in DECISION_LOG before scope changes. The separate trading-bot integration is deferred. Preserve safety and ask owner when in doubt.

# CLAUDE.md — Trading Signal Bot development contract

**Read first (authoritative owner-approved product direction, 2026-09-27):**
1. [Product Charter](docs/product/PROJECT_CHARTER.md)
2. [Decision Log](docs/product/DECISION_LOG.md)
3. [Implementation Roadmap](docs/product/IMPLEMENTATION_ROADMAP.md)
4. [Idea Register](docs/product/IDEA_REGISTER.md)

Older README, docs/claude/live-learning.md and strategy-history documents may describe superseded operations. **Do not treat old "live learning", daily auto-optimization or active paper trading claims as current.** If old docs conflict with the owner-approved charter, stop and surface the conflict instead of silently changing strategy or scope.

## Current hard gates
- PAPER_TRADING = **HALTED** under B3 fail-closed controls; PAPER_ONLY; LIVE_TRADING = **FORBIDDEN**.
- No /recover_risk, /resume, production deploy, migration, restart, funded exchange keys or live orders without separate explicit owner approval.
- No auto-training, optimizer reactivation, model promotion or use of the sealed holdout for new research. Previously viewed post-freeze results do not qualify as pristine independent validation.
- P1 instrumentation must preserve current scanner/analyzer/signal_engine decisions, indicator weights, macro gates, fill/exit simulation and B3. Test decision parity.
- P0 least-privilege PostgreSQL design passed isolated testing; **production rollout is deferred**. Do not introduce new research processes using the cluster SUPERUSER account.
- Separate `trading-bot` execution integration is deferred. Do not connect or modify its real-money execution.
- Future ML downside/upside and historical-pattern predictions are approved **research direction**. Any risk throttle is shadow-only until independent prospective validation and owner approval. B3 limits may never be bypassed.
- **Ideas and decisions:** Add every new proposal to IDEA_REGISTER (or linked GitHub Issue) before implementing; add owner-approved decisions to DECISION_LOG; update roadmap and charter as necessary. Do not conflate conceptual approval with code/deployment/trading approval.

## Working discipline
- Check actual GitHub HEAD and deployed versions; do not assume they match. Use isolated feature branches and targeted staging, never `git add -A`.
- Prefer synthetic isolated PostgreSQL and offline datasets. Do not expose credentials, tokenized URLs, production data or private security reports in Git.
- No `docker compose up -d` without naming the specific service; this can start deliberately stopped components.
- Database settings such as optimizer_settings/indicator_weights may override .env; verify current deployed state read-only before proposing a change.
- Closed candles only and point-in-time feature availability; no future information in research features.
- Each phase requires tests, reproducibility manifest, performance/latency evidence, rollback plan and owner review before merge or deployment.

## Existing technical references (historical/current relevance must be checked)
- [Architecture](docs/claude/architecture.md)
- [Database](docs/claude/database.md)
- [Operations and Telegram](docs/claude/operations.md)
- [Troubleshooting](docs/claude/troubleshooting.md)
- [Strategy history](docs/claude/strategy-history.md)
- [Edge research foundation](docs/edge_research_foundation.md)
- [Development log](DEV_LOG.md)
