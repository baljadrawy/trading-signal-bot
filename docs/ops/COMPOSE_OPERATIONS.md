# Compose operations: canonical safety runbook

**Status:** mandatory policy for every human and agent operating the production bot.
**Introduced:** 2026-09-30 (S5B hardening), from the S5A Compose safety audit.
**Scope:** project `trading-signal-bot`, production checkout `/home/tradmin/trading-signal-bot`,
single shared host `89.58.35.49`.

This file is the single source of truth for Docker and Docker Compose commands. Any other
document that shows a lifecycle command (`up`, `down`, `build`, `restart`, ...) is either
initial-setup-only, historical, or wrong; this file wins.

## 0. Ground rules
- **Single shared host.** The same Docker daemon runs other projects (the shared `postgres`
  container in project `shared-postgres`, xsch, wishlist, hermes). A careless command can hit
  them. Never use commands that act on "everything".
- **Paper trading only.** `PAPER_TRADING=true` always. The bot is currently fail-closed:
  PAPER_HALTED (B3, `risk:loss_streak_halt`). No operation may lift the halt; recovery follows
  `docs/loss_streak_recovery_runbook.md` and needs the owner.
- **One service at a time.** Never mutate more than one service in one command or one step.
- **The learner (`continuous_learner`) stays stopped.** It is in Compose profile `learner`, so
  default commands ignore it. Starting it needs separate, explicit owner authorization.
- **D3 services are drift-blocked.** `analyzer`, `signal_engine` and `claude_review` differ from
  the Compose definition (environment drift). Recreating any of them applies that drift. They must
  not be recreated until the D3 phase is approved.
- **Pinned images.** `telegram`, `trade_tracker` and `scanner` run the approved aiohttp 3.14.3
  images recorded in `deploy/aiohttp-3.14.3/IMAGES.md` (`image:` + `pull_policy: never`, no
  `build:`). Never rebuild, retag, re-pull or overwrite those tags.
- **Source of truth.** The production `docker-compose.yml` must equal the reviewed Git blob.
  Changes go through a PR, and installing a merged file in production is a separate,
  owner-authorized step with offline hash verification (`config --hash`).
- **Absolute STOP rule.** If anything is unexpected (hash mismatch, unexpected diff, an
  unexpected container ID/image/state change, a failing gate, a secret in output), STOP and
  return to the owner. Do not diagnose-and-continue, do not improvise a workaround.

Common prefix (always explicit project and file; run from the production directory):

```bash
cd /home/tradmin/trading-signal-bot
DC="docker compose -p trading-signal-bot -f docker-compose.yml"
```

Service to container map: `telegram`=`trading_telegram`, `trade_tracker`=`trading_tracker`,
`scanner`=`trading_scanner`, `analyzer`=`trading_analyzer`, `signal_engine`=`trading_signal_engine`,
`claude_review`=`trading_claude_review`, `continuous_learner`=`trading_continuous_learner` (stopped),
`optimizer` (profile `disabled`, not deployed).

## Class A: read-only (always allowed)
No approval needed. Prefer the helper `ops/compose-safe` (read-only, allowlisted, redacts tokens).

| Purpose | Command |
|---|---|
| Status | `docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Image}}'`, `$DC ps`, `ops/compose-safe status` |
| Logs | `docker logs --since 30m <container>`, `$DC logs --since 30m --tail 200 <svc>`, `ops/compose-safe logs <svc>` |
| Inspect | `docker inspect <container>`, `docker image inspect <ref>`, `ops/compose-safe inspect <svc>` |
| Resources | `docker stats --no-stream`, `$DC top`, `$DC images` |
| Render hash | `$DC config --hash <svc>`, `ops/compose-safe render-hash <svc>` |
| Service list | `$DC config --services`, `ops/compose-safe services` |

**Secret warning:** plain `docker compose config` (and `config --format json|yaml`) prints the
fully interpolated configuration, including every `.env` secret, to the terminal. Never run it
unredirected. If a full render is needed, write it only to a private file:

```bash
umask 077; $DC config --format json > "$EVIDENCE_DIR/render.json"   # mode 600, never cat it
```

Compare renders by hash or with a script; never print them. Redact bearer and Telegram bot tokens
from any log excerpt you share.

