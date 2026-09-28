# BACKUP_RECOVERY_PLAN — Trading Signal Bot, Phase 1: backup and recovery preflight

| Item | Value |
|---|---|
| Repository | `baljadrawy/trading-signal-bot` (private) |
| Document | `docs/audits/2026-09-28/BACKUP_RECOVERY_PLAN.md`. This is a **plan for owner review**. None of it has been executed. |
| Observation window | 2026-09-27 21:49–22:05 UTC (2026-09-27 23:49 to 2026-09-28 00:05 CEST, host time) |
| Host | netcup VPS `375895`. One host serves **both development and production**; there is no staging host. aarch64, Ubuntu 24.04.5 LTS, kernel 6.8.0-142, 12 vCPU, 23.4 GiB RAM, **no swap**, one 743 GiB ext4 disk (`/dev/vda1`). Last boot: 2026-09-27 09:44 UTC. |
| Tools present | Docker Engine 29.8.1 (containerd image store), Compose 5.5.1, git 2.43.0. restic 0.19.1 and rclone 1.75.0 are in `~/.local/bin`. |
| State held throughout | PAPER_TRADING = **HALTED**; the effective B3 row is `2026-09-11 · paused · risk:loss_streak_halt · id 29415`. EXECUTION_MODE = PAPER_ONLY. LIVE_TRADING = FORBIDDEN. B3 unchanged. FORWARD_HOLDOUT sealed. `trading_continuous_learner` exited. |

**What this preflight did not do:**
- It created no backup.
- It installed, built, pulled, loaded, tagged, restarted or stopped nothing.
- It created, moved or deleted no Git ref, and it ran no `git fetch`.
- It changed no GitHub setting.
- It wrote nothing outside its own folder, `/home/tradmin/backups/tsb-backup-preflight-20260928/`.
- It opened no sealed-holdout content.

§1 lists the exact read-only method.

---

## 0. Executive summary

**What is already protected:**
- **Code and history.** All 221 commits reachable from any local ref are on GitHub; 0 commits are local-only.
- **Phase 0 (2026-09-27, 18:01–18:14 CEST).** An encrypted local restic repository, `/home/tradmin/backups/tsb-restic` (13,305 MiB, 5 snapshots), plus a staging folder containing:
  - a 27-ref Git bundle (17 local branches);
  - a 12-image / 15-tag image archive, including every rollback anchor;
  - the deployed code and the service logs.

  A full restore verified it at the time.
- **The `trading_signals` database.** It is dumped nightly at 03:17 CEST by the twitter-scheduler (xsch) backup job into a **local** restic repository. There are 12 snapshots; the latest is 2026-09-27 03:17 CEST.
- **Production is unchanged since Phase 0.** Its working tree is byte-for-byte the Phase-0 state; only the live `data/evidence/_telemetry.json` changed. The 12 production and rollback images still have the IDs recorded in Phase 0.

**Gaps, most important first:**
1. **No off-host copy of anything except Git.** The restic repository, the database dumps, the images, the evidence and the research data all live on the **same disk** as production. Losing the disk or the host would destroy production and every local backup together. Only the wishlist project's database leaves the host, to Google Drive.
2. **Key escrow is not confirmed.**
   - The `tsb-restic` password file and the xsch backup configuration, which holds the key to the `trading_signals` dumps, exist only on this host.
   - An off-host copy is useless until the owner stores these keys somewhere else.
3. **The existing bundles miss 5 branch tips (32 commits):** `develop`, `deploy/baseline-2026-09-27`, P1 `feature/forward-instrumentation`, `refactor/strategy-math`, and the PR #3 docs branch.
   - They exist only on GitHub, which has **no branch protection**.
   - This host holds a **read-write** deploy key.
4. **Records created after Phase 0 are in no backup.** They are:
   - the GitHub sync evidence;
   - the **P0 security package, which exists nowhere else**;
   - the execution-bot comparison;
   - the P1 report;
   - the post-P1 audits;
   - this preflight.

   Together they total about 1.6 MB.
5. **Images missing from any backup:**
   - the base image pinned by all 7 Dockerfiles, `python:3.12-slim@sha256:d764629c…`;
   - the database engine `postgres:16-alpine@sha256:e013e867…`, which is the rollback target for the PostgreSQL 16.15 update (D1).
6. **Database weaknesses:**
   - There is no dump owned by this project.
   - No scheduled restore test covers `trading_signals`; the monthly test covers xsch only.
   - There is no WAL archiving, so up to 24 hours of changes can be lost.
   - Data checksums are off.
   - The cluster-wide role dumps contain every project's password hashes.
7. **`/tmp` is emptied at every boot** (`D /tmp 1777 root root 30d`). The next reboot will delete the registered Git worktree `b3-worktree` and the session scratch files created after Phase 0. The impact is low: the worktree is clean and its branch is on GitHub.

**Recommendation.** Every step needs its approval checkpoint (§14). **No step needs downtime**: no container is stopped, restarted or recreated in any project.

| Stage | What it does | Size and time |
|---|---|---|
| A. Local Phase-1 backup | A fresh all-refs bundle. No fetch is needed, because the local tracking refs equal GitHub. A dump of the bot's database only, plus its schema and the roles without passwords. Two base images. The logs-volume delta. Host records. New snapshots in `tsb-restic`, deduplicated against Phase 0. | Adds about 0.25–0.6 GB. About 15–25 minutes. |
| B. Key escrow (owner) | The owner stores the keys somewhere else. | Before stage C |
| C. Off-host copy | Copies the **encrypted** repository to a destination the owner chooses (§7.6). | About 14 GB the first time. About 25–50 minutes at 5–10 MiB/s. |
| D. Isolated recovery drill | Restores and checks Git, files, the database (in a network-less throwaway PostgreSQL), the image archives, and an **off-host restore on a different machine**. The different machine is the only real proof of recovery after losing this host. | — |

---

## 1. Method, and the safety record of this preflight

- **Git:**
  - Read-only commands only, with `GIT_OPTIONAL_LOCKS=0`, so `status` did not rewrite the index: `for-each-ref`, `worktree list`, `stash list`, `count-objects`, `rev-list`, `merge-base`, `fsck --unreachable --no-reflogs`, `bundle verify/list-heads`.
  - `git ls-remote` for `origin` and `snapshot`.
  - GitHub API `GET` calls only: repo, branches, tags, releases, pulls, rulesets, keys.
  - **No fetch** was run and no ref was created.
- **Docker:**
  - Listings: `ps -a`, `image ls`, `volume ls/inspect`, `network inspect`, `system df -v`.
  - `inspect --format` templates that print only image, state, labels, mounts and networks. **Container environment variables were never printed.**
  - For export sizing, `docker save` was streamed straight into a byte counter or `tar -t`, and the output was discarded. **No image file was written, and nothing was loaded or tagged.**
- **PostgreSQL:**
  - `docker exec postgres psql` with `default_transaction_read_only=on`.
  - Catalog and statistics queries only: version, settings, databases and sizes, roles (names and attributes), extensions, tablespaces, WAL size, and sessions grouped by database, user, application and client, **without query text**.
  - The only application row read is the B3 effective-decision row. The handoff lists that row as a safe read-only check.
  - No application table content was read. No sealed-holdout row was read.
- **Backups:**
  - File listings and sizes.
  - `restic snapshots` with `--no-lock --no-cache`, so nothing was written to any repository.
  - Log tails of the backup jobs, passed through a credential-redaction filter.
- **Secrets:**
  - Secret-bearing files were inventoried by **name and mode only**, never by content or size.
  - The crontab was read through a redaction filter; the two `Authorization` headers print as `[REDACTED]`.
- **Sealed holdout:**
  - Located by definition, path, date-named file and catalog metadata only.
  - No evidence file, database row or log line from the holdout period was opened.
- **Evidence** is in `work/`: 37 small text files (mode 600, folder 700), listed in Appendix A. `MANIFEST.sha256` at the folder root covers them and this plan.

---

## 2. Git inventory (task 1)

### 2.1 GitHub, at 2026-09-27 21:51 UTC

| Item | Value |
|---|---|
| Visibility / default branch | private / `main` (`0a396c2`) |
| Branches | **13**. None is protected. `rulesets` = 0. `delete_branch_on_merge` = false. |
| Tags / releases | **0 / 0** |
| Pull requests | #3 open **draft**: `docs/market-intelligence-governance-20260927` @ `b9d352e` → `develop`. #1 and #2 (`dev` → `main`) were merged on 2026-04-08. |
| PR refs | `pull/1/head` = `cf1b9b2`: the object is local but no local ref names it; it is an ancestor of `05999ea`. `pull/2/head` = `c7e9b88` (= `dev`). `pull/3/head` = `b9d352e`. `pull/3/merge` = `97e40ea` is a GitHub-generated test merge; it is not local and is not needed. |
| Deploy key | `server-signalbot-rw`, **read_only = false**, created 2026-06-21 |
| Separate archive repository | `baljadrawy/signal-bot-live-learning-snapshot`: private, `main` = `0a396c2`, last push 2026-07-01 |
| Local remote-tracking refs vs `ls-remote` | **All 13 equal, SHA for SHA.** All 13 objects are present locally, so **no fetch is needed** for a complete bundle. |

### 2.2 Local refs (common Git directory `/home/tradmin/trading-signal-bot/.git`, 47 MiB, 221 commits)

| Ref | SHA | On GitHub | Notes |
|---|---|---|---|
| `develop` | `4e3eb0a` | yes | integration base; `main` is 44 commits behind it |
| `main` | `0a396c2` | yes (default) | 0 unique commits |
| `deploy/baseline-2026-09-27` | `3ed49c3` | yes | known-good production record; parent is B3 `8bfca77` |
| `fix/b3-fail-closed-trading-state` | `8bfca77` | yes | B3 source; contained in develop |
| `integration/research-pipeline` | `63da7d3` | yes | checked out in the **production folder** |
| `feature/forward-instrumentation` (P1) | `23dea90` | yes | **+1 unique** vs develop; not merged or deployed |
| `refactor/strategy-math` | `6d6790f` | yes | **+1 unique**; unreviewed |
| `safety/disable-auto-tune` | `3d1857d` | yes | **+1 unique**, 44 behind (diverged) |
| `fix/loss-streak-recovery-epoch`, `feat/py312-feature-store-audit-2026-06-23`, `feat/throttle-decay-2026-08-10` | `05999ea`, `d91fd50`, `912b51a` | yes | contained in develop |
| **10 local-only names:** `fix/{fee-net-gate-2026-07-29, measurement-layer-2026-07-15, neutralize-4f84717-2026-07-29, report-net-fees-2026-07-29}`, `research/{evidence-capture-filter, falsification-library, flight-recorder, health-monitor, null-a-evidence-store, recorder-hardening}` | `1d090be`, `c2725a9`, `cdd3450`, `f9dbc77`, `928ff1a`, `bf7b0a1`, `7b45a8f`, `5157ca9`, `2ec84fd`, `f72d623` | **names: no. Commits: yes** (all ⊂ `origin/develop`) | only the branch *names* are local-only |
| `origin/*` (13), `origin/dev` and `origin/docs/market-intelligence-governance-20260927` (`b9d352e`) | = GitHub | — | the docs branch was fetched during the 2026-09-27 publish task |
| `snapshot/main` | `0a396c2` | archive repository | — |
| tag `snapshot-live-learning-0a396c2` (lightweight) | `0a396c2` | **tag: no. Commit: yes** | local only |
| Stash | none | — | — |

**Branches with unique commits vs `develop`:**
- P1: +1.
- refactor: +1.
- safety: +1 (and 44 behind).
- docs / PR #3: **+22** (21 by the owner plus `b9d352e`, the audit publication).

### 2.3 Worktrees (6)

