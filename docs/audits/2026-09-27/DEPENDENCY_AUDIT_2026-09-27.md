# DEPENDENCY_AUDIT_2026-09-27 — Trading Signal Bot, post-P1 (read-only)

**Date:** 2026-09-27. Evidence was collected 20:55–21:09 UTC.

**Mode:** strictly read-only, under `docs/product/SINGLE_HOST_SAFETY.md` and `DEPENDENCY_POLICY.md` (governance branch @`2ffb44b`). Nothing was installed, built, pulled, recreated, restarted, migrated or written.

**Host:** development and production share **one host**. No independent staging exists.

**State:** PAPER_TRADING=HALTED · PAPER_ONLY · LIVE_TRADING=FORBIDDEN · B3 unchanged · HOLDOUT sealed · learner stopped.

**Evidence (Appendices A and B are verbatim copies):**
- `work/python_dependency_matrix.{md,json}`
- `work/runtime_platform_matrix.{md,json}`

**Labels used below:**
- **[C]** Confirmed: directly observed or fetched from the official source at the time noted.
- **[A]** Assumption or assessment, such as applicability judged from reading the code.
- **[R]** Recommendation.
- **[V]** Needs verification before acting.

## 1. Prioritised findings
| P | Finding | Status |
|---|---|---|
| **P0** | The shared **PostgreSQL 16.14** misses the **16.15** security release (2026-08-13): 25 CVEs fixed, several CVSS 8.8 authenticated code execution. The blast radius covers TSB, xsch and wishlist. | [C] version, date and fix; [A] exposure is limited because the port is bound to loopback and most exploits need an authenticated role. §3.2 |
| **P0** | **aiohttp 3.13.5** in all 6 running TSB containers carries 14 advisories, fixed in **3.14.3**. **GHSA-cq5v-8q36-5273 / CVE-2026-69244 (HIGH)** is in the client response parser we use. | [C] versions and advisories; [A] applicability. §3.1 |
| **P1** | Before any P1 deployment: resolve the unreviewed uncommitted `analyzer/technical_analyzer.py` in the production folder; build reproducibly (the base digest is orphaned upstream; there is no lockfile); decide on the aiohttp fix; add evidence storage, retention and backup. | §4 |
| **P2** | Python **3.12.13** vs 3.12.14; about 3.5 months of trixie security updates missing; `pip==26.1.*` blocks the fix for CVE-2026-13346; transitive drift between images; `ta` 0.11.0 unmaintained and source-built; major upgrades pending. | §3, §6 |
| **P2** | postgres is pinned by **tag** only; no `pids_limit` anywhere; no swap; `shared_db_net` crosses projects. | §5 |
| **P3** | Unused `asyncio-throttle`; redundant `websockets==12.0`; heavy `anthropic` used only for two exception classes; the retired optimizer's requirements. | §6 |

## 2. Version matrix (summary; the full per-package matrix is Appendix A)
| Component | Installed [C] | Latest stable (date, source) [C] | Py3.12 / arm64 [C] | Note |
|---|---|---|---|---|
| Host OS / kernel | Ubuntu 24.04.5 LTS / 6.8.0-142, aarch64, 12 vCPU, 23.4 GiB | 24.04 LTS supported to 2029-05-31 | – | Current |
| Docker Engine / Compose / containerd / runc | 29.8.1 / v5.5.1 / 2.3.6 / 1.5.1 | 29.8.1 (2026-09-15) / v5.5.1 (2026-09-03) / 2.3.x LTS to 2028-04-30 | arm64 | Current |
| Python base | `python:3.12-slim@sha256:d764629c…` = **3.12.13**, Debian 13 trixie (2026-06-11) | **3.12.14** (2026-08-12); `3.12-slim` → `f77ac9e4…` (2026-09-25). 3.12 is security-only until 2028-10 | multi-arch incl. arm64/v8 | The digest is untagged upstream but still pullable (HEAD 200) |
| PostgreSQL | **16.14** (Alpine 3.24.1, `postgres:16-alpine`, digest `e013e867…`) | **16.15** (2026-08-13). PG16 EOL 2028-11-09. Newest major 18.6 | arm64 | P0 |
| aiohttp | **3.13.5** (6 containers, 7 manifests) | **3.14.3** (PyPI 2026-07-23) | yes / yes | P0 |
| pip / wheel (build) | 26.1.2 / 0.46.3 | pip **26.2.0** fixes CVE-2026-13346 | – | P2 |
| numpy | 2.2.6 (scanner, analyzer, pinned); **2.5.2** (signal_engine, via pandas) | see Appendix A | yes / yes | drift; parity-critical |
| pandas | 3.0.3 | 3.0.x newer (see A) | yes / yes | parity-critical |
| ta | 0.11.0 (source build, no wheel) | 0.11.0 is the latest; last release 2023-11-02 | sdist | unmaintained [A] |
| python-binance | 1.0.19 | 1.0.37 | yes / pure | WS manager not used [C] |
| websockets | 12.0 (analyzer, pinned) / 17.0.1 (others) | see A | yes / yes | redundant pin |
| asyncpg | 0.29.0 | 0.31.0 | yes / yes | only change is `prepare()` without cache; not used [A] |
| python-telegram-bot | 21.11.1 | **22.8** (major) | yes / pure | removed v20-deprecated APIs not used [A] |
| anthropic | 0.25.0 (signal_engine), 0.49.0 (optimizer, retired) | **1.8.0** (major, httpx2) | yes | used only for 2 exception classes |

## 3. Security findings (exact)
### 3.1 aiohttp 3.13.5 → fixed in 3.14.3 [C]
Links follow the official GitHub Security Advisory scheme: `https://github.com/advisories/<GHSA>` (upstream: `https://github.com/aio-libs/aiohttp/security/advisories`).

| GHSA / CVE | Severity | Fixed | Applicability to our deployment [A] |
|---|---|---|---|
| **GHSA-cq5v-8q36-5273 / CVE-2026-69244** | **HIGH** | 3.14.3 | **APPLICABLE**: C response parser in every aiohttp client (python-binance AsyncClient in scanner/analyzer/signal_engine; ClientSession in alerts, telegram, whitelist, tracker). Exchange and Telegram endpoints are the peers. |
| GHSA-mq44-7p77-q5h7 / CVE-2026-59881 | MODERATE | 3.14.2 | **APPLICABLE**: `trade_tracker/binance_price_stream.py` `ws_connect` |
| GHSA-xcgm-r5h9-7989 / CVE-2026-54274 | MODERATE | 3.14.1 | **LIKELY APPLICABLE**: WS frame reader in the tracker |
| GHSA-63hw-fmq6-xxg2 / CVE-2026-54277 | MODERATE | 3.14.1 | POSSIBLE (parser line length; mainly server-side) |
| GHSA-mfx4-hv73-q22v / CVE-2026-69243 | MODERATE | 3.14.2 | Likely N/A (server WS upgrade smuggling) |
| GHSA-4fvr-rgm6-gqmc / CVE-2026-54273 · GHSA-g3cq-j2xw-wf74 / CVE-2026-54278 | MODERATE | 3.14.1 | N/A: no `aiohttp.web` server |
| GHSA-hg6j-4rv6-33pg / CVE-2026-47265 · GHSA-hpj7-wq8m-9hgp / CVE-2026-54276 · GHSA-jg22-mg44-37j8 / CVE-2026-34993 | MODERATE | 3.14.0–3.14.1 | N/A in current code: no per-request cookies, DigestAuth or CookieJar.load |
| GHSA-2fqr-mr3j-6wp8 / CVE-2026-54279 · GHSA-4m7w-qmgq-4wj5 / CVE-2026-54275 · GHSA-9x8q-7h8h-wcw9 / CVE-2026-54280 · GHSA-m6qw-4cw2-hm4m / CVE-2026-50269 | LOW | 3.14.0–3.14.1 | N/A in current code |

The requirements comment claiming "latest — resolves all CVEs" is **stale** [C].

### 3.2 PostgreSQL 16.14 → fixed in 16.15 [C]
- **Official source:** `https://www.postgresql.org/support/security/` (per-CVE pages `…/support/security/CVE-YYYY-NNNNN/`) and the 16.15 release notes.
- **16 of the 25 CVE IDs recorded in evidence:**
  - CVE-2026-6464, -6471
  - CVE-2026-14662, -14664, -14668, -14669, -14670, -14671, -14677, -14679, -14680
  - CVE-2026-15741 (SQL injection via EXTRACT deparse), -15742
  - CVE-2026-16239
  - CVE-2026-18408, -19385
- **Severity:** CVSS 8.8 authenticated code execution includes CVE-2026-16239, -14680, -14669, -14664, -14662, -14670, -15742 and -14671. Client-side pg_dump/psql issues: CVE-2026-19385, -18408, -6464.
- **[V] The other 9 IDs** must be copied from the official 16.15 notes when remediation starts.
- **[A] Applicability:**
  - Most require an authenticated DB role.
  - Today every TSB service connects as the **bootstrap superuser**, so authentication is not a barrier for a compromised TSB container. The P0 least-privilege roles are designed but deferred.
  - The port is published on loopback only.
- **Upgrade caveat [C]:**
  - No dump/restore is needed.
  - Post-update configuration and cleanup steps exist, for example the new `output_plugin_libraries`.
  - btree_gist and ltree indexes may need REINDEX.
  - **[V]** Check whether any cluster DB uses them (xsch/wishlist included).

### 3.3 pip 26.1.2 → 26.2.0 [C]
GHSA-qwm4-qh6w-59xr / CVE-2026-13346 / PYSEC-2026-3721, MODERATE.
- **Build-time only:** a doubly-encoded index URL is mishandled.
- `pip==26.1.*` can never pick up the fix.

