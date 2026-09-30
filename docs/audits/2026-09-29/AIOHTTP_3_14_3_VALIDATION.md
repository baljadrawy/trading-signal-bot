# AIOHTTP_3_14_3_VALIDATION — security remediation aiohttp 3.13.5 → 3.14.3 (isolated; NOT deployed)

**Verdict: THIN-OVERLAY VALIDATION PASS. Deployment NOT included; it needs a separate owner approval.**

> **Status update 2026-09-30 (added; the historical text below is unchanged):** telegram, trade_tracker and scanner are now DEPLOYED on the validated overlays. analyzer, signal_engine and claude_review are validated but NOT deployed. See §10.

Scope: the security fix only (GHSA-cq5v-8q36-5273 / CVE-2026-69244 HIGH and 13 other advisories). Isolated on the shared host. No production container, image, tag, requirements file, database or trading state was changed. PAPER_HALTED (B3 row `2026-09-11 · risk:loss_streak_halt · 29415`) and the stopped learner were verified before and after.

## 1. Audit trail (every STOP preserved)

| # | Event | Disposition |
|---|---|---|
| STOP #1: AIO-2 | A normal dependency resolution of the requirements (3.13.5 **or** 3.14.3) drifts 6–21 unrelated transitive packages per service versus production. Examples: yarl, multidict, propcache, idna, ujson 5→6, websockets, dateparser, regex, pytz, urllib3, numpy 2.5.2→2.5.3, filelock 3→4, and the anthropic/httpx chain. aiohttp 3.14.3 requires none of these changes. | **Normal rebuild path BLOCKED.** The owner approved the thin-overlay path (AIO-2B). |
| STOP #2: AIO-2B.3 | BuildKit rejected `FROM sha256:<id>`: it looked up a Docker Hub repository named `library/sha256`, and access was denied; nothing was pulled. | The build recipe was corrected, after separate owner approval, to use **exact-image temporary local tags** `tsb-aiohttp-base-<svc>:20260929`. |
| STOP #3: original HG4 | The combined filesystem hash differed. A read-only diagnosis found the only non-aiohttp difference was `/etc/hostname`, which Docker bind-mounts into each container at runtime (proven from `/proc/self/mountinfo` and by identical content under the same `--hostname`). | Validation method corrected after owner approval. Revised HG4: layer inspection is primary; per-file manifests exclude only runtime mounts proven per container. |
| STOP #4: HG2 (scanner) | **Reporting correction:** the diagnosis report wrongly said the overlay had *one* appended layer. The revised HG2 correctly detected **two** content layers (COPY and RUN). Execution stopped. | The owner authorized a read-only inspection of both layers. The gate was corrected to exactly two layers only after exact evidence. No production change occurred. |

## 2. Artifact

- `aiohttp-3.14.3-cp312-cp312-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl`
- Official PyPI `bdist_wheel`, not yanked, 1,765,282 bytes.
- **SHA-256 `f631fe87a6f30df5fbe6d79640b25e4cffb38c31c7fb6f10871517b84b0f8c1a`**, re-verified before reuse.
- Tags: cp312-cp312 manylinux_2_17/2014/2_28 aarch64. Every production image is Python 3.12.13, glibc 2.41, aarch64.

## 3. Overlay method and gates (per service, independently)

- **Base:** the exact production image, through a temporary local tag.
- **Build:** `docker build --network=none --pull=false`. `COPY` the wheel to `/tmp/overlay`, then `RUN sha256sum -c && pip install --no-deps --no-index --no-cache-dir <wheel> && rm -rf /tmp/overlay`, then restore `USER appuser`. The mechanism is in `deploy/security-overlay/aiohttp-3.14.3/`.