| Path | Branch @ SHA | State |
|---|---|---|
| `/home/tradmin/trading-signal-bot` | `integration/research-pipeline` @ `63da7d3` | **Production compose folder.** 111 status entries (224 with `-uall`: 7 modified, 217 untracked). This is **identical to the Phase-0 inventory**. 76 ignored entries. 6,546 MiB on disk. |
| `/home/tradmin/tsb-baseline` | `deploy/baseline-2026-09-27` @ `3ed49c3` | clean |
| `/home/tradmin/tsb-develop` | `develop` @ `4e3eb0a` | clean |
| `/home/tradmin/tsb-p1` | `feature/forward-instrumentation` @ `23dea90` | clean (1 ignored entry) |
| `/home/tradmin/tsb-refactor` | `refactor/strategy-math` @ `6d6790f` | clean |
| `/tmp/claude-1000/…/scratchpad/b3-worktree` | `fix/b3-fail-closed-trading-state` @ `8bfca77` | clean, but **on `/tmp`**, which is emptied at boot (§6.5) |

### 2.4 Git state that no bundle can carry

| Item | Finding | Covered by |
|---|---|---|
| Reflogs, `.git/worktrees/*` metadata, `config` (remotes, upstreams), hooks (samples only) | Present locally | A file-level `.git` copy in restic only. Phase-0 snapshot `b965532a` holds the state as of 18:01 CEST, **before** the 5 new tips existed. |
| Commits reachable only from a reflog | 0 | — |
| Unreachable commits | 2: a stash dropped on 2026-08-12 (`7029799`, `0446a66`). Its only change, `docs/canary_state.md`, is **byte-identical** to develop's blob `8fd6159`. | Nothing is unique, so no action is needed |
| Unreachable blob | 1 (`9b65664…`, 25,519 B, loose since 2026-06-23). **Not opened.** | Only a file-level `.git` copy. A future `git gc` would prune it. |

---

## 3. Existing Git bundles and coverage (task 2)

### 3.1 Bundles on the host

A search of `/home/tradmin`, `/tmp`, `/srv`, `/opt`, `/var/backups`, `/mnt` and `/media` found exactly two.

| Bundle | Size, date | Refs | `bundle verify` | sha256 |
|---|---|---|---|---|
| `/home/tradmin/backups/tsb-phase0-20260927/git/trading-signal-bot-all-refs-20260927.bundle` | 41,617,046 B, 2026-09-27 17:50 CEST | 27 refs / 19 SHAs: 17 local heads, 7 remote-tracking refs, 1 tag, `HEAD`, `worktrees/b3-worktree/HEAD` | **okay, complete history** | `bbd4e52b4ba7557f…`, matches the Phase-0 `MANIFEST-INDEX` |
| `/home/tradmin/backups/signal-bot-live-learning-0a396c2.bundle` | 41,386,109 B, 2026-07-01 | 1: tag `snapshot-live-learning-0a396c2` | **okay, complete history** | `e176cece4b9d20b5…` |

A related file is `/home/tradmin/backups/signal-bot-live-learning-0a396c2.tar.gz` (41,430,525 B, 2026-07-01).

### 3.2 Coverage of every current ref

"Covered" means the SHA is a head of either bundle or an ancestor of one.

| Result | Refs |
|---|---|
| **Covered** | `main`, `integration/research-pipeline`, B3 `8bfca77`, `safety/disable-auto-tune`, `fix/loss-streak-recovery-epoch` and both `feat/*` branches (local and remote); the 10 local-only names; `origin/dev` and `pull/1..2/head`; `snapshot/main`; the tag |
| **NOT covered** | `develop` and `origin/develop` (`4e3eb0a`); `deploy/baseline-2026-09-27` and its remote (`3ed49c3`); `feature/forward-instrumentation` and its remote (`23dea90`); `refactor/strategy-math` and its remote (`6d6790f`); `origin/docs/market-intelligence-governance-20260927` = GitHub `pull/3/head` (`b9d352e`). |
| Stale value inside the Phase-0 bundle | Its `refs/remotes/origin/integration/research-pipeline` = `c4a623c`. Today it is `63da7d3`, and the bundle does contain `63da7d3` as a local head. |

### 3.3 Commits missing from every bundle: **32**

Full list in Appendix B.

| Group | Commits |
|---|---|
| `develop` beyond the Phase-0 bundle | 8: `3ed49c3` (baseline record), `39d701d`, `d221514`, `224bfa6`, `2cd9e68`, `b1c804d`, `970dda9`, `4e3eb0a` |
| `refactor/strategy-math` | 1: `6d6790f` |
| P1 | 1: `23dea90` |
| PR #3 docs branch | 22: 21 by the owner (`3c5a633` … `2ffb44b`, 2026-09-27 22:58–23:52 +0300) plus `b9d352e` (the audits) |

**Conclusion:**
- All 32 commits are on GitHub.
- The file-level `.git` copy in Phase-0 snapshot `b965532a` also predates them.
- Their only copies independent of GitHub are the object store of this very host.
- **One new `--all` bundle closes the gap.** It needs no fetch, because every GitHub tip is already local (§2.1).

---

## 4. Docker: containers, images, Compose files, mounts, volumes (task 3)

### 4.1 Containers on the host (14)

| Project | Containers | Started (UTC) |
|---|---|---|
| **trading-signal-bot** (Compose project, directory `/home/tradmin/trading-signal-bot`, `docker-compose.yml`) | `trading_scanner` 9b0b53a6a799 · `trading_analyzer` ce305ecd7760 · `trading_signal_engine` b3d4b6236654 · `trading_tracker` 2b59c6a164c0 · `trading_telegram` b84d3d1528a0 · `trading_claude_review` 8bca25750c77. All Up and healthy. Plus `trading_continuous_learner` d1aa69bde63f, **Exited (143)**, which must stay stopped. | analyzer, signal_engine, claude_review 09:44:59 (boot) · tracker 12:36:54 · telegram 12:37:29 · scanner 12:37:47 (B3 overlay) · learner last 2026-08-17 |
| shared-postgres (`/home/tradmin/shared-postgres`) | `postgres` (`postgres:16-alpine` e013e867e712), healthy, memory limit **512 MiB** | 09:44:59 |
| twitter-scheduler (xsch) | `xsch-app`, `xsch-caddy`. Caddy serves 0.0.0.0:80/443 for the public sites. | 09:44:59 |
| wishlist (gjafa) | `wishlist-app` (image `wishlist-app:ce778a893d88`, no Compose labels); `wishlist-test-c2bui-c` (exited test container on `shared_db_net`) | 09:44:59 |
| jadrawy | `jadrawy-web` | 09:44:59 |
| hermes | `hermes` (own network and volume) | 12:00:19 |

### 4.2 Images the bot needs preserved

With the containerd store, image ID = the image's index or manifest digest.

| Role | Tag(s) | ID | Export size | In Phase-0 image tar |
|---|---|---|---|---|
| scanner (running) | `trading-signal-bot-scanner:latest`, `b3prep-20260927T120659/scanner:candidate` | 9b0b53a6a799 | — | **yes** |
| analyzer (running) | `trading-signal-bot-analyzer:latest`, `r1b-base:analyzer-ce305ecd` | ce305ecd7760 | — | **yes** |
| signal_engine (running) | `trading-signal-bot-signal_engine:latest` | b3d4b6236654 | — | **yes** |
| trade_tracker (running) | `trading-signal-bot-trade_tracker:latest`, `b3prep…/tracker:candidate` | 2b59c6a164c0 | — | **yes** |
| telegram (running) | `trading-signal-bot-telegram:latest`, `b3prep…/telegram:candidate` | b84d3d1528a0 | — | **yes** |
| claude_review (running; **must never be rebuilt**) | `trading-signal-bot-claude_review:latest` | 8bca25750c77 | — | **yes** |
| continuous_learner (exited) | `trading-signal-bot-continuous_learner:latest` | d1aa69bde63f | — | **yes** |
| Rollback anchors | `b3-rollback/scanner:pre-b3` 4d59ba3d6e79 · `b3-rollback/telegram:pre-b3` = `tgrelease:risk1d` fb0ef1b9097a · `b3-rollback/trade_tracker:pre-b3` = `ttrelease:risk1d` c60cac87920a · `trade_tracker:pre-risk1-rollback` d291f64e0795 · `telegram:pre-risk1-rollback` ab4bc1077b6c | — | — | **yes** |
| **Build base, pinned by all 7 Dockerfiles** | `python:3.12-slim@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9` (arm64 manifest `9bde4953fa9a…`) | d764629ce0dd | about **46 MB** | **no** |
| **Database engine** (shared; D1 rollback target) | `postgres:16-alpine` | e013e867e712 | **114.5 MB** | **no** |
| Research replay environment (Research-1B) | `r1b-replay:analyzer-ce305ecd-pyarrow` | 923f43cacb83 | 142.0 MB | no (optional) |
| Disabled optimizer | `trading-signal-bot-optimizer:latest` | 374fcce71a61 | 61.0 MB | no (optional) |
| Test environment | `tsb-sync-test:pytest` | 38cb032c4e48 | 145.9 MB | no (optional) |

**Verification of the Phase-0 tar:**
- All 15 Phase-0 tags still resolve to the IDs in `images/image_tags_ids.txt`.
- The tar `images/trading-signal-bot-images-20260927.tar` (568,331,776 B, sha256 `2b8b3f41…`) was re-hashed by the cleanup audit on 2026-09-27 and matched.

**Base-image nuance, tested by streaming only:**
- `docker save python:3.12-slim` **without** `--platform` keeps the index digest `d764629c…` that the Dockerfiles pin.
- With `--platform linux/arm64`, it records only the platform manifest `9bde4953…`.
- **Save the base images without `--platform`.**

**Other projects' images** are out of scope and belong to their own backups: xsch, caddy, wishlist (7 tags), hermes, jadrawy, `shared-postgres-backup:local`, `restic/restic:0.18.0`.

### 4.3 Compose files and running configuration

| File | State |
|---|---|
| `/home/tradmin/trading-signal-bot/docker-compose.yml` (8,031 B) | Tracked. Byte-identical to `develop`, `3ed49c3` and `8bfca77`. It declares **only** `logs_data` and `models_data` as project volumes. The learner has no disabling profile, so a bare `up -d` would start it. `optimizer` has `profiles: ["disabled"]`. |
| `/home/tradmin/trading-signal-bot/docker-compose.yml.bak` (2026-06-21) | Historical; untracked |
| `/home/tradmin/shared-postgres/docker-compose.yml` | Its own GitHub repo, `baljadrawy/shared-postgres`, is clean at `40c5328`. It defines the external volume `trading-signal-bot_postgres_data`, the port `127.0.0.1:5432`, the 512m memory limit and the one-shot `shared-postgres-backup` service. |
| Staged P0 compose files (`compose/docker-compose.p0.step1..6.yml`) | In `/home/tradmin/backups/tsb-p0-security-20260927/` only; not deployed |
| **Configuration drift** (P0 finding) | analyzer, signal_engine and claude_review run an older configuration than the compose file on disk. Recreating them would apply the new one. The environment-free container records from Phase 0 (`images/container_records.json`) must be refreshed in the new backup. |

### 4.4 Mounts and volumes

