#!/bin/bash
# Proposed main branch protection (PR-on-Demand revision 2026-10-26; docs/ops/MAIN_BRANCH_PROTECTION_PROPOSAL.md). NOT APPLIED: owner review first.
# usage: apply_branch_protection.sh [--branch main] [--check | --apply]
#   --check (default): read-only. Prints the current protection and merge settings next to the proposal.
#   --apply: changes repository settings. Refused unless APPLY_CONFIRM="<branch>@<first 12 hex of the sha256 of
#            main_branch_protection.json>", so an approval names the exact configuration it approves.
# Rollback: gh api -X DELETE repos/$REPO/branches/<branch>/protection (and restore merge settings from the --check output).
set -euo pipefail
REPO=${REPO:-baljadrawy/trading-signal-bot}; BR=main; MODE=check
while [ $# -gt 0 ]; do case "$1" in --branch) BR=$2; shift 2;; --check) MODE=check; shift;; --apply) MODE=apply; shift;; *) echo "unknown arg $1"; exit 2;; esac; done
H=$(cd "$(dirname "$0")" && pwd); P=$H/main_branch_protection.json; S=$H/repo_merge_settings.json
SHA=$(sha256sum "$P" | cut -c1-12)
echo "repo=$REPO branch=$BR proposal_sha=$SHA mode=$MODE"
echo "--- current protection"; { gh api "repos/$REPO/branches/$BR/protection" 2>&1 || true; } | head -c 4000; echo
echo "--- current merge settings"; gh api "repos/$REPO" --jq '{allow_merge_commit,allow_squash_merge,allow_rebase_merge,allow_auto_merge,delete_branch_on_merge}'
echo "--- proposed protection"; cat "$P"; echo "--- proposed merge settings"; cat "$S"
[ "$MODE" = check ] && { echo "CHECK ONLY: nothing changed"; exit 0; }
[ "${APPLY_CONFIRM:-}" = "$BR@$SHA" ] || { echo "REFUSED: set APPLY_CONFIRM=$BR@$SHA after owner approval"; exit 3; }
gh api -X PUT "repos/$REPO/branches/$BR/protection" --input "$P" > /dev/null
gh api -X PATCH "repos/$REPO" --input "$S" > /dev/null
echo "APPLIED to $BR; verify with --check"
