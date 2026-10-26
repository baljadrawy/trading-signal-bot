"""The proposed GitHub branch protection (PR-on-Demand revision, 2026-10-26) is internally consistent (offline; nothing
is applied): no PR required, the three tests.yml checks required on the exact commit, no force push or deletion."""
import json
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH = os.path.join(ROOT, "ops", "github")
PROT = json.load(open(os.path.join(GH, "main_branch_protection.json")))
MERGE = json.load(open(os.path.join(GH, "repo_merge_settings.json")))
REQUIRED = {"default suite (no database)", "disposable-PostgreSQL matrix", "P2 forward collector suite (p2_forward/tests)"}


def test_required_checks_are_exactly_the_policy_set_and_strict():
    rsc = PROT["required_status_checks"]
    assert rsc["strict"] is True
    assert {c["context"] for c in rsc["checks"]} == REQUIRED
    assert all(c["app_id"] == 15368 for c in rsc["checks"])          # GitHub Actions, not any app posting a status


def test_required_check_names_exist_in_the_workflow():
    wf = open(os.path.join(ROOT, ".github", "workflows", "tests.yml")).read()
    names = set(re.findall(r"^\s+name:\s*(.+?)\s*$", wf, re.M))
    assert REQUIRED <= {n.strip("'\"") for n in names}, REQUIRED - names


def test_no_bypass_no_force_push_no_deletion_conversations_resolved():
    assert PROT["enforce_admins"] is True
    assert PROT["allow_force_pushes"] is False and PROT["allow_deletions"] is False
    assert PROT["required_conversation_resolution"] is True


def test_no_pull_request_required_so_d0_can_be_integrated_directly():
    # Owner directive 2026-10-26 (PR-on-Demand): low-risk D0 reaches main by fast-forward when CI is green.
    assert "required_pull_request_reviews" in PROT and PROT["required_pull_request_reviews"] is None
    assert PROT["restrictions"] is None and PROT["lock_branch"] is False
    assert PROT["required_linear_history"] is False                 # merge commits stay allowed


def test_integration_branches_trigger_the_required_workflow():
    """The direct flow pushes the candidate to integration/** first; without that trigger it could never get checks."""
    on = open(os.path.join(ROOT, ".github", "workflows", "tests.yml")).read().split("\njobs:", 1)[0]
    push = on.split("push:", 1)[1].split("pull_request:", 1)[0]
    assert "'integration/**'" in push or '"integration/**"' in push or "integration/**" in push
    assert "main" in push


def test_merge_commit_only():
    assert MERGE["allow_merge_commit"] is True
    assert MERGE["allow_squash_merge"] is False and MERGE["allow_rebase_merge"] is False
    assert MERGE["allow_auto_merge"] is False


def test_script_defaults_to_check_and_refuses_apply_without_confirmation():
    src = open(os.path.join(GH, "apply_branch_protection.sh")).read()
    assert "MODE=check" in src and 'APPLY_CONFIRM:-}" = "$BR@$SHA"' in src
    env = dict(os.environ, PATH="/nonexistent-gh-free-path:" + os.environ.get("PATH", ""), APPLY_CONFIRM="")
    stub = os.path.join(os.environ.get("TMPDIR", "/tmp"), "bp-stub")
    os.makedirs(stub, exist_ok=True)
    with open(os.path.join(stub, "gh"), "w") as fh:          # a gh stub: records calls, never touches GitHub
        fh.write("#!/bin/sh\necho \"$@\" >> \"$GH_STUB_LOG\"\necho '{}'\n")
    os.chmod(os.path.join(stub, "gh"), 0o755)
    log = os.path.join(stub, "calls.log")
    open(log, "w").close()
    env.update(PATH=stub + ":" + os.environ.get("PATH", ""), GH_STUB_LOG=log)
    r = subprocess.run(["bash", os.path.join(GH, "apply_branch_protection.sh"), "--apply"], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 3 and "REFUSED" in r.stdout
    calls = open(log).read()
    assert "-X PUT" not in calls and "-X PATCH" not in calls


def test_required_checks_come_only_from_the_unfiltered_tests_workflow():
    """A required check from a path-filtered workflow (r14-*) would never report on most PRs: a merge lockout."""
    wfdir = os.path.join(ROOT, ".github", "workflows")
    for fn in sorted(os.listdir(wfdir)):
        text = open(os.path.join(wfdir, fn)).read()
        names = {n.strip("'\"") for n in re.findall(r"^\s+name:\s*(.+?)\s*$", text, re.M)}
        if fn == "tests.yml":
            on = text.split("\njobs:", 1)[0]
            assert "paths:" not in on and "paths-ignore:" not in on
        else:
            assert not REQUIRED & names, (fn, REQUIRED & names)


def test_rollback_and_emergency_procedure_documented():
    doc = open(os.path.join(ROOT, "docs", "ops", "MAIN_BRANCH_PROTECTION_PROPOSAL.md")).read()
    assert "-X DELETE repos/baljadrawy/trading-signal-bot/branches/main/protection" in doc
    assert "branches/main/protection/required_status_checks" in doc         # emergency: lift checks only
    assert "Validation against main cce58c3" in doc
    assert "GH006" in doc and "integration/bp-smoke" in doc                   # smoke test confirms push semantics