| Source | Used by | Size | Preserve? |
|---|---|---|---|
| **bind** `/home/tradmin/trading-signal-bot/data/evidence` → `/app/data/evidence` (rw) | signal_engine | 182 MiB (§6.1) | **yes**, via the working-tree snapshot. The directory is untracked and not ignored, so the production folder itself is a runtime dependency. |
| **bind** `~/.claude` and `~/.claude.json` (ro) | claude_review | — | **secret-bearing** (Claude CLI sign-in). Not backed up. Re-issued at recovery (§7.7). |
| **volume** `trading-signal-bot_logs_data` | all 6 running services | 196.9 MB | **yes**. Phase 0 holds 188 MB; the delta is about 9 MB. |
| **volume** `trading-signal-bot_models_data` | analyzer, signal_engine | 0 B | nothing to preserve |
| **volume** `trading-signal-bot_postgres_data` → `/var/lib/postgresql/data` (PGDATA `…/pgdata`) | `postgres` (**all projects**) | 176.4 MB | Logical dumps per project (§5). It carries **no Compose project label** and is external to shared-postgres, so `down -v` of the bot project would not match it. Never touch it. |
| Future **bind** `./data/evidence_v2` (P1) | analyzer, signal_engine, trade_tracker, telegram | 25–40 MB/day once enabled | include once P1 is deployed (G5/D4/D8) |

**Networks:**
- `shared_db_net` (172.18.0.0/16, no project label). Members: wishlist-app .2, xsch-app .3, postgres .4, and the bot services .5–.10.
- `trading-signal-bot_trading_network` (172.19.0.0/16).
- `twitter-scheduler_edge` (172.20.0.0/16).
- `hermes_net` (172.21.0.0/16).

### 4.5 Items not to preserve, and hygiene findings (owner decision, CP-10)

- **Build cache: 141.8 GB (131.8 GB reclaimable).** Not a backup item. It is the largest consumer of the shared disk.
- **16 unused anonymous volumes (923 MB).** Most are about 48–51 MB, the size of an empty initialized PostgreSQL 16 cluster. Some are larger: `3e2ef181…` 111.9 MB (2026-09-27 13:02 CEST), `622d5dd5…` 74.5 MB, `199cacd6…` 74.4 MB, `04825472…` 65.8 MB.
  - They are probably left over from disposable test databases that were removed without `-v`.
  - The larger ones **may hold copies of production rows, including sealed-holdout rows**.
  - **Do not back them up. Do not prune them without an owner-reviewed inspection.** A blanket `docker volume prune` would also remove them without review.

---

## 5. The shared PostgreSQL cluster (task 4)

### 5.1 Cluster facts

| Setting | Value | Consequence |
|---|---|---|
| Version | **16.14** (Alpine, aarch64) | the 16.15 update (D1) is pending: 25 CVEs, including client-side pg_dump/psql issues |
| Engine image | `postgres:16-alpine` e013e867e712; memory limit 512 MiB; started 09:44:59 UTC | `docker exec pg_dump` runs **inside this memory limit**, next to the server that serves every project |
| Data | volume `trading-signal-bot_postgres_data`, PGDATA `/var/lib/postgresql/data/pgdata`, 176.4 MB, WAL 4 × 16 MiB | a physical copy would be about 180 MB |
| `archive_mode` | **off**. `archive_command` is empty or disabled. `pg_stat_archiver`: 0 archived. 0 replication slots. | **No point-in-time recovery.** Up to 24 hours of changes can be lost (nightly dump). |
| `wal_level` / `max_wal_senders` | replica / 10 | `pg_basebackup` is possible (not proposed now) |
| `data_checksums` | **off** | page corruption is not detected; §10 adds `amcheck` on the restored copy |
| Network | `listen_addresses='*'` inside the container; published on the host at **127.0.0.1:5432 only** | no direct external client is possible (Colab would need an SSH tunnel) |
| `password_encryption` | scram-sha-256 | — |

### 5.2 Databases and dependent projects

| Database | Owner role | Size | Project | Live sessions at 21:55 UTC | Existing backup |
|---|---|---|---|---|---|
| `trading_signals` | `trading_signal_bot` | 53,066,775 B (51 MB) | **trading-signal-bot** | 6 (the 6 running services, app `trading_bot`, 172.18.0.5–.10) | nightly by the **xsch job**, local only |
| `wishlist` | `wishlist_user` | 12 MB | wishlist (gjafa.com) | 0 at that instant | nightly by the **shared-postgres job**, **off-host** (Google Drive) |
| `xsch` | `xsch_user` | 9.7 MB | twitter-scheduler (xsch.gjafa.com) | 2 (xsch-app) | nightly by the xsch job, local only; monthly restore test |
| `wishlist_test` | `wishlist_test_role` | 9.1 MB | wishlist tests (a test database **inside the production cluster**) | 0 | none |
| `postgres`, `template0/1` | `trading_signal_bot` | 7.4–7.6 MB each | maintenance | 1 (this preflight) | globals only |

- No external client was connected. Only `local` and Docker `172.18.0.x` sessions were present.
- The bot database holds 25 tables, 18 sequences and 53 indexes. It uses the `plpgsql` extension only and has 0 large objects. The largest tables are `signals` (34 MB) and `analysis_results` (5.5 MB).

**Roles** (names and attributes only):
- `trading_signal_bot`: **SUPERUSER** with every attribute. It is the cluster's bootstrap superuser, it belongs to *this* project, and both backup jobs use it to dump roles.
- `xsch_user`, `wishlist_user`, `wishlist_test_role`: login only.
- `shared_pg_backup`: login, member of `pg_read_all_data`.
- There are 0 `tsb_*` roles; the P0 rollout is still deferred.

### 5.3 Existing database backups and schedules

Crontab of `tradmin`, host time CEST; credentials redacted. There are no system timers for backups.

| When | Job | Scope | Destination | Last result |
|---|---|---|---|---|
| daily 03:17 | `twitter-scheduler/scripts/backup-run.sh` | **`xsch` and `trading_signals`** (custom-format dumps, checked with `pg_restore --list`) plus `pg_dumpall --globals-only` **with password hashes** | restic **local** `/home/tradmin/backups/restic` (21 MiB); keep 7 daily / 4 weekly / 12 monthly | 12 snapshots, `85741dfa` (2026-08-03) … **`ac3ce687` 2026-09-27 03:17:03**; last success 03:17:05 |
| Sun 04:07 | `backup-verify.sh` | `restic check` plus a 20% data read; snapshot age | same | 2026-09-27 04:07, no errors |
| 1st of month 04:37 | `backup-restore-test.sh` | **xsch only**, restored into `xsch_restore_test` **inside the production cluster** | — | 2026-09-01 04:37 |
| daily 03:23 | `shared-postgres/scripts/backup-run.sh` → one-shot `shared-postgres-backup` container | globals (with hashes) and `wishlist` | restic `rclone:gdrive:shared-postgres-backup`, **off-host** (Google Drive). The older local repository `/home/tradmin/backups/shared-postgres-restic` (3 snapshots) is left from the pre-Drive phase. | 12 snapshots; last success 2026-09-27 01:24 UTC |
| daily 03:40 | `hermes/backup.sh` | hermes project (not PostgreSQL) | local `hermes-restic` | — |
| every 12h at :30 (00:30, 12:30) | `trading-signal-bot/research/walk_forward_audit.sh` | reads the database through `docker exec psql`; writes a log into the production folder | — | — |
| */30 min | `canary_watchdog.py` (venv inside the production folder) | reads `.env` and telemetry, runs `docker inspect` | — | — |

**Database gaps for this bot:**
- No dump owned by this project, under its own key and repository.
- No off-host copy.
- **No scheduled restore test of `trading_signals`.** Phase 0 ran one isolated test on 2026-09-27.
- The only dumps carry **every project's role password hashes**.
- Up to 24 hours of changes can be lost.
- Data checksums are off.

---

## 6. Evidence, sealed holdout and research artifacts (task 5)

### 6.1 Evidence v1

The directory is `/home/tradmin/trading-signal-bot/data/evidence`. It is bind-mounted into signal_engine, untracked, and not ignored.

- **72 files, 182 MiB:**
  - 69 files `evidence-2026-06-29.jsonl` … `evidence-2026-09-11.jsonl`;
  - `_telemetry.json` (live; rewritten every cycle);
  - `_telemetry.PhaseA-R1.json`;
  - `_phaseA-R1_conclusion.txt`.
- By file-name date:
  - **23 files dated 2026-08-19 or later, 186.0 MB.** This is the holdout period. The 2026-08-19 file straddles the freeze instant.
  - 46 earlier files, 4.3 MB.
- The last JSONL was written 2026-09-11 18:20 CEST, at the halt.
- **Since Phase 0 only `_telemetry.json` changed.** Phase-0 snapshot `b965532a` holds all 72 files, with SHA-256 values in `manifests/SHA256-repo-worktree.txt`.

### 6.2 Evidence v2 (proposed by P1; not deployed)

- **Location:** `/home/tradmin/trading-signal-bot/data/evidence_v2/<service>/` as a new bind mount for analyzer, signal_engine, trade_tracker and telegram. **It does not exist yet.**
- **Expected volume:** 25–40 MB/day.
- **Plan:** add the path to the snapshot includes on the day it is created (CP-9, G5/D4/D8). It must never be placed on `/tmp`.

### 6.3 Sealed holdout: where it lives and the handling rules

**Definition** (research governance): FORWARD_HOLDOUT is everything after **2026-08-19T09:33:46Z** (freeze commit `63da7d3`). The seal records themselves are metadata tracked on `develop`, and therefore on GitHub:
- `research/governance/holdout_status.json`
- `research/governance/research_freeze.json`
- `research/governance/freeze_config.json`
- `research/governance/contamination_registry.jsonl`

| Holdout-bearing location | Metadata observed (content not opened) |
|---|---|
| `trading_signals` rows timestamped after the freeze (signals, analysis, trades, results, approvals, outbox, risk rows) | database 51 MB. Backed up only as whole-database dumps. |
| Evidence v1 files dated 2026-08-19 to 2026-09-11 | 23 files, 186.0 MB |
| Service log lines after the freeze | `logs_data` volume (196.9 MB) and the Phase-0 `logs-volume/` copy |
| Possible copies | the 16 anonymous volumes (§4.5); derived research outputs (for example `research/runs/p0r-00aa3ea80de7/`, Phase-0 session research). Not opened; treat as holdout-bearing. |

**Handling rules (H1–H6).** These form the approval content of CP-2, CP-5, CP-6 and CP-8.

| Rule | Content |
|---|---|
| **H1** | No person or agent opens, parses, samples, greps or displays holdout-period content. |
| **H2** | Backup tools may read holdout bytes **mechanically**: `pg_dump`, `restic`, `sha256sum`. |
| **H3** | Verification uses only checksums, dump entry counts, per-table row counts, a schema comparison, and the single B3 effective-decision row. It never selects outcome, price or PnL columns. It never `cat`s evidence files and never runs `restic dump` on them. If the owner prefers, row counts can be limited to tables outside the holdout (Q4). |
| **H4** | Restores that contain the holdout go **only** into isolated scratch directories or network-less throwaway containers, which are destroyed afterwards. No research code runs against a restored copy. |
| **H5** | Off-host copies are encrypted client-side (restic AES-256). The storage provider's credentials cannot decrypt them. |
| **H6** | Every command run against holdout-bearing artifacts is logged in the run log. |

### 6.4 Research data

The directory is `/home/tradmin/research-data/trading-signal-bot`.

| Item | Value |
|---|---|
| Size | 8,746 MiB on disk; 8.39 GiB in restic |
| Files | 51,997 |
| Contents | `raw` 2,922 MiB, `snapshots` 5,801 MiB, `ds-d82b982e7221e2dcc7b7` 23 MiB, plus small `certification`, `normalized` and `universe` directories |
| Created | 2026-08-19 |
| Changed since Phase 0 | 0 files, so snapshot `ac2d1b05` covers it completely |

It was created on the freeze day, and its content was not inspected. Handle it under H1–H6.

### 6.5 Untracked research artifacts and session scratch

- **Production folder.** There are 217 untracked files, identical to the Phase-0 inventory:
  - 121 are byte-identical to develop blobs;
  - 91 exist only on disk: 72 evidence files and 19 `research/skill_application/**/*.csv|*.jsonl` outputs.
  - There is **no unique untracked code**.
  - All of it is in `b965532a`.
  - Excluded by design: `research/skill_application/.venv` (1.5 GB, rebuildable), `__pycache__`, `.pytest_cache`, and all `.env*` files.
