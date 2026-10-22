# Release candidates 2026-10-22: Collector observability (#76), signal_engine telemetry (#74), runner R2 (#71)

**Status: candidates built and validated in isolation. NOTHING IS DEPLOYED.**

No production container, image tag, configuration, database, incident or dataset was changed. A before/after identity
capture of every running container (ID, image, start time, restart count) was identical. Each stage below needs its
own explicit owner approval, and the stages must not overlap.

## Status update (2026-10-22, release gates round)

| Item | State |
|---|---|
| **Stage C** | **APPLIED and validated** (owner-authorized). Installed `config.py` `e7a557b7…` → `e380eae6…`; backup kept. See `STAGE_C_RECORD.md`. |
| #77 (SCHEMA.md + VERSION 1.6.1) | **merged** as `72c0bee` after all gates; main CI green |
| Stage A candidate | **Collector 1.6.1** `sha256:89232400…` replaces RC-A r2. See `STAGE_A_MANIFEST.md`. Not deployed. |
| Stage A strategy | O2a recommended: one restart, lifecycle logging on, flapping off. See `STAGE_A_RELEASE_STRATEGY.md`. |
| Collector 1.6.0 archive | already present (2026-10-20) and **verified**; the earlier "none exists" statement is corrected below |
| Development | #80 admission budget I-1 (24 tests, mutation-checked); #78 + P1 corpus / P2 boundaries; #81 rotation flake fix |
| Stage B | RC-B preserved, unchanged. Database-read request in `STAGE_B_DB_READ_REQUEST.md`. Not deployed. |

## 1. Verified baseline (2026-10-22, read-only)

