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

## Apply (after owner approval only)

```
ops/github/apply_branch_protection.sh --check                       # read-only: current vs proposed
APPLY_CONFIRM=main@<12-hex shown by --check> ops/github/apply_branch_protection.sh --apply
ops/github/apply_branch_protection.sh --check                       # verify
```

`--apply` refuses unless `APPLY_CONFIRM` names the branch and the proposal hash.

**Rollback:**
- `gh api -X DELETE repos/baljadrawy/trading-signal-bot/branches/main/protection`;
- restore the merge settings recorded by the first `--check`.

**Tests:** `tests/test_branch_protection_proposal.py` checks the files against §8 offline. It also checks that the required check names exist in `.github/workflows/tests.yml`, and that `--apply` without confirmation makes no write call (it runs against a `gh` stub).