**No OSV records [C]** for the other installed versions, including python-binance 1.0.19, asyncpg 0.29.0, pandas 3.0.3, numpy 2.2.6/2.5.2, websockets 12.0/17.0.1, PTB 21.11.1, anthropic, requests 2.34.2, urllib3 2.7.0 and certifi 2026.7.22. No latest-stable version has any advisory. Absence of an OSV record is not proof of safety.

## 4. P1 release readiness (`feature/forward-instrumentation@23dea90`)
**Status: NOT READY TO DEPLOY. The code is ready for independent review.**

**Confirmed [C]:**
- 22 files; recording is off by default.
- The added PIT and identity fields are **additive JSON only** (`analysis_data.pit`, `signals.features_snapshot.identity`); there is no schema migration.
- Separate `data/evidence_v2` bind mount; the v1 recorder and files are untouched.
- Hooks never raise (proven by tests).
- 999 passed / 3 skipped with recording off and on; 24/24 in the telegram-image environment.
- Before/after decision parity against develop holds for selection (300 scenarios), analyzer (48 runs) and the DB tracker lifecycle (4 arms).
- Overhead: emit p50 0.06 ms; a 200-candidate cycle rises from 1.7 ms to 5.0 ms; worst-case memory is about 28 MB per service.

**Blocking gaps before deployment:**

| Gap | Why | Owner approval |
|---|---|---|
| **G1. Reproducible build not demonstrated** | The base digest is orphaned upstream (still pullable), there is no transitive lock, and pip/wheel use wildcards. A rebuild would also pull today's transitive versions (for example numpy drift). SINGLE_HOST_SAFETY §7 requires a reproducible build and known-good image IDs. | Build location (same host with limits vs external) |
| **G2. Tests ran in test environments, not the rebuilt images** | The parity suite must re-run against the actual built images. | – |
| **G3. The production folder holds an uncommitted, unreviewed `analyzer/technical_analyzer.py`** (= `refactor/strategy-math`) | A build from that folder would ship it. P1 changes the same analyzer. | Decision on the refactor (see REPOSITORY_CLEANUP_AUDIT) |
| **G4. aiohttp HIGH** | Shipping P1 on 3.13.5 re-ships a known HIGH CVE. Upgrading in the same release mixes a behaviour change into the release. | Order: security fix first as its own release, or P1 first |
| **G5. Storage, retention and backup of `data/evidence_v2`** | About 25–40 MB/day. It is not in any scheduled backup; single-host loss would take it with production. | Backup and retention policy |
| **G6. Five of seven deployed images differ from develop** | A clean rebuild of scanner, analyzer, signal_engine or claude_review changes production code beyond P1. P1 rebuilds only analyzer, signal_engine, tracker and telegram, and signal_engine and analyzer are among the drifted images. | Accept the develop code for those 2 images, or a per-file review |

Rollback remains simple ([C] design): turn the flag off, or redeploy the previous image IDs. The additive JSON keys are ignored by old code.

## 5. Shared-host resource and isolation plan (for a future, separately approved experiment)
**Baseline [C]:**
- 12 vCPU, 23.4 GiB RAM, **no swap**.
- Disk 743 G, 31% used. The build cache is 141.8 GB, 131.8 GB of it reclaimable (untouched).
- All containers together: about 1.29 GiB RSS; TSB about 374 MiB; CPU about 1%.
- **Headroom for a test stack: about 4 vCPU and 8 GiB.**

**Rules [R]** (from SINGLE_HOST_SAFETY §3–7 and the runtime findings):
1. **Before any run:** record `docker ps`, networks, ports, mounts and `free`/`df`. Stop if headroom is inadequate.
2. **Naming:** a unique compose project, for example `tsbdep-<date>`. Override every `container_name` (production uses fixed `trading_*`). Unique networks and volumes.
3. **Network:**
   - A private `--internal` network; **never `shared_db_net`**.
   - No published ports. Ports already in use: 80/443, 127.0.0.1:5432, :3000, :5091.
4. **Limits on every container:** `--cpus ≤ 2`, `--memory ≤ 2g` (DB ≤ 1g), `--pids-limit 256`. `nice`/`ionice` for builds. Total test ≤ 4 vCPU / 6 GiB.
5. **Data:** a disposable Postgres pinned **by digest**, on tmpfs, schema-only or synthetic. Never production `.env`, rows, holdout or tokens.
6. **Builds:**
   - Build into unique tags (`tsb-dep-test/<svc>:<sha>`); **never retag `trading-signal-bot-*:latest`**.
   - Never prune the build cache or images; `b3-rollback/*` anchors share the store.
   - If a same-host build cannot be demonstrated as safe, propose an external arm64 builder.
7. **Egress:** the same IP as production. Mock exchange and Telegram; no production bot identity.
8. **Teardown:** remove only the uniquely named test resources; verify production container IDs and start times are unchanged.

## 6. Proposed upgrade order and rollback
Each step is its own branch or PR. It is re-checked upstream at merge time, gated by the full test and parity suite in the isolated environment, and deployed one service at a time with owner approval. There is **no learner restart** and **no paper restart**.

| # | Change | Class | Parity risk | Host / downtime impact | Rollback |
|---|---|---|---|---|---|
| 1 | **PostgreSQL 16.14 → 16.15** (shared cluster), pinned **by digest** | Urgent security (P0) | None for strategy. SQL-driver semantics unchanged within the minor. | Restart of the shared DB: seconds to minutes of downtime for **TSB, xsch and wishlist**. Needs a maintenance window and a verified fresh dump/restic snapshot first. Plus post-update steps and REINDEX [V]. | Stop, restore the previous image digest `e013e867…` (same major, on-disk compatible) and start; the pre-upgrade snapshot is a fallback |
| 2 | **aiohttp 3.13.5 → 3.14.3** (+ yarl/multidict/propcache as resolved), pip → 26.2.x in Dockerfiles | Urgent security (P0) | Low. HTTP/WS client paths; tracker WS behaviour needs testing. | Rebuild of 6 images; per-service recreate means about 10–30 s gaps; while HALTED, no trading impact | Previous image IDs (manifest / `b3-rollback`) |
| 3 | **Lockfiles and reproducibility:** pin transitive deps with hashes per service (for example `pip-compile --generate-hashes`), pin pip/wheel exactly, re-pin the base to a current digest (3.12.14), pin claude_review apt | Reproducibility (P2) | The base patch 3.12.13→3.12.14 and the new trixie packages are mostly low risk, **but** lockfiles freeze numpy per image. Unify numpy only with parity tests. | Build CPU/IO only (limited) | Old images |
| 4 | Remove unused `asyncio-throttle`, the redundant `websockets==12.0` pin and heavy `anthropic` (replace the two exception imports) | Cleanup (P3) | None expected [A] | Smaller images | Old images |
| 5 | asyncpg 0.29 → 0.31 | Minor | Low; transaction and pool tests | Rebuild | Old images |
| 6 | python-binance 1.0.19 → 1.0.37, websockets alignment | Minor, behaviour-sensitive | Klines/precision semantics: candle-timestamp and filter parity tests | Rebuild | Old images |
| 7 | **pandas / numpy / ta** (indicator stack) | **Behaviour-changing** | **High.** numpy ≥2.3 float-summation changes. Needs its own experiment, indicator-drift tolerance, a contract hash and owner approval (DEPENDENCY_POLICY invariant). `ta` is unmaintained, so evaluate a vendored or maintained alternative. | Rebuild | Old images |
| 8 | python-telegram-bot 21 → 22 (major) | Major | B3 command and authorization parity in the telegram image tests | Rebuild telegram | Old image |
| 9 | anthropic 0.25 → 1.8, or drop it (see 4) | Major | Only 2 exception classes are used | Rebuild | Old image |
| 10 | Python 3.12 → 3.13/3.14 | Major runtime | Full re-validation | Rebuild all | Old images |

## 7. Decisions requiring owner approval (none is implied by this audit)
| ID | Decision |
|---|---|
| D1 | Urgent PostgreSQL 16.15 update: a maintenance window with the xsch and wishlist owners, a fresh backup first, digest pinning in `/home/tradmin/shared-postgres` |
| D2 | aiohttp security release ordering: before P1 (recommended [R]) or bundled |
| D3 | Build location: same host under §5 limits, or an external arm64 builder |
| D4 | Adopt hash-pinned lockfiles, exact pip/wheel and base-digest refresh policy |
| D5 | Treat pandas/numpy/ta as a separate behaviour-changing experiment; decide the future of `ta` |
| D6 | Remove the unused and heavy dependencies (asyncio-throttle, websockets pin, anthropic) |
| D7 | Add `pids_limit` and memory limits to all containers, and a swap policy (host change; affects other projects) |
| D8 | Backup and retention for `data/evidence_v2`, plus the off-host backup decision (still owner-deferred) |
| D9 | P1 deployment gates G1–G6 (§4) |
| D10 | Audit cadence: re-check upstream at every merge and deployment |

---
# Appendix A — Python dependency matrix (verbatim: work/python_dependency_matrix.md)

# Trading Signal Bot — Python dependency matrix (read-only audit)

**Date:** 2026-09-27 (generated 2026-09-27T21:14:33Z) · **Repo:** `/home/tradmin/tsb-p1` branch `feature/forward-instrumentation` @ `23dea904a852` (manifests identical to `develop` 4e3eb0a; only docker-compose.yml differs) · **Host:** aarch64, all images arm64/linux, Python 3.12.13

**Lookup times (UTC):** container inventory 20:56:11Z · PyPI JSON 20:58:24–20:58:39Z · OSV querybatch (installed) 20:58:33Z · OSV (latest) 21:09:17Z · GitHub releases 21:01:32–21:02:02Z · changelogs 21:04:01–21:08:16Z. Per-request timestamps are in the JSON.

**Read-only:** no pip/docker build/run/compose/start/stop, no DB, no repo edits, no env/secret output. `trading_continuous_learner` (Exited 143) was not started or inspected beyond its image ID.