| Item | Value |
|---|---|
| `main` | `0abb22d1096bce8e514cdedf6c4d0fa2b4bea745`. CI run 39695088373 green. |
| Collector | container `65b152109ca3`, image `tsb-p2-forward:p2f-160-1bfb5f6-20261014T0652Z` = `sha256:324d52c9b37a2ecd9a1ddace7e93ad5d7728411d98e8503abcd618f87c8f59e8`, started 2026-10-20T08:26Z, 0 restarts. `HEALTHY`; incidents 0 CRITICAL, 0 DEGRADED, 3 WARNING (kept unacknowledged as directed). |
| Collector config | `~/ops/tsb-p2-forward/configs/continuous-v1.json`, 7 keys, sha256 `ebe6be133c51a01e57be1da25da6454846a0b3205b514b959251872fd4bd8d10`. None of the #76 keys is present. |
| signal_engine | `tsb-a561-signal_engine:rel-ea8ae4f-r2` = `sha256:c5be4e34c064c707cb421c2f5d26c38dfee8ad75f36d7e3b177be88d4a825418` (overlay chain, source `ea8ae4f`) |
| Other Paper services | analyzer `011f99ba…`, telegram `51d62f4d…`, trade_tracker `2cf1dd52…`, scanner `63b38e7a…`. All unchanged and out of scope. |
| Compose (prod) | blob `04f965ef…` = `main` |
| Host Collector scripts | `p2f_continuous_up.sh` and `p2f_continuous_stop.sh` are byte-identical to `main`. |
| Research runner | All installed files equal `main` except `research_exec/config.py` (pre-#71: R2 = 6 workers / 600 %) |
| Canary watchdog | The installed file equals `research/ops/canary_watchdog.py`. `STALE_SECONDS = 600`. |

### Deployment delta (running vs `main`)

| Component | Running | `main` delta | In this release |
|---|---|---|---|
| Collector package | 1.6.0 @ `1bfb5f6` | #76: `app.py`, `config.py`, `transport.py` changed; `flapping.py` new. All off by default. | **RC-A** (Stage A) |
| signal_engine | `ea8ae4f` overlay | #74 (`recorder.py`, `signal_logic.py`, one `config.py` field) **and** #59 (`t1_cap.py`, `strategy_math.py`, `trade_geometry.py`, `T1_CAP_POLICY`) | **RC-B** carries #74 only. #59 is excluded (§3). |
| analyzer | `ea8ae4f` overlay | #59 (dormant T1 cap policy flag) | Not released (no approved need) |
| Research runner | pre-#71 | #71: R2 5 / 500 % | **Stage C** |
| Compose | = `main` | none | Stage B changes one `image:` line and adds one env var |

## 2. RC-A: Collector

| | |
|---|---|
| Tag | `tsb-p2-forward:p2f-rc-0abb22d-20261022T0713Z-r2` |
| Image ID | `sha256:c5f30d556827e04478533f49f17fd82c4cb2090f06c9c34cec4967a8bae7acc5` |
| Source | `main` `0abb22d`, `git archive` (clean export), canonical `p2_forward/Dockerfile` |
| Base | `python@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9` (same as running) |
| Baked provenance | `P2F_GIT_COMMIT=0abb22d1…`, `P2F_IMAGE_TAG=<tag>`, `P2F_BUILD_TIME` ISO-8601 (2026-10-22T07:13Z) |

Provenance checks (all offline, `--network none`):

| Check | Result |
|---|---|
| Layers vs running 1.6.0 | 6 of 8 layer diff-IDs identical (base and the pinned `pip install` layer), so the dependency layer is **byte-identical**. |
| `pip freeze --all`, Python, every site-packages file | identical to running |
| `/app` tree vs running | exactly 4 files differ: `app.py`, `config.py`, `transport.py` changed, `flapping.py` added |
| `/app` package vs `main` source | identical (sha256 per file) |
| User, Cmd, Entrypoint, Healthcheck | identical to running |
| Superseded build | `…-20261022T0713Z` (`sha256:6abf708d…`) has identical layers but a compact `P2F_BUILD_TIME`. Do not deploy it; it is kept, not deleted. |

## 3. RC-B: signal_engine

| | |
|---|---|
| Tag | `tsb-a561-signal_engine:rc-b-37a7c2c-20261022T0725Z` |
| Image ID | `sha256:11e81d5dd9babb82a33960b47839bbf8a8f8bf3d17e25e4c5cba1e1404f7c833` |
| Source commit | `37a7c2c7080e259f9550b957ce6cb1ac623ae19a` on `release/rc-b-se-telemetry-on-ea8ae4f`. Base `ea8ae4f` (the running source) plus #74 only. CI run 39742463015 green (default suite and PostgreSQL matrix). |
| Build | Minimal overlay `FROM tsb-a561-signal_engine:rel-ea8ae4f-r2` (the tag was verified to resolve to `c5be4e34…` first). Three `COPY` with the running owners and modes. Labels: `org.opencontainers.image.revision=37a7c2c…`, `tsb.rc.base_image_id`, `tsb.rc.delta`. |

| File in image | Source | sha256 |
|---|---|---|
| `/app/research/null_a/recorder.py` (664) | identical to #74 (`0457f04..6b0f226`) | `57aa7aeb…` |
| `/app/signal_logic.py` (775) | identical to #74 (one line) | `613036d4…` |
| `/app/shared/config.py` (775) | `ea8ae4f` + **only** `EVIDENCE_TELEMETRY_MIN_INTERVAL_S` | `342af91e…` |

**Why `config.py` is not the `main` blob.** `shared/evidence_v2.strategy_config_snapshot` hashes **every** non-`EVIDENCE*`
Config field into the `config_hash` stamped on every signal_engine evidence event. The `main` blob also adds the #59
field `T1_CAP_POLICY`, which nothing in this image reads. It would still change `config_hash`, which is an unintended
#59 lineage effect. Measured offline with default env:

| Variant | Config fields hashed | `config_hash` |
|---|---|---|
| running image | 73 | `35d8ba8e07d1fceb…` |
| `main` `config.py` | 74 (`T1_CAP_POLICY`) | `cd3ef9622ff1a49b…` (**changes**) |
| RC-B `config.py` | 73 | `35d8ba8e07d1fceb…` (**unchanged**) |

`code_sha` changes from `e5b3c1266313eacb…` to `5320f56aecf8cff2…`, as for any code change. That is a lineage boundary
to declare at deployment. No #59 runtime file is present: `t1_cap.py` is absent, and `strategy_math.py` stays dormant
as in the running image.

Provenance checks:

| Check | Result |
|---|---|
| Layers | The 24 base layer diff-IDs are identical to the running image; 3 layers are added. |
| Full filesystem (13,308 files) | Only the 3 intended files differ; `/etc/hostname` differs per container. Modes and owners under `/app` are identical. |
| `pip freeze --all` (51 lines) | identical. **aiohttp 3.14.3** (same wheel sha256 `f631fe87…`). Python 3.12.13. |
| `runtime_manifest.py generate` against `37a7c2c` | 56/56 `match`, 0 assembled, 0 unknown. Dormant files are the same as running. The 49 installed distributions are identical. Summary in `rc_b_manifest_summary.json`. |
| Runtime config | User, WorkingDir, Cmd, Entrypoint, Env, Healthcheck identical |

## 4. Isolated validation (synthetic only)

Every run used `--network none`, a read-only root, a tmpfs, no production mount and no production env. Tests ran on
the **unmodified RC images**. pytest was mounted read-only, and the repository tests were mounted read-only. Five tests
that need real dataset metadata **skipped** in the containers, which confirms that no protected data was reachable.

### Collector (RC-A)

| Area | Evidence | Result |
|---|---|---|
| Full collector suite in the RC image | `main` tests, package resolved to `/app/p2_forward` | **458 passed**, 6 skipped. 1 failure and 2 errors are environment-only: `ProcessRoles` expects foreign host processes in `/proc`, and `BeforeAfter` needs a `git` binary absent from the image. All three ran green in CI on `0abb22d`. A first run on a `noexec` tmpfs showed 5 more failures; they were a harness artifact (stub `docker` not executable) and passed on rerun. |
| Startup / shutdown | `Collector.run` continuous e2e, fake exchange | exit 0, clean stop, every closed day **PASS** with the unchanged verifier |
| Disabled-default | same flapping exchange, no flags | No `ws_session_end` or `conn_flapping*` events, 0 incidents. Lifecycle profile is otherwise identical. |
| Enabled lifecycle instrumentation | flags on, sockets dropping for 25 s | 17–21 `ws_session_end` per run: `stream_ended` for the drops, `local_end` for planned rotations. No end was labelled remote without evidence. |
| Flapping detection | window 15 s / max 3 / clear 12 s | `conn_flapping_open` on both connections, then `conn_flapping_resolved` after quiet. 0 active incidents at the end. WARNING only; health never DEGRADED. |
| Evidence integrity / certification | `verify_day` on every closed day of every run | PASS, 0 failures, including days with the new lifecycle events |
| Downstream reader | P2-C `reader.py` (`8aaddc16`) on 4 synthetic datasets | every record validates; control ingestion accepts the new events |
| Rollback 1.6.0 into an RC dataset | running image `324d52c9…`, same dataset, current config | exit 0. Days PASS with the **1.6.0** verifier. The open `conn_flapping` WARNINGs **stay open** (1.6.0 has no resolver). |
| Re-forward | RC again on the same dataset | resolves previous-boot `conn_flapping` incidents |
| Config compatibility | `config.load()` matrix | 1.6.0 + current config: loads. 1.6.0 + new keys: **REFUSED** (`unknown config keys`). RC + either: loads; defaults off. |
| `rotation_handoff_incomplete` WARNING seen once | same scenario, flags off, RC vs 1.6.0 | It also occurs on unmodified 1.6.0 (1 of 2 runs): a timing artifact of the synthetic drops, not #76 |
| Resources (prod limits 1.5 CPU / 768 MiB / 64 PIDs) | 45 s e2e, sampled every 2 s | 1.6.0: CPU mean 14.8 %, memory peak 88.9 MiB, 7 PIDs. RC with flags on: 14.6 %, 90.7 MiB, 7 PIDs. Suite peak 135 % / 174 MiB. |

### signal_engine (RC-B)

| Area | Evidence | Result |
|---|---|---|
| Existing recorder tests on image bits | 5 files, 29 tests | running 29/29, RC 29/29 |
| #74 tests on image bits | `test_evidence_telemetry_interval.py` | RC 6/6 (total 35/35) |
| Release-branch CI | default suite and PostgreSQL matrix on `37a7c2c` | green |
| Real wiring | `signal_logic.get_evidence_recorder()` and the real `run_flusher()` task; 12 s, flush 0.25 s | see the next table |

| Setting | `_telemetry.json` writes | Bytes written | Worst staleness | History length | Alarm write lag | Shutdown write |
|---|---|---|---|---|---|---|
| running image | 48 | 528 KB | 0.21 s | 48 | 0.049 s | yes |
| RC, unset (default) | 48 | 528 KB | 0.21 s | 48 | – | yes |
| RC, `=0` | 48 | 529 KB | 0.20 s | 48 | – | yes |
| RC, `=3` s | **5** | **56 KB** | 3.0 s | 48 (no snapshot lost) | 0.023 s | yes |

The default is identical to running. With the interval set, writes drop by the interval/flush ratio, freshness is bounded
by the interval, alarm counters are written at once, and the schema (13 keys) is unchanged. In production (flush 5 s,
proposed interval 60 s): about 12× fewer rewrites (about 178 MB/h → about 15 MB/h) and worst-case file age about 65 s,
against the watchdog's 600 s.

## 5. Staged deployment proposal

Rules for every stage:
- one stage per window;
- the Collector and Paper are never changed in the same window;
- every step is Class B (`docs/ops/COMPOSE_OPERATIONS.md`): pre-identity capture into a mode-700 evidence folder, one
  command, post-checks, STOP on any deviation;
- no incident acknowledgment is part of any stage.

### Stage A: Collector observability

| | |
|---|---|
| Artifact | **Recommended:** RC-A **r3**, rebuilt from the merge of Draft PR #77. #77 documents the new events in `SCHEMA.md` (the dataset contract shipped in the image) and sets `VERSION` 1.6.1; there is no behaviour change. **Available now:** RC-A r2 `sha256:c5f30d55…`. Its only gap is that `SCHEMA.md` does not document the new events. |
| Config | A **new file** `configs/continuous-v1-obs.json` = the current 7 keys + `"ws_session_end_events": true` + `"conn_flapping_enabled": true`. Keep the defaults window 1800 s / max 10 / clear 1800 s; do not lower `max`, since a continuous outage reaches about 8 attempts per 30 min. The original file is never edited. |
| Procedure | `p2f_continuous_stop.sh <dataset> <compose>`, then `p2f_continuous_up.sh <rc tag> <rc image id> <dataset> <new config> <compose>` |
| Expected benefit | Each disconnect is classified (peer close code, 1006 abnormal, local, ping timeout), which answers the open question of the 2026-10-21 episode (close codes were not recorded). A `conn_flapping` WARNING appears within about 30 min of an episode like 13:34–16:42Z (193 + 58 disconnects). |
| Downtime / gap | One restart. The A36 image swap measured 33.6 s of data downtime; expect 30–60 s, worst case the 450 s stop grace. The gap is recorded as a `downtime` record, and the day seals PASS (A36, 2026-10-19). |
| Preconditions | 1. Offline archive of the running 1.6.0 image: **exists and verified** (see `STAGE_A_MANIFEST.md`; the `IMAGES.md` gap of 10-18 was closed on 10-20). 2. No research run active: STOPPING/STOPPED refuses admission and freezes running work. 3. No active CRITICAL; the 3 WARNINGs unchanged. 4. Window away from the UTC day close, the 23:10/00:10 rotations and universe refresh. 5. Not within 72 h of a Stage B change. |
| Acceptance | **T+10 min:** `HEALTHY`; run record `build.git_commit` = RC commit; image ID as approved; no new CRITICAL or DEGRADED. **T+24 h:** the deploy day seals PASS with the downtime record and 0 unexplained gaps; `ws_session_end` count is consistent with health reconnect counters; no `conn_flapping` without ≥ 10 ended sessions in 30 min. **T+72 h (monitoring window):** CPU and memory within ±10 % of the pre-deploy baseline; no seal failure. |
| Rollback triggers | Startup refused; not `HEALTHY` 10 min after start (outside a corroborated exchange outage); any CRITICAL or DEGRADED attributable to the release; verifier or seal FAIL; write or emit errors; resources over limits. |
| Rollback | **Soft:** the same RC with the original config (flags off) behaves like 1.6.0. **Full:** stop, then `p2f_continuous_up.sh` with `324d52c9…` **and the original `continuous-v1.json`**; 1.6.0 refuses the new keys. Open `conn_flapping` WARNINGs then stay open until owner disposition; they are never acknowledged automatically. |

### Stage B: signal_engine telemetry write reduction

| | |
|---|---|
| Artifact | RC-B `tsb-a561-signal_engine:rc-b-37a7c2c-20261022T0725Z` = `sha256:11e81d5dd9babb82a33960b47839bbf8a8f8bf3d17e25e4c5cba1e1404f7c833` |
| Config | Compose (repository PR, then the production file): signal_engine `image:` = RC-B tag (rollback comment `rel-ea8ae4f-r2`), plus `EVIDENCE_TELEMETRY_MIN_INTERVAL_S: "60"`. Update `deploy/DEPLOYED.json` (D3/D4 baseline). |
| Procedure | `docker compose -p trading-signal-bot -f docker-compose.yml up -d --no-deps --no-build --pull never --force-recreate signal_engine` |
| Expected benefit | `_telemetry.json` rewrites go from every 5 s to every 60 s: about 12× fewer writes (≈178 → ≈15 MB/h). Alarms are still written at once. The history and schema are unchanged. |
| Freshness verification | file age ≤ 65 s at every check; canary watchdog never `STALE` (600 s) |
| Downtime | One recreate, about 10–20 s. Schedule mid-interval, away from 15m/4h/1d candle closes. telegram and trade_tracker are not touched. |
| Preconditions | 1. Class B pre-gate: PAPER_HALTED/B3 state from an **owner-approved database read** (required by `COMPOSE_OPERATIONS.md`). 2. Learner stopped. 3. `$DC config --hash signal_engine` equals the reviewed value. 4. Not within 72 h of Stage A. 5. Declare the `code_sha` lineage boundary in the ops record. |
| Acceptance | Healthy on two consecutive reads. No `evidence recorder unavailable` in logs. Telemetry `evidence_captured_total` keeps increasing and `evidence_flush_failures` / `evidence_dropped_records` are unchanged. Events carry the new `code_sha` and an **unchanged** `config_hash`. Block-I/O over 1 h well below the pre-deploy hour. Monitoring window 24 h. |
| Rollback triggers | unhealthy; watchdog `STALE`; recorder unavailable; flush failures or drops rise; any signal-path exception; `config_hash` changed |
| Rollback | Compose `image:` back to `rel-ea8ae4f-r2` (`c5be4e34…`), same canonical recreate. The leftover env var is ignored by the old Config. |

### Stage C: research runner R2 correction (#71)

| | |
|---|---|
| Artifact | `ops/research/research_exec/config.py` @ `0abb22d`: git blob `25b522cfeec3cb9d6e068b8898978f24370919f7`, sha256 `e380eae69a89c229d4f36e0f0c294f4d00256367ea20188c740d01dffde49d1e` |
| Installed now | blob `cc97e722…` (pre-#71), sha256 `e7a557b7b218dd89850d860ce60cacc3f4341666f9bf56cc7b9cde8c818a922d` |
| Change | R2 workers 6 → 5, CPU quota 600 % → 500 % (owner budget 2026-10-20) |
| Expected benefit | Elevated research runs stay within the approved 5 vCPU and leave headroom for the Collector and Paper |
| Downtime | none. Host file read per runner invocation; no service, unit or cron change. |
| Preconditions | no research run active (heavy lock free); backup copy with sha256; not during a Stage A window |
| Acceptance | installed sha256 = `e380eae6…`; resolving profile R2 from the installed copy gives 5 / 500 %; all other runner files unchanged |
| Rollback | restore the backup (sha256 `e7a557b7…`) |

### Recommended order

1. **Stage C** (no downtime, no service).
2. Merge #77, rebuild RC-A r3, rerun §4 (automated, about 30 min).
3. **Stage A**, then its 72 h window.
4. **Stage B** after Stage A is accepted.

Stage B can go before Stage A if write reduction is the priority. It must never share a window with Stage A.

## 6. Release-readiness matrix

| Item | Ready to deploy | Ready to activate | Requires additional validation | Requires owner approval |
|---|---|---|---|---|
| RC-A r2 (flags off) | yes | n/a (nothing to activate) | no | **yes** (Class B) |
| #76 flags in production | – | **no** until #77 → r3 (or the owner accepts the doc gap on r2) | r3 rerun of §4 | **yes** |
| RC-B with interval 60 s | yes | yes (validated) | no | **yes**, plus the database read for the halt-state pre-gate |
| Stage C runner file | yes | yes | no | **yes** |
| Draft PR #77 (SCHEMA/VERSION) | – | – | CI | merge approval |
| Rotation e2e flake (`market_component_stale`) | – | – | fixed in Draft #81 (cause measured per overlap; see §8) | merge approval |
| Draft PR #78 (lab P5/P6b guards, stacked on #67) | – | – | CI | merge approval, after the #67 review |
| Canonical image plan | design only | – | – | each phase |
| #59 T1 cap policy | **not released** | no (strategy boundary) | – | **yes**, separately |

**Blockers:**
1. Stage B Class B pre-gate needs an owner-approved database read.
2. Activating the #76 flags is blocked on #77 and the r3 rebuild.
3. ~~No offline archive of the running Collector image~~ **Corrected:** `~/backups/tsb-p2-forward-images/…T0652Z.tar` (sha256 `32a5eb05…`, created 2026-10-20) was already present; it was verified on 2026-10-22.
4. The two mandatory independent external reviews are still outstanding; nothing here substitutes for them.

## 7. Operational risks

| Risk | Mitigation |
|---|---|
| Collector restart gap (30–60 s of irreplaceable data) | single restart; recorded downtime; window away from boundaries |
| `conn_flapping` counts planned rotations and failed connects | about 1 rotation per connection per 23 h; outage attempts ≤ 8/30 min < 10; WARNING only; research admission allows WARNING |
| Rollback leaves `conn_flapping` WARNING open | documented; owner disposition; RC re-forward resolves it |
| Rollback with the new config file | separate config path; rollback uses the original file |
| Collector `config_hash` changes even with flags off (`58544062…` → `4597aed3…`: new defaults are hashed) | expected run-record boundary; no consumer pins it |
| signal_engine `code_sha` boundary | declared in the ops record; `config_hash` unchanged |
| Overlay chain grows by 3 layers | interim rule; see `docs/ops/CANONICAL_IMAGE_REMEDIATION_PLAN.md` |

## 8. Development continuation (no activation, no governed research)

| Item | Output | State |
|---|---|---|
| #76 dataset contract gap | Draft PR #77: `SCHEMA.md` documents `ws_session_end` / `conn_flapping*` and the rollback limits; `VERSION` 1.6.1 | awaiting review |
| Strategy Lab parity | Draft PR #78, stacked on #67: P5 shared-module blob pins + P6b production isolation. 42 tests pass, mutation-checked. It also records two spec path corrections. P1–P4, P7 and F1–F10 need the lab adapter, which is not written. | awaiting the #67 review |
| Admission controller | `docs/ops/RESEARCH_ADMISSION_CONTROLLER_IMPLEMENTATION_PLAN.md`: `budget.py` with injected probes, integration seams, a 1:1 test map, rollout I-1…I-5 (shadow mode first) | plan only |
| Canonical images | `docs/ops/CANONICAL_IMAGE_REMEDIATION_PLAN.md` | design only |
| Rotation e2e flake | **Correction:** the earlier per-run A/B was underpowered, and calling the fix "falsified" was wrong. Per-overlap instrumentation (12 runs × 3 overlaps): original 10/36 overlaps without a stale copy (one run 0/3 = the failure), fixed 0/36. Draft #81. | awaiting review |
| Independent external reviews | Packages A/B were prepared earlier; still mandatory and outstanding | not substitutable |

## 9. Reproduce

The scripts are in `validation/`. Run them with `--network none` and synthetic data only:
- `tel_harness.py`: Stage B wiring and telemetry measurement;
- `flap_e2e.py`: Collector continuous e2e; `rc` and `rollback` phases; `OVER`, `FLAP_S`, `CAL_H0`, `NO_FLAP` env;
- `reader_check.py`: P2-C reader over synthetic datasets.
