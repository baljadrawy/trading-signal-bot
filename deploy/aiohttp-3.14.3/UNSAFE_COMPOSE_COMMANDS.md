# Unsafe Compose commands: remediation note

> **Status 2026-09-30: resolved by S5B** (branch `fix/compose-ops-hardening-20260930`) — see
> [S5B resolution](#s5b-resolution-2026-09-30) below. Canonical policy: `docs/ops/COMPOSE_OPERATIONS.md`.
> The original note is kept unchanged below for the record; its line numbers refer to `develop@99401654`.

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

## S5B resolution (2026-09-30)

Scope: every CRITICAL/HIGH/MEDIUM row of the S5A inventory (`COMMAND_INVENTORY.tsv`, after the manual
correction: CRITICAL 1, HIGH 25, MEDIUM 8), plus the rows S5A reclassified and the deployed watchdog copy.
Line numbers refer to `develop@99401654`. Git-only change: no container, image or production file was touched.

| Location (develop@99401654) | Severity | Finding | S5B status | How |
|---|---|---|---|---|
| `SETUP_GUIDE.md:340` | CRITICAL | `down -v && up -d` | FIXED | Instruction removed; replaced by a warning and a migrations/owner pointer |
| `CLAUDE.md:14` | HIGH | `build --no-cache <svc> && up -d <svc>` | FIXED | Replaced by read-only quick commands and the mandatory Operations Safety section |
| `GIT_GUIDE.md:145`, `:146` | HIGH | `build`, bare `up -d` | FIXED | Replaced by "merge is not deploy" + Class B pointer |
| `SETUP_GUIDE.md:183`, `:186` | HIGH | `down`, bare `up -d` | FIXED | Maintenance block replaced by Class A/B/C summary and read-only commands |
| `SETUP_GUIDE.md:193`, `:194` | HIGH | `build`, bare `up -d` | FIXED | Same block; code update = PR + separately authorized install |
| `SETUP_GUIDE.md:443`, `:444`, `:448`, `:449` | HIGH | `build`, bare `up -d` (x2) | FIXED | "Update code on the server" block replaced by runbook pointer |
| `docs/claude/operations.md:6`, `:7`, `:8`, `:11` | HIGH | `down`, `build --no-cache`, bare `up -d`, build+up signal_engine | FIXED | Replaced by read-only commands and the Class A/B/C policy |
| `docs/claude/operations.md:28`, `:29` | HIGH | `build`, `up -d --no-build` (no service) | FIXED | Replaced by isolated-clone build + Class B deploy wording |
| `docs/canary_runbook.md:31` | HIGH | `up -d --build signal_engine` | HISTORICAL-BANNERED | Banner added; the sentence rewritten as historical with "do not repeat" + runbook pointer |
| `docs/superpowers/plans/2026-06-25-live-learning-collector.md:464,570,766,767` | HIGH | build/up sequences, bare `up -d` | HISTORICAL-BANNERED | Banner only; content unchanged |
| `docs/superpowers/specs/2026-07-15-measurement-layer-fix-design.md:113` | HIGH | `build trade_tracker && up -d` (rollout prose) | HISTORICAL-BANNERED | Banner only; content unchanged |
| `setup.sh:25` | HIGH | `docker compose build` | INTENTIONALLY RETAINED WITH GATE | Initial install on an empty host only; fail-closed guard exits 1 before any build/start if any `trading-signal-bot`-labelled or `trading_*` container exists (or if the check itself fails) |
| `setup.sh:52` | HIGH | bare `up -d` | INTENTIONALLY RETAINED WITH GATE | Same guard |
| `SETUP_GUIDE.md:189` | MEDIUM | `restart scanner` | FIXED | Now a Class B pointer (owner approval, one service) |
| `docs/canary_runbook.md:73` | MEDIUM | `restart signal_engine` | HISTORICAL-BANNERED | Banner; command replaced by "notify owner, Class B procedure" comment |
| `docs/canary_state.md:66` | MEDIUM | `up -d signal_engine` | HISTORICAL-BANNERED | Banner; command replaced by "notify owner, Class B procedure (D3 drift-blocked)" comment |
| `docs/phase3_entry_hypothesis_review_2026-08-17.md:54`, `:57` | MEDIUM | `docker run -v "$PWD:/app"`, `compose run ... continuous_learner` | HISTORICAL-BANNERED | Banner only; content unchanged |
| `research/ops/canary_watchdog.py:75` | MEDIUM | alert text recommends `up -d signal_engine` | FIXED | Text now "notify the owner and follow docs/ops/COMPOSE_OPERATIONS.md (no automatic Compose commands)"; repository source only |
| `/home/tradmin/canary_watchdog.py` (deployed copy, outside Git) | MEDIUM | same alert text | DEPLOYED COPY STILL PENDING | Not touched by S5B; updating it is a separate, owner-authorized host-file step |
| `setup.sh:33` | MEDIUM | `docker start postgres` | INTENTIONALLY RETAINED WITH GATE | Initial setup only (shared DB start is a no-op when running); behind the same guard |
| `setup.sh:60` | MEDIUM (reclassified from HIGH) | echoed `down` advice | FIXED | Replaced by a runbook pointer |
| `deploy/baseline-2026-09-27/README.md:13` | LOW (reclassified mention) | "do not assume `build` reproduces" | OUT-OF-SCOPE | Warning prose, not an instruction |
| `docs/superpowers/plans/2026-07-15-measurement-layer-fix.md:7` | LOW (reclassified mention) | "until an explicit `build/up`" | OUT-OF-SCOPE | Prose; the plan contains no operational lifecycle command, so no banner was added |
| `docs/superpowers/specs/2026-07-15-measurement-layer-fix-design.md:55` | LOW (reclassified mention) | "`build/up` is run by the user" | OUT-OF-SCOPE | Prose (file is bannered anyway for `:113`) |
| `docker-compose.yml:204-205` (comments) | LOW | optimizer comments cite `up -d` / `up -d optimizer` | INTENTIONALLY RETAINED WITH GATE | Left unchanged so the Compose diff stays exactly the one profile line; comments do not affect hashes. Re-enabling the optimizer is owner-only and governed by the runbook |
| Production `/home/tradmin/trading-signal-bot/docker-compose.yml` | — | learner still in the default model until the S5B file is installed | DEPLOYED COPY STILL PENDING | Installing the reviewed file is a separate, owner-authorized S2-style step (offline hashes: all unchanged) |

**Tally (34 CRITICAL/HIGH/MEDIUM rows):** FIXED 21, HISTORICAL-BANNERED 10, INTENTIONALLY RETAINED WITH GATE 3,
DEPLOYED COPY STILL PENDING 0 of the 34 (plus 2 extra rows: the deployed watchdog copy and the production Compose
install). Reclassified/LOW rows listed above: OUT-OF-SCOPE 3, RETAINED WITH GATE 1 (Compose comments).

Structural control added by S5B: `continuous_learner` now has `profiles: ["learner"]` (not started by any default
`up`; config hashes of all 7 services unchanged offline). Read-only helper: `ops/compose-safe`.