## 1. Running containers

| Container | Image ID | Image created (UTC) | Tags | Python | Dists |
|---|---|---|---|---|---|
| trading_scanner | `9b0b53a6a799` | 2026-09-27T11:04:46Z | b3prep-20260927T120659/scanner:candidate, trading-signal-bot-scanner:latest | 3.12.13 | 31 |
| trading_analyzer | `ce305ecd7760` | 2026-08-19T08:32:27Z | r1b-base:analyzer-ce305ecd, trading-signal-bot-analyzer:latest | 3.12.13 | 31 |
| trading_signal_engine | `b3d4b6236654` | 2026-08-19T08:31:51Z | trading-signal-bot-signal_engine:latest | 3.12.13 | 49 |
| trading_claude_review | `8bca25750c77` | 2026-08-17T16:56:45Z | trading-signal-bot-claude_review:latest | 3.12.13 | 14 |
| trading_telegram | `b84d3d1528a0` | 2026-09-27T11:04:48Z | b3prep-20260927T120659/telegram:candidate, trading-signal-bot-telegram:latest | 3.12.13 | 20 |
| trading_tracker | `2b59c6a164c0` | 2026-09-27T11:04:49Z | b3prep-20260927T120659/tracker:candidate, trading-signal-bot-trade_tracker:latest | 3.12.13 | 28 |
| trading_continuous_learner | `d1aa69bde63f` | 2026-08-17T17:48:01Z | trading-signal-bot-continuous_learner:latest | 3.12.13 (image env) | not inspected |

Base image in all 7 Dockerfiles: `python:3.12-slim@sha256:d764629c…e0b9` (digest-pinned). Bootstrap: `pip==26.1.*`, `wheel==0.46.*`. **No lockfile, no constraints file, no hashes**; every direct dependency is `==`-pinned, every transitive dependency floats.

## 2. Declared manifests vs installed (direct deps)

| Service | Declared (requirements.txt) | Installed check |
|---|---|---|
| scanner | python-binance==1.0.19, asyncpg==0.29.0, aiohttp==3.13.5, pandas==3.0.3, numpy==2.2.6, asyncio-throttle==1.0.2 | all MATCH |
| analyzer | python-binance==1.0.19, asyncpg==0.29.0, aiohttp==3.13.5, pandas==3.0.3, numpy==2.2.6, ta==0.11.0, websockets==12.0 | all MATCH |
| signal_engine | asyncpg==0.29.0, anthropic==0.25.0, aiohttp==3.13.5, pandas==3.0.3, python-binance==1.0.19 | all MATCH |
| trade_tracker | python-binance==1.0.19, asyncpg==0.29.0, aiohttp==3.13.5 | all MATCH |
| telegram | asyncpg==0.29.0, python-telegram-bot==21.11.1, aiohttp==3.13.5 | all MATCH |
| claude_review | asyncpg==0.29.0, aiohttp==3.13.5 | all MATCH |
| optimizer | asyncpg==0.29.0, aiohttp==3.13.5, anthropic==0.49.0 | no container (declared only) |

## 3. Dependency matrix

Columns: installed per container (sc=scanner, an=analyzer, se=signal_engine, cr=claude_review, tg=telegram, tr=tracker); wheel = cp312-compatible manylinux-aarch64 or pure wheel for installed / latest; OSV = advisories affecting the installed version (latest versions: all 0 as of 21:09:17Z).

