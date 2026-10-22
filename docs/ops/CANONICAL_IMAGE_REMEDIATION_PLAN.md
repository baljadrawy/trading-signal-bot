# Canonical image remediation plan (design only)

**Status: design. Nothing in this plan has been built, and no production image, tag or container is changed by it.**
Each execution step below needs its own owner approval. The first production use of a canonical image is a separate
Class B operation (`docs/ops/COMPOSE_OPERATIONS.md`).

## 1. Problem

The four Paper release images (`tsb-a561-*:rel-ea8ae4f-r2`) and the scanner image are **overlay chains**, not
reproducible builds (`deploy/a561-rel-ea8ae4f/IMAGES.md`). The running signal_engine image, read with `docker history`,
is:

1. `python:3.12-slim@sha256:d764629c…` (pinned base, arm64);
2. `pip install -r signal_engine/requirements.txt`: 5 direct pins, **transitive dependencies resolved at build time**;
3. an aiohttp 3.14.3 wheel overlay (`file:///tmp/overlay/…aarch64.whl`, sha256-checked);
4. six single-file `COPY` overlays;
5. two whole-tree `COPY . /app/` overlays.

The consequences are:

| Defect | Effect today |
|---|---|
| No lock file and unpinned transitive dependencies | A rebuild from any commit resolves different versions. `signal_engine/requirements.txt` still pins aiohttp 3.13.5, but 3.14.3 is running. |
| Content is assembled from layers | Equivalence can only be proven per file (`runtime_manifest.py`), never by rebuilding. A file deleted in source can survive in a lower layer. |
| Revision label is `unknown` | An image cannot be traced to a commit without the manifest. |
| Every change needs a new overlay | Each release adds layers to a chain that nobody can rebuild (the Stage B RC of 2026-10-22 is one more). |
| Single host, arm64 only | CI runs on x86. Nothing CI builds is what runs in production. |

The collector (`p2_forward/Dockerfile`) is the exception and is the model for the target state. It has a digest-pinned
base, `pip install --no-deps --only-binary=:all:` from a complete pinned list, and baked provenance. Its 2026-10-22 RC
rebuild reproduced the dependency layer **byte-identically** (same layer diff-ID as the running 1.6.0 image).

## 2. Target state

For each Paper service (scanner, analyzer, signal_engine, trade_tracker, telegram):

- **A complete lock.** `<service>/requirements.lock` lists every distribution, direct and transitive, with
  `==version` and `--hash=sha256:` for the **linux/arm64 cp312** wheel. The first lock is the exact inventory of the
  running image (`deploy/a561-rel-ea8ae4f/installed-packages/<service>.txt`), not a fresh resolution.
- **One-stage canonical Dockerfile.**
  - `FROM python:3.12-slim@sha256:<digest>`.
  - `pip install --no-deps --require-hashes --only-binary=:all: -r requirements.lock`, then `pip check`.
  - Explicit `COPY` of the service's import closure only.
  - Labels `org.opencontainers.image.revision=<full sha>` and `ARG BUILD_REVISION`, which is what
    `ops/provenance/build_preflight.py` already requires.
- **An offline wheelhouse.** All locked wheels are stored with a `SHA256SUMS` file in the restic repository, so a build
  runs with `--network none` and does not depend on PyPI availability.
- **Deterministic metadata.** `SOURCE_DATE_EPOCH` is the commit time, and BuildKit `rewrite-timestamp=true`. The
  reproducibility target is **identical layer diff-IDs on two independent builds**, not identical image IDs, because
  config timestamps may differ.

## 3. Equivalence gate (before any canonical image may replace an overlay)

A canonical image `C` is equivalent to the running overlay `R` only if all of these hold. Each is checked offline with
`--network none`.

| # | Check | Pass condition |
|---|---|---|
| E1 | App tree (`runtime_manifest.py generate`) | Every file under `/app` has the same sha256 in `C` and `R`. Dormant files stay absent. |
| E2 | Distributions | `pip freeze --all` is identical. The only allowed difference is `aiohttp @ file:///tmp/overlay/…` vs `aiohttp==3.14.3`. |
| E3 | site-packages files | sha256 of every non-`.pyc` file is identical, except an allow-list of pip metadata (`RECORD`, `INSTALLER`, `direct_url.json`). |
| E4 | Base layers | The base layer diff-IDs equal those of `R`'s base layers. |
| E5 | OS packages | `dpkg-query -W` output is identical. |
| E6 | Runtime config | `User`, `WorkingDir`, `Cmd`, `Entrypoint`, `Env` (excluding build labels), `Healthcheck` are identical. |
| E7 | Behaviour | The service's isolated test set passes on `C` and `R` with identical results. For signal_engine, that includes the recorder tests and the telemetry harness of the 2026-10-22 RC. |
| E8 | Reproducibility | Two builds on separate days, from the wheelhouse and offline, give identical layer diff-IDs. |

Any difference outside the allow-lists is a STOP and goes back to the owner.

## 4. Phases

| Phase | Work | Production impact | Approval |
|---|---|---|---|
| R-1 | Lock extraction: turn each `installed-packages/<service>.txt` into a hashed `requirements.lock` (`ops/provenance/lock_candidate.py`, review-only). Fix the stale aiohttp 3.13.5 pins in `requirements.txt` so they agree with the lock. | none (repository only) | PR review |
| R-2 | Build the wheelhouse from the lock, verify hashes, store it in restic with SHA256SUMS. | none (host disk, backup) | owner (backup write) |
| R-3 | Canonical Dockerfiles and a `build_preflight.py` extension that requires the lock and `--require-hashes`. | none | PR review |
| R-4 | Build canonical images offline under new tags `tsb-canon-<svc>:<sha12>-<ts>`. Run gate E1–E8 against each running overlay. Publish a manifest and an equivalence report per service. | none (new tags only; no running tag is moved) | owner (local builds) |
| R-5 | CI: an arm64 build job (QEMU or an arm64 runner) that rebuilds from the lock and compares layer diff-IDs with the R-4 result. | none | PR review |
| R-6 | Replacement, **one service at a time**, as a Class B operation. Each replacement is an equivalence swap: same behaviour and the same `config_hash` lineage. The overlay image stays tagged as the rollback image. Start with telegram (least coupled), then trade_tracker, analyzer, scanner and signal_engine last. Never in the same window as a Collector change. | one recreate per service | owner, per service |
| R-7 | After every service runs a canonical image, releases are built only from the canonical Dockerfile at a merged commit. The overlay procedure is retired. | none | owner |

## 5. Interim rule (until R-6 is complete)

A release for a Paper service is a **minimal overlay on the exact running image ID**, with these properties:

- only the files of the approved change;
- the release commit is based on the running source commit;
- base layers are proven identical (diff-ID prefix);
- the full filesystem diff is limited to the intended files;
- `pip freeze` is identical;
- `runtime_manifest.py` reports every file `match` against the release commit.

The Stage B RC of 2026-10-22 (`deploy/rc-20261022/RELEASE_CANDIDATES.md`) follows this rule.

## 6. Risks and open questions

- **Wheel availability.** Some running versions may no longer be downloadable for arm64, so R-2 may find gaps. The
  fallback is to extract the installed files from the running image into a wheelhouse built with `pip wheel` from
  site-packages. That is weaker and must be labelled as such.
- **Scanner.** It has no source commit (it is assembled per file), so R-1 needs a source reconstruction first.
- **Arch.** CI is x86. Until R-5, reproducibility is proven only on the production host.
- **Disk.** One canonical image per service is about 0.5 GB on the host. Check free space before R-4.
