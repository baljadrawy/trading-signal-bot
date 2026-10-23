"""The proposed GitHub branch protection matches BRANCH_RELEASE_POLICY.md section 8 (offline; nothing is applied)."""
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


def test_pull_request_required_with_zero_approvals_while_single_account():
    r = PROT["required_pull_request_reviews"]
    assert r["required_approving_review_count"] == 0          # single account: the author cannot approve own PR
    assert r["dismiss_stale_reviews"] is True


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
