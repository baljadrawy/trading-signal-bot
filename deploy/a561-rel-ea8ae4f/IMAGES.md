# Release record: a561-rel-ea8ae4f-r2 (running production images, verified 2026-10-18)

**Status: historical runtime record.** This PR deploys nothing and changes no container. The images below were deployed by A56.5 on 2026-10-16. The A56 24-hour soak was evaluated at 2026-10-17T23:07Z (`~/ops/tsb-a56-upgrade-kit/a56-final/eval-final-2026-10-17T23:07:04Z.json`): every required runbook gate passed, with seven preserved FAIL records classified as non-blocking warnings.

**These release images are NOT canonical Dockerfile builds.** Each is an overlay chain (`COPY . /app` layers on earlier production images). Their OCI `revision` label is `unknown`. A canonical build from `ea8ae4f` would differ:
- it would contain the dormant modules listed below;
- analyzer and signal_engine would install aiohttp 3.13.5 (their `requirements.txt` pins it), not the 3.14.3 actually installed;
- transitive dependencies are not locked.

Equivalence is established **by content** (per-file hashes), never by bit-for-bit rebuild.

## Running services

| Service | Container | Image | Image ID | Source | Compose config-hash (container label) |
|---|---|---|---|---|---|
| analyzer | trading_analyzer | `tsb-a561-analyzer:rel-ea8ae4f-r2` | `sha256:011f99ba451b0debc25d1332d59eb60819b5ad49f26b170b3b196400af42fb57` | `ea8ae4f`: 46/46 files match; 3 dormant | `c69beccc09d1…` |
| signal_engine | trading_signal_engine | `tsb-a561-signal_engine:rel-ea8ae4f-r2` | `sha256:c5be4e34c064c707cb421c2f5d26c38dfee8ad75f36d7e3b177be88d4a825418` | `ea8ae4f`: 56/56 match; 2 dormant | `20dcae19a702…` |
| telegram | trading_telegram | `tsb-a561-telegram:rel-ea8ae4f-r2` | `sha256:51d62f4dfa512c54c29db8886cff171de7d48b356fde6f1874098df057f4d219` | `ea8ae4f`: 46/47 match; 1 assembled (`requirements.txt`, older text); 1 dormant | `3f03902854b6…` |
| trade_tracker | trading_tracker | `tsb-a561-trade_tracker:rel-ea8ae4f-r2` | `sha256:2cf1dd52cd89d44b7dc70c92b0ff797a54e3799d7deaf82b4fe7d1012ba76ae8` | `ea8ae4f`: 47/48 match; 1 assembled (`requirements.txt`); 1 dormant | `9d914e8f9994…` |
| scanner | trading_scanner | `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z` | `sha256:63b38e7a659d0efbc5dd1cb2a6035da1ab210f7774e94056d77fe7c61b50615e` | assembled: all 23 files exist in history; per-file commits in `deploy/baseline-2026-09-27/deployed_files.json` (23/23 match). Not changed by A56 | `e99de276a5c2…` (includes an override file, below) |
| collector | tsb-p2-forward-collector | `tsb-p2-forward:p2f-160-1bfb5f6-20261014T0652Z` | `sha256:324d52c9b37a2ecd9a1ddace7e93ad5d7728411d98e8503abcd618f87c8f59e8` | `1bfb5f6`: 18/18 match; baked `P2F_GIT_COMMIT=1bfb5f6…`. Source import is a separate PR | `6f62e5177564…` (compose under `~/ops/tsb-p2-forward`) |
| postgres | postgres | `postgres:16.15-alpine3.24@sha256:721873c3…` | `sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea` | upstream image; shared-postgres project (outside this repository) | `2012965f16b5…` |

**Dormant files.** These are in the Dockerfile COPY scope at `ea8ae4f` but absent from the image. They are not imported at runtime; the import closure was verified in A56.4.
- analyzer: `shared/risk_epoch.py`, `shared/signal_readiness.py`, `shared/strategy_math.py`
- signal_engine: `shared/risk_epoch.py`, `shared/strategy_math.py`
- telegram and trade_tracker: `shared/strategy_math.py`

**Schema.** The soak monitor asserted `schema_version = 11` every 15 minutes during the soak. A4 confirmed migrations 010 and 011 with checksums `3820075074c5…` and `5958a6b15454…`.

## Compose

- `docker-compose.yml` in this commit is byte-identical to the deployed production file (git blob `04f965ef8c20a0b2283f695b5eb90735e036643e`). Its only difference from `ea8ae4f` is the 4 `image:` lines above, each with its rollback comment.
- It uses `env_file`. It contains no literal credentials, ports or host IPs.
- **Scanner override.** The scanner was last created (2026-09-30) with a second compose file: `~/backups/tsb-aiohttp-20260929T122701Z/deploy-scanner-20260930T065007Z/override-scanner.yml` (81 bytes). It sets only `services.scanner.image` to the same image as the main compose. The image is identical, but the running config-hash (`e99de276…`) includes that file. A canonical `-f docker-compose.yml` render therefore produces a different hash, which is expected and not drift.

## Rollback images (present locally; A7 verified 2026-10-17T23:07Z)

| Service | Rollback image | Image ID |
|---|---|---|
| analyzer | `tsb-p1d-analyzer:p1d-59297305-20261001T2045Z` | `sha256:b9b13d957bf47054e9c73c49f64a828f70186d3744fbde5e0b9a2e4dee34d378` |
| signal_engine | `tsb-p1d-signal_engine:p1d-59297305-20261001T2045Z` | `sha256:80096a981b2e68a2ab56de6c9725e6288d0a7b3b9fb595e64699cae48aa37fa2` |
| telegram | `tsb-p1d-telegram:p1d-59297305-20261001T2045Z` | `sha256:e5f3096b7a7130f868656171193e50e9c575545d034c5f35182636362eb2065a` |
| trade_tracker | `tsb-p1d-trade_tracker:p1d-59297305-20261001T2045Z` | `sha256:698d31730ec309d416efa3f42f2b1d92cb86bd2360b7d3051c007714ae4bba08` |

Archive hashes are in `ARCHIVE_REFERENCES.json` (references only; no archive is in Git). **Every archive is on this host only.** No archive of the running collector 1.6.0 image was found.

## Dependencies

- `installed-packages/<service>.txt` lists the distributions actually installed in each running image. It is a runtime baseline, **not** a lock file used by any build.
- There are no lock files. Transitive dependencies are unpinned (15–40 per service).
- Versions differ between images, for example numpy 2.2.6 vs 2.5.2, websockets 12.0 vs 17.0.1, and idna 3.18 vs 3.19.
- aiohttp 3.14.3 is installed in every image, but `analyzer/requirements.txt` and `signal_engine/requirements.txt` still pin 3.13.5. Fixing that, and introducing per-service constraints, changes future builds and needs a separate review.

## Verify (read-only; no container is created or changed)

```
python3 ops/provenance/runtime_manifest.py verify deploy/a561-rel-ea8ae4f/services.json \
        deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json --repo <git checkout with full history>
```

`OK <service>` for each service means the running image still has exactly the recorded files, packages and identity. Then compare `git hash-object <production>/docker-compose.yml` with this commit's `docker-compose.yml` blob.
