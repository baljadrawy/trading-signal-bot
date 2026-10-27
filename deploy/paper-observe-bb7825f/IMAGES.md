# Release record: paper-observe-bb7825f-r2 (Paper observe mode, deployed 2026-10-27)

**Status: runtime record of an owner-authorized deployment.** This commit deploys nothing and changes no container.
It records what was deployed on 2026-10-27 in two Class B steps (one service each) and what was observed afterwards.
Report states separately (owner contract §2): **Saved** yes, **Integrated** yes (`main`), **Deployed** yes,
**Validated: NO** — the econ-observe-v1 evidence check needs a first admission, and admissions are impossible while
the technical pause of 2026-10-21 is in place (it was deliberately not cleared; no `/resume`).

## Source and integration

| Item | Value |
|---|---|
| Application source | `bb7825f4744278095ef76a1d0f3b872e3043358f` (observe mode `758b94f`, `risk.observed` notice `a593e5b`, capacity tests `2f19608`, optional price-fetch retry `bb7825f`, default off). CI `tests` run `40409378227` success |
| Stage 1 compose commit | `7305d2eb5c9282a7cf199abbe931b24668629d20`, `docker-compose.yml` blob `91430822414fd7e8ab398cfd033d1f7a5e3117ee`; CI `tests` push/main run `40490612728` success |
| Stage 2 compose commit | `26eb4e8c69273bf1eda4d8953c44dad86364f92b`, blob `d1a4b197e10f31a4972e8f6e5feba6be361c3689`; CI `tests` push/main run `40497476955` success (also `40485214707` push and `40488012931` pull_request on the integration branch) |
| Integration | both compose commits fast-forwarded into `main` by the independent reviewer (ChatGPT); Claude Code did not push to `main` |
| Stage 2 diff | `7305d2e..26eb4e8`: `docker-compose.yml` only, 2 insertions, 1 deletion (telegram `image:` line, `PAPER_ECONOMIC_HALT_MODE: "observe"`) |

## Deployed services

| Service | Container ID | Image | Image ID (immutable) | Started (UTC; exact value in `deploy/DEPLOYED.json`) | Compose config-hash label |
|---|---|---|---|---|---|
| trade_tracker | `e311ca1f1c6dd95aa02a293850a95e62de9423324c4028f07156aa4a14318a81` | `tsb-obs-trade_tracker:bb7825f-20261027-r2` | `sha256:8e609ca84740e9cd5c16f79c5fac2ae28a0f5004bb90665e29f4f0a6f5e1410c` | 2026-10-27 10:56Z | `539e6347530538094159a2bb16dc16c213946670e2a7a40b1064809ab9d48a28` |
| telegram | `5630fab54ee24d378c8689ca38727e73f2762050d006e6c24520cb3cd772f937` | `tsb-obs-telegram:bb7825f-20261027-r2` | `sha256:d665388a9092f6e5f4364a3e0dff6cca33e9623c782ea47251b625be6a2a7b83` | 2026-10-27 11:51Z | `14b2baf7ee5940be88b22b81f6c5f84579a6cb4752a6ace76f92a6dc549fa38b` |

These are local images without a registry, so the image ID (config digest) is the immutable identifier; `RepoDigests`
is empty. Both images carry `org.opencontainers.image.revision=bb7825f4744278095ef76a1d0f3b872e3043358f`; created
2026-10-27 07:40Z, 21 layers each.

**Build method (not a canonical Dockerfile build).** Each image is a minimal overlay `FROM` the running release image
(verified by image ID first), copying the full Dockerfile COPY scope (`shared/` + `<svc>/`) from a clean
`git archive bb7825f`, with the running owners and file modes, built with `--network none --pull=false`. The
dependency set is the base image's, unchanged.

**Content verification** (spec `services.json` in this directory; manifest generated 2026-10-27 with
`ops/provenance/runtime_manifest.py generate services.json RUNTIME_MANIFEST.json`, then `verify` = OK, and
`drift_check.py check --deep` against it = MATCH 46, DRIFT 0, verification FULL):
- trade_tracker: 51/51 files match `bb7825f`, 0 assembled, 0 unknown, 0 dormant.
- telegram: 50/50 files match `bb7825f`, 0 assembled, 0 unknown, 0 dormant.
- installed Python distributions of both images are identical to their `rel-ea8ae4f-r2` bases.
- analyzer, signal_engine, scanner and postgres entries are byte-identical to `deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json`
  (unchanged services, deterministic generation). The collector entry now describes the running 1.6.1 image
  (`sha256:89232400…`, source `72c0bee`, 19/19 match), which the a561 manifest predates.

