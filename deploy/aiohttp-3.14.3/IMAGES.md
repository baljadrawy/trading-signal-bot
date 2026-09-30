# aiohttp 3.14.3: approved production image provenance

A **provenance record**, not an execution script. It records the images that `docker-compose.yml` pins for the
three services deployed on aiohttp 3.14.3 (Option 2b: `image:` + `pull_policy: never`, no `build:`).
Recorded 2026-09-30.

**Scope:** telegram, trade_tracker, scanner ONLY.
- analyzer, signal_engine and claude_review were validated but NOT deployed; they remain on aiohttp 3.13.5, pending their separate environment-drift (D3) phase.
- optimizer and continuous_learner are not part of this rollout.

## Common artifact and mechanism
- **aiohttp wheel:** `aiohttp-3.14.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl`
  - SHA-256 `f631fe87a6f30df5fbe6d79640b25e4cffb38c31c7fb6f10871517b84b0f8c1a`, 1,765,282 bytes, public on PyPI. It is not committed.
- **Thin overlay:** `deploy/security-overlay/aiohttp-3.14.3/Dockerfile`, introduced in PR #4 commit `ddb3ca2ab9bcec977076ab5c961c7de01fed5f25`.
  - It takes the EXACT existing production image as its base.
  - It adds exactly 2 layers:
    1. COPY of the hash-verified wheel;
    2. `pip install --no-deps --no-index`, then removal of `/tmp/overlay`.
  - Build flags: `--network=none --pull=false`.
- **Acceptance gates (per image), from the PR #4 README and validation report:**
  - identical base image ID and config;
  - RootFS = base + exactly 2 layers;
  - package inventory differs ONLY by `aiohttp 3.13.5 → 3.14.3`;
  - `/app` byte-identical;
  - aiohttp 3.14.3 metadata and C extensions load.
- **Base images:** the 2026-09-27 B3 single-file-overlay production builds (`b3prep-20260927T120659/*:candidate`, image label `org.opencontainers.image.revision=unknown`).
  - Their provenance is recorded on branch `deploy/baseline-2026-09-27`. Source reproducibility is **not proven**.
- **Platform:** `linux/arm64`. Each image ID is an OCI **index** digest. Compose's `com.docker.compose.image` label records the index's linux/arm64 **image-manifest** digest (listed below).

## Images

| Service | Compose `image:` reference (exact) | Immutable image ID (OCI index) | linux/arm64 manifest | aiohttp |
|---|---|---|---|---|
| telegram | `tsb-aiohttp-test-telegram:3.14.3-20260929T124120Z` | `sha256:ef80d11c657967ad21318685eab8ef41cbc08ac7002d06bb8f825960e6bee4f1` | `sha256:1099781fec930029d04bb62af2f4dbf736e04ba35952ec27b071e9dcd495d44b` | 3.14.3 |
| trade_tracker | `tsb-aiohttp-test-trade_tracker:3.14.3-20260929T124120Z` | `sha256:af063314973ee6f4f988903c9836a91b30b4f3343cb68db8587bd41580b179c3` | `sha256:ee9c4458302ade4b1ad40d23c1075ba5b96785e03400d0e577089b2f40b9f9f9` | 3.14.3 |
| scanner | `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z` | `sha256:63b38e7a659d0efbc5dd1cb2a6035da1ab210f7774e94056d77fe7c61b50615e` | `sha256:b647a72a68f16d5ca72d4546db2c62a149875b12cdea4dbb9e8c7cda11525e68` | 3.14.3 |

## Base (pre-overlay) images = rollback targets (aiohttp 3.13.5)

