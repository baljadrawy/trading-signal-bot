# Unsafe Compose commands: remediation note (scoped; NOT fixed here)

Recorded 2026-09-30 with the aiohttp 3.14.3 source-of-truth alignment. It lists existing documented commands that can
recreate, rebuild or start production containers. **Nothing below is changed in this PR.** Repository-wide command
cleanup is a separate, bounded phase, linked to the P0 repository-cleanup item. Line numbers refer to this branch.

## Classification
1. Could revert or recreate services
2. Could start the stopped `continuous_learner`
3. Could rebuild from unpinned source (no lockfiles, so transitive drift)
4. Could affect the D3-drift services (analyzer, signal_engine, claude_review). Their running containers differ from the Compose definition, so any recreation applies that drift.

With this PR's Compose file, telegram, trade_tracker and scanner have no `build:` and use `pull_policy: never`. A build therefore skips them, and a recreation resolves to the pinned 3.14.3 images. Classes 2–4 still apply to the other services.

| Location | Command | Classes |
|---|---|---|
| `setup.sh:25` | `docker compose build` | 3, 4 |
| `setup.sh:52` | `docker compose up -d` (bare) | 1, 2, 4 |
| `setup.sh:60` | `echo docker compose down` (advice) | 1 |
| `SETUP_GUIDE.md:183` | `docker compose down` | 1 |
| `SETUP_GUIDE.md:186,194,444,449` | `docker compose up -d` (bare) | 1, 2, 4 |
| `SETUP_GUIDE.md:189` | `docker compose restart scanner` | same container; low risk |
| `SETUP_GUIDE.md:193,443,448` | `docker compose build` | 3, 4 |
| `SETUP_GUIDE.md:340` | `docker compose down -v && docker compose up -d` | 1, 2, 4, **and destroys volumes** |
| `GIT_GUIDE.md:145` / `:146` | `docker compose build` / `docker compose up -d` | 3, 4 / 1, 2, 4 |
| `CLAUDE.md:14` | `docker compose build --no-cache <service> && docker compose up -d <service>` | 1, 3, 4 |
| `docs/claude/operations.md:6` / `:7` / `:8` | `down` / `build --no-cache` / bare `up -d` | 1 / 3, 4 / 1, 2, 4 |
| `docs/claude/operations.md:11` | `build --no-cache signal_engine && up -d signal_engine` | 1, 3, 4 |
| `docs/claude/operations.md:28` / `:29` | `build` / `up -d --no-build` (no service) | 3, 4 / 1, 2, 4 |
| `docs/canary_runbook.md:31` | `docker compose up -d --build signal_engine` | 1, 3, 4 |
| `docs/canary_runbook.md:73` | `docker compose restart signal_engine` | same container; low risk |
| `docs/canary_state.md:66` | `docker compose up -d signal_engine` | 1, 4 |
| `research/ops/canary_watchdog.py:75` | alert text recommends `docker compose up -d signal_engine` (text only; the watchdog itself only runs `docker inspect`) | 1, 4 |
| `docs/superpowers/plans/2026-06-25-live-learning-collector.md:464,570,766,767` | `build --no-cache …`, `up -d analyzer …`, bare `up -d` | 1, 2, 3, 4 |
| `docs/superpowers/specs/2026-07-15-measurement-layer-fix-design.md:55,113` | `docker compose build/up`, `build trade_tracker && up -d` | 1, 3 |
| `docker-compose.yml:204-205` (comments) | `docker compose up -d` / `up -d optimizer` | 1, 2 |

**Scheduled jobs:** no cron job or systemd unit recreates containers (checked 2026-09-30).

## Proposed safe replacement (for the future cleanup phase)
- Always use a scoped command: `docker compose -p trading-signal-bot -f docker-compose.yml up -d --no-deps --no-build --pull never <service>`, and only under an owner-approved, gated procedure.
- Never use bare `up -d`, `down` or `down -v` in documentation.
- Mark `build` flows as development-only; they never apply to telegram, trade_tracker or scanner.
- Warn that the learner must stay stopped.
- Point to `deploy/aiohttp-3.14.3/IMAGES.md` for the approved images.