- **Session scratch** `/tmp/claude-1000/-home-tradmin/f9e8015a-…/scratchpad` (about 2.9 GB):
  - **Covered by snapshot `c6ee6bdb` (18:03 CEST):** the R1B replay harness (`r1b/`, 175 MB), R1A probes and scripts, B3 preparation, the patch and the validation files, all created before 16:03 UTC.
  - **Deliberately excluded:** `deployed/` and `deployed_now/` (1.3 GB each; derived copies of container filesystems) and `b3-worktree` (clean; its branch is on GitHub).
  - **Not covered:** about 12 MB of post-Phase-0 working files (dependency and cleanup audit sources, `code_audit/`, `gh/` API dumps, `p1/`, `inst/`). Their final outputs are persisted in `/home/tradmin/backups/tsb-*`.
  - Also present: `trading-bot/` (1 MB), a read-only clone of **another** private repository. **Do not back it up**; it is on GitHub.
- **`/tmp` lifetime.** `/usr/lib/tmpfiles.d/tmp.conf` contains `D /tmp 1777 root root 30d`. `/tmp` is therefore **emptied at every boot** and aged out after 30 days. The host rebooted on 2026-09-27 at 09:44 UTC. Other session folders in `/tmp/claude-1000` (for example 304 MB for another session) belong to other work.

### 6.6 Decision and audit records created after Phase 0 (in no backup)

The folders below total about 1.6 MB, and a pattern scan found no credentials in any of them.

| Folder | Files | Size | Notes |
|---|---|---|---|
| `tsb-sync-20260927` | 28 | 208 KB | |
| `tsb-p0-security-20260927` | 55 | 396 KB | roles.sql v2, test harness, staged compose files, report. **Its only copy.** |
| `tsb-exec-comparison-20260927` | 5 | 64 KB | |
| `tsb-p1-instrumentation-20260927` | 10 | 56 KB | |
| `tsb-post-p1-audit-20260927` | 9 | 832 KB | its 3 documents are also on GitHub |
| `tsb-backup-preflight-20260928` | — | — | this preflight |

---

## 7. Storage, destinations, sizes and restoration requirements (task 6)

### 7.1 Capacity

| Resource | Value | Note |
|---|---|---|
| Disk `/dev/vda1` (ext4) | 743 GiB total, 224 GiB used, **520 GiB free** (31% used) | **One filesystem** for Docker (`/var/lib/docker`), `/home`, `/tmp` and every local backup, so it is a single failure domain |
| Docker | images 29.75 GB (52), volumes 1.77 GB, build cache 141.8 GB | — |
| Memory | 23,975 MiB total; 20,914 MiB available; **no swap** | Throwaway workloads need hard memory limits: an out-of-memory event could kill `postgres`, which serves every project. |
| Load | 0.77 / 0.63 / 0.53 | ample headroom |

### 7.2 Existing destinations

| Destination | Type | Used for |
|---|---|---|
| `/home/tradmin/backups/tsb-restic` | local restic, encrypted, 13,305 MiB | Phase 0 (this bot) |
| `/home/tradmin/backups/tsb-phase0-20260927/` | local staging, 827 MiB | bundle, image tar, deployed code, logs, manifests, runbooks |
| `/home/tradmin/backups/restic` | local restic, 21 MiB | xsch job (xsch and `trading_signals`) |
| `/home/tradmin/backups/shared-postgres-restic`, `hermes-restic` | local restic | other projects |
| `rclone` remote `gdrive:` | **off-host** (Google Drive, OAuth token on this host) | wishlist database (shared-postgres job) |
| GitHub (`origin`, `snapshot`) | **off-host**, code only | all commits |

### 7.3 Coverage matrix

| Asset | Local copy | Off-host copy |
|---|---|---|
| Commits (221) | bundle misses 32 (§3) | **GitHub (all)**; mutable (read-write deploy key, no protection) |
| Branch names (21 local), tag, reflogs, worktree metadata | bundle and `b965532a` (stale since 18:01 CEST) | branch names 13/23; tag no |
| Production working tree and untracked work, evidence v1 | `b965532a` (current; only telemetry changed) | **none** |
| Research data 8.4 GiB | `ac2d1b05` (current) | **none** |
| Session research (R1A, R1B, B3 preparation) | `c6ee6bdb` | **none** |
| Production and rollback images (12 IDs / 15 tags) | Phase-0 tar (current) | **none** |
| Base image and database engine image | image store only | **none** (Docker Hub may still serve them by digest; not guaranteed) |
| `trading_signals` database | xsch repository (nightly) | **none** |
| Logs volume | Phase 0 (−9 MB) | **none** |
| Records after Phase 0 (§6.6) | **none** | 3 audit documents on GitHub |
| Secrets (§7.7) | the host only | **unknown**, depends on owner escrow |

### 7.4 Missing backup items (consolidated)