Runtime parity checks after each step: filtered environment `PAPER_TRADING=true`, `PAPER_ECONOMIC_HALT_MODE=observe`
(`RISK_PRICE_FETCH_RETRIES` not set, default 0); healthy twice at least 60 s apart; 0 error lines in logs; the other
six containers unchanged (ID, image, start time, restart count, config-hash, IPs); pause row unchanged.

**Why the manifest is not in Git.** `ops/provenance/protected_scan.py` blocks the generated manifest: it contains
image creation times at second precision, a build-time label and one Python distribution name, all of which match
the scan's patterns, and the scan's only exception is `started_at` in `deploy/DEPLOYED.json`. The a561 manifest
predates the scan. Widening the exception changes a protection gate, so it is left to the owner. Until then:
- the manifest is kept on the host: `~/ops/tsb-paper-observe-pkg/run-20261027T1149Z-stage2/RUNTIME_MANIFEST.paper-observe-bb7825f.json`
  (sha256 `49d1a90fa5d9023f07a7338e890399194176b88908c671c85f2fba9d15e83241`; spec copy sha256 `fc6cd67c…`);
- `deploy/DEPLOYED.json` keeps `release_manifest` on the a561 manifest, so a plain `check --deep` reports D2 DRIFT for
  telegram, trade_tracker and the collector (expected; the a561 manifest describes the previous images). To verify
  content, run `runtime_manifest.py verify deploy/paper-observe-bb7825f/services.json <host manifest>`.

## Archives and rollback

Archives are on the host only (never in Git): set `~/backups/tsb-paper-observe-20261027/`, `sha256sum -c SHA256SUMS` OK.

| Service | Role | File | sha256 |
|---|---|---|---|
| trade_tracker | running image | `trade_tracker.obs-bb7825f-20261027-r2.tar` | `27668ee2adffbc27da5a655bcfaf736328f877edf33df6a71acb5360ace0dcc3` |
| trade_tracker | rollback image | `trade_tracker.rollback-rel-ea8ae4f-r2.tar` | `4890a6441a5e944ca6fadd12eec65b1fc50aca0ddd30ebfa0b10fa88ed60c080` |
| telegram | running image | `telegram.obs-bb7825f-20261027-r2.tar` | `8bb4de70fa2004b321c29b9f8f6c0f035d5f13677c108c0ac0b1c5957115363b` |
| telegram | rollback image | `telegram.rollback-rel-ea8ae4f-r2.tar` | `5d9551fd80285b9cfffdd6932082b0e83e2bda7c73fc7d46699cb5eb3c1998ed` |

Rollback images (present locally): `tsb-a561-trade_tracker:rel-ea8ae4f-r2` = `sha256:2cf1dd52cd89d44b7dc70c92b0ff797a54e3799d7deaf82b4fe7d1012ba76ae8`,
`tsb-a561-telegram:rel-ea8ae4f-r2` = `sha256:51d62f4dfa512c54c29db8886cff171de7d48b356fde6f1874098df057f4d219`. The
earlier `rel-ea8ae4f-r2` archives in `~/backups/tsb-a564-release-images-20261016T204443Z` remain valid as well.
Rollback = a reviewed compose commit restoring the previous `image:` line and `PAPER_ECONOMIC_HALT_MODE` removal (or
`"enforce"`), then the same one-service Class B command, telegram first, then trade_tracker. A rollback needs its own
owner operational approval.

## Host evidence (not in Git)

- Stage 1: `~/ops/tsb-paper-observe-pkg/run-20261027T1044Z/` (`STAGE1_RESULT.md`, preflight, pre/post identity,
  hash gate, pause read, compose copy before the step).
- Stage 2: `~/ops/tsb-paper-observe-pkg/run-20261027T1149Z-stage2/` (`STAGE2_RESULT.md`, `VERSION_BOUNDARY.md`, same
  evidence set).

## Observations recorded during the deployment (not failures)

- Stage 2 preflight: the CI line first printed FAIL because of a quoting error in the check command itself; it was
  re-evaluated at 11:50Z with the corrected command (`40497476955 … main push success`). Both outputs are kept.
- Collector Docker health was `unhealthy` for about one minute around each step (DEGRADED 10:59–11:00Z and
  11:48–11:49Z), with `write_errors` 0. This is a pre-existing pattern (DEGRADED entries per day 2026-10-21..27:
  89, 62, 126, 49, 295, 59, 39, starting before Stage 1), investigated separately from Paper recovery.
