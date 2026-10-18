# Trading Signal Bot: Main-First Branch, Release and Deployment Policy

**Status: PROPOSED (Draft PR, 2026-10-18; revision 2, same day: legacy-release exception and environment-template rules).** This policy takes effect only when the owner approves and merges this PR. Until then, existing records govern.

- **Source:** owner direction of 2026-10-17/18 ("main is the authoritative branch for approved project code; completed eligible branches are merged promptly after review; releases originate from approved commits reachable from main; merge and deployment are separate gates").
- **Earlier direction:** the 2026-09-27 owner direction in `docs/product/REPOSITORY_CONSOLIDATION.md` (Draft PR #3, "one long-lived branch, `main`").
- **No existing record is modified by this PR.** Conflicts are listed in section 12 and are resolved by dated notes after owner review. Historical governance evidence is preserved unchanged.

## 1. Canonical branch
1. `main` is the only authoritative source of completed and approved code and version-controlled operational definitions.
2. Every production image is built from a commit reachable from `main`, and that commit is tagged as a release.
3. **Merging into `main` never deploys.** Deployment is a separate, explicitly approved, manual action. GitHub has no deploy workflow, deploy key action, webhook or self-hosted runner that reacts to `main`. Adding any of these needs owner approval and an update to this policy.

## 2. Working branches
1. Short-lived `feature/*`, `fix/*`, `ops/*` and `docs/*` branches are created from `main` (from `develop` during the transition, section 11).
2. One concern per branch. Branches are deleted after their merge is verified, unless they are protected (rule 4 below).
3. Every completed branch that passes all gates is merged promptly. Completed eligible work does not wait on unrelated work.
4. **Protected research branches** carry research governance (holdouts, preregistration, sealed datasets). They are never merged wholesale. Only reviewed, runtime-relevant source is integrated, with a provenance manifest. The branch itself is preserved with an annotated tag.

## 3. PR gates (all required before merge)
| Gate | Requirement |
|---|---|
| Review | Owner approval of the PR scope and diff. A Draft PR is never merged. |
| Tests | CI green, **and** tests relevant to the changed component run in CI. Collector tests must be added to CI before collector code is merged. Green CI never proves runtime equivalence on its own. |
| Security | Scan for secrets, credentials and keys on all new blobs and commit messages. No real environment files (`.env`, `*.env`, `.env.*`), credentials, tokens, private keys, host secrets, dumps, live data or image archives. A sanitized template (section 9) is allowed only after this scan and an explicit review. |
| Holdout | No protected holdout contents or outcome records; research access follows the holdout governance record. |
| Documentation | Current-state docs updated in the same PR, or a tracked follow-up. Historical records get a dated note only. |
| Provenance | Any PR that changes deployable code states which images or services it affects. A PR that records running state states exactly how that state was verified. |

## 4. Releases
1. Release = an annotated tag `rel-YYYYMMDD-<shortsha>` on a `main` commit, plus a release record at `deploy/<release>/IMAGES.md` containing:
   - the image IDs and digests;
   - the per-service source commit;
   - the dependency lock (for the legacy transition exception in item 5 only: the installed-package inventory, with the missing locks stated);
   - the manifest of image file hashes;
   - the rollback images;
   - the archive SHA256SUMS.
2. Tags are never moved or deleted. Image digests are immutable references, and a release pins images by tag **and** records the digest.
3. Builds are canonical:
   - built from a clean checkout of the tagged commit (`git status --porcelain` empty);
   - `BUILD_REVISION=<full sha>` and an OCI revision label;
   - dependencies installed from the committed lock.
   Overlay or partial builds are allowed only as an approved exception, documented in the release record with a file-level manifest.
4. A build from a dirty, unverified or non-`main` checkout is never deployed.
5. **Legacy transition exception (the currently deployed A56 release only).** Release `a561-rel-ea8ae4f-r2` (A56.5, deployed 2026-10-16) predates this policy. It does **not** meet the canonical gates of items 3 and 6, and it is never described as if it did. It may be recorded as a **legacy release (transition exception)** only if its release record (`deploy/a561-rel-ea8ae4f/`) states accurately:
   - the verified content-equivalence evidence: per-file hashes of every running image against git, and the manifest verifier result;
   - the per-service installed-package inventories, labelled as a runtime baseline, **not** as locks;
   - that complete dependency locks are **missing**, and the known pin mismatches (for example, aiohttp pinned 3.13.5 in two `requirements.txt` files while 3.14.3 is installed);
   - that the images are composite overlay chains with dormant modules, not canonical Dockerfile builds, and that **no bit-exact rebuild has been demonstrated**;
   - that every image archive is **on-host only**, and any image without an archive (currently the running collector).
   The exception covers recording and operating this one existing release. It is not a release-gate pass and it does not extend to any later release.
6. **Canonical release gates (every future release).** A future release must satisfy, before deployment approval:
   - a committed per-service dependency lock;
   - a canonical build from a clean checkout of the tagged `main` commit (item 3);
   - a reproducibility check: the installed set in the built image equals the lock, and its `/app` equals the release manifest;
   - the release record of item 1.
   Any deviation needs a **separate, documented owner-approved exception** in the release record, naming the unmet gate, the reason, the evidence that exists instead, and the conditions for closing it. Exceptions are never retroactive and never implied.

## 5. Deployment, rollback and DR gates
1. Each deployment needs owner approval naming:
   - the release tag;
   - the services;
   - the rollback image;
   - the backup or recovery point;
   - the observation window.
2. Compose changes in production are applied only from the reviewed `main` blob. The deployed file must equal a committed blob, except for host-local templated values.
3. Rollback targets and recovery points (DB dump plus evidence) must be verified before deployment.
4. Deploy is not accepted until its observation or soak verdict is recorded.
5. Disaster recovery: an off-host copy of release images, the repository and backups is required before a release is called recoverable. Until then every release record states "on-host only".

## 6. Separate approvals (never implied by one another)
Preserve ≠ merge ≠ release tag ≠ deploy ≠ run research ≠ change schedules/backups ≠ change DB roles/credentials.

## 7. Hotfix and backport
1. `hotfix/*` is created from the **release tag currently deployed**, with minimal change and an expedited owner review.
2. After deployment, the hotfix is merged to `main` within the same stage. It is not closed until `main` contains it (GitHub checkpoint rule: push plus remote SHA verification).
3. A hotfix may never stay running from a local-only commit. Preservation on GitHub is the first step.

## 8. Branch protection (once `main` is runtime-accurate)
- `main`:
  - PR required;
  - 1 approval (owner);
  - required status `tests`;
  - linear history or merge commits per owner choice;
  - no force-push;
  - no deletion;
  - administrators included;
  - conversation resolution required.
- The default branch stays `main`.
- During the transition, `develop` gets the same protection.

## 9. Configuration classes
| Class | Examples | Rule |
|---|---|---|
| Versioned | service compose (env-file based), Dockerfiles, migrations, ops scripts, systemd units, monitor code | Committed, reviewed |
| Template | host paths, host labels, crontab lines, collector resource limits, image tags injected by environment; **sanitized environment templates** (`.env.example` or an equivalent `*.example` file) holding only variable names, comments and non-secret placeholders or defaults | Committed as a template plus a documented host-local value file (not secret). An environment template is added or changed only after the secret scan of section 3 and an explicit review. `.gitignore` keeps excluding `.env`, `*.env` and `.env.*`, and lists each reviewed template as an explicit exception (today: `!.env.example`) |
| Never committed | real environment files (`.env`, `*.env`, `.env.*` other than a reviewed template, backups such as `.env.bak.*`), credentials, tokens, private keys, host secrets, DB dumps, image archives, research-data, evidence/soak state, holdout contents | Referenced by path and SHA-256 only. Host-local configuration stays on the host, separate from the version-controlled templates |
| Immutable evidence | dated audits, release records, governance JSON/JSONL, SHA256SUMS | Append or dated correction only |

## 10. Agents and automation
Agents follow this policy:
- no push or merge without the owner's approval for that action;
- they report Saved / Merged / Deployed / Validated separately.

## 11. Transition and retirement of `develop`
1. Until `main` is runtime-accurate and protected, `develop` remains the integration branch, and PRs continue to target it.
2. After the fast-forward, new PRs target `main`. `develop` stays read-only and protected.
3. `develop` is retired (archived with a tag, then deleted only on approval) once:
   - CI triggers include `main`;
   - no open PR targets `develop`;
   - every live branch has been rebased or retargeted with approval.

## 12. Compatibility with existing records (to resolve by dated note after approval)
| Record | Status vs this policy | Proposed handling |
|---|---|---|
| `docs/product/REPOSITORY_CONSOLIDATION.md` (PR #3, unmerged) | Consistent (one long-lived `main`) | Reference; no change |
| `docs/ops/COMPOSE_OPERATIONS.md`, `CLAUDE.md` operations safety (Class A/B/C) | Consistent; this policy adds release and merge gates on top | Keep. Dated note that pinned-image lines are superseded by `deploy/a561-rel-ea8ae4f/IMAGES.md` |
| `GIT_GUIDE.md` (`dev` integration, main "runs on a Raspberry Pi", `git add .`) | **Conflicts** | Replace with a pointer to this file (separate docs PR) |
| `SETUP_GUIDE.md` Git section | **Conflicts** (duplicate, outdated flow) | Remove in the docs PR |
| `docs/claude/operations.md` (`git push origin main`) | **Conflicts** (direct push) | Correct in the docs PR |
| `docs/github-checkpoint-governance-20261008` (unmerged: "stage closure needs a verified GitHub checkpoint") | Consistent (Saved / Merged / Deployed / Validated) | Merge separately or fold in |
| `.github/workflows/tests.yml` | Requires PR-0 (main triggers, collector job) | PR-0 |
| `.env.example` (tracked; `.gitignore` exception `!.env.example`) | Allowed class (sanitized template), but **not yet reviewed** under section 9; its content was not inspected during consolidation | Secret scan and review in a separate step before it is relied on |
| `deploy/a561-rel-ea8ae4f/IMAGES.md` (runtime-provenance PR) | States the item-5 facts: not canonical builds, inventories not locks, aiohttp pin mismatch, on-host archives, no collector archive | Record as the legacy transition exception |
| Historical audits, release records, governance JSON/JSONL | Immutable | Never rewritten |
