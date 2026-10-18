# Portability and disaster-recovery gap register (R1, 2026-10-18)

**Status: living register.** Each entry records evidence, an owner, dependencies and an acceptance criterion. "Observed" means a read-only observation made on 2026-10-18 (R0/R1) against `main@ce38ff7`. It is not a certification. Closing an entry needs its acceptance criterion to be met and recorded.

**Roles.**
- **Owner:** the repository and server owner. Approves every gated step.
- **Operator:** the person or agent preparing and executing an approved step.

## 1. Service → image → source (observed)

| Service (container) | Image tag | Image ID | Source | Recorded in |
|---|---|---|---|---|
| analyzer (`trading_analyzer`) | `tsb-a561-analyzer:rel-ea8ae4f-r2` | `sha256:011f99ba451b…` | `ea8ae4f`: per-file match, 3 dormant modules | `deploy/a561-rel-ea8ae4f/` |
| signal_engine (`trading_signal_engine`) | `tsb-a561-signal_engine:rel-ea8ae4f-r2` | `sha256:c5be4e34c064…` | `ea8ae4f`: per-file match | same |
| telegram (`trading_telegram`) | `tsb-a561-telegram:rel-ea8ae4f-r2` | `sha256:51d62f4dfa51…` | `ea8ae4f` (`requirements.txt` text older) | same |
| trade_tracker (`trading_tracker`) | `tsb-a561-trade_tracker:rel-ea8ae4f-r2` | `sha256:2cf1dd52cd89…` | `ea8ae4f` (`requirements.txt` text older) | same |
| scanner (`trading_scanner`) | `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z` | `sha256:63b38e7a659d…` | Assembled from older commits; each file is traced | `deploy/baseline-2026-09-27/deployed_files.json`, `deploy/aiohttp-3.14.3/IMAGES.md` |
| collector (`tsb-p2-forward-collector`) | `tsb-p2-forward:p2f-160-1bfb5f6-20261014T0652Z` | `sha256:324d52c9b37a…` | `1bfb5f6`; also baked into the image as `P2F_GIT_COMMIT` | `p2_forward/PROVENANCE.json` |
| postgres (`postgres`, shared-postgres project) | `postgres:16.15-alpine3.24@sha256:721873c3…` | `sha256:721873c34ceb…` | Upstream image | outside this repository |
| continuous_learner | `trading-signal-bot-continuous_learner` | `sha256:d1aa69bde63f…` | exited since 2026-08-17; must stay stopped | — |

Other observations:
- **Compose:** the production `docker-compose.yml` equals `main` (blob `04f965ef`). For all 5 trading services, the render hash equals the running config-hash.
- **Revision labels:** `org.opencontainers.image.revision` is `unknown` on every trading image.
- **Architecture:** every image is linux/arm64.
- **Re-verify:** `ops/provenance/runtime_manifest.py verify`, then `ops/host/render.py compare`.
- **Full runtime-to-repository traceability** (every component, checkout classification, dependencies outside Git, proposed deployment manifest and drift detection): `docs/ops/RUNTIME_TRACEABILITY.md`.

## 2. Two different recovery capabilities

| Capability | Means | Available today? |
|---|---|---|
| **Artifact-based recovery**: run the *same* images again | Image archives (`docker load`), DB dump plus evidence copy, `.env` from the owner, compose from `main`, host templates from `ops/host/` | **Partly.** Archives exist for 4 release images, the rollback images and the scanner overlay, verified on 2026-10-18. **None for the running collector.** Everything is on this host; arm64 only; the DB backup is degraded (see `TSB_BACKUP_RECOVERY_PLAN.md`) |
| **Source-based reproducibility**: build equivalent images from Git | Canonical Dockerfile build from a tagged `main` commit with locked dependencies, compared with the release manifest | **No.** See P-01 to P-04. The release is a documented legacy exception (`docs/ops/BRANCH_RELEASE_POLICY.md`, section 4 item 5) |

Never describe artifact recovery as reproducibility, or the reverse.

## 3. Gap register

