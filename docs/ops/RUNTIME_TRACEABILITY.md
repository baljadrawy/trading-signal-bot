# Runtime-to-repository traceability (R1.1, observed 2026-10-18)

> **R1.3 policy proposal (2026-10-18):** [EVENT_DRIVEN_RECOVERY_GOVERNANCE.md](EVENT_DRIVEN_RECOVERY_GOVERNANCE.md) makes the existing drift checker an on-demand development/merge/deployment/handover governance gate, **not** an independent scheduled monitor. Any earlier hourly/daily scheduling suggestions below are historical and not authorized. Production remains unchanged.

**Purpose:** make GitHub the auditable record of what actually runs, without making the runtime follow the latest source.
- Every statement here is a **read-only observation** (Class A) against `main@a2d7592`. It is not a certification.
- Re-verify with the commands in section 6.
- The sealed release record (`deploy/a561-rel-ea8ae4f/`) is referenced, never edited.

## 1. Three different things, never to be conflated

| Term | What it is | Today |
|---|---|---|
| **Source HEAD** | A Git commit: `main` (canonical) or the production checkout | `main@a2d7592`. The production checkout is `integration/research-pipeline@63da7d3`, with 8 modified and 308 untracked files |
| **Image revision** | What an image *claims* about its source (OCI `revision` label, baked environment variables) | `unknown` on every trading image. The collector bakes `P2F_GIT_COMMIT=1bfb5f6…` |
| **Actual runtime** | The bytes inside the running image, plus its effective configuration | Measured by per-file hashes (`RUNTIME_MANIFEST.json`) and Compose config-hash labels |

**The production checkout is not evidence of the running code.** The images are pinned overlays built from staged contexts. Image `/app` files compared with the checkout's working files on 2026-10-18:

| Service | Image files | Identical in checkout | Different | Absent from checkout |
|---|---|---|---|---|
| analyzer | 46 | 20 | 8 | 18 |
| signal_engine | 56 | 29 | 8 | 19 |
| telegram | 47 | 21 | 7 | 19 |
| trade_tracker | 48 | 21 | 8 | 19 |
| scanner | 23 | 17 | 6 | 0 |
| collector | 18 | 0 | 0 | 18 (not in the checkout) |

## 2. Traceability matrix (every running bot component)

| Component | Runtime identity | Image ID / revision label | Source evidence | Where in GitHub | Status |
|---|---|---|---|---|---|
| analyzer | container `trading_analyzer`, started 2026-10-16T22:19Z, healthy, 0 restarts | `sha256:011f99ba…` / `unknown` | 46/46 files = `ea8ae4f`; 3 dormant modules | `main` (no service code changed since `ea8ae4f`); `deploy/a561-rel-ea8ae4f/` | **MATCH (content)** |
| signal_engine | `trading_signal_engine`, 2026-10-16T22:50Z | `sha256:c5be4e34…` / `unknown` | 56/56 = `ea8ae4f`; 2 dormant | same | **MATCH (content)** |
| telegram | `trading_telegram`, 2026-10-16T21:48Z | `sha256:51d62f4d…` / `unknown` | 46/47 = `ea8ae4f`; `requirements.txt` text is older (installed aiohttp 3.14.3) | same | **MATCH, explained difference** |
| trade_tracker | `trading_tracker`, 2026-10-16T21:17Z | `sha256:2cf1dd52…` / `unknown` | 47/48 = `ea8ae4f`; same `requirements.txt` note | same | **MATCH, explained difference** |
| scanner | `trading_scanner`, 2026-09-30T06:50Z | `sha256:63b38e7a…` / `unknown` | 23 files assembled from older commits, each traced; **8 of 23 differ from `main:scanner/` and `shared/`** | `deploy/baseline-2026-09-27/deployed_files.json`, `deploy/aiohttp-3.14.3/IMAGES.md` | **ASSEMBLED.** Runtime is older than `main`'s scanner source, by design (no redeploy was approved) |
| collector | `tsb-p2-forward-collector`, 2026-10-14T10:26Z, own compose project | `sha256:324d52c9…` / baked `1bfb5f6` | 18/18 = `1bfb5f6` = `main:p2_forward/p2_forward` | `p2_forward/`, `PROVENANCE.json` | **MATCH (content and label)** |
| postgres (shared) | `postgres`, project shared-postgres | `sha256:721873c3…` (upstream `16.15-alpine3.24`) | upstream image | not in this repository | **External**, out of scope |
| continuous_learner | stopped since 2026-08-17 (exit 143) | `sha256:d1aa69bd…` / `c4cae2b-dirty` | — | `docker-compose.yml` (profile `learner`) | **Retired, must stay stopped** |
| Compose (trading) | config-hash labels on 5 containers | — | `render-hash` = label for 5/5 (including scanner) | `docker-compose.yml` blob `04f965ef` = production file | **MATCH** |
| Collector compose and config | `~/ops/tsb-p2-forward/{compose.yml, configs/continuous-v1.json}` | — | byte-identical after rendering | `p2_forward/compose.yml`, `ops/host/` | **MATCH** |
| Collector monitor | user unit `tsb-p2f-monitor.service` (active, 96 h), `tsbops.slice`, `p2f_cont_monitor.py` | — | unit, slice and script identical | `ops/host/systemd/`, `p2_forward/ops/` | **MATCH** |
| Cron: canary watchdog (*/30) | `~/canary_watchdog.py` run with the checkout's `research/skill_application/.venv` (Python 3.12.3) | — | script = `main:research/ops/canary_watchdog.py`; stdlib-only imports | `research/ops/`, `ops/host/cron/` | **MATCH, with a host-only interpreter dependency** |
| Cron: p1bg backup (04:53) | `~/ops/tsb-p1bg/tsb-p1bg-backup.sh` | — | sha256 `bfc99a95…` | `ops/tsb-p1bg/` | **MATCH (failing since 2026-10-10)** |
| Cron: collector daily seal and backup (:17) | `~/ops/tsb-p2-forward/p2f_seal_day.py`, `p2f_backup.py` | — | identical | `p2_forward/ops/`, `ops/host/cron/` | **MATCH** |
| Cron: A56 soak monitor (`1-59/15`) | `~/ops/tsb-a56-upgrade-kit/a566/soak_check.py`; expired (no-op after 2026-10-17T23:05Z) | — | — | deliberately not versioned | **UNRESOLVED:** removal awaits owner approval |
| Transient research units | 6 failed `rj-*.service`; `research.slice` active, with no job running | — | — | — | **Host-only history**; cleanup needs owner approval |

