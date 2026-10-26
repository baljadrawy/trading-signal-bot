# Proposed `main` branch protection (NOT APPLIED)

**Status:** proposal for owner review. Revision 2, 2026-10-26: aligned with the owner directive
*Continuous Development + PR-on-Demand* (`docs/governance/DEVELOPMENT_FIRST_POLICY.md`, top;
`docs/governance/OWNER_OPERATING_CONTRACT.md` §2), which says #90 must be revised before activation.
Nothing in this PR changes GitHub settings. Applying it is a separate owner decision that names the configuration
hash (see "Implementation").

## What changed in revision 2 and why

Revision 1 (2026-10-23) required a pull request for every change to `main`. The directive now lets low-risk D0
changes reach `main` directly (fast-forward or local merge, no PR) when CI is green. A "PR required" rule would
block exactly that, so it is removed. Safety comes from the CI gate on the exact commit, not from the PR object.

| Setting (`ops/github/main_branch_protection.json`) | Rev 1 | Rev 2 | Purpose |
|---|---|---|---|
| `required_pull_request_reviews` | present, 0 approvals | **`null` (no PR required)** | PR-on-Demand: direct D0 integration allowed |
| `required_status_checks` | 3 checks, strict, app 15368 | unchanged | every commit that becomes `main` has passed `tests.yml` |
| `enforce_admins` | true | unchanged | the owner account cannot skip the checks by accident |
| `allow_force_pushes` / `allow_deletions` | false / false | unchanged | history and evidence on `main` are never rewritten |
| `required_conversation_resolution` | true | unchanged | only matters when a PR is used on demand |
| `required_linear_history` | false | unchanged | merge commits stay allowed |
| `repo_merge_settings.json` | merge commit only | unchanged | see "Merge methods" |

The three required checks are the jobs of `.github/workflows/tests.yml` (`default suite (no database)`,
`disposable-PostgreSQL matrix`, `P2 forward collector suite (p2_forward/tests)`), pinned to the GitHub Actions app
(id 15368) so a status posted by another app cannot satisfy them.

## Integration flow (D0, no PR)

```
local: commit(s) on top of current origin/main          (fast-forward or a local merge commit)
   |  run proportionate tests + protected_scan.py
   v
git push origin HEAD:refs/heads/integration/rnd      (the ONE shared lane; tests.yml runs on push to integration/**)
   |  wait: the 3 required checks are "success" on that exact SHA (app 15368)
   v
git push origin <sha>:refs/heads/main                   (fast-forward only; no force)
   |  GitHub accepts only if <sha> already has the 3 successful checks
   v
tests.yml runs again on main (full collector suite)     -> record Integrated = <sha>; never "Deployed"
```

- If `main` moved meanwhile, the push is a non-fast-forward and is rejected (force push is off). Rebase or merge onto
  the new `main`, push the new SHA to `integration/<name>` and wait again. This is what `strict` means here.
- A local merge commit is a **new SHA without checks**: it must go through `integration/**` first; pushing it straight
  to `main` is rejected.
- A PR is still allowed when wanted (review, discussion, larger or riskier change); it merges through the same checks.
- Merging to `main` deploys nothing (`BRANCH_RELEASE_POLICY.md` §1.3). Owner gates for deploy, Paper strategy, halt,
  DB writes and protected data are not affected by this file.

**Contract alignment (2026-10-26).** The owner contract prefers "no branch for ordinary low-risk changes"; required status
checks make GitHub refuse a SHA on `main` that has no green checks. The two are reconciled by the directive's allowance
of "at most one shared, short-lived integration branch": `integration/rnd` is that single CI staging lane for every
change (no per-task branches, no routine PRs). PRs remain on demand (owner request, or `.github/**` changes that change
CI itself). If the owner prefers zero branches, the alternative is to drop required status checks and rely on
post-push CI on `main` (detects, does not prevent) — recorded here as the explicit trade-off.

## GitHub semantics relied on, and uncertainty

1. **Direct push with required checks (high confidence).** On a protected branch with required status checks, a push
   is accepted only if the pushed commit already has successful required checks; otherwise GitHub rejects it with
   `GH006 … Required status check "<name>" is expected`. Checks attach to the commit SHA, so a successful run from the
   `integration/**` push satisfies the requirement when that SHA is pushed to `main`.
2. **`strict` for pushes (uncertain).** GitHub documents strict ("up to date before merging") for PR merges. Whether it
   is evaluated on direct pushes is not clearly documented; the fast-forward-only rule makes it moot (a fast-forward of
   `main` is up to date by construction). It is kept for on-demand PRs.
3. **Collector check on `integration/**` (by design).** `.github/ci/change_scope.py` may let the collector job report
   success without running the suite when the branch changed no collector input. The post-push `main` run always runs it
   in full. This is accepted; any doubt runs the suite.
4. **Cancelled runs.** `integration/**` runs are cancel-in-progress per ref: a superseded SHA shows "cancelled", which
   does not satisfy the requirement. Push the final candidate and wait for its own run.
5. **Self-weakening.** A commit that edits `tests.yml` is tested with its own workflow file. Changes to `.github/**`
   are the one place where the gate can weaken itself. Recommended (owner decision; the directive lists CI as D0):
   integrate `.github/**` changes through an on-demand PR with an explicit owner look.

