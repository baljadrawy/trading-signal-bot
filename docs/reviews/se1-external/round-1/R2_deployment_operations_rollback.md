REVIEWER 2 (model: Claude Opus 5.5) — SE-1 deployment, operations and rollback

## A. Verdict
**CONDITIONAL GO.** The image content and Compose targeting are sound. Four procedure gaps must be closed before the owner authorizes the Class B recreate: version boundary, health false-positive, B3 gate definition and a pre-staged rollback. None is a code BLOCKER.

## B. Findings

**R2-01 HIGH: version boundary unresolved; the template routes it to STOP.** README.md:57,109; VERSION_BOUNDARY_TEMPLATE.md:9-11; shared/strategy_identity.py:715-721 (main.py is a file-scoped ACTIVE file, and selection_policy.py enters the closure).
- The overlay inherits `APP_VERSION=sb-2026.08`. I checked this independently on both the base image and the running env. That value is the `strategy_version` stamped on signals (signal_logic.py:214).
- So `source_hash` changes under an unchanged label. The template classes that as UNDECLARED_CHANGE, which means stop.
- Impact: activation either stops or creates a boundary nobody declared.
- Fix: before the request, the owner declares version_before/after, and the before/after identity manifests are drafted with `shared.strategy_version_boundary`. Either cite a byte-identical golden replay (MINOR/PATCH) or classify the change MAJOR. Decide whether the label is also stamped through `APP_VERSION`.
- Blocks activation, not the build.

**R2-02 MEDIUM: the health check can pass on the old container's heartbeat.**
- Heartbeats live in the database, keyed by service name (shared/health.py:32-44, 61-78), so a recreate does not reset them.
- The running env has `HEALTH_MAX_AGE_SECONDS=180` (verified), and the Docker interval is 60 s. Two "healthy" reads inside 180 s of start can both come from the old process. That covers README:107,117-118.
- Fix: count the first health read only at least 180 s after the new StartedAt, with reads at least 60 s apart. Add an owner-approved read showing `last_started_at` and `last_success_at` are later than StartedAt and the metadata carries `funnel`.

**R2-03 MEDIUM: the PAPER_HALTED/B3 gate is undefined.**
- README:108 says only "per COMPOSE_OPERATIONS.md".
- That runbook (lines 16-28, 112) requires "still in force", verified from the database. It also says the halt is recomputed and must not be asserted without a read.
- The Paper observe change altered the pause state since the runbook text was written. The literal gate may fail (STOP) or get skipped.
- Fix: define the gate as pre/post equality of the pause row and the risk.halted outbox count, as the precedent did (paper-observe IMAGES.md:47; VERSION_BOUNDARY.md:29). Use a named, owner-approved read-only query.

**R2-04 MEDIUM: rollback is not pre-staged.**
- README:130-132 rolls back "through the same Compose path": a PR, the integrator's merge, then install.
- COMPOSE_OPERATIONS.md:121-122 allows a rollback only if it was pre-approved in the plan.
- During a refusal loop, signal_engine emits nothing until that chain completes.
- Fix: the rollback target is the current reviewed blob `d1a4b197…`, which is already integrated. Name it, with expected config-hash `20dcae19…` (valid if `.env` is unchanged) and image `sha256:c5be4e34…`. Get the rollback pre-approved in the same authorization and write out the exact command.
- `tsb-p1d-signal_engine` (`80096a98…`) is not a valid SE-1 rollback: it would also revert the A56.x changes, and its schema compatibility is unverified. Say so.

**R2-05 MEDIUM: the base is pinned by assertion, not by proof.**
- Dockerfile:7-8 uses `FROM ${BASE_TAG}`, a mutable tag. The `tsb.base_image` label (line 11) is a hard-coded string, not derived from the build.
- The "temporary local tag" means a daemon write next to pinned tags, plus a later cleanup.
- Fix: no new tag. Use the pinned tag, or `tsb-a561-signal_engine@sha256:c5be4e34…` (present in RepoDigests, verified).
- Add a post-build gate: the new image's RootFS.Layers[0..23] equal the base's 24 layers, the total is 26, and User/Cmd/WorkingDir/Env are unchanged.
- Refuse if `tsb-se1-signal_engine:7ff582f-r1` already exists. It is absent today (verified).