| Package | Role | Declared | Installed | Latest stable (uploaded) | Update | Py3.12 inst/latest (requires_python latest) | Wheel inst/latest | License (latest) | OSV on installed |
|---|---|---|---|---|---|---|---|---|---|
| aiohttp | direct | ==3.13.5 (scanner,analyzer,signal_engine,trade_tracker,telegram,claude_review,optimizer) | 3.13.5 (sc,an,se,cr,tg,tr) | 3.14.3 (2026-07-23) | 3.13.5: minor | Y / Y (>=3.10) | wheel → wheel | Apache-2.0 AND MIT | 3.13.5: 28 OSV records |
| anthropic | direct | ==0.25.0 (signal_engine); ==0.49.0 (optimizer) | 0.25.0 (se) | 1.8.0 (2026-09-22) | 0.25.0: MAJOR 0->1; 0.49.0: MAJOR 0->1 | Y/Y / Y (>=3.10) | wheel/wheel → wheel | MIT | none |
| asyncio-throttle | direct | ==1.0.2 (scanner) | 1.0.2 (sc) | 1.0.2 (2021-04-07) | 1.0.2: up-to-date | Y / Y (>=3.6) | wheel → wheel | MIT | none |
| asyncpg | direct | ==0.29.0 (scanner,analyzer,signal_engine,trade_tracker,telegram,claude_review,optimizer) | 0.29.0 (sc,an,se,cr,tg,tr) | 0.31.0 (2025-11-24) | 0.29.0: 0.x minor 29->31 (potentially breaking) | Y / Y (>=3.9.0) | wheel → wheel | Apache-2.0 | none |
| numpy | direct | ==2.2.6 (scanner,analyzer) | 2.2.6 (sc,an); 2.5.2 (se) | 2.5.3 (2026-09-06) | 2.2.6: minor; 2.5.2: patch | Y/Y / Y (>=3.12) | wheel/wheel → wheel | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | none |
| pandas | direct | ==3.0.3 (scanner,analyzer,signal_engine) | 3.0.3 (sc,an,se) | 3.0.6 (2026-09-17) | 3.0.3: patch | Y / Y (>=3.11) | wheel → wheel | BSD License | none |
| python-binance | direct | ==1.0.19 (scanner,analyzer,signal_engine,trade_tracker) | 1.0.19 (sc,an,se,tr) | 1.0.37 (2026-06-08) | 1.0.19: patch | Y / Y (None) | wheel → wheel | MIT | none |
| python-telegram-bot | direct | ==21.11.1 (telegram) | 21.11.1 (tg) | 22.8 (2026-06-12) | 21.11.1: MAJOR 21->22 | Y / Y (>=3.10) | wheel → wheel | LGPL-3.0-only | none |
| ta | direct | ==0.11.0 (analyzer) | 0.11.0 (an) | 0.11.0 (2023-11-02) | 0.11.0: up-to-date | Y / Y (None) | sdist-build → sdist-build | The MIT License (MIT) | none |
| websockets | direct | ==12.0 (analyzer) | 12.0 (an); 17.0.1 (sc,se,tr) | 17.1 (2026-08-26) | 12.0: MAJOR 12->17; 17.0.1: minor | Y/Y / Y (>=3.11) | wheel/wheel → wheel | BSD-3-Clause | none |
| pip | build tooling | — | 26.1.2 (sc,an,se,cr,tg,tr) | 26.2.1 (2026-08-04) | 26.1.2: calver update | Y / Y (>=3.10) | wheel → wheel | MIT | 26.1.2: 2 OSV records |
| setuptools | build tooling | — | — | 84.0.0 (2026-08-08) | not installed | — / Y (>=3.10) | — → wheel | MIT | none |
| wheel | build tooling | — | 0.46.3 (sc,an,se,cr,tg,tr) | 0.48.0 (2026-08-11) | 0.46.3: 0.x minor 46->48 (potentially breaking) | Y / Y (>=3.9) | wheel → wheel | MIT | none |
| aiohappyeyeballs | critical transitive | — | 2.7.1 (sc,an,se,cr,tg,tr) | 2.7.1 (2026-07-01) | 2.7.1: up-to-date | Y / Y (>=3.10) | wheel → wheel | PSF-2.0 | none |
| aiosignal | critical transitive | — | 1.4.0 (sc,an,se,cr,tg,tr) | 1.4.0 (2025-07-03) | 1.4.0: up-to-date | Y / Y (>=3.9) | wheel → wheel | Apache 2.0 | none |
| attrs | critical transitive | — | 26.1.0 (sc,an,se,cr,tg,tr) | 26.1.0 (2026-03-19) | 26.1.0: up-to-date | Y / Y (>=3.9) | wheel → wheel | MIT | none |
| certifi | critical transitive | — | 2026.7.22 (sc,an,se,tg,tr) | 2026.7.22 (2026-07-22) | 2026.7.22: up-to-date | Y / Y (>=3.7) | wheel → wheel | MPL-2.0 | none |
| charset-normalizer | critical transitive | — | 3.5.1 (sc,an,se,tr) | 3.5.1 (2026-08-15) | 3.5.1: up-to-date | Y / Y (>=3.7) | wheel → wheel | MIT | none |
| cryptography | critical transitive | — | — | 50.0.1 (2026-08-25) | not installed | — / Y (!=3.9.0,!=3.9.1,>=3.9) | — → wheel | Apache-2.0 OR BSD-3-Clause | none |
| dateparser | critical transitive | — | 1.4.2 (sc,an,se,tr) | 1.4.3 (2026-09-03) | 1.4.2: patch | Y / Y (>=3.10) | wheel → wheel | BSD-3-Clause | none |
| frozenlist | critical transitive | — | 1.8.0 (sc,an,se,cr,tg,tr) | 1.8.0 (2025-10-06) | 1.8.0: up-to-date | Y / Y (>=3.9) | wheel → wheel | Apache-2.0 | none |
| h11 | critical transitive | — | 0.16.0 (se,tg) | 0.16.0 (2025-04-24) | 0.16.0: up-to-date | Y / Y (>=3.8) | wheel → wheel | MIT | none |
| httpcore | critical transitive | — | 1.0.9 (se,tg) | 1.0.9 (2025-04-24) | 1.0.9: up-to-date | Y / Y (>=3.8) | wheel → wheel | BSD-3-Clause | none |
| httpx | critical transitive | — | 0.28.1 (se,tg) | 0.28.1 (2024-12-06) | 0.28.1: up-to-date | Y / Y (>=3.8) | wheel → wheel | BSD-3-Clause | none |
| idna | critical transitive | — | 3.18 (sc,se,cr,tr); 3.19 (an,tg) | 3.20 (2026-09-17) | 3.18: minor; 3.19: minor | Y/Y / Y (>=3.9) | wheel/wheel → wheel | BSD-3-Clause | none |
| multidict | critical transitive | — | 6.7.1 (sc,an,se,cr,tg,tr) | 7.0.0 (2026-09-26) | 6.7.1: MAJOR 6->7 | Y / Y (>=3.10) | wheel → wheel | Apache License 2.0 | none |
| propcache | critical transitive | — | 0.5.2 (sc,an,se,cr,tg,tr) | 0.5.4 (2026-09-16) | 0.5.2: patch | Y / Y (>=3.10) | wheel → wheel | Apache-2.0 | none |
| pycryptodome | critical transitive | — | 3.23.0 (sc,an,se,tr) | 3.23.0 (2025-05-17) | 3.23.0: up-to-date | Y / Y (!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*,!=3.5.*,!=3.6.*,>=2.7) | wheel → wheel | BSD, Public Domain | none |
| pydantic | critical transitive | — | 2.13.4 (se) | 2.13.5 (2026-08-28) | 2.13.4: patch | Y / Y (>=3.9) | wheel → wheel | MIT | none |
| pydantic_core | critical transitive | — | 2.46.4 (se) | 2.49.0 (2026-09-09) | 2.46.4: minor | Y / Y (>=3.10) | wheel → wheel | MIT | none |
| python-dateutil | critical transitive | — | 2.9.0.post0 (sc,an,se,tr) | 2.9.0.post0 (2024-03-01) | 2.9.0.post0: up-to-date | Y / Y (!=3.0.*,!=3.1.*,!=3.2.*,>=2.7) | wheel → wheel | Dual License | none |
| pytz | critical transitive | — | 2026.3.post1 (sc,an,se,tr) | 2026.4 (2026-09-24) | 2026.3.post1: calver update | Y / Y (None) | wheel → wheel | MIT | none |
| requests | critical transitive | — | 2.34.2 (sc,an,se,tr) | 2.34.2 (2026-05-14) | 2.34.2: up-to-date | Y / Y (>=3.10) | wheel → wheel | Apache-2.0 | none |
| tzdata | critical transitive | — | — | 2026.4 (2026-09-12) | not installed | — / Y (>=2) | — → wheel | Apache-2.0 | none |
| ujson | critical transitive | — | 5.13.0 (sc,an,se,tr) | 6.0.0 (2026-09-04) | 5.13.0: MAJOR 5->6 | Y / Y (>=3.10) | wheel → wheel | BSD-3-Clause AND TCL | none |
| urllib3 | critical transitive | — | 2.7.0 (sc,an,se,tr) | 2.8.0 (2026-09-15) | 2.7.0: minor | Y / Y (>=3.10) | wheel → wheel | MIT | none |
| yarl | critical transitive | — | 1.24.5 (sc,an,se,cr,tg,tr) | 1.25.1 (2026-09-15) | 1.24.5: minor | Y / Y (>=3.10) | wheel → wheel | Apache-2.0 | none |
| annotated-types | transitive | — | 0.8.0 (se) | 0.8.0 (2026-07-23) | 0.8.0: up-to-date | Y / Y (>=3.10) | wheel → wheel | MIT | none |
| anyio | transitive | — | 4.14.2 (se,tg) | 4.15.1 (2026-09-05) | 4.14.2: minor | Y / Y (>=3.10) | wheel → wheel | MIT | none |
| click | transitive | — | 8.4.2 (se) | 8.5.0 (2026-08-26) | 8.4.2: minor | Y / Y (>=3.10) | wheel → wheel | BSD-3-Clause | none |
| distro | transitive | — | 1.9.0 (se) | 1.9.0 (2023-12-24) | 1.9.0: up-to-date | Y / Y (>=3.6) | wheel → wheel | Apache License, Version 2.0 | none |
| filelock | transitive | — | 3.32.3 (se) | 4.0.4 (2026-09-26) | 3.32.3: MAJOR 3->4 | Y / Y (>=3.10) | wheel → wheel | MIT | none |
| fsspec | transitive | — | 2026.7.0 (se) | 2026.9.0 (2026-09-18) | 2026.7.0: calver update | Y / Y (>=3.10) | wheel → wheel | BSD-3-Clause | none |
| hf-xet | transitive | — | 1.6.0 (se) | 1.6.0 (2026-08-03) | 1.6.0: up-to-date | Y / Y (>=3.8) | wheel → wheel | Apache-2.0 | none |
| huggingface_hub | transitive | — | 1.27.0 (se) | 2.0.0 (2026-09-24) | 1.27.0: MAJOR 1->2 | Y / Y (>=3.10.0) | wheel → wheel | Apache-2.0 | none |
| packaging | transitive | — | 26.3 (sc,an,se,cr,tg,tr) | 26.3 (2026-08-04) | 26.3: up-to-date | Y / Y (>=3.9) | wheel → wheel | Apache-2.0 OR BSD-2-Clause | none |
| PyYAML | transitive | — | 6.0.3 (se) | 6.0.3 (2025-09-25) | 6.0.3: up-to-date | Y / Y (>=3.8) | wheel → wheel | MIT | none |
| regex | transitive | — | 2026.7.19 (sc,an,se,tr) | 2026.9.10 (2026-09-09) | 2026.7.19: calver update | Y / Y (>=3.10) | wheel → wheel | Apache-2.0 AND CNRI-Python | none |
| six | transitive | — | 1.17.0 (sc,an,se,tr) | 1.17.0 (2024-12-04) | 1.17.0: up-to-date | Y / Y (!=3.0.*,!=3.1.*,!=3.2.*,>=2.7) | wheel → wheel | MIT | none |
| sniffio | transitive | — | 1.3.1 (se) | 1.3.1 (2024-02-25) | 1.3.1: up-to-date | Y / Y (>=3.7) | wheel → wheel | MIT OR Apache-2.0 | none |
| tokenizers | transitive | — | 0.23.1 (se) | 0.23.2 (2026-09-03) | 0.23.1: patch | Y / Y (>=3.10) | wheel → wheel | Apache Software License | none |
| tqdm | transitive | — | 4.70.0 (se) | 4.70.1 (2026-09-11) | 4.70.0: patch | Y / Y (>=3.8) | wheel → wheel | MPL-2.0 AND MIT | none |
| typing_extensions | transitive | — | 4.16.0 (sc,an,se,cr,tg,tr) | 4.16.0 (2026-07-02) | 4.16.0: up-to-date | Y / Y (>=3.9) | wheel → wheel | PSF-2.0 | none |
| typing-inspection | transitive | — | 0.4.4 (se) | 0.4.4 (2026-08-12) | 0.4.4: up-to-date | Y / Y (>=3.10) | wheel → wheel | MIT | none |
| tzlocal | transitive | — | 5.4.4 (sc,an,se,tr) | 5.4.4 (2026-06-29) | 5.4.4: up-to-date | Y / Y (>=3.10) | wheel → wheel | MIT | none |

Not installed anywhere: `setuptools` (latest 84.0.0, 2026-08-08), `tzdata` (latest 2026.4; pandas 3 needs it only on win32/emscripten), `cryptography` (latest 50.0.1). `ta` 0.11.0 has **no wheel** (sdist only → built during `docker build`). `multidict` latest allowed by aiohttp's `<7.0` cap is 6.9.1 (2026-09-21).

## 4. Security findings

OSV was queried for 56 installed/declared (package, version) pairs and 56 latest-stable versions. Only two installed packages are affected; **no latest-stable version has an OSV advisory**.

### 4.1 aiohttp 3.13.5 — installed in all 6 running containers, declared in all 7 requirements files

The requirements comment `# latest — حل كل CVEs aiohttp 2024-2026` is stale: 3.14.0 (GitHub release 2026-06-01) … 3.14.3 (GitHub release 2026-07-22, PyPI upload 2026-07-23) fix 14 CVEs present in 3.13.5. **Upgrading to 3.14.3 fixes all of them.**