## 3. Production checkout differences (classified; content of secrets never read)

| Class | Items | Disposition |
|---|---|---|
| Configuration equal to `main` | `docker-compose.yml`, `.gitignore`, `database/init.sql` (modified versus checkout HEAD, identical to `main`) | Aligned. Compose is the deployed source of truth |
| Stale source (older committed versions) | `analyzer/technical_analyzer.py`, `shared/schema.py`, `telegram/main.py`, `trade_tracker/main.py`, `docs/canary_state.md` | Not what runs (section 1). No action; never build from this checkout (Class C) |
| Source now on `main` | 126 untracked files byte-identical to `main` (for example `database/migrations/009_*`, `shared/risk_epoch.py`) | The checkout is simply behind `main` |
| Generated runtime evidence | 163 files under `data/evidence`, `data/evidence_v2` (bind-mounted) | **Protected scientific evidence:** never committed, never modified |
| Research outputs | 19 untracked plus ignored `research/skill_application/out/*`, `research/runs/*` | Host-only research data; outside this record |
| Secrets | ignored `.env` plus 4 `.env.*` variants or backups | **Never read, never committed.** Names only |
| Host tooling | `.venv` (used by the canary cron), `logs/`, `.claude/`, `.superpowers/`, caches | Host-only |

## 4. Runtime dependencies not reproducibly represented in GitHub

| Dependency | Why it is not in GitHub | Status |
|---|---|---|
| `.env` secrets | By design | Host-only. Owner-held copy **unverified** (PORTABILITY_AND_DR S-01) |
| Image artifacts (local Docker store; archives under `~/backups`) | Binary; overlay recipes are not in the repository | References only (`ARCHIVE_REFERENCES.json`); no archive of the running collector |
| Base layers of the overlay images | Built 2026-08 from an unknown revision | **UNRESOLVED** (P-01) |
| Scanner override file `~/backups/…/override-scanner.yml` | Historical deploy artifact | Redundant: render-hash matches without it (`deploy/a561-rel-ea8ae4f/CORRECTIONS.md`) |
| Canary interpreter `.venv` in the production checkout | Host tooling | Script imports stdlib only; any Python 3.12 would do. **Not pinned** |
| Collector monitor binding and history (`~/ops/tsb-p2-forward/monitor/`) | Runtime state | Host-only by design |
| Research collector dataset (`~/research-data/…`, 4.5 GB) | Protected research data | Host-only (R-01) |
| Docker volumes `logs_data`, `models_data` | Runtime state | Host-only |
| Shared-postgres cluster, roles, volume `trading-signal-bot_postgres_data` | Another project | External (H-01) |
| A56 kit, R-1 kit (`~/ops/…`) | Execution and approval evidence | Host-only. Referenced by path and SHA256SUMS |
| `develop` branch | Transitional | `ce38ff7`, now one merge behind `main`. Retirement per policy section 11 |

