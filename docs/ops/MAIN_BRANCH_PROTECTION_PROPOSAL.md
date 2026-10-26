# Proposed `main` branch protection (NOT APPLIED)

**Status:** proposal for owner review, 2026-10-23. Nothing in this PR changes GitHub settings.
Applying it is a separate owner decision that names the configuration hash (see "Apply").

**Observed 2026-10-23 (read-only):**
- `main` is **not protected** (`GET …/branches/main/protection` returns 404 "Branch not protected").
- The repository allows merge, squash and rebase merges.
- `BRANCH_RELEASE_POLICY.md` §8 requires protection and merge commits only.

## Mapping from §8 to settings

| §8 requirement | Setting (`ops/github/main_branch_protection.json` / `repo_merge_settings.json`) |
|---|---|
| A PR is required; no direct pushes, the owner's included | `required_pull_request_reviews` present, plus `enforce_admins: true` |
| Required strict status checks: the three suites | `required_status_checks.strict: true`; contexts `default suite (no database)`, `disposable-PostgreSQL matrix`, `P2 forward collector suite (p2_forward/tests)`, pinned to the GitHub Actions app (id 15368), so a status posted by another app cannot satisfy them |
| Conversation resolution | `required_conversation_resolution: true` |
| Force-push and deletion blocked | `allow_force_pushes: false`, `allow_deletions: false` |
| No bypass (rules apply to administrators) | `enforce_admins: true` |
| Merge commit only | `allow_merge_commit: true`, `allow_squash_merge: false`, `allow_rebase_merge: false` |
| 0 required approvals while there is a single account | `required_approving_review_count: 0`, `dismiss_stale_reviews: true`. Raise to 1, with `require_last_push_approval: true`, when a separate reviewer identity exists. |

**Recorded, not enforceable with one account (unchanged):**
- an independent review of the final head SHA;
- explicit owner merge authorization naming the PR number and its head SHA.

**`develop`:** §8 also names `develop` "during the transition". The same file applies to it with `--branch develop`, if the owner still wants it protected.

## Consequences to accept before applying

1. **No merge is possible while GitHub Actions cannot run.** The account billing block of 2026-10-23 would then stop every merge, including docs-only PRs. That is the intended effect of required checks, not a malfunction.
2. **The owner can no longer push to `main` directly** or force-push it. An emergency change also goes through a PR.
3. **Strict mode:** a PR must be up to date with `main` before merging, so it is re-run after any other merge.
4. **Required checks.** Workflows that are not required (`r14-*`, R1.4 parity, Socket) keep running but do not block. Adding them is a separate decision.

## Validation against main cce58c3 (2026-10-26, read-only)

Checked after #92 (CI efficiency) was merged; this branch now merges `origin/main` at `cce58c3`.

| Item | Result |
|---|---|
| Required names = job `name:` in `.github/workflows/tests.yml` | exact match, each once: `unit` → `default suite (no database)`, `database` → `disposable-PostgreSQL matrix`, `collector` → `P2 forward collector suite (p2_forward/tests)` |
| Check-run app on `cce58c3` | all three from `github-actions`, app id **15368**. Others seen: `R1.4 static parity inventory…` (15368, not required), `Socket Security: Project Report` (app 156372, not required) |
| `tests.yml` triggers | `pull_request` to `main`/`develop`, `push` to `main`/`develop`/`integration/**`, `workflow_dispatch`; **no workflow-level `paths`/`paths-ignore`** |
| Required jobs | no job-level `if:` or `needs:` (guarded by `tests/test_ci_workflows.py`) |
| `r14-*` workflows | path-filtered (`r14-build-readiness`, `r14-lock-review`) or `workflow_dispatch` only: **must not be required**, and none is |
| Live state (GET) | `main` and `develop` not protected (404); rulesets `[]`; merge, squash and rebase all allowed; `allow_auto_merge=false`, `delete_branch_on_merge=false`, `allow_update_branch=false` |
| Bots | no Dependabot config, no CODEOWNERS; the only non-owner check is Socket (not required) |

**JSON change needed: none.** `main_branch_protection.json` and `repo_merge_settings.json` are unchanged.

**Recorded deviation.** §8 says "merge commit only". #92 was **squash-merged** (2026-10-26, 16:55Z): `cce58c3` has one parent and the PR head `dd6b1a8` is not in `main`'s history. This was possible because squash is still enabled. Its provenance is the PR #92 head SHA, not the commits on `main`. Applying the proposal turns squash off. If the owner wants to keep squash, change `repo_merge_settings.json` and its test before applying.

## Conflict and lockout analysis