**Smoke test after applying (confirms 1 and 2):**
- (a) **negative:** push a docs-only commit that has never been tested directly to `main`
  (`git push origin <untested-sha>:refs/heads/main`). It must fail with `GH006 … Required status check … is expected`.
  If it is accepted, the protection is not effective: roll back (below) and report.
- (b) **positive:** push the same commit to `integration/bp-smoke`, wait for the 3 checks, then fast-forward `main` to
  it. It must be accepted. Use a real, harmless D0 change (for example the record of this smoke test) so nothing has to
  be undone.
- (c) **force:** `git push --force-with-lease origin <older-sha>:refs/heads/main` must be rejected.

## Merge methods

- Allowed: **merge commit** (PRs) and **fast-forward** (direct push; a git operation, not a repository merge setting).
- Squash and rebase merges stay **disabled**: both create a new SHA on `main` that CI never tested on its own and drop
  the reviewed commits' SHAs. #92 was squash-merged (2026-10-26) while squash was still enabled; its provenance is the
  PR head `dd6b1a8`, which is preserved on `ci/actions-efficiency`. If the owner wants squash for on-demand PRs, set
  `allow_squash_merge: true` in `repo_merge_settings.json` and its test before applying.

## Conflicts and risks

| Risk | Effect | Mitigation |
|---|---|---|
| Actions unavailable (billing block, as on 2026-10-23) | nothing can reach `main` | Emergency procedure below (owner only, temporary) |
| Path-filtered workflow made required | its check never reports, so pushes are stuck | only `tests.yml` jobs are required; it has no path filters (tested) |
| `integration/**` dropped from `tests.yml` push triggers | the direct flow has no way to get checks | guarded by a test |
| Single account, 0 approvals | GitHub enforces no review | independent review is advisory for D0 (directive); recommended PR for `.github/**` (see 5 above) |
| `develop` | stale; not protected by this proposal | apply with `--branch develop` only if the owner asks |

## Implementation (owner-approved run only)

```
R=baljadrawy/trading-signal-bot; T=$(date -u +%Y%m%dT%H%MZ); D=~/bp-snapshots; mkdir -p $D
gh run list -R $R -w tests -L 3                                                # Actions running
ops/github/apply_branch_protection.sh --check | tee $D/check-$T.txt            # snapshot; prints proposal_sha
gh api repos/$R --jq '{allow_merge_commit,allow_squash_merge,allow_rebase_merge,allow_auto_merge,delete_branch_on_merge}' > $D/merge-$T.json
gh api repos/$R/branches/main/protection > $D/protection-$T.json 2>&1 || true   # 404 expected today
APPLY_CONFIRM=main@<proposal_sha> ops/github/apply_branch_protection.sh --apply
ops/github/apply_branch_protection.sh --check | tee $D/after-$T.txt
gh api repos/$R/branches/main/protection --jq '{pr:.required_pull_request_reviews,strict:.required_status_checks.strict,checks:[.required_status_checks.checks[]|"\(.context)@\(.app_id)"],admins:.enforce_admins.enabled,force:.allow_force_pushes.enabled,del:.allow_deletions.enabled}'
```
Then run the smoke test (a)–(c) and record the results.

## Emergency: Actions unavailable (owner only, temporary)

Lift only the status-check requirement; force push and deletion stay blocked:
```
gh api -X DELETE repos/baljadrawy/trading-signal-bot/branches/main/protection/required_status_checks
# push the named, locally tested D0 SHA (record the reason), then restore immediately:
APPLY_CONFIRM=main@<proposal_sha> ops/github/apply_branch_protection.sh --apply && ops/github/apply_branch_protection.sh --check
```
Run `tests.yml` on that SHA (`workflow_dispatch`) as soon as Actions is back.

## Rollback (full)

```
gh api -X DELETE repos/baljadrawy/trading-signal-bot/branches/main/protection
gh api -X PATCH repos/baljadrawy/trading-signal-bot --input ~/bp-snapshots/merge-<T>.json   # restore merge settings
ops/github/apply_branch_protection.sh --check                                               # expect 404 + snapshot values
```
Values observed on 2026-10-26: `main` not protected, rulesets `[]`; merge, squash and rebase all `true`; auto-merge and
delete-branch `false`.

## Validation against main cce58c3 (2026-10-26, read-only; still valid for revision 2)

Required names equal the job `name:` values in `tests.yml`, each once; all three check runs on `cce58c3` came from
`github-actions` (app 15368). `tests.yml` triggers: `push` to `main`/`develop`/`integration/**`, `pull_request` to
`main`/`develop`, `workflow_dispatch`; no workflow-level path filters; required jobs have no job-level `if:`/`needs:`.
`r14-*` workflows are path-filtered or manual and are not required. No Dependabot config, no CODEOWNERS.

## Tests

`tests/test_branch_protection_proposal.py` (offline): required checks exact and strict with app 15368; no PR
requirement; no force push or deletion, admins included; merge commit only; `tests.yml` unfiltered and pushed on
`integration/**`; no required name from another workflow; `--apply` without confirmation makes no write call (gh stub);
rollback, emergency and smoke-test commands documented. `tests/test_ci_workflows.py` keeps the required jobs
unconditional.
