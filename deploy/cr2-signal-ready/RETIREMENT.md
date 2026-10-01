# CR-2: claude_review runtime retirement

A **provenance record**, not an execution script. Recorded 2026-10-01.

## Why it is safe to retire
- Production cutover to the Option 3 contract completed and was verified on 2026-10-01: PR #8 code, deployed through PR
  #9 images (`deploy/cr2-signal-ready/IMAGES.md`).
- The active path is signal_engine → `signal.ready` (decision_source `policy_ready`) → telegram → trade_tracker.
- No deployed service produces `signal.created`, and no deployed service depends on claude_review's process or heartbeat.
- Compose has no `depends_on` on it.

## What this change does
- **Removes the `claude_review` service from `docker-compose.yml`**, with its build definition, environment
  (`ANTHROPIC_API_KEY: ""`, `SERVICE_NAME`, `HEALTH_MAX_AGE_SECONDS`), `.env` exposure and Claude credential bind mounts:
  - `/home/tradmin/.claude` → `/home/appuser/.claude` (ro);
  - `/home/tradmin/.claude.json` → `/home/appuser/.claude.json` (ro).
  - No other service's rendered configuration or config hash changes.
- **Removes `claude_review` from `ops/compose-safe` `SERVICES`.** The helper now refuses it as an unknown service.
- **Updates the runtime documentation:** `CLAUDE.md` and `docs/ops/COMPOSE_OPERATIONS.md`.

## What it deliberately keeps
- **The stopped container.** It is not removed by this change; removing it needs separate owner authorization. Once
  the service leaves Compose, Compose may list it as an orphan. **Never use `--remove-orphans`.**
- **Its image:** `trading-signal-bot-claude_review:latest` = `sha256:8bca25750c77ae2ab5921fd89e35decf050a8ccf11f73d0226fdeec5272b4aa5`.
- **The `claude_review/` source and its tests.**
- **Historical data:** the DB columns (`claude_approved`, `claude_comment`, `decision_source`), the historical
  `signal.reviewed` events and decisions, and every migration.
- **Volumes**, including the shared `logs_data`.
- **Shared credentials in `.env`.**
- **Legacy compatibility:** telegram and trade_tracker still accept `signal.reviewed` + `claude_approved` (dual-accept),
  so a rollback needs no code change.

## Stopped container at retirement

| Field | Value |
|---|---|
| Container ID | `5c726c57e0a0fa72bcf67f2dbf934a990415a8023dad059904172234ad365234` |
| Image ID | `sha256:8bca25750c77ae2ab5921fd89e35decf050a8ccf11f73d0226fdeec5272b4aa5` (`trading-signal-bot-claude_review`) |
| Config fingerprint (sha256 of Config, HostConfig, Image, Name and Mounts) | `1dbf00c75c41b3cb53b1c9bb3001b6c3e71d55fa62da40b5a34b4bf84b44be4f` |
| Compose config-hash label | `0812a3468dd8d160d20e0cb3d2e20bb97144cbe6f48ec0d485236663df9d81c4` |
| Created | 2026-08-17T16:56:53Z |
| Last started | 2026-09-29T12:06:38Z |
| Stopped | 2026-10-01T11:28:40.856Z (exit 143, D3C-R1); restart count 0 |
| Restart policy | `unless-stopped`. A stopped container stays stopped across daemon restarts. |
| Mounts | volume `trading-signal-bot_logs_data` → `/app/logs` (rw); the two Claude credential binds above (ro) |
| Environment | 43 variable names, from `.env` plus image defaults. Values are not recorded here. |

## Rollback
Each level needs owner authorization and the gated Class B procedure.
1. **Undo the Compose retirement:**
   - reinstall the pre-retirement Compose file (blob `6dc227b490247cccc1a519fcc762ce90e4bdfca8`, develop `a5ce42d7`);
   - check `config --hash claude_review` = `df1bee38709227ec…`.
2. **Re-activate the legacy relay without recreating it:**
   - `docker start trading_claude_review` starts the same container with the same config;
   - this only works while the container has not been removed.
   - If it has been removed, recreate the service from the step-1 Compose file using
     `--no-build --pull never`. The preserved image `trading-signal-bot-claude_review:latest` is used.
3. **Restore the old contract:**
   - pin signal_engine back to `tsb-aiohttp-test-signal_engine:3.14.3-20260929T124120Z` and recreate only signal_engine,
     so `signal.created` is emitted again;
   - claude_review then relays `signal.reviewed`;
   - the CR-2 telegram and trade_tracker images accept that path unchanged.