## Class B: explicit owner authorization + gated procedure
Allowed only after the owner has approved **this specific operation on this specific service**,
following a written, gated procedure (per-rollout script or checklist with an evidence folder).

Operations in this class:
- restart, stop, recreate, deploy or roll back **one** service;
- `docker exec` / `$DC exec` of anything that writes (scripts, migrations, psql writes);
- an intentional learner start (additionally needs its own separate authorization).

Canonical recreate/deploy form (run from `/home/tradmin/trading-signal-bot` only, one service):

```bash
docker compose -p trading-signal-bot -f docker-compose.yml up -d --no-deps --no-build --pull never --force-recreate <svc>
```

Restart without config change: `$DC restart <svc>`. Stop: `$DC stop <svc>`.

Mandatory gates for every Class B step:
1. **Pre-identity capture** into a timestamped, mode-700 evidence folder: container ID, image ID
   and reference, `StartedAt`, `RestartCount`, network IPs, `com.docker.compose.config-hash` label;
   same for every other bot container (to prove they are untouched).
2. **Pre-gates:** PAPER_HALTED/B3 still in force; learner still stopped; the target is not a D3
   service (unless the D3 phase is approved); for recreate/deploy, `$DC config --hash <svc>` equals
   the expected hash and the image is the approved one (`deploy/aiohttp-3.14.3/IMAGES.md` for the
   pinned services, or the rollback tag named in the approved plan).
3. Run exactly one command for one service.
4. **Post-checks:** the target's new identity matches expectations (restart: same container ID and
   image; recreate: expected image and config hash); every other container is unchanged; fresh
   health check twice (healthcheck `healthy` on two consecutive reads, not a cached value) plus a
   log review; PAPER_HALTED/B3 and the stopped learner re-verified.
5. Any deviation: STOP, keep the evidence, return to the owner. Rollback only if it was
   pre-approved as part of the plan.

Rollback = the same canonical form on the exact prior image (a dedicated rollback override or the
rollback tag from `deploy/aiohttp-3.14.3/IMAGES.md`), with the same gates.

**Learner (separate authorization only):** after a D3-style environment review and with a stop plan:

```bash
docker compose -p trading-signal-bot -f docker-compose.yml --profile learner up -d --no-deps --no-build --pull never continuous_learner
```

Note: Docker documents that explicitly naming a profiled service (e.g. `run continuous_learner`)
can activate it without `--profile`. The profile is not a lock; this policy is.

## Class C: forbidden in production
Never run these against project `trading-signal-bot` on this host (no exception without a new,
explicit owner decision recorded in writing):

- bare `up` / `up -d` (no service), or `up` naming several services;
- `up --build`, `build`, or any image build from or in the production checkout
  (`/home/tradmin/trading-signal-bot` is dirty and would become the build context and overwrite the
  `trading-signal-bot-<svc>:latest` rollback tags);
- `down` (removes every bot container and the project network: full outage and D3 drift on return);
- `down -v` / `down --volumes` (additionally deletes the `logs_data` and `models_data` volumes);
- `--remove-orphans` on any command;
- `docker system|image|builder|volume|container|network prune`;
- `pull` of application images (the pinned images are local-only; `pull_policy: never`);
- broad `start` / `stop` / `restart` / `rm` / `kill` without exactly one service;
- `docker run` or `$DC run` that mounts the production working directory (`-v "$PWD:/app"` and similar);
- any command that mutates more than one service at once.

**The learner profile does NOT make bare commands acceptable.** It only removes the learner from
the default model; a bare `up -d` would still recreate the D3 services with drifted environment,
and `down` would still take the whole bot down.

## Initial setup vs production
`setup.sh` and the build steps in `SETUP_GUIDE.md` are for a first install on an **empty host**
only. `setup.sh` refuses to run when any `trading-signal-bot` or `trading_*` container exists.
Development builds happen in an isolated clone with a unique image tag, never in production.

## Automation
Scripts, cron jobs and alerts must never run Class B or C commands automatically. Alerts may
recommend "notify the owner and follow this runbook"; they must not print a copy-paste lifecycle
command. `ops/compose-safe` has no mutation subcommands by design; mutations belong to the
separately authorized, gated per-rollout deployment scripts.