## 5. Proposed versioned deployment manifest (proposal; not created)

> **Update 2026-10-18 (R1.2):** implemented as `deploy/DEPLOYED.json` (schema and usage in `deploy/DEPLOYED.md`). The text below is the original proposal.

**Purpose:** one committed, machine-readable record per deployment change. It would be proposed through a PR together with each approved deploy or rollback, and would be the reference for drift detection.

**Proposed path:** `deploy/DEPLOYED.json`, with history in Git. Each release record stays in its own `deploy/<release>/` directory.

**Rules:**
- It records **observations**, not intentions.
- Every reproducibility claim is one of three levels:
  - `L0-artifact`: an image archive exists;
  - `L1-content-verified`: per-file hashes equal a commit;
  - `L2-canonical-rebuild`: a clean build from a tagged `main` commit reproduces the manifest.
- **L2 may only be written with evidence.** No service qualifies today.
- No secret values; environment *names* only where needed.

Illustrative content for today. This JSON block is documentation only; it is not a committed file:

```json
{
  "schema": "tsb-deployed/1",
  "observed_at": "2026-10-18",
  "repository_head": "a2d75924469997ba37830b81e3d4eac11d915c10",
  "compose": {"path": "docker-compose.yml", "git_blob": "04f965ef8c20a0b2283f695b5eb90735e036643e"},
  "services": {
    "analyzer":      {"image_id": "sha256:011f99ba451b…", "source": "ea8ae4f", "level": "L1-content-verified", "release": "deploy/a561-rel-ea8ae4f"},
    "signal_engine": {"image_id": "sha256:c5be4e34c064…", "source": "ea8ae4f", "level": "L1-content-verified", "release": "deploy/a561-rel-ea8ae4f"},
    "telegram":      {"image_id": "sha256:51d62f4dfa51…", "source": "ea8ae4f", "level": "L1-content-verified", "release": "deploy/a561-rel-ea8ae4f"},
    "trade_tracker": {"image_id": "sha256:2cf1dd52cd89…", "source": "ea8ae4f", "level": "L1-content-verified", "release": "deploy/a561-rel-ea8ae4f"},
    "scanner":       {"image_id": "sha256:63b38e7a659d…", "source": "assembled", "level": "L1-content-verified", "release": "deploy/aiohttp-3.14.3"},
    "collector":     {"image_id": "sha256:324d52c9b37a…", "source": "1bfb5f6", "level": "L1-content-verified", "release": "p2_forward/PROVENANCE.json"}
  },
  "l2_canonical_rebuild": "none",
  "archives_off_host": false
}
```

## 6. Non-mutating drift detection (design)

> **Update 2026-10-18 (R1.2):** implemented as `ops/provenance/drift_check.py`, with tests in `tests/test_drift_check.py`. Not scheduled.

**Principle:**
- read-only Docker and Git operations only: `docker inspect`, `docker image inspect`, `docker save` streamed to hashing, `git hash-object`;
- never `exec`, `restart`, `pull`, `build` or plain `docker compose config`;
- never prints environment values;
- exit 0 means no drift, 1 means drift, 2 means the check could not run.

The checks reuse tools already in the repository:

| # | Check | Tool | Drift means |
|---|---|---|---|
| D1 | Each running container's image ID equals the manifest | `docker inspect --format {{.Image}}` | an unapproved image change |
| D2 | `/app` contents and installed packages equal the release manifest | `ops/provenance/runtime_manifest.py verify` | image content changed |
| D3 | Production `docker-compose.yml` blob equals `main` (or the deployed manifest) | `git hash-object` | compose edited outside a PR |
| D4 | Render hash equals the container config-hash label, per service | `ops/compose-safe render-hash <svc>` | configuration or `.env` changed since the container was created |
| D5 | Collector compose, config, systemd units and cron equal the templates | `ops/host/render.py compare` | host definitions changed |
| D6 | Container start times and restart counts equal the last observation | `docker inspect` | unplanned restart or recreate |
| D7 | `continuous_learner` is still not running | `docker inspect --format {{.State.Status}}` | a safety breach (STOP) |
| D8 | The safety flag `PAPER_TRADING=true` holds on every trading container (this value only) | `docker inspect` environment, filtered to that key | a safety breach (STOP) |

**Operation (proposal):**
- a single wrapper (`ops/provenance/drift_check.py`, **not implemented**) runs D1 to D8 and writes a JSON report with no secret values;
- D2 streams `docker save` (minutes of I/O), so D2 runs at most daily and niced, and D1, D3 to D8 can run hourly;
- running it from cron or alerting needs a separate approval.
- **Any drift is reported to the owner, never auto-corrected.**
