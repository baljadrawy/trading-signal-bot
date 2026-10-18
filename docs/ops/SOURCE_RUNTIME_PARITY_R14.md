# R1.4 — Externally Auditable Source-to-Runtime Parity

**Status:** mandatory release-gate proposal; no production change authorized. **Scope:** all future bot and collector container releases. The 2026-10-18 A56 legacy runtime remains an explicitly noncanonical transition exception.

## Objective and truth boundaries
An external reviewer with GitHub access but no server access must be able to inspect the **exact source tree, Docker build inputs, dependency locks, tests, image manifest and deployment attestation** for each release. GitHub `main` may advance ahead of production: **a signed/immutable release commit**, not current HEAD, is the comparison target. No GitHub-only artifact proves what is currently running; runtime verification requires independently verifiable, server-origin evidence.

## Mandatory gates for every NEW release
1. **Source:** tagged full commit SHA reachable from `main`; clean, isolated checkout; no production working-tree builds, hidden overlays or copied live files. Build contexts and Dockerfiles committed. Record source tree SHA and per-service source paths.
2. **Dependencies:** committed pinned, reproducible per-service dependency inventories/locks, hashes when supported; fail on mismatch between installed packages and lock. Pin base images by immutable digest and record platform, builder and build args (excluding secrets).
3. **Build:** clean CI runner builds each affected service without production credentials or protected evidence. OCI `org.opencontainers.image.revision` equals tagged SHA. Generate manifest of application paths and SHA256, installed dependency inventory, SBOM and image digest/ID; verify the built image against manifest. No mutable-only tags, unreviewed `docker commit`, untracked overlays or undocumented exceptions.
4. **Review:** reviewer can follow release tag -> source tree -> Dockerfile/lock -> CI run -> build attestation -> image digest -> release record -> sanitized runtime attestation. Every claimed equality is tied to hashes, not just filenames or `main` being newer.
5. **Predeploy:** separately owner-approved named release, one service at a time, rollback image and certified recovery point. Verify exact digest and release metadata on host; preserve PAPER_TRADING and stopped learner. STOP if evidence absent or safety checks fail.
6. **Postdeploy:** capture observed container ID, image ID/digest, Compose hash, image content check, runtime status and observation time using read-only tools; publish a reviewed, sanitized attestation (or privately share with the reviewer). Sign or otherwise bind it to the authorized host identity and release digest; retain evidence privately. `deploy/DEPLOYED.json` is updated only from observation through reviewed PR, never guessed from HEAD.
7. **Acceptance:** record independent reviewer verdict on source/build evidence and distinct operator verdict on runtime evidence. Without trusted runtime attestation, status is **SOURCE_VERIFIED / RUNTIME_UNVERIFIED**, never full parity.

## Existing runtime: explicit migration backlog
- analyzer, signal_engine, telegram, trade_tracker: legacy composite overlay images sourced around `ea8ae4f`, with incomplete canonical rebuild provenance; do not relabel as reproducible.
- scanner: assembled from older sources; 8/23 image files differ from current `main`; requires its own clean-build migration.
- forward collector: source content matches `1bfb5f6`, but the running image archive is missing. Protect the existing collector and scientific evidence.
- PostgreSQL: shared external dependency; not rebuilt or changed by this project. Continuous learner remains stopped.
- Existing image archives and restore points are not deleted by this work. R1.3 event-driven backup governance remains separately approval-gated.

## Immediate implementation plan (no production access required)
A. Add a read-only CI gate for *static release readiness*: verify manifest schema and required evidence paths; report missing canonical build/lock/attestation as blockers. Do not claim to rebuild old overlays.
B. Inventory service Dockerfiles, lock coverage, Compose image references and current legacy gaps in a machine-readable file. Each gap must have a named owner/action and be closed in a separately reviewed PR.
C. Build and test canonical images on GitHub-hosted runners, in isolated CI only, after dependency locking and clean-build tests are available. Never push or deploy automatically.
D. Prepare external review packet template with source commit, CI run, build digest, SBOM, manifest, signed runtime observation and exceptions.
E. Plan service-by-service production cutover only after explicit owner approval, rollback and recovery validation.

