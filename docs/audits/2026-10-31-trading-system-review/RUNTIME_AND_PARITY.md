# Runtime Inventory, Deployed Versions and GitHub-to-Runtime Parity

Part of the Trading Signal Bot audit package of 2026-10-31 ([README.md](README.md)). Companion documents: [FULL_SYSTEM_AUDIT_AR.md](FULL_SYSTEM_AUDIT_AR.md) (the complete Arabic audit), [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md), [MARKET_CONTEXT_AND_ASSET_SELECTION.md](MARKET_CONTEXT_AND_ASSET_SELECTION.md), [RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md](RESEARCH_HISTORY_AND_ECONOMIC_EVIDENCE.md) and [REVIEWER_EVIDENCE_PACK.md](REVIEWER_EVIDENCE_PACK.md).

## 0. Document control

| Field | Value |
|---|---|
| Package | `docs/audits/2026-10-31-trading-system-review/` |
| Document | `RUNTIME_AND_PARITY.md`: runtime inventory, image provenance, Compose configuration and precedence, GitHub-to-runtime parity, implemented architecture and actual activation status |
| Audit and runtime inspection date | 2026-10-31; runtime samples at 13:59Z and 14:05Z |
| Repository | `baljadrawy/trading-signal-bot` (private GitHub repository) |
| main at audit time and at publication time | `eba90ddf4ae60641f80627472098e34650915d28` (eba90dd) |
| Code read for analyzer and signal_engine | `ea8ae4f00e80c5c171536293d2df7472fa338c3e` (ea8ae4f), the commit documented as deployed |
| Code read for telegram and trade_tracker | `bb7825f4744278095ef76a1d0f3b872e3043358f` (bb7825f), the commit documented as deployed |
| Code read for the forward collector | `72c0bee82b44bede5192373d18374724f11c6c3a` (72c0bee) |
| Scanner | Assembled image. Blob list in `deploy/baseline-2026-09-27/deployed_files.json` at `8bfca778b42fa5c29993d5c57bf1674ae755522f` (8bfca77); `shared/config.py` blob c5c03b5c from `7bf6214dee3f62b345c3152eb65d234094921bb5` (7bf6214) |
| Repository documents read at | `ebf8d8ad2c71b1203565c10b98f22f32e0a81c05` (ebf8d8a, `feature/design-a-v1`, which is main plus 13 Design A files) |
| Production checkout | Branch `integration/research-pipeline` at `63da7d31daef2b952c695b256f81cf174b6451a8` (63da7d3), plus uncommitted edits |
| Status | READ-ONLY, AS-IS audit; documentation-only publication; not a profitability certification. Neither the audit nor this publication changed any application code, configuration, database, container or Paper Trading state. |

**Reading rule.** GitHub source is never treated here as proof of deployed behaviour. Container and image metadata are RUNTIME_VERIFIED, and only for the moment of inspection. Which code runs inside each image is DOCUMENTED_ONLY (RT-16) and was NOT VERIFIED at runtime (RT-17). Behaviour described from code is SOURCE_VERIFIED at the named commit and nothing more.

### Evidence classes

| Class | Meaning in this document |
|---|---|
| RUNTIME_VERIFIED | Observed directly on the production host during the 2026-10-31 read-only inspection. Covers container and image metadata, the Compose service list and config hashes, and the git state of the host Compose file and of the production checkout. A point-in-time observation that says nothing about code behaviour inside images. |
| SOURCE_VERIFIED | Confirmed by reading source code or tracked files at a named commit (git objects). Not proof of deployed behaviour. |
| DOCUMENTED_ONLY | Stated in repository documents, deploy records or the 2026-09-27 non-secret config snapshot. Not independently verified at runtime. |
| HISTORICAL_REPORTED | A past result, verdict or self-report, not re-run or recomputed. Never a current operational observation. |
| INFERRED | A reasoned conclusion from other evidence. Not directly observed. |
| NOT_VERIFIED | Could not be verified, either because evidence is missing or because the access needed (database reads, `.env` values, image filesystems) was not authorized. |
| CONTRADICTORY | Two or more sources disagree. |

### How to read the tags

- Every finding carries a tag such as `[RT-09 · RUNTIME_VERIFIED]`: a stable finding ID from the package register, followed by its evidence class.
- The same IDs and classes are used in every document of the package, including the Arabic audit, so a finding can be traced across documents. Later mentions use the bare ID (for example RT-09).
- Each major finding is followed by an evidence line giving:
  - the source;
  - the symbol or key;
  - the commit, or "runtime";
  - the observation date;
  - whether it is runtime-verified;
  - its limitations.
- The ID prefixes used here are:
  - PD: scope and process;
  - RT: runtime and parity;
  - ARC: architecture and activation;
  - CAL: configuration precedence (treated in full in [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md));
  - CON: contradictions.
- IDs from other areas are mentioned by bare ID only.

### Summary of what is and is not established

| Question | Answer | Basis |
|---|---|---|
| Which containers run, with which image tags and image IDs? | Established at inspection time: five bot services, the forward collector and postgres run; the learner is stopped; claude_review, redis and optimizer have no container. | RT-09, RT-10, RT-14 |
| Do the deploy records match what runs? | Yes. All 8 of 8 DEPLOYED.json entries match on container, image, ref, start time, restart count, state and config hash. | RT-23, RT-35 |
| Does the production Compose file equal the reviewed Git version? | At blob level, yes. However, the checkout is a stale non-main branch with uncommitted edits, so git status cannot show clean parity. | RT-24, CON-03 |
| Which commit's code runs inside each image? | Documented only. Image labels name a commit only for telegram and trade_tracker (bb7825f); no image filesystem was hashed. | RT-15, RT-16, RT-17 |
| Which feature flags and thresholds are effective? | Not verified. `.env` and the database were not read; the only configured values come from the 2026-09-27 snapshot. | CAL-02, CAL-03, RT-31, RT-47 |
| Is Paper-only enforced? | No order-placement code exists in the repository. This is source-verified, not runtime-verified. | ARC-11 |
| Are the services healthy? | The five bot services and postgres are healthy. The collector is unhealthy, for an unverified cause. | RT-43, RT-45 |

### Contents