| Service | Base / rollback image ID | linux/arm64 manifest | Rollback tag | Other local tags |
|---|---|---|---|---|
| telegram | `sha256:b84d3d1528a085391892bd9e162d99b7bd75a7d72caca3aa66f2d29caceda76f` | `sha256:3ecea80b60151aaeee41dc9a9ce2521e700ebe1e07f8c760a2fcde6328fc969c` | `tsb-aiohttp-rollback-telegram:pre-3.14.3-20260929` | `trading-signal-bot-telegram:latest`, `tsb-aiohttp-base-telegram:20260929`, `b3prep-20260927T120659/telegram:candidate` |
| trade_tracker | `sha256:2b59c6a164c02ccca6fc6ec4245948104857d381148ee19bdc8436b357dfac26` | `sha256:0cd28a47706a4cbad801856d9c4bdde391019a14f296836d0e719da6c44f3a4d` | `tsb-aiohttp-rollback-trade_tracker:pre-3.14.3-20260929` | `trading-signal-bot-trade_tracker:latest`, `tsb-aiohttp-base-trade_tracker:20260929`, `b3prep-20260927T120659/tracker:candidate` |
| scanner | `sha256:9b0b53a6a799990690947b8e39aba77e7dbf055df41e3f29af3d95a7f20defa1` | `sha256:9c052a823b4a6fe724af9f0c5b7e0d39cf7701dca7b180ac067943cca6ccda7f` | `tsb-aiohttp-rollback-scanner:pre-3.14.3-20260929` | `trading-signal-bot-scanner:latest`, `tsb-aiohttp-base-scanner:20260929`, `b3prep-20260927T120659/scanner:candidate` |

Rollback = recreate ONE service on its rollback image through a service-scoped, gated procedure. Every rollback needs owner approval. Database or schema impact: none.

## Expected Compose config hashes (Option 2b, production project directory)

| Service | `com.docker.compose.config-hash` |
|---|---|
| telegram | `166d2d9965cbefa6bf036fce1a47d5e04e273146e6010a93ff75674a2fb0b1b5` |
| trade_tracker | `330a40b65e06af3be2d3704c9f894d0c282721e04c0b47c85c38026dd9316ab0` |
| scanner | `e99de276a5c29317907203ba18df738dd411a4ce91dd6edc539234846709f32f` |

These equal the hashes of the running containers deployed on 2026-09-30. Compose's config hash ignores `build`, `pull_policy` and file paths, so installing this Compose file does not by itself require recreation.

## Evidence (local host, owner-only; paths for audit)
- **Validation:** `/home/tradmin/backups/tsb-aiohttp-20260929T122701Z/`, covering:
  - `overlay/`: wheel, `Dockerfile.<svc>`, per-service layer, HG4, integrity and inventory files, `matrix.psv`;
  - `tests/RESULTS.md`;
  - `preflight/DEPLOYMENT_PREFLIGHT.md`;
  - `deps/`: normal-resolution drift evidence.
- **Deployment runs (gated, one service each, no rollback needed):**
  - telegram: `…/deploy-telegram-v2-20260930T042152Z/` (2026-09-30 04:21–04:26 UTC; an earlier attempt rolled back on 2026-09-29 and is documented in `TELEGRAM_AIOHTTP_DEPLOYMENT_HANDOFF.md`);
  - trade_tracker: `…/deploy-trade_tracker-20260930T061054Z/` (06:10–06:15 UTC);
  - scanner: `…/deploy-scanner-20260930T065007Z/` (06:50–06:54 UTC).
- **Source-of-truth audit:** `…/sot-audit-20260930T072621Z/AIOHTTP_SOURCE_OF_TRUTH_AUDIT.md`.

## Durability limitation (open)
- **The three overlay images exist ONLY in the local Docker image store on the production host.** They are not in a registry, not in an image archive and not in any backup snapshot. The local evidence folder above is also not yet backed up.
- The base/rollback images are in the local Phase 0 image archive (`/home/tradmin/backups/tsb-phase0-20260927/images/`) and the local restic repository. Both are on the same host.
- **On host loss,** exact image IDs cannot be reproduced, because builds are not bit-reproducible and the base source revision is unknown. A content-equivalent rebuild needs a surviving base image plus the Dockerfile above plus the PyPI wheel, followed by re-validation with the gates.
- Archiving the images and evidence, and any registry or off-host copy, require separate owner approval (CP-6 remains deferred).

## Tag caveat
- The approved references are the original **validation tags** (`tsb-aiohttp-test-*`). They were kept verbatim so the config hashes, and therefore the running containers, stay unchanged.
- Local tags are mutable, so these tags must never be rebuilt or retagged.
- Renaming them to durable production tags would change the config hash and require one gated recreation per service. That is a separate, optional decision.