**R2-06 MEDIUM: the content-verification pass criterion is unstated.**
- runtime_manifest.py inspects **images only**, through `docker image inspect` and `docker save` (lines 41-62, 125-135). It never inspects containers.
- `generate` always exits 0 (lines 181-187). `verify` needs a committed manifest. None exists, and protected_scan blocks committing one (precedent IMAGES.md:49-57).
- A main.py from the wrong commit would be classed `assembled` and still exit 0. File mode, owner and `tsb.*` labels are not checked.
- Expected result for the services.json spec at 7ff582f: match 61, dormant 2 (`shared/risk_epoch.py`, `shared/strategy_math.py`), assembled 0, unknown 0. The copy_map yields 63 paths and the image will hold 61.
- Fix: make that summary a hard gate. Separately confirm the container's `.Image` equals the built ID.

**R2-07 LOW: restart loop on refusal.**
- The refusal happens before any database I/O (main.py:103-104; `Database.connect` is at 109).
- Under `unless-stopped`, Docker backs off to about one restart per minute. Logs are capped at 3 × 10 MB. No alert fires and no heartbeat changes.
- Blast radius is signal_engine only.
- The proposed strings "on", "20000" and "true" pass the validators (funnel_flags.py:35-72).
- The running env has no `FUNNEL_*` or `SELECTION_*` names (verified), and the Compose `environment:` block overrides `env_file`.
- Residual: a failure after `mark_started` (the lazy import at main.py:124) would loop with a database connection on every restart.
- Fix: dry run before the recreate. Use a disposable `--network none --read-only` container from the new image with the exact values, calling `funnel_recording_config()` and `selection_policy_from_env()` and importing `shared.funnel_hooks`.

**R2-08 LOW: build hygiene.**
- The README:99 command has no `-f`. 7ff582f has no root Dockerfile, so it fails closed, but it is inconsistent with Dockerfile:5-6.
- The Dockerfile is not in the source commit. Record its blob (commit 0ddc324).
- `SOURCE_COMMIT` has no default, so a missing build-arg leaves an empty revision label.
- File modes follow the export umask. Base files are 0664/0775 (verified), and the precedent preserved running modes. This has no functional effect.

**R2-09 LOW: post-deploy provenance is not planned.** There is no image archive or SHA256SUMS (precedent IMAGES.md:59-72), no DEPLOYED.json update and no handling of per-update backups (CLAUDE.md:22). The source is an unmerged release branch, pushed to origin (verified), so parity must be documented explicitly.

## C. Claim verification
| Claim | Status |
|---|---|
| Running container uses `c5be4e34…` (README:19-20) | VERIFIED |
| "55 Python files + requirements.txt match ea8ae4f" | 56/56 match: VERIFIED. Composition is 54 .py + `/app/Dockerfile` + requirements.txt, so the "55 Python" count is REFUTED (minor) |
| `git diff ea8ae4f 7ff582f` = exactly 6 files; ea8ae4f is an ancestor | VERIFIED |
| Overlay copies only the six files, as 1000:1000 | VERIFIED. Matches base ownership; appuser is uid 1000 |
| Dependency set unchanged | VERIFIED (no RUN; new imports resolve against ea8ae4f modules) |
| Service/container/project labels | VERIFIED |
| Recreate touches only signal_engine | VERIFIED against blob d1a4b197 (per-service env, no depends_on, no shared env anchor). Production file equality NOT VERIFIED |
| Rollback images present locally | VERIFIED. Archives NOT VERIFIED |
| Disk free 474 GB | VERIFIED (473 GB, 37 %) |
| Fail-closed start-up before database I/O | VERIFIED |
| Health still passes with the `funnel` key | VERIFIED, but see R2-02 |
| services.json can verify the image | PARTIAL: image-level only, no pass/fail gate |
| Tests inside the image (150 passed) | NOT VERIFIED (R3 scope) |
| Version-boundary record required | VERIFIED; not drafted |

## D. Residual risks
- SIGTERM on recreate: there is no visible handler, so in-memory evidence_v2 events may be lost at stop. This is pre-existing; not verified.
- Container IPs change on recreate.
- The build leaves cache on the shared daemon.
- Compose network-label drift could make `up` fail.
- The collector is currently unhealthy (a separate project). Record it as the expected pre-state so it does not trigger a spurious STOP.
- 24 hours shows only operational health.

## E. Minimal remediation
1. Draft the VB entry with an owner-declared version label and the golden-replay/MAJOR decision.
2. Define the health timing and heartbeat-freshness read.
3. Define the B3 gate as pre/post pause-row equality under a named read-only query.
4. Pre-approve the rollback to blob `d1a4b197` / config-hash `20dcae19…` / image `c5be4e34…`, with the exact command.
5. Pin the base by digest and add the post-build layer-chain gate. No temporary tag.
6. Make the manifest summary (61/2/0/0) and container image ID hard gates.
7. Dry-run the config validation in a disposable container.
8. Add the archive, DEPLOYED.json and backup steps.

Every command above is a proposal only. Nothing was built, run against services or changed.