1. [Scope, method and evidence limitations](#1-scope-method-and-evidence-limitations)
2. [Production checkout state](#2-production-checkout-state)
3. [Service and container inventory](#3-service-and-container-inventory)
4. [Images and provenance](#4-images-and-provenance)
5. [Compose configuration, config hashes and configuration precedence](#5-compose-configuration-config-hashes-and-configuration-precedence)
6. [Parity verdict per service](#6-parity-verdict-per-service)
7. [Version drift between documented commits, main and the checkout](#7-version-drift-between-documented-commits-main-and-the-checkout)
8. [Branch integration status](#8-branch-integration-status)
9. [Health observations](#9-health-observations)
10. [Implemented architecture and actual activation status](#10-implemented-architecture-and-actual-activation-status)
11. [Runtime-related contradictions](#11-runtime-related-contradictions)
12. [Not verified in this area and open questions](#12-not-verified-in-this-area-and-open-questions)

## 1. Scope, method and evidence limitations

This section records how the runtime and parity evidence was obtained. PD-01 to PD-04 are the investigation agents' own reports of their method on 2026-10-31; they were not re-run during publication. PD-05 records the publication-stage checks.

**[PD-01 · HISTORICAL_REPORTED] Inspection method.** The runtime inspection started at 13:59Z on 2026-10-31, and a second health sample was taken at 14:05Z. The runbook [docs/ops/COMPOSE_OPERATIONS.md](../../ops/COMPOSE_OPERATIONS.md) was read first. Only Class A read-only commands were used:
- `docker ps` and `docker inspect` with selected fields, and `docker image inspect`;
- Docker Compose `config --hash` and `config --services`;
- `ops/compose-safe logs --tail 20`, run from a non-production worktree against the production project. Its output was machine-filtered to category counts, so no log line was viewed or quoted.

Ancestry figures (ahead/behind, merged/unmerged) were computed in the shared git object store of the audit worktrees, not inside the production checkout.
- Evidence:
  - source: runtime/parity investigation report §1 and compiled audit §2;
  - commit: runtime;
  - observed: 2026-10-31;
  - runtime-verified: not applicable (method statement);
  - limitations: self-reported by the investigation agent; not re-run during publication.

**[PD-02 · HISTORICAL_REPORTED] What was not accessed.** The audit did not access:
- the production database (no queries of any kind);
- `.env` contents or any environment value;
- `docker exec`;
- network fetches;
- image filesystems;
- Paper outcomes after 2026-08-19;
- sealed holdouts or protected evidence partitions.

Research data files (JSON, JSONL, CSV) and the root `*.txt` outputs were checked for existence only. Post-freeze sections of committed documents were skipped: A42 §A.3 L61-66, §B.1 L107 and §A42-F L283, and A45 §A45-C W1 L93.
- Evidence:
  - source: compiled audit §2, research-history report legend, runtime report §1;
  - commit: not applicable;
  - observed: 2026-10-31;
  - runtime-verified: not applicable;
  - limitations: self-reported.

**[PD-03 · HISTORICAL_REPORTED] Versions read.** Code was read with `git show` (read-only) at the commits documented as deployed:
- analyzer and signal_engine at ea8ae4f;
- telegram and trade_tracker at bb7825f;
- the collector at 72c0bee;
- the scanner from the blobs listed in `deploy/baseline-2026-09-27/deployed_files.json` at 8bfca77, with the `shared/config.py` blob c5c03b5c from 7bf6214.

Repository documents were read at ebf8d8a (`feature/design-a-v1`). Configured values were taken from the committed non-secret snapshot `deploy/baseline-2026-09-27/config/*.nonsecret.json` (2026-09-27).

One investigation report labels ebf8d8a as "main". A publication-stage check confirmed that eba90dd is an ancestor of ebf8d8a and that only the 13 Design A files differ, none of them in an active-service directory.
- Evidence:
  - source: strategy, indicator, architecture and universe investigation reports;
  - commits: ea8ae4f, bb7825f, 72c0bee, 8bfca77, 7bf6214, ebf8d8a;
  - observed: not applicable;
  - runtime-verified: no;
  - limitations: reading code at a commit does not prove that a running image contains that commit (RT-16, RT-17).

**[PD-04 · HISTORICAL_REPORTED] Process deviations disclosed by the investigation agents.** All five were outside the repository and had no production effect:
1. one temporary file holding `git ls-remote` output was written to the session scratchpad root instead of its audit folder;
2. a sub-agent wrote and ran a static helper script in the session scratchpad; it uses only `git show` and regular expressions and imports no application module;
3. the modification time of the production `.env` file was read (metadata only; its content was never read);
4. audit notes were written in the session scratchpad, outside the repository;
5. a permission rule blocked reading `.env.example`, so its values are cited only through `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md`.
- Evidence:
  - source: runtime, strategy, indicator, architecture and universe investigation reports, and compiled audit §2;
  - commit: not applicable;
  - observed: 2026-10-31;
  - runtime-verified: not applicable;
  - limitations: self-reported; none of these files is part of this package.

**[PD-05 · SOURCE_VERIFIED] Publication-stage checks.** The publication re-ran no investigation. Its read-only checks on git objects, with no runtime access, were limited to resolving report inconsistencies or missing evidence:
- the legacy 1d score rule and the legacy order-book term (`signal_engine/signal_logic.py` at ea8ae4f);
- the capacity-multiplier wording (`shared/economic_halt_policy.py:18-20` at bb7825f);
- the source of the 15m fee-burden figure (`docs/strategy/S4_MECHANISM_COMPARISON.md:58`);
- path existence on main;
- the full commit SHAs listed in section 0.
- Evidence:
  - source: git objects in the publication worktree;
  - commits: eba90dd, ea8ae4f, bb7825f;
  - observed: 2026-10-31;
  - runtime-verified: no;
  - limitations: none of these checks touched the host runtime.

**Evidence limitations for this document.**
- Runtime facts are a snapshot taken between 13:59Z and 14:05Z on 2026-10-31.
- No image filesystem was read, so the code inside each image is DOCUMENTED_ONLY (RT-16, RT-17).
- No `.env` value and no database row was read. Every effective flag value and the pause/risk state are NOT VERIFIED (RT-31, RT-46, RT-47, CAL-03).
- Logs were seen only as category counts.
- Container IDs, network addresses and host paths are deliberately omitted from this package.

## 2. Production checkout state

The production checkout is the host working tree from which the production Compose project is operated. Its path is withheld ([REDACTED-HOST-PATH]). All observations in this section were made with read-only git commands on the host.

**[RT-01 · RUNTIME_VERIFIED] Branch and HEAD.** The checkout is on branch `integration/research-pipeline` with no upstream configured. HEAD is 63da7d3, dated 2026-08-19 (the research-freeze date), which equals the remote tip of that branch.
- Evidence: host git (Class A, read-only), current branch, upstream configuration and HEAD.
  - Commit: runtime (HEAD 63da7d3). Observed 2026-10-31. Runtime-verified: yes.
  - Limitations: point-in-time.

**[RT-02 · RUNTIME_VERIFIED] Uncommitted changes.** Eight tracked files are modified, with +219/−204 changed lines in total. There are also 104 untracked entries (research data, scripts and documents).

| Modified tracked file | Changed lines |
|---|---|
| `analyzer/technical_analyzer.py` | 146 |
| `telegram/main.py` | 104 |
| `docker-compose.yml` | 84 |
| `trade_tracker/main.py` | 30 |
| `docs/canary_state.md` | 29 |
| `database/init.sql` | 22 |
| `.gitignore` | 6 |
| `shared/schema.py` | 2 |

- Evidence: host `git status` and diff statistics against HEAD 63da7d3.
  - Commit: runtime. Observed 2026-10-31. Runtime-verified: yes.
  - Limitations: untracked entries were counted, not inspected.

**[RT-03 · RUNTIME_VERIFIED] Blob identity of the modified files.**
- Three of the modified files equal the blobs at main eba90dd: `docker-compose.yml`, `database/init.sql` and `.gitignore`. `database/init.sql` also equals ea8ae4f and bb7825f (blob 031b1c0).
- Five files carry uncommitted edits that match no commit, whether HEAD, main, ea8ae4f or bb7825f:
  - `analyzer/technical_analyzer.py`;
  - `shared/schema.py`;
  - `telegram/main.py`;
  - `trade_tracker/main.py`;
  - `docs/canary_state.md`.
- Evidence: `git hash-object` on the host files, compared with git objects at 63da7d3, eba90dd, ea8ae4f and bb7825f.
  - Observed 2026-10-31. Runtime-verified: yes.
  - Limitations: equality is per file blob. It says nothing about which code a container runs (see RT-26 and RT-27).

**[RT-04 · RUNTIME_VERIFIED] Relation to main.**
- Remote main is eba90dd (`git ls-remote`).
- merge-base(63da7d3, eba90dd) = 63da7d3, so the checkout HEAD is an ancestor of main: 0 commits ahead and 267 behind.
- The checkout's own `origin/main` ref is stale at 0a396c2 (2026-06-28), and eba90dd is absent from its object store. The relation therefore cannot be derived from the checkout alone; it was computed in the audit worktrees' shared object store.
- Evidence: `git ls-remote`, `git merge-base` and commit counting on commits 63da7d3, eba90dd and 0a396c2.
  - Observed 2026-10-31. Runtime-verified: yes.
  - Limitations: ancestry only.

**[RT-05 · RUNTIME_VERIFIED] Missing operational directories.** The production checkout contains neither a `deploy/` nor an `ops/` directory (see CON-02).
- Evidence: host directory listing. Observed 2026-10-31. Runtime-verified: yes.

**[RT-06 · SOURCE_VERIFIED] Schema versions.**

| Location | `REQUIRED_SCHEMA_VERSION` |
|---|---|
| 63da7d3 | 8 |
| the checkout's uncommitted edits | 9 |
| ea8ae4f, bb7825f and main | 11 |

Migrations 001 to 011 are present at ea8ae4f. The checkout's uncommitted edits include migration 009 (`risk_recovery_events`) and a `cmd_recover_risk` Telegram command, an older version of what later landed in main.
- Evidence: git objects at 63da7d3, ea8ae4f, bb7825f and eba90dd, plus the host working-tree files; symbol `REQUIRED_SCHEMA_VERSION` and the migration files.
  - Runtime-verified: no (file content, not runtime behaviour).
  - Limitations: the database's actual schema version was not read.

**[RT-07 · SOURCE_VERIFIED] Checkout versus deployed sources.**
- The checkout differs from every deployed image's documented source in `analyzer/`, `signal_engine/`, `telegram/main.py` and `trade_tracker/`.
- Files where the checkout differs from main: `analyzer/main.py`, `analyzer/technical_analyzer.py`, `signal_engine/main.py`, `signal_engine/signal_logic.py`, `telegram/main.py`, `trade_tracker/main.py` and `binance_price_stream.py`.
- The checkout's `scanner/*.py` files equal main and ea8ae4f, but the running scanner image is an assembled overlay (RT-39).
- Only `continuous_learner` would be built from the checkout (ARC-19, CON-19).
- Evidence: file-hash comparison of host files with git objects at eba90dd, ea8ae4f and bb7825f.
  - Runtime-verified: no.
  - Limitations: file comparison only.

**[RT-08 · INFERRED] Nature of the analyzer edit.** The checkout's `analyzer/technical_analyzer.py` edit (+7/−139 lines against 63da7d3) replaces inline indicator and level code with calls into `shared/strategy_math`. By reading, it is functionally equivalent. It is not what runs: the running analyzer image is documented as ea8ae4f content (RT-16).
- Evidence: strategy/execution investigation report ("production checkout change"), comparing 63da7d3 with the host working tree.
  - Runtime-verified: no.
  - Limitations: equivalence was judged by reading, not by tests.

## 3. Service and container inventory

**[RT-09 · RUNTIME_VERIFIED] Container inventory.** All dates are 2026; times are UTC to the minute. The restart count was 0 for every container.

| Container (Compose project) | State | Config.Image | Image Id | Created | Started | Health | Restart policy |
|---|---|---|---|---|---|---|---|
| trading_analyzer | running | `tsb-a561-analyzer:rel-ea8ae4f-r2` | 011f99ba451b | 10-16 22:19Z | 10-19 15:20Z | healthy | unless-stopped |
| trading_scanner | running | `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z` | 63b38e7a659d | 09-30 06:50Z | 10-19 15:20Z | healthy | unless-stopped |
| trading_signal_engine | running | `tsb-a561-signal_engine:rel-ea8ae4f-r2` | c5be4e34c064 | 10-16 22:50Z | 10-19 15:20Z | healthy | unless-stopped |
| trading_telegram | running | `tsb-obs-telegram:bb7825f-20261027-r2` | d665388a9092 | 10-27 11:51Z | 10-27 11:51Z | healthy | unless-stopped |
| trading_tracker | running | `tsb-obs-trade_tracker:bb7825f-20261027-r2` | 8e609ca84740 | 10-27 10:56Z | 10-27 10:56Z | healthy | unless-stopped |
| trading_continuous_learner | exited (143) | `trading-signal-bot-continuous_learner` | d1aa69bde63f | 08-17 17:49Z | 08-17 17:49Z, finished 08-17 21:03Z | unhealthy (left over from its last run) | unless-stopped |
| tsb-p2-forward-collector (project tsb-p2-forward) | running | `tsb-p2-forward:p2f-161-72c0bee-20261022T1558Z` | 89232400d528 | 10-22 17:45Z | 10-22 17:45Z | unhealthy | no |
| postgres (project shared-postgres) | running | `postgres:16.15-alpine3.24@sha256:721873c3…` | 721873c34ceb | 09-29 12:05Z | 10-19 15:20Z | healthy | unless-stopped |

Sub-points from the audit notes:
- postgres is a shared PostgreSQL 16.15 instance outside the bot's Compose project.
- The forward collector runs as its own Compose project, from image p2f 1.6.1. That image is documented as built at 72c0bee, in DEPLOYED.json and in the image tag (DOCUMENTED_ONLY). The image carries no labels (RT-15), and another document names commit 1bfb5f6 (CON-06).

Evidence for the inventory:
- Sources: `docker ps`, and `docker inspect` (State, Config.Image, Image, Created, StartedAt, RestartCount, Health, restart policy), together with `docker image inspect`.
- Commit: runtime. Observed 2026-10-31 at 13:59Z and 14:05Z. Runtime-verified: yes.
- Limitations:
  - point-in-time;
  - container IDs and network details are deliberately omitted;
  - second-precision start times are recorded in [deploy/DEPLOYED.json](../../../deploy/DEPLOYED.json) and matched live (RT-35).

**[RT-10 · RUNTIME_VERIFIED] Running, stopped and absent services.**

| Status | Services |
|---|---|
| Running | analyzer, scanner, signal_engine, telegram, trade_tracker, the forward collector, postgres |
| Stopped but present | `trading_continuous_learner` (exited with code 143) |
| No container | `claude_review`, `redis`, `optimizer` |

- Evidence: `docker ps -a` (Class A). Observed 2026-10-31. Runtime-verified: yes.
  - Limitations: whether a Compose service definition exists was checked separately (RT-22).

**[RT-11 · RUNTIME_VERIFIED] The learner stayed stopped.**
- `continuous_learner` stayed stopped through the 2026-10-19 restart, when analyzer, scanner, signal_engine and postgres last started; the collector last started on 2026-10-22, and telegram and trade_tracker on 2026-10-27. Its restart policy is `unless-stopped`.
- The audit notes record that `deploy/DEPLOYED.json` expects the learner to be not running. That record describes it as "stopped since 2026-08-17; must stay stopped" (DOCUMENTED_ONLY; see LRN-04).
- Evidence: `docker inspect` (state and restart policy) and `deploy/DEPLOYED.json`.
  - Commit: runtime. Observed 2026-10-31. Runtime-verified: yes for state and policy.
  - Limitations: why it stayed stopped is inferred (RT-12).

**[RT-12 · INFERRED] What keeps the learner stopped.** Because the policy is `unless-stopped`, the learner staying stopped depends on three things:
- Docker's manual-stop flag;
- the `learner` Compose profile, which only keeps it out of a default `up`;
- the operating procedure.

CLAUDE.md states that the profile is not an authorization boundary and that targeting the learner needs a separate owner authorization (DOCUMENTED_ONLY).
- Evidence: runtime report §3 and compiled audit §3.
  - Runtime-verified: no.
  - Limitations: the manual-stop flag itself was not inspected.

**[RT-13 · RUNTIME_VERIFIED] claude_review is retired from runtime.**
- There is no `claude_review` container, and the service is removed from the Compose file.
- The image `trading-signal-bot-claude_review:latest` is still present locally. CLAUDE.md notes that rolling back the CR-2 retirement would require creating the service from that image.
- Passive code remnants are described in ARC-16 to ARC-18.
- Evidence: `docker ps -a`, `docker image inspect` and Compose `config --services`. Observed 2026-10-31. Runtime-verified: yes.

## 4. Images and provenance

**[RT-14 · RUNTIME_VERIFIED] Image inventory.** The table gives each image's Id prefix, creation time (UTC, to the minute), source labels and the deploy records it matches.

| Image | Id | Created | Source labels | Matches records |
|---|---|---|---|---|
| `tsb-a561-analyzer:rel-ea8ae4f-r2` | 011f99ba451b | 10-16 18:46 | revision=unknown | a561 `IMAGES.md`, `DEPLOYED.json` |
| `tsb-a561-signal_engine:rel-ea8ae4f-r2` | c5be4e34c064 | 10-16 18:46 | revision=unknown | a561 `IMAGES.md`, `DEPLOYED.json` |
| `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z` | 63b38e7a659d | 09-29 12:41 | revision=unknown | aiohttp `IMAGES.md`, `DEPLOYED.json` |
| `tsb-obs-telegram:bb7825f-20261027-r2` | d665388a9092 | 10-27 07:40 | revision=bb7825f; base `tsb-a561-telegram` (51d62f4d) | paper-observe `IMAGES.md`, `VERSION_BOUNDARY.md`, `DEPLOYED.json` |
| `tsb-obs-trade_tracker:bb7825f-20261027-r2` | 8e609ca84740 | 10-27 07:40 | revision=bb7825f; base 2cf1dd52 | paper-observe `IMAGES.md`, `VERSION_BOUNDARY.md`, `DEPLOYED.json` |
| `tsb-p2-forward:p2f-161-72c0bee-20261022T1558Z` | 89232400d528 | 10-22 15:58 | no labels at all | Stage A record, `DEPLOYED.json` |
| `continuous_learner:latest` (container Config.Image `trading-signal-bot-continuous_learner`) | d1aa69bde63f | 08-17 17:48 | revision=c4cae2b-dirty | `DEPLOYED.json` |

The records are:
- `deploy/a561-rel-ea8ae4f/IMAGES.md`;
- `deploy/paper-observe-bb7825f/IMAGES.md`;
- `deploy/aiohttp-3.14.3/IMAGES.md`;
- [deploy/DEPLOYED.json](../../../deploy/DEPLOYED.json);
- [deploy/VERSION_BOUNDARY.md](../../../deploy/VERSION_BOUNDARY.md).

Evidence:
- Source: `docker image inspect` (Id, Created, labels), compared with the deploy records.
- Commit: runtime. Observed 2026-10-31. Runtime-verified: yes.
- Limitations: image metadata only.

**[RT-15 · RUNTIME_VERIFIED] What the labels prove.** Image labels identify a source commit only for the two `tsb-obs` images (revision=bb7825f).
- The analyzer, signal_engine and scanner images carry `revision=unknown`.
- The collector image has no labels.
- The learner image is labelled `c4cae2b-dirty`.

Image IDs and image references are RUNTIME_VERIFIED. Source commits derived from labels are verified only for telegram and trade_tracker.
- Evidence:
  - source: `docker image inspect` labels;
  - commit: runtime;
  - observed: 2026-10-31;
  - runtime-verified: yes;
  - limitations: a label is a build-time claim recorded in the image; it is not a hash of the image's files.

**[RT-16 · DOCUMENTED_ONLY] Content parity is recorded, not observed.** Parity between the running images and the documented commits is recorded only in the deploy records:

| Service | Recorded parity |
|---|---|
| analyzer | 46 of 46 shipped files equal ea8ae4f |
| signal_engine | 56 of 56 equal ea8ae4f |
| telegram | 50 of 50 equal bb7825f |
| trade_tracker | 51 of 51 equal bb7825f |
| scanner | assembled overlay; 8 of its 23 files differ from main |

The records are `deploy/DEPLOYED.json`, `deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json` and the `IMAGES.md` files.
- Evidence:
  - source: deploy records at eba90dd;
  - symbol: per-service file-match counts;
  - commit: eba90dd (records);
  - runtime-verified: no;
  - limitations: these counts were produced when the records were written; this audit did not recompute them.

**[RT-17 · NOT_VERIFIED] Image contents were not hashed.**
- Hashing the files inside the images needs an image filesystem read. That is not a Class A operation and was not authorized (see OQ-03).
- Consequently, no code behaviour described anywhere in this package is runtime-verified. Behaviour is SOURCE_VERIFIED at the documented commit only.
- Evidence:
  - source: runtime report §6 and compiled audit;
  - runtime-verified: no;
  - limitations: this is the main gap between "deployed per records" and "observed to execute this code".

**[RT-18 · RUNTIME_VERIFIED] No registry digests.** RepoDigests are only `<repo>@<Id>`: these are local images with no registry digest. The record wording on this point is inconsistent (CON-04).
- Evidence:
  - source: `docker image inspect` (RepoDigests);
  - observed: 2026-10-31;
  - runtime-verified: yes.

**[RT-19 · RUNTIME_VERIFIED] Rollback images are present locally.**
- `tsb-a561-telegram` (51d62f4d) and `tsb-a561-trade_tracker` (2cf1dd52), matching `deploy/VERSION_BOUNDARY.md`;
- `tsb-p1d-analyzer` and `tsb-p1d-signal_engine`;
- `tsb-aiohttp-rollback-scanner` (9b0b53a6).
- Evidence:
  - source: `docker image inspect`;
  - observed: 2026-10-31;
  - runtime-verified: yes;
  - limitations: presence only; rollback was not exercised.

**[RT-20 · RUNTIME_VERIFIED] Compose image-label digests.** For four containers, the `com.docker.compose.image` label differs from the image Id:

| Container | Label digest | Note |
|---|---|---|
| scanner | b647a72a | the documented arm64 manifest digest |
| telegram | ef66b10b | |
| trade_tracker | 37444d16 | |
| collector | cb3dd739 | |

- Evidence:
  - source: `docker inspect` labels;
  - observed: 2026-10-31;
  - runtime-verified: yes.

**[RT-21 · NOT_VERIFIED] Undocumented label digests.** The telegram, trade_tracker and collector label digests are documented nowhere. They are INFERRED to be platform-manifest digests.
- Evidence:
  - source: runtime report §4 and §9;
  - runtime-verified: no;
  - limitations: their meaning was not confirmed.

## 5. Compose configuration, config hashes and configuration precedence

**[RT-22 · RUNTIME_VERIFIED] Compose services.** `config --services` lists analyzer, scanner, signal_engine, telegram and trade_tracker.
- The learner and the optimizer are not in that list. They are defined behind the `learner` and `disabled` profiles (LRN-03, LRN-09).
- claude_review is not defined (RT-13).
- Evidence:
  - source: `docker compose config --services` (Class A);
  - observed: 2026-10-31;
  - runtime-verified: yes.

**[RT-23 · RUNTIME_VERIFIED] Config hashes equal the deploy records.** For every running bot service, three hashes are identical: the current `config --hash`, the hash in the container's Compose label, and the hash in the deploy record.

| Service | Config hash (prefix) | Recorded in |
|---|---|---|
| analyzer | c69beccc | a561 `IMAGES.md`, `DEPLOYED.json` |
| scanner | e99de276 | aiohttp `IMAGES.md`, `DEPLOYED.json` |
| signal_engine | 20dcae19 | a561 `IMAGES.md`, `DEPLOYED.json` |
| telegram | 14b2baf7 | paper-observe `IMAGES.md`, `DEPLOYED.json` |
| trade_tracker | 539e6347 | paper-observe `IMAGES.md`, `DEPLOYED.json` |

- Evidence:
  - source: `docker compose config --hash <service>` (Class A), the container's Compose labels, and the deploy records;
  - commit: runtime;
  - observed: 2026-10-31;
  - runtime-verified: yes;
  - limitations: a config hash covers the rendered service configuration, not image contents; only hash prefixes are given here.

**[RT-24 · RUNTIME_VERIFIED] The host Compose file is main's reviewed file.** The host `docker-compose.yml` has blob d1a4b197 (`git hash-object`). It equals:
- `eba90dd:docker-compose.yml`;
- the `git_blob` in `deploy/DEPLOYED.json`;
- the stage-2 blob in `deploy/VERSION_BOUNDARY.md`.

It differs from the checkout HEAD blob e83a83fc. The "local modification" is therefore main's reviewed Compose file sitting on a stale branch.
- Evidence:
  - source: `git hash-object` on the host and git objects;
  - commits: runtime, eba90dd and 63da7d3;
  - observed: 2026-10-31;
  - runtime-verified: yes;
  - limitations: blob identity only (see CON-03).

**[RT-25 · RUNTIME_VERIFIED] Compose changes against the checkout HEAD (names only, no values).**
- claude_review is removed.
- continuous_learner gained `profiles`.
- scanner: `build` is replaced by `image` plus `pull_policy`.
- analyzer and signal_engine: the same change, plus:
  - `volumes`;
  - the CoinMarketCap and CoinGecko credential variables, which are set blank and used by no client;
  - EVIDENCE_V2_ENABLED.
- telegram and trade_tracker: the same change, plus EVIDENCE_V2_ENABLED and PAPER_ECONOMIC_HALT_MODE (literal `observe`).
- Evidence:
  - source: comparison of the host Compose file with the HEAD blob (names only);
  - observed: 2026-10-31;
  - runtime-verified: yes;
  - limitations: no environment value was printed or recorded.

**[RT-26 · RUNTIME_VERIFIED] No builds and no source mounts.**
- No running service has `build:`.
- Mounts are logs, models and evidence data only. There are no source bind mounts.
- Evidence:
  - source: Compose file and `docker inspect` mounts;
  - observed: 2026-10-31;
  - runtime-verified: yes.

**[RT-27 · INFERRED] The checkout's edits are not executed.** Since no running service builds from the checkout or mounts source from it (RT-26), its uncommitted code is not executed by any running service.
- Evidence:
  - source: RT-26 and RT-03;
  - runtime-verified: no;
  - limitations: this does not cover the learner, which would build from the checkout if started (ARC-19).

**[RT-28 · RUNTIME_VERIFIED] Scanner override file.** The scanner container was created with an additional override file kept in a host backup directory. The file exists but was not read. The plain-file render hash now equals the container's label.
- Evidence:
  - source: `docker inspect` labels and Compose `config --hash`;
  - observed: 2026-10-31;
  - runtime-verified: yes;
  - limitations: the override's content is unknown to this audit.

**[RT-29 · RUNTIME_VERIFIED] Collector Compose file.** The host `compose.yml` of the separate collector project has blob 12052900. It equals `eba90dd:p2_forward/compose.yml` and `deploy/DEPLOYED.json`.
- Evidence:
  - source: `git hash-object` on the host and git objects;
  - observed: 2026-10-31;
  - runtime-verified: yes.

**[RT-30 · NOT_VERIFIED] Collector render hash.** The collector's render hash was not computed, because computing it needs P2F_* environment values.
- Evidence:
  - source: runtime report §5;
  - runtime-verified: no.

**[RT-31 · NOT_VERIFIED] PAPER_TRADING.** PAPER_TRADING is not set in any service's Compose `environment:` block. Its runtime value, from `.env` or the code default true, was not read.
- Evidence:
  - source: Compose file (blob d1a4b197) and `shared/config.py`;
  - runtime-verified: no;
  - limitations: needs a redacted `.env` read (OQ-02).
- Structural Paper-only behaviour is covered separately: no order-placement code exists (ARC-11).

### Configuration precedence

**[CAL-01 · SOURCE_VERIFIED] Precedence order.** The effective value of a setting resolves in this order: Compose `environment:` first, then `.env` (loaded through `env_file`), then the dataclass default read at import.
- No strategy or universe variable is set in any Compose `environment:` block, so every strategy value comes from the unread `.env`.
- Hard-coded constants cannot be overridden.
- The only database override is `optimizer_settings` `min_score` / `min_tf`, read only on the legacy decision path.
- `indicator_weights` have no environment counterpart; they multiply score parts with a default of 1.0.
- Full parameter treatment: [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md).
- Evidence:
  - source: `shared/config.py` dataclass defaults, Compose file blob d1a4b197, and `_get_live_thresholds` in `signal_engine/signal_logic.py`;
  - commits: ea8ae4f, bb7825f, eba90dd;
  - runtime-verified: no;
  - limitations: this describes the resolution order, not the resolved values (CAL-03). CLAUDE.md's statement that DB thresholds override `.env` is contradicted (CON-11).

**[CAL-02 · DOCUMENTED_ONLY] Where configured values come from.** Configured values come from the committed resolved-config snapshot `deploy/baseline-2026-09-27/config/*.nonsecret.json` (2026-09-27). That snapshot predates every current container start (RT-09): 2026-10-19 for analyzer, scanner, signal_engine and postgres; 2026-10-22 for the collector; 2026-10-27 for telegram and trade_tracker.
- `.env.example` values are cited through `docs/ops/ENV_EXAMPLE_REVIEW_2026-10-18.md`, which itself flags `.env.example` as misleading (line 20).
- Evidence:
  - source: deploy baseline snapshot and the environment-example review document at eba90dd;
  - runtime-verified: no;
  - limitations: the snapshot may be stale.

**[CAL-03 · NOT_VERIFIED] No effective value is verified.**
- For every parameter, "runtime-verified" is no.
- Every database value (`optimizer_settings`, `indicator_weights`, `learned_gates`, `symbol_blacklist`) requires an authorization that was not granted.
- Evidence:
  - source: indicator/calibration report;
  - runtime-verified: no;
  - limitations: see OQ-01 and OQ-02.

## 6. Parity verdict per service

The matrix below reproduces the runtime investigation's per-service parity verdict. Each cell carries its own evidence class. In it:
- "Configured-enabled" means the service is defined in its Compose project's default service set. For the five bot services it also means the config hash matches the records (RT-23).
- "Operationally verified" would require reading the image filesystem or the service's runtime state.

| Service | Documented commit | Integrated in main | In deployed image | Configured-enabled | Observed executing | Operationally verified |
|---|---|---|---|---|---|---|
| analyzer | ea8ae4f | yes (SOURCE_VERIFIED, ancestry) | 46/46 files per records (DOCUMENTED_ONLY); label revision=unknown (RUNTIME_VERIFIED) | yes (RUNTIME_VERIFIED) | running, healthy (RUNTIME_VERIFIED) | NOT_VERIFIED (needs the image filesystem) |
| signal_engine | ea8ae4f | yes (SOURCE_VERIFIED) | 56/56 per records (DOCUMENTED_ONLY) | yes (RUNTIME_VERIFIED) | running, healthy (RUNTIME_VERIFIED) | NOT_VERIFIED |
| scanner | assembled overlay; 8 of 23 files differ from main (DOCUMENTED_ONLY) | not applicable | per records (DOCUMENTED_ONLY) | yes (RUNTIME_VERIFIED) | running, healthy (RUNTIME_VERIFIED) | NOT_VERIFIED |
| telegram | bb7825f | yes (SOURCE_VERIFIED) | label revision=bb7825f (RUNTIME_VERIFIED); 50/50 per records (DOCUMENTED_ONLY) | yes, observe mode (RUNTIME_VERIFIED) | process running (RUNTIME_VERIFIED); observe path NOT_VERIFIED | record says "Validated: NO" (DOCUMENTED_ONLY) |
| trade_tracker | bb7825f | yes (SOURCE_VERIFIED) | label revision=bb7825f (RUNTIME_VERIFIED); 51/51 per records (DOCUMENTED_ONLY) | yes, observe mode (RUNTIME_VERIFIED) | process running (RUNTIME_VERIFIED); observe path NOT_VERIFIED | record says "Validated: NO" (DOCUMENTED_ONLY) |
| collector | 72c0bee | yes (SOURCE_VERIFIED) | no labels; per records (DOCUMENTED_ONLY) | yes (RUNTIME_VERIFIED) | running (RUNTIME_VERIFIED) | unhealthy; cause NOT_VERIFIED |
| continuous_learner | label c4cae2b-dirty | yes, as reported (SOURCE_VERIFIED) | label c4cae2b-dirty (RUNTIME_VERIFIED) | excluded by the `learner` profile | not executing (RUNTIME_VERIFIED) | not applicable |
| production checkout (63da7d3 plus edits) | not applicable | 63da7d3 is in main (SOURCE_VERIFIED) | not the source of any running image (INFERRED, RT-27) | not applicable | not applicable | not applicable |

**[RT-32 · RUNTIME_VERIFIED] Configured-enabled and executing.**
- analyzer, signal_engine, scanner, telegram and trade_tracker are running and healthy.
- telegram and trade_tracker are configured with PAPER_ECONOMIC_HALT_MODE=observe.
- The forward collector is running.
- The learner is not executing; it is excluded by its profile.
- Evidence:
  - source: Compose `config --services` / `config --hash`, the Compose file, and `docker inspect`;
  - observed: 2026-10-31;
  - runtime-verified: yes, for configuration and process state;
  - limitations: "configured" means the Compose definition, not the code path taken inside the process (RT-33).

**[RT-33 · NOT_VERIFIED] The observe code path.** Two things would need image filesystem access or runtime state: whether the observe code path is the one executing inside telegram and trade_tracker, and per-service operational verification in general.
- Evidence:
  - source: runtime report §6;
  - runtime-verified: no.
- The observe-mode rules themselves are SOURCE_VERIFIED at bb7825f; see RSK-01 in [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md).

**[RT-34 · DOCUMENTED_ONLY] Paper-observe validation status.** The paper-observe deployment record states "Validated: NO" for telegram and trade_tracker.
- Evidence:
  - source: the paper-observe deployment record under `deploy/paper-observe-bb7825f/` at eba90dd, as cited by the runtime investigation;
  - runtime-verified: no.

**[RT-35 · RUNTIME_VERIFIED] DEPLOYED.json matches live.** Every service entry in [deploy/DEPLOYED.json](../../../deploy/DEPLOYED.json) (8 of 8) matches the live container on seven fields:
- container ID;
- image Id;
- image ref;
- start time;
- restart count;
- state;
- config hash.

DEPLOYED.json does not track health.
- Evidence:
  - source: field-by-field comparison of `deploy/DEPLOYED.json` with `docker inspect`;
  - commit: eba90dd (record) vs runtime;
  - observed: 2026-10-31;
  - runtime-verified: yes;
  - limitations:
    - a match of metadata, not of image contents (RT-17);
    - the collector's unhealthy state is not reflected in the record (CON-05).

**[RT-36 · DOCUMENTED_ONLY] Known release-manifest pointer gap.** The DEPLOYED.json `release_manifest` still points to the a561 manifest, while the paper-observe manifest lives only on the host. A plain deep check therefore reports drift for telegram, trade_tracker and the collector, by design. This gap is known and documented.
- Evidence:
  - source: `deploy/DEPLOYED.json` and the runtime report §9;
  - runtime-verified: no;
  - limitations: a documented known gap, not a new defect.

## 7. Version drift between documented commits, main and the checkout

**[RT-37 · SOURCE_VERIFIED] What changed between the documented commits.**

From ea8ae4f to bb7825f (the commits behind the analyzer/signal_engine and telegram/trade_tracker images):
- Added T1_CAP_POLICY: `shared/t1_cap.py`, from commit `a4a7561e568e1e3ecd8b769566d59c1d4c9afd6d` (a4a7561).
- Added `shared/economic_halt_policy.py`.
- Added the observe-aware `risk_epoch.operational_state`. At bb7825f, telegram calls `operational_state(streak, paused, econ_mode)` at `telegram/main.py:737`, and trade_tracker imports `economic_halt_policy` at `trade_tracker/main.py:34`.
- Changed:
  - `analyzer/main.py`: +2 lines, a T1 startup check (`t1_cap_policy()`);
  - `analyzer/technical_analyzer.py`: 17 lines;
  - `signal_engine/signal_logic.py`: +1 line, `telemetry_min_interval`;
  - `shared/config.py`: +32 lines;
  - `telegram_messages`.

From bb7825f to main:
- For active code, bb7825f equals main. Only `docker-compose.yml` differs, by 6 lines.

main against ea8ae4f:
- main differs from ea8ae4f in `analyzer/main.py` (the T1 startup check), `analyzer/technical_analyzer.py` and `signal_engine/signal_logic.py` (one telemetry line).
- telegram and trade_tracker run bb7825f code, which equals main.

From 63da7d3 (the checkout HEAD) to ea8ae4f:
- 42 files changed in active directories, about +7,500 lines.
- For example, `shared/signal_readiness.py`, `outbox_watch`, `signal_identity`, `signal_selection` and `risk_epoch` are absent at 63da7d3.

The T1-cap consequence is recorded as STR-17. In the documented-deployed analyzer source (ea8ae4f), the cap is hard-coded and cannot be switched. The running behaviour is NOT VERIFIED (RT-17).
- Evidence:
  - source: git diffs between ea8ae4f, bb7825f, eba90dd and 63da7d3;
  - runtime-verified: no;
  - limitations: line counts come from the audit notes and reports and were not recomputed during publication.

**[RT-38 · INFERRED] Running without the newer modules is harmless today.** The documented-deployed analyzer and signal_engine source (ea8ae4f) lacks `economic_halt_policy`, `risk_epoch` and `t1_cap`. This is harmless today because neither service imports them.
- Evidence:
  - source: import graph at ea8ae4f, from the architecture report and audit notes;
  - runtime-verified: no;
  - limitations: "harmless" refers only to import compatibility, not to strategy behaviour (STR-17).

**[RT-39 · DOCUMENTED_ONLY] The scanner image is assembled.** According to `deploy/a561-rel-ea8ae4f/RUNTIME_MANIFEST.json:622-866` and `deploy/baseline-2026-09-27/deployed_files.json`, the scanner image is assembled from several older commits:
- Its `scanner/main.py` (blob 3dc9cb1) and `scanner_logic.py` (blob fa03cc2a) are identical to ea8ae4f and main.
- Its shared config (`shared/config.py` blob c5c03b5c from 7bf6214), macro, outbox and schema files are older versions.
- Its schema guard requires v6.
- Evidence:
  - source: deploy records, plus blob comparison of the traced files;
  - commits: 8bfca77, 7bf6214, ea8ae4f;
  - runtime-verified: no;
  - limitations: the blob equality is SOURCE_VERIFIED, but that the image contains those blobs is documented only.

**[RT-40 · NOT_VERIFIED] Scanner imports.** The scanner's actual imports are unknown, because its base revision is unknown.
- Evidence:
  - source: architecture report;
  - runtime-verified: no.

## 8. Branch integration status

**[RT-41 · SOURCE_VERIFIED] Remote branches.** There are 141 remote heads. Merge status was judged by ancestry against eba90dd; every tip object was available locally.

Merged into main:
- `integration/research-pipeline` (equal to the production HEAD), `develop`, `dev`;
- `feature/a42` through `feature/a48`; `feature/s3-signal-selection`, `s3-shadow-sidecar`, `s3-shadow-evaluation`;
- `fix/a38-paper-execution-integrity`, `fix/a49-economic-label-on-a38`, `fix/b3-fail-closed-trading-state`, `fix/loss-streak-recovery-epoch`, `fix/t1-cap-policy-flag`;
- `feat/research-admission-budget` and `-probes`, `feat/throttle-decay`;
- `research/s4-mechanism-infra`, `research/s4-phase1-comparison`, `docs/strategy-lab-architecture`.

Not merged (commits outside main):
- `feature/design-a-v1` +5;
- `integration/rnd` +8; `integration/paper-vb-a1` +5; `integration/paper-observe-activation` +3;
- `integration/a49-candidate` +9; `a49-candidate-r2` +11; `a50` +14; `a51` +16; `a52` +20; `a53` +10;
- `research/variant-ledger` +10; `feat/research-admission-shadow` +3; `feat/technical-halt-recovery` +4; `feat/s5-pwr-1-ladder-power` +3;
- `lab/l1-account-safeguards` +6; `lab/l1-parity-guards` +8;
- `release/rc-b-se-telemetry-on-ea8ae4f` +1; `refactor/strategy-math` +1; `safety/disable-auto-tune` +1; `fix/a49-nonfinite-economic-label` +11; `docs/profitability-roadmap` +3;
- `feature/p2a`, `p2b`, `p2c`, `p2cr`, `p2e1`, `p2f0`, `p2rm0`, `p2x0`, `p2x1` (+1 to +61); `feature/g1g2` +3; `feature/forward-instrumentation` +1.
- Evidence:
  - source: `git ls-remote` and ancestry tests against eba90dd;
  - observed: 2026-10-31;
  - runtime-verified: no (repository state, not runtime);
  - limitations: see RT-42.

**[RT-42 · INFERRED] Ancestry-only merge check.** The merge check uses ancestry only. Work integrated by squash or cherry-pick would still appear as not merged.
- Evidence:
  - source: runtime report §7;
  - runtime-verified: no.

## 9. Health observations

**[RT-43 · RUNTIME_VERIFIED] Health at 13:59Z and 14:05Z.**

| Service | Docker health (two samples) | Restarts | Safe log check (`ops/compose-safe`, tail 20, category counts only) |
|---|---|---|---|
| analyzer, scanner, signal_engine, telegram | healthy ×2 | 0 | 0 error/traceback, 0 connection-failure, 0 halt/pause/observe lines |
| trade_tracker | healthy ×2 | 0 | 0 error, connection or halt lines; WARN-level lines present but not inspected (RT-44) |
| collector | unhealthy ×2 | 0 | not checked (RT-45) |
| postgres | healthy ×2 | 0 | not checked (no database access) |

- Evidence:
  - source: `docker inspect` health state at two sample times, plus `ops/compose-safe logs --tail 20` with output reduced to counts;
  - commit: runtime;
  - observed: 2026-10-31;
  - runtime-verified: yes;
  - limitations: 20 log lines per service are a very short window; health is the container's own healthcheck verdict.

**[RT-44 · NOT_VERIFIED] trade_tracker warnings.** trade_tracker has WARN-level log lines. They were not inspected, because their text matched protected patterns.
- Evidence:
  - source: runtime report §8;
  - runtime-verified: no;
  - limitations: their content and significance are unknown.

**[RT-45 · NOT_VERIFIED] Cause of the collector's unhealthy status.** The collector's logs were not checked: `ops/compose-safe` does not cover the separate project tsb-p2-forward, and `Health.Log` is not an allowed inspection field. The cause is therefore unknown. The earlier deployment record documented the collector as healthy (CON-05).
- Evidence:
  - source: runtime report §8;
  - runtime-verified: no;
  - limitations: see OQ-04.

**[RT-46 · NOT_VERIFIED] Pause, halt and risk state.** PAPER_HALTED, pause and risk state require a database read, which was not authorized.
- Evidence:
  - source: runtime report §8 and architecture report;
  - runtime-verified: no;
  - limitations: whether Paper is currently admitting trades is unknown to this audit (OQ-01).

**[RT-47 · NOT_VERIFIED] Effective flag values and container state beyond the records.** Two things were not verified:
- the runtime values of SIGNAL_INTEGRITY_MODE, LIVE_LEARNING_MODE, LEARNING_GATES_ENABLED, TIMEFRAMES, RISK_CANARY_MAX_OPEN_TRADES and PAPER_ENTRY_FILL_MODEL, all of which come from `.env`;
- container state beyond what `deploy/DEPLOYED.json` records. The audit notes give that record's observation date as 2026-10-27, noted alongside a repository head 26eb4e8 (DOCUMENTED_ONLY).
- Evidence:
  - source: architecture report (NOT VERIFIED list) and compiled audit;
  - runtime-verified: no;
  - limitations: see OQ-02.

## 10. Implemented architecture and actual activation status

All findings in this section are read from code at the documented commits: ea8ae4f for the analyzer, signal_engine and the traced scanner files; bb7825f for telegram and trade_tracker; 72c0bee for the collector.

They are SOURCE_VERIFIED descriptions of that code. Whether the running images contain exactly that code is DOCUMENTED_ONLY (RT-16) and was NOT VERIFIED (RT-17). Process liveness is RUNTIME_VERIFIED (RT-32, RT-43).

**[ARC-01 · SOURCE_VERIFIED] Active pipeline.** The active pipeline is scanner → analyzer → signal_engine → `signal.ready` → telegram → trade_tracker, which is the CR-2 path described in CLAUDE.md.
- `signal.ready` is a row in the PostgreSQL `outbox_events` table, polled by telegram.
- There is no Redis and no LISTEN/NOTIFY.
- Evidence:
  - source: `signal_engine/main.py`, `shared/outbox.py`, `shared/signal_readiness.py` and `telegram/main.py`;
  - commits: ea8ae4f and bb7825f;
  - runtime-verified: no (code path).

**[ARC-02 · SOURCE_VERIFIED] Tables read and written along the pipeline.**

| Stage | Writes |
|---|---|
| scanner | `scan_candidates`, `service_heartbeats` |
| analyzer | upserts `analysis_results` per symbol and timeframe (`analyzer/main.py:165-174`); marks `scan_candidates.analyzed` |
| signal_engine | `signals` plus an `outbox_events` row (`signal.ready`) in one transaction; also `risk_management.signals_sent`, the `analysis_results` status, `macro_history` and heartbeats |
| telegram | `signals.telegram_sent` plus a `signal.delivered` event in one transaction; also `risk_management`, `risk_recovery_events`, `approval_requests`, the symbol white/blacklists and heartbeats |
| trade_tracker | `active_trades` and then `trade_results`; also `paper_entry_orders`, `trade_target_fills`, `risk_management`, `signals` (`telegram_sent=false` on rejects, `trade_tracker/main.py:768`, 804) and outbox events (`trade.*`, `risk.halted`, `risk.observed`, `price_stream.*`, `tracker.recovered`) |

Read paths:
- telegram reads `signals`, `active_trades`, `trade_results`, `trade_target_fills`, heartbeats, `optimizer_settings` (only for the /status display) and `analysis_results`.
- telegram and trade_tracker read no learner table, and nothing calls claude_review.
- The tracker admits trades by polling `signals`. The `signal.delivered` event is used only for reconciliation (`trade_tracker/main.py:646-679`).
- Evidence:
  - source: SQL in the service modules;
  - commits: ea8ae4f and bb7825f;
  - runtime-verified: no;
  - limitations: table contents were not read.

**Stage table.** Each row is one finding. Line numbers refer to the documented commit for that service.

| Finding and stage | Modules and functions | Inputs → outputs | Service and image | Code read at |
|---|---|---|---|---|
| [ARC-03 · SOURCE_VERIFIED] Market data | python-binance AsyncClient over REST: `scanner_logic.py:74-124`; `technical_analyzer.py:127-134` (201 klines); `orderbook_analyzer.py:19` (20-level book); `macro_context.py:53-63`. CoinGecko `/api/v3/global` for USDT.D and BTC.D (`macro_context.py:28-33`, blocking urllib, no credential). Tracker: public REST `/api/v3/ticker/price` (`trade_tracker/main.py:1435`), `/exchangeInfo` (1461) and `/klines` (1485), plus the Binance WebSocket aggTrade stream at stream.binance.com (`binance_price_stream.py:12`, 94-107). No fear-and-greed or CoinMarketCap client exists. | exchange and CoinGecko data → `macro_history` and the per-service analyses | inside each service | ea8ae4f, bb7825f |
| [ARC-04 · SOURCE_VERIFIED] Scanner | `scanner/main.py` loop (lines 24-64); `scanner_logic.py` | Binance, `symbol_blacklist`, `risk_management` → `scan_candidates`, `service_heartbeats`. Cleanup expires `analysis_results` after 2 h and deletes `scan_candidates` after 1 h. | service `scanner` (container trading_scanner), image `tsb-aiohttp-test-scanner:3.14.3-20260929T124120Z`; env files: the shared `.env` plus a second, exchange-specific env file (names only; contents not read) | traced blobs equal to ea8ae4f (RT-39) |
| [ARC-05 · SOURCE_VERIFIED] Analyzer | `analyzer/main.py`; `technical_analyzer.TechnicalAnalyzer` (`_get_indicator_weights` at lines 63 and 482-490, `detect_trade_setup` 68-73, `_calculate_levels`); `orderbook_analyzer.py`; `simple_entry.py` | up to 50 `scan_candidates` per loop, Binance data and `indicator_weights` (read with no flag, fallback 1.0; written historically by the optimizer, colab and the init seed) → `analysis_results` upsert, `scan_candidates.analyzed`, evidence JSONL. Requires schema 11; no pause check; 60 s timeout per symbol; a weight read error falls back to 1.0; only 4 `analyzer/` files are copied into the image. | service `analyzer`, image `tsb-a561-analyzer:rel-ea8ae4f-r2` | ea8ae4f |
| [ARC-06 · SOURCE_VERIFIED] Signal engine | `signal_engine/main.py` (candidate query lines 146-155; live/legacy selector 173-176); `signal_logic.py` (gates 722-831, `save_signal` 911-1026); `macro_context.py`; `shared/signal_identity.py`; `shared/dependency_safety.py` | Reads `analysis_results` under 30 min old (`ORDER BY symbol, total_score DESC LIMIT 200`), `active_trades`, `signals`, `scan_candidates`, `macro_history`. Reads `learned_gates` only behind a flag, and `optimizer_settings` and `risk_management`/`trade_results` only on the legacy path. Writes `signals`, `risk_management.signals_sent`, `outbox_events`, the `analysis_results` status. Gate order: macro, then order book/spread (fail-closed), invalid stop, open trade or cooldown, learned gates. No pause check. In off mode a cooldown read error becomes an empty set, which fails open (`signal_logic.py:424-431`). In enforce mode bounded retries block the cycle, freshness and duplicate checks apply, and a `setup_key` is required. | service `signal_engine`, image `tsb-a561-signal_engine:rel-ea8ae4f-r2` | ea8ae4f |
| [ARC-07 · SOURCE_VERIFIED] signal.ready | `shared/signal_readiness.py`, `shared/outbox.py` | One `outbox_events` row, written in the same transaction as the `signals` insert. Payload {signal_id, decision_source, strategy_version}; unique on (event_type, aggregate_type, aggregate_id); dead-lettered after 8 attempts (migration 004). `assert_signal_complete` fails closed. A signal counts as ready if `decision_source='policy_ready' OR claude_approved IS TRUE` (`signal_readiness.py:26-33`). | — | ea8ae4f, bb7825f |
| [ARC-08 · SOURCE_VERIFIED] Telegram | `telegram/main.py`: `signal_loop` 187-242; `handle_candidate_event` 249-294; `can_deliver_candidate` 364-382; `mark_delivered` 576-583; lifecycle notices 449-539; /pause, /resume and /recover_risk 852-933 | `signal_loop` claims 5 events every 15 s, using FOR UPDATE SKIP LOCKED with a 300 s lease (`shared/outbox.py:27-44`), and also claims the legacy `signal.reviewed` event (`main.py:210`). A paused system refuses and drops the candidate (268-275). Capacity is min(MAX_OPEN_TRADES=10, RISK_CANARY_MAX_OPEN_TRADES). RISK_CANARY_MAX_OPEN_TRADES has code default 1 and is 2 in the 2026-09-27 snapshot (CON-16); its effective value is NOT VERIFIED (RT-47). `mark_delivered` sets `signals.telegram_sent` and emits `signal.delivered` in one transaction. Lifecycle notices are at-least-once with a 24 h TTL. Commands are owner-only. A transient error ends as `expired_undelivered` plus an alert. PAPER_ECONOMIC_HALT_MODE only changes message text here (736-749, 874-878, 472-473). Delivery uses the Telegram Bot API `sendMessage`. | service `telegram`, image `tsb-obs-telegram:bb7825f-20261027-r2` | bb7825f |
| [ARC-09 · SOURCE_VERIFIED] Trade tracker | `trade_tracker/main.py`: `main` 73-146; `register_new_signals` 705-904; `assess_new_trade_risk` 922-1006; `_risk_price` 1020-1038; `record_risk_decision` 1041-1093; `evaluate_trade` 1189-1304; `close_trade_barrier` 1307-1401; `binance_price_stream.py` | Signals that are `telegram_sent`, ready and under 2 h old → `active_trades`, `paper_entry_orders`, `trade_target_fills`, `risk_management`, outbox `trade.*`, `risk.halted`, `risk.observed`. WebSocket reconnects with a 5–60 s backoff; a REST check runs every 30 s; the WebSocket price cache is not used for decisions; writes are idempotent (ON CONFLICT). | service `trade_tracker` (container trading_tracker), image `tsb-obs-trade_tracker:bb7825f-20261027-r2` | bb7825f |
| [ARC-10 · SOURCE_VERIFIED] Result recording | `close_trade_barrier`; `shared/triple_barrier.py`, `shared/partial_exits.py`, `shared/fees.py:41-74`; `evidence_v2.py:183-211` | → `trade_results` (gross `result` plus `economic_result`, `net_profit_usdt`, `cost_usdt`, `label_policy`), `trade_target_fills`, `risk_management` wins/losses, a `trade.closed` event. Idempotent per `signal_id`. Evidence goes only to JSONL files under `data/evidence_v2/<service>/`. | inside the tracker | bb7825f |
| [ARC-14 · SOURCE_VERIFIED] Research components | Collector `python -m p2_forward` (version 1.6.1); `research/continuous_learner.py`; the research runner | The collector reads binance.vision WebSocket/REST data into files under `/data` and uses no database. It is not on the trading path. Its health file must be at most 30 s old; incidents stay latched until an ack file is written; `previous_run_crash_or_kill` sets DEGRADED; config keys include `ws_session_end_events` and `conn_flapping_enabled`. The learner writes `learned_gates`, `learned_gate_history` and `learning_runs`. | Collector: separate project tsb-p2-forward, image `tsb-p2-forward:p2f-161-72c0bee-20261022T1558Z`. Learner: Compose profile `learner`, build context ".". Runner: a systemd user job, not part of Compose. | 72c0bee, ea8ae4f |

Evidence for the stage table:
- Source: code at the documented commits, read with `git show`.
- Runtime-verified: no; process liveness only (RT-32).
- Limitations: image contents are DOCUMENTED_ONLY (RT-16); the scanner's imports are NOT VERIFIED (RT-40).

**Activation, safety and tests by stage.** This table restates the architecture investigation's activation matrix. Code defaults are SOURCE_VERIFIED at the documented commits. Values marked "snapshot" are DOCUMENTED_ONLY (2026-09-27). No effective runtime value is verified (CAL-03, RT-47).

| Stage | Flags and defaults | Failure handling | Tests |
|---|---|---|---|
| Market data | MACRO_MAX_STALE_HOURS=2 | Closed candles only; gaps, duplicates and NaN rejected (`shared/ohlcv.py:26-83`). No age check on the last candle, except the freshness rule in integrity `enforce` mode (`shared/signal_identity.py:186-200`). Stale macro data blocks signals. | test_ohlcv, test_macro_context |
| Scanner | SCAN_INTERVAL_SECONDS=300; volume ≥ 10M USDT and 24h price change ≥ 1% | The only upstream halt (B3) gate: `get_pause_state()` (`scanner_logic.py:26-29`; `trading_state.py:21-47`) fails closed, and only the latest `manual_resume` allows scanning. The BTC trend falls back to "neutral" on error, so that filter fails open (`scanner_logic.py:125-148`; MKT-02). | test_b3_fail_closed_callers only |
| Analyzer | SIGNAL_INTEGRITY_MODE defaults to `off`, and an unknown value refuses start; EVIDENCE_V2_ENABLED is "true" in Compose; LIVE_LEARNING_MODE defaults to false; no T1_CAP_POLICY exists at ea8ae4f, so the T1 cap is hard-coded as `resistance*0.99` (`technical_analyzer.py:463-467`; STR-17) | Requires schema 11. No pause check. 60 s timeout per symbol. A weight read error falls back to 1.0. | test_indicators, test_orderbook_analyzer, test_simple_entry, test_regime, test_signal_stop, test_a43_signal_integrity, test_evidence_v2_pit |
| Signal engine | LIVE_LEARNING_MODE; LEARNING_GATES_ENABLED defaults to false; the env names LEARNING_CLEAN_START, LEARNING_CONFIDENCE_Z and LEARNING_EXPLORATION_RATE are set | Gates in order: macro, order book/spread (fail-closed), invalid stop, open trade or cooldown, learned gates. In `off` mode a cooldown read error becomes an empty set and fails open (`signal_logic.py:424-431`). In `enforce` mode bounded retries block the cycle, freshness and duplicate checks apply, and a `setup_key` is required. No pause check. | test_fixed_candidate_policy, test_live_spread_finite, test_signal_logic_hook, test_a44_selection_pipeline, test_decision_parity_before_after |
| signal.ready | — | `assert_signal_complete` fails closed. Readiness = `decision_source='policy_ready' OR claude_approved IS TRUE` (`signal_readiness.py:26-33`). | test_cr1_signal_ready_contract and its e2e variant, test_p1r_cr2_contract and its e2e variant, test_outbox |
| Telegram | PAPER_ECONOMIC_HALT_MODE=observe in Compose; in telegram it only changes message text | If paused, a candidate is refused and dropped. Capacity is min(MAX_OPEN_TRADES=10, RISK_CANARY_MAX_OPEN_TRADES). RISK_CANARY_MAX_OPEN_TRADES has code default 1 and is 2 in the 2026-09-27 snapshot (CON-16); its effective value is NOT VERIFIED (RT-47). Commands are owner-only. A transient error ends as `expired_undelivered` plus an alert. The whitelist approval path is dead code (`whitelist.py:107-111`; UNI-08). | test_telegram_handlers and test_b3_telegram_gate (both skip outside `/app`), test_risk_recovery_command, test_paper_economic_alerts, test_telegram_messages |
| Trade tracker | PAPER_ECONOMIC_HALT_MODE defaults to `enforce`; an unknown value falls back to enforce; observe requires PAPER_TRADING=true. PAPER_ENTRY_FILL_MODEL: an unknown value refuses start. RISK_PRICE_FETCH_RETRIES=0, backoff 0.5. | **enforce**: the daily-loss, weekly-loss, drawdown and loss-streak (B3) stops write a `risk:` pause. **observe** (configured in Compose; execution NOT VERIFIED, RT-33): those four become `observed:` records, and only `invalid_risk_state` pauses. A NaN price gives `invalid_risk_state`. WebSocket reconnect with 5–60 s backoff; REST check every 30 s; the WebSocket price cache is not used for decisions. ON CONFLICT keeps writes idempotent. No order-placement code exists anywhere in the repository (ARC-11). Details: RSK-01. | test_binance_price_stream, test_risk_price_retry, test_paper_economic_observation, test_paper_observe_capacity, test_a49_*, test_risk_epoch_concurrency, test_a48_tracker_parity_db |
| Result recording | — | Writes are idempotent per `signal_id`. | test_a38_lifecycle_db, test_fees, test_triple_barrier, test_partial_exits, test_evidence_v2_tracker_db |
| Research | Collector config: `ws_session_end_events`, `conn_flapping_enabled` | The health file must be at most 30 s old. Incidents stay latched until an ack file is written. `previous_run_crash_or_kill` sets DEGRADED. The collector is not on the trading path. | `p2_forward/tests/` (about 27 files), test_continuous_learner |

**[ARC-11 · SOURCE_VERIFIED] Paper-only is structural.**
- There is no order-placement code anywhere in the repository.
- PAPER_TRADING (code default true) only gates observe mode and labels.
- The anthropic package is imported only for exception types (`shared/retry_utils.py:33-40`).
- Evidence:
  - source: a repository-wide search, `shared/config.py` and `shared/retry_utils.py`;
  - commits: ea8ae4f and bb7825f;
  - runtime-verified: no;
  - limitations: this proves absence in the repository source, not in the images (RT-17). The runtime PAPER_TRADING value is NOT VERIFIED (RT-31).

**[ARC-12 · SOURCE_VERIFIED] Pause and halt checks.**
- The scanner's `get_pause_state()` (`scanner_logic.py:26-29`; `trading_state.py:21-47`) fails closed, and only the latest `manual_resume` allows scanning. It is the only upstream B3 gate.
- telegram refuses candidates while paused.
- The tracker applies its risk gate (RSK-01).
- The analyzer and signal_engine have no pause check.
- Evidence:
  - source: `scanner_logic.py` and `trading_state.py` at the scanner's traced blobs, `telegram/main.py` and `trade_tracker/main.py` at bb7825f, and analyzer/signal_engine code at ea8ae4f;
  - runtime-verified: no;
  - limitations: the current pause state is NOT VERIFIED (RT-46).

**[ARC-13 · SOURCE_VERIFIED] Market-data safety.**
- Only closed candles are used.
- Gaps, duplicates and NaN are rejected (`shared/ohlcv.py:26-83`).
- There is no age check on the last candle, except the freshness rule in integrity enforce mode (`shared/signal_identity.py:186-200`), which is off by default and not set in Compose (STR-33). Its runtime `.env` value is NOT VERIFIED (STR-34, RT-47).
- Stale macro data blocks signals (MACRO_MAX_STALE_HOURS=2).
- Evidence:
  - source: `shared/ohlcv.py`, `shared/signal_identity.py` and `shared/macro_context.py`;
  - commit: ea8ae4f;
  - runtime-verified: no.

**[ARC-15 · SOURCE_VERIFIED] Tests by stage.** The test modules per stage are those listed in the activation table above:
- market data: 2 modules;
- scanner: 1;
- analyzer: 7;
- signal engine: 5;
- signal.ready: 5;
- telegram: 5, two of which skip outside `/app`;
- tracker: 7 or more (including the test_a49_* modules);
- result recording: 5;
- research: about 27 collector test files plus test_continuous_learner.
- Evidence:
  - source: the `tests/` tree and `p2_forward/tests/`, as mapped by the architecture investigation;
  - runtime-verified: no;
  - limitations: the tests were not run during the audit or this publication.

**[ARC-22 · SOURCE_VERIFIED] Flags and code defaults.**

| Flag | Code default and behaviour |
|---|---|
| SIGNAL_INTEGRITY_MODE | default `off` (`shared/config.py:118` at ea8ae4f); an unknown value refuses start |
| EVIDENCE_V2_ENABLED | "true" in Compose |
| LIVE_LEARNING_MODE | default false (`shared/config.py:74` at ea8ae4f) |
| LEARNING_GATES_ENABLED | default false |
| LEARNING_CLEAN_START, LEARNING_CONFIDENCE_Z, LEARNING_EXPLORATION_RATE | env names set on signal_engine |
| SCAN_INTERVAL_SECONDS | 300 |
| PAPER_ECONOMIC_HALT_MODE | default `enforce` (`shared/config.py:131` at bb7825f) |
| PAPER_ENTRY_FILL_MODEL | `shared/config.py:112` at bb7825f; `observed_price_v0` or `resting_limit_v1`; an unknown value refuses start |
| RISK_PRICE_FETCH_RETRIES | default 0 (`shared/config.py:157` at bb7825f); backoff 0.5 (`:158` at bb7825f) |

Line numbers differ between ea8ae4f and bb7825f (RT-37).

- Evidence:
  - source: `shared/config.py` and the Compose file;
  - commits: ea8ae4f, bb7825f, eba90dd (Compose);
  - runtime-verified: no;
  - limitations: the effective values come from `.env` and are NOT VERIFIED (RT-47).

**[ARC-23 · DOCUMENTED_ONLY] Snapshot flags.** The 2026-09-27 non-secret baseline config snapshot records ENABLE_EVIDENCE_RECORDER true and LIVE_LEARNING_MODE true.
- Evidence:
  - source: `deploy/baseline-2026-09-27/config/*.nonsecret.json`, as cited in the audit notes and architecture report;
  - runtime-verified: no;
  - limitations: the snapshot predates every current container start (CAL-02).

### claude_review remnants

**[ARC-16 · SOURCE_VERIFIED] Passive dependencies remain.** claude_review has no Compose service and no import on the active path. Two passive dependencies remain:
- telegram still claims the legacy `signal.reviewed` event (`telegram/main.py:210`);
- the readiness predicate `READY_SQL_PREDICATE` still accepts `claude_approved IS TRUE`.
- Evidence:
  - source: `telegram/main.py` at bb7825f and `shared/signal_readiness.py`;
  - runtime-verified: no.

**[ARC-17 · INFERRED] Neither remnant is live.** signal_engine emits only `signal.ready`, and the tracker's 2-hour admission window excludes old approved rows.
- Evidence:
  - source: ARC-07, ARC-09 and the architecture report;
  - runtime-verified: no;
  - limitations: rows in the database were not read.

**[ARC-18 · SOURCE_VERIFIED] Stale Compose backup.** The tracked `docker-compose.yml.bak`, which is also present in the production directory, still defines claude_review.
- Evidence:
  - source: the tracked file in the repository and the host directory listing;
  - runtime-verified: no (SOURCE_VERIFIED; its presence in the production directory is as reported by the architecture investigation);
  - limitations: a hazard only if that file were ever used.

### The learner while stopped

The learner's code, data, statistics and runtime reader are documented under LRN-01 to LRN-20 in [STRATEGIES_INDICATORS_CALIBRATION.md](STRATEGIES_INDICATORS_CALIBRATION.md). The runtime-facing facts are:
- **Runtime reader.** The only runtime reader of learner output is signal_engine's `learned_gates` query (`signal_logic.py:27-28`, 391-394, 741-743). It sits behind LEARNING_GATES_ENABLED (default false) and has no age filter (LRN-18).
- **Flag value.** The flag is false in the 2026-09-27 snapshot (STR-19). The current `.env` value, and whether any `learned_gates` rows exist, are NOT VERIFIED (LRN-20).
- **If re-enabled.** Turning the flag on would immediately re-apply throttles last computed on or before 2026-08-17 (LRN-19).
- **LIVE_LEARNING_MODE** reads no learner table. It switches to rule-based setups and the `fixed_execution_quality_v1` selection policy (STR-01).
- **Frozen weights.** Frozen optimizer and colab data still reach the active path. `indicator_weights` are read with no flag and set `total_score`. Because the candidate query sorts by symbol first, the weights order only timeframes within a symbol, and `LIMIT 200` truncates alphabetically (LRN-16, LRN-17). `optimizer_settings` are used only by the legacy selector and the /status display.

**[ARC-19 · SOURCE_VERIFIED] How the learner could start.**
- `--profile learner` builds the learner from the production checkout (63da7d3 plus edits), not from a pinned release image (see also LRN-03, CON-19).
- `ops/compose-safe` refuses to start the learner.
- Evidence:
  - source: the Compose file (blob d1a4b197) and `ops/compose-safe`;
  - commit: eba90dd;
  - runtime-verified: no;
  - limitations: governance forbids starting it without a separate owner authorization (CLAUDE.md, DOCUMENTED_ONLY).

**[ARC-20 · DOCUMENTED_ONLY] Learner script inside an image.** The signal_engine image contains the learner script, so the learner could also be run via exec.
- Evidence:
  - source: repository documentation, as cited by the architecture investigation;
  - runtime-verified: no (image contents not read, RT-17).

### Legacy or unused code

**[ARC-21 · SOURCE_VERIFIED] Code not imported by any service.**
- Not imported by any service:
  - `claude_review/`;
  - `optimizer/` (Compose profile `disabled`);
  - `colab/`;
  - `monitor_canary.py`;
  - most of `analyzer/`, since only 4 files are copied into the analyzer image.
- Shared modules that no service imports:
  - `candidate_selection`, `signal_selection`, `s3_shadow*`;
  - `trade_geometry`, `strategy_math`, `t1_cap`;
  - `execution_calibration`, `replay_execution`, `signal_quality`;
  - `setup_diagnostics`, `counterfactual_barrier`, `candidate_diagnostics`.
- Evidence:
  - source: the import graph of the service entrypoints;
  - commits: ea8ae4f and bb7825f;
  - runtime-verified: no;
  - limitations: research modules are covered by STR-26 to STR-39.

## 11. Runtime-related contradictions

Each entry records two or more sources that disagree. The runtime observation is named where one exists. Contradictions in other areas are listed in their home documents. Examples are CON-09 (gross versus net counters), CON-11 (database override precedence), CON-22 (T1_CAP_POLICY on main but absent from the documented-deployed analyzer source, ea8ae4f) and CON-31 (the f3104c2 deployment status).

**[CON-01 · CONTRADICTORY] Stale runbook image list.**
- [docs/ops/COMPOSE_OPERATIONS.md](../../ops/COMPOSE_OPERATIONS.md) §0 says telegram and trade_tracker run `tsb-a561-*:rel-ea8ae4f-r2`, "verified against the running containers".
- Observed: `tsb-obs-*:bb7825f-20261027-r2` (RT-09). This agrees with CLAUDE.md, `deploy/DEPLOYED.json` and the paper-observe record.
- The canonical runbook is therefore stale. Its Class B image gate also points to the aiohttp `IMAGES.md`, which now covers only the scanner.
- Evidence:
  - sources: `docs/ops/COMPOSE_OPERATIONS.md` §0 at eba90dd vs `docker inspect` on 2026-10-31;
  - limitations: documentation drift; no runtime consequence was observed.

**[CON-02 · CONTRADICTORY] Helper scripts assumed in the production directory.**
- CLAUDE.md and the runbook treat `ops/compose-safe` as runnable from the production directory.
- The production checkout has neither `ops/` nor `deploy/` (RT-05).
- Evidence:
  - sources: CLAUDE.md and `docs/ops/COMPOSE_OPERATIONS.md` vs the host directory listing.

**[CON-03 · CONTRADICTORY] Blob-level parity only.**
- The rule that the production `docker-compose.yml` must equal the reviewed Git blob holds at blob level (RT-24).
- But the checkout is a non-main branch with no upstream, 267 commits behind main (RT-01, RT-04), and five files carry uncommitted edits matching no commit (RT-03).
- As a result, `git status` cannot show clean parity.
- Evidence:
  - sources: CLAUDE.md ("source of truth" rule) vs host git state on 2026-10-31.

**[CON-04 · CONTRADICTORY] RepoDigests wording.**
- The paper-observe `IMAGES.md` says "RepoDigests is empty" and calls the image Id a "config digest".
- Observed: RepoDigests = `<repo>@<Id>` (RT-18).
- The aiohttp record calls the same kind of Id the "OCI index". This contradiction is minor.
- Evidence:
  - sources: `deploy/paper-observe-bb7825f/IMAGES.md` and `deploy/aiohttp-3.14.3/IMAGES.md` vs `docker image inspect`.

**[CON-05 · CONTRADICTORY] Collector health.**
- The Stage A record documented the collector as HEALTHY after its deployment.
- On both reads of 2026-10-31 it is unhealthy (RT-43), for a cause that was NOT VERIFIED (RT-45).
- DEPLOYED.json does not track health (RT-35).
- Evidence:
  - sources: the Stage A deployment record vs `docker inspect`.

**[CON-06 · CONTRADICTORY] Collector commit.**
- `docs/ops/RUNTIME_TRACEABILITY.md` gives the collector commit as 1bfb5f6.
- `deploy/DEPLOYED.json` gives 72c0bee, which matches the running image tag `p2f-161-72c0bee-20261022T1558Z` (RT-09).
- Evidence:
  - sources: the two documents at eba90dd vs the observed image reference.

**[CON-07 · CONTRADICTORY] "Not wired" docstrings.**
- The docstrings of `shared/signal_identity.py` and `shared/dependency_safety.py` say "not wired" / "no production caller".
- Both modules are imported by production services (ARC-06).
- Evidence:
  - sources: module docstrings vs imports in `signal_engine` at ea8ae4f.

**[CON-08 · CONTRADICTORY] Documentation describes a learning, reviewing system.**
- `docs/claude/architecture.md:29` and `docs/claude/live-learning.md` show the learner and claude_review as active, and CLAUDE.md:3 says the bot "learns continuously".
- Observed: the learner is stopped (RT-10, RT-11) and claude_review is retired (RT-13).
- Evidence:
  - sources: the cited documents at eba90dd vs `docker ps -a` and the Compose service list.

**[CON-10 · CONTRADICTORY] RISK_PRICE_FETCH_RETRIES parsing.**
- The commit message for RISK_PRICE_FETCH_RETRIES says an invalid value becomes 0.
- In code, a non-numeric value raises at import (`shared/config.py:157` at bb7825f).
- Evidence:
  - sources: commit message vs `shared/config.py` at bb7825f.

**[CON-19 · CONTRADICTORY] Pinned images versus a working-tree build.**
- Every running service uses a pinned release image (RT-09).
- The learner, if started, would be built from the production working tree (63da7d3 plus uncommitted edits; ARC-19, LRN-03). That tree differs from every deployed source (RT-07).
- This sits against the pinned-image practice recorded in CLAUDE.md ("no rebuild and no retag").
- Evidence:
  - sources: Compose file (blob d1a4b197) and CLAUDE.md vs the host checkout state.

## 12. Not verified in this area and open questions

**Not verified (bare IDs).**

| ID | What is missing |
|---|---|
| RT-17 | image filesystem contents |
| RT-21 | meaning of three Compose label digests |
| RT-30 | collector render hash |
| RT-31 | runtime PAPER_TRADING value |
| RT-33 | observe code path actually executing |
| RT-40 | scanner imports |
| RT-44 | content of the trade_tracker WARN lines |
| RT-45 | cause of the collector's unhealthy status |
| RT-46 | pause, halt and risk state |
| RT-47 | effective flag values and container state beyond the records |
| CAL-03 | every effective parameter and database value |

Related items in other documents:
- STR-04: LIVE_LEARNING_MODE value;
- CAL-10: running APP_VERSION;
- LRN-20: learner table contents;
- EXE-08: fill model value;
- UNI-06: blacklist contents.

**Open questions for the owner relevant to this area.** These are questions only. Nothing in this package changes runtime, configuration or data.
- [OQ-01] Authorize narrow database reads? The proposed scope is:
  - `optimizer_settings` (key, value, updated_at);
  - `indicator_weights` (indicator, condition, weight, last_updated);
  - the current pause state only.

  Nothing would be read from trade or learning tables, whose post-freeze counts and times are protected (OD-7).
- [OQ-02] Authorize reading non-secret `.env` flags through a redacted allow-list? The flags are LIVE_LEARNING_MODE, SIGNAL_INTEGRITY_MODE, LEARNING_GATES_ENABLED, TIMEFRAMES, RISK_CANARY_MAX_OPEN_TRADES, PAPER_TRADING and PAPER_ENTRY_FILL_MODEL.
- [OQ-03] Authorize image content verification, that is, hashing the files inside the images? This is not a Class A operation.
- [OQ-04] The collector is unhealthy. Should an operational investigation be opened?
- [OQ-05] The production checkout is a stale branch with local edits, and the learner would build from it. What is the decision?

The full list of open questions is in [FULL_SYSTEM_AUDIT_AR.md](FULL_SYSTEM_AUDIT_AR.md) and [REVIEWER_EVIDENCE_PACK.md](REVIEWER_EVIDENCE_PACK.md). Governance boundaries that apply to any follow-up are in [OWNER_OPERATING_CONTRACT.md](../../governance/OWNER_OPERATING_CONTRACT.md), [DEVELOPMENT_FIRST_POLICY.md](../../governance/DEVELOPMENT_FIRST_POLICY.md) and [BRANCH_RELEASE_POLICY.md](../../ops/BRANCH_RELEASE_POLICY.md).

---

This document records findings only. It makes no recommendation to change code, configuration, runtime or strategy, and it is not a profitability certification.