| # | Missing item | Priority |
|---|---|---|
| **M1** | 5 tips / 32 commits in no bundle; their GitHub copy is mutable | P1 |
| **M2** | No off-host copy of any non-Git asset of this bot | **P0 for resilience** |
| **M3** | Keys not escrowed: the `tsb-restic` password, the xsch backup configuration's key, and the future off-host credentials | **P0**; blocks M2's value |
| **M4** | Records after Phase 0, including the only copy of the P0 package | P1 |
| **M5** | Base image `python:3.12-slim@sha256:d764629c…` and `postgres:16-alpine@sha256:e013e867…` | P1 (reproducibility and D1 rollback) |
| **M6** | Optional research images `r1b-replay` (R1B reproducibility), `tsb-sync-test`, `optimizer` | P3 |
| **M7** | No dump owned by this project; roles only exist with other projects' hashes; no scheduled restore test of `trading_signals`; up to 24 hours of changes can be lost | P1 |
| **M8** | Logs-volume delta (about 9 MB) | P3 |
| **M9** | Post-Phase-0 scratch (about 12 MB); `b3-worktree` on `/tmp` | P3 |
| **M10** | Refreshed host records: container records without env (drift), network and volume definitions, cron lines of this bot, platform versions | P2 |
| **M11** | Evidence v2 retention and backup (future) | P2 at P1 deployment |
| **M12** (outside this bot's scope; D1) | No cluster-level physical backup; xsch database local only (xsch D-10) | D1 prerequisite |

### 7.5 Expected size

"New data" means data added to `tsb-restic` after deduplication; these are estimates.

| Component | Raw | New data | Notes |
|---|---|---|---|
| Git bundle `--all` | about 42 MB | ≤ 42 MB | a file; partial deduplication against the Phase-0 bundle |
| Production folder, including `.git` (Phase-0 excludes), parent `b965532a` | 4.46 GiB | about 10–60 MB | new objects, telemetry |
| Research data, parent `ac2d1b05` | 8.39 GiB | about 0 | unchanged |
| Database dump (custom format), schema, roles without passwords, row counts | about 3 MB | about 3 MB | the Phase-0 dump was 2,469,335 B |
| `python:3.12-slim` (index) + `postgres:16-alpine` | 46 + 115 MB | ≤ 160 MB | |
| Optional: `r1b-replay`, `optimizer`, `tsb-sync-test` | 142 + 61 + 146 MB | ≤ 350 MB | analyzer layers may deduplicate |
| `logs_data` tar | 197 MB | about 10 MB | |
| Records after Phase 0, this preflight, host records | about 2 MB | about 2 MB | |
| Optional post-Phase-0 scratch | about 12 MB | about 12 MB | |
| **Total** | — | **about 0.25 GB (about 0.6 GB with the optional images)** | the repository grows to about 13.6–14.0 GB |

- **Local staging folder:** 0.2–0.6 GB. It can be deleted once the snapshot is verified; keeping it is also possible (520 GiB free).
- **Off-host first copy:** about 14 GB.
- **Off-host increments:** about 3 MB/day (database), plus 25–40 MB/day once evidence v2 is enabled.
- **Restore-drill scratch:** at most 20 GB of disk (§10), plus a 2 GiB tmpfs.

### 7.6 Off-host destination options (owner decision, CP-6)

Criteria:
- It is independent of this host and of GitHub.
- It can be made immutable or append-only, so that a compromised host cannot delete the backups.
- EU jurisdiction (the host is in Germany).
- Restic support.
- Cost at 14 GB and above.

Verify prices at the time of purchase.

| Option | How | Strengths | Weaknesses |
|---|---|---|---|
| **A. Storage box / SFTP host with provider-side snapshots** (for example an EU "storage box" product, or a second small VPS the owner controls) | restic `sftp:` repository (or `restic copy`); SSH key restricted to one sub-account; provider snapshots enabled from the provider panel | Cheap. EU. **Provider snapshots cannot be deleted over SFTP.** Simple restic workflow. | Needs an account and an SSH key; SFTP credentials on the host allow deleting the *live* copy, but not the provider snapshots |
| **B. S3-compatible object storage with Object Lock / versioning** (EU region) | restic `s3:` repository; an application key **without delete rights**, or bucket versioning plus a lifecycle rule | **Strongest ransomware resistance.** Cheap at this size. | Needs account setup and a key-policy design; restic `forget/prune` must run from a separate trusted machine |
| **C. Google Drive (existing `gdrive:` rclone remote)** | `rclone copy` of the repository folder, or restic `rclone:gdrive:tsb-restic` | **Zero setup; already works** for wishlist. It can protect the data tonight. | The OAuth token on the host can **delete** the backups, so it is not ransomware-resistant. Free-tier capacity (15 GB, shared with mail) may not fit 14 GB. API quotas. Phase 0 noted earlier token-save and client-ID warnings. |
| **D. Owner-controlled machine (pull)** | The owner's computer or NAS runs `rsync --checksum` of `tsb-restic` over SSH, or runs restic itself | The host holds **no credential** to the copy, which gives the best isolation | Manual cadence; depends on the owner's machine being on |
| E. GitHub | — | Already holds the code | **Not for data**: private data, size limits, sealed holdout |

**Recommendation:**
- **Primary:** A or B, for immutability and EU jurisdiction.
- **Plus:** one pull copy (D) after major milestones.
- **Stop-gap:** C may be used **only** if the owner wants protection before A or B exists. Its capacity must be confirmed first.

**For every option, the key is escrowed first (CP-7).**

### 7.7 Restoration requirements

| Requirement | Detail |
|---|---|
| **Architecture** | The images are **arm64 only**. A disaster-recovery host must be arm64; otherwise the images must be rebuilt, and **rebuilds are not reproducible** (mixed builds, single-file overlays, no lockfiles, unmatched files in claude_review). The image tar is the only exact restore path for the production code. |
| Host sizing (this bot only) | ≥ 4 vCPU, ≥ 8 GB RAM, ≥ 60 GB disk (+ 9 GB research data + images). Add the other projects if they move with it. |
| Software | Docker Engine 29.x with the containerd store (tested here); Compose v2 (5.5.1 here); restic ≥ 0.17 (0.19.1 here; binary sha256 `2fb45ac6f9071b6f…`); rclone if C is used; git ≥ 2.40; the `postgres:16-alpine` image (the same ID for physical fidelity; any 16.x works for logical restores). |
| **Keys (must be off-host)** | `~/.config/tsb-backup/restic-password` (`tsb-restic`); the xsch job's key in `~/.config/xsch-backup/env` (for the `trading_signals` dumps; **mode 640**, tighten to 600 as CP-10 hygiene); the off-host repository password and destination credentials |
| **Secrets (not in any backup by design)** | `/home/tradmin/trading-signal-bot/.env`, `.env.binance`, `.env.bak.*` (database password, Telegram bot token, the read-only Binance key and secret, and so on). The Claude CLI sign-in (`~/.claude`, `~/.claude.json`) for claude_review. The GitHub deploy key or `gh` token (can be re-issued). `shared-postgres/.env`, `admin.env`, `secrets/*` (cluster bootstrap and backup passwords; shared-postgres owner). `~/.config/rclone/rclone.conf` (if C). |
| Runbooks | Phase-0 `docs/RECOVERY.md`. **`docs/B3_RESTORE_RUNBOOK.md` is mandatory for any restore of `trading_signals`.** `OPERATOR_NOTE_resume_limitation.md`. §11 of this plan. |
| Invariants after any restore | A restored database may contain an old valid `manual_resume` row. **Write `manual_pause` before any service starts.** Never start `continuous_learner`. Never run a bare `docker compose up`. No `/resume` or `/recover_risk`. Trading stays HALTED. |

### 7.8 Time, downtime, and data-loss and recovery-time targets

All times are estimates, to be measured in the drill.

| Activity | Duration | Downtime |
|---|---|---|
| Local Phase-1 backup (§8, B0–B9) | about 15–25 min (restic scans about 270k files; the Git and database steps take seconds) | **none** |
| Off-host first copy, 14 GB | about 25 min at 10 MiB/s, about 50 min at 5 MiB/s | **none**; the bandwidth is capped to protect the public sites |
| Recovery drill (§10) | about 45–90 min | **none** (isolated) |
| Production restore of `trading_signals` (only if ever needed) | about 20–40 min under the B3 runbook | **this bot only** (6 services stopped; already HALTED). xsch and wishlist are unaffected. |
| Full-host disaster recovery on a new arm64 host | about 3–6 h, manual | — |

**Data-loss window (recovery point objective):**
- Database, locally: ≤ 24 h. Off-host today: **never protected**. After this plan: the time since the last off-host copy.
- Files: the time since the last snapshot. Today that is Phase 0; only telemetry has changed since.

---

## 8. Backup procedure: ordered commands for a future **owner-approved** execution (task 7)

> Nothing below has been run. Each block names the checkpoint that authorizes it. Run as `tradmin`, in one shell, **outside 03:00–05:00 CEST** and away from 00:30 and 12:30 CEST. Every stop condition (§13) aborts the run and keeps all artifacts for review.

### 8.0 Common setup (CP-0)
```bash
set -euo pipefail
umask 077
export GIT_OPTIONAL_LOCKS=0 LC_ALL=C GOMAXPROCS=2
TS=$(date -u +%Y%m%dT%H%M%SZ)
P=/home/tradmin/trading-signal-bot                       # production folder: read only
D=/home/tradmin/backups/tsb-phase1-$TS                   # new staging folder
PH0=/home/tradmin/backups/tsb-phase0-20260927
export RESTIC_REPOSITORY=/home/tradmin/backups/tsb-restic
export RESTIC_PASSWORD_FILE=/home/tradmin/.config/tsb-backup/restic-password
PGIMG=sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb      # postgres:16-alpine
ALPINE=sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b     # alpine:3
N="nice -n 19 ionice -c 3"
mkdir -m 700 -p "$D"/{git,db,images,volumes,host,logs}
exec > >(tee -a "$D/logs/run.log") 2>&1
stop() { echo "STOP $1: $2"; exit "${3:-90}"; }
halt_now() {
  docker exec -i -e PGOPTIONS='-c default_transaction_read_only=on' postgres \
    psql -X -q -At -F'|' -U trading_signal_bot -d trading_signals -c \
    "SELECT date, is_trading_paused, pause_reason, id FROM risk_management
     WHERE is_trading_paused OR pause_reason='manual_resume'
     ORDER BY date DESC NULLS FIRST, id DESC LIMIT 1"
}
HALT_EXPECTED='2026-09-11|t|risk:loss_streak_halt|29415'
```

### 8.1 B0: baseline and guards (read only; CP-0)
```bash
[ "$(halt_now)" = "$HALT_EXPECTED" ] || stop S1 "halt row changed"
[ "$(docker inspect -f '{{.State.Status}}' trading_continuous_learner)" = exited ] || stop S1 "learner not exited"
[ "$(docker inspect -f '{{.State.Health.Status}}' postgres)" = healthy ] || stop S7 "postgres not healthy"
for c in $(docker ps -aq); do docker inspect -f '{{.Name}}|{{.Image}}|{{.State.StartedAt}}|{{.State.Status}}' "$c"; done | sort > "$D/host/started_before.txt"
avail=$(df -B1 --output=avail /home | tail -1); [ "$avail" -gt $((50*1024**3)) ] || stop S3 "less than 50 GiB free"
read -r l1 _ < /proc/loadavg; awk -v l="$l1" 'BEGIN{exit !(l<8)}' || stop S4 "load $l1"
[ "$(awk '/MemAvailable/{print $2}' /proc/meminfo)" -gt $((4*1024*1024)) ] || stop S4 "MemAvailable < 4 GiB"
h=$(TZ=Europe/Berlin date +%H); { [ "$h" -ge 3 ] && [ "$h" -lt 5 ]; } && stop S5 "inside the 03:00-05:00 backup window"
pgrep -f 'backup-run\.sh|backup-verify\.sh|backup-restore-test\.sh|hermes/backup\.sh|restic (backup|check|prune|forget|copy)' >/dev/null && stop S5 "another backup job is running"
{ date -u; cat /proc/loadavg; free -m; df -h /home; docker ps -a --format '{{.Names}}|{{.Status}}|{{.Ports}}'; docker network ls; } > "$D/host/baseline.txt"
```

### 8.2 B1: Git (CP-1; no ref is created, moved or deleted)
```bash
git -C "$P" ls-remote origin > "$D/git/ls-remote-origin.txt"
git -C "$P" for-each-ref --format='%(objectname) %(refname)' > "$D/git/local-refs.txt"
git -C "$P" worktree list --porcelain > "$D/git/worktrees.txt"
drift=0
while read -r sha ref; do
  case "$ref" in refs/heads/*)
    b=${ref#refs/heads/}
    [ "$(git -C "$P" rev-parse -q --verify "refs/remotes/origin/$b" || true)" = "$sha" ] || { echo "DRIFT $b $sha"; drift=1; } ;;
  esac
done < "$D/git/ls-remote-origin.txt"
[ "$drift" -eq 0 ] || stop CP-1b "GitHub moved after the preflight; a plain 'git fetch origin' (NO --prune) needs separate approval" 21
B="$D/git/trading-signal-bot-all-refs-$TS.bundle"
git -C "$P" bundle create "$B" --all
git -C "$P" bundle verify "$B"
git -C "$P" bundle list-heads "$B" > "$D/git/bundle-heads.txt"
heads=$(awk '{print $1}' "$D/git/bundle-heads.txt" | sort -u)
{ awk '{print $1, "local:"$2}' "$D/git/local-refs.txt"
  grep -E 'refs/(heads/|pull/[0-9]+/head)' "$D/git/ls-remote-origin.txt" | awk '{print $1, "github:"$2}'; } |
while read -r s r; do
  ok=; for h in $heads; do git -C "$P" merge-base --is-ancestor "$s" "$h" 2>/dev/null && { ok=1; break; }; done
  [ -n "$ok" ] || echo "NOT COVERED $r $s"
done > "$D/git/not-covered.txt"
[ ! -s "$D/git/not-covered.txt" ] || stop S9 "bundle coverage gap (see not-covered.txt)"
( cd "$D/git" && sha256sum "$(basename "$B")" > SHA256SUMS )
```
Expected result:
- `not-covered.txt` is empty.
- The heads include `4e3eb0a`, `3ed49c3`, `23dea90`, `6d6790f`, `b9d352e` (`refs/remotes/origin/docs/…`), `8bfca77`, `3d1857d`, `63da7d3`, `0a396c2`, the 10 local-only names and the tag.

*Optional, separately approved (CP-1a = cleanup audit A2):* create and push the annotated tag `prod-baseline-2026-09-27` → `3ed49c3` **before** B1, using the exact commands in `REPOSITORY_CLEANUP_AUDIT.md` Part II §5.2. The bundle then carries it.

### 8.3 B2: this bot's database only (CP-2)

pg_dump works from a single read-only snapshot and takes ACCESS SHARE locks on this bot's tables only. It waits at most 30 s for a lock.

```bash
PGX() { docker exec -i -e PGOPTIONS='-c default_transaction_read_only=on' postgres "$@"; }
counts() { PGX psql -X -q -At -F'|' -U trading_signal_bot -d trading_signals <<'SQL'
SELECT format('SELECT %L AS t, count(*) FROM %I.%I', c.relname, n.nspname, c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r','p') AND n.nspname = 'public' ORDER BY 1 \gexec
SQL
}
counts > "$D/db/rowcounts-before.txt"
PGX pg_dump -U trading_signal_bot -d trading_signals --format=custom --lock-wait-timeout=30s --no-password > "$D/db/trading_signals-$TS.dump"
counts > "$D/db/rowcounts-after.txt"
PGX pg_dump -U trading_signal_bot -d trading_signals --schema-only --no-owner --no-privileges --no-password > "$D/db/trading_signals-schema-$TS.sql"
PGX pg_dumpall -U trading_signal_bot --globals-only --no-role-passwords --no-password > "$D/db/globals-no-role-passwords-$TS.sql"
[ -s "$D/db/trading_signals-$TS.dump" ] || stop S9 "empty dump"
# Check the dump table of contents in a throwaway, network-less client container, not in the shared server's memory limit
docker run --rm -i --network none --memory 256m --cpus 0.5 --pids-limit 64 "$PGIMG" pg_restore --list < "$D/db/trading_signals-$TS.dump" > "$D/db/toc.txt"
[ "$(grep -c 'TABLE DATA' "$D/db/toc.txt")" -ge 25 ] || stop S9 "dump TOC lacks table data"
diff -q "$D/db/rowcounts-before.txt" "$D/db/rowcounts-after.txt" || echo "NOTE: rows changed during the dump; list the tables in the run log (volatile tables only are acceptable)"
( cd "$D/db" && sha256sum ./* > SHA256SUMS )
```
- Roles are dumped with **`--no-role-passwords`**, so the backup of this bot never holds other projects' password hashes. Passwords come from escrow at recovery time.
- Dumping `xsch` and `wishlist` is **out of scope**. They belong to their own jobs and to the D1 plan (CP-11).

### 8.4 B3: images (CP-3; never `docker load`, `tag`, `pull` or `prune`)
```bash
while read -r tag id; do [ "$(docker image inspect -f '{{.Id}}' "$tag")" = "$id" ] || echo "CHANGED $tag"; done \
  < "$PH0/images/image_tags_ids.txt" > "$D/images/changed-since-phase0.txt"
[ ! -s "$D/images/changed-since-phase0.txt" ] || stop CP-3b "production image set changed; a new full export needs approval" 31
[ "$(sha256sum < "$PH0/images/trading-signal-bot-images-20260927.tar" | cut -d' ' -f1)" = "$(cat "$PH0/images/trading-signal-bot-images-20260927.tar.sha256")" ] || stop S9 "Phase-0 image tar hash mismatch"
save_pinned() {  # $1 ref, $2 expected full image ID, $3 output name. No --platform: this keeps the index digest.
  [ "$(docker image inspect -f '{{.Id}}' "$1")" = "$2" ] || stop S9 "$1 no longer has ID $2"
  docker save -o "$D/images/$3.tar" "$1"
}
save_pinned python:3.12-slim   sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9 base-python-3.12-slim-d764629ce0dd
save_pinned postgres:16-alpine "$PGIMG" engine-postgres-16-alpine-e013e867e712
# optional, CP-3a
# save_pinned r1b-replay:analyzer-ce305ecd-pyarrow sha256:923f43cacb83a31763365b17a0e17d9f1c250af8ce31163f5802a571b21af14c research-r1b-replay-923f43cacb83
# save_pinned trading-signal-bot-optimizer:latest sha256:374fcce71a6123e57206a8108e0a6e054aff79f8c14a42b87589b10735012f38 archive-optimizer-374fcce71a61
( cd "$D/images" && sha256sum ./*.tar > SHA256SUMS )
```

### 8.5 B4: logs volume (CP-4; a throwaway, read-only helper container with no network)
```bash
docker run --rm --name "tsb-bkp-logs-$TS" --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user 1000:1000 --memory 128m --cpus 0.5 --pids-limit 32 \
  -v trading-signal-bot_logs_data:/src:ro -v "$D/volumes":/dst \
  "$ALPINE" tar -C /src -cf "/dst/logs_data-$TS.tar" .
( cd "$D/volumes" && sha256sum ./*.tar > SHA256SUMS )
```
If `tar` reports permission errors, **stop** (CP-4b). Running the helper as root requires a separate approval.

### 8.6 B5: host records (CP-0; no environment variables and no secrets)
```bash
for c in $(docker ps -aq); do docker inspect --format '{{json .Name}} {{json .Image}} {{json .Config.Image}} {{json .Config.Labels}} {{json .HostConfig.RestartPolicy}} {{json .HostConfig.Memory}} {{json .Mounts}}' "$c"; done > "$D/host/container-records-no-env.jsonl"
docker image ls --no-trunc --format '{{.ID}} {{.Repository}}:{{.Tag}} {{.CreatedAt}}' | sort > "$D/host/images.txt"
docker volume ls --format '{{.Name}} {{.Driver}}' > "$D/host/volumes.txt"
for n in shared_db_net trading-signal-bot_trading_network; do docker network inspect --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}}{{end}} internal={{.Internal}}' "$n"; done > "$D/host/networks.txt"
cp "$P/docker-compose.yml" "$D/host/tsb-docker-compose.yml"; cp /home/tradmin/shared-postgres/docker-compose.yml "$D/host/shared-postgres-docker-compose.yml"
crontab -l | grep -E 'walk_forward_audit|canary_watchdog|cron-signal-bot-review' > "$D/host/crontab-tsb-lines.txt"   # these 3 lines hold no credentials
{ uname -a; grep PRETTY /etc/os-release; docker version --format '{{.Server.Version}}'; docker compose version --short; restic version; git --version; } > "$D/host/platform.txt"
cp /home/tradmin/tsb-baseline/deploy/baseline-2026-09-27/DEPLOYED_MANIFEST.json "$D/host/"   # the baseline image-ID record (8,001 B)
```

### 8.7 B6: restic snapshots into `tsb-restic` (CP-5)
```bash
$N restic check                                             # metadata integrity before writing (about 1 min)
$N restic backup --tag tsb-phase1 --tag repo-worktree --parent b965532a \
     --exclude-file "$PH0/manifests/excludes-repo.txt" "$P"
$N restic backup --tag tsb-phase1 --tag research-data --parent ac2d1b05 /home/tradmin/research-data/trading-signal-bot
$N restic backup --tag tsb-phase1 --tag phase1-artifacts "$D" \
     /home/tradmin/backups/tsb-sync-20260927 /home/tradmin/backups/tsb-p0-security-20260927 \
     /home/tradmin/backups/tsb-exec-comparison-20260927 /home/tradmin/backups/tsb-p1-instrumentation-20260927 \
     /home/tradmin/backups/tsb-post-p1-audit-20260927 /home/tradmin/backups/tsb-backup-preflight-20260928
# optional, CP-5b: post-Phase-0 scratch, without derived copies, the worktree, or the other project's clone
S=/tmp/claude-1000/-home-tradmin/f9e8015a-2572-40e2-8955-cabae27535bf/scratchpad
printf '%s\n' "$S/deployed" "$S/deployed_now" "$S/b3-worktree" "$S/trading-bot" '__pycache__' > "$D/logs/excludes-scratch.txt"
# $N restic backup --tag tsb-phase1 --tag session-scratch --exclude-file "$D/logs/excludes-scratch.txt" "$S"
$N restic check --read-data-subset=10%
restic snapshots --tag tsb-phase1 > "$D/logs/snapshots.txt"
```
- The excludes (`excludes-repo.txt`) keep out `.env`, `.env.*`, `colab/token.json`, the `.venv`, `__pycache__` and `.pytest_cache`.
- Only **this bot's** repository is written. The xsch, shared-postgres and hermes repositories are never touched, so there is no lock contention with their jobs.

### 8.8 B7: pre-upload credential scan (CP-6 gate)
```bash
grep -rIlE 'BEGIN [A-Z ]*PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{30,}|[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|SCRAM-SHA-256\$[0-9]+:|postgres(ql)?://[^:/@ ]+:[^@/ $]{6,}@' "$D" \
  /home/tradmin/backups/tsb-{sync,p0-security,exec-comparison,p1-instrumentation,post-p1-audit}-2026092* > "$D/logs/credential-scan.txt" || true
[ ! -s "$D/logs/credential-scan.txt" ] || stop S8 "credential pattern found; do not upload"
```

### 8.9 B8: off-host copy (CP-6 and **CP-7 key escrow first**; the variant depends on the chosen option)
```bash
# Option A/B/D-style: a separately keyed remote repository with the same chunker parameters, so 'copy' deduplicates.
# The owner creates the destination credentials; they live in a 600 file and are never echoed.
R2='sftp:<user>@<storage-host>:/tsb-restic'           # or  s3:https://<endpoint>/<bucket>/tsb-restic
RP2=/home/tradmin/.config/tsb-backup/restic-password-offhost   # created by the owner, escrowed BEFORE first use
restic -r "$R2" --password-file "$RP2" init --from-repo "$RESTIC_REPOSITORY" --from-password-file "$RESTIC_PASSWORD_FILE" --copy-chunker-params   # first time only
$N restic -r "$R2" --password-file "$RP2" --limit-upload 10240 copy --from-repo "$RESTIC_REPOSITORY" --from-password-file "$RESTIC_PASSWORD_FILE"
restic -r "$R2" --password-file "$RP2" check --read-data-subset=5%
restic -r "$R2" --password-file "$RP2" snapshots > "$D/logs/offhost-snapshots.txt"

# Option C stop-gap: file-level copy of the encrypted repository (same key). NEVER 'rclone sync', which propagates deletions.
# $N rclone copy /home/tradmin/backups/tsb-restic gdrive:tsb-restic --checksum --bwlimit 10M --transfers 2
# restic -r rclone:gdrive:tsb-restic check --read-data-subset=5%
```

### 8.10 B9: post-checks and closure (CP-0)
```bash
[ "$(halt_now)" = "$HALT_EXPECTED" ] || stop S1 "halt row changed during the run"
for c in $(docker ps -aq); do docker inspect -f '{{.Name}}|{{.Image}}|{{.State.StartedAt}}|{{.State.Status}}' "$c"; done | sort > "$D/host/started_after.txt"
grep -v -E '^/tsb-bkp-' "$D/host/started_after.txt" | diff "$D/host/started_before.txt" - || stop S2 "a container changed state or restarted"
[ -z "$(docker ps -aq --filter name=tsb-bkp-)" ] || stop S10 "helper container left behind"
df -h /home > "$D/logs/df-after.txt"
( cd "$D" && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256 )
chmod -R go-rwx "$D"
```

### 8.11 Key escrow (owner action; CP-7)

This is a precondition for relying on any off-host copy. The owner, in their own session, **never through Claude**, stores the following in a password manager, plus one offline copy:
1. The content of `~/.config/tsb-backup/restic-password`.
2. The off-host repository password (`restic-password-offhost`).
3. The destination credentials.
4. The secrets listed in §7.7.

Escrow the xsch backup key under xsch D-10.

**Proof of escrow:** drill R5 opens the off-host repository **from a different machine** using only the escrowed copies.

---

## 9. Verification procedure

| Check | Command or evidence | Pass criterion |
|---|---|---|
| V1 Bundle integrity | `git bundle verify` | "okay", complete history |
| V2 Bundle coverage | `not-covered.txt` | empty (all local refs and GitHub branch and PR heads) |
| V3 Bundle usability | R1 mirror clone plus `fsck --full --strict` | exit 0; ref set equals `bundle-heads.txt` |
| V4 Dump validity | `pg_restore --list` in a network-less client | ≥ 25 `TABLE DATA` entries; about 188 TOC entries as in Phase 0 |
| V5 Dump consistency | `rowcounts-before` = `rowcounts-after` | equal, or only volatile tables differ (logged) |
| V6 Image archives | sha256 of each tar; blob self-hash; `index.json` digests (R4) | Phase-0 tar = `2b8b3f41…`; base index = `d764629c…`; engine index = `e013e867…` |
| V7 Repository integrity | `restic check` + `--read-data-subset=10%` (local), `5%` (remote) | "no errors were found" |
| V8 Snapshot content | `restic snapshots --tag tsb-phase1`; `restic diff b965532a <new>` | new snapshots present; worktree diff = telemetry plus the new `.git` objects |
| V9 Production untouched | B9: halt row, container state and start times, helper cleanup | identical to B0 |
| V10 Manifests | `MANIFEST.sha256` in `$D`; per-folder `SHA256SUMS` | `sha256sum -c` passes |
| V11 Off-host independence | R5 on another machine | restore of a sample path matches the manifest |

---

## 10. Recovery drill with isolated resources (CP-8)

These rules follow `SINGLE_HOST_SAFETY` §3–§5:
- Record a baseline first.
- Use unique names (`tsb-drill-*`) and a label (`purpose=tsb-backup-drill`).
- Use **`--network none`** and publish no ports.
- Keep data in tmpfs or scratch storage only.
- Set explicit CPU, memory and process limits.
- Leave production containers, networks, volumes and the shared cluster untouched.

The drill does restore **production data, including holdout rows**, into a throwaway database. That is why CP-8 approves H1–H6 explicitly: verification by counts and hashes only, and destruction afterwards.

```bash
set -euo pipefail; umask 077
TS=$(date -u +%Y%m%dT%H%M%SZ); T=/home/tradmin/restore-drill-$TS; mkdir -m 700 -p "$T"
D="/home/tradmin/backups/tsb-phase1-<TS-of-backup>"      # the verified staging folder (replace the placeholder)
PGIMG=sha256:e013e867e712fec275706a6c51c966f0bb0c93cfa8f51000f85a15f9865a28cb
export RESTIC_REPOSITORY=/home/tradmin/backups/tsb-restic RESTIC_PASSWORD_FILE=/home/tradmin/.config/tsb-backup/restic-password
[ -z "$(docker ps -aq --filter label=purpose=tsb-backup-drill)" ] || { echo "STOP: leftover drill container"; exit 1; }
{ date -u; cat /proc/loadavg; free -m; df -h /home; docker ps -a --format '{{.Names}}|{{.Status}}|{{.Ports}}'; docker network ls; } > "$T/baseline.txt"
docker volume ls -qf dangling=true | sort > "$T/dangling-before.txt"
```

**R1: Git** (about 1 min)
```bash
B=$(ls "$D"/git/*.bundle)
git clone -q --mirror "$B" "$T/git-drill.git"
git -C "$T/git-drill.git" fsck --full --strict
git -C "$T/git-drill.git" for-each-ref --format='%(objectname) %(refname)' | sort > "$T/git-refs.txt"
for c in 4e3eb0a 3ed49c3 8bfca77 23dea90 6d6790f 3d1857d 63da7d3 0a396c2 b9d352e; do
  git -C "$T/git-drill.git" cat-file -e "$c^{commit}" || { echo "STOP S9: commit $c missing from the bundle clone"; exit 1; }
done; echo "R1 key commits present"
```

**R2: Files** (about 5–10 min for the selected paths)
```bash
NEW=$(restic snapshots --tag tsb-phase1,repo-worktree --json | python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["short_id"])')
restic restore "$NEW" --target "$T/files" \
  --include /home/tradmin/trading-signal-bot/research/governance \
  --include /home/tradmin/trading-signal-bot/docs \
  --include /home/tradmin/trading-signal-bot/data/evidence
# Hash-only comparison with the Phase-0 manifest ("sha256  bytes  path"); the live telemetry file is expected to differ
grep -E ' /home/tradmin/trading-signal-bot/(research/governance|docs|data/evidence)/' \
  /home/tradmin/backups/tsb-phase0-20260927/manifests/SHA256-repo-worktree.txt | grep -v '_telemetry.json$' |
  awk '{print $1"  '"$T"'/files"$3}' | sha256sum -c --quiet || { echo "STOP S9: restored files differ"; exit 1; }
echo "R2 files identical"
```

**R3: Database in a throwaway, network-less PostgreSQL 16** (about 5 min)
```bash
C=tsb-drill-pg-$TS
docker run -d --rm --name "$C" --label purpose=tsb-backup-drill --network none \
  --memory 1g --memory-swap 1g --cpus 1 --pids-limit 256 \
  --tmpfs /var/lib/postgresql/data:rw,size=2g -e POSTGRES_HOST_AUTH_METHOD=trust "$PGIMG"
for i in $(seq 90); do docker exec "$C" pg_isready -q -h 127.0.0.1 -U postgres && break; sleep 1; done   # TCP: ready only after init
docker exec "$C" createdb -h 127.0.0.1 -U postgres tsb_drill
docker exec -i "$C" pg_restore -h 127.0.0.1 -U postgres -d tsb_drill --no-owner --no-privileges --exit-on-error < "$(ls "$D"/db/trading_signals-*.dump)"
docker exec -i "$C" psql -X -q -At -F'|' -h 127.0.0.1 -U postgres -d tsb_drill > "$T/drill-rowcounts.txt" <<'SQL'
SELECT format('SELECT %L AS t, count(*) FROM %I.%I', c.relname, n.nspname, c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r','p') AND n.nspname = 'public' ORDER BY 1 \gexec
SQL
diff "$D/db/rowcounts-after.txt" "$T/drill-rowcounts.txt" || { echo "STOP S9: row counts differ"; exit 1; }
echo "R3 row counts equal"
docker exec "$C" pg_dump -h 127.0.0.1 -U postgres -d tsb_drill --schema-only --no-owner --no-privileges > "$T/drill-schema.sql"
diff <(grep -v -E '^(--|$|\\(un)?restrict )' "$(ls "$D"/db/trading_signals-schema-*.sql)") <(grep -v -E '^(--|$|\\(un)?restrict )' "$T/drill-schema.sql") \
  || { echo "STOP S9: schema differs"; exit 1; }
echo "R3 schema equal"
# B3 invariant on the COPY (flags only). It must equal the live halt row.
docker exec "$C" psql -X -At -F'|' -h 127.0.0.1 -U postgres -d tsb_drill -c "SELECT date, is_trading_paused, pause_reason, id FROM risk_management WHERE is_trading_paused OR pause_reason='manual_resume' ORDER BY date DESC NULLS FIRST, id DESC LIMIT 1"
# Structural index check on the COPY only (data checksums are off in production)
docker exec -i "$C" psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d tsb_drill -o /dev/null <<'SQL'
CREATE EXTENSION IF NOT EXISTS amcheck;
SELECT bt_index_check(i.indexrelid) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
JOIN pg_am a ON a.oid = c.relam JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE a.amname = 'btree' AND n.nspname = 'public';
SQL
docker rm -f -v "$C"
```
- **Never** connect the drill container to `shared_db_net`.
- **Never** point any application image at it.
- **Never** restore into the production cluster. The xsch monthly test does restore into the production cluster; this plan deliberately does not.

**R4: Image archives, checked structurally** (about 3–5 min; **no `docker load` on this host**)

`docker load` would re-point tags such as `trading-signal-bot-scanner:latest`. It is allowed only on an isolated Docker host (Phase-0 RECOVERY §5).

```bash
for tar in /home/tradmin/backups/tsb-phase0-20260927/images/trading-signal-bot-images-20260927.tar "$D"/images/*.tar; do
  x="$T/img/$(basename "$tar" .tar)"; mkdir -p "$x"; tar -xf "$tar" -C "$x"
  ( cd "$x/blobs/sha256" && for f in *; do printf '%s  %s\n' "$f" "$f"; done | sha256sum -c --quiet ) \
    || { echo "STOP S9: corrupt blob in $(basename "$tar")"; exit 1; }
  echo "R4 blobs OK $(basename "$tar")"
  python3 -c 'import json,sys; print(sys.argv[2], [m["digest"][:19] for m in json.load(open(sys.argv[1]))["manifests"]])' "$x/index.json" "$(basename "$tar")"
done
```
Expected results:
- The 15 Phase-0 tags map to the IDs in `image_tags_ids.txt`, as verified in Phase 0.
- The base archive's index is `d764629c…`.
- The engine archive's index is `e013e867…`.

**R5: Off-host restore on a different machine** (the owner's computer; the only true single-host-loss proof)

Install restic there, then:
```bash
restic -r '<R2>' --password-file ./escrowed-offhost-password snapshots
restic -r '<R2>' --password-file ./escrowed-offhost-password restore latest --tag research-data --target ./drill \
  --include /home/tradmin/research-data/trading-signal-bot/certification
restic -r '<R2>' --password-file ./escrowed-offhost-password check --read-data-subset=2%
```
If R5 is impossible (no second machine), CP-8 records it as an **accepted residual risk**.

**R6: Teardown and evidence**
```bash
[ -z "$(docker ps -aq --filter label=purpose=tsb-backup-drill)" ] || docker rm -f -v $(docker ps -aq --filter label=purpose=tsb-backup-drill)
docker volume ls -qf dangling=true | sort | diff "$T/dangling-before.txt" - && echo "no new anonymous volumes"
cp "$T"/{baseline.txt,git-refs.txt,drill-rowcounts.txt} "$D/logs/" 2>/dev/null || true
case "$T" in /home/tradmin/restore-drill-20*) rm -rf -- "$T" ;; *) echo "refusing to delete $T" ;; esac
```
Record the elapsed time of R1–R5 as the measured recovery times.

---

## 11. Disaster-recovery outline (reference only; not a drill)

1. **Provision.**
   - Provision an **arm64** host (§7.7).
   - Install Docker 29.x with Compose v2, restic 0.19.x and git.
   - Harden SSH before exposure (xsch D-8).
2. **Restore keys and secrets** from escrow. Never paste them into chat or tickets.
3. **Restore the repositories.**
   - Restore `tsb-restic` from off-host into `/home/tradmin/backups/tsb-restic`.
   - Restore `b965532a`/`<phase1>` worktree, `ac2d1b05` research data, and the Phase-0/Phase-1 artifacts.
   - Verify them against the manifests.
4. **Recreate the infrastructure.**
   - Create the networks: `shared_db_net`, and let Compose create its own network.
   - Create the volumes: `trading-signal-bot_postgres_data`, `…_logs_data`, `…_models_data`.
   - Start `postgres` from `/home/tradmin/shared-postgres` (image `e013e867…`).
   - Restore the roles. **Set passwords from escrow**, because the dumps of this bot carry none.
   - Restore each project's database from its own backup, under that project's runbook: xsch plan 019, the shared-postgres/wishlist job.
5. **Load the images.** Loading the Phase-0 image tar on the **fresh** daemon is safe there, because no other tags exist yet. Verify the IDs against `image_tags_ids.txt`.
6. **Restore `trading_signals` under `B3_RESTORE_RUNBOOK.md`.** Services stay stopped. Write `manual_pause`, verify the three gates, then start the services **one at a time** with `docker compose up -d --no-deps --no-build <svc>` (scanner last).
   - **Never start `continuous_learner`.**
   - No `/resume` or `/recover_risk`.
   - Trading stays HALTED until the owner separately authorizes otherwise.
7. **Re-establish the rest.**
   - Re-establish the cron lines from `crontab-tsb-lines.txt`.
   - Rebuild the `.venv` of `research/skill_application` only if the owner wants the watchdog back.
   - Sign the Claude CLI back in for claude_review.

---

## 12. Steps that could affect other projects on the shared host (task 8)

| Step | Shared resource touched | Possible effect on xsch, wishlist, hermes, jadrawy | Mitigation (built into §8/§10) |
|---|---|---|---|
| B0, B5, B9 checks | Docker API, catalog queries | none (read-only, milliseconds) | — |
| B1 Git bundle | `.git` of the bot; GitHub read | none | no fetch or gc; `GIT_OPTIONAL_LOCKS=0` |
| **B2 `pg_dump`/`pg_dumpall` through `docker exec postgres`** | the **shared server process and its 512 MiB memory limit**; ACCESS SHARE locks on this bot's tables | small memory and CPU use inside the shared container; locks block only DDL on this bot's tables; no effect on other databases | This bot's database only (51 MB). `--lock-wait-timeout=30s`. Off-peak. The table-of-contents check runs in a **separate** network-less container. Never `pg_dumpall` data. |
| B3 `docker save` | image store and daemon I/O | negligible | **No `load`, `tag`, `pull` or `prune`.** Save by verified ID. |
| B4 helper container | the daemon; the logs volume mounted **read-only** | none | `--network none`, read-only, memory, CPU and process limits, `--rm`, unique name |
| **B6 restic** | CPU and disk I/O on the **single shared disk** | a short I/O burst could slow the public sites | `nice -n 19 ionice -c 3`, `GOMAXPROCS=2`; only `tsb-restic` is written, so no lock contention with the xsch, shared-postgres or hermes repositories; outside 03:00–05:00 |
| **B8 upload** | the host's network link | could raise latency for xsch.gjafa.com, gjafa.com and jadrawy | `--limit-upload 10240` (about 10 MiB/s) or `--bwlimit 10M`; off-peak; stop if the xsch watchdog reports errors |
| **Staging and drill disk use** | **the one filesystem shared by Docker and all projects** | a full disk would stop PostgreSQL and every site | stop if less than 50 GiB is free; staging ≤ 1 GB; drill scratch ≤ 20 GB; delete after the drill |
| **R3 throwaway PostgreSQL** | RAM (no swap), CPU | an unbounded container could trigger the out-of-memory killer and hit the shared `postgres` | `--memory 1g --memory-swap 1g --cpus 1 --pids-limit 256`, a 2 GiB tmpfs, `--network none`, no ports |
| Using the xsch and shared-postgres repositories | their restic locks and retention | lock conflicts or data loss for other projects | **never used by this plan**; no `forget` or `prune` except in `tsb-restic` (and not in this plan) |
| Option C (Google Drive) | the shared `gdrive:` OAuth token | a token refresh or quota problem could break the **wishlist off-host backup** | prefer A or B; if C, check quota first and use a separate folder `gdrive:tsb-restic`; never `rclone sync` |
| **Forbidden** (not in the plan) | — | a bare `docker compose up -d` starts the learner and recreates drifted services; `docker system/volume/image prune` deletes rollback anchors and unreviewed volumes; `down -v`; a restore into the production cluster; any PostgreSQL restart (D1 is a separate plan) | each is a stop condition (S10) |

---

## 13. Risks, rollback and stop conditions

### 13.1 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The host or disk is lost before an off-host copy and key escrow exist | low per day, cumulative | **All non-Git assets of this bot are lost**; database history, research data and evidence are not recoverable | Stage C plus CP-7 are the priority |
| An off-host copy exists but the key is not escrowed | medium (a common failure) | The copy cannot be read | CP-7 comes before CP-6; R5 proves it from another machine |
| A compromised host deletes or overwrites GitHub branches (read-write deploy key, no protection) | low | Code history loss, if no bundle exists elsewhere | The bundle in the off-host repository; owner decisions on the key and protection (cleanup audit A-items) |
| A restored database reopens trading (an old `manual_resume`) | medium on restore | Unintended paper trading | The B3 runbook is mandatory: `manual_pause` first; never start the learner |
| `docker load` of an old tar on production re-points `:latest` | low | The next Compose start would run old code | Never load on this host (R4 checks structure only) |
| The throwaway database, or restic, exhausts RAM or disk | low | Shared PostgreSQL or site outage | Hard limits; S3 and S4 stop conditions |
| Holdout leakage through verification | low | Contaminates future validation | H1–H6; counts and hashes only |
| Backups hold other projects' role hashes | exists today (xsch and shared jobs) | A secret spread across more places | This plan uses `--no-role-passwords` |
| `/tmp` wipe at reboot | certain at the next boot | Loss of the scratch files after Phase 0 | CP-5b snapshot; the worktree is clean |

### 13.2 Rollback (every backup step is additive)

| Step | How to undo |
|---|---|
| B1–B5 | Delete the staging folder `$D` (guarded path check). Production and Git refs are never modified. |
| B6 | `restic forget <new-snapshot-ids>` on `tsb-restic` only (owner approval). Add `prune` only if space matters. Phase-0 snapshots are never forgotten. |
| B8 | Delete the remote repository or folder at the destination (owner). The local repository is unaffected. |
| R-steps | `docker rm -f -v` the labelled drill containers, then remove the guarded drill directory. |
| Optional CP-1a tag | Before it is pushed: `git tag -d prod-baseline-2026-09-27`. After it is pushed: see cleanup audit §5.3. Rarely needed. |
| Optional CP-1b fetch | Only adds or updates `refs/remotes/*`; no rollback is needed. Never `--prune`. |

### 13.3 Stop conditions: abort, keep all artifacts, report

| # | Condition |
|---|---|
| S1 | The B3 effective row is not `2026-09-11 · t · risk:loss_streak_halt · 29415`, or the learner is not `exited`. |
| S2 | Any container of any project changes state or start time during the run (B0 vs B9). |
| S3 | Less than 50 GiB is free, or a step would use more than 10% of the free space. |
| S4 | The 1-minute load is 8 or more, or MemAvailable is below 4 GiB. |
| S5 | Inside 03:00–05:00 CEST, or any other backup job or restic process is running. |
| S6 | `pg_dump` waits longer than 30 s for a lock, or any lock wait involves the xsch or wishlist databases. |
| S7 | `postgres` is not healthy, or more than 80 connections are open. |
| S8 | The credential scan finds anything in the staging folder or the records. |
| S9 | Any verification fails: bundle verify or coverage, the table of contents, hashes, restic check, or R1–R4. |
| S10 | A step would need an unapproved action: stop, restart, `up`, `down`, `load`, `tag`, `pull`, `prune`, `fetch --prune`, `gc`, `worktree prune`, a restore into the production cluster, or any change to trading state. |
| S11 | The upload degrades the sites (xsch watchdog errors, or latency complaints). Lower the bandwidth limit or stop. |

---

## 14. Approval checkpoints (explicit; each is independent)

| CP | Owner approves… | Scope and limits | Default if not approved |
|---|---|---|---|
| **CP-0** | This plan and an execution window | Date and time outside 03:00–05:00 CEST and away from 00:30 and 12:30. Staging `/home/tradmin/backups/tsb-phase1-<ts>`. B0, B5 and B9 checks. | Nothing runs |
| **CP-1** | Git backup: ls-remote, a new `--all` bundle, verify, coverage | No ref changes; no fetch | M1 stays open |
| CP-1a (optional) | Create and push the rollback tag `prod-baseline-2026-09-27` → `3ed49c3` first (cleanup audit A2) | One annotated tag; never `--tags` or `--force` | No tag |
| CP-1b (conditional) | A plain `git fetch origin` (**no `--prune`**), only if B1 detects GitHub drift | Adds or updates `refs/remotes/*` only | Stop at B1 |
| **CP-2** | A dump of **this bot's database only**: custom format, schema, roles **without passwords**, row counts before and after, a table-of-contents check in a throwaway client. Accept H1–H6 (holdout rows are read mechanically by `pg_dump`). | `--lock-wait-timeout=30s`; `xsch` and `wishlist` excluded | Only the nightly xsch dumps |
| **CP-3** | Export `python:3.12-slim@d764629c…` and `postgres:16-alpine@e013e867…`; re-hash the Phase-0 tar | No `load`, `tag`, `pull` or `prune` | M5 stays open |
| CP-3a (optional) | Also export `r1b-replay`, `optimizer`, `tsb-sync-test` (about 350 MB) | — | Not exported |
| CP-3b (conditional) | A new full production-image export, if any ID changed since Phase 0 | — | Stop at B3 |
| **CP-4** | The throwaway read-only helper container (`alpine`, `--network none`, uid 1000) to archive `logs_data` | CP-4b is needed if root is required | Phase-0 logs only |
| **CP-5** | restic snapshots in `tsb-restic` (worktree with the Phase-0 excludes, research data, records after Phase 0, staging), plus `check --read-data-subset=10%` | No `forget` or `prune`; no other repository touched | Local Phase-0 only |
| CP-5b (optional) | A snapshot of the post-Phase-0 scratch (about 12 MB; excludes `deployed*`, `b3-worktree`, `trading-bot/`) | — | Lost at the next reboot |
| **CP-6** | The off-host destination (A/B/C/D), its credentials (created by the owner), the bandwidth cap, the first-upload window, and that **encrypted, holdout-bearing data leaves the host** | `copy` only, never `sync`; `--limit-upload` | Single-host risk accepted |
| **CP-7** | **Key escrow confirmed by the owner** (`tsb-restic` password, the off-host password, destination credentials, the §7.7 secrets). **Precondition for CP-6.** | The owner acts; Claude never reads or prints keys | CP-6 blocked |
| **CP-8** | The isolated recovery drill R1–R6: production rows (including holdout) restored into a network-less throwaway PostgreSQL (1 CPU, 1 GiB, 2 GiB tmpfs); scratch ≤ 20 GB; destroyed afterwards; H1–H6. R5 on the owner's machine. | Checks by counts and hashes only | The recovery path stays unproven |
| CP-9 (later) | Recurring schedule and retention: for example a daily dump of this bot into `tsb-restic` (outside 03:00–05:00), a weekly off-host `copy`, a monthly isolated restore drill for `trading_signals`, and evidence v2 inclusion at P1 deployment | A crontab change is a host change and needs a separate review | Manual only |
| CP-10 (hygiene, separate) | Inspect or remove the 16 anonymous volumes (possible production-data copies); review the build cache; `chmod 600 ~/.config/xsch-backup/env`; move needed items off `/tmp`; the `wishlist_test` database inside the production cluster (wishlist owner) | Each is its own change | No change |
| CP-11 (D1, separate plan) | A cluster-wide pre-upgrade backup (all project databases plus a physical `pg_basebackup`) coordinated with the xsch and wishlist owners before PostgreSQL 16.15 | It copies other projects' personal data and restarts the shared database | Not in scope |

---

## 15. Open questions for the owner

1. Which off-host option (§7.6), in which region, and at what monthly budget? Is a second copy on the owner's machine (D) acceptable?
2. Were the `tsb-restic` password and the xsch backup key **already escrowed** outside this host? If not, CP-7 comes first.
3. Should the optional research images (CP-3a) and the scratch files (CP-5b) be kept?
4. May verification use **per-table row counts** on tables that hold holdout rows, or only hashes and table-of-contents checks (H3)?
5. Should the `.env` secrets be kept only in the password manager (recommended), or also in a separately keyed encrypted archive inside the off-host repository?
6. Retention: keep the Phase-0 and Phase-1 snapshots forever? What cadence after that (CP-9)?
7. Should the cluster-wide D1 backup (CP-11) be scheduled together with this plan or after it?
8. Should the host's GitHub deploy key become **read-only**, and should branch protection be enabled? Both would make GitHub a trustworthy second copy of the code.

---

## Appendix A. Evidence files (`/home/tradmin/backups/tsb-backup-preflight-20260928/work/`)

| File | Content |
|---|---|
| `git_local_refs.txt`, `git_worktrees.txt`, `git_stash.txt` (empty), `git_count_objects.txt`, `git_config_remotes.txt` | Local Git state |
| `ls_remote_origin.txt`, `ls_remote_snapshot.txt`, `gh_repo.json`, `gh_branches.txt`, `gh_pulls.txt` | GitHub state (GET and ls-remote only) |
| `bundles_found.txt`, `heads_*.bundle.txt`, `coverage_per_ref.txt`, `missing_commits.txt`, `missing_commits_detail.txt` | Bundle inventory and gaps |
| `docker_ps_all.txt`, `docker_containers_detail.txt`, `docker_mounts.txt`, `docker_images_all.txt`, `docker_volumes.txt`, `docker_system_df_v.txt`, `docker_shared_db_net.txt`, `host_baseline.txt` | Docker inventory (no environment variables) |
| `pg_cluster_inventory.txt`, `pg_tsb_inventory.txt` | Cluster catalog metadata and the B3 row |
| `crontab_redacted.txt`, `restic_tsb_snapshots.txt`, `restic_xsch_snapshots.txt`, `backups_du_mb.txt`, `df.txt` | Schedules and backups |
| `worktree_status.txt`, `prod_status_uall_now.txt`, `prod_changed_since_phase0.txt`, `scratchpad_inventory.txt`, `secret_files_inventory.txt` (names and modes only) | Working trees, drift, scratch, secrets |

## Appendix B. The 32 commits missing from every existing bundle (all present on GitHub)

| Tip | Commits (newest first) |
|---|---|
| PR #3 `docs/market-intelligence-governance-20260927` (22) | `b9d352e` docs(audits): add post-P1 dependency and repository-cleanup audits with handoff · `2ffb44b` `954819c` docs: instruct Claude to audit repository before single-branch consolidation · `bd9766a` docs: register single canonical branch and safe cleanup decision · `e210fc2` docs: audit 13 branches and plan single-main repository consolidation with deletion gates · `9e299ee` `7f7cd5e` `cba52f5` `099ad49` docs: enforce shared-host dev/prod safety in governance · `3b72e95` docs: record single-host dev/prod constraint and read-only audit rules · `39cde51` docs: log reported P1 completion and pending independent gates · `60e6bf8` docs: capture actual post-P1 dependency inventory… · `da37f48` `f34021e` `184b10a` docs: register latest stable dependency policy and post-P1 review gate · `7e5800b` docs: add stable supported dependency review policy for post-P1 work · `a653c42` docs: point Claude to authoritative charter and current halted state · `fb815bf` docs: make approved charter and halt governance authoritative for Claude · `522be4e` `9d4bc2b` `bab699d` `3c5a633` docs: record approved market intelligence vision and gated risk-throttle roadmap |
| `feature/forward-instrumentation` (1) | `23dea90` feat(p1): forward-trading instrumentation — evidence recorder v2 (default off) |
| `refactor/strategy-math` (1) | `6d6790f` refactor(analyzer): route indicators and levels through shared.strategy_math |
| `develop` (8, including the baseline) | `4e3eb0a` research(skill_application): preserve research scripts · `970dda9` docs(research): add Phase 1.6 data, governance and handoff documentation · `b1c804d` research(governance): preserve frozen research governance records · `2cd9e68` feat(research): add replay and P0R runtime-contract runner · `224bfa6` feat(research): add historical data governance tooling · `d221514` feat(research): add research foundation and shared strategy math · `39d701d` chore(repo): keep immutable research datasets and runs out of git · `3ed49c3` chore(deploy): record deployed production baseline 2026-09-27 (= `deploy/baseline-2026-09-27`) |

*End of plan. Status: awaiting owner review. No backup has been created.*
