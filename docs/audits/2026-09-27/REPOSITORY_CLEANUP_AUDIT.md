# REPOSITORY_CLEANUP_AUDIT — baljadrawy/trading-signal-bot (read-only, 2026-09-27)

**Mode:** strictly read-only. There was no fetch, tag, delete, merge, push or settings change, and only GET calls on the GitHub API. It follows ADR-011 and `docs/product/REPOSITORY_CONSOLIDATION.md` (governance branch @`2ffb44b`, PR #3) and SINGLE_HOST_SAFETY.

**Goal:** one permanent branch, `main`, with temporary branches only during development and PR review.

**Labels:** **[C]** confirmed, **[A]** assessment, **[R]** recommendation, **[V]** verify before acting. Part II (verbatim from `work/repository_cleanup_findings.md`) holds the per-branch and per-file evidence, the SHAs, the 9-step sequence with commands and Appendix A.

# Part I — Consolidated assessment
## 1. Prioritised findings
| P | Finding |
|---|---|
| **P0** | **Unreviewed code in the production folder [C].** `/home/tradmin/trading-signal-bot` has an uncommitted `analyzer/technical_analyzer.py` that is byte-identical to the unreviewed `refactor/strategy-math@6d6790f`. The running analyzer image does **not** contain it, but any `docker compose build` from that folder would ship it. |
| **P0** | **Unsafe bare `docker compose up -d` [C]** in `setup.sh:52`, `docs/claude/operations.md:6-8`, `CLAUDE.md:14` and more. It would start the deliberately stopped `continuous_learner`, which has no profile. |
| **P1** | **Backup gap [C].** The Phase-0 bundle lacks develop `4e3eb0a`, baseline `3ed49c3`, P1 `23dea90`, refactor `6d6790f` and PR #3 `2ffb44b` (which exists on GitHub only). No off-host copy exists. |
| **P1** | **No rollback tag [C].** The only local tag is lightweight (`snapshot-live-learning-0a396c2`). GitHub has 0 tags and 0 releases. |
| **P1** | **No guard on `main` [C]:** no protection or rulesets. The host holds a **write** deploy key `server-signalbot-rw`, and the paused `cron-signal-bot-review.sh` would commit and push on the checked-out branch if re-enabled. |
| **P2** | **develop ≠ production for 5 of 7 images [C].** 23 of 190 deployed file records run older blobs; 3 files match no commit (preserved in `3ed49c3/unmatched`). |
| **P3** | 17 obsolete branches contained in develop; 8 SAFE-TO-REMOVE files; 201 `.py` NEEDS-OWNER-DECISION; 135.9 MB tracked (98.7% in `analyzer/` caches and CSVs). |

## 2. Deployed images vs develop vs uncommitted production folder [C]
None of these three was modified.

| Layer | What it is | Relation |
|---|---|---|
| **Running images** (7) | IDs equal to `DEPLOYED_MANIFEST.json` (scanner `9b0b53a6a799`, analyzer `ce305ecd7760`, signal_engine `b3d4b6236654`, tracker `2b59c6a164c0`, telegram `b84d3d1528a0`, claude_review `8bca25750c77`, learner `d1aa69bde63f` exited) | Known-good baseline record **`3ed49c3`** (on B3 `8bfca77`). No image carries a clean git SHA label. |
| **develop `4e3eb0a`** | baseline + 7 research/docs commits | Equal to production code only for **tracker (29/29) and telegram (28/28)**. Scanner (5 files), analyzer (2), signal_engine (2), claude_review (6) and the learner (8) run older blobs, all reachable in develop's history. |
| **Production folder** `/home/tradmin/trading-signal-bot` | Dirty checkout of `integration/research-pipeline@63da7d3` with 111 status entries; contains the unreviewed `technical_analyzer.py` | It is the compose project directory, the `data/evidence` bind mount and the cron path. **Any git operation or build here is a production change.** |

**Consequence [R]:** do not squash, rebase or rewrite history, and do not delete `develop` before `main` contains it. It is the only path that reaches every deployed blob.

## 3. Single-main consolidation sequence (proposal; each step needs owner approval)
| Step | Action | Resource / downtime impact | Rollback |
|---|---|---|---|
| 0 | Approvals and freeze window | none | – |
| 1 | Approved `git fetch origin` (no prune), a fresh all-refs bundle, `git bundle verify`, and an off-host copy decision | seconds of IO; no service impact | the bundle itself |
| 2 | Create and push the annotated tag **`prod-baseline-2026-09-27` → `3ed49c306ce404359c94ee549dd24b431be2a558`** (push only this tag; never `--tags` or `--force`); verify the manifest | none | `git push origin :refs/tags/…` (tag only) |
| 3 | Decide each unique branch. **refactor:** review + parity PR, or retire. **safety/disable-auto-tune:** port as a fresh PR onto `main`, or retire. **P1:** its own release gate. Retire only with an `archive/*` tag. | none | the archive tag restores the branch |
| 4 | Review and merge PR #3 (governance docs) into develop | none | revert the PR |
| 5 | **develop → main via PR, merge-commit method only.** `main` has 0 unique commits; its only unique file is an older `.dockerignore`. | none; hosts use paths, not branches [C] | reset `main` to `0a396c2` (recorded; in bundle) |
| 6 | GitHub settings: keep default `main`, protection/rulesets (**[V]** GitHub plan), `delete_branch_on_merge`, restrict merge methods | none | revert settings |
| 7 | Update references (CLAUDE.md, docs, `setup.sh`, deploy notes) through PRs to `main` | none | revert PR |
| 8 | Delete obsolete branches in waves A→E (§4) | none | recreate from bundle or tag |
| 9 | Steady state: `main` only; cron rewritten to push PR branches only | none | – |

**The production folder is excluded from every step.** Switching it to `main` is a separate, owner-approved production change with its own diff review.

## 4. Deletion candidates (each reviewed individually in Part II §9; nothing deleted)
| Wave | Items | Precondition |
|---|---|---|
| A | remote `dev`, `feat/py312-feature-store-audit-2026-06-23`, `feat/throttle-decay-2026-08-10`, `fix/loss-streak-recovery-epoch` (all contained in develop, 0 unique) | step 1 bundle |
| B | `deploy/baseline-2026-09-27`, `fix/b3-fail-closed-trading-state` | step 2 tag pushed and verified |
| C | remote `integration/research-pipeline` only; the **local branch stays** (production runs from it) | step 5 |
| D | 10 local-only contained branches, plus local twins once worktrees are released (A10) | bundle |
| E | `develop` (last) | `main` contains it (step 5) |
| Conditional | docs branch after PR #3; P1 after its gate; refactor and safety only with a decision + `archive/*` tag | per-branch decision |
| Files | 8 SAFE-TO-REMOVE (4 duplicate `.py`, 2 duplicate `.md`, `database/migrate.sql`, `docker-compose.yml.bak`) in one PR on `main` | after step 5 |
| Never | tags; Docker `b3-rollback/*` anchors; the production folder | – |

## 5. Remediation plans (proposals)
**R1. Uncommitted production-folder change (P0).**
1. Record, read-only, the file's SHA-256 against `6d6790f`.
2. Keep the committed copy (do not delete `refactor/strategy-math`).
3. Owner chooses one of:
   - (a) retire: owner-approved restore of the tracked file in the production folder *after* a backup copy (a production-folder change with no service impact, since the running image does not contain the file); or
   - (b) adopt: review + parity PR through `main`.
4. Until decided: **no image builds from the production folder** [R].
- Impact: file only; no downtime.
- Rollback: the backup copy or the branch.

**R2. Bare `docker compose up -d` (P0).**
1. A PR on `main` replaces every instance with explicit `docker compose up -d --no-deps --no-build <service>`.
2. Consider `profiles: ["retired"]` for `continuous_learner` in compose. This is a compose change, so it is deployed only with an approved release.
3. Until then, operators must name services.
- Impact: none until deployed.
- Rollback: revert the PR.

**R3. Branch protection and deploy-key access (P1).**
1. **[V]** Confirm the GitHub plan (protection and rulesets on private repos).
2. Require PRs into `main`; block force-push and deletion; enable `delete_branch_on_merge`.
3. Rotate the host deploy key to **read-only**. Pushes then happen from the owner's machine or from a separate, owner-held key per task.
4. Keep `cron-signal-bot-review.sh` paused until it pushes PR branches only.
- Impact: none on services. The host loses push access, so Claude sessions will need the owner to push or use a scoped token.
- Rollback: restore the settings or the key.

## 6. Owner approvals and open questions
- **Approvals:** A1–A12 are in Part II §10.1. Headline items: fetch + bundle + off-host copy; the rollback tag; PR #3; develop→main merge-commit; refactor, safety and P1 decisions; deletion waves; GitHub settings and deploy key; worktree pruning; file-cleanup PR; cron rewrite.
- **Open questions:**
  - Is the GitHub plan Pro?
  - Is Colab still writing `indicator_weights` to the production DB?
  - Where should the off-host backup live?
  - Merge commit or fast-forward?
  - What should happen to the 107 analyzer research scripts?

---
# Part II — Detailed findings and evidence (verbatim: work/repository_cleanup_findings.md)

# REPOSITORY_CLEANUP_AUDIT — baljadrawy/trading-signal-bot

| Field | Value |
|---|---|
| Date | 2026-09-27 (evening, after P1 push `23dea90`) |
| Mode | **STRICTLY READ-ONLY.** No branch/tag/file/default-branch/CI/host change was made. Nothing was fetched, checked out, merged, pushed, tagged or deleted. |
| Governing decisions | ADR-011 (one long-lived canonical branch, target `main`), `docs/product/REPOSITORY_CONSOLIDATION.md`, `docs/product/SINGLE_HOST_SAFETY.md` (ADR-010), `DECISION_LOG.md`. All read from the remote branch `docs/market-intelligence-governance-20260927@2ffb44b` (draft PR #3) through `gh api .../contents?ref=`. That branch is **not merged**. |
| Canonical target | `main` = the only permanent branch. Feature/fix/docs branches exist only while under PR review. Release and rollback points become immutable annotated tags, not permanent branches. |
| Status of this document | Findings and **proposals only**. Each deletion, tag, merge, default-branch or protection change needs separate owner approval (ADR-011 gate). Changing the GitHub default branch or deleting branches **is not a deployment**. Production stays PAPER_HALTED / PAPER_ONLY with B3 fail-closed. |


## Contents
- [0. Executive summary](#0-executive-summary)
- [1. Scope, rules and method](#1-scope-rules-and-method)
- [2. GitHub repository state](#2-github-repository-state-get-only-2026-09-27)
- [3. Branch, tag and ref inventory](#3-branch-tag-and-ref-inventory)
- [4. Production deployment, rollback anchors, schedules and backups](#4-production-deployment-rollback-anchors-schedules-and-backups)
- [5. Known-good production baseline and proposed rollback tag](#5-known-good-production-baseline-and-proposed-rollback-tag-not-created)
- [6. Unused-code audit on `develop`](#6-unused-code-audit-on-develop-4e3eb0a-worktree-hometradmintsb-develop)
- [7. Repository hygiene: size, artifacts, docs and config clutter](#7-repository-hygiene-size-artifacts-docs-and-config-clutter)
- [8. Safe consolidation sequence](#8-safe-consolidation-sequence-proposal-each-step-needs-its-own-owner-approval)
- [9. Deletion list](#9-deletion-list-proposed-nothing-deleted-owner-sign-off-required-per-item)
- [10. Owner decisions required, open questions and audit limitations](#10-owner-decisions-required-open-questions-and-audit-limitations)
- [11. Evidence index](#11-evidence-index-reproducible-read-only)
- [Appendix A. Per-file candidate table](#appendix-a-candidate-table-every-non-production-non-test-py-file-250-rows)

## 0. Executive summary

**Verdict.** Consolidating to one permanent `main` is feasible, low-risk for Git history, and needs **no history rewrite**:
- `main` (`0a396c2`) has **0 unique commits** and is 44 commits behind `develop` (`4e3eb0a`), so it is a strict ancestor.
- There is no CI, no workflow, no branch protection and no GitHub deployment that references any branch.
- The GitHub **default branch is already `main`**.

The real risks are **not** in GitHub. They are on the single shared host (ADR-010) and in four branches that carry unique work.

### Key counts
| Area | Count / fact |
|---|---|
| Branch names (local ∪ GitHub) | **23**: 21 local heads + 2 GitHub-only (`dev`, `docs/market-intelligence-governance-20260927`) |
| GitHub branches | **13**. SHA-for-SHA equal to local remote-tracking refs and `ls-remote`. |
| Local-only branches (never pushed) | **10**: `fix/*-2026-07-15/-07-29` ×4, `research/*` ×6. All fully contained in `develop` and all exact heads in the Phase-0 bundle. |
| Fully contained in `develop` (0 unique patches) | **18**: `main` + **17 obsolete candidates** |
| Branches with unique, unmerged work | **4**: see the table below |
| Tags / releases | GitHub: **0 / 0**. Local: 1 lightweight `snapshot-live-learning-0a396c2` → `0a396c2`. **No immutable rollback tag exists.** |
| PRs | 3. #1 and #2 (`dev`→`main`) merged 2026-04-08. **#3 open draft** (governance docs → `develop`). |
| Worktrees on the host | 6. Six local branches are pinned by worktrees. The production compose runs from `/home/tradmin/trading-signal-bot`, a dirty checkout on `integration/research-pipeline`. |
| Tracked `.py` on `develop` | **345**. 45 production-reachable. 140 KEEP. **201 NEEDS-OWNER-DECISION**, mostly `analyzer/` research. **4 SAFE-TO-REMOVE** (byte-identical duplicates). |
| SAFE-TO-REMOVE files in total | **8** (4 `.py` + 2 `.md` duplicates + `database/migrate.sql` + `docker-compose.yml.bak`) |
| Repository size on `develop` | 952 files, **135.9 MB**. `analyzer/` is 98.7% of it (434 `.pkl` caches = 105.4 MB; 3 result CSVs = 31.6 MB). Packed history is 40.6 MB and is **not** bloated by deleted files. |

**The four branches with unique, unmerged work:**
- `feature/forward-instrumentation` (P1 `23dea90`, +1)
- `refactor/strategy-math` (`6d6790f`, +1)
- `safety/disable-auto-tune` (`3d1857d`, +1/−44, diverged)
- `docs/market-intelligence-governance-20260927` (`2ffb44b`, +21, PR #3, **GitHub-only**)

### Known-good production baseline and proposed rollback tag
- **Baseline:** `deploy/baseline-2026-09-27@3ed49c3` records the deployed state on top of **B3 `8bfca77`** (`3ed49c3^ == 8bfca77`).
- **Running images:** all 7 service image IDs match `DEPLOYED_MANIFEST.json`.
- **Rollback anchors:** 5 Docker tags (`b3-rollback/{scanner,telegram,trade_tracker}:pre-b3`, `{trade_tracker,telegram}:pre-risk1-rollback`). They are preserved in the verified Phase-0 image tar.
- **Proposed tag (not created):** annotated **`prod-baseline-2026-09-27` → `3ed49c306ce404359c94ee549dd24b431be2a558`**. §5 gives the exact command and verification.
  - The tag name deliberately differs from the branch/path `deploy/baseline-2026-09-27`, which is ambiguous in Git.
  - The name is currently free as a tag, a branch and a path.

### Critical findings (read before any action)
1. **Unreviewed code sits in the production checkout.** The uncommitted `analyzer/technical_analyzer.py` in `/home/tradmin/trading-signal-bot` is byte-identical to the unreviewed `refactor/strategy-math@6d6790f`.
   - The running analyzer image does **not** contain it.
   - Any `docker compose build` from that directory would ship it.
   - Deleting `refactor/strategy-math` would orphan the only committed copy.
2. **`develop` ≠ production code for 5 of 7 images.**
   - 23 of 190 deployed file records (11 unique paths) run older blobs, and 3 files match no commit at all.
   - Every deployed blob is reachable **only through `develop`'s history** (the 3 unmatched files are preserved in `3ed49c3`).
   - Therefore: never squash or rebase `develop` into `main`, never rewrite history, and never delete `develop` before `main` contains it.
3. **Backup gap.** The Phase-0 all-refs bundle (17:50) does **not** contain `develop@4e3eb0a`, `deploy/baseline@3ed49c3`, P1 `23dea90`, `refactor/strategy-math@6d6790f`, or PR #3 `2ffb44b`. PR #3 exists **only on GitHub**: it was never fetched and is in no bundle. A fresh verified bundle, taken after an owner-approved `git fetch`, is a hard precondition for any deletion. Off-host backup is still an owner-blocked item.
4. **No server-side guard on `main`.**
   - No protection and no rulesets.
   - The host holds a **write** deploy key (`server-signalbot-rw`).
   - The paused `cron-signal-bot-review.sh` would commit and push directly on the checked-out branch if re-enabled.
5. **Host dependencies are paths, not branch names.**
   - Compose, the `data/evidence` bind mount (untracked, not ignored), the `walk_forward_audit.sh` cron and the canary-watchdog cron (untracked `.venv` inside `research/skill_application/`) all depend on the **directory** `/home/tradmin/trading-signal-bot`.
   - GitHub branch operations do not affect them.
   - Removing, re-cloning, `git clean`-ing or switching that checkout is a production change.
6. **Unsafe instructions in tracked files.** A bare `docker compose up -d` appears in `setup.sh:52`, `docs/claude/operations.md:6-8`, `CLAUDE.md:14` and elsewhere. Because `continuous_learner` has no compose profile, this would start the deliberately stopped learner (SINGLE_HOST_SAFETY §5).

### Deletion list headline (all proposals; each needs owner sign-off; §9 has the evidence)
- **Remote branches, 8, in waves:**
  - Wave A: `dev`, `feat/py312-feature-store-audit-2026-06-23`, `feat/throttle-decay-2026-08-10`, `fix/loss-streak-recovery-epoch`
  - Wave B, after the tag: `deploy/baseline-2026-09-27`, `fix/b3-fail-closed-trading-state`
  - Wave C, remote only: `integration/research-pipeline`
  - Wave E, last, after `main` is canonical: `develop`
- **Local branches:** the 10 local-only contained branches (Wave D), plus local twins of the waves above once their worktrees are released. The local `integration/research-pipeline` stays while production runs from it.
- **Conditional, not now:**
  - `docs/…` after PR #3 merges
  - P1 after its gated merge
  - `refactor/strategy-math` and `safety/disable-auto-tune` only after an owner decision **and** an `archive/*` tag
- **Tags:** none to delete.
- **Files:** 8 SAFE-TO-REMOVE via one cleanup PR on `main` after consolidation. Everything else is KEEP or NEEDS-OWNER-DECISION (evidence producers, caches, the disabled optimizer, Colab, dated migrations, stale docs).

## 1. Scope, rules and method

**Evidence sources (all read-only):**

- **Git (shared object store of all worktrees):**
  - `git --no-optional-locks` with `for-each-ref`, `branch -a -vv`, `tag -l`, `rev-list --left-right --count`, `merge-base --is-ancestor`, `cherry`, `log`, `show --stat`, `diff --stat`, `ls-tree`, `ls-files`, `grep`, `cat-file`, `worktree list`.
  - `git ls-remote origin` / `snapshot`.
  - `git bundle list-heads` on existing bundles.
- **GitHub REST, GET only:**
  - repo metadata, branches, tags, releases and pulls (`state=all`)
  - `branches/*/protection`, `rulesets`, `rules/branches/*`
  - `actions/workflows`, `actions/runs`, `actions/permissions`
  - deployments, environments, hooks, deploy keys (titles only)
  - compare endpoints and `contents?ref=`
- **Host metadata:**
  - `docker ps`, `docker image ls`, and `docker inspect --format` restricted to labels, image IDs and mounts. Container environments were never printed.
  - The crontab only through the mandated `grep -F trading-signal-bot | sed` redaction.
  - The baseline manifest files in `/home/tradmin/tsb-baseline/deploy/baseline-2026-09-27/`.
- **Code audit:** static reading of the `develop` worktree `/home/tradmin/tsb-develop` (`4e3eb0a`). This used a stdlib-only AST import-graph script kept in the auditor's scratchpad. No project code, tests, builds or package installs were run.

**Deliberately not inspected:**

- `.env` files, secrets and container environments
- sealed research outcomes: files under research data/results and any `*.jsonl`/`*.csv` evidence, listed by name/size only
- restic repositories and production databases

**Worktrees sharing one repository** (`git worktree list`, all on the single production host; see ADR-010):

| Worktree | Branch | HEAD | Role |
|---|---|---|---|
| `/home/tradmin/trading-signal-bot` | `integration/research-pipeline` | `63da7d3` | Original checkout. **Dirty**. Production compose/source dir (see §4). Do not modify. |
| `/home/tradmin/tsb-develop` | `develop` | `4e3eb0a` | Integration baseline |
| `/home/tradmin/tsb-baseline` | `deploy/baseline-2026-09-27` | `3ed49c3` | Recorded production baseline |
| `/home/tradmin/tsb-refactor` | `refactor/strategy-math` | `6d6790f` | Unreviewed refactor |
| `/home/tradmin/tsb-p1` | `feature/forward-instrumentation` | `23dea90` | P1, pushed, not merged/deployed |
| `…/scratchpad/b3-worktree` (a Claude session scratch dir under `/tmp`) | `fix/b3-fail-closed-trading-state` | `8bfca77` | B3 fix worktree. Volatile location. |

A local branch that is checked out in a worktree **cannot be deleted** until that worktree is removed. Removing worktrees is a host change and needs owner approval.

**Full SHAs used in this document:**

| Ref | Full SHA |
|---|---|
| `develop` | `4e3eb0ae82b2bf0ea7b954f00c9b8da5469a8b76` |
| `main` (= GitHub default) | `0a396c2a30d3b0d8fe4209b156ed27b89e017efc` |
| `deploy/baseline-2026-09-27` | `3ed49c306ce404359c94ee549dd24b431be2a558` |
| `fix/b3-fail-closed-trading-state` (B3) | `8bfca778b42fa5c29993d5c57bf1674ae755522f` |
| `feature/forward-instrumentation` (P1) | `23dea904a852e71c3b00414fc06a45417ada2792` |
| `refactor/strategy-math` | `6d6790f30314cb6943450c81a3bc4ecea67b7c78` |
| `safety/disable-auto-tune` | `3d1857d8e2cdec320f722f2a784a5fb3dab691ef` |
| `integration/research-pipeline` | `63da7d31daef2b952c695b256f81cf174b6451a8` |
| `docs/market-intelligence-governance-20260927` (PR #3) | `2ffb44b80b79c90c37de8f29020b94c0af949fc3` |
| `dev` (remote only; PR #2 head) | `c7e9b88e8ff2b58583dce9e52c661ef7620face3` |
| PR #1 head | `cf1b9b260dc175db9311f3f138a264e7f5e86a73` |
| `feat/py312-feature-store-audit-2026-06-23` | `d91fd500289e6bcbc969b76d84c9f3624d9eb7d4` |
| `feat/throttle-decay-2026-08-10` | `912b51aa351a646ee335e6add48e160dce0365e4` |
| `fix/loss-streak-recovery-epoch` | `05999eacf2c8fd612aadb210ee2ae1adbbb536c8` |

## 2. GitHub repository state (GET only, 2026-09-27)

| Item | Finding | Consequence for consolidation |
|---|---|---|
| Visibility | private, not archived, not a fork. Owner type User. The token has `admin` permission. | Default-branch and deletion changes are technically possible with the owner's token. They were not exercised. |
| Default branch | **`main` already** (`HEAD → 0a396c2`) | No default-branch *switch* is needed. The problem is that `main` is stale. After `develop` is merged into `main`, the default stays `main`. |
| Branches on GitHub | 13 (§3). None protected. | — |
| Branch protection / rulesets | None. `branches/{main,develop}/protection` → 404 "Branch not protected". `rulesets` → `[]`. `rules/branches/{main,develop}` → `[]`. | No server-side guard stops a direct push, force-push or deletion of `main`. Protection/rulesets on a *private* repo of a User account need a paid plan (GitHub Pro). The plan is not visible to this token, so the owner must verify it. |
| Tags / releases | **0 tags, 0 releases on GitHub.** The only tag is local: lightweight `snapshot-live-learning-0a396c2` → `0a396c2`. | No immutable rollback anchor exists in Git today. The production baseline is only protected by the *branch* `deploy/baseline-2026-09-27` (see §5 tag proposal). |
| GitHub Actions / CI | Actions enabled (`allowed_actions: all`). **0 workflows, 0 runs.** No `.github/` workflows. | No CI depends on any branch name, so branch deletion breaks no pipeline. There is also no automated test gate on PRs. |
| Deployments / environments / Pages / webhooks | none / none / none / none | Production deploys are manual on the host, not GitHub-driven. |
| Deploy keys | 1: `server-signalbot-rw`, **read_only = false** (created 2026-06-21) | The production host holds a key that can push, force-push and delete refs. Owner decision: keep it, make it read-only, or rotate it. Without branch protection this key is a risk to `main`. |
| `delete_branch_on_merge` | `false` | Proposal: set it to `true` so PR branches disappear after merge, which enforces the "temporary branches only" rule. |
| Merge methods | merge-commit, squash and rebase all allowed | For the `develop → main` consolidation PR use **"Create a merge commit"** only. Squash/rebase would create new SHAs, and the baseline `3ed49c3`, B3 `8bfca77` and all recorded SHAs would then not be reachable from `main`. |
| Pull requests | 3 in total. **#3 open, draft**, `docs/market-intelligence-governance-20260927` → `develop`. #1 (`dev`@`cf1b9b2` → `main`, merged 2026-04-08). #2 (`dev`@`c7e9b88` → `main`, merged 2026-04-08). | PR #3 targets `develop`. It must be **retargeted to `main`** before `develop` is deleted. Otherwise GitHub closes it when its base disappears. |
| Second remote `snapshot` | `github.com/baljadrawy/signal-bot-live-learning-snapshot` with `main@0a396c2` only | This is a separate repo. It is out of scope for deletion. It is already an off-repo copy of `0a396c2`. |

## 3. Branch, tag and ref inventory

Method: this section uses only `git --no-optional-locks` read-only commands on the shared object store (`/home/tradmin/trading-signal-bot/.git`) and `gh api` GET calls (`branches`, `pulls?state=all`, `compare/*`, `rules/branches/*`, `rulesets`, `branches/*/protection`). Conflict probes (`git merge-tree --write-tree`) ran with `GIT_OBJECT_DIRECTORY=<scratchpad>/mt-objs` and `GIT_ALTERNATE_OBJECT_DIRECTORIES=<common>/objects`, so the new tree objects went into the scratchpad and nothing was written to the repository's object store or refs. `develop` = `4e3eb0ae82`, `main` = `0a396c2a30`. Nothing was fetched, so the governance branch (`2ffb44b`) is not in the local object store and was inspected only through the compare API.

### (a) Summary counts

| Item | Count | Detail |
|---|---|---|
| Distinct branch names (local ∪ GitHub) | **23** | 21 local heads + 2 GitHub-only (`dev`, `docs/market-intelligence-governance-20260927`) |
| GitHub branches | **13** | All match `git ls-remote` and the local remote-tracking refs (SHA-for-SHA). Ahead/behind from the GitHub compare API equals local `rev-list` for all 12 comparable branches. |
| Local-only branches (never pushed) | **10** | `fix/fee-net-gate-2026-07-29`, `fix/measurement-layer-2026-07-15`, `fix/neutralize-4f84717-2026-07-29`, `fix/report-net-fees-2026-07-29`, `research/{evidence-capture-filter, falsification-library, flight-recorder, health-monitor, null-a-evidence-store, recorder-hardening}` |
| Branches (other than develop) **fully contained in develop** | **18** | 8 on GitHub (`main`, `dev`, `deploy/baseline-2026-09-27`, `feat/py312-feature-store-audit-2026-06-23`, `feat/throttle-decay-2026-08-10`, `fix/b3-fail-closed-trading-state`, `fix/loss-streak-recovery-epoch`, `integration/research-pipeline`) + all 10 local-only branches. `git cherry develop <ref>` = 0 `+` for every one. |
| Branches with **unique, unmerged work** | **4** | `feature/forward-instrumentation` (+1), `refactor/strategy-math` (+1), `safety/disable-auto-tune` (+1 / −44, diverged, based on `main`), `docs/market-intelligence-governance-20260927` (+21, GitHub only, PR #3) |
| Tags | **1 local, 0 on GitHub, 0 releases** | `snapshot-live-learning-0a396c2` is **lightweight** (`cat-file -t` = commit), local-only, pointing at `main`'s tip `0a396c2` |
| Remotes | 2 | `origin` = `git@github.com:baljadrawy/trading-signal-bot.git`; `snapshot` = `https://github.com/baljadrawy/signal-bot-live-learning-snapshot.git` (private repo, `main@0a396c2`, last push 2026-07-01) |
| Worktrees | 6 | 5 under `/home/tradmin`, plus 1 under a Claude session scratchpad in `/tmp` (see (d)) |
| PRs | 3 | #1 and #2 (`dev`→`main`) merged 2026-04-08; #3 open **draft** (`docs/…`→`develop`), mergeable_state `clean` |
| Branch protection / rulesets | **none** | `branches/{main,develop}/protection` → 404 "Branch not protected"; `rulesets` = `[]`; `rules/branches/{main,develop}` = `[]` |
| Default branch | `main@0a396c2` | 44 commits behind `develop`, 0 ahead |

### (b) Full branch matrix

Columns: **dev b/a** and **main b/a** = `git rev-list --left-right --count <base>...<ref>` (commits behind / commits ahead). **⊂dev** and **⊂main** = `git merge-base --is-ancestor <ref> <base>`. **cherry +/−** = `git cherry develop <ref>`. **P0 bundle** = whether the tip is reachable from the heads in `/home/tradmin/backups/tsb-phase0-20260927/git/trading-signal-bot-all-refs-20260927.bundle` (created 17:50).

| Ref | SHA | Committer date | Author | GitHub | Upstream | Worktree | dev b/a | main b/a | ⊂dev | ⊂main | cherry +/− | P0 bundle | Class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `develop` | 4e3eb0ae82 | 2026-09-27 18:27 +0200 | Signal Bot Optimizer | y | none | /home/tradmin/tsb-develop | 0/0 | 0/44 | Y | N | 0/0 | **NO** (8 commits after bundle) | integration baseline |
| `main` | 0a396c2a30 | 2026-06-28 05:50 +0200 | Signal Bot Optimizer | y (default) | origin/main | — | 44/0 | 0/0 | Y | Y | 0/0 | yes | contained, stale default |
| `deploy/baseline-2026-09-27` | 3ed49c306c | 2026-09-27 18:23 +0200 | Signal Bot Optimizer | y | none | /home/tradmin/tsb-baseline | 7/0 | 0/37 | Y | N | 0/0 | **NO** | contained, rollback anchor |
| `fix/b3-fail-closed-trading-state` | 8bfca778b4 | 2026-09-27 12:57 +0200 | Signal Bot Optimizer | y | none | /tmp/claude-1000/…/scratchpad/b3-worktree | 8/0 | 0/36 | Y | N | 0/0 | yes | contained, B3 deployed overlay source |
| `fix/loss-streak-recovery-epoch` | 05999eacf2 | 2026-08-26 08:21 +0200 | Signal Bot Optimizer | y | origin/… | — | 9/0 | 0/35 | Y | N | 0/0 | yes | contained |
| `integration/research-pipeline` | 63da7d31da | 2026-08-19 10:37 +0200 | Signal Bot Optimizer | y | none | **/home/tradmin/trading-signal-bot (production checkout, dirty)** | 10/0 | 0/34 | Y | N | 0/0 | yes | contained, deployed image source |
| `feat/throttle-decay-2026-08-10` | 912b51aa35 | 2026-08-10 23:26 +0200 | Signal Bot Optimizer | y | origin/… | — | 18/0 | 0/26 | Y | N | 0/0 | yes | contained |
| `fix/report-net-fees-2026-07-29` | f9dbc77587 | 2026-07-29 02:48 +0200 | Signal Bot Optimizer | **n (local-only)** | none | — | 19/0 | 0/25 | Y | N | 0/0 | yes | contained |
| `fix/neutralize-4f84717-2026-07-29` | cdd3450a1d | 2026-07-29 02:19 +0200 | Signal Bot Optimizer | **n** | none | — | 20/0 | 0/24 | Y | N | 0/0 | yes | contained |
| `fix/fee-net-gate-2026-07-29` | 1d090be398 | 2026-07-29 01:31 +0200 | Signal Bot Optimizer | **n** | none | — | 21/0 | 0/23 | Y | N | 0/0 | yes | contained |
| `fix/measurement-layer-2026-07-15` | c2725a9635 | 2026-07-15 12:21 +0200 | Signal Bot Optimizer | **n** | none | — | 22/0 | 0/22 | Y | N | 0/0 | yes | contained |
| `research/evidence-capture-filter` | 928ff1a079 | 2026-06-28 20:42 +0200 | Signal Bot Optimizer | **n** | none | — | 37/0 | 0/7 | Y | N | 0/0 | yes | contained |
| `research/recorder-hardening` | f72d623a8d | 2026-06-28 20:32 +0200 | Signal Bot Optimizer | **n** | none | — | 38/0 | 0/6 | Y | N | 0/0 | yes | contained |
| `research/flight-recorder` | 7b45a8f2db | 2026-06-28 20:25 +0200 | Signal Bot Optimizer | **n** | none | — | 39/0 | 0/5 | Y | N | 0/0 | yes | contained |
| `research/null-a-evidence-store` | 2ec84fd37e | 2026-06-28 19:42 +0200 | Signal Bot Optimizer | **n** | none | — | 41/0 | 0/3 | Y | N | 0/0 | yes | contained |
| `research/health-monitor` | 5157ca9b59 | 2026-06-28 19:23 +0200 | Signal Bot Optimizer | **n** | none | — | 42/0 | 0/2 | Y | N | 0/0 | yes | contained |
| `research/falsification-library` | bf7b0a1dc4 | 2026-06-28 19:02 +0200 | Signal Bot Optimizer | **n** | none | — | 43/0 | 0/1 | Y | N | 0/0 | yes | contained |
| `feat/py312-feature-store-audit-2026-06-23` | d91fd50028 | 2026-06-23 14:15 +0200 | Signal Bot Optimizer | y | origin/… | — | 63/0 | 19/0 | Y | **Y** | 0/0 | yes | contained (in main too) |
| `dev` (GitHub only; local `origin/dev`) | c7e9b88e8f | 2026-04-08 14:07 +0300 | baljadrawy | y | — | — | 189/0 | 145/0 | Y | **Y** | 0/0 | yes (`refs/remotes/origin/dev`) | contained (in main too); PR #1/#2 head |
| `feature/forward-instrumentation` (P1) | 23dea904a8 | 2026-09-27 22:27 +0200 | Signal Bot Optimizer | y | origin/… | /home/tradmin/tsb-p1 | 0/**1** | 0/45 | **N** | N | **1**/0 | **NO** | **unique, unmerged** |
| `refactor/strategy-math` | 6d6790f303 | 2026-09-27 18:28 +0200 | Signal Bot Optimizer | y | none | /home/tradmin/tsb-refactor | 0/**1** | 0/45 | **N** | N | **1**/0 | **NO** | **unique, unmerged** |
| `safety/disable-auto-tune` | 3d1857d8e2 | 2026-06-28 18:55 +0200 | Signal Bot Optimizer | y | none | — | **44/1** | 0/1 | **N** | N | **1**/0 | yes | **unique, diverged** |
| `docs/market-intelligence-governance-20260927` | 2ffb44b80b | 2026-09-27 20:52 UTC | Basim AlThobaiti | **y (GitHub only, not fetched)** | — | — | 0/**21** (API) | 0/65 (API) | N | N | n/a (21 docs commits) | **NO** | **unique, unmerged (PR #3)** |
| tag `snapshot-live-learning-0a396c2` (lightweight, local-only) | 0a396c2a30 | 2026-06-28 05:50 +0200 | Signal Bot Optimizer | **n** (tag not on origin) | — | — | 44/0 | 0/0 | Y | Y | 0/0 | yes (also in `/home/tradmin/backups/signal-bot-live-learning-0a396c2.bundle`) | archival label |
| PR #1 head `cf1b9b260d` | cf1b9b260d | 2026-04-08 13:16 +0300 | baljadrawy | `refs/pull/1/head` | — | — | 190/0 | 146/0 | Y | Y | 0/0 | yes | merged (merge commit 7fc4a7c35c ⊂ main, develop) |
| PR #2 head `c7e9b88e8f` | c7e9b88e8f | 2026-04-08 14:07 +0300 | baljadrawy | `refs/pull/2/head` | — | — | 189/0 | 145/0 | Y | Y | 0/0 | yes | merged (merge commit c7b5ecbc3c ⊂ main, develop) |

First-parent lineage of `main..develop` (44 commits, 1 merge): `develop 4e3eb0a` ← 6 research/docs commits (18:27) ← `3ed49c3 deploy/baseline` ← `8bfca77 fix/b3` ← `05999ea fix/loss-streak` ← `63da7d3 integration/research-pipeline` ← … ← `f9dbc77`, `cdd3450`, `1d090be`, `c2725a9` (the local-only fixes) ← … ← `4f84717` ← `main 0a396c2`. The six `research/*` branches sit on the June 28 side branch that was merged into this history.

### (c) Review of each unmerged branch

#### C1. `feature/forward-instrumentation` @23dea904a852 (P1). Unique, not deployed.
- **Unique commit:** `23dea90` (2026-09-27 22:27) "feat(p1): forward-trading instrumentation — evidence recorder v2 (default off)". Parent = `develop` (0 behind).
- **Diffstat:** 22 files, +3163/−13. Runtime files: `analyzer/main.py` (+55), `analyzer/technical_analyzer.py` (+5), `signal_engine/main.py` (+116), `signal_engine/signal_logic.py` (+132), `telegram/main.py` (+74), `trade_tracker/main.py` (+200), `shared/config.py` (+12), **`docker-compose.yml` (+8: a `./data/evidence_v2` bind mount for analyzer, signal_engine, trade_tracker and telegram)**. New files: `shared/evidence_v2.py` (630), `research/evidence_v2/{__init__,reconcile}.py` (351), `docs/evidence_v2/{EVENT_SCHEMA,OPERATIONS}.md`, and 9 test files (`tests/test_evidence_v2_*.py`, `tests/test_decision_parity_before_after.py`, `tests/evidence_v2_fakes.py`, `tests/bench_evidence_v2.py`).
- **What it does** (commit body and config diff): point-in-time decision events controlled by `EVIDENCE_V2_ENABLED`, which defaults to `false`. Seven more `EVIDENCE_V2_*` settings control the directory, queue, batch, flush, fsync, cache and stats. The recorder writes JSONL under `data/evidence_v2/<service>/` and leaves the v1 recorder untouched. The commit states: no DB schema, migration, strategy, risk or B3 change. It includes before/after decision-parity tests against develop.
- **Already in develop in another form?** No. `git grep evidence_v2 develop` returns 0 hits. The v1 flight recorder (`research/flight-recorder` lineage) is in develop, and P1 is additive to it.
- **Lost if deleted:** the whole P1 implementation. It exists only on GitHub and in the local object store, **not in the Phase-0 bundle**. The external report and evidence are in `/home/tradmin/backups/tsb-p1-instrumentation-20260927/` (report, test evidence, MANIFEST), but that directory holds no git objects.
- **Interactions** (merge-tree probes, scratch objects only): P1 × `refactor/strategy-math` gives a **content conflict in `analyzer/technical_analyzer.py`**, because both edit the import block near `from shared.retry_utils import format_error`. P1 × `safety/disable-auto-tune` gives a **content conflict in `shared/config.py`**. P1 × PR #3 has no file overlap.
- **Recommendation: KEEP-until-owner-review, then MERGE via PR (never a local merge)**, only after the release gates and separate owner approval (ADR-002, SINGLE_HOST_SAFETY §7). The `docker-compose.yml` change means that merging and then updating the production checkout changes the live compose file. Treat it as a deployment change. Do not delete the branch before the merge.

#### C2. `refactor/strategy-math` @6d6790f30314. Unique, unreviewed, not deployed.
- **Unique commit:** `6d6790f` (2026-09-27 18:28) "refactor(analyzer): route indicators and levels through shared.strategy_math". Its own message says it is UNREVIEWED and NOT DEPLOYED and should not be merged until a parity test against the deployed analyzer passes (image `ce305ecd`, commit `63da7d3`). It reports the suite passing (292 passed, 21 skipped).
- **Diffstat:** 1 file, `analyzer/technical_analyzer.py` +7/−139.
- **Call sites changed:** `TechnicalAnalyzer._calculate_indicators(df)` becomes `calculate_production_indicators(df, production_indicator_params(config))`. `TechnicalAnalyzer._calculate_levels(df, timeframe, trade_type)` becomes `calculate_signal_levels(df, timeframe, trade_type, breakout_n=config.MOM_BREAKOUT_N)`. The import `from shared.signal_stop import plan_signal_stop` moves into `shared/strategy_math.py`. `import ta` stays, because it is still used by `_raw_features` (CCI, Williams %R, ROC, MFI, CMF). The only caller is `analyze()`: `df = self._calculate_indicators(df)` … `levels = self._calculate_levels(df, tf, trade_type)`.
- **Static numeric-equivalence review** (reading the code; not executed):
  - Indicators use the same `ta` classes and parameters (RSI, MACD, EMA 20/50/200, BB, ATR, ADX(14), StochRSI, OBV plus EMA20, volume MA and ratio). Positional and keyword argument orders match the `ta` signatures.
  - Levels use the same stop formula `max(entry−1.5·ATR, 0.99·support)`, the same `0.97·entry` fallback, the same timeframe caps `{1d:.03, 4h:.05, 1h:.04, 15m:.02}`, the same `plan_signal_stop` branch for momentum/reversion with `breakout_n = MOM_BREAKOUT_N`, the same cap branch otherwise, the same targets 1.0R/1.8R/2.2R, the same T1 resistance cap (chained comparison `t1 > resistance > entry` ≡ `and`), and the same rounding and dict keys.
  - Two inline guards are dropped (`if target_2 <= target_1: target_2 = entry + risk*1.8`, and likewise for T3). They reassign the value the target already has, so they are no-ops. `entry + risk*1.0` becomes `entry + risk`, which is exact in IEEE-754.
  - **One semantic difference:** `calculate_production_indicators` does `df = df.copy()` and returns a new frame instead of mutating the input. The only caller reassigns the result, so there is no behavioural effect, only an extra DataFrame copy per analysis (CPU/memory).
  - **Assessment:** by reading, a pure extraction with equal outputs expected. This has **not been verified at runtime against the deployed image**. The commit adds no analyzer-vs-strategy_math parity test. Develop's `tests/test_research_replay_parity.py` only golden-tests `calculate_signal_levels`. Structural risk: the live analyzer would then depend on `shared/strategy_math.py`, which research code also imports (`research/foundation/replay.py`, `research/p0r.py`, and `research/foundation/contract.py` lists it as a contract file). A research-side edit would then change production behaviour. `analyzer/*` and `shared/signal_stop.py` are byte-identical between `63da7d3` (deployed source) and `develop`, so a diff against develop is also a diff against the deployed analyzer source.
- **Production-checkout finding:** the uncommitted `analyzer/technical_analyzer.py` in `/home/tradmin/trading-signal-bot` is **byte-identical to the `6d6790f` blob** (hash-object comparison, see (d)3). Rebuilding the analyzer image from the production checkout would therefore ship this unreviewed refactor.
- **Lost if deleted:** one small commit. A copy of the content also exists as the dirty working-tree file in the production checkout. Not in the Phase-0 bundle.
- **Recommendation: NEEDS-OWNER-DECISION (KEEP until review).** Option A: review plus a runtime parity test against `63da7d3`/image `ce305ecd`, then a PR. It conflicts with P1 in the import block, so it must be rebased after whichever lands first. Option B: reject, preserve as an archive tag `archive/refactor-strategy-math-6d6790f`, then delete. Never delete without a tag.

#### C3. `safety/disable-auto-tune` @3d1857d8e2cd. Unique, diverged.
- **Base:** merge-base with develop = `0a396c2` (= `main`). 1 ahead, 44 behind develop (GitHub: `diverged`, ahead 1, behind 44).
- **Unique commit:** `3d1857d` (2026-06-28 18:55) "safety(optimizer): gate recent-trade auto-tuner behind ENABLE_AUTO_TUNE (default off)". Files: `optimizer/tuner.py` M +43, `shared/config.py` M +7, `tests/test_optimizer_main.py` A +39, `tests/test_tuner_killswitch.py` A +81 (+170 total). The bypass returns `[]` without writing settings and emits telemetry (read-only SELECT, `AUTO_TUNE_BYPASS_COUNT`). Rollback per the commit: `ENABLE_AUTO_TUNE=true`.
- **Already in develop?** No. `git grep ENABLE_AUTO_TUNE develop` hits only `DEV_LOG.md:11`, which records "PR#1 … **غير مدموج**" (not merged). Develop's `optimizer/main.py:85` still calls `tuner.auto_tune(stats)` unconditionally. The mitigation in develop is operational only: the `optimizer` compose service is `profiles: ["disabled"]`. Neither test file exists in develop or main.
- **Conflict probe:** `merge-tree develop 3d1857d` gives `optimizer/tuner.py` auto-merged and **`shared/config.py` CONFLICT (content)**. Develop's only change to `tuner.py` since the base is `c4cae2b` (removes `_ensure_settings_table`, −24).
- **Lost if deleted without a tag:** the only implementation of the auto-tune kill-switch and its tests. The tip is in the Phase-0 bundle.
- **Recommendation: NEEDS-OWNER-DECISION.** (a) Port it onto current develop/main as a fresh PR branch: resolve the `shared/config.py` conflict and re-run its tests. This is ADR/redesign "PR#1", and it adds a code-level guard on top of the compose-profile guard. (b) Retire it: create `archive/safety-disable-auto-tune-3d1857d`, verify, then delete the branch. Do not merge the stale branch directly, because it is 44 commits behind.

#### C4. `docs/market-intelligence-governance-20260927` @2ffb44b80b79. GitHub only, PR #3 draft → develop.
- **Compare API:** merge base `4e3eb0ae82` (= develop tip). Ahead 21, behind 0 vs develop; ahead 65 vs main. PR #3 is `draft`, `mergeable: true`, `mergeable_state: clean`, `rebaseable: true`, 0 comments or reviews. User `baljadrawy`; commits authored "Basim AlThobaiti" (per-file web-UI commits, 19:58–20:52 UTC).
- **Files (docs only, +287/−32):** `CLAUDE.md` M (+48/−32: governance override header, shared-host rule, single-canonical-branch rule) and new files `docs/product/{DECISION_LOG, DEPENDENCY_AUDIT_2026-09-27_INITIAL, DEPENDENCY_POLICY, IDEA_REGISTER, IMPLEMENTATION_ROADMAP, PROJECT_CHARTER, REPOSITORY_CONSOLIDATION, SINGLE_HOST_SAFETY}.md`. No code, compose or CI files.
- **Lost if deleted:** the owner's governance record (ADR-001…011, charter, consolidation plan). It exists **only on GitHub**: not fetched locally and not in any bundle.
- **Recommendation: MERGE-via-PR-then-delete.** Owner marks the PR ready and merges it, with squash-merge optional to collapse the 21 micro-commits. This should happen **before** `develop` is promoted to `main`, or the PR should be retargeted to `main` if `develop` is promoted first. Before any consolidation step, mirror it locally or in a bundle, because it is currently a single-copy (GitHub-only) ref.

### Branches fully contained in develop (18). Deleting any of these loses no commits.
Every tip is an ancestor of `develop`, so all its commits stay reachable after the branch name is removed. Each line lists: SHA, last subject, and the obstacle to deletion.
- `main` 0a396c2: learner/digest fix. Default branch: must be **fast-forwarded, not deleted**. It is an ancestor of develop, so an FF to develop is possible (0 unique commits).
- `dev` (GitHub only) c7e9b88: "🐛 إصلاح 3 أخطاء في البناء". Head of the merged PRs #1/#2, also contained in `main`. No obstacle.
- `deploy/baseline-2026-09-27` 3ed49c3: records the deployed production baseline. **The rollback anchor. Needs an annotated tag before deletion, and it is checked out in the `/home/tradmin/tsb-baseline` worktree.** Not in the Phase-0 bundle. **Name hazard:** the branch name equals the tracked directory `deploy/baseline-2026-09-27/`, so `git log deploy/baseline-2026-09-27` fails with "ambiguous argument: both revision and filename". Use `refs/heads/…` or `--`, and choose a tag name that differs from the path.
- `fix/b3-fail-closed-trading-state` 8bfca77: B3 fail-closed. Source of the deployed B3 overlay. Checked out in a worktree under a **Claude session scratchpad in `/tmp`** (`…/f9e8015a…/scratchpad/b3-worktree`), which is ephemeral. That worktree must be removed or pruned before local branch deletion.
- `fix/loss-streak-recovery-epoch` 05999ea: recoverable loss-streak epoch. No obstacle.
- `integration/research-pipeline` 63da7d3: route entries by validated regime. **Checked out in the production checkout** `/home/tradmin/trading-signal-bot` and the source of the deployed images. The local branch cannot be deleted while it is checked out there, and switching that checkout is a production-host action that needs owner approval. The GitHub copy can be deleted independently once the deployment docs reference a tag.
- `feat/throttle-decay-2026-08-10` 912b51a: learner stale-throttle expiry. No obstacle.
- `feat/py312-feature-store-audit-2026-06-23` d91fd50: docs(CLAUDE) after the pandas3 upgrade. Also contained in `main`. No obstacle.
- Local-only, contained, and **also in the Phase-0 bundle**, so there are two copies (object store and bundle) and deletion loses nothing:
  - `fix/report-net-fees-2026-07-29` f9dbc77 (NET-of-fee /stats and /trades)
  - `fix/neutralize-4f84717-2026-07-29` cdd3450
  - `fix/fee-net-gate-2026-07-29` 1d090be
  - `fix/measurement-layer-2026-07-15` c2725a9
  - `research/evidence-capture-filter` 928ff1a
  - `research/recorder-hardening` f72d623
  - `research/flight-recorder` 7b45a8f
  - `research/null-a-evidence-store` 2ec84fd
  - `research/health-monitor` 5157ca9
  - `research/falsification-library` bf7b0a1

  All have `git cherry develop` with 0 `+`, and their tips appear on develop's first-parent or merged history. Deleting them loses only the ref label and its reflog.

Recovery for any deleted contained branch (owner-run, later): `git branch <name> <sha>`, or `git push origin <sha>:refs/heads/<name>`. From the bundle: `git fetch <bundle> refs/heads/<name>:refs/heads/<name>`.

### (d) Notes

1. **`main` / default branch:** 0 unique commits vs develop (`rev-list` 44/0, `merge-base --is-ancestor main develop` = true, GitHub compare `behind 44`). A PR `develop → main` would be a fast-forward-able superset. There is no protection, no rulesets, no Actions workflows, no environments and no deployments on GitHub, so changing the default branch breaks no CI (verify the deployment docs separately). `delete_branch_on_merge` is `false`, so merged PR branches currently survive; the owner may consider enabling it. That is a settings change, not part of this audit.
2. **PR heads:** `refs/pull/1/head` = cf1b9b2 and `refs/pull/2/head` = c7e9b88. Both PRs merged on 2026-04-08; merge commits `7fc4a7c35c` and `c7b5ecbc3c` are ancestors of both `main` and `develop`. GitHub keeps `refs/pull/*` even after `dev` is deleted, and they cannot be deleted by users.
3. **Dirty production checkout** (`/home/tradmin/trading-signal-bot`, branch `integration/research-pipeline` @63da7d3): `git status --porcelain=v1 | wc -l` = **111** (224 with `-uall`: 7 modified tracked, 217 untracked files).
   - **7 modified tracked files, all byte-identical to committed blobs** (`hash-object` vs `rev-parse <ref>:<path>`):
     - `analyzer/technical_analyzer.py` (+/−146) = **`refactor/strategy-math` only**
     - `telegram/main.py` (+104) and `trade_tracker/main.py` (30) = develop = baseline 3ed49c3 = B3 8bfca77
     - `database/init.sql` (+22) and `shared/schema.py` (2) = develop = baseline = B3
     - `.gitignore` (+6) and `docs/canary_state.md` (+29) = develop (not baseline)

     No uncommitted tracked change is unique to the production checkout.
   - **217 untracked files:**
     - 121 byte-identical to develop blobs: `research/skill_application/` 56, `research/foundation/` 16, `research/governance/` 13, `research/data_governance/` 13, `tests/` 9, `docs/` 7, `research/*.py|sql|json` 4, `shared/` 2 (`strategy_math.py`, `risk_epoch.py`), `database/migrations/` 1.
     - 5 exist in develop but were not compared, because they are sealed/evidence paths: `research/governance/{contamination_registry,hypotheses,validation_usage}.jsonl` and `research/{datasets,runs}/.gitkeep`.
     - **91 exist only on disk and in no git ref:** 72 `data/evidence/*.jsonl` (v1 flight-recorder evidence, 2026-06-29 onward) and 19 `research/skill_application/**/*.csv|*.jsonl` research data outputs. Not opened. These are evidence data, not code; they are protected only by host backups (restic), not git. **There are zero untracked code files unique to the production checkout.**
4. **Snapshot tag and remote:** `snapshot-live-learning-0a396c2` is a lightweight local tag on `main`'s tip. It is not on origin. The same commit is preserved in the separate private repo `baljadrawy/signal-bot-live-learning-snapshot` (`main@0a396c2`) and in `/home/tradmin/backups/signal-bot-live-learning-0a396c2.bundle` (contains only this tag). It stays reachable from develop and main after consolidation, so no action is required. Optionally re-create it as an annotated `archive/` tag on origin if the owner wants it on the canonical repo. The extra `snapshot` remote (HTTPS) is an archival mirror; owner decides whether to keep it configured, to avoid accidental pushes.
5. **Bundle coverage gap:** the Phase-0 bundle (17:50) does **not** contain `develop@4e3eb0a` (missing 8 commits: `3ed49c3`, `39d701d`, `d221514`, `224bfa6`, `2cd9e68`, `b1c804d`, `970dda9`, `4e3eb0a`), `deploy/baseline@3ed49c3`, `refactor/strategy-math@6d6790f`, `feature/forward-instrumentation@23dea90`, or `docs/…@2ffb44b` (never fetched). The bundle's `refs/remotes/origin/integration/research-pipeline` is `c4a623c`, a pre-sync value. **Before any branch deletion, a new all-refs bundle should be taken after fetching PR #3 in an owner-approved step, and verified with `git bundle verify` and `list-heads`.**
6. **Worktree dependencies that block local branch deletion:** `develop` (tsb-develop), `deploy/baseline-2026-09-27` (tsb-baseline), `feature/forward-instrumentation` (tsb-p1), `refactor/strategy-math` (tsb-refactor), `integration/research-pipeline` (production checkout: do **not** touch without owner approval), `fix/b3-fail-closed-trading-state` (`/tmp` scratchpad worktree). `git branch -d/-D` refuses to delete a branch that is checked out in any worktree.

## 4. Production deployment, rollback anchors, schedules and backups

Method: `git --no-optional-locks` read-only commands on the shared repository, `docker ps`/`docker inspect --format` (labels, image IDs and mounts only; no env), `docker image ls/inspect` (labels only), redacted `crontab -l | grep`, `systemctl list-timers`, `git bundle list-heads/verify`, `sha256sum`, and GitHub GET `compare`/`contents`. Nothing was written. No `.env`, container env, evidence data (`*.jsonl`/`*.csv`/`data/`/`results`) or restic repository was opened.

---

### 4.1 Production baseline and overlay parity

#### Recorded baseline
| Item | Value |
|---|---|
| Baseline record branch | `deploy/baseline-2026-09-27` @ `3ed49c306ce404359c94ee549dd24b431be2a558` (2026-09-27 18:23 +0200) |
| Parent (B3 fix) | `fix/b3-fail-closed-trading-state` @ `8bfca778b42fa5c29993d5c57bf1674ae755522f`. `3ed49c3^ == 8bfca77`. |
| What 3ed49c3 adds | 12 new files, all under `deploy/baseline-2026-09-27/` (README, `DEPLOYED_MANIFEST.json`, `deployed_files.json`, 6× `config/*.nonsecret.json`, 3× `unmatched/...` evidence copies). No code change. |
| Ancestry | `8bfca77` and `3ed49c3` are **ancestors of develop `4e3eb0a`** and **NOT ancestors of main `0a396c2`**. |
| Mode/state recorded | PAPER_ONLY; HALTED (`risk:loss_streak_halt`, decision id 29415). The README states **reproducibility is NOT PROVEN**: mixed builds plus single-file overlays. |
| develop vs 3ed49c3 | 7 commits (all 2026-09-27 18:27, research/docs only): `39d701d` `d221514` `224bfa6` `2cd9e68` `b1c804d` `970dda9` `4e3eb0a`. Under the service directories, shared/, database/, compose, Dockerfiles and requirements, the only change is a new `shared/strategy_math.py`. It is imported only by `research/*` and tests, not by any service. A rebuild would copy it into the images through `COPY shared/`, where it would be inert. |

**Conclusion.** The known-good production code baseline is **`3ed49c3`, which records B3 `8bfca77`**. For every deployed file path, develop `4e3eb0a` equals `3ed49c3` and `8bfca77`: 59 of 75 unique (path, blob) pairs match all three. develop therefore adds nothing to the deployed code paths.

#### Running images vs. manifest
All 7 service container image IDs equal `DEPLOYED_MANIFEST.json` exactly:

| Service | Image ID | Manifest match | Image revision label |
|---|---|---|---|
| scanner | 9b0b53a6a799 | yes | `unknown` |
| analyzer | ce305ecd7760 | yes | `unknown` |
| signal_engine | b3d4b6236654 | yes | `unknown` |
| trade_tracker | 2b59c6a164c0 | yes | `unknown` |
| telegram | b84d3d1528a0 | yes | `unknown` |
| claude_review | 8bca25750c77 | yes | `c4cae2b-dirty` |
| continuous_learner (exited) | d1aa69bde63f | yes | `c4cae2b-dirty` |

No image carries a clean git SHA. The Dockerfiles default `BUILD_REVISION=unknown`, and only `setup.sh` exports `git rev-parse HEAD`. Image provenance therefore rests on `deployed_files.json`, not on labels.

#### Is develop's tree equal to production code? (190 deployed files, 7 containers)
| Service | Equal to develop | Files that differ (deployed version matches commit …) |
|---|---|---|
| trade_tracker | **29/29** | – (B3 overlay) |
| telegram | **28/28** | – (B3 overlay) |
| signal_engine | 35/37 | `shared/trading_state.py`@05999ea (pre-B3), `shared/schema.py`@63da7d3 |
| analyzer | 26/28 | `shared/trading_state.py`@05999ea (pre-B3, not called per README), `shared/schema.py`@63da7d3 |
| scanner | 18/23 | `shared/config.py`@7bf6214, `shared/schema.py`@7bf6214, `shared/triple_barrier.py`@7bf6214, `shared/macro_context.py`@c4a623c (blob also equals main's), `shared/telegram_messages.py`@**NO COMMIT** |
| claude_review | 11/17 | `shared/config.py`@c4cae2b, `shared/macro_context.py`@c4a623c, `shared/triple_barrier.py`@14fc775, `shared/candle.py`@14fc775, `shared/schema.py`@**NO COMMIT**, `shared/learning_governance.py`@**NO COMMIT** |
| continuous_learner (stopped) | 20/28 | `signal_engine/signal_logic.py`@605a962, `signal_engine/main.py`@c4a623c, `shared/config.py`@14fc775, `shared/macro_context.py`@c4a623c, `shared/triple_barrier.py`@14fc775, `shared/candle.py`@14fc775, `shared/schema.py`@7bf6214, `research/strategy_performance_review.py`@14fc775 |

- In total, 23 of the 190 file records differ from develop. None of them match develop, P1, the refactor branch or main, except `macro_context.py`, which matches main.
- The older source commits `05999ea 63da7d3 c4a623c 7bf6214 605a962 14fc775 c4cae2b` are all **ancestors of develop** and none are ancestors of main. Every deployed file with a git source is therefore reachable from develop's history.
- The 3 "NO COMMIT" files (blobs `a8cf860f`, `88e01969`, `df6fcc1f`) exist in git **only** as the evidence copies under `deploy/baseline-2026-09-27/unmatched/...`, added by `3ed49c3` and present on develop, P1 and refactor but not on main. Their sha256 values match the manifest (`640e134f…`, `9d43e9d4…`, `14540f16…`).
- **Result:** develop's code is identical to production only for tracker and telegram. The other 5 images run older blobs and 3 unversioned files. A clean rebuild from develop or main would therefore change the scanner, analyzer, signal_engine and claude_review code. **Deleting any ref must keep develop's history reachable** (via main after the merge, or via a tag), because the deployed blobs are only reachable through it.

---

### 4.2 Running containers and source directories

| Container | Status | Compose project / service | Mounts |
|---|---|---|---|
| trading_scanner | Up (healthy) | trading-signal-bot / scanner | volume logs_data |
| trading_telegram | Up (healthy) | trading-signal-bot / telegram | volume logs_data |
| trading_tracker | Up (healthy) | trading-signal-bot / trade_tracker | volume logs_data |
| trading_signal_engine | Up (healthy) | trading-signal-bot / signal_engine | logs_data, models_data, **bind `/home/tradmin/trading-signal-bot/data/evidence` → `/app/data/evidence`** |
| trading_analyzer | Up (healthy) | trading-signal-bot / analyzer | logs_data, models_data |
| trading_claude_review | Up (healthy) | trading-signal-bot / claude_review | logs_data, bind `~/.claude` and `~/.claude.json` (ro in compose) |
| trading_continuous_learner | Exited (143), about 5 weeks | trading-signal-bot / continuous_learner | – |
| postgres | Up (healthy) | **shared-postgres** (`/home/tradmin/shared-postgres/docker-compose.yml`) | volume `trading-signal-bot_postgres_data` |

- **The production compose working directory is `/home/tradmin/trading-signal-bot`**, the original worktree on `integration/research-pipeline` @63da7d3 (dirty). Its config file is `/home/tradmin/trading-signal-bot/docker-compose.yml`, which is byte-identical to the compose file at develop, 3ed49c3, 8bfca77 and HEAD, and differs from main.
- **Live dependency on a worktree:** signal_engine bind-mounts `./data/evidence`, resolved inside the original worktree. That directory is **untracked and not ignored** (`??`). `git clean -fdx`, removing the worktree, or re-cloning would break or destroy the production mount source. The worktree directory, not the branch, is the production dependency. Moving compose to another checkout requires moving this path first.
- **Dirty state of the production checkout** (7 tracked files modified, names only). `.gitignore`, `database/init.sql`, `docs/canary_state.md`, `shared/schema.py`, `telegram/main.py` and `trade_tracker/main.py` equal develop. **`analyzer/technical_analyzer.py` equals `refactor/strategy-math` @6d6790f**: the unreviewed analyzer rewiring (+7/−139 lines) is sitting uncommitted in the production checkout. The untracked `shared/strategy_math.py` equals develop. The running analyzer image does **not** contain this change (its deployed blob equals develop/8bfca77). **Risk:** any `docker compose build` (bare or `analyzer`) from the production checkout would ship unreviewed refactor code.
- Git refuses to delete a local branch that is checked out in a worktree. Current pins: `integration/research-pipeline` (original, production compose dir), `deploy/baseline-2026-09-27` (`/home/tradmin/tsb-baseline`), `develop` (`/home/tradmin/tsb-develop`), `feature/forward-instrumentation` (`/home/tradmin/tsb-p1`), `refactor/strategy-math` (`/home/tradmin/tsb-refactor`), and `fix/b3-fail-closed-trading-state` (the `/tmp/.../scratchpad/b3-worktree`). Remote deletion is independent of these pins.

---

### 4.3 Docker rollback anchors (Docker tags, not git)

| Tag | Image ID | Created | Revision label |
|---|---|---|---|
| `b3-rollback/scanner:pre-b3` | 4d59ba3d6e79 | 2026-08-18 | unknown |
| `b3-rollback/telegram:pre-b3` | fb0ef1b9097a | 2026-08-26 | unknown |
| `b3-rollback/trade_tracker:pre-b3` | c60cac87920a | 2026-08-26 | unknown |
| `trade_tracker:pre-risk1-rollback` | d291f64e0795 | 2026-08-19 | unknown |
| `telegram:pre-risk1-rollback` | ab4bc1077b6c | 2026-08-19 | unknown |
| `b3prep-20260927T120659/{scanner,telegram,tracker}:candidate` | = running 9b0b53a6a799 / b84d3d1528a0 / 2b59c6a164c0 | 2026-09-27 | unknown |

Other bot-labelled images:
- `trading-signal-bot-optimizer:latest` 374fcce71a61 (2026-06-23; no container; the compose profile is `disabled`).
- Research/test images `r1b-base:analyzer-ce305ecd` (same ID as the running analyzer), `r1b-replay:analyzer-ce305ecd-pyarrow` 923f43cacb83 and `tsb-sync-test:pytest` 38cb032c4e48.

All 5 rollback anchors plus the 7 service images and 3 candidate tags (15 tags, 12 images) are in `/home/tradmin/backups/tsb-phase0-20260927/images/trading-signal-bot-images-20260927.tar`. I recomputed its sha256 (`2b8b3f41…`), which matches `MANIFEST-INDEX.txt` and the `.tar.sha256` file. Git branch cleanup does not affect these anchors. **Keep them. Never run `docker image prune -a` during cleanup.**

---

### 4.4 Scheduled jobs (redacted) and their repository dependencies

User crontab, filtered by `trading-signal-bot` and `signal` (the `tsb-` filter matched nothing):
```
# [PAUSED 2026-07-01 for Canary Phase A — re-enable after canary] 0 */12 * * * /home/tradmin/.claude/cron-signal-bot-review.sh
30 */12 * * * /usr/bin/env bash /home/tradmin/trading-signal-bot/research/walk_forward_audit.sh >> /home/tradmin/trading-signal-bot/research/walk_forward_audit.log 2>&1
*/30 * * * * /home/tradmin/trading-signal-bot/research/skill_application/.venv/bin/python /home/tradmin/canary_watchdog.py >> /home/tradmin/canary_watchdog.log 2>&1  # CANARY_PHASE_A_WATCHDOG
```
There are no systemd units or timers for the bot. User timers contain only `launchpadlib-cache-clean`, and system timers are OS defaults.

| Job | Depends on | Tracked in develop / main | Branch dependency |
|---|---|---|---|
| walk_forward_audit (active, every 12h) | Script at `/home/tradmin/trading-signal-bot/research/walk_forward_audit.sh`; writes its log into that worktree; runs `docker exec … psql` on the DB container; reads `../.env` only with `--telegram`, which cron does not pass | Y / Y. Blob `bc295c12` is identical on develop, main, integration and the original worktree file. | **The original worktree path**, not a branch name. Works on any branch that keeps the file. |
| canary watchdog (active, every 30 min) | Interpreter `/home/tradmin/trading-signal-bot/research/skill_application/.venv` (ignored by `.gitignore:57`, exists only in the original worktree); script `/home/tradmin/canary_watchdog.py` outside the repo; the script's `REPO=/home/tradmin/trading-signal-bot` reads `.env` and `data/evidence/_telemetry.json` and calls `docker inspect trading_signal_engine` | The host script is byte-identical (`d36ab2c1`) to `research/ops/canary_watchdog.py` on develop, integration, baseline and P1. **Absent on main.** | **The original worktree path** (venv, `.env`, `data/evidence`). The message string still says "canary_watchdog @ integration/research-pipeline". |
| cron-signal-bot-review.sh (**paused**) | `/home/tradmin/.claude/cron-signal-bot-review.sh` reads `/home/tradmin/trading-signal-bot/.env`; its prompt instructs "edit code directly + commit + push to the repo" | not in repo | If re-enabled it would commit and push **on whatever branch is checked out in the original worktree**, which conflicts with the one-`main`-via-PR rule. It must be rewritten before any re-enable. |

**Implication:** both active jobs and the production compose project depend on the **directory `/home/tradmin/trading-signal-bot`**. Do not remove, re-clone or `git clean` it, or switch it away from a branch containing `research/walk_forward_audit.sh` and `research/skill_application/`, until cron and compose have been repointed. Changing the GitHub default branch or deleting remote branches does not affect them.

---

### 4.5 Branch-name references to update when `main` becomes canonical (develop tree)

False positives were excluded: `__main__`, `main()`, `main.py`, variables named `main` in research scripts, `# main` section comments, and tests importing the module `main`.

| File (develop) | Reference | Action when main is canonical |
|---|---|---|
| `GIT_GUIDE.md` (27 hits) | Old GitFlow: `main` = "stable on the Raspberry Pi", a `dev` branch, hotfix merges into main and dev, `git checkout/pull/push origin main` | Obsolete (Raspberry Pi, `dev`). Rewrite to single-main plus short-lived PR branches, or delete (owner decision). |
| `SETUP_GUIDE.md` (14 hits, lines ~192, 350–442) | Same main/dev GitFlow, `git pull origin main` | Rewrite the branch section. |
| `docs/claude/operations.md:38` | `git push origin main` (direct push) | Change to a PR-based flow; direct pushes to main are forbidden by the consolidation plan. |
| `docs/canary_runbook.md:5,8` | "Branch: `integration/research-pipeline`", "Image built from `integration/research-pipeline` (NOT `main`)" | Historical; update or annotate as superseded after consolidation. |
| `docs/canary_state.md:4` | "Branch: `integration/research-pipeline` (NOT merged to `main`)" | Update. |
| `docs/current_handoff_2026-08-17.md:8` | "Branch: `integration/research-pipeline`" | Dated handoff; leave as a historical record or annotate. |
| `DEV_LOG.md:9,12` | `integration/research-pipeline` "not merged into main" | Historical log; append a new entry rather than rewrite. |
| `research/ops/canary_watchdog.py:91` | Telegram text "canary_watchdog @ integration/research-pipeline" | Cosmetic; the host copy `/home/tradmin/canary_watchdog.py` is identical. |
| `deploy/baseline-2026-09-27/README.md:3`, `DEPLOYED_MANIFEST.json:2` | "This branch (`deploy/baseline-2026-09-27`)" | Immutable record. Keep the text; after converting the branch to a tag, note the tag name in a new doc, not in this record. |
| `CLAUDE.md` on develop | no branch references | – |
| `CLAUDE.md` on `docs/market-intelligence-governance-20260927` (GitHub only) | l.47–48 "Target one long-lived `main`…"; l.25 "isolated feature branches" | Already aligned with the target. |

Other build-provenance items: the Dockerfiles' `BUILD_REVISION` defaults to `unknown` and `docker-compose.yml:22` passes `${BUILD_REVISION:-unknown}`. Future builds from main should export `BUILD_REVISION=$(git rev-parse HEAD)`, as `setup.sh` already does.

---

### 4.6 Git config, hooks and `.github`

- **`.github/`:** absent on develop, main, integration, P1, refactor and (GitHub API 404) the docs branch. GitHub Actions reports 0 workflows and 0 runs (§2). **No CI references branch names.**
- **Hooks:** the common git dir is `/home/tradmin/trading-signal-bot/.git`; `hooks/` contains only `*.sample` files; `core.hooksPath` is unset.
- **Branch/remote config (credentials none; URLs are SSH/public HTTPS):**
  - `remote.origin.url=git@github.com:baljadrawy/trading-signal-bot.git`, fetch `+refs/heads/*:refs/remotes/origin/*`.
  - `remote.snapshot.url=https://github.com/baljadrawy/signal-bot-live-learning-snapshot.git`; that repo has a single `main` = `0a396c2`.
  - Upstream tracking is set for `main`, `feat/py312-feature-store-audit-2026-06-23`, `feat/throttle-decay-2026-08-10`, `fix/loss-streak-recovery-epoch` and `feature/forward-instrumentation`. Nothing is set for develop, deploy/baseline, refactor, integration or b3.
  - `push.default` is unset, `init.defaultBranch` is unset, and `extensions.worktreeConfig` is unset.
- After a remote branch is deleted, local `refs/remotes/origin/<b>` lingers until a later `git fetch --prune`. The stale `branch.<b>.merge` config entries are harmless but should be removed with the local branch (`git branch -d` removes them).

---

### 4.7 Backup and bundle coverage

#### Backups found
| Path | Content | Verified now |
|---|---|---|
| `/home/tradmin/backups/tsb-phase0-20260927/git/trading-signal-bot-all-refs-20260927.bundle` (41,617,046 B, 2026-09-27 17:50) | 27 refs (19 distinct SHAs): 17 local branches, remote-tracking refs, tag `snapshot-live-learning-0a396c2`, HEAD, `worktrees/b3-worktree/HEAD` | `git bundle verify` = **okay, complete history**. sha256 `bbd4e52b…` = MANIFEST-INDEX. `bundle_heads.txt` = actual heads. |
| `/home/tradmin/backups/signal-bot-live-learning-0a396c2.bundle` (2026-07-01) | `refs/tags/snapshot-live-learning-0a396c2` → 0a396c2 | `git bundle verify` = okay, complete history |
| `/home/tradmin/backups/tsb-phase0-20260927/images/*.tar` (568 MB) | 12 images / 15 tags incl. all rollback anchors | sha256 matches |
| `tsb-phase0-20260927/docs/` | `B3_RESTORE_RUNBOOK.md`, `RECOVERY.md`, `COVERAGE.md`, `OPERATOR_NOTE_resume_limitation.md`; plus `manifests/`, `inventory/`, `deployed/`, `logs-volume/` | `COVERAGE.md`: encrypted restic `/home/tradmin/backups/tsb-restic`; **off-server backup: NOT DONE (blocker)** |
| `tsb-sync-20260927/` | Sync evidence (refs before, remote heads before/after, pushed paths, commit groups) | metadata only; no bundle |
| `tsb-p1-instrumentation-20260927/` | P1 report, test evidence, `MANIFEST.sha256` | **no git bundle of the P1 branch** |

The phase0 bundle was created at **17:50, before** `3ed49c3` (18:23), develop (18:27), refactor (18:28), P1 (22:27) and the docs branch (20:52 UTC). In that bundle, `origin/integration/research-pipeline` is recorded at the older `c4a623c`; its local head `63da7d3` is included.

#### Coverage per ref ("covered" = SHA is a bundle head or an ancestor of one)
| Ref | SHA | Coverage |
|---|---|---|
| main / origin/main / snapshot/main / tag snapshot-live-learning-0a396c2 | 0a396c2 | EXACT head (both bundles) |
| integration/research-pipeline (local + origin) | 63da7d3 | EXACT head |
| fix/b3-fail-closed-trading-state (local + origin) | 8bfca77 | EXACT head |
| fix/loss-streak-recovery-epoch (local + origin) | 05999ea | EXACT head |
| feat/py312-feature-store-audit-2026-06-23 (local + origin) | d91fd50 | EXACT head |
| feat/throttle-decay-2026-08-10 (local + origin) | 912b51a | EXACT head |
| safety/disable-auto-tune (local + origin) | 3d1857d | EXACT head |
| origin/dev (= GitHub `dev`, PR #2 head) | c7e9b88 | EXACT head |
| GitHub `refs/pull/1/head` | cf1b9b2 | ancestor of 05999ea |
| local-only fix/fee-net-gate-2026-07-29, fix/measurement-layer-2026-07-15, fix/neutralize-4f84717-2026-07-29, fix/report-net-fees-2026-07-29 | 1d090be, c2725a9, cdd3450, f9dbc77 | EXACT heads |
| local-only research/evidence-capture-filter, falsification-library, flight-recorder, health-monitor, null-a-evidence-store, recorder-hardening | 928ff1a, bf7b0a1, 7b45a8f, 5157ca9, 2ec84fd, f72d623 | EXACT heads |
| **develop** (local + origin) | 4e3eb0a | **NOT COVERED** |
| **deploy/baseline-2026-09-27** (local + origin) | 3ed49c3 | **NOT COVERED** |
| **feature/forward-instrumentation** (local + origin) | 23dea90 | **NOT COVERED** |
| **refactor/strategy-math** (local + origin) | 6d6790f | **NOT COVERED** |
| **docs/market-intelligence-governance-20260927** (GitHub only; PR #3 head) | 2ffb44b | **NOT COVERED**. The object is **missing locally** (never fetched). Per GitHub compare it is 21 commits ahead of develop and 0 behind, merge base `4e3eb0a`, 9 files (CLAUDE.md plus 8 `docs/product/*`). |

#### Uncovered refs requiring a fresh bundle before any deletion
`develop@4e3eb0a`, `deploy/baseline-2026-09-27@3ed49c3`, `feature/forward-instrumentation@23dea90`, `refactor/strategy-math@6d6790f`, and `docs/market-intelligence-governance-20260927@2ffb44b` (must be fetched first, which requires owner approval because fetch is outside this audit's scope). The planned rollback tag on `3ed49c3` must also be in that bundle. Because develop contains 3ed49c3 and 8bfca77, one new all-refs bundle taken after fetching would cover everything. Store it off-host: off-server backup is still an owner-blocked item.

## 5. Known-good production baseline and proposed rollback tag (NOT created)

### 5.1 What the baseline is
- **Commit:** `3ed49c306ce404359c94ee549dd24b431be2a558` ("chore(deploy): record deployed production baseline 2026-09-27", 18:23 +0200), the head of branch `deploy/baseline-2026-09-27`.
- **Parent:** `8bfca778b42fa5c29993d5c57bf1674ae755522f` (B3 fail-closed, `fix/b3-fail-closed-trading-state`).
- **What it adds:** only 12 record files under `deploy/baseline-2026-09-27/`: the README, `DEPLOYED_MANIFEST.json`, `deployed_files.json` (190 records), 6× `config/*.nonsecret.json`, and 3× `unmatched/` byte-exact copies of deployed files that match no commit.
- **What it records:** the running image IDs of all 7 containers.

  | Container | Image ID |
  |---|---|
  | scanner | `9b0b53a6a799` |
  | analyzer | `ce305ecd7760` |
  | signal_engine | `b3d4b6236654` |
  | trade_tracker | `2b59c6a164c0` |
  | telegram | `b84d3d1528a0` |
  | claude_review | `8bca25750c77` |
  | continuous_learner (stopped) | `d1aa69bde63f` |

- **Rollback anchors** (Docker tags): `b3-rollback/{scanner,telegram,trade_tracker}:pre-b3`, `trade_tracker:pre-risk1-rollback` and `telegram:pre-risk1-rollback`.
- **State:** PAPER_ONLY, HALTED.
- **Reproducibility of the images is explicitly NOT proven**: mixed builds plus single-file overlays.
- **Ancestry:** `3ed49c3` and `8bfca77` are ancestors of `develop`, **not** of `main`. Every other commit the manifest cites as a deployed-file source is also an ancestor of `develop`: `05999ea`, `63da7d3`, `c4a623c`, `7bf6214`, `605a962`, `14fc775`, `c4cae2b`.
- **Where it is protected today:** only by a *branch*, which is mutable and deletable, plus the object store. There is no tag and it is in no bundle.

### 5.2 Proposed tag
- **Name:** `prod-baseline-2026-09-27`, annotated.
  - It deliberately differs from the branch name and path `deploy/baseline-2026-09-27`, because `git log deploy/baseline-2026-09-27` is already ambiguous: that string is both a revision and a path.
  - As of this audit the name does not exist as a tag, branch or path.
- **Target:** `3ed49c306ce404359c94ee549dd24b431be2a558`. This one tag also pins B3 `8bfca77` (its parent).
- **Naming convention for later:**
  - `prod-baseline-YYYY-MM-DD` for each deployed baseline.
  - `archive/<branch-name>-<sha7>` for unique branches retired without merging (§8 step 3).

**Exact commands.** Run them only after owner approval (ADR-011) and after step 1 in §8. They can be run from any worktree, because tags are repository-global.
```bash
cd /home/tradmin/tsb-develop
# preconditions (read-only)
git cat-file -e 3ed49c306ce404359c94ee549dd24b431be2a558^{commit} && echo COMMIT-OK
git rev-parse --verify -q refs/tags/prod-baseline-2026-09-27 && echo "TAG EXISTS - STOP"
git ls-remote --exit-code origin refs/tags/prod-baseline-2026-09-27 && echo "REMOTE TAG EXISTS - STOP"
test "$(git rev-parse 3ed49c306ce404359c94ee549dd24b431be2a558^)" = 8bfca778b42fa5c29993d5c57bf1674ae755522f && echo PARENT-IS-B3

# create (annotated; add -s instead of -a if a signing key is configured)
git tag -a prod-baseline-2026-09-27 3ed49c306ce404359c94ee549dd24b431be2a558 -F - <<'EOF'
Production baseline 2026-09-27 (PAPER_ONLY, PAPER_HALTED, B3 fail-closed)

Record commit 3ed49c306ce404359c94ee549dd24b431be2a558 (deploy/baseline-2026-09-27)
on top of B3 8bfca778b42fa5c29993d5c57bf1674ae755522f (fix/b3-fail-closed-trading-state).
deploy/baseline-2026-09-27/{DEPLOYED_MANIFEST.json,deployed_files.json,unmatched/} record
running image IDs and per-file SHA256 for 7 containers (190 files, 3 unmatched copies).
Images: scanner 9b0b53a6a799, analyzer ce305ecd7760, signal_engine b3d4b6236654,
trade_tracker 2b59c6a164c0, telegram b84d3d1528a0, claude_review 8bca25750c77,
continuous_learner (stopped) d1aa69bde63f.
Docker rollback anchors: b3-rollback/{scanner,telegram,trade_tracker}:pre-b3,
trade_tracker:pre-risk1-rollback, telegram:pre-risk1-rollback.
Image reproducibility is NOT proven (mixed builds + single-file overlays).
Immutable replacement for branch deploy/baseline-2026-09-27 (ADR-011).
EOF

# publish ONLY this tag (never --tags, never --force)
git push origin refs/tags/prod-baseline-2026-09-27
```

### 5.3 Verification (all must pass before any branch deletion)
```bash
git cat-file -t prod-baseline-2026-09-27                     # -> tag   (annotated, not lightweight)
git rev-parse prod-baseline-2026-09-27^{commit}              # -> 3ed49c306ce404359c94ee549dd24b431be2a558
git merge-base --is-ancestor 8bfca778b42fa5c29993d5c57bf1674ae755522f prod-baseline-2026-09-27 && echo B3-PINNED
git diff --quiet refs/heads/deploy/baseline-2026-09-27 prod-baseline-2026-09-27 -- && echo SAME-TREE-AS-BRANCH
git ls-remote origin 'refs/tags/prod-baseline-2026-09-27*'   # 2 lines: <tag-object> and <3ed49c3…>  ^{}
gh api repos/baljadrawy/trading-signal-bot/git/ref/tags/prod-baseline-2026-09-27 --jq '.object.type+" "+.object.sha'   # tag <obj>
gh api repos/baljadrawy/trading-signal-bot/git/tags/<obj> --jq '.object.sha'   # -> 3ed49c306ce4…
# manifest integrity: tagged manifest == file in the baseline worktree
git show prod-baseline-2026-09-27:deploy/baseline-2026-09-27/DEPLOYED_MANIFEST.json | sha256sum
sha256sum /home/tradmin/tsb-baseline/deploy/baseline-2026-09-27/DEPLOYED_MANIFEST.json
# the new bundle (step 1 / re-run after tagging) must list the tag
git bundle list-heads <new-bundle> | grep prod-baseline-2026-09-27
```

**Optional protection.** If the GitHub plan allows it, add a tag ruleset for `prod-baseline-*` and `archive/*` that blocks deletion and update.

**Recovery if the tag is created wrongly** (before anything depends on it): `git tag -d prod-baseline-2026-09-27 && git push origin :refs/tags/prod-baseline-2026-09-27`, then re-create it. Never move a published baseline tag after branches have been deleted against it.

## 6. Unused-code audit on `develop` (@4e3eb0a, worktree /home/tradmin/tsb-develop)

### 6.1 Method and limitations
- **Scope:** the 952 files tracked in develop (`git ls-files`), of which 345 are `.py`. Nothing was executed: no project code, tests, pip, or docker build/run. Helper scripts (stdlib `ast`/`re`/`json` only) and their outputs are in the scratchpad `code_audit/` (`graph.py`, `reach.py`, `deps.py`, `table.py`, plus JSON outputs).
- **Import graph:** AST parse of all 345 `.py` files (0 parse errors). It covers absolute and relative imports, imports nested in functions, `try/except ImportError` fallbacks, and literal `importlib.import_module`/`__import__` calls. Modules resolve against runtime roots derived from each Dockerfile's COPY layout. Service code is copied flat to `/app`, with `shared/` at `/app/shared` and, in the signal_engine image, `research/{continuous_learner,rollback_learned_gates,strategy_performance_review}.py` and `research/null_a/` at `/app/research`. Literal `sys.path.insert/append` targets also count as roots: `'.'` and `parents[1]` map to the repo root, `'/app'` to the service dir plus the repo root, `'analyzer'` and `'signal_engine'` to those dirs.
- **Reachability:** a BFS from each production CMD (`main.py` of 6 services) plus the compose healthcheck `python -m shared.health`, from the dormant services (continuous_learner, optimizer), from ops/recovery entrypoints (cron, setup.sh, runbooks) and from `tests/`.
- **String references:** every tracked text file (code, Dockerfiles, compose, shell, SQL, docs, governance contracts) plus the redacted crontab lines was scanned for each `.py` file's path, basename or dotted module path. The scan never printed file content. Sealed or evidence files were excluded from all content reads: `*.jsonl`, `*.csv`, `*.pkl`, `results/`, `out/`, `cache/`, `data/`, `runs/`, `governance/` (except contracts), and analyzer-level result `.json`/`.txt` dumps. **Disclosure:** one path-token-only `git grep -o` matched the filename token inside `analyzer/research/results/killzone_causal_2026_05_21_v2.md`. It printed only the token `research/scripts/killzone_causal_v2.py`, no content.
- **Limitations:**
  - Dynamic imports built from non-literal strings, `exec(open(...))`, `docker cp` or `docker exec` of ad-hoc scripts into containers, and external callers cannot be seen statically. External callers include Google Colab, the owner's shell history, and other hosts.
  - The research scripts under `analyzer/` were written to be `docker cp`'d into the analyzer container (`sys.path.insert(0,'/app')`), so "not referenced" does not mean "never run".
  - Function-level dead code inside reachable modules was **not** analysed; the audit is file-level only.
  - The deployed-file comparison uses `deploy/baseline-2026-09-27/deployed_files.json` (190 entries, 7 containers).

### 6.2 Entrypoints (develop)
| Runtime unit | Build / command | Entry → reachable files | Status |
|---|---|---|---|
| scanner | `scanner/Dockerfile`: COPY `shared/`, `scanner/` → `/app`; CMD `python -u main.py`; healthcheck `python -m shared.health` | scanner/main.py → 13 files (scanner_logic + 11 shared) | running (prod) |
| analyzer | `analyzer/Dockerfile`: COPY **only** `main.py technical_analyzer.py orderbook_analyzer.py simple_entry.py` + `shared/` | 15 files; all 4 copied files are reachable. The other **108 top-level `analyzer/*.py` (plus 9 under `analyzer/research/`) are never in the image** | running |
| signal_engine | `signal_engine/Dockerfile`: `shared/`, `signal_engine/`, research/continuous_learner.py, rollback_learned_gates.py, strategy_performance_review.py, `research/null_a/` | 19 files. `research.null_a.recorder`/`.sinks` are imported **lazily inside functions** of signal_logic.py (lines 31–32, 64), and `signal_logic` lazily from main.py:44 | running |
| continuous_learner | same image; compose `command: sh -c "while true; do PYTHONPATH=/app python research/continuous_learner.py …"`; **no `profiles:`**, so a bare `docker compose up -d` would start it | 9 files | deliberately stopped |
| claude_review | COPY `shared/`, `claude_review/`; Claude Code CLI via npm; `/home/tradmin/.claude*` bind-mounted read-only | 9 files | running |
| trade_tracker | COPY `shared/`, `trade_tracker/` | 20 files (try `.binance_price_stream` / fallback `binance_price_stream`) | running |
| telegram | COPY `shared/`, `telegram/` | 14 files | running |
| optimizer | `profiles: ["disabled"]` (since 2026-06-19); CMD `python -u optimizer/main.py`; healthcheck `grep python /proc/1/cmdline` | 8 files | disabled; absent from the deployed baseline manifest |
| cron (every 12h, :30) | `bash /home/tradmin/trading-signal-bot/research/walk_forward_audit.sh` (runs from the **original checkout**, integration/research-pipeline) | bash plus `docker exec … psql` only; no Python imports; tracked file is byte-identical in develop | active |
| cron (every 30 min) | `research/skill_application/.venv/bin/python /home/tradmin/canary_watchdog.py` | host copy is **sha256-identical** to tracked `research/ops/canary_watchdog.py` (stdlib only); interpreter is the **untracked** venv inside `research/skill_application/` of the original checkout | active |
| setup.sh | `docker compose build`, `python3 database/migrate.py`, **`docker compose up -d` (bare; would start the stopped learner, which SINGLE_HOST_SAFETY §5 forbids)** | database/migrate.py → `database/migrations/NNN_*.sql` | manual |
| runbooks (docs) | `docker compose exec continuous_learner python research/strategy_performance_review.py` · `… research/rollback_learned_gates.py RUN_ID` · `python -m research.replay` · `python -m research.data_governance.cli` · `.venv/bin/python monitor_canary.py` · `.venv/bin/python research/measurement_reanalysis.py` · `python research/entry_hypothesis_review.py` · `.venv/bin/python -m pytest` (19×) | see 6.5 | manual |

No Makefile, pyproject, setup.cfg, conftest.py, pytest.ini or `.github/` exists. **No CI.**

### 6.3 Classification summary (345 tracked `.py`)
| Class | Files | → KEEP | → NEEDS-OWNER-DECISION | → SAFE-TO-REMOVE |
|---|---|---|---|---|
| PROD-REACHABLE | 45 | 45 | – | – |
| DORMANT-SERVICE (learner, optimizer) | 5 | 1 | 4 (optimizer/*) | – |
| OPS/RECOVERY | 3 | 3 | – | – |
| TEST (tests/*.py) | 50 | 50 | – | – |
| TEST-ONLY (reached only from tests or research CLIs) | 39 | 28 | 11 (research/falsification, research/monitoring) | – |
| RESEARCH-STANDALONE / unreferenced by any import | 203 | 13 | 186 | 4 |
| **Total** | **345** | **140** | **201** | **4** |

PROD-REACHABLE by directory:
- shared: 24 of 25; every shared module except `strategy_math.py` is reached by at least one service. alerts, config, database and logger reach 8 units; health and schema reach 7.
- research/null_a: 7 (signal_engine, lazy).
- analyzer: 4
- trade_tracker: 3
- scanner: 2
- signal_engine: 2
- telegram: 2
- claude_review: 1

### 6.4 Findings that matter for cleanup
1. **The analyzer service directory is mostly research.** 108 of the 112 top-level `analyzer/*.py` (plus 9 `.py` under `analyzer/research/`) are never copied into the image. They are the Part 1–50 backtest program, the ML/futures/OI/momentum studies and cycle checks. 31 of them read or write tracked result files (`backtest_results_part*.jsonl`, `edge_leaderboard.jsonl`, …). They are evidence producers for recorded verdicts, so the recommendation is **NEEDS-OWNER-DECISION**: move them into a research archive path, or preserve them under an archive tag and then delete. They are not SAFE-TO-REMOVE.
2. **Exact duplicate code.** Six byte-identical blob pairs exist (4 `.py` + 2 `.md` reports). Details are in 6.5.
3. **Lazy and dynamic imports are production-critical.** `research/null_a/*` is reachable only through function-level imports in `signal_engine/signal_logic.py`, and `signal_logic` only through a lazy import in `signal_engine/main.py`. A naive top-level import scan would wrongly flag all 7 null_a files as unused. `tests/test_b3_fail_closed_callers.py` and `tests/test_risk_recovery_command.py` use `importlib.import_module('main')` as a container-layout fallback.
4. **Production images run older code than develop.** All 59 unique deployed repo paths (190 manifest entries across 7 containers) still exist in develop, so no deployed file is a deletion candidate. **11 paths differ** from develop because some images were built from older commits (shared/schema.py in 5 containers; config, macro_context and triple_barrier in scanner/claude_review/learner; and others). Reach these via tags and history, not branch tips.
5. **Schema drift risk (not a deletion).** `database/init.sql` plus `database/migrations/001–009` do **not** create `features_snapshot`, `macro_history` or `macro_snapshot`. Those exist only in the dated one-shot files `database/migrate_features_snapshot_2026_06_23.sql` and `database/migrate_live_learning_2026_06_25.sql`, so those files must be kept (or folded into numbered migrations) before anyone treats them as legacy. `database/migrate.sql` is fully superseded: all 4 of its tables appear in init.sql/migrations and it has zero references.
6. **Vestigial infrastructure (config, not files).** No production code loads models (no joblib, pickle or `/app/models` reads), yet compose mounts the `models_data` volume into analyzer and signal_engine and 4 Dockerfiles `mkdir /app/models`. This is NEEDS-OWNER-DECISION as a separate cleanup PR.
7. **`shared/strategy_math.py`** is not used by production on develop. The research replay/P0R code and 2 tests use it, and it is the wiring target of the unmerged `refactor/strategy-math`. **KEEP.**

### 6.5 SAFE-TO-REMOVE (strong evidence only)
In every row below, the retained copy is byte-identical: same git blob, verified with `git ls-tree`. Each removed file has zero importers, is absent from every Dockerfile COPY, compose file, crontab line and runbook, and does not appear in `deployed_files.json` or `unmatched/`. Removal therefore loses no code; git history retains it.

| # | Remove | Keep (identical blob) | Blob | Last commit | Note |
|---|---|---|---|---|---|
| 1 | `analyzer/research/entry_reverse_engineer.py` | `research/entry_reverse_engineer.py` | 27f1e14b3b | 2026-05-20 | Reports cite the path `research/entry_reverse_engineer.py`. |
| 2 | `analyzer/research/scripts/entry_filter_test.py` | `research/scripts/entry_filter_test.py` | 6e7f86eeee | 2026-05-20 | Reports cite `research/scripts/entry_filter_test.py`. |
| 3 | `analyzer/research/scripts/killzone_causal_v2.py` | `research/scripts/killzone_causal_v2.py` | d1024ce5b3 | 2026-05-21 | A report under `analyzer/research/results/` cites `research/scripts/killzone_causal_v2.py`, which is ambiguous relative to `analyzer/`. The code is identical either way. Record the mapping in the cleanup PR. |
| 4 | `analyzer/backtest_part30.py` | `analyzer/backtest_part30_schema_reconciliation.py` | 937924750f | 2026-06-13 | Zero references to either name. The kept name is the descriptive one. |
| 5 (docs) | `analyzer/research/entry_methodology_report.md` | `research/entry_methodology_report.md` | 9e3426d2f0 | – | Duplicate research report (not opened; blob equality only). |
| 6 (docs) | `analyzer/research/entry_filter_causal_test_2026_05_20.md` | `research/entry_filter_causal_test_2026_05_20.md` | ddfec4fe31 | – | Same as above. |
| 7 (SQL) | `database/migrate.sql` | `database/init.sql` + `database/migrations/` | – | 2026-05-14 | Zero references. All 4 tables it creates (scan_candidates, approval_requests, risk_management, symbol_blacklist) are defined in init.sql/migrations. |

- **Risk:** low. No runtime, test or image path references these files.
- **Recovery:** `git checkout <pre-removal-commit> -- <path>` (or `git show <sha>:<path>`), available from develop history, the preserved tags and the phase-0 bundle.
- **Test impact:** none (no test imports them).

### 6.6 NEEDS-OWNER-DECISION (grouped; per-file rows in Appendix A)
| Group | Files | Why not safe | Recommendation |
|---|---|---|---|
| `analyzer/*.py` research scripts (excluding the 4 in the image and #4 above) | 107 `.py` (+ `analyzer/MODEL_FROZEN_SPEC.md`, zero refs) | Part 1–50 backtests, ML/futures/OI/momentum studies and cycle-check scripts; 31 of them read or write tracked result files. They back recorded no-edge verdicts and were run by `docker cp` into the analyzer container, which the repo cannot show. | Move them out of the service dir (e.g. `research/archive/analyzer_legacy/`) in one PR, or preserve them under an annotated archive tag and then delete. Do not mix this with a code-change PR. |
| `analyzer/research/**` non-duplicate code | `scripts/edge_discovery_{clean,v2,v3,v4_vwap_rs}.py`, `scripts/ict_structural_causal{,_v3}.py` (6) | Near-duplicate variants of `research/scripts/*`; `ict_structural_causal.py` differs in size, 31206 B vs 32618 B | Same archive decision. The adjacent `analyzer/research/results/`, `cache/` and `bt_cache_vrsi/` (≈133 MB of tracked pkl/csv) are sealed data and outside this code audit. |
| `research/scripts/*.py` | 6 (fvg_census, fvg_ic_test, ict_structural_causal, killzone_causal_test, killzone_causal_v2, entry_filter_test) + `research/entry_reverse_engineer.py` | Producers of results under `research/results/` and cited in reports | KEEP as research record, or archive with tag |
| `research/skill_application/**` | 65 `.py` + `run_final_ml.sh`, `wf_skill_audit.js`, `out/` (evidence) | Explicitly preserved by develop HEAD `4e3eb0a` (2026-09-27). Excluded from Docker builds by `.dockerignore`. **Its untracked `.venv/` in the original checkout is the interpreter of the active canary_watchdog cron**, so do not remove or rename the directory in the original checkout. | KEEP for now. If archived later, first repoint the cron to a dedicated venv. |
| `optimizer/*` (4) | `__init__.py`, `main.py`, `analyzer.py`, `tuner.py` | Disabled by compose profile since 2026-06-19 (strategy freeze). It rewrote `indicator_weights`/`optimizer_settings` hourly. Absent from the deployed baseline. The unmerged `safety/disable-auto-tune` branch touches it. | Decide retire vs keep. Removing it requires a compose + Dockerfile change in the same PR. |
| `research/falsification/*` (9), `research/monitoring/*` (2) | shadow-only libraries | Tested (`tests/test_falsification.py`, `tests/test_monitoring.py`) but not wired to any service. They are PR #2/#3 of the robustness ladder. | KEEP while the robustness ladder is open; otherwise archive together with their tests. |
| `colab/daily_training.py` + `.ipynb` | 2 | Zero repo references; last commit 2026-04-14. It **UPDATEs `indicator_weights` and INSERTs `learning_log` in the prod DB** over an SSH tunnel, which contradicts the freeze. External Colab use cannot be ruled out from the host. | Recommend removal after the owner confirms there is no external Colab schedule. |
| `database/migrate_features_snapshot_2026_06_23.sql`, `database/migrate_live_learning_2026_06_25.sql` | 2 | Only source of `features_snapshot`, `macro_history` and `macro_snapshot` DDL (see 6.4 #5) | Fold into numbered `migrations/010_*.sql` first, then remove |
| Vestigial `models_data` volume, `/app/models` mkdir | config | No production code reads models | Separate config-cleanup PR |

KEEP (not candidates, for the record):
- the 3 `deploy/baseline-2026-09-27/unmatched/**` copies (deployment evidence)
- `research/ops/canary_watchdog.py` (source of the active cron)
- `research/walk_forward_audit.sh` (active cron, run from the original checkout)
- `research/rollback_learned_gates.py`, `research/strategy_performance_review.py` (ops runbooks, deployed)
- `monitor_canary.py`, `research/{portfolio,walk_forward,entry_hypothesis}_review.py` (documented tools + tests)
- `research/foundation/*`, `research/data_governance/*`, `research/p0r.py`, `research/replay.py`, `research/measurement_reanalysis.py` (2026-09-27 governance toolchain / documented)
- `research/continuous_learner.py` (stopped service, still built into the image)
- `shared/strategy_math.py`

### 6.7 Dependencies: declared vs imported (reachable code per image)
| requirements file | Declared | Imported by reachable code | Declared but not imported | Imported but not declared | Assessment |
|---|---|---|---|---|---|
| analyzer | python-binance 1.0.19, asyncpg, aiohttp 3.13.5, pandas 3.0.3, numpy 2.2.6, ta 0.11.0, websockets 12.0 | binance, asyncpg, aiohttp, pandas, numpy, ta | **websockets** | (anthropic: optional `try/except` in shared/retry_utils.py) | websockets is a **transitive pin**: python-binance 1.0.19 has `Requires-Dist: websockets`, unversioned, per the installed METADATA. **KEEP.** Only the analyzer image pins it; the other python-binance images do not, which is an inconsistency for the ADR-009 dependency PR. |
| scanner | python-binance, asyncpg, aiohttp, pandas, numpy, **asyncio-throttle 1.0.2** | binance, asyncpg, aiohttp, pandas, numpy | **asyncio-throttle** (no `throttle`/`Throttler` anywhere in the repo) | – | Candidate for removal in the separate dependency PR (needs an image rebuild, so the release gates apply) |
| signal_engine (+ learner, rollback, strategy_review in the same image) | asyncpg, anthropic **0.25.0**, aiohttp, pandas, python-binance | asyncpg, aiohttp, pandas (null_a sinks), binance (main.py macro), anthropic only through the optional guard in retry_utils | anthropic is effectively unused (only exception classes for retry classification) | **numpy** (research/null_a/{buckets,conditional_null,evidence_store}.py) | numpy arrives transitively through pandas and works, but should be declared explicitly. anthropic is a removal candidate or should be aligned with 0.49.0. |
| claude_review | asyncpg, aiohttp | asyncpg, aiohttp | – | (anthropic optional) | Uses the Claude Code CLI (npm `@anthropic-ai/claude-code@2.1.197`), not the SDK. OK. |
| trade_tracker | **python-binance**, asyncpg, aiohttp | asyncpg, aiohttp | **python-binance** (tracker uses aiohttp REST/WS in binance_price_stream.py; no `binance` import) | (anthropic optional) | Removal candidate for the dependency PR |
| telegram | asyncpg, python-telegram-bot 21.11.1, aiohttp | asyncpg, telegram (`from telegram import …`, `telegram.ext`), aiohttp | – | (anthropic optional) | OK. The automated scan reported a false negative here because a local dir shares the name `telegram`; manually verified. |
| optimizer (disabled) | asyncpg, aiohttp, **anthropic 0.49.0** | asyncpg, aiohttp | **anthropic** (no anthropic/claude usage in optimizer/*) | – | Moot while disabled |
| *(none)* tests | – | pytest (23 files), pytest_asyncio (2), pandas (9), numpy (8) | – | **pytest, pytest-asyncio**: no dev requirements file. Runbooks use `research/skill_application/.venv/bin/python -m pytest`. | Add `requirements-dev.txt` in the dependency PR |
| *(none)* research | – | numpy, pandas, requests, scipy, sklearn, statsmodels, xgboost, pandas_ta, shap, joblib, ta, psycopg2, asyncpg, binance; `overfit_detector` (not in repo, presumably venv/skill-provided) | – | All undeclared (research runs in the untracked venv) | Document or pin a research lock file when archiving |

Version skew to note for ADR-009: `anthropic` is pinned at 0.25.0 in signal_engine and at 0.49.0 in optimizer.

### 6.8 Non-code observations (outside this section's scope, recorded for the consolidated audit)
- Large tracked data under `analyzer/`: `bt_cache_vrsi/` has 64 pkl (≈52.3 MB); `research/cache/` has 368 pkl (≈49.1 MB, 3 with non-ASCII names); `research/results/` has 3 csv (≈31.6 MB, sealed evidence, **not opened**). There are also `part37_ohlc_cache.pkl` (3.27 MB), `part38_1h_cache.pkl` (0.76 MB), `backtest_results_part1.jsonl` (0.82 MB), `backtest_results_volume_rsi_mtf.jsonl` (0.96 MB) and a stray `backtest_results_part33.jsonl.bug`.
- `.dockerignore` excludes `*.pkl`, `*.csv`, `*.jsonl` and `research/skill_application/`, so none of this reaches the images.
- `docker-compose.yml.bak` (224 lines) is tracked next to the 300-line live compose.


## 7. Repository hygiene: size, artifacts, docs and config clutter

Scope: `develop@4e3eb0a` (worktree `/home/tradmin/tsb-develop`), compared with `main@0a396c2`, `integration/research-pipeline@63da7d3` and `deploy/baseline-2026-09-27@3ed49c3`. The production checkout `/home/tradmin/trading-signal-bot` (dirty, `63da7d3`) was inspected with `git --no-optional-locks status`, looking at names only.

Method: only read-only git commands were used (`ls-tree`, `log`, `grep`, `cat-file --batch-check`, `check-ignore --no-index`, `hash-object` without `-w`), plus `gh api` GET requests. No `.env` file was opened. No `*.csv` or `*.jsonl` contents were read, and nothing under a `results/` or data directory was opened. Research outputs are listed by name and size only.

---

### 7.1 Size and large files

#### Totals on `develop@4e3eb0a`
- **952 tracked files, 142,450,710 bytes (135.9 MB)**.
- About 136.8 MB (96%) of that is data, not code:

| Extension | Files | Bytes | Notes |
|---|---:|---:|---|
| `.pkl` | 434 | 105,425,900 | OHLC/kline pickle caches. Includes 3 files with non-ASCII names, e.g. `analyzer/research/cache/klines/币安人生USDT_{1d,1h,4h}.pkl` |
| `.csv` | 7 | 31,627,094 | 3 research-result CSVs total 31.6 MB |
| `.py` | 345 | 2,618,814 | All the code |
| `.jsonl` | 31 | 2,062,778 | Backtest-result evidence |
| `.json` | 44 | 311,858 | |
| `.md` | 46 | 288,695 | |
| everything else | ~45 | <0.2 MB | |

#### By top-level directory

| Directory | Files | Bytes |
|---|---:|---:|
| `analyzer/` | 605 | **140,559,580 (98.7% of the repo)** |
| `research/` | 173 | 1,011,249 |
| `tests/` | 50 | 185,253 |
| `docs/` | 30 | 169,523 |
| `shared/` | 25 | 97,733 |
| `deploy/` | 12 | 93,065 |
| `(root)` | 15 | 79,862 |
| `telegram/` | 4 | 56,928 |
| `trade_tracker/` | 5 | 50,059 |
| `signal_engine/` | 4 | 48,335 |
| `database/` | 14 | 30,790 |
| `optimizer/` | 6 | 25,400 |
| `colab/` | 2 | 21,040 |
| `claude_review/` | 3 | 11,336 |
| `scanner/` | 4 | 10,557 |

#### Tracked files larger than 500 KB (35 files)

| Size (B) | Path | Added in | Reader (code) |
|---:|---|---|---|
| 12,559,869 | `analyzer/research/results/killzone_causal_2026_05_21_v2_raw.csv` | f1ac14a (2026-06-13) | research result (not opened) |
| 9,942,215 | `analyzer/research/results/ict_structural_causal_2026_05_22_ict_v3_features.csv` | f1ac14a (2026-06-13) | research result (not opened) |
| 9,100,366 | `analyzer/research/results/ict_structural_causal_2026_05_21_ict_features.csv` | 6e0c276 (2026-05-21) | research result (not opened) |
| 3,273,349 | `analyzer/part37_ohlc_cache.pkl` | f1ac14a (2026-06-13) | `analyzer/backtest_part37_smc_advanced_ohlc.py` |
| 1,963,681 ×25 | `analyzer/bt_cache_vrsi/{ZEC,XRP,XLM,WLD,TRX,TAO,SUI,SOL,PORTAL,NFP,NEAR,MEME,LINK,INJ,ID,HEI,HBAR,FET,ETH,DOGE,BTC,BNB,ALGO,ADA}USDT_15m_12m.pkl` | f1ac14a | `analyzer/backtest_volume_rsi_mtf.py` |
| 1,271,577 / 1,077,537 / 740,249 / 691,865 | `analyzer/bt_cache_vrsi/{ASTER,ALLO,U,RLUSD}USDT_15m_12m.pkl` | f1ac14a | same |
| 964,865 | `analyzer/backtest_results_volume_rsi_mtf.jsonl` | | evidence (not opened) |
| 822,313 | `analyzer/backtest_results_part1.jsonl` | | evidence (not opened) |
| 761,849 | `analyzer/part38_1h_cache.pkl` | f1ac14a | `analyzer/backtest_part38_wide_rr_isolation.py` |

#### Pickle cache directories

| Directory | Files | Bytes | Readers |
|---|---:|---:|---|
| `analyzer/bt_cache_vrsi` | 64 | 52.3 MB | `analyzer/backtest_volume_rsi_mtf.py` |
| `analyzer/research/cache/ict_ohlc` | 137 | 32.9 MB | `analyzer/backtest_imbalance.py`, `{analyzer/,}research/scripts/ict_structural_causal*.py`, `research/entry_hypothesis_review.py`, `research/skill_application/scripts/lib.py` |
| `analyzer/research/cache/klines_kz_v2` | 80 | 8.4 MB | `{analyzer/,}research/scripts/killzone_causal_v2.py`, `research/skill_application/scripts/lib.py` |
| `analyzer/research/cache/klines` | 147 | 7.8 MB | same family |
| `analyzer/research/cache` (root) | 4 | 5 KB | |
| `analyzer/part37_ohlc_cache.pkl`, `part38_1h_cache.pkl` | 2 | 4.0 MB | part37/part38 backtests |

#### Other tracked data and evidence (names and sizes only, not opened)
- **`analyzer/backtest_results_part*.jsonl` (27 files)**, 0.6 KB–822 KB each. Other analyzer data files:
  - `analyzer/backtest_results_volume_rsi_mtf.jsonl` (965 KB)
  - `analyzer/edge_leaderboard.jsonl` (3.7 KB; read and appended by `analyzer/backtest_part33_smc_unified*.py`, `part35`, `part40`, `part50`)
  - `analyzer/research/entry_re_partial.jsonl` (24 KB)
  - `analyzer/trades50.csv` (5.6 KB; read by `analyzer/backtest_imbalance.py`)
  - `analyzer/research_summary.txt` (818 B; no code reader)
  - `analyzer/backtest_results_part33.jsonl.bug` (2.3 KB; a quarantined buggy run; no reader)
- **`research/skill_application/out/` (15 files, ~84 KB):** `REPORT.md`, `telegram.md`, 3× `.csv`, 10× `.json`.
  - They were force-added in 977746f (2026-06-23), but `.gitignore:62` ignores `research/skill_application/out/`. The directory is therefore both ignored and tracked, which is inconsistent.
- **Other research outputs:**
  - `research/skill_application/scripts/fc_RESULTS.md` (11 KB) and `fc_robust_out.txt` (6 KB)
  - `research/governance/contamination_registry.jsonl` (968 B)
  - two **0-byte** registries, `research/governance/{hypotheses,validation_usage}.jsonl`. These are intentional placeholders; KEEP.

#### Provenance and impact
- All the pickle caches, 2 of the 3 large results CSVs (the third came in 6e0c276, 2026-05-21) and several root and analyzer artifacts arrived in **one commit: `f1ac14a` (2026-06-13) "docs(cycle20): final gate 45/50 trades…"**. That looks like a bulk `git add -A` by the autonomous monitoring cron. `CLAUDE.md:23` and the governance CLAUDE.md both now forbid `git add -A`.
- These caches are present **identically on `main`, `63da7d3`, `3ed49c3` and `develop`**:
  - `analyzer/bt_cache_vrsi`: 64 files
  - `analyzer/research/cache`: 368 files
  - `analyzer/research/results`: 10 files
  - `research/skill_application/out`: 15 files
- **No image impact:**
  - `.dockerignore` on develop excludes `*.csv *.jsonl *.pkl *.joblib data/ research/skill_application/`.
  - `analyzer/Dockerfile:22` copies only `main.py technical_analyzer.py orderbook_analyzer.py simple_entry.py` plus `shared/`.
  - The 56 `analyzer/backtest_*.py` scripts and all analyzer data are research-only and never enter an image.
- **Classification: NEEDS-OWNER-DECISION** for everything in this section.
  - The pickles are market-data caches that can be rebuilt from Binance or data.binance.vision.
  - The `results/` CSVs and `*.jsonl` are research evidence. Governance forbids deleting evidence just because nothing imports it.
  - Proposed option, via a cleanup PR only after the baseline tag and backups exist:
    - `git rm --cached` the pickle caches and `results/*.csv`, and add `.gitignore` rules for `analyzer/**/cache/`, `analyzer/bt_cache_*/` and `analyzer/*_cache.pkl`.
    - Keep a SHA-256 manifest of the removed files in `docs/` or `research/`.
    - Content stays recoverable from history, e.g. `git show 3ed49c3:<path>`, and from the phase-0 bundle.
  - Effect: the checkout shrinks by about 137 MB. The pack does not shrink (see §7.2).

### 7.2 History bloat (report only; no rewrite recommended)
- `git rev-list --objects --all` finds 2,221 objects, of which **1,359 are unique blobs: 139.2 MB uncompressed, 40.6 MB packed**. That is consistent with `git count-objects`:
  - `size-pack` 39.38 MiB, plus 4.08 MiB loose, 902 objects
  - `.git` on disk 46 MB
  - GitHub `size` = 41,142 KB
- The **develop tip alone holds 135.9 MB of those 139.2 MB**. History is therefore *not* bloated by deleted files. The weight is live data at the tip of every branch.
- The top 25 blobs in history are the same files as the tip list in §7.1: the 3 results CSVs (12.6 / 9.9 / 9.1 MB), `part37_ohlc_cache.pkl`, and 21 `bt_cache_vrsi` 1.96 MB pickles.
- **Recommendation: do NOT rewrite history** (no filter-repo or BFG).
  - A rewrite would change every SHA, including baseline `3ed49c3`, B3 `8bfca77` and P1 `23dea90`.
  - It would invalidate `deploy/baseline-2026-09-27/DEPLOYED_MANIFEST.json`, the SHA in image revision labels (e.g. `c4cae2b-dirty`), the phase-0 bundle and the rollback provenance.
  - A packed repo of about 40 MB is acceptable. Removing the files from the tip (§7.1) is enough.

### 7.3 Root artifacts

Root files tracked on develop (15): `.dockerignore`, `.env.example`, `.gitignore`, `CLAUDE.md`, `DEV_LOG.md`, `GIT_GUIDE.md`, `README.md`, `SETUP_GUIDE.md`, `analysis_output.txt`, `backtest_results_part40.jsonl`, `docker-compose.yml`, `docker-compose.yml.bak`, `indicator_perf_report.txt`, `monitor_canary.py`, `setup.sh`.

- `main` has the same set **except** `monitor_canary.py`, and it also lacks the `deploy/` directory.
- `63da7d3` and `3ed49c3` have exactly the same 15 root files as develop.

"Ignored?" below means whether current develop rules would ignore the path (`git check-ignore --no-index`).

| Path | develop | main | 63da7d3 | 3ed49c3 | Ignored? | Size | Evidence | Recommendation |
|---|:-:|:-:|:-:|:-:|:-:|---:|---|---|
| `analysis_output.txt` | T | T | T | T | no | 3,426 | Added f1ac14a (2026-06-13). Console output of `analyzer/backtest_part40_edge_discovery_v2.py` (its line "Results saved to backtest_results_part40.jsonl" appears inside it). No code or doc reads it. | **Remove from tip via cleanup PR (low risk).** Stale research console output; history keeps it. Owner sign-off because it is a research output. |
| `backtest_results_part40.jsonl` | T | T | T | T | no | 2,920 | Added f1ac14a. Written by `analyzer/backtest_part40_edge_discovery_v2.py:259` (`open("backtest_results_part40.jsonl","a")`, relative to CWD, so a run from the repo root recreates it here). | **NEEDS-OWNER-DECISION:** evidence file (not opened). Move next to the other `analyzer/backtest_results_part*.jsonl` or to external evidence storage. Do not delete outright. |
| `docker-compose.yml.bak` | T | T | T | T | no | 5,745 | Added 67834fc (2026-06-22). Pre-hardening compose: no `continuous_learner`, no `security_opt`/`cap_drop`/`tmpfs` (diff vs current: 101+/25−). Zero references anywhere. | **SAFE-TO-REMOVE via PR.** A stale config that could bring up an unhardened stack by mistake. History and bundle keep it. |
| `indicator_perf_report.txt` | T | T | T | T | no | 7,071 | Added a402f71 (2026-06-07) "per-indicator performance report from 2461 live closed trades". The generator `analyzer/indicator_perf_analysis.py:185` writes to `/app/logs/…`, so the root copy is a manual snapshot. No readers. | **NEEDS-OWNER-DECISION (low risk):** research output. Archive to `docs/history/` or remove from tip. |
| `monitor_canary.py` | T | – | T | T | no | 3,833 | Added b0a45bd (2026-06-28). Referenced by `docs/canary_runbook.md:15,38`, `docs/canary_state.md:50`, `DEV_LOG.md:13`. Canary Phase A closed 2026-07-06. | **KEEP for now.** Operational tool, not an artifact. Cron use is covered in §6. Later it could move to `research/ops/`. |
| `setup.sh` | T | T | T | T | no | 1,949 | Header `setup.sh:2` says "Raspberry Pi". **`setup.sh:52` runs a bare `docker compose up -d`**, which would start the deliberately stopped `continuous_learner` and conflicts with SINGLE_HOST_SAFETY §5. Referenced by `README.md:33`. | **NEEDS-OWNER-DECISION:** keep only if rewritten or guarded ("first install only; never on the shared prod host"), otherwise retire. |
| `analyzer/backtest_results_part33.jsonl.bug` (not root, same class) | T | T | T | T | no | 2,314 | Added f1ac14a. Quarantined buggy result; no reader. | **NEEDS-OWNER-DECISION:** evidence. |

T = tracked, – = absent.

#### Untracked and ignored files (local only; not git cleanup items)

**Worktrees:**
- `/home/tradmin/tsb-develop`, `/home/tradmin/tsb-baseline`, `/home/tradmin/tsb-refactor` and `/home/tradmin/tsb-p1` are **clean**: no modified, untracked or ignored entries.

**Production checkout `/home/tradmin/trading-signal-bot` (HEAD `63da7d3`):**

*Modified tracked files (7), all already committed elsewhere.* Each working-tree blob was compared with `git hash-object` (no `-w`):

| File | Matching committed blob |
|---|---|
| `.gitignore` | develop / 6d6790f / 23dea90 |
| `database/init.sql` | develop / 3ed49c3 / 8bfca77 / 6d6790f / 23dea90 / 05999ea |
| `docs/canary_state.md` | develop / 6d6790f / 23dea90 |
| `shared/schema.py` | develop / 3ed49c3 / 8bfca77 / 6d6790f / 23dea90 / 05999ea |
| `telegram/main.py` | develop / 3ed49c3 / 8bfca77 / 6d6790f / 05999ea |
| `trade_tracker/main.py` | develop / 3ed49c3 / 8bfca77 / 6d6790f / 05999ea |
| **`analyzer/technical_analyzer.py` (−146 lines)** | **only `refactor/strategy-math@6d6790f`**, not develop and not baseline |

⚠️ **Cross-scope flag:** the unreviewed analyzer rewiring from `refactor/strategy-math` sits uncommitted in the production checkout's working tree. That branch is its only committed ref. Do not delete `refactor/strategy-math` until the owner decides. Images are baked (`docs/claude/operations.md:20`: no code bind-mounts), so this does not affect running containers unless someone rebuilds from that checkout.

*104 untracked (`??`) entries.* Everything except data is already tracked on develop (preserved by `970dda9`/`4e3eb0a` and the like). **Not in develop:**
- **`data/`** (root runtime evidence directory; **not gitignored** by develop's rules)
- 16× `research/skill_application/scripts/*.csv` and 1× `*.jsonl`
- `research/skill_application/support_strength_rows{,_control}.csv`

These are research data and evidence. They are **not a git cleanup item and must not be deleted**; the owner decides on archival. Proposed via PR: add `.gitignore` rules for `/data/`, `research/skill_application/scripts/*.{csv,jsonl,log}` and `research/skill_application/*.csv`, so that no future `git add` can commit evidence.

*76 ignored (`!!`) entries:*
- 39 × `research/skill_application/out/*` (untracked outputs)
- 20 × `__pycache__/`
- `.venv`, `data/`, `external_skills/`, `research/runs/p0r-00aa3ea80de7/`
- `logs/`, `analyzer/logs/`, `analyzer/bt_symbols.txt`
- `.claude/`, `.pytest_cache/`, `.superpowers/`
- `*.log`
- secret files, correctly ignored and **not opened**: `.env`, `.env.binance`, `.env.bak.1782042169`, `.env.bak.ar1`, `.env.bak.precanary`. The owner may want to prune the `.env.bak.*` secret backups outside git.

### 7.4 Docs inventory, duplication and conflicts

#### Inventory (46 `*.md` files on develop)
- There is no `AGENTS.md`.
- **`docs/product/` does not exist on develop.** It exists only on `docs/market-intelligence-governance-20260927` (PR #3, draft, 21 commits ahead of develop and 0 behind). That branch adds:
  - `docs/product/{DECISION_LOG, DEPENDENCY_AUDIT_2026-09-27_INITIAL, DEPENDENCY_POLICY, IDEA_REGISTER, IMPLEMENTATION_ROADMAP, PROJECT_CHARTER, REPOSITORY_CONSOLIDATION, SINGLE_HOST_SAFETY}.md`
  - a modified **`CLAUDE.md`** (80 changed lines) that states older README, `live-learning.md` and `strategy-history` "may describe superseded operations" and must not be treated as current.

| Group | Files (bytes, last commit) | Status |
|---|---|---|
| Root | `CLAUDE.md` (2379, 2026-06-26 3aed157) · `README.md` (2138, 2026-04-08 cc4153c) · `GIT_GUIDE.md` (9137, 2026-04-05 a78365e) · `SETUP_GUIDE.md` (15198, 2026-04-08 cc4153c) · `DEV_LOG.md` (15102, 2026-06-29 0f06065) | CLAUDE, README, GIT_GUIDE and SETUP_GUIDE are **byte-identical on main and develop**. All are stale (see conflicts). |
| `docs/claude/` (6) | `architecture` (2890, 06-26) · `database` (3658, 08-17) · `live-learning` (4975, 08-17) · `operations` (3923, 08-17) · `strategy-history` (3008, 06-26) · `troubleshooting` (1456, 06-26) | Linked from CLAUDE.md. Several are stale. |
| `docs/` root (20) | `canary_runbook` (06-28) · `canary_state` (09-27) · `code_indicator_review_plan` (08-19) · `current_handoff_2026-08-17` (09-27) · `edge_research_foundation` (09-27) · `indicator_regime_execution_review_2026-08-19` · `loss_streak_recovery_runbook` (08-26) · `loss_streak_remediation_2026-08-17` · `phase3/4/5/6/7/9_*_2026-08-17` (6) · `phase16_data_completion`, `phase16b_historical_macro`, `phase2a_p0r_runtime_contract`, `research_temporal_governance` (09-27) · `signal_aware_execution_2026-08-18` · `telegram_trade_lifecycle_2026-08-18` | Dated review and runbook records. Only on develop and its descendants (none on main). |
| `docs/superpowers/` (4) | plans and specs for live-learning collector (06-25; 33.7 KB plan) and measurement-layer fix (07-15) | Completed implementation plans (historical). |
| Deploy | `deploy/baseline-2026-09-27/README.md` (3380, 09-27 3ed49c3) | Current. The production baseline record. |
| Analyzer | `analyzer/MODEL_FROZEN_SPEC.md` (2468, 06-13, no references) · `analyzer/research/entry_filter_causal_test_2026_05_20.md` · `analyzer/research/entry_methodology_report.md` · `analyzer/research/results/{killzone_causal_2026_05_21_v2, edge_discovery_2026_05_22_v3}.md` (results; not opened) | Historical research. |
| Research | `research/entry_filter_causal_test_2026_05_20.md`, `research/entry_methodology_report.md` · `research/skill_application/out/{REPORT,telegram}.md` (tracked but ignored) · `research/skill_application/scripts/fc_RESULTS.md` (results; not opened) | Historical research. |

#### Exact duplicates (same blob)
- `analyzer/research/entry_filter_causal_test_2026_05_20.md` = `research/entry_filter_causal_test_2026_05_20.md` (ddfec4fe)
- `analyzer/research/entry_methodology_report.md` = `research/entry_methodology_report.md` (9e3426d2)
- The same mirroring applies to code (see §5).

#### Key conflicts (file:line)

1. **Branch workflow contradicts ADR-011** ("main only long-lived; PR-only; no direct unreviewed pushes to main"; `dev` is dead at 189 behind):
   - `GIT_GUIDE.md:10-19,30`: main+dev git-flow, "main = what runs on the Raspberry Pi".
   - `GIT_GUIDE.md:134-138,176,181`: local `git merge dev` then `git push origin main` / `dev`.
   - `SETUP_GUIDE.md:381,395-396,413,417`: same.
   - **`docs/claude/operations.md:34-39`: "رفع للـ GitHub … `git push origin main`"** (direct push to main).
2. **Current-state claims are superseded.** Governance and the deploy record say PAPER HALTED under B3, learner stopped since 2026-08-17 (`deploy/baseline-2026-09-27/README.md:37`) and `LEARNING_GATES_ENABLED=false` (`docs/current_handoff_2026-08-17.md:11-14`). These docs say otherwise:
   - `CLAUDE.md:3`: "the current mode: live learning — collects live trades … and learns continuously".
   - `docs/claude/live-learning.md:1-3`: "النظام الحالي … active since 2026-06-26".
   - `docs/claude/operations.md:44`: `LIVE_LEARNING_MODE=true … enabled`.
   - `README.md:9,12`: Claude reviews every signal; daily self-learning.
3. **Unsafe operational commands** that conflict with SINGLE_HOST_SAFETY §5 and §7 (no bare `docker compose up -d`, and no rebuild or restart without an owner-approved release plan):
   - `CLAUDE.md:14`
   - **`docs/claude/operations.md:6-8`** (`docker compose down` / `build --no-cache` / `up -d` for the whole stack), `:11`, `:28-29`
   - `SETUP_GUIDE.md:186,194,444,449`
   - `GIT_GUIDE.md:146`
   - **`setup.sh:52`**
   - `docs/canary_runbook.md:31`, `docs/canary_state.md:66`
   - `docs/superpowers/plans/2026-06-25-live-learning-collector.md:464,570,767`
4. **Architecture drift:**
   - `docs/claude/architecture.md:12` lists a `continuous_learner/` directory that **does not exist** on develop. The service code is `research/continuous_learner.py`, as `:20` itself says.
   - The same doc omits `optimizer/`, `deploy/`, `tests/` and `colab/`.
   - `README.md:17-24`: the container table lacks `trade_tracker`, `optimizer` and `continuous_learner`.
5. **Stale branch pointers and source-of-truth claims:**
   - `docs/canary_state.md:1,4`: "single source of truth in-repo … Branch: integration/research-pipeline (NOT merged to main)"; Canary Phase A closed 2026-07-06.
   - `docs/current_handoff_2026-08-17.md:8`: "الفرع: integration/research-pipeline".
   - `DEV_LOG.md:9`: same.
   - **DEV_LOG has no entry after 2026-06-29.** It misses the July–September work: measurement-layer fix, loss-streak epoch, B3, the baseline and P1.
6. **Obsolete platform and pipeline:**
   - "Raspberry Pi" in `GIT_GUIDE.md` (7 places) and `setup.sh:2`, versus `CLAUDE.md:8` (aarch64 VPS).
   - `SETUP_GUIDE.md:135-166,318-319,475` describe Colab daily training. `colab/` is referenced only by SETUP_GUIDE and `.gitignore`; the optimizer is profile-disabled and the ML pipeline is shelved.

#### Consolidation proposals (proposals only; each needs owner approval in a docs PR)
- **Canonical set after PR #3 merges:** the governance `CLAUDE.md` plus `docs/product/*` (charter, decision log, roadmap, idea register, dependency policy, single-host safety, repository consolidation), plus `deploy/baseline-2026-09-27/README.md` as the deployment record. Keep these operational runbooks: `docs/loss_streak_recovery_runbook.md`, `docs/claude/database.md`, `docs/claude/troubleshooting.md`.
- **Rewrite:**
  - `README.md`: a short, current architecture with a pointer to CLAUDE.md and `docs/product`.
  - `docs/claude/operations.md`: drop `git push origin main` and the whole-stack `down/build/up -d`; point to SINGLE_HOST_SAFETY and the scoped, owner-approved release procedure.
  - `docs/claude/architecture.md`: fix the `continuous_learner` path and list all services.
  - `CLAUDE.md:14`: already replaced by the governance version.
- **Retire or replace:**
  - `GIT_GUIDE.md` → a short "Branching & release" section: main only, PR branches, immutable release and rollback tags. It could live in `REPOSITORY_CONSOLIDATION.md` or a new `docs/product/BRANCHING.md`.
  - `SETUP_GUIDE.md` → strip git-flow and Colab, keep the first-install content, and add a "never on the shared prod host" warning.
- **Archive** under `docs/history/`, or add a "HISTORICAL – superseded by docs/product (2026-09-27)" banner:
  - `docs/claude/live-learning.md`, `docs/claude/strategy-history.md`
  - `docs/current_handoff_2026-08-17.md`
  - `docs/canary_runbook.md`, `docs/canary_state.md`
  - `docs/superpowers/*`
  - `docs/phase*_review_*.md`, `docs/*_2026-08-1x.md`
  - `analyzer/MODEL_FROZEN_SPEC.md`
- **DEV_LOG.md:** either resume it, or freeze it with a banner pointing to `docs/product/DECISION_LOG.md` and git history.
- **Duplicate research reports:** pick one location (suggest `research/`, since the analyzer image never ships `analyzer/research`) and remove the byte-identical copy. There is zero information loss because the blobs are identical.

### 7.5 Config clutter
- **Backup or duplicate configs:**
  - `docker-compose.yml.bak` → **SAFE-TO-REMOVE (PR)** (see §7.3).
  - `analyzer/backtest_results_part33.jsonl.bug` → NEEDS-OWNER-DECISION (evidence).
  - Four `deploy/baseline-2026-09-27/config/*.nonsecret.json` are identical (blob edeca7cc). That is expected (the same non-secret env was captured per container) and they form part of the baseline record: **KEEP**.
  - There is no other compose variant.
- **Duplicate code copies** (research only; nothing in any Dockerfile):
  - `analyzer/backtest_part30.py` = `analyzer/backtest_part30_schema_reconciliation.py` (blob 93792475; neither name is referenced; the copy was re-added in f1ac14a).
  - `analyzer/research/entry_reverse_engineer.py` = `research/entry_reverse_engineer.py` (27f1e14b).
  - `analyzer/research/scripts/{entry_filter_test.py, killzone_causal_v2.py}` = `research/scripts/…` (6e7f86ee, d1024ce5).
  - `ict_structural_causal.py` exists in both trees but has **diverged** (31,206 vs 32,618 B), so it is not a pure duplicate.
  - One copy of each identical pair is removable via PR (**SAFE**, zero loss); diverged copies are NEEDS-OWNER-DECISION. §6 covers cron and script usage.
- **Requirements** (7 per-service `requirements.txt`; needed for per-service Docker builds, so **KEEP**):
  - Shared pins are consistent: asyncpg 0.29.0, aiohttp 3.13.5, pandas 3.0.3, numpy 2.2.6, python-binance 1.0.19.
  - **Drift:** `anthropic==0.25.0` (signal_engine) vs `anthropic==0.49.0` (optimizer). `claude_review/requirements.txt` has no anthropic pin.
  - There is no top-level constraints or lock file.
  - Defer to the ADR-009 dependency audit; no change in the cleanup PR.
- **Empty or placeholder files:** `optimizer/__init__.py` (package marker), `research/governance/{hypotheses,validation_usage}.jsonl` (empty governance registries), 2× `.gitkeep`. All **KEEP**.
- **Bytecode and secrets:** no `__pycache__/`, `*.pyc`, credential-like names, `.pem` or `.key` files are tracked. `.env*` files are ignored, and only `.env.example` is tracked.
- **Notebooks:** `colab/daily_training.ipynb` (12 KB) and `colab/daily_training.py` (8.6 KB) are referenced only by `SETUP_GUIDE.md`. **NEEDS-OWNER-DECISION** (likely obsolete Colab training path).
- **Vendored or third-party:**
  - None vendored.
  - `research/skill_application/wf_skill_audit.js` is a Claude Workflow script from the 2026-06-23 skill audit (research tooling; KEEP or archive).
  - `research/external_skills/` is ignored, not tracked.
- **Ignore-rule gaps and inconsistencies:**
  - Missing rules: `/data/`, `research/skill_application/scripts/*.{csv,jsonl,log}`, `research/skill_application/*.csv`, `analyzer/**/cache/`, `analyzer/bt_cache_*/`, `analyzer/*_cache.pkl`.
  - `research/skill_application/out/` is ignored yet has 15 tracked files.
  - `.dockerignore` differs between main (44 B) and develop (132 B). Develop's version correctly excludes data.
  - Fix all of these in one small hygiene PR after the baseline tag.

## 8. Safe consolidation sequence (proposal; each step needs its own owner approval)

**Global rules for every step:**
- One step at a time; verify before moving on.
- No force-push and no history rewrite.
- No squash or rebase of `develop` into `main`.
- No host or production change bundled with GitHub steps.
- No bare `docker compose` commands.
- Changing GitHub branches, tags or defaults **is not a deployment**. Production runs baked images from `/home/tradmin/trading-signal-bot` and is unaffected.
- **Before each step,** record `git ls-remote origin > <backup-dir>/ls-remote-<step>.txt` so there is a before-state to restore.

Variables used below:
```bash
R=baljadrawy/trading-signal-bot
D=/home/tradmin/backups/tsb-cleanup-$(date +%Y%m%d)        # new backup dir (mode 700)
B="$D/tsb-all-refs-$(date +%Y%m%dT%H%M).bundle"
```

### Step 0: Approvals and freeze window
- **Preconditions:**
  - The owner approves this audit's deletion list (§9) and the order below.
  - No P1/refactor/safety work is being pushed.
  - PAPER_HALTED is unchanged.
  - The paused `cron-signal-bot-review.sh` stays paused. It would push directly to the checked-out branch.
- **Verify:**
  - `gh api repos/$R --jq .default_branch` → `main`.
  - `gh api "repos/$R/pulls?state=open" --jq '.[].number'` → only `3` (plus any P1 PR, if opened).
- **Recovery:** n/a.

### Step 1: Fresh, complete, verified backup (hard precondition for every later step)
- **Preconditions:** the owner approves a plain `git fetch origin`.
  - No `--prune`: it only adds or updates `refs/remotes/*`; worktrees and the production checkout are untouched.
  - It is needed because PR #3 (`2ffb44b`) exists only on GitHub.
  - Disk: the bundle is about 45 MB.
- **Commands:**
  ```bash
  mkdir -m 700 -p "$D"; cd /home/tradmin/tsb-develop
  git ls-remote origin > "$D/ls-remote-before.txt"
  git fetch origin                                   # NO --prune
  git cat-file -e 2ffb44b80b79c90c37de8f29020b94c0af949fc3^{commit} && echo PR3-FETCHED
  git bundle create "$B" --all                       # all heads, remote-tracking refs, tags
  git bundle verify "$B"                             # "okay"
  git bundle list-heads "$B" > "$D/bundle_heads.txt"
  git for-each-ref --format='%(objectname) %(refname)' > "$D/refs_manifest.txt"
  git worktree list --porcelain > "$D/worktrees.txt"
  sha256sum "$B" > "$D/SHA256SUMS"
  # coverage: every GitHub branch tip must be a bundle head or an ancestor of one
  grep -v 'refs/pull/' "$D/ls-remote-before.txt" | while read s r; do
    ok=; for h in $(awk '{print $1}' "$D/bundle_heads.txt" | sort -u); do
      git merge-base --is-ancestor "$s" "$h" 2>/dev/null && { ok=1; break; }; done
    [ -n "$ok" ] || echo "NOT COVERED: $r $s"; done          # expect no output
  # restore test into a scratch dir, then remove it
  git clone -q --mirror "$B" "$D/restore-test.git" && git -C "$D/restore-test.git" for-each-ref | wc -l && rm -rf "$D/restore-test.git"
  ```
- **Verify:**
  - `bundle verify` reports okay.
  - There are no "NOT COVERED" lines.
  - The bundle heads include `develop 4e3eb0a`, `3ed49c3`, `23dea90`, `6d6790f`, `3d1857d` and `origin/docs/… 2ffb44b`.
  - The 10 local-only branches are included.
- **Backup:** keep the Phase-0 bundle as well. Owner decision: an off-host copy of `$D`. It is currently blocked, so single-host loss remains an accepted risk until it is resolved.
- **Recovery:** this step is additive. Delete `$D` if it has to be redone.

### Step 2: Create and publish the baseline rollback tag
- **What:** `prod-baseline-2026-09-27` → `3ed49c3`. §5.2 has the exact commands and §5.3 the verification.
- **After the tag:** re-run `git bundle create "$D/tags-$(date +%H%M).bundle" --tags` or a new `--all` bundle so the tag object is also backed up.
- **Recovery:** §5.3.

### Step 3: Owner decisions on the unique branches, then archive tags only where the decision is "retire"
- **`refactor/strategy-math@6d6790f`:**
  - (A) Review plus a runtime parity test against deployed `63da7d3` / image `ce305ecd`, then a PR to `main`. It conflicts with P1 in the `technical_analyzer.py` imports, so rebase it after whichever lands first.
  - (B) Retire: `git tag -a archive/refactor-strategy-math-6d6790f 6d6790f30314cb6943450c81a3bc4ecea67b7c78 -m "Unmerged, unreviewed analyzer rewiring; retired <date> by owner decision"`.
  - **Either way**, the owner must also decide what happens to the identical uncommitted `analyzer/technical_analyzer.py` in the production checkout. Restoring the committed file is a host change that needs separate approval. Until then, never build images from that directory.
- **`safety/disable-auto-tune@3d1857d`:**
  - (A) Port it onto current `main` as a fresh PR branch: resolve the `shared/config.py` conflict and re-run its 2 test files.
  - (B) Retire: `git tag -a archive/safety-disable-auto-tune-3d1857d 3d1857d8e2cdec320f722f2a784a5fb3dab691ef -m "Auto-tune kill-switch (ENABLE_AUTO_TUNE) not merged; optimizer disabled by compose profile; retired <date>"`.
  - Never merge the stale branch itself: it is 44 commits behind.
- **P1 `feature/forward-instrumentation@23dea90`:** keep it. It is merged only through its own release-gated PR (ADR-002; it changes `docker-compose.yml`, so it is effectively a deployment change). It is not part of the cleanup.
- **Push each archive tag individually:** `git push origin refs/tags/archive/<name>`.
- **Verify:** `git cat-file -t` gives `tag`, `rev-parse <tag>^{commit}` equals the branch SHA, and `ls-remote` shows the tag.
- **Recovery:** delete and re-create the tag before its branch is deleted.

### Step 4: Governance docs PR #3
- **Preconditions:** owner review. The PR is draft, docs-only (9 files, +287/−32), mergeable `clean`, and has no file overlap with P1.
- **Option 1 (preferred):** mark it ready (`gh pr ready 3`) and merge it into `develop`.
  - Merge commit or squash; squash is acceptable because it is docs-only.
  - Then run step 5, and the governance lands on `main` together with everything else.
- **Option 2:** do step 5 first, then retarget with `gh pr edit 3 --base main`. This **must** happen before `develop` is deleted, or GitHub closes the PR.
- **Verify:** `git diff --stat <pre-merge-develop> origin/develop` touches only `CLAUDE.md` and `docs/product/*`.
- **Recovery:** the GitHub "Revert" button, which opens a revert PR. No force-push.

### Step 5: Promote `develop` into `main` through a PR (not locally)
- **Preconditions:**
  - Steps 1 and 2 verified.
  - `git merge-base --is-ancestor origin/main origin/develop` is true. Today: main 44 behind, 0 ahead, `git cherry` 0.
  - **`main`'s own unique commits: none.** The only content that exists on `main` and differs is the older `.dockerignore` (44 B vs 132 B on develop), which develop's version supersedes. `monitor_canary.py` and `deploy/` arrive from develop. The PR #1/#2 merge commits `7fc4a7c`/`c7b5ecb` are already ancestors of both.
- **Commands:**
  ```bash
  gh pr create --repo $R --base main --head develop \
    --title "Promote develop to main (ADR-011 consolidation)" \
    --body "Fast-forward-equivalent promotion; main has 0 unique commits. Not a deployment."
  gh pr merge <N> --repo $R --merge      # "Create a merge commit" ONLY. Never --squash / --rebase. Do NOT pass --delete-branch.
  ```
  GitHub's squash **and** rebase methods always create new SHAs. The baseline `3ed49c3`, B3 `8bfca77`, P1's base and all SHAs in the deploy manifest would then not be reachable from `main`.
- **Alternative, still not a local merge:** the owner can fast-forward the ref with `gh api -X PATCH repos/$R/git/refs/heads/main -f sha=<develop-sha> -F force=false`. This gives identical SHAs and no merge commit, but it is not a PR. Use it only if the owner explicitly prefers it.
- **Verify** (after an approved `git fetch origin`):
  ```bash
  git merge-base --is-ancestor 4e3eb0ae82b2bf0ea7b954f00c9b8da5469a8b76 origin/main && echo DEVELOP-IN-MAIN
  git merge-base --is-ancestor 3ed49c306ce404359c94ee549dd24b431be2a558 origin/main && echo BASELINE-IN-MAIN
  git diff --quiet origin/develop origin/main && echo "main tree == develop tree"
  gh api repos/$R/compare/main...develop --jq '{status,ahead_by,behind_by}'   # ahead_by 0
  docker ps --format '{{.Names}} {{.Image}}'   # unchanged vs DEPLOYED_MANIFEST (proves no deployment happened)
  ```
- **Recovery:**
  - Preferred: a revert PR of the merge commit.
  - `main`'s old tip `0a396c2` stays preserved in 3 places: the local tag `snapshot-live-learning-0a396c2`, the `snapshot` repo, and both bundles.
  - Force-resetting `main` needs explicit owner approval.

### Step 6: Default branch and repository settings (owner-approved GitHub settings; no host impact)
- **Default branch:** it is already `main`, so there is no switch to make. Just verify `gh api repos/$R --jq .default_branch`.
- **Settings to propose:**
  - `delete_branch_on_merge=true` (Settings → General → "Automatically delete head branches"), to enforce the temporary-branch rule.
  - Protection or ruleset on `main`, if the plan permits it on a private repo: require a PR, block force-push and deletion. Do **not** require linear history, because merge commits are the chosen method.
  - Optionally disable "Allow rebase merging".
- **Deploy key `server-signalbot-rw` (write):** decide whether to keep it write-enabled or make it read-only. A read-only key would stop host-side pushes of PR branches; a protected `main` limits the damage if it stays write.
- **Verify:** `gh api repos/$R --jq '{default_branch,delete_branch_on_merge}'`, and `gh api repos/$R/rules/branches/main`.
- **Recovery:** revert the settings in the UI.

### Step 7: Update references (docs, scripts, deploy notes) through PRs to `main`
- **Docs PR:**
  - `GIT_GUIDE.md` and `SETUP_GUIDE.md`: GitFlow with `dev`, Raspberry Pi, direct pushes to `main`.
  - `docs/claude/operations.md:34-39` (`git push origin main`) and `:6-8` (whole-stack `down/build/up -d`).
  - `README.md` and `docs/claude/architecture.md`: missing services, and a non-existent `continuous_learner/` directory.
  - Banners on the canary and handoff docs that point at `integration/research-pipeline`.
  - A new `DEV_LOG.md` entry.
  - Details are in §4.5 and §7.4.
- **Script PR** (reviewed; not deployed by itself):
  - Guard or remove the bare `docker compose up -d` in `setup.sh:52`.
  - Cosmetic text in `research/ops/canary_watchdog.py:91`.
- **CI:** none exists, so there is nothing to update.
- **Host (separate approval, never bundled with GitHub steps):**
  - Crontab entries reference paths, not branch names, so they need **no change**.
  - `/home/tradmin/tsb-develop` must be switched to `main` or removed before `develop` can be deleted locally.
  - The production checkout stays on `integration/research-pipeline` until an owner-approved release plan repoints it. Its dirty tree, `data/evidence` bind mount, `.venv` and `.env` must move first.
- **Backup documents:** Phase-0 `COVERAGE.md` line 30 (`git worktree add … fix/b3-fail-closed-trading-state`) should use `8bfca77` or `prod-baseline-2026-09-27^` once the branch is gone. `RECOVERY.md:50` clones from the immutable bundle and is unaffected.
- **Verify:** `git grep -nE 'git push origin main|integration/research-pipeline' origin/main -- '*.md' '*.sh' '*.py'` → only intentional historical mentions remain.

### Step 8: Delete obsolete branches, in waves (§9 has the per-branch evidence and recovery)
- **Remote deletion, per branch:**
  ```bash
  b=<branch>; sha=$(git rev-parse "refs/remotes/origin/$b")           # after approved fetch
  git merge-base --is-ancestor "$sha" origin/main && echo CONTAINED-IN-MAIN
  git bundle list-heads "$B" | grep -q "$sha" && echo IN-BUNDLE    # or ancestor of a bundle head
  test "$(gh api "repos/$R/pulls?state=open&head=baljadrawy:$b" --jq length)" = 0 && echo NO-OPEN-PR-FROM
  test "$(gh api "repos/$R/pulls?state=open&base=$b" --jq length)" = 0 && echo NO-OPEN-PR-INTO
  echo "$sha $b" >> "$D/deleted-branches.txt"
  git push origin --delete "$b"       # UI alternative: Code → Branches → trash icon
  ```
- **Local deletion:** `git branch -d <b>`, never `-D` for these. `-d` refuses unless the branch is merged into HEAD, so run it from a worktree whose HEAD contains it (`develop` today, `main` later).
  - A branch checked out in a worktree must first be released: `git worktree remove <path>`, or `git worktree prune` for the stale `/tmp` B3 worktree. That is a host change and needs approval.
- **Order:**
  - **Wave A:** `dev`, `feat/py312-feature-store-audit-2026-06-23`, `feat/throttle-decay-2026-08-10`, `fix/loss-streak-recovery-epoch`.
  - **Wave B:** `deploy/baseline-2026-09-27` and `fix/b3-fail-closed-trading-state`, after step 2.
  - **Wave C:** remote `integration/research-pipeline`, after step 7.
  - **Wave D:** the 10 local-only branches.
  - **Wave E:** `develop`, last. Preconditions: step 5 verified, PR #3 merged or retargeted, the P1 PR (if open) retargeted to `main`, `tsb-develop` released, docs no longer name `develop` as the integration branch, and owner approval.
- **After each wave:** a `git fetch --prune origin` (approved) clears stale remote-tracking refs. Then re-verify with `gh api "repos/$R/branches?per_page=100" --jq '.[].name'`.

### Step 9: Enforce the steady state
- **Branches:** `main` is the only permanent branch. Feature, fix and docs branches are PR-only and auto-deleted on merge. Releases and rollbacks use annotated tags (`prod-baseline-*`, `archive/*`).
- **Expected GitHub branch list after cleanup:** `main` plus only live PR branches: P1 until merged, and `refactor`/`safety` only while an owner decision is pending.
- **Production check:** the 7 container image IDs still equal `DEPLOYED_MANIFEST.json`, and the production checkout status count is unchanged. The audit measured 111 porcelain entries.

## 9. Deletion list (proposed; nothing deleted; owner sign-off required per item)

**Legend:**
- **⊂dev** / **⊂main** = `git merge-base --is-ancestor <sha> <branch>`, as of this audit.
- **P0** = exact head in the Phase-0 bundle `/home/tradmin/backups/tsb-phase0-20260927/git/trading-signal-bot-all-refs-20260927.bundle`, which passes `git bundle verify` and matches its recorded sha256.
- **Every item also requires the new step-1 bundle.**
- `git cherry develop <ref>` returned 0 unique patches for every branch in 9.1.

**Generic recovery for any deleted branch:**
- From the object store, while the SHA is reachable: `git push origin <full-sha>:refs/heads/<name>` (remote) or `git branch <name> <full-sha>` (local). All SHAs below stay reachable from `main` (after step 5) and from `prod-baseline-2026-09-27`, so `git gc` will not drop them.
- From a bundle, in a scratch clone: `git clone --mirror <bundle> /tmp/r.git && git -C /tmp/r.git push git@github.com:baljadrawy/trading-signal-bot.git <sha>:refs/heads/<name>`, or `git fetch <bundle> refs/heads/<name>:refs/heads/<name>`.
- For branches deleted through a merged PR, GitHub also offers a "Restore branch" button on the PR page.

### 9.1 Branches: delete (after the stated preconditions)
| # | Wave | Ref (scope) | Full SHA | ⊂dev | ⊂main now | P0 | Blockers / dependencies | Risk | Precondition |
|---|---|---|---|---|---|---|---|---|---|
| 1 | A | `dev` (remote only; no local branch) | `c7e9b88e8ff2b58583dce9e52c661ef7620face3` | Y (189 behind) | **Y** | Y (`origin/dev`) | Head of merged PRs #1/#2. `refs/pull/*` are kept by GitHub. Only the obsolete `GIT_GUIDE`/`SETUP_GUIDE` GitFlow mentions a `dev` branch. | very low | step 1 |
| 2 | A | `feat/py312-feature-store-audit-2026-06-23` (remote + local) | `d91fd500289e6bcbc969b76d84c9f3624d9eb7d4` | Y (63) | **Y** | Y | No worktree. 0 references in `develop`. | very low | step 1 |
| 3 | A | `feat/throttle-decay-2026-08-10` (remote + local) | `912b51aa351a646ee335e6add48e160dce0365e4` | Y (18) | N (Y after step 5) | Y | No worktree. 0 references. | very low | steps 1, 5 |
| 4 | A | `fix/loss-streak-recovery-epoch` (remote + local) | `05999eacf2c8fd612aadb210ee2ae1adbbb536c8` | Y (9) | N (Y after step 5) | Y | Deployed `shared/trading_state.py` in signal_engine/analyzer = blob @`05999ea`; the manifest cites the SHA, not the branch. 0 branch-name references. | low | steps 1, 5 |
| 5 | B | `deploy/baseline-2026-09-27` (remote + local) | `3ed49c306ce404359c94ee549dd24b431be2a558` | Y (7) | N (Y after step 5) | **N** | **Rollback anchor.** Local branch pinned by worktree `/home/tradmin/tsb-baseline`. The record README calls itself "this branch" (immutable text; leave it). | **high before the tag**, low after | steps 1, **2 verified**, 5; worktree released (host approval) |
| 6 | B | `fix/b3-fail-closed-trading-state` (remote + local) | `8bfca778b42fa5c29993d5c57bf1674ae755522f` | Y (8) | N (Y after step 5) | Y | Source of the deployed B3 overlay (tracker/telegram). It equals `prod-baseline-2026-09-27^`. Local branch pinned by the `/tmp/…/scratchpad/b3-worktree` (ephemeral). Phase-0 `COVERAGE.md:30` names the branch. | low after the tag | steps 1, 2, 5; `git worktree prune`/`remove` (host approval) |
| 7 | C | `integration/research-pipeline` (**remote only**) | `63da7d31daef2b952c695b256f81cf174b6451a8` | Y (10) | N (Y after step 5) | Y | Deployed images were built from its lineage (manifest cites `63da7d3`). **The local branch is checked out in the production checkout: do NOT delete it locally** until an approved release plan repoints `/home/tradmin/trading-signal-bot`. Canary docs, the handoff doc, DEV_LOG and `canary_watchdog.py:91` mention the name. | low (remote) | steps 1, 5, 7 (docs) |
| 8 | D | `fix/report-net-fees-2026-07-29` (local only) | `f9dbc775874ec3bfc56f35a2fb8f765af735814c` | Y | N | Y | never pushed; no worktree | very low | step 1 |
| 9 | D | `fix/neutralize-4f84717-2026-07-29` (local only) | `cdd3450a1d9932e83563e3b9f8baa6b8eccd873e` | Y | N | Y | same | very low | step 1 |
| 10 | D | `fix/fee-net-gate-2026-07-29` (local only) | `1d090be398a233f32522657d7a3914bb4a7de493` | Y | N | Y | same | very low | step 1 |
| 11 | D | `fix/measurement-layer-2026-07-15` (local only) | `c2725a96352ba980cdc07331c198c4ff8283efc0` | Y | N | Y | Named only in historical `docs/superpowers/{plans,specs}/2026-07-15-measurement-layer-fix*.md` | very low | step 1 |
| 12 | D | `research/evidence-capture-filter` (local only) | `928ff1a07963e4861bd13409a257e47fb2301f3e` | Y | N | Y | never pushed | very low | step 1 |
| 13 | D | `research/recorder-hardening` (local only) | `f72d623a8d397f8d71470c72eea33da5e6c7dc6e` | Y | N | Y | never pushed | very low | step 1 |
| 14 | D | `research/flight-recorder` (local only) | `7b45a8f2db3ea657c2af6beee33d4d5c5312d318` | Y | N | Y | never pushed | very low | step 1 |
| 15 | D | `research/null-a-evidence-store` (local only) | `2ec84fd37e04919cc43a7785122179a91ddb645a` | Y | N | Y | never pushed | very low | step 1 |
| 16 | D | `research/health-monitor` (local only) | `5157ca9b59872fd2133c79fe7f8757a7bf7ab662` | Y | N | Y | never pushed | very low | step 1 |
| 17 | D | `research/falsification-library` (local only) | `bf7b0a1dc4f009aa7729fa8c3278831b0397d5c2` | Y | N | Y | never pushed | very low | step 1 |
| 18 | **E (last)** | `develop` (remote + local) | `4e3eb0ae82b2bf0ea7b954f00c9b8da5469a8b76` | – | N (Y after step 5) | **N** | **The only path to all deployed blobs until `main` contains it.** It is the base of PR #3 and the parent of P1/refactor. Local branch pinned by `/home/tradmin/tsb-develop`. | **high if early**, low after the preconditions | steps 1–7 verified; PR #3 merged or retargeted; P1 PR retargeted; worktree released |

**Deletion commands** (after the preconditions and approval):
- Waves A–C and E: `git push origin --delete <name>`.
- Local twins and wave D: `git branch -d <name>`, run from a worktree whose HEAD contains the branch.
- Record `<sha> <name>` in `$D/deleted-branches.txt` **before** each deletion.

### 9.2 Branches: do NOT delete now (conditional)
| Ref | Full SHA | Why not | When it may be deleted | Loss if deleted today |
|---|---|---|---|---|
| `main` | `0a396c2a30d3b0d8fe4209b156ed27b89e017efc` | Canonical target and GitHub default | never | – |
| `feature/forward-instrumentation` (P1) | `23dea904a852e71c3b00414fc06a45417ada2792` | +1 unique commit (22 files, +3163/−13, including a `docker-compose.yml` bind mount). Not merged or deployed. Not in any bundle. | After its release-gated PR merges (auto-delete) | the whole P1 implementation |
| `refactor/strategy-math` | `6d6790f30314cb6943450c81a3bc4ecea67b7c78` | +1 unreviewed commit (`technical_analyzer.py` +7/−139). It is the only committed copy of the change that sits uncommitted in the production checkout. Not in any bundle. | After an owner decision: PR (then auto-delete), or `archive/refactor-strategy-math-6d6790f` tag + delete | the analyzer rewiring, and provenance of the production-checkout diff |
| `safety/disable-auto-tune` | `3d1857d8e2cdec320f722f2a784a5fb3dab691ef` | +1 unique commit: the ENABLE_AUTO_TUNE kill-switch plus 2 test files, which exist nowhere else. Diverged from main (44 behind). It is in P0. | After an owner decision: port to a fresh PR, or `archive/safety-disable-auto-tune-3d1857d` tag + delete | the only code-level auto-tune kill-switch |
| `docs/market-intelligence-governance-20260927` (GitHub only, PR #3) | `2ffb44b80b79c90c37de8f29020b94c0af949fc3` | +21 docs commits (ADR-001…011, charter, consolidation plan). **Single copy on GitHub:** never fetched, in no bundle. | After PR #3 merges (auto-delete) | the owner's governance record |

### 9.3 Tags, remotes, images, worktrees
- **Tags to delete: none.** Keep the local lightweight `snapshot-live-learning-0a396c2` (→ `0a396c2`). It is also preserved in `/home/tradmin/backups/signal-bot-live-learning-0a396c2.bundle` and the private repo `baljadrawy/signal-bot-live-learning-snapshot`. Optionally the owner can publish it as an annotated `archive/` tag.
- **Tags to add:** `prod-baseline-2026-09-27` (§5). `archive/*` only for branches the owner retires (§8 step 3).
- **Remote `snapshot`:** keep (archival mirror). Removing the local remote config is optional and an owner decision.
- **Docker images: delete none.** Keep all 5 rollback anchors, the 3 `b3prep-*:candidate` tags and the running images. Never run `docker image prune -a` as part of this cleanup.
- **Worktrees** (host changes, separate approval, only when their branch is being deleted):
  - `/home/tradmin/tsb-baseline` (wave B)
  - the `/tmp/…/scratchpad/b3-worktree` (wave B; `git worktree prune` once the directory is gone)
  - `/home/tradmin/tsb-develop` (before wave E)
  - `/home/tradmin/tsb-refactor` and `/home/tradmin/tsb-p1` (after their decisions)
  - **The production checkout `/home/tradmin/trading-signal-bot` is never part of this cleanup.**

### 9.4 Files: one cleanup PR on `main`, after step 5, separate from branch consolidation
| # | Path (tracked on develop, main, 63da7d3, 3ed49c3) | Class | Evidence | Risk | Recovery |
|---|---|---|---|---|---|
| F1 | `docker-compose.yml.bak` | SAFE-TO-REMOVE | Pre-hardening compose (no `continuous_learner`, no `security_opt`/`cap_drop`/`tmpfs`). Zero references anywhere. | low; removing it prevents an accidental unhardened stack | `git show prod-baseline-2026-09-27:docker-compose.yml.bak` |
| F2 | `analyzer/backtest_part30.py` | SAFE-TO-REMOVE | Byte-identical to `analyzer/backtest_part30_schema_reconciliation.py` (blob `937924750f`). 0 importers, 0 references. | none | same pattern |
| F3 | `analyzer/research/entry_reverse_engineer.py` | SAFE-TO-REMOVE | = `research/entry_reverse_engineer.py` (`27f1e14b3b`). 0 importers. Reports cite the kept path. | none | same |
| F4 | `analyzer/research/scripts/entry_filter_test.py` | SAFE-TO-REMOVE | = `research/scripts/entry_filter_test.py` (`6e7f86eeee`) | none | same |
| F5 | `analyzer/research/scripts/killzone_causal_v2.py` | SAFE-TO-REMOVE | = `research/scripts/killzone_causal_v2.py` (`d1024ce5b3`). One report citation is path-ambiguous but the code is identical; note the mapping in the PR. | none | same |
| F6 | `analyzer/research/entry_methodology_report.md` | SAFE-TO-REMOVE | = `research/entry_methodology_report.md` (`9e3426d2f0`) | none | same |
| F7 | `analyzer/research/entry_filter_causal_test_2026_05_20.md` | SAFE-TO-REMOVE | = `research/entry_filter_causal_test_2026_05_20.md` (`ddfec4fe31`) | none | same |
| F8 | `database/migrate.sql` | SAFE-TO-REMOVE | Zero references. `setup.sh` runs `database/migrate.py`, which applies `migrations/NNN_*.sql`. All 4 tables it creates already exist in `init.sql`/`migrations/`. | low | same |
| (F9) | `analysis_output.txt` | low risk, **owner sign-off** | Stale console output of `backtest_part40_edge_discovery_v2.py`; no reader | low (research output) | same |

**How to remove:** `git rm <paths>` on a short-lived branch from `main`, then a PR reviewed by the owner and a merge commit. **Test impact:** none; no test imports these files. **Production impact:** none; none is in any Dockerfile COPY, compose file, cron job or `deployed_files.json`. **Recovery:** revert the PR, or restore from the tag, history or bundle.

**Explicitly NOT on the deletion list (NEEDS-OWNER-DECISION or KEEP; see §6.6, §7):**
- The 107 `analyzer/*.py` research scripts, which produced sealed verdicts.
- The `analyzer/**` `.pkl` caches (105 MB) and result CSVs/JSONL, which are evidence.
- `backtest_results_part40.jsonl`, `indicator_perf_report.txt` and `analyzer/backtest_results_part33.jsonl.bug`.
- `optimizer/*` (disabled; the safety branch depends on the decision).
- `colab/*`. It writes the production DB, and external use cannot be excluded.
- The dated one-shot migrations, which are the only DDL for 3 tables.
- `research/skill_application/**`. Its untracked `.venv` runs the active canary-watchdog cron.
- `research/falsification`, `research/monitoring`, `monitor_canary.py` and `setup.sh` (rewrite, not delete).
- The stale docs (rewrite or archive).
- All untracked evidence in the production checkout: 91 files in no git ref, including `data/evidence/*.jsonl`. **Never delete these as part of Git cleanup.**

## 10. Owner decisions required, open questions and audit limitations

### 10.1 Approvals required (ADR-011: none is implied by this audit)
| ID | Decision | Blocks |
|---|---|---|
| A1 | Approve `git fetch origin` (no prune) and the fresh all-refs bundle, plus a decision on an **off-host** copy (currently blocked). | everything |
| A2 | Approve creating and pushing the annotated tag `prod-baseline-2026-09-27` → `3ed49c3` (§5). | waves B and E |
| A3 | PR #3: review and merge into `develop` first (preferred), or retarget it to `main` after step 5. | step 5 / wave E |
| A4 | Approve the `develop → main` PR with **merge-commit** method only (no squash or rebase). | waves C–E |
| A5 | `refactor/strategy-math`: review plus a runtime parity test and a PR, **or** retire with an archive tag. Also decide what to do with the identical uncommitted `analyzer/technical_analyzer.py` in the production checkout; until then, no image builds from that directory. | its deletion |
| A6 | `safety/disable-auto-tune`: port it as a fresh PR onto `main` (resolving the `shared/config.py` conflict), **or** retire it with an archive tag. | its deletion |
| A7 | P1 `feature/forward-instrumentation`: a separate release-gated decision (ADR-002, SINGLE_HOST_SAFETY §7). Not part of the cleanup. | P1 branch deletion |
| A8 | Approve the branch deletion waves A–E (§9.1). | – |
| A9 | GitHub settings: `delete_branch_on_merge`, protection or ruleset on `main` (plan permitting), deploy-key scope (`server-signalbot-rw` is write), merge-method restrictions. | steady state |
| A10 | Host changes, separate from GitHub: release or prune worktrees (`tsb-baseline`, `/tmp` b3-worktree, `tsb-develop`, later `tsb-refactor`/`tsb-p1`). **The production checkout is excluded.** | local deletions |
| A11 | File-cleanup PR: the SAFE list F1–F8 (plus F9), `.gitignore` rule fixes, and separate decisions for each NEEDS-OWNER-DECISION group (analyzer research archive, pkl caches, optimizer, colab, migrations fold-in, docs rewrite and archive). | – |
| A12 | Keep `cron-signal-bot-review.sh` paused until it is rewritten to push PR branches only (it currently commits and pushes directly on the checked-out branch). | steady state |

### 10.2 Open questions
1. **GitHub plan.** Is the owner account on GitHub Pro? Branch protection and rulesets on private repos need it, and the plan is not visible to this token.
2. **Colab.** Is `colab/daily_training.*` still scheduled externally? It writes `indicator_weights`/`learning_log` to the production DB.
3. **Off-host backup.** Where should the off-host copy of the new bundle and image tar live? This is a pre-existing owner-blocked item.
4. **Merge commit vs fast-forward.** For the `develop → main` promotion, does the owner accept a merge commit (PR, recommended), or prefer the equivalent-SHA fast-forward ref update (not a PR)?
5. **Analyzer research code.** Should the 107 analyzer research scripts move to a `research/archive/` path (history preserved), or be retired behind an archive tag?

### 10.3 Limitations of this audit
- **Import analysis is static and file-level.** It cannot see non-literal dynamic imports, `exec`, scripts `docker cp`-ed into containers, or external callers (Colab, shell history). Function-level dead code inside reachable modules was not analysed.
- **Evidence was not opened.** Sealed evidence, research results, `*.jsonl`/`*.csv` and `.env` files were deliberately not opened, so their contents were not assessed.
- **PR #3 was not fetched.** `2ffb44b` was inspected only through the GitHub compare and contents APIs.
- **Nothing was executed.** No builds, tests or parity runs. The "pure refactor" assessment of `6d6790f` comes from reading the code.
- **Point-in-time snapshot** (2026-09-27, around 23:00 +0200). Re-run the ahead/behind and `ls-remote` checks immediately before every step.

## 11. Evidence index (reproducible, read-only)
- **Refs:**
  - `git --no-optional-locks for-each-ref --format='%(refname)|%(objectname:short=10)|%(committerdate:iso8601)|%(authorname)|%(upstream:short)'`
  - `git ls-remote origin`, and the same for `snapshot`
  - `git worktree list`
- **Ahead/behind and containment:**
  - `git rev-list --left-right --count develop...<ref>` (and `main...<ref>`)
  - `git merge-base --is-ancestor <ref> develop`
  - `git cherry develop <ref>`
  - GitHub `compare/develop...<branch>`
- **GitHub (GET):**
  - `repos/$R`, `branches`, `tags`, `releases`, `pulls?state=all`
  - `branches/{main,develop}/protection` (404), `rulesets` (`[]`), `rules/branches/*` (`[]`)
  - `actions/workflows` (0), `actions/runs` (0), `deployments` (0), `environments` (0), `hooks` (0), `keys` (1)
  - `contents/docs/product/*?ref=docs/market-intelligence-governance-20260927`
- **Deploy:**
  - `/home/tradmin/tsb-baseline/deploy/baseline-2026-09-27/{README.md,DEPLOYED_MANIFEST.json,deployed_files.json,unmatched/}`
  - `docker inspect --format` (labels, image and mounts only)
  - `docker image ls`
  - the redacted crontab grep (§4.4)
- **Backups:**
  - `git bundle verify` / `list-heads` on the Phase-0 bundle (27 refs) and `signal-bot-live-learning-0a396c2.bundle`
  - sha256 of the Phase-0 image tar checked against `MANIFEST-INDEX.txt`
- **Code:**
  - a stdlib AST import graph over the 345 tracked `.py` files on `develop`, with reachability from Dockerfile CMDs, compose, cron and runbooks
  - per-image requirements compared against imports
  - helper scripts kept in the auditor's ephemeral session scratchpad (`code_audit/`), not committed
- **Hygiene:**
  - `git ls-tree -r -l develop`
  - `git rev-list --objects --all | git cat-file --batch-check`
  - `git check-ignore --no-index`
  - `git --no-optional-locks status --porcelain=v1 --ignored` (names only)
  - `git hash-object` (without `-w`) for dirty-file matching

## Appendix A. Candidate table: every non-production, non-test `.py` file (250 rows)
class = import-reachability class. Evidence: importers = files importing it; str-refs = other tracked text files (plus redacted crontab) that mention its path, basename or module path.

| path | class | evidence | last commit | size B | recommendation | reason |
|---|---|---|---|---|---|---|
| `analyzer/backtest_part30.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5000 | **SAFE-TO-REMOVE** | byte-identical blob duplicate of `analyzer/backtest_part30_schema_reconciliation.py` (kept copy); no importers |
| `analyzer/research/entry_reverse_engineer.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=3; touches 4 tracked data/report file(s) | 2026-05-20 | 32439 | **SAFE-TO-REMOVE** | byte-identical blob duplicate of `research/entry_reverse_engineer.py` (kept copy); no importers |
| `analyzer/research/scripts/entry_filter_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=3; touches 4 tracked data/report file(s) | 2026-05-20 | 27940 | **SAFE-TO-REMOVE** | byte-identical blob duplicate of `research/scripts/entry_filter_test.py` (kept copy); no importers |
| `analyzer/research/scripts/killzone_causal_v2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1; touches 1 tracked data/report file(s) | 2026-05-21 | 33574 | **SAFE-TO-REMOVE** | byte-identical blob duplicate of `research/scripts/killzone_causal_v2.py` (kept copy); no importers |
| `analyzer/attr_fix.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 1342 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_fixed_template.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 27326 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_imbalance.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-06-13 | 4584 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_killzone_analysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-13 | 21740 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part1.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1; touches 1 tracked data/report file(s) | 2026-05-16 | 9202 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part10_trend_ok_relaxation.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-17 | 8042 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part11_fee_slippage.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-17 | 11116 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part12_1d_score_cap.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-17 | 6660 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part13_smc_ohlc.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-17 | 29939 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part14_hyperopt_fee_adj.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-18 | 14677 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part15_feature_lab_strict.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-18 | 26363 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part16_cost_leverage.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-18 | 15284 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part17_symbol_edge.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-18 | 11054 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part18_indicator_combos.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-18 | 12560 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part19_forward_validation.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-19 | 8016 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-05-16 | 13236 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part20_timing_analysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-19 | 7965 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part21_signal_quality_rsi_div.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-19 | 9618 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part22_sl_atr_analysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-19 | 10428 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part23_forward_validation_v2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-20 | 10276 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part24_indicator_pattern_post_freeze.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-20 | 8671 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part25_stoch_rsi_filter.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-20 | 14609 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part26_post_freeze_pattern.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-21 | 7634 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part27_concentration_and_market_silence.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-21 | 11196 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part28_rejection_pattern_analysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-21 | 10937 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part29_score_band_drift.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-21 | 15180 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part3.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-05-16 | 9187 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part30_schema_reconciliation.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-22 | 5000 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part31_bearish_vs_sideways.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-23 | 6019 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part32_rsi_div_bootstrap.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-24 | 13344 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part33_smc_unified.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-06-13 | 17534 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part33_smc_unified_v2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-05-25 | 24285 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part34_wide_rr_isolation.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-13 | 13965 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part35_ichimoku_advanced.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-06-13 | 10902 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part36_sensitivity_tuning.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-13 | 6751 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part37_smc_advanced_ohlc.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-05-27 | 40144 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part38_wide_rr_isolation.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-05-27 | 33600 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part39_smc_advanced_validation.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 14081 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part4.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-05-16 | 15188 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part40_edge_discovery_v2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-13 | 12212 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part41_feature_importance.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 3591 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part42_stochastic_rsi.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 3290 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part44_stop_policy.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 21973 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part45_stoch_combo_walkforward.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-11 | 9953 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part46_volume_stoch_confirmation.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-11 | 6011 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part47_combo_amplifiers.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-11 | 6138 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part48_order_imbalance_cluster.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-22 | 2614 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part49_volatility_microstructure.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-22 | 6589 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part5.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 3 tracked data/report file(s) | 2026-05-16 | 11246 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part50_final_edge_verdict.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-13 | 6559 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part6_hyperopt.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-05-16 | 15141 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part7_rsi_filter_validation.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-17 | 9543 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part8_feature_lab.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 4 tracked data/report file(s) | 2026-05-16 | 28090 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_part9_hyperopt_full.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-17 | 10877 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_rsi_band_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 13888 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/backtest_volume_rsi_mtf.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-06-13 | 17161 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/basis_decomp.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5782 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/bear_side_full.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 3120 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/bear_side_hope_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 3435 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/bt_download.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 1849 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/bt_engine.py` | UNREFERENCED-BY-IMPORT | importers=24; str-refs=0 | 2026-06-13 | 11959 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/capacity_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 7765 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/check_status.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 1830 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/check_status_cycle21.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-14 | 1781 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/check_stoch_cycle21.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-14 | 1947 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/check_threshold.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 440 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/combo_robustness.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 6326 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/concentration_check.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 4045 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/cycle22_analysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-22 | 5572 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/detailed_check.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 1846 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/factor_attribution.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1 | 2026-06-13 | 6131 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/families_engine.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 6358 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/fut_download.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 1720 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/fut_engine.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 10363 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/fut_verify.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 3704 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/futures_coverage.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 2411 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/ict_validation_screen.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-13 | 5931 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/indep_verify.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=2 | 2026-06-13 | 7207 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/indicator_perf_analysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-13 | 9484 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/model_compare.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5381 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/momentum_ls.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 4569 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/momentum_mvp.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5065 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/momentum_oos.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5645 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/momentum_stress.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5779 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/momentum_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 3797 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/oi_diag.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 3025 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/oi_download.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 1568 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/oi_engine.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 6648 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/oi_refined.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5274 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/part35_smc_advanced_v3.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-23 | 7474 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/part43_stochastic_rsi_validation.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 2316 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/part44_smc_advanced_v2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 909 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/part45_mfe_wide_rr.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-21 | 11102 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/part46_smc_ohlc_real.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-21 | 9157 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/period_dissection.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 6479 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/phase_check.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 2645 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/phase_check_full.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 2713 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/phase_robustness.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5389 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/reduced_score_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 3529 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/research/scripts/edge_discovery_clean.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 39841 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/research/scripts/edge_discovery_v2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 31387 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/research/scripts/edge_discovery_v3.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-05-22 | 31361 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/research/scripts/edge_discovery_v4_vwap_rs.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 27241 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/research/scripts/ict_structural_causal.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-21 | 31206 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/research/scripts/ict_structural_causal_v3.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-05-22 | 43790 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/rolling_wf.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 6239 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/score_inversion_attribution.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 4506 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/source_analysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5118 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/surv_diag.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 1049 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/survivorship_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5127 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/tranche_correct.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 5520 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/turn_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 2818 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `analyzer/turn_test2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 2789 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `colab/daily_training.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-04-14 | 8588 | **NEEDS-OWNER-DECISION** | legacy Colab trainer (Apr 2026), zero repo refs, UPDATEs indicator_weights in prod DB via SSH tunnel (conflicts with freeze); external Colab use cannot be ruled out from host — recommend remove |
| `optimizer/__init__.py` | DORMANT-SERVICE | importers=1; str-refs=0 | 2026-04-14 | 0 | **NEEDS-OWNER-DECISION** | optimizer service: compose profile "disabled" since 2026-06-19 (freeze); not in deployed baseline; retire vs keep |
| `optimizer/analyzer.py` | DORMANT-SERVICE | importers=1; str-refs=1 | 2026-06-20 | 11187 | **NEEDS-OWNER-DECISION** | optimizer service: compose profile "disabled" since 2026-06-19 (freeze); not in deployed baseline; retire vs keep |
| `optimizer/main.py` | DORMANT-SERVICE | importers=0; str-refs=25 | 2026-06-20 | 6266 | **NEEDS-OWNER-DECISION** | optimizer service: compose profile "disabled" since 2026-06-19 (freeze); not in deployed baseline; retire vs keep |
| `optimizer/tuner.py` | DORMANT-SERVICE | importers=1; str-refs=2 | 2026-08-17 | 7108 | **NEEDS-OWNER-DECISION** | optimizer service: compose profile "disabled" since 2026-06-19 (freeze); not in deployed baseline; retire vs keep |
| `research/entry_reverse_engineer.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=3; touches 4 tracked data/report file(s) | 2026-05-20 | 32439 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `research/falsification/__init__.py` | TEST-ONLY | importers=7; str-refs=0 | 2026-06-28 | 514 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/falsification/bootstrap.py` | TEST-ONLY | importers=2; str-refs=1 | 2026-06-28 | 1340 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/falsification/core.py` | TEST-ONLY | importers=1; str-refs=0 | 2026-06-28 | 4692 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/falsification/metrics.py` | TEST-ONLY | importers=7; str-refs=1 | 2026-06-28 | 1512 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/falsification/monte_carlo.py` | TEST-ONLY | importers=1; str-refs=0 | 2026-06-28 | 955 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/falsification/oos.py` | TEST-ONLY | importers=1; str-refs=0 | 2026-06-28 | 1176 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/falsification/random_null.py` | TEST-ONLY | importers=3; str-refs=2 | 2026-06-28 | 1356 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/falsification/remove_best.py` | TEST-ONLY | importers=2; str-refs=1 | 2026-06-28 | 879 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/falsification/walk_forward.py` | TEST-ONLY | importers=1; str-refs=0 | 2026-06-28 | 1182 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/monitoring/__init__.py` | TEST-ONLY | importers=1; str-refs=0 | 2026-06-28 | 561 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/monitoring/health.py` | TEST-ONLY | importers=2; str-refs=2 | 2026-06-28 | 7606 | **NEEDS-OWNER-DECISION** | shadow-only library (robustness PR ladder #2/#3), tested, not wired to any service |
| `research/scripts/entry_filter_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=3; touches 4 tracked data/report file(s) | 2026-05-20 | 27940 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `research/scripts/fvg_census.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-13 | 5929 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `research/scripts/fvg_ic_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-13 | 11873 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `research/scripts/ict_structural_causal.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1; touches 1 tracked data/report file(s) | 2026-05-21 | 32618 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `research/scripts/killzone_causal_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-13 | 30171 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `research/scripts/killzone_causal_v2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1; touches 1 tracked data/report file(s) | 2026-05-21 | 33574 | **NEEDS-OWNER-DECISION** | research script (not in any image/cron/runbook); reproducibility of recorded research verdicts |
| `research/skill_application/scripts/a1_leak_decomp.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 8115 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/a1_verify.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3673 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/a2_analysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3166 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/a2_gates.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3135 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/a2_robust.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 2434 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/a3_analysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3744 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/a3_fees.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 2372 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/a3_final.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4710 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/a3_robust.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 2856 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b1_live.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4548 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b1_live_audit.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4254 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b1_oos_analyze.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 2877 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b1_oos_collect.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3807 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b2_final.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 6040 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b2_live_analysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4585 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b2_oos.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3644 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b2_oos_agg.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3190 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b2_stress_1d.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3981 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b3_analyze.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 5277 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b3_collect.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 5477 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b3_live.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3006 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b3_live_analyze.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4366 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b3_oos_1d.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3308 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b3_oos_analyze.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 6735 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b4_hist_macro.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1 | 2026-09-27 | 6409 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b4_hist_pit.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 5711 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b4_hist_v2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3955 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b4_live_audit.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4819 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b4_live_v2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4767 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b5_fund_robust.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4248 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b5_funding_dl.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4889 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/b5_pairs.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 8046 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/dl_history.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 2400 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/fc_alwayson.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1 | 2026-09-27 | 5393 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/fc_backtest.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1 | 2026-09-27 | 8697 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/fc_download.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1 | 2026-09-27 | 3567 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/fc_robust.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1; touches 1 tracked data/report file(s) | 2026-09-27 | 13779 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/lib.py` | UNREFERENCED-BY-IMPORT | importers=11; str-refs=1 | 2026-06-23 | 5312 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/ma2050_filter_on_live.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 5392 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/ma2050_uptrend_bt.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 7138 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/ml_dataset.py` | UNREFERENCED-BY-IMPORT | importers=1; str-refs=1 | 2026-09-27 | 13836 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/ml_forward_test.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 5408 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/ml_liq_sweep.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3693 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/ml_verify_1d.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 2997 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/ml_walkforward.py` | UNREFERENCED-BY-IMPORT | importers=3; str-refs=1 | 2026-09-27 | 8660 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/run_d1_multiple_testing.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 3 tracked data/report file(s) | 2026-06-23 | 10555 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/run_d3_ml_walkforward.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-23 | 13033 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/run_d4_combo_forensics.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-23 | 13836 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/run_dsr_d2.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-23 | 7954 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/run_kelly.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-23 | 7326 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/run_mr_filter.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 2 tracked data/report file(s) | 2026-06-23 | 7675 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/run_regime.py` | UNREFERENCED-BY-IMPORT | importers=1; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-23 | 9140 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/run_regime_mt.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-23 | 2995 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/run_verify_combo.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-23 | 9375 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/run_x_atr.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-06-23 | 9216 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/smc_audit_candidate.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4988 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/smc_backtest.py` | UNREFERENCED-BY-IMPORT | importers=5; str-refs=0 | 2026-09-27 | 12660 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/smc_demand_audit.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 4640 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/smc_demand_entry.py` | UNREFERENCED-BY-IMPORT | importers=1; str-refs=0 | 2026-09-27 | 8076 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/smc_demand_supply.py` | UNREFERENCED-BY-IMPORT | importers=1; str-refs=0 | 2026-09-27 | 8277 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/smc_exit_study.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 9332 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/support_strength_audit.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 5903 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/support_strength_bt.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 7372 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/target_policy_bt.py` | UNREFERENCED-BY-IMPORT | importers=15; str-refs=0 | 2026-09-27 | 16945 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `research/skill_application/scripts/verify_improvements.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-06-23 | 2969 | **NEEDS-OWNER-DECISION** | research scripts explicitly preserved by develop HEAD 4e3eb0a (2026-09-27); dir excluded by .dockerignore; its UNTRACKED .venv runs the cron watchdog |
| `database/migrate.py` | OPS/RECOVERY | importers=0; str-refs=5 | 2026-08-17 | 2369 | **KEEP** | setup.sh line 48; migration runner for database/migrations/ |
| `deploy/baseline-2026-09-27/unmatched/trading_claude_review/app/shared/learning_governance.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=3 | 2026-09-27 | 2044 | **KEEP** | deployment evidence: running-container file with no git match (baseline manifest) |
| `deploy/baseline-2026-09-27/unmatched/trading_claude_review/app/shared/schema.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=3 | 2026-09-27 | 685 | **KEEP** | deployment evidence: running-container file with no git match (baseline manifest) |
| `deploy/baseline-2026-09-27/unmatched/trading_scanner/app/shared/telegram_messages.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=3 | 2026-09-27 | 3151 | **KEEP** | deployment evidence: running-container file with no git match (baseline manifest) |
| `monitor_canary.py` | TEST-ONLY | importers=1; str-refs=5 | 2026-06-28 | 3833 | **KEEP** | canary runbook (docs/canary_runbook.md, docs/canary_state.md) + tests/test_canary_monitor.py |
| `research/continuous_learner.py` | DORMANT-SERVICE | importers=1; str-refs=8; deployed in continuous_learner,signal_engine | 2026-08-17 | 17416 | **KEEP** | compose service continuous_learner (stopped, not removed) + COPY in signal_engine image + tests; deployed |
| `research/data_governance/__init__.py` | TEST-ONLY | importers=8; str-refs=0 | 2026-09-27 | 231 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/build_freeze.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-09-27 | 7089 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/build_normalized.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 7317 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/build_universe.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 3511 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/cli.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1; touches 1 tracked data/report file(s) | 2026-09-27 | 1079 | **KEEP** | documented CLI (docs/research_temporal_governance.md: python -m research.data_governance.cli); Phase-16 sealing toolchain |
| `research/data_governance/download_binance_15m.py` | TEST-ONLY | importers=2; str-refs=1 | 2026-09-27 | 4141 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/execution.py` | TEST-ONLY | importers=4; str-refs=7 | 2026-09-27 | 1535 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/governance.py` | TEST-ONLY | importers=4; str-refs=2 | 2026-09-27 | 3946 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/market.py` | TEST-ONLY | importers=2; str-refs=1 | 2026-09-27 | 4412 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/seal_phase16.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0; touches 1 tracked data/report file(s) | 2026-09-27 | 5598 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/technical_validate.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 5060 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/universe.py` | TEST-ONLY | importers=2; str-refs=2 | 2026-09-27 | 3378 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/data_governance/verify_binance_archive.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=0 | 2026-09-27 | 2815 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/entry_hypothesis_review.py` | TEST-ONLY | importers=1; str-refs=3 | 2026-08-17 | 3736 | **KEEP** | documented review tool (docs/code_indicator_review_plan.md / phase reviews) + dedicated test |
| `research/foundation/__init__.py` | TEST-ONLY | importers=14; str-refs=0 | 2026-09-27 | 469 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/contract.py` | TEST-ONLY | importers=12; str-refs=7 | 2026-09-27 | 7396 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/costs.py` | TEST-ONLY | importers=3; str-refs=1 | 2026-09-27 | 997 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/dataset.py` | TEST-ONLY | importers=7; str-refs=4 | 2026-09-27 | 4738 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/experiment.py` | TEST-ONLY | importers=3; str-refs=2 | 2026-09-27 | 5814 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/holdout.py` | TEST-ONLY | importers=2; str-refs=1 | 2026-09-27 | 431 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/labels.py` | TEST-ONLY | importers=2; str-refs=1 | 2026-09-27 | 2232 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/metrics.py` | TEST-ONLY | importers=1; str-refs=0 | 2026-09-27 | 1208 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/opportunity.py` | TEST-ONLY | importers=4; str-refs=1 | 2026-09-27 | 3407 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/portfolio.py` | TEST-ONLY | importers=2; str-refs=1 | 2026-09-27 | 2709 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/quality.py` | TEST-ONLY | importers=4; str-refs=3 | 2026-09-27 | 2353 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/readers.py` | TEST-ONLY | importers=2; str-refs=3 | 2026-09-27 | 4341 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/replay.py` | TEST-ONLY | importers=5; str-refs=5 | 2026-09-27 | 8903 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/replay_position.py` | TEST-ONLY | importers=2; str-refs=1 | 2026-09-27 | 5269 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/runner.py` | TEST-ONLY | importers=2; str-refs=2 | 2026-09-27 | 14163 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/foundation/runtime_contract.py` | TEST-ONLY | importers=2; str-refs=3 | 2026-09-27 | 5815 | **KEEP** | Phase-16/P0R research-governance library (2026-09-27), imported by research CLIs + tests |
| `research/measurement_reanalysis.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1 | 2026-07-15 | 3199 | **KEEP** | documented in docs/superpowers/plans/2026-07-15-measurement-layer-fix.md; producer of measurement-fix evidence |
| `research/ops/canary_watchdog.py` | OPS/RECOVERY | importers=0; str-refs=3 | 2026-06-29 | 6359 | **KEEP** | source of ACTIVE cron job (*/30; identical sha256 to /home/tradmin/canary_watchdog.py) |
| `research/p0r.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=1; touches 1 tracked data/report file(s) | 2026-09-27 | 13330 | **KEEP** | documented (docs/phase2a_p0r_runtime_contract.md); P0R runtime-contract harness |
| `research/portfolio_review.py` | TEST-ONLY | importers=1; str-refs=2 | 2026-08-17 | 8037 | **KEEP** | documented review tool (docs/code_indicator_review_plan.md / phase reviews) + dedicated test |
| `research/replay.py` | UNREFERENCED-BY-IMPORT | importers=0; str-refs=2 | 2026-09-27 | 2380 | **KEEP** | documented (docs/edge_research_foundation.md: python -m research.replay) |
| `research/rollback_learned_gates.py` | OPS/RECOVERY | importers=0; str-refs=3; deployed in continuous_learner,signal_engine | 2026-08-17 | 4342 | **KEEP** | recovery tool COPYed into signal_engine image; runbook docs/claude/live-learning.md |
| `research/strategy_performance_review.py` | TEST-ONLY | importers=3; str-refs=8; deployed in continuous_learner,signal_engine | 2026-08-17 | 10154 | **KEEP** | ops runbook (docs/claude/operations.md: docker compose exec continuous_learner python research/strategy_performance_review.py); COPYed + deployed |
| `research/walk_forward_review.py` | TEST-ONLY | importers=1; str-refs=2 | 2026-08-17 | 5879 | **KEEP** | documented review tool (docs/code_indicator_review_plan.md / phase reviews) + dedicated test |
| `shared/strategy_math.py` | TEST-ONLY | importers=4; str-refs=7 | 2026-09-27 | 4740 | **KEEP** | imported by research/foundation/replay.py, research/p0r.py + 2 tests; wiring target of unmerged refactor/strategy-math |