| ID | Gap (evidence) | Risk | Owner | Depends on | Acceptance criterion |
|---|---|---|---|---|---|
| P-01 | The overlay build recipes for the running images are not in the repository; they exist only in image layer history. The base images' source revision is unknown | High | Owner (decide); Operator (prepare) | — | Canonical build from a tagged `main` commit in an isolated environment; its `/app` equals the release manifest |
| P-02 | No dependency locks; 15–40 transitive packages are unpinned per service (`deploy/a561-rel-ea8ae4f/installed-packages/`) | High | Operator | — | A committed per-service lock; the installed set in the canonical build equals the lock |
| P-03 | `analyzer` and `signal_engine` `requirements.txt` pin aiohttp 3.13.5, but 3.14.3 is installed | Medium | Operator | P-02 | Pins equal the installed set (changes future builds only; separate review) |
| P-04 | AMD64: every image is arm64, and the aiohttp overlay wheel is aarch64-only. (The base pin `python@sha256:d764…` *is* a multi-arch index including amd64, verified against Docker Hub on 2026-10-18) | High | Owner | P-01, P-02 | Canonical builds pass on both architectures in isolation, with equal manifests |
| P-05 | Image archives are on this host only; the running collector image has no archive | High | Owner | — | Collector image archived with its checksum; off-host copies of every archive verified |
| D-01 | The `trading_signals` backup has failed since 2026-10-10 | **Critical** | Owner | R-1 gates | `TSB_BACKUP_RECOVERY_PLAN.md` step 3: G2 and G3 `OK set=` |
| D-02 | No off-host copy of the trading DB or evidence; `trading_signals` is outside the shared-postgres backup's scope | **Critical** | Owner | D-01 | Encrypted off-host copy verified, plus a restore test from it |
| D-03 | No atomic DB-plus-evidence restore point | Medium | Operator | D-01 | Consistency boundary documented, and skew measured in a restore test |
| D-04 | No recent restore rehearsal of a p1bg set | High | Owner | D-01 | Isolated restore test (plan, section 6) passes |
| D-05 | Backup failures are not alerted (log only) | High | Operator | — | A failed run alerts the owner the same morning |
| S-01 | Secrets live only in `.env` on this host; owner-held copies are **unverified** | High | Owner | — | Owner confirms an off-host secret store holding every variable *name* listed in the secret inventory |
| S-02 | The DB password is in Git history (A60); all services use one highly privileged DB role; R-5 roles are not applied | High | Owner | — | Rotation (G6) done; R-5 applied through its gates |
| S-03 | `CMC_PRO_API_KEY` is injected into containers but read by no code | Low | Operator | — | Removed from the runtime environment after approval |
| S-04 | Secrets are visible to anyone with Docker access (environment variables) | Medium | Owner | — | Decision recorded (accept, or move to file-based secrets) |
| H-01 | Shared infrastructure: the PostgreSQL cluster is shared with other projects; the data volume is named `trading-signal-bot_postgres_data`; the bot depends on the `postgres` hostname on `shared_db_net` | Medium | Owner | — | A documented extraction procedure (dump `trading_signals` plus the required roles) tested in isolation |
| H-02 | `shared_db_net` also connects `wishlist-app` and `xsch-app` to the bot containers | Medium | Owner | — | Isolation decision recorded (for example, a dedicated DB network) |
| H-03 | Runtime state outside Git: the production checkout is dirty on a research branch; the `canary_watchdog` cron uses that checkout's gitignored `.venv`; the collector monitor binding is host state | Medium | Operator | — | Each item documented with a rebuild procedure, or pinned |
| H-04 | The `trading_claude_review` container no longer exists (docs said it was kept); only its images remain | Low | Operator | — | Docs corrected (this PR); the CR-2 rollback path is described from the image |
| G-01 | Halt state not verified authoritatively: docs say `loss_streak_halt`; logs show `loss_streak_reduce` rejections | High | Owner | — | An owner-approved database read records the state; the docs are then aligned |
| G-02 | `main` and `develop` are unprotected | Medium | Owner | — | Protection as in `BRANCH_RELEASE_POLICY.md`, section 8 |
| G-03 | The expired A56 soak cron line is still installed | Low | Owner | — | Removed with approval; the crontab record is updated |
| R-01 | The collector research dataset (4.5 GB) and its sealed-day backups are on this host only | Medium | Owner (research governance) | D-02 | Off-host decision under research governance; the holdout stays sealed |
| M-01 | No monitoring from outside the host | Medium | Owner | — | Decision recorded |

## 4. Existing documents this register builds on

- **Releases and images:**
  - `deploy/a561-rel-ea8ae4f/` (release record, manifests, verifier, `CORRECTIONS.md`);
  - `deploy/aiohttp-3.14.3/`;
  - `deploy/p1d-forward-instrumentation/`;
  - `deploy/cr2-signal-ready/`;
  - `deploy/baseline-2026-09-27/`.
- **Operations and host:**
  - `docs/ops/COMPOSE_OPERATIONS.md`;
  - `docs/ops/BRANCH_RELEASE_POLICY.md`;
  - `ops/host/`;
  - `p2_forward/RUNTIME_IMPORT.md`.
- **Backup:**
  - `ops/tsb-p1bg/README.md`;
  - `docs/ops/TSB_BACKUP_RECOVERY_PLAN.md`;
  - outside the repository: `~/ops/tsb-r1-backup-repair/` and `~/ops/tsb-r1-backup-repair-evidence/` (R-1 kit, recovery-point inventory, CP-9 proposal).
- **Runbooks and governance:**
  - `docs/loss_streak_recovery_runbook.md`;
  - `docs/evidence_v2/OPERATIONS.md`;
  - `docs/research_temporal_governance.md`;
  - `research/governance/holdout_status.json`.