| GHSA | CVE | PYSEC | GHSA severity | Fixed in | Summary | Applicability here (assessment) |
|---|---|---|---|---|---|---|
| GHSA-cq5v-8q36-5273 | CVE-2026-69244 | PYSEC-2026-3545 | HIGH | 3.14.3 | AIOHTTP: Out-of-bounds heap read in C HTTP response parser error path (malformed chunked response) | APPLICABLE (client): C HTTP *response* parser — every aiohttp client (python-binance AsyncClient in scanner/analyzer/signal_engine; ClientSession in shared/alerts.py, telegram/main.py, telegram/whitelist.py, trade_tracker, optimizer). Needs a malicious/compromised server or TLS interception. |
| GHSA-4fvr-rgm6-gqmc | CVE-2026-54273 | PYSEC-2026-2107 | MODERATE | 3.14.1 | aiohttp: HTTP/1 Pipelined Requests Queue Without Limit | N/A: server-side pipelining; no aiohttp.web server. |
| GHSA-63hw-fmq6-xxg2 | CVE-2026-54277 | PYSEC-2026-2110 | MODERATE | 3.14.1 | aiohttp: C HTTP Parser Bypasses max_line_size for Fragmented Lines | POSSIBLE (C HTTP parser line-length check; primarily server request parsing) — assessment only. |
| GHSA-g3cq-j2xw-wf74 | CVE-2026-54278 | PYSEC-2026-2111 | MODERATE | 3.14.1 | aiohttp: Unread Compressed Request Bodies Bypass client_max_size During Cleanup | N/A: server-side client_max_size; no aiohttp.web server. |
| GHSA-hg6j-4rv6-33pg | CVE-2026-47265 | PYSEC-2026-2105 | MODERATE | 3.14.0 | AIOHTTP is vulnerable to cross-origin redirect with per-request cookies | N/A in current code: needs per-request cookies= (not used). |
| GHSA-hpj7-wq8m-9hgp | CVE-2026-54276 | PYSEC-2026-2109 | MODERATE | 3.14.1 | aiohttp: DigestAuthMiddleware Applies Credentials to Cross-Origin Redirect Challenges | N/A in current code: DigestAuthMiddleware not used. |
| GHSA-jg22-mg44-37j8 | CVE-2026-34993 | PYSEC-2026-2104 | MODERATE | 3.14.0 | AIOHTTP is Vulnerable to Deserialization of Untrusted Data | N/A in current code: CookieJar.load() not used. |
| GHSA-mfx4-hv73-q22v | CVE-2026-69243 | PYSEC-2026-3546 | MODERATE | 3.14.2 | AIOHTTP: HTTP request smuggling via WebSocket upgrade | LIKELY N/A: request smuggling via WebSocket upgrade (server-side); no aiohttp.web server in shipped code. |
| GHSA-mq44-7p77-q5h7 | CVE-2026-59881 | PYSEC-2026-3547 | MODERATE | 3.14.2 | AIOHTTP: WebSocket client accepts compressed frames without negotiated permessage-deflate | APPLICABLE (WS client): trade_tracker/binance_price_stream.py uses session.ws_connect(). |
| GHSA-xcgm-r5h9-7989 | CVE-2026-54274 | PYSEC-2026-2108 | MODERATE | 3.14.1 | aiohttp: Incomplete websocket frame payloads bypass memory limits | LIKELY APPLICABLE (WS reader): trade_tracker WebSocket client (assessment: frame reader shared by client and server). |
| GHSA-2fqr-mr3j-6wp8 | CVE-2026-54279 | PYSEC-2026-2112 | LOW | 3.14.1 | aiohttp: Host-Only Cookies Become Domain Cookies After CookieJar Persistence | N/A in current code: CookieJar.save()/load() not used. |
| GHSA-4m7w-qmgq-4wj5 | CVE-2026-54275 | PYSEC-2026-237 | LOW | 3.14.1 | aiohttp: TLS Server Hostname Override Is Ignored When Reusing HTTPS Connections | N/A in current code: per-request server_hostname not used. |
| GHSA-9x8q-7h8h-wcw9 | CVE-2026-54280 | PYSEC-2026-2113 | LOW | 3.14.1 | aiohttp: Payload Response Resources Are Not Closed After Mid-Body Disconnect | LIKELY N/A: server payload resources; no aiohttp.web server. |
| GHSA-m6qw-4cw2-hm4m | CVE-2026-50269 | PYSEC-2026-2106 | LOW | 3.14.0 | aiohttp: CRLF injection in multipart headers | N/A in current code: no multipart/FormData usage. |

aiohttp use in shipped code: python-binance `AsyncClient` (scanner, analyzer, signal_engine MacroContext), `ClientSession` in shared/alerts.py, telegram/main.py, telegram/whitelist.py, trade_tracker, optimizer; `ws_connect` in trade_tracker/binance_price_stream.py. No `aiohttp.web` server, no `CookieJar` persistence, no `DigestAuthMiddleware`, no `cookies=`/`server_hostname=`/`BasicAuth`, no multipart. Practical exposure: peers are Binance/Telegram over TLS, so exploitation needs a malicious/compromised endpoint or TLS interception — risk is real but low; the fix is a drop-in minor bump.

### 4.2 pip 26.1.2 — build tooling in all images

- **GHSA-qwm4-qh6w-59xr** / CVE-2026-13346 / PYSEC-2026-3721 — GHSA severity MODERATE, CVSS `CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:U/C:N/I:H/A:N`; `CVSS:4.0/AV:N/AC:H/AT:P/PR:H/UI:A/VC:N/VI:H/VA:N/SC:N/SI:N/SA:N`; fixed in 26.2.0. pip would incorrectly handle doubly-encoded package URLs from indexes. BUILD-TIME ONLY: pip is not used at runtime; matters on image rebuilds; Dockerfile pin pip==26.1.* blocks the fix. Latest pip is 26.2.1 (2026-08-04).

### 4.3 No advisories

All other installed versions (including python-binance 1.0.19, asyncpg 0.29.0, pandas 3.0.3, numpy 2.2.6/2.5.2, websockets 12.0/17.0.1, python-telegram-bot 21.11.1, anthropic 0.25.0/0.49.0, requests 2.34.2, urllib3 2.7.0, certifi 2026.7.22, idna 3.18/3.19, pycryptodome 3.23.0, wheel 0.46.3, ujson 5.13.0) returned **no OSV records** at 20:58:33Z. OSV absence is not proof of safety.

## 5. Drift and reproducibility