| Service | Production image ID | Overlay image ID (tag `tsb-aiohttp-test-<svc>:3.14.3-20260929T124120Z`) | RootFS prefix | Layer A (COPY) | Layer B (RUN) | aiohttp | Other package diff | App hash | HG5 | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| scanner | `9b0b53a6a799` | `63b38e7a659d` | MATCH (+2) | wheel only, SHA match | aiohttp only | 3.14.3 | NONE | MATCH (23) | PASS | PASS |
| analyzer | `ce305ecd7760` | `47877db4cfe8` | MATCH (+2) | wheel only, SHA match | aiohttp only | 3.14.3 | NONE | MATCH (28) | PASS | PASS |
| signal_engine | `b3d4b6236654` | `4b7f4a58073a` | MATCH (+2) | wheel only, SHA match | aiohttp only | 3.14.3 | NONE | MATCH (37) | PASS | PASS |
| trade_tracker | `2b59c6a164c0` | `af063314973e` | MATCH (+2) | wheel only, SHA match | aiohttp only | 3.14.3 | NONE | MATCH (29) | PASS | PASS |
| telegram | `b84d3d1528a0` | `ef80d11c6579` | MATCH (+2) | wheel only, SHA match | aiohttp only | 3.14.3 | NONE | MATCH (28) | PASS | PASS |
| claude_review | `8bca25750c77` | `aaeb0467815a` | MATCH (+2) | wheel only, SHA match | aiohttp only | 3.14.3 | NONE | MATCH (17) | PASS | PASS |

**Evidence per service:**
- Layer A has 3 entries: `tmp`, `tmp/overlay` and the wheel.
- Layer B has 150 entries: `site-packages/aiohttp/**`, `aiohttp-3.14.3.dist-info/**`, and deletion markers for `aiohttp-3.13.5.dist-info` and `/tmp/overlay`.
- The final filesystem has no `/tmp/overlay`.
- Of the 139 per-file differences, 138 are aiohttp-owned. The only other is `/etc/hostname`, a runtime mount proven by that container's mountinfo.
- Package inventory: only `aiohttp 3.13.5 → 3.14.3`; pip, setuptools, wheel, yarl, multidict, propcache, python-binance, websockets and numpy are unchanged.
- Python, architecture, Env, Cmd, Entrypoint, User, WorkingDir, Healthcheck and Labels are identical.
- **OCI note:** the wheel bytes stay in immutable layer A, even though the later layer removes them from the final filesystem. This is acceptable **only** because the file is a public, hash-verified artifact. It must never be generalized to secrets or private files.

## 4. Tests (isolated: `--network none`, resource-limited, mocks only; no credentials, orders, database or holdout)

