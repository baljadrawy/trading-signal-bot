# Stage A deployment manifest: Collector 1.6.1 (NOT AUTHORIZED, NOT DEPLOYED)

This manifest supersedes the r2/r3 wording of `RELEASE_CANDIDATES.md` §5 for Stage A. Execution needs a **separate
explicit owner approval** naming the option of `STAGE_A_RELEASE_STRATEGY.md` (O2a recommended). Nothing below has
been run against production.

## 1. Artifacts

| Item | Value |
|---|---|
| Candidate image | `tsb-p2-forward:p2f-161-72c0bee-20261022T1558Z` |
| Image ID | `sha256:89232400d5285b7a35d0fcba14965861c2b49e7c614c9bba7daa121504d68e5d` |
| Source | `main` `72c0bee82b44bede5192373d18374724f11c6c3a` (merge of #77; main CI run 39809795209 green), clean `git archive`, canonical `p2_forward/Dockerfile`, offline build with the pinned base |
| Version | `p2cr-collector-1.6.1`, `schema_version` 2, schema doc `SCHEMA-v2-c160a464.md` |
| Running image (rollback) | `tsb-p2-forward:p2f-160-1bfb5f6-20261014T0652Z` = `sha256:324d52c9b37a2ecd9a1ddace7e93ad5d7728411d98e8503abcd618f87c8f59e8` |
| Offline rollback archive | `~/backups/tsb-p2-forward-images/tsb-p2-forward_p2f-160-1bfb5f6-20261014T0652Z.tar` (created 2026-10-20), sha256 `32a5eb05ee4f8682207e004810264e6e3cea7725f7e4eeec26d704aae54b8d5b` (matches its `.sha256`). A byte-identical second copy `…running-1.6.0.tar` was made on 2026-10-22, with `…image-inspect.json` and `…SHA256SUMS`. |
| Archive verification (no `docker load`) | `index.json` → `sha256:324d52c9…` (OCI index, arm64 manifest `d97b5e06…`). All 14 blobs re-hashed to their names. The 8 layer diff-IDs equal the local image. RepoTag correct. |
| Original config | `~/ops/tsb-p2-forward/configs/continuous-v1.json`, sha256 `ebe6be133c51a01e57be1da25da6454846a0b3205b514b959251872fd4bd8d10`, mode 400. **Never edited.** |
| Proposed config (O2a) | **new file** `configs/continuous-v1-obs-lifecycle.json`, mode 400: the original line + `"ws_session_end_events": true`, sha256 `0db3f89d8e30639ec3f7bb19722fa931b49afa22b910b999f957d31abb25f53e` |
| Alternative (O2b) | `configs/continuous-v1-obs-both.json`, sha256 `ced616c48cef723e00b68d2514a13b54bb8ead6e4aabf98e37f15bbdb8a9c617` |
| Pre-Stage-A snapshot | `~/ops/tsb-p2-forward/backup-pre-stagea-20261022T161749Z/` (mode 700): config, `compose.yml` `06f32bc5…`, `p2f_continuous_up.sh` `7b2b9b9b…`, `p2f_continuous_stop.sh` `456ed24a…`, `p2f_ack_binding.py` `bf6b9188…`, `SHA256SUMS`. The gated scripts are byte-identical to `main`. |

## 2. Provenance checks (done, offline)

- Layers: 6 of 8 layer diff-IDs are identical to the running 1.6.0 (base and the pinned dependency layer). `pip freeze`, Python and every site-packages file are identical.
- `/app` vs 1.6.0: `app.py`, `config.py`, `transport.py`, `SCHEMA.md` changed; `flapping.py` added. vs r2: only `SCHEMA.md` and `config.py` (`VERSION`).
- The image package is byte-identical to the `72c0bee` source. User, Cmd, Entrypoint, Healthcheck and WorkingDir are identical to 1.6.0.

## 3. Expected `config_hash` transition (run record / health)

The method was validated: the hash computed for 1.6.0 from a copy of the production config equals the running health value `45296f7a443da177`.

| Image + config | `config_hash` |
|---|---|
| 1.6.0 + `continuous-v1.json` (today) | `45296f7a443da177` |
| 1.6.1 + `continuous-v1.json` (flags off) | `feb253c349c61c35` |
| **1.6.1 + `continuous-v1-obs-lifecycle.json` (O2a)** | **`6546b4795fa135e4`** |
| 1.6.1 + `continuous-v1-obs-both.json` (O2b) | `8cb5806e9efeb45e` |
| 1.6.0 + either obs file | **refused** (`unknown config keys`) |

Any other value after start is a STOP.

## 4. Validation of 1.6.1 (isolated, synthetic, `--network none`)

| Check | Result |
|---|---|
| Full collector suite in the image | 458 passed, 6 skipped. 2 errors need `git` (not in the image; green in CI). 1 load-sensitive throughput assertion (`test_g3_f3 …16s_certification…`, `durable_seen 9 > 50`) failed under full-suite load and **passed 3/3 alone on both 1.6.1 and r2**; green in CI on `72c0bee`. |
| Disabled (current config) | no new events, 0 incidents, days PASS |
| **O2a lifecycle only** | 20 `ws_session_end` (`stream_ended` 13, `local_end` 7), **no flapping events, 0 incidents**, days PASS |
| O2b clear path | flapping opened on both connections and resolved, 0 active at the end, days PASS |
| Rollback A: O2a → 1.6.0 → 1.6.1 | exit 0 in each phase, days PASS (1.6.0 verifier included), **0 incidents at every step** |
| Rollback B: O2b → 1.6.0 → 1.6.1 | the 2 `conn_flapping` WARNINGs **stay open under 1.6.0** and are resolved by the 1.6.1 re-forward |
| Schema | each run binds its own doc (1.6.1 → `SCHEMA-v2-c160a464.md`, 1.6.0 → `SCHEMA-v2-e7a641c3.md`), hash-verified; the new doc documents the events |
| P2-C reader (`8aaddc16`) | 5 datasets (including mixed 1.6.1/1.6.0 runs): every record validates; the new events are ingested |
| Resources (prod limits) | O2a: CPU mean 15.7 %, p95 25.0 %, memory peak 92.2 MiB, 7 PIDs (1.6.0: 14.8 %, 88.9 MiB, 7) |

## 5. Procedure (when approved; one service, Class B)

1. Evidence folder (mode 700): pre-identity of every running container, Collector health summary, incident severities, the files of §1 with sha256.
2. Preconditions (each a STOP if false):
   - no research job active (`rj-*` units none, heavy/light locks free);
   - no active CRITICAL or DEGRADED; the 3 WARNINGs unchanged;
   - the window is ≥ 30 min from the UTC day close and the 23:10/00:10 rotations, and outside universe refresh;
   - no Paper change in the previous 72 h;
   - the candidate image ID equals §1;
   - the archive sha256 re-verified.
3. Create the new config file (§1, mode 400). Verify its sha256 = `0db3f89d…`.
4. `~/ops/tsb-p2-forward/p2f_continuous_stop.sh <dataset> ~/ops/tsb-p2-forward/compose.yml` → expect a clean stop marker.
5. `~/ops/tsb-p2-forward/p2f_continuous_up.sh tsb-p2-forward:p2f-161-72c0bee-20261022T1558Z sha256:89232400… <dataset> ~/ops/tsb-p2-forward/configs/continuous-v1-obs-lifecycle.json ~/ops/tsb-p2-forward/compose.yml` → expect `UP OK`. The script itself refuses on an image mismatch, a restart policy other than `no`, isolation failures and an unclean previous run.

## 6. Acceptance checklist

| When | Check | Pass |
|---|---|---|
| T+2 min | container image ID = `89232400…`; restart policy `no`; health `STARTING` → `HEALTHY` | ☐ |
| T+10 min | `HEALTHY`; run record `build.git_commit` = `72c0bee…`, `collector_version` 1.6.1, `config_hash` = `6546b4795fa135e4`; no new CRITICAL or DEGRADED; the 3 WARNINGs unchanged; downtime record present; the Collector monitor is not `STOPPED` | ☐ |
| T+1 h | the `ws_session_end` count matches the ended sessions (health reconnect counters); no write or emit errors; CPU and memory within ±10 % of the pre-deploy baseline | ☐ |
| T+24 h | the deploy day seals PASS with the downtime record and 0 unexplained gaps; daily backup + restore-test OK | ☐ |
| T+72 h (window end) | no seal failure; no incident attributable to the release; resources stable | ☐ |

**Rollback triggers:**
- startup refused;
- not `HEALTHY` 10 min after start, outside a corroborated exchange outage;
- any CRITICAL or DEGRADED attributable to the release;
- `config_hash` ≠ `6546b479…`;
- verifier or seal FAIL;
- write or emit errors;
- resources over limits.

**Rollback:**
- **Soft:** stop, then start the same image with `continuous-v1.json`. This is the 1.6.0 behaviour; expect `config_hash` `feb253c3…`.
- **Full:** stop, then start `tsb-p2-forward:p2f-160-1bfb5f6-20261014T0652Z` / `sha256:324d52c9…` with **`continuous-v1.json`** (1.6.0 refuses the obs file); expect `config_hash` `45296f7a…`.
- If the local image is lost: `docker load -i` the verified archive, then check the image ID before starting.
- O2a creates no incident, so a rollback leaves nothing to dispose of.