- No lockfile, no constraints file, no --require-hashes anywhere; only DIRECT deps are exact-pinned (==). All transitive deps float at image-build time (per-container lists under containers.*.unpinned_transitive_installed).
- Base image is digest-pinned in all 7 Dockerfiles: python:3.12-slim@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9 -> Python 3.12.13 (PYTHON_SHA256 c08bc65a81971c1dd5783182826503369466c7e67374d1646519adf05207b684) in every running image. Bootstrap tooling pinned by wildcard: pip==26.1.* (installed 26.1.2), wheel==0.46.* (installed 0.46.3).
- Observed drift from identical specs: idna 3.18 (scanner, signal_engine, claude_review, tracker) vs 3.19 (analyzer, telegram).
- numpy 2.2.6 (pinned: scanner, analyzer) vs 2.5.2 (signal_engine: not declared; resolved via pandas 3.0.3 'numpy>=1.26.0').
- websockets 12.0 (analyzer pin) vs 17.0.1 (scanner, signal_engine, tracker via unpinned python-binance requirement).
- anthropic 0.25.0 (signal_engine) vs 0.49.0 (optimizer requirements; optimizer has no container).
- Inference from PyPI upload dates: the pip layers were resolved at different dates than the image 'Created' times (Docker layer cache). scanner/tracker/signal_engine contain charset-normalizer 3.5.1 (uploaded 2026-08-15) but idna 3.18 (3.19 uploaded 2026-08-18) -> resolved ~2026-08-15..18, although scanner/tracker images are dated 2026-09-27 (B3 candidates). telegram (dated 2026-09-27) has idna 3.19 but anyio 4.14.2 (4.15.1 uploaded 2026-09-05) -> resolved ~2026-08-18..09-05.
- A cache-less rebuild today would re-resolve every unpinned transitive dep, e.g. idna 3.20, urllib3 2.8.0, yarl 1.25.1, propcache 0.5.4, multidict 6.9.1 (7.0.0 blocked by aiohttp's <7.0), websockets 17.1, dateparser 1.4.3, pytz 2026.4, regex 2026.9.10, ujson 6.0.0 (MAJOR, via python-binance), numpy 2.5.3 in signal_engine, click 8.5.0/filelock 4.0.4 (MAJOR)/fsspec 2026.9.0/tokenizers 0.23.2 in signal_engine (huggingface-hub stays <2.0 via tokenizers). These are eligibility statements from PyPI metadata; no resolver was run (pip install --dry-run is forbidden here).
- ta 0.11.0 is sdist-only -> compiled/built during docker build with an isolated build backend fetched from PyPI at that moment (setuptools not pinned by this repo; latest setuptools 84.0.0).
- Test venv (/home/tradmin/trading-signal-bot/research/skill_application/.venv, Python 3.12.3, read from dist-info names only): numpy 2.2.6, pandas 3.0.3, ta 0.11.0, aiohttp 3.13.5, asyncpg 0.29.0, python-binance 1.0.19, websockets 17.0.1, scipy 1.18.0, pytest 9.1.1 -> matches the analyzer numeric stack; Python patch level differs from containers (3.12.3 vs 3.12.13).
- The whole shared/ tree is copied into every image, including modules whose deps are absent there (shared/strategy_math.py needs ta; shared/ohlcv.py + regime.py need numpy/pandas). Static import-graph check: no running service imports a module whose deps are missing; latent ImportError if a future change imports them from tracker/telegram/claude_review.
- claude_review additionally installs npm @anthropic-ai/claude-code@2.1.197 (exact pin; not a Python dependency; not audited here).

## 6. Breaking-change risks

### 6.1 Indicator numerical parity

Indicator math runs in **analyzer** (`ta` 0.11.0 + pandas 3.0.3 + numpy 2.2.6) and **scanner** (`shared/ohlcv.py`, same pandas/numpy pins); the test venv matches that stack. signal_engine (numpy 2.5.2) does not compute indicators. Parity holds today; the risks are in any future bump:

- **numpy** 2.2.6 (scanner/analyzer, pinned); 2.5.2 (signal_engine, unpinned) → 2.5.3 (2026-09-06) — parity risk: MEDIUM for any bump of the scanner/analyzer pin (last-bit float differences in reductions can flip exact-threshold comparisons; seeded research RNG streams for binomial change in 2.5). signal_engine already runs 2.5.2 but does not compute indicators.
  - 2.3.0: 'Changes to the main iterator and potential numerical changes' — buffered iteration changes 'may slightly change numerical results of floating point operations' for np.sum(); count_nonzero(axis=None) returns a NumPy scalar; float16/float32 print format changed; many expired deprecations (np.tostring removed, bincount(minlength=None) raises, ...).
  - 2.4.0: numpy.round always returns a copy; removed `interpolation=` from percentile/quantile (use method=), numpy.in1d, linalg.linalg / fft.helper modules, reshape(newshape=), save(fix_imports=); improved quantile/percentile accuracy for 16/32-bit floats.
  - 2.5.x requires Python >=3.12 (PyPI metadata of 2.5.2/2.5.3); 2.5.0: linalg.eig/eigvals always return complex; numpy.where no longer truncates out-of-range Python ints; datetime64/timedelta64 arithmetic raises OverflowError on overflow; default allocator now PyMem_RawMalloc; corrected BTPE binomial sampler (Generator.binomial streams change); expired deprecations (numpy.distutils, row_stack, cross on 2-D vectors, ...).
- **pandas** 3.0.3 → 3.0.6 (2026-09-17) — parity risk: LOW
  - 3.0.4: regression fixes (StringDtype arithmetic, zoneinfo localisation >2100, MultiIndex set) and bug fixes: DataFrame.iloc silently ignoring assignment with unordered/duplicated column indexer when values are referenced (CoW), eval() CoW mutation, DateOffset arithmetic segfault under threads.
  - 3.0.5: only fixes 3.0.4 wheels built against an incompatible numpy (segfault on Python 3.14).
  - 3.0.6: regressions in read_csv(usecols/sep=None), tz_convert/tz_localize offsets for pre-standard-time dates, Series.interpolate(method='linear') on pyarrow dtypes, CoW fixes (.loc full-slice with pyarrow, RangeIndex).
  - No rolling/ewm/reduction kernel changes listed -> no expected indicator-value change; no API removals.
- **ta** 0.11.0 → 0.11.0 (2023-11-02) — no newer release — parity risk: MEDIUM (unmaintained numeric core; any pandas/numpy bump must be parity-tested on ta outputs)
  - Maintenance: last PyPI release 2023-11-02 (~3 years); GitHub has 0 releases (tags 0.11.0/0.10.3/0.10.2), not archived, 159 open issues, last commit 2026-03-18 'Update README.md' (previous code commit 2023-11-02).
  - Predates pandas 3.0 (Copy-on-Write default, removed fillna(method=)); pandas-3 compatibility of all ta code paths is not guaranteed upstream — only the indicators currently exercised are proven by the running analyzer.
  - sdist-only: built at image build time (non-hermetic build backend).

### 6.2 B3 / DB / Telegram / exchange behaviour

- **python-telegram-bot** 21.11.1 → 22.8 (2026-06-12) (MAJOR 21->22) — risk: LOW-MEDIUM (major bump; code surface small and clean per grep; needs a smoke test of polling + outbox delivery).
  - 22.0: removes all functionality deprecated in v20.x — filters.CHAT, filters.StatusUpdate.USER_SHARED, Defaults.disable_web_page_preview/quote, ApplicationBuilder/HTTPXRequest proxy_url, *_timeout args of Application.run_polling/Updater.start_webhook, Message.reply_*(quote=), EncryptedPassportElement.credentials; PassportFile.file_date -> datetime; BaseRequest.read_timeout abstract; write_timeout default for media now DEFAULT_NONE (was 20).
  - 22.1: send_gift parameter order (user_id); 22.2: opt-in timedelta for duration attributes (PTB_TIMEDELTA env), int durations deprecated; httpx range widened to >=0.27,<0.29.
  - 22.3 / 22.7: removal of Bot API 9.0 / 9.3 deprecated attributes; 22.5: ReplyParameters.checklist_task_id moved last; 22.8: filename positional arg of InputMedia* deprecated; requires Python >=3.10.
  - Usage in telegram/: Application.builder().token().build(), app.start(), app.updater.start_polling(drop_pending_updates=True), bot.send_message(keyword args), aiohttp for raw calls — grep found NO use of any 22.0-removed API.
  - Source: https://docs.python-telegram-bot.org/en/v22.8/changelog.html (fetched 2026-09-27T21:04:32Z) + GitHub releases
- **asyncpg** 0.29.0 → 0.31.0 (2025-11-24) (0.x minor x2) — risk: LOW (B3/DB)
  - 0.30.0: Python 3.13 + PostgreSQL 17 support, GSSAPI/SSPI auth, sslnegotiation param, Pool(connect=...), fetchmany, customizable connection reset, None handling in copy_from_query.
  - 0.31.0: Python 3.14; drops Python 3.8; prepare() stops using named statements by default *when the statement cache is disabled*; connection service file (pg_service.conf) support; connection-leak fix.
  - shared/database.py: asyncpg.create_pool(min_size=2, max_size=10, command_timeout=60, server_settings=...) with default statement cache and connection params from the environment -> the prepare() change does not apply; service-file support only matters if PGSERVICE/PGSERVICEFILE were set (environment deliberately NOT inspected).
  - Source: GitHub releases v0.30.0, v0.31.0 (gh api 2026-09-27T21:01:39Z)
- **aiohttp** 3.13.5 → 3.14.3 (PyPI 2026-07-23; GitHub release 2026-07-22) (minor) — risk: LOW (drop-in for this client-only usage; deprecation warnings only if BasicAuth were used).
  - 3.14.0 removals/breaking: dropped Python 3.9; outbound header serialization now rejects ASCII control characters (RFC 9110/9112); web.BaseRequest.host no longer falls back to socket.getfqdn (server only).
  - 3.14.0 deprecations (removal in 4.0): BasicAuth and auth=/proxy_auth= parameters (use encode_basic_auth + headers).
  - 3.14.1-3.14.3: security fixes (see security findings), fragmented-WebSocket control-frame fix (3.14.2), 3.14.3 fixes the client dropping only the *first* Authorization / Cookie / Proxy-Authorization header when a redirect crosses an origin.
  - No aiohttp server, BasicAuth, cookies=, CookieJar persistence or multipart usage found in shipped code.
  - Source: GitHub releases v3.14.0-v3.14.3 (gh api 2026-09-27T21:02:02Z after a transient HTTP 504 at 21:01:40Z)
- **python-binance** 1.0.19 (2023-08-11) → 1.0.37 (2026-06-08) (18 patch-numbered releases) — risk: LOW-MEDIUM (default recvWindow + many internal changes; klines REST path stable).
  - 1.0.20: EDDSA auth, proxy support for AsyncClient; 1.0.23: websocket CRUD/ws-api, default recvWindow parameter added, fix for `fail_connection` issue related to the websockets upgrade; 1.0.26: microsecond time-unit support; 1.0.29: async client empty-text fix, websocket max_queue_size; 1.0.30: futures_historical_klines* default limit=None, spot listenKey deprecated; 1.0.35: websocket reconnect fixes, margin socket via ws-api.
  - 1.0.37 no longer requires ujson. All deps remain unpinned in every release.
  - This codebase uses only AsyncClient REST (get_klines, order book) — no BinanceSocketManager/ThreadedWebsocketManager — so the websockets incompatibility of 1.0.19 is latent.
  - Source: GitHub releases v1.0.20-v1.0.37 (gh api 2026-09-27T21:01:38Z)
- **websockets** 12.0 (analyzer, pinned); 17.0.1 (scanner/signal_engine/tracker, unpinned via python-binance) → 17.1 (2026-08-26) (MAJOR 12->17 for analyzer) — risk: LOW at runtime (no direct websockets use; python-binance streams unused) but the analyzer pin 12.0 vs 17.0.1 elsewhere means python-binance is import-tested against two different websockets majors.
  - 13.0: path argument of server handlers deprecated; threading ssl_context -> ssl.
  - 14.0: new asyncio implementation becomes the default for websockets.connect/serve; legacy implementation deprecated; requires Python >=3.9.
  - 15.0: client connections use system SOCKS/HTTP proxies automatically; threading keepalive enabled.
  - 16.0: requires Python >=3.10.
  - 17.0: requires Python >=3.11; aliases for modules moved in 9.0 removed; several boolean args keyword-only; non-ASCII handshake header encoding changed.
  - 17.1: no backwards-incompatible changes.
  - Source: docs/project/changelog.rst @17.1 (gh api 2026-09-27T21:04:01Z); GitHub release bodies only link to it
- **anthropic** 0.25.0 (signal_engine); 0.49.0 declared in optimizer (no container) → 1.8.0 (2026-09-22) (MAJOR 0.x -> 1.x) — risk: LOW functionally (SDK effectively unused); high dependency-footprint cost.
  - 0.28.0 removed old streaming event_handler API; 0.39.0 removed client.count_tokens() and Python 3.7; 0.41.0/0.43.0 removed deprecated HTTP client options; 0.59.0 removed older deprecated models; 0.72.1 dropped Python 3.8.
  - 1.0.0 (2026-08-20): 'upgrade to httpx2 and some minor breaking changes. See MIGRATION.md' — 1.8.0 requires httpx2<3,>=2.0.0, docstring-parser, jiter (0.25.0 required httpx + tokenizers).
  - Only anthropic.APIConnectionError / APITimeoutError are referenced (optional import in shared/retry_utils.py, guarded by except (ImportError, AttributeError)). Whether those names still exist in 1.x was NOT verified from source.
  - Source: GitHub releases v0.25.1-v1.8.0 (gh api 2026-09-27T21:01:53Z)

Other major jumps available but not in the declared set: ujson 5.13.0 → 6.0.0 (via python-binance; removed non-bytes bytes-like support), multidict 6 → 7 (blocked by aiohttp), huggingface-hub 1 → 2 (blocked by tokenizers), filelock 3 → 4 (signal_engine only, via anthropic's chain).

## 7. Unused or retired dependencies

| Package | Where | Evidence | Status |
|---|---|---|---|
| asyncio-throttle==1.0.2 | scanner | never imported anywhere in the repository | UNUSED |
| websockets==12.0 | analyzer | no direct import in shipped analyzer code; only an import-time dependency of python-binance (which pulls websockets anyway) | REDUNDANT PIN (diverges from 17.0.1 elsewhere) |
| anthropic==0.25.0 | signal_engine (+ stopped continuous_learner image) | only optional exception classes in shared/retry_utils.py; no API client; claude_review uses the Claude Code CLI (npm) instead; 18 extra distributions attributable to it: anyio, sniffio, distro, httpx, httpcore, h11, pydantic, pydantic-core, annotated-types, typing-inspection, tokenizers, huggingface-hub, hf-xet, fsspec, filelock, PyYAML, tqdm, click | RETIRED / effectively unused |
| anthropic==0.49.0 | optimizer (no running container) | optimizer/main.py imports only aiohttp + shared; anthropic only via optional import in shared/retry_utils.py | RETIRED / effectively unused |
| pandas==3.0.3 | signal_engine | only a lazy import in research/null_a/sinks.py (DataFrame sink); signal_engine main path imports no pandas/numpy | LIGHTLY USED (keeps numpy unpinned in that image) |
| optimizer/requirements.txt | optimizer | compose service trading_optimizer has no container on this host | DECLARED ONLY (not deployed) |

## 8. Limitations

- Latest-version compatibility is from PyPI metadata; no resolver or install was run. The stopped `trading_continuous_learner` image was not inventoried.
- Advisory applicability is a grep-based assessment of shipped code, not an exploit test. The environment (e.g. PGSERVICE for asyncpg 0.31) was deliberately not read.
- Transient GitHub HTTP 504 on the aiohttp releases call at 21:01:40Z; the retry at 21:02:02Z succeeded. No other lookup failed.

Machine-readable companion: `python_dependency_matrix.json` (same directory).

---
# Appendix B — Runtime / platform matrix (verbatim: work/runtime_platform_matrix.md)

# TSB Runtime / Platform Matrix — 2026-09-27

**Mode:** strictly read-only. The host is a single netcup ARM64 VPS that serves as both dev and prod.
**Window:** 2026-09-27T20:55:26Z → 21:02:57Z (UTC).
**Nothing was changed.** No build, run, pull, compose, start, stop, restart, rm or prune. No installs, no DB writes, no git network operations. `trading_continuous_learner` was not started and not exec'd. Only the four allowed env keys were ever read. The machine-readable companion is `runtime_platform_matrix.json` in this directory.

---

## 1. Host (observed 20:55:26Z)

| Item | Value |
|---|---|
| OS | Ubuntu 24.04.5 LTS (noble); standard support to **2029-05-31** — current |
| Kernel | 6.8.0-142-generic #142-Ubuntu SMP PREEMPT_DYNAMIC (built 2026-09-02) |
| Arch / CPU | **aarch64**, ARM Neoverse-N1, **12 vCPU**, 1 NUMA node |
| RAM | 23,975 MiB total; 2,883 used; 21,091 available; **swap 0** |
| Disk | `/dev/vda1` 743G, 223G used (31%), 520G free. `/home` and `/var/lib/docker` are on the same fs |
| Uptime / load | up 11:10 (booted ~09:45Z); load 0.59/0.37/0.32, then 1.11/0.59/0.40 during the audit |
| Docker Engine | **29.8.1** (API 1.56, go1.26.8), linux/arm64 |
| Compose plugin | **v5.5.1** |
| containerd / runc / init | **2.3.6** / 1.5.1 / 0.19.0 |
| Storage | `overlayfs` + **containerd image store** (`io.containerd.snapshotter.v1`) |
| Daemon | cgroup v2 (systemd); live-restore **on**; apparmor + seccomp + cgroupns + **no-new-privileges** set daemon-wide; json-file logging |

## 2. Base-image pin vs running images

**Dockerfile pin.** All 7 Dockerfiles use the same pin, in both `/home/tradmin/tsb-p1` and the prod checkout `/home/tradmin/trading-signal-bot`:
`FROM python:3.12-slim@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9`

| Question | Answer | Evidence |
|---|---|---|
| What is the digest? | A multi-arch **OCI image index** covering 8 platforms: amd64, arm/v5, arm/v7, **arm64/v8**, 386, ppc64le, riscv64, s390x | `docker image ls --tree` (20:57:53Z); registry HEAD content-type `application/vnd.oci.image.index.v1+json` (20:58:40Z) |
| Python / Debian | **Python 3.12.13 on Debian 13 (trixie)**, created 2026-06-11T01:15:59Z | image env `PYTHON_VERSION=3.12.13`; `python -V` and `/etc/os-release` in all 6 running TSB containers |
| Still pullable? | **Yes**: registry HEAD returned 200 | registry-1.docker.io at 20:58:40Z |
| Still tagged upstream? | **No.** `3.12-slim` now = `f77ac9e4…` = **3.12.14**-slim-trixie (pushed 2026-09-25). `3.12.13-slim` was rebuilt as `229a2c5b…` on 2026-08-07 | Docker Hub tags API at 20:57:27Z and 20:57:54Z |
| Were the running images built from the pin? | **Yes.** In all 8 `trading-signal-bot-*` images, the first 4 RootFS diffIDs equal the pin's 4 layers (`4b8111b4e6ad`, `e39b360c6de4`, `0e8d67283b73`, `e08e77e4dc02`) | `docker image inspect` at 20:56:22Z |
| Would a rebuild reproduce them? | **Only the base would.** The rest floats: `pip==26.1.*` and `wheel==0.46.*` wildcards, top-level `==` pins with no `--hash` and no transitive lock, and an unpinned `apt-get install` in claude_review | Dockerfiles and requirements files |

## 3. TSB images and containers (inspect 20:56:10–22Z, stats 20:56:38Z)

| Container | Image ID (short) | Image built (UTC) | Python / OS | Mem used / limit | CPU cap | CPU% | PIDs (limit) | Networks |
|---|---|---|---|---|---|---|---|---|
| trading_scanner | 9b0b53a6a799 | 2026-09-27 11:04 | 3.12.13 / Debian 13 | 68.1 MiB / 512 MiB (13.3%) | 1.0 | 0.01 | 14 (none) | shared_db_net, trading_network |
| trading_telegram | b84d3d1528a0 | 2026-09-27 11:04 | 3.12.13 / Debian 13 | 44.6 MiB / 256 MiB (17.4%) | none | 0.00 | 4 (none) | same |
| trading_tracker | 2b59c6a164c0 | 2026-09-27 11:04 | 3.12.13 / Debian 13 | 28.9 MiB / 256 MiB (11.3%) | none | 0.15 | 3 (none) | same |
| trading_signal_engine | b3d4b6236654 | 2026-08-19 08:31 | 3.12.13 / Debian 13 | 88.9 MiB / 512 MiB (17.4%) | 1.0 | 0.01 | 14 (none) | same |
| trading_analyzer | ce305ecd7760 | 2026-08-19 08:32 | 3.12.13 / Debian 13 | 108.8 MiB / 1 GiB (10.6%) | 1.5 | 0.01 | 14 (none) | same |
| trading_claude_review | 8bca25750c77 | 2026-08-17 16:56 | 3.12.13 / Debian 13 | 34.6 MiB / 512 MiB (6.8%) | none | 0.01 | 3 (none) | same |
| trading_continuous_learner | d1aa69bde63f | 2026-08-17 17:48 | 3.12.13 (env) | **Exited (143), 5 weeks ago**; limit 256 MiB | none | — | — | shared_db_net |
| (optimizer, profile `disabled`) | 374fcce71a61 | 2026-06-23 11:48 | 3.12.13 (env) | not running | — | — | — | — |
| **postgres** (shared) | e013e867e712 | 2026-06-16 23:00 | PG 16.14 / Alpine 3.24.1 | 116.7 MiB / 512 MiB (22.8%) | none | 0.00 | 13 (none) | shared_db_net; 127.0.0.1:5432 |

- Every running container's image ID matches its `trading-signal-bot-*:latest` tag, so there is no drift between tags and what is running.
- All images are `linux/arm64`. MemorySwap is set to 2× the limit, but the host has no swap.
- Rollback anchors `b3-rollback/{scanner,telegram,trade_tracker}:pre-b3` are also on Python 3.12.13 and arm64.
- The compose file declares a hardened runtime (read_only, init, cap_drop ALL, no-new-privileges, tmpfs /tmp) on all 8 services. It was not verified at runtime because those inspect fields were outside the allowed set.
- No `pids_limit` is declared or set on any container.

## 4. PostgreSQL (psql at 20:56:48Z; upstream at 20:58:41Z–21:00:30Z)

| Item | Value |
|---|---|
| `SELECT version()` | PostgreSQL **16.14** on aarch64-unknown-linux-musl, gcc (Alpine 15.2.0), 64-bit |
| Image | `postgres:16-alpine`, **pinned by tag only** in `/home/tradmin/shared-postgres/docker-compose.yml`. Local digest `sha256:e013e867…` (created 2026-06-16) |
| Latest 16.x | **16.15**, released **2026-08-13** (postgresql.org versioning page and 16.15 release notes). **16.14 is not current.** |
| Docker Hub `16-alpine` now | `721873c34ceb…` = 16.15-alpine3.24, pushed 2026-09-21, arm64/v8 included |
| PG16 EOL | **2028-11-09** |
| Newest major | **18** (18.6). 17 is at 17.11 |
| Security after 16.14 | **25 CVEs fixed in 16.15 affect 16.14.** Many are CVSS 8.8 authenticated code execution: CVE-2026-16239, -14680, -14669, -14664, -14662, -14670, -15742, -14671; CVE-2026-15741 is SQL injection via EXTRACT deparse. There are also client-side issues in pg_dump/psql: CVE-2026-19385, -18408, -6464. |
| 16.15 upgrade caveat | No dump/restore is needed. However, the first three security entries require config adjustments or data cleanups (for example the new `output_plugin_libraries` setting), and btree_gist/ltree indexes may need REINDEX. |
| Settings | max_connections 100; shared_buffers 128MB; work_mem 4MB; effective_cache_size 4GB; **ssl off**; **data_checksums off**; wal_level replica |

## 5. Upstream status (lookups 20:57:27Z–21:00:30Z)

| Component | Running | Latest / status | EOL / support | Source (UTC fetch) |
|---|---|---|---|---|
| Python 3.12 | 3.12.13 (released 2026-03-03) | **3.12.14 (2026-08-12)**. The branch is **security-only** (bugfix support ended 2025-04-02) | **2028-10** (devguide) / 2028-10-31 | devguide 20:59:14Z; python.org API and release page 20:59:43Z; endoflife 20:58:53Z |
| Python 3.13 | — | 3.13.15 (2026-08-05); bugfix | 2029-10 | same |
| Python 3.14 | — | 3.14.7 (2026-08-05); bugfix, newest feature line. 3.15 is due 2026-10-01 | 2030-10 | same |
| Debian (TSB base) | 13 trixie | current stable; 13.7 released 2026-09-12 | security to 2028-08-09; LTS to 2030-06-30 | debian.org/releases 20:59:16Z |
| Debian bookworm | not used | oldstable; **regular security ended 2026-07-11** | LTS to 2028-06-30 | same |
| `python:3.12-slim` default | trixie | the index equals `3.12-slim-trixie` | — | Docker Hub 20:57:27Z |
| Alpine (postgres) | 3.24.1 | 3.24.2 | 2028-06-01 | endoflife alpine-linux 20:59:16Z |
| Docker Engine | 29.8.1 | **29.8.1 (2026-09-15)**: current, no CVEs listed; 28.x EOL 2026-05-13 | 29 has no announced EOL | docs.docker.com 20:59:15Z |
| Compose | v5.5.1 | **v5.5.1 (2026-09-03)**: current | — | docs.docker.com → github.com/docker/compose/releases 20:59:15Z |
| containerd | 2.3.6 | 2.3.6 (2026-09-24); 2.4.1 is the newest minor | 2.3 is **LTS to 2028-04-30** | endoflife 20:58:54Z |

## 6. Shared-host resource baseline (20:56:38–51Z)

**Totals**
- 12 vCPU. The summed container CPU in the snapshot was ~1.07% of one core.
- 23.4 GiB RAM with ~20.6 GiB available and no swap.
- 520G free disk.

**Memory**
- Containers use ~1.29 GiB RSS in total, of which TSB uses ~374 MiB.
- Declared hard limits come to 8 GiB: TSB 3 GiB, postgres 0.5 GiB, hermes 4 GiB, jadrawy-web 0.5 GiB.
- wishlist-app, xsch-app and xsch-caddy have **no memory limit**.

**Busiest containers**

| Container | Memory used / limit |
|---|---|
| hermes | 414 MiB / 4 GiB |
| wishlist-app | 126 MiB / unlimited |
| xsch-app | 124 MiB / unlimited |
| postgres | 117 MiB / 512 MiB |
| jadrawy-web | 115 MiB / 512 MiB |
| trading_analyzer | 109 MiB / 1 GiB |

trading_signal_engine has the most block writes (1.73 GB).

**Ports and networks**

| Container | Status | Networks | Ports |
|---|---|---|---|
| xsch-caddy | Up | twitter-scheduler_edge | **0.0.0.0:80, 0.0.0.0:443 (public)** |
| postgres | Up | shared_db_net | 127.0.0.1:5432 |
| xsch-app | Up | shared_db_net, twitter-scheduler_edge | 127.0.0.1:3000 |
| wishlist-app | Up | shared_db_net, twitter-scheduler_edge | 5000 exposed only |
| jadrawy-web | Up | twitter-scheduler_edge | 3000 exposed only |
| hermes | Up | hermes_net | — |
| wishlist-test-c2bui-c | Exited (255) | shared_db_net | 127.0.0.1:5091 reserved |
| trading_* | Up (learner exited) | shared_db_net + trading-signal-bot_trading_network | **none published** |

**Docker disk:**
- Images: 29.75 GB, 21.09 GB of it reclaimable.
- **Build cache: 141.8 GB, 131.8 GB of it reclaimable.**
- Volumes: 1.77 GB.
- Nothing was pruned.

**Daemon oddity:** `docker info` reports Running=13, but `docker ps` shows 12 (rechecked at 21:02:57Z). This is probably a stale counter from live-restore after the reboot, when wishlist-test exited with 255. It does not involve TSB.

**Headroom for an isolated test stack:**
- CPU: about 4 vCPU hard-capped.
- RAM: about 8 GiB hard-limited. That leaves at least 6 GiB of reserve for prod, hermes and page cache. A TSB mirror needs 3 GiB and a test postgres 0.5–1 GiB.
- Disk: ample.
- The binding constraints are isolation, not capacity.

## 7. Findings

| # | Sev | Finding |
|---|---|---|
| F1 | **HIGH** | The shared PostgreSQL is on **16.14**. **16.15** (2026-08-13) fixes **25 CVEs** that affect 16.14, several of them CVSS 8.8 authenticated code execution. The blast radius covers TSB, xsch and wishlist. Two things limit exposure: the port is bound to loopback only, and most exploits need an authenticated role. The minor upgrade has post-update steps (see §4). |
| F2 | MED | postgres is **pinned by tag only**. Any recreate or pull will jump silently to 16.15, and the running digest `e013e867…` is not recorded in compose. |
| F3 | MED | Every TSB image runs **Python 3.12.13**, one security release behind 3.12.14 (2026-08-12). The 3.12 branch is security-only until 2028-10. The base is frozen at 2026-06-11, so about 3.5 months of trixie security updates are also missing. |
| F4 | LOW | The base digest pin is sound and verifiably the base of what runs, but it is **orphaned upstream**: no tag points to it. It is still pullable (HEAD 200), but Docker Hub does not guarantee to keep untagged images. A local copy exists. |
| F5 | LOW | Rebuilds are **not bit-reproducible**: pip/wheel wildcards, no hashes or transitive lock, and unpinned apt in claude_review. |
| F6 | INFO | **arm64 is confirmed end-to-end.** Both the host and every image are arm64, and the pinned base and postgres indexes include arm64/v8. All local TSB images and rollback anchors are **arm64-only**, although the compose header claims amd64/Hetzner support. Moving to amd64 therefore means a rebuild, not an image load. amd64 is untested. |
| F7 | MED | **No PidsLimit on any container**, three neighbours with no memory limit, and **no swap**. A runaway container can exhaust PIDs or RAM for the whole host, with the OOM killer as the only backstop. |
| F8 | MED | `shared_db_net` connects the TSB services with postgres **and** wishlist-app/xsch-app, so there is cross-project L3 reach. The fixed `container_name: trading_*` values and the external network mean a second compose project would collide with or join prod. |
| F9 | LOW | postgres has `ssl=off` (acceptable only because traffic stays on loopback or the bridge) and `data_checksums=off`. `effective_cache_size` is 4GB against a 512 MiB cgroup; this is only a planner hint, not a real allocation. |
| F10 | INFO | Docker 29.8.1, compose v5.5.1, containerd 2.3.6 LTS, runc 1.5.1 and Ubuntu 24.04.5 are all **current**. There is no platform-layer gap. |
| F11 | INFO | The build cache (141.8 GB, 131.8 GB reclaimable) is the largest disk consumer. It was not touched. |

## 8. Isolation constraints for a future test plan

1. Keep test containers off `shared_db_net` and away from the prod postgres cluster. Use a private network and a separate postgres pinned **by digest**.
2. Override the compose project name, every `container_name` and all named volumes.
3. Avoid the host ports already in use: 80 and 443 (public), 127.0.0.1:5432, 127.0.0.1:3000 and 127.0.0.1:5091.
4. Set `mem_limit`, `cpus` **and** `pids_limit` on every test container. The host has no swap.
5. Test traffic leaves from the same egress IP as prod, so the exchange API rate limits and the Telegram bot identity are shared. Use no prod tokens or chats, and throttle exchange calls.
6. Do not prune images or build cache during test setup without owner approval, because the rollback anchors `b3-rollback/*` live in the same image store.
7. The images are arm64-only, so any amd64 or off-host test requires a rebuild.

## 9. Sources (UTC fetch time, HTTP status)

| Source | Fetched (UTC) | Status |
|---|---|---|
| Docker Hub tags `library/python?name=3.12-slim` | 20:57:27Z | 200 |
| Docker Hub tags `library/python?name=3.12.13-slim`, `3.12.14-slim`, `3.12.12-slim` | 20:57:53–54Z | 200 |
| registry-1.docker.io manifest **HEAD** for `sha256:d764629c…` and `f77ac9e4…` | 20:58:40Z | 200 |
| Docker Hub tags `library/postgres?name=16-alpine` and `16.1` | 20:58:41Z | 200 |
| endoflife.date `python`, `postgresql`, `docker-engine`, `debian`, `containerd`, `ubuntu` | 20:58:53–54Z | 200 |
| endoflife.date `docker-compose` | 20:58:54Z | 404 (product not tracked) |
| endoflife.date `alpine` → `alpine-linux` | 20:59:16Z | 301 → 200 |
| devguide.python.org/versions/ | 20:59:14Z | 200 |
| python.org/downloads/ | 20:59:14Z | 200 |
| python.org/downloads/release/python-31214/ | 20:59:43Z | 200 |
| python.org/api/v2/downloads/release/ | 20:59:43Z | 200 |
| postgresql.org/support/versioning/ | 20:59:14Z | 200 |
| postgresql.org/support/security/ | 20:59:14Z | 200 |
| postgresql.org/docs/release/16.15/ | 21:00:30Z | 200 |
| docs.docker.com/engine/release-notes/ (→ `/29/`) | 20:59:15Z | 200 |
| docs.docker.com/compose/releases/release-notes/ (→ github.com/docker/compose/releases) | 20:59:15Z | 200 |
| debian.org/releases/ | 20:59:16Z | 200 |

A non-interactive `sudo -n true` probe was run once. It reported no passwordless sudo, and no privileged command was executed.