## Stop conditions
Missing locks, unknown image provenance, unsigned/untrusted runtime observations, protected evidence exposure, secrets in logs/artifacts, CI failure, mutable digest, changed Compose hash or safety status -> **STOP**. Never rewrite evidence to produce a passing result. A metadata-only drift check is not content parity. No cron changes, DB access, backup rotation, service restarts, merge, production deploy or protected scientific runs are authorized by this document.

## Static inventory: verification layers and current readiness (2026-10-18)
`ops/provenance/parity_inventory.py` (schema `tsb-r14-static-audit/2`) reads only committed files and keeps three layers apart:
- **Source verified:** the image's source is identified by a commit, with per-file evidence in the repository.
- **Build verified:** a canonical rebuild from committed inputs, attested by CI. Not implemented yet, so it is never true today.
- **Runtime verified:** **always false** in this tool. It needs trusted server-origin attestation, and GitHub metadata can never establish it.

Output of the current repository (exit 2, blockers present):

| Service | Source | Build blockers found statically | Runtime |
|---|---|---|---|
| analyzer | commit `ea8ae4f` + per-file evidence | revision label defaults to `unknown`; **aiohttp pinned 3.13.5, installed 3.14.3**; 22 installed distributions unpinned (no lock); no canonical rebuild | not verifiable from GitHub |
| signal_engine | commit `ea8ae4f` | the same label and aiohttp pin gaps; 42 unpinned; no canonical rebuild | not verifiable from GitHub |
| trade_tracker | commit `ea8ae4f` | label `unknown`; 23 unpinned; no canonical rebuild | not verifiable from GitHub |
| telegram | commit `ea8ae4f` | label `unknown`; 15 unpinned; no canonical rebuild | not verifiable from GitHub |
| scanner | **assembled** (not a single commit) | label `unknown`; 23 unpinned; no canonical rebuild | not verifiable from GitHub |
| collector | commit `1bfb5f6` | no OCI revision label (it bakes `P2F_GIT_COMMIT` instead); no canonical rebuild; **no archive of the running image** | not verifiable from GitHub |

The compose `image:` references of the five trading services equal the observed image references in `deploy/DEPLOYED.json`. That is a static comparison only.

**Gap owners and actions** (each to be closed in its own reviewed PR):

| Gap | Owner | Action |
|---|---|---|
| Dependency locks | Operator | Add a per-service committed lock (`requirements.lock`) generated in isolation; prove installed set = lock |
| aiohttp pins | Operator | Align `analyzer` and `signal_engine` requirements with the installed 3.14.3 (affects future builds only) |
| Revision label | Operator | Build only with `BUILD_REVISION=<full sha>`; fail the build when it is missing or `unknown`; add an OCI label to the collector |
| Canonical rebuild | Operator, with Owner approval | CI builds on GitHub-hosted runners after the locks exist; manifest compared with `runtime_manifest.py`; never pushed or deployed |
| Collector archive | Owner | Approve archiving the running collector image (Class A `docker save` to a private path) |
| Scanner provenance | Owner | Decide on a clean scanner rebuild from `main` (a deployment change, separately approved) |
| Runtime attestation | Owner | Define the server-origin, signed observation (the R1.2 drift-check output is the candidate) |

**CI semantics.** The `parity-inventory` job:
- **passes only while blockers are detected**;
- asserts the schema, the static scope, all six services, and `runtime_verified: false` everywhere;
- runs the unit and negative tests;
- **fails** if the tool ever claims runtime parity, or if blockers disappear without review ("Unexpected readiness"). Closing gaps therefore requires deliberately updating this gate in a reviewed PR; the gate is never silently weakened.

Plan status:
- **A** (static gate): implemented.
- **B** (inventory): implemented, with the owners and actions above.
- **C** (canonical CI builds), **D** (review packet), **E** (cutover): not started; C depends on the locks.
