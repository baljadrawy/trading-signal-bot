# Canary — Live State (single source of truth in-repo)

Companion to `docs/canary_runbook.md`. Captures WHAT is live right now, the operational
assets, and how to roll back. Branch: `integration/research-pipeline` (NOT merged to `main`).

## What is live (as of 2026-06-29)
- **Phase A-R2** active on the production server (this machine = Hetzner VPS 89.58.35.49).
- signal_engine running the integration branch code (via bind-mount) + rebuilt image.
- `.env` flags:
  ```
  ENABLE_EVIDENCE_RECORDER=true
  EVIDENCE_FILTER_SYMBOLS=            # empty = all symbols
  EVIDENCE_FILTER_TIMEFRAMES=15m,4h,1d
  EVIDENCE_FILTER_SOURCES=live
  EVIDENCE_FILTER_MAX_SIGNALS_PER_HOUR=20
  EVIDENCE_PHASE_ID=PhaseA-R2
  ```
- Evidence + telemetry → host `./data/evidence/` (NOT git-tracked):
  `_telemetry.json` (ring buffer), `evidence-YYYY-MM-DD.jsonl` (captured records),
  `_telemetry.PhaseA-R1.json` + `_phaseA-R1_conclusion.txt` (preserved A-R1 evidence).

## Why the docker-compose mounts exist (critical)
`signal_engine` bind-mounts `./signal_engine:/app` which SHADOWS the image's COPY'd `research/`.
So `docker-compose.yml` adds:
```
- ./research:/app/research:ro          # recorder package importable at runtime
- ./data/evidence:/app/data/evidence   # evidence/telemetry aligned with monitor_canary
```
Without these the recorder's lazy import fails → degrades to a no-op → ZERO evidence (safe but
useless). They are committed on this branch.

## Operational assets
- Runbook / contract: `docs/canary_runbook.md`.
- Monitor (manual): `research/skill_application/.venv/bin/python monitor_canary.py data/evidence/_telemetry.json`.
- Watchdog (version-controlled): `research/ops/canary_watchdog.py`. The RUNTIME copy cron executes
  is `/home/tradmin/canary_watchdog.py` (kept outside the repo so it survives branch switches).
  Keep the two in sync when editing.
- Cron: `*/30 * * * *` (tag `CANARY_PHASE_A_WATCHDOG`, log `/home/tradmin/canary_watchdog.log`).
  Sends ONE identified Telegram on RED / INVALID / VALIDATED transitions (deduped via
  `/home/tradmin/.canary_watchdog_state` + `/home/tradmin/.canary_validated`).

## States
GREEN (ok) · YELLOW (criteria miss, no rollback) · RED (rollback trigger: dropped>0 /
write_success<99.9%) · INVALID (captured=0 for >12h → sample too sparse) · STALE (telemetry >10min old).

## Rollback (1 step, ~1 min — no code change)
```
# in .env:
ENABLE_EVIDENCE_RECORDER=false
docker compose up -d signal_engine
```
`.env` backups: `.env.bak.precanary`, `.env.bak.ar1`. The recorder is fully isolated and
off-by-default; rollback is a flag flip + restart. No DB migration, no state to unwind.

## Two-layer review (end-of-week — never conflate)
1. **System health**: latency, dropped, flush_success, queue_depth, stability. (instrumented)
2. **Inference validity**: selection bias, policy drift, sample size, null quality. (NOT instrumented)

## Known limitation (do not misread the evidence)
Captured evidence = the bot's POST-FILTER selected `best` signal (after macro-block +
learned_gates throttle + cooldown), and learned_gates adapts during collection. So it is
"what the bot's current policy selects," NOT an unbiased signal universe. A valid edge / Null-A
test (PR#4-era, deferred) would first need: capture the pre-filter candidate pool + freeze
learned_gates during the window. The pipeline-HEALTH reading is unaffected by this.

## Not done yet
PR #4 (wire health monitor + Null-A to collected evidence) — gated on a full paper week of
evidence + the inference-validity analysis, NOT on canary GREEN. Canary GREEN ≠ strategy edge.