| # | Risk | Effect | Mitigation |
|---|---|---|---|
| 1 | `enforce_admins` + PR required, with a single account | no direct push or bypass for the owner | Not a lockout: branch protection does not limit repository-admin API calls, so the owner can still lift it (see Emergency). The only real lockout is losing the admin account itself (out of scope). |
| 2 | Strict up-to-date + `allow_update_branch=false` | after every merge, open PRs show "out of date" and there is no "Update branch" button | merge `origin/main` into the branch locally and push (merge commit, as now), then CI runs again. Optionally enable `allow_update_branch` (owner decision, not in the JSON). |
| 3 | A path-filtered workflow made required | its check never reports on unrelated PRs, so the PR is stuck at "Expected" | only `tests.yml` jobs are required, and `tests.yml` has no path filters (tests in both files) |
| 4 | Collector job skipped by `change_scope.py` | the job **reports success** when no collector input changed, so the requirement is met without running the suite | intended (#92). Any doubt runs the suite, and `main`, `develop` and manual runs always run it in full. The check is never "skipped" or missing because there is no job-level `if:`. |
| 5 | `cancel-in-progress` on PRs | a superseded run shows "cancelled" on the old head | the new head gets its own run; `main` runs are never cancelled |
| 6 | `workflow_dispatch` | a manual run on the PR head posts the same check names (app 15368) and can satisfy them | that is the documented way to re-run. It still uses the branch's own workflow file. |
| 7 | A PR edits `tests.yml` itself | `pull_request` runs use the PR's workflow, so it could weaken its own required checks | the independent review of the final head SHA (§8, recorded) must cover `.github/**`. GitHub cannot enforce this with one account. |
| 8 | Actions cannot run (billing block, as on 2026-10-23) | no check reports, so **no merge at all**, including docs-only PRs | Emergency procedure below. It is owner-only and temporary. |
| 9 | Conversation resolution | only **review threads** (inline or review comments) block; plain PR/issue comments (where reviews and authorizations are recorded today) cannot be resolved and do not block | resolve or answer inline threads before merging; the author can resolve their own threads |
| 10 | `develop` | stale at `ce38ff7` (CI is main-first) | do not apply to `develop` now. If the owner wants it, use `--branch develop` with the same procedure. |
| 11 | 0 approvals | GitHub enforces no review | §8 records the review and authorization; raise to 1 when a second identity exists |

## Implementation plan (owner-approved run only)

```
R=baljadrawy/trading-signal-bot; T=$(date -u +%Y%m%dT%H%MZ); D=~/bp-snapshots; mkdir -p $D
# 1. pre-checks: proposal at reviewed head, tests and scan green, Actions running (a recent tests.yml run succeeded)
gh run list -R $R -w tests -L 3
# 2. snapshot (read-only)
ops/github/apply_branch_protection.sh --check | tee $D/check-$T.txt          # prints proposal_sha
gh api repos/$R --jq '{allow_merge_commit,allow_squash_merge,allow_rebase_merge,allow_auto_merge,delete_branch_on_merge}' > $D/merge-$T.json
gh api repos/$R/branches/main/protection > $D/protection-$T.json 2>&1 || true   # 404 expected today
# 3. apply
APPLY_CONFIRM=main@<proposal_sha> ops/github/apply_branch_protection.sh --apply
# 4. verify (GET)
ops/github/apply_branch_protection.sh --check | tee $D/after-$T.txt
gh api repos/$R/branches/main/protection --jq '{strict:.required_status_checks.strict,checks:[.required_status_checks.checks[]|"\(.context)@\(.app_id)"],admins:.enforce_admins.enabled,conv:.required_conversation_resolution.enabled,force:.allow_force_pushes.enabled,del:.allow_deletions.enabled}'
```

5. **Test PR:** open a docs-only Draft PR (for example `ops/bp-smoke`) into `main`. Confirm that:
   - merging is blocked while the three checks are pending;
   - the collector check reports success through the change-scope skip;
   - once all three are green, merging is allowed and only "Create a merge commit" is offered;
   - after another PR merges, the smoke PR shows "out of date".

   Then close it without merging. Optionally confirm that a direct push is rejected: `git push origin <noop-commit>:main` must fail with "protected branch".

## Emergency: Actions unavailable (owner only, temporary)

Lift only the status-check requirement and keep the PR requirement and the no-force-push rule:
```
gh api -X DELETE repos/baljadrawy/trading-signal-bot/branches/main/protection/required_status_checks
# merge the authorized PR at its named head SHA (record the reason on the PR), then restore immediately:
APPLY_CONFIRM=main@<proposal_sha> ops/github/apply_branch_protection.sh --apply && ops/github/apply_branch_protection.sh --check
```

## Rollback (full)

```
gh api -X DELETE repos/baljadrawy/trading-signal-bot/branches/main/protection
gh api -X PATCH repos/baljadrawy/trading-signal-bot --input ~/bp-snapshots/merge-<T>.json   # restore merge settings from snapshot
ops/github/apply_branch_protection.sh --check                                               # expect 404 + snapshot values
```
Values observed on 2026-10-26: merge, squash and rebase all `true`; auto-merge and delete-branch `false`.

## Apply, guard and tests

`--apply` refuses unless `APPLY_CONFIRM=<branch>@<12-hex proposal sha shown by --check>`. The full sequence is in "Implementation plan" above.

**Tests:** `tests/test_branch_protection_proposal.py` checks the files against §8 offline. It covers:
- the required check names exist in `.github/workflows/tests.yml`;
- no required name comes from another, path-filtered, workflow;
- `tests.yml` has no path filters;
- the rollback and emergency commands are documented;
- `--apply` without confirmation makes no write call (it runs against a `gh` stub).

`tests/test_ci_workflows.py` (from #92) keeps the required jobs unconditional.