| Group | Result |
|---|---|
| Regression: develop suite, in `tsb-aiohttp-test-pytestenv:3.14.3` (`41376d253885`; `tsb-sync-test:pytest` plus the same wheel; package diff aiohttp only) | **292 passed, 21 skipped, 8.33 s**. Identical to the 3.13.5 control (292/21, 8.16 s). Skips: 19 DB tests (`RISK_TEST_DSN` unset; no database contacted) and 2 that need python-telegram-bot. |
| Full suite plus the new compat file on 3.14.3 | 302 passed, 22 skipped, 49.4 s |
| python-binance 1.0.19: the real `AsyncClient.create` / `_init_session(loop=)` | PASS in scanner, analyzer, signal_engine and trade_tracker. Ping, klines and depth hit the right paths and params; `X-MBX-APIKEY` is absent without a key and present with a dummy key; a 400 raises `BinanceAPIException`; the timeout fires at 0.50 s; `close_connection` is clean; **0 warnings**. |
| trade_tracker WebSocket (production `/app/binance_price_stream.py` against a local server) | PASS: connect, subscribe, aggTrade → callback, dedup, ping/pong, server close → reconnect after the 5 s backoff, clean cancel (CLOSE 1000), heartbeat active. **Finding:** production `ws_connect` uses `compress=0` on both versions, so no permissive deflate is negotiated. A compressed-frame case with `compress=15` also passed. |
| Direct aiohttp paths (hard-coded URLs rewritten to a local server at `ClientSession._request`; each function's own calls and kwargs unchanged) | PASS: `shared/alerts.send_alert` in all 6 overlays (200, 400, `ClientTimeout(10)`); tracker `get_current_price`, `get_min_notional` and `get_last_closed_candle` (200, 5xx/429, 5 s timeout); telegram `get_current_price`. The whitelist lookup is DB-only (it imports aiohttp but uses no network). Only static headers are used, and 3.14.3 rejects a CR/LF header value. |
| claude_review | PASS: imports; the aiohttp exception classes used by `retry_utils` exist |
| Version | aiohttp 3.14.3 and only `aiohttp-3.14.3.dist-info` in every overlay |
| Compat totals | 34 cases: 34 PASS, 0 FAIL, 0 SKIP |

**Recorded harness notes:**
- The new test's first run wrongly expected deflate to be negotiated, and the assertion was corrected to match the default (`compress=0`, the same on 3.13.5). The first-run log is kept. **No existing test was changed or weakened.**
- The 2 PTB-dependent suite tests did not run in the telegram overlay, because it has no pytest and nothing was installed. The telegram aiohttp paths are covered by the compat cases.

Test file: `tests/test_aiohttp_314_compat.py`. Evidence: `/home/tradmin/backups/tsb-aiohttp-20260929T122701Z/` (`deps/`, `overlay/`, `tests/RESULTS.md`, logs).

## 5. Resources

- Every container ran with `--network none` (except the dependency-resolution dry-run in STOP #1), ≤1–2 CPUs and ≤1–2 GiB each, never above the ≤3 CPU / ≤4 GiB envelope.
- Load stayed below 2.5.
- Seven test images were added: 6 overlays and the pytestenv. Nothing was pruned.

## 6. Production-drift and deployment method

| Option | Code drift | Package drift | Reproducibility | Rollback | Verdict |
|---|---|---|---|---|---|
| A. Normal rebuild from the branch | **Yes**: production differs from develop in scanner, analyzer, signal_engine and claude_review (older blobs and 3 unversioned files) | **Yes**: 6–21 packages per service (STOP #1) | poor (no lockfile) | image IDs | **BLOCKED** |
| B. Thin overlay on the exact production images | **None** (`/app` byte-identical) | **None** (aiohttp only) | hash-pinned wheel, exact base, gated procedure | previous image IDs unchanged locally | **RECOMMENDED** |

**Proposed future deployment** (not executed; needs owner approval):
- Retag each service's production `:latest` to its validated overlay ID, keeping rollback tags `aiohttp-rollback/<svc>:pre-3.14.3` pointing at the current IDs.
- Recreate **one service at a time** with `docker compose up -d --no-deps --no-build --pull never --force-recreate <svc>`, and verify fresh health before the next.
- Order: **claude_review → telegram → analyzer → signal_engine → trade_tracker → scanner (last)**, the lowest blast radius first and the B3-runbook ending.
- The learner is never started. PAPER_HALTED is re-verified after each step.
- **Caveat:** recreating analyzer, signal_engine and claude_review applies the known compose-configuration drift (P0 finding D3). The owner must acknowledge this, or approve a drift-neutral method, before deployment.

## 7. Rollback matrix (database/schema impact: NONE for all)

| Container | Current production image | Overlay candidate | Rollback image | Recreation required | Stateful implications |
|---|---|---|---|---|---|
| trading_scanner | `9b0b53a6a799` | `63b38e7a659d` | `9b0b53a6a799` (also in the Phase-0 archive) | yes | none (stateless; B3 is enforced in the database) |
| trading_analyzer | `ce305ecd7760` | `47877db4cfe8` | `ce305ecd7760` | yes (+ D3 drift) | none |
| trading_signal_engine | `b3d4b6236654` | `4b7f4a58073a` | `b3d4b6236654` | yes (+ D3 drift) | evidence bind mount unchanged |
| trading_tracker | `2b59c6a164c0` | `af063314973e` | `2b59c6a164c0` | yes | WebSocket reconnects; no trades while halted |
| trading_telegram | `b84d3d1528a0` | `ef80d11c6579` | `b84d3d1528a0` | yes | polling resumes |
| trading_claude_review | `8bca25750c77` | `aaeb0467815a` | `8bca25750c77` | yes (+ D3 drift) | none |

## 8. Remaining risks

1. Deploying requires container recreation, and therefore applies the D3 configuration drift.
2. Temporary base tags `tsb-aiohttp-base-*:20260929` are still present. They are harmless metadata; removing them was deferred for owner review, since removal is permitted only under conditions the owner specified.
3. The DB-backed tests (19) and the 2 PTB suite tests did not run in this phase. They are unaffected by aiohttp, and the same tests were skipped on 3.13.5.
4. `continuous_learner` (`d1aa69bd`) and the optimizer image remain on 3.13.5 (the learner is stopped; the optimizer has no container).

## 9. Follow-up finding (NOT solved here)

**Dependency reproducibility / lockfile remediation is required after this security remediation.** No lockfiles or constraints exist, so any normal rebuild drifts transitive packages. Handle it in a separate, owner-approved phase.

## 10. Deployment status (added 2026-09-30; sections 1–9 above are the unchanged 2026-09-29 validation record)

**Successfully deployed to production** (one service at a time, each under a separate owner authorization, with a gated script, a closed Compose-bookkeeping allowlist, strict IPs, fresh health ×2, native smoke and a 3×60 s observation; no rollback needed):

| Service | Deployed (UTC) | Image (overlay) | aiohttp | Evidence (local host) |
|---|---|---|---|---|
| telegram | 2026-09-30 04:21–04:26 | `sha256:ef80d11c657967ad21318685eab8ef41cbc08ac7002d06bb8f825960e6bee4f1` | 3.14.3 | `deploy-telegram-v2-20260930T042152Z/` |
| trade_tracker | 2026-09-30 06:10–06:15 | `sha256:af063314973ee6f4f988903c9836a91b30b4f3343cb68db8587bd41580b179c3` | 3.14.3 | `deploy-trade_tracker-20260930T061054Z/` |
| scanner | 2026-09-30 06:50–06:54 | `sha256:63b38e7a659d0efbc5dd1cb2a6035da1ab210f7774e94056d77fe7c61b50615e` | 3.14.3 | `deploy-scanner-20260930T065007Z/` |

- **Earlier telegram attempt:** on 2026-09-29 it stopped at D4 (a Compose-label difference) and was rolled back to `b84d3d15…`. The gates were corrected under owner review before the successful run.
- **Evidence root:** `/home/tradmin/backups/tsb-aiohttp-20260929T122701Z/`.
- **Image provenance and rollback targets:** `deploy/aiohttp-3.14.3/IMAGES.md`.
- **Compose:** `docker-compose.yml` now pins these three images (`image:` + `pull_policy: never`, no `build:`). This reproduces the running config hashes exactly, so installing it needs no recreation. The production installation is a separate, owner-authorized step.

**Validated but NOT deployed** (still aiohttp 3.13.5 in production and in `requirements.txt`): analyzer, signal_engine, claude_review.
- Their recreation would apply the known Compose/runtime environment drift (P0 finding D3). They wait for a separate phase.
- The overlay images `47877db4…`, `4b7f4a58…` and `aaeb0467…` remain local, validated, unused.

**Not part of this rollout:**
- **optimizer:** no overlay built; no running container; profile `disabled`; `requirements.txt` stays on 3.13.5.
- **continuous_learner:** stopped; builds from `signal_engine/requirements.txt` (3.13.5); not rebuilt or started.

**Requirements scope:** `aiohttp==3.14.3` only in `telegram/`, `trade_tracker/` and `scanner/requirements.txt`. Nothing else changed; there are still no lockfiles (§9).

