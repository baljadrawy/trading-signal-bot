#!/usr/bin/env python3
"""Conservative CI change detection (standard library only). Decides whether a job's real work must run.

Prints exactly one line to stdout, `run=true` or `run=false`, for $GITHUB_OUTPUT; the reason goes to stderr.
Fail-safe by construction: any doubt (unknown scope, unknown event, protected branch, missing or unreachable
SHAs, git error, empty diff, any changed path matching the scope's inputs) gives `run=true`. Only a
pull_request, or a push to a non-protected branch, whose complete diff touches none of the scope's inputs
gives `run=false`. The job itself always runs and reports its status, so required-check names are unchanged.

usage: change_scope.py SCOPE        environment: EVENT, REF, BASE_SHA, HEAD_SHA [, MAIN_REF]
       (pull_request: BASE_SHA/HEAD_SHA = pull_request base/head SHA. push: BASE_SHA is IGNORED; the range is
       the branch's complete change since its merge-base with MAIN_REF, default refs/remotes/origin/main.
       event.before is deliberately not used: the run that tested `before` may have been cancelled by
       concurrency or failed, so a diff from `before` could skip a collector change nobody tested.)

See docs/ops/CI_EFFICIENCY.md.
"""
import os
import re
import subprocess
import sys

PROTECTED_REFS = ("refs/heads/main", "refs/heads/develop")
SHA = re.compile(r"^[0-9a-f]{40}$")

# Inputs that, when changed, always make the scope run. Kept deliberately wider than the component:
# the component itself, the CI definition and its helper scripts, top-level tests and shared code,
# any requirements / constraints / lock file, and any pytest or packaging configuration (pytest
# searches parent directories for its rootdir configuration).
COMMON_INPUTS = (
    r"^\.github/",
    r"^tests/",
    r"^shared/",
    r"(^|/)requirements[^/]*$",
    r"(^|/)constraints[^/]*$",
    r"\.lock$",
    r"(^|/)conftest\.py$",
    r"(^|/)(pytest\.ini|pyproject\.toml|setup\.cfg|tox\.ini|\.python-version)$",
)
SCOPES = {
    # p2_forward/tests imports only p2_forward/ (its package, ops/, verifier/, tests/) and reads git history
    # of p2_forward/p2_forward at a fixed commit; it installs p2_forward/requirements.txt plus the pytest pin
    # from .github/ci/requirements-test.txt.
    "collector": (r"^p2_forward/",) + COMMON_INPUTS,
}


def decide(scope, files):
    """Pure decision on a complete list of changed paths. Returns (run, reason)."""
    if scope not in SCOPES:
        return True, f"unknown scope {scope!r}"
    if not files:
        return True, "empty or unknown diff"
    pats = [re.compile(p) for p in SCOPES[scope]]
    for f in files:
        for p in pats:
            if p.search(f):
                return True, f"input changed: {f} (matches {p.pattern})"
    return False, f"{len(files)} changed path(s), none is an input of scope {scope!r}"


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def _commit_exists(sha):
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode == 0


def changed_files(event, ref, base, head):
    """Complete list of changed paths, or (None, reason) when it cannot be established safely."""
    if event == "pull_request":
        if not (SHA.match(base or "") and SHA.match(head or "")):
            return None, "pull_request without both base and head SHA"
        rng = f"{base}...{head}"                    # the PR's own changes (merge-base to head)
    elif event == "push":
        if ref in PROTECTED_REFS:
            return None, f"push to protected branch {ref}: always full"
        if not SHA.match(head or "") or not _commit_exists(head):
            return None, "push without a usable head commit"
        main_ref = os.environ.get("MAIN_REF") or "refs/remotes/origin/main"
        mb = subprocess.run(["git", "merge-base", main_ref, head], capture_output=True, text=True)
        base = mb.stdout.strip()
        if mb.returncode or not SHA.match(base):
            return None, f"no merge-base with {main_ref} (ref not fetched or unrelated history)"
        rng = f"{base}..{head}"                     # the branch's complete change since it left main
    else:
        return None, f"event {event!r}: always full"
    for sha in (base, head):
        if not _commit_exists(sha):
            return None, f"commit {sha} not present"
    # --no-renames lists both the old and the new path of a rename.
    out = _git("diff", "--name-only", "--no-renames", rng)
    return [line for line in out.splitlines() if line], f"diff {rng}"


def main(argv):
    scope = argv[1] if len(argv) > 1 else ""
    try:
        files, how = changed_files(os.environ.get("EVENT", ""), os.environ.get("REF", ""),
                                   os.environ.get("BASE_SHA", ""), os.environ.get("HEAD_SHA", ""))
        if files is None:
            run, reason = True, how
        else:
            run, reason = decide(scope, files)
            reason = f"{how}: {reason}"
    except Exception as exc:                         # fail safe: never skip on an error
        run, reason = True, f"error ({type(exc).__name__}: {exc})"
    print(f"change_scope {scope}: {'RUN' if run else 'SKIP'} - {reason}", file=sys.stderr)
    print(f"run={'true' if run else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
