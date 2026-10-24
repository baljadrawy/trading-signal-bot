"""Offline guards for the CI workflow definitions and the change-detection helper (docs/ops/CI_EFFICIENCY.md).

Text and indentation based, so it needs no YAML library in the CI test environment; a structural YAML check
runs additionally where PyYAML is importable.
"""
import importlib.util
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"
TESTS = WF / "tests.yml"
REQUIRED = ("default suite (no database)", "disposable-PostgreSQL matrix", "P2 forward collector suite (p2_forward/tests)")

SPEC = importlib.util.spec_from_file_location("change_scope", ROOT / ".github" / "ci" / "change_scope.py")
cs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cs)


def top_block(text, key):
    """Lines of a top-level mapping block such as `on:` or `jobs:` (until the next top-level key)."""
    lines, out, inside = text.splitlines(), [], False
    for line in lines:
        if re.match(rf"^{re.escape(key)}:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^\S", line):
            break
        if inside:
            out.append(line)
    return out


def jobs(text):
    """{job_id: [lines]} for the two-space-indented job keys under `jobs:`."""
    res, cur = {}, None
    for line in top_block(text, "jobs"):
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            cur = m.group(1)
            res[cur] = []
        elif cur:
            res[cur].append(line)
    return res


def test_required_check_names_exist_exactly_once():
    text = TESTS.read_text()
    names = [m.group(1).strip() for m in re.finditer(r"^    name: (.+)$", text, re.M)]
    for req in REQUIRED:
        assert names.count(req) == 1, (req, names)


def test_required_jobs_are_unconditional():
    """A job-level `if:` would leave a required check unreported or skipped; work may only be skipped by steps."""
    for jid, lines in jobs(TESTS.read_text()).items():
        assert not any(re.match(r"^    if:", ln) for ln in lines), jid
        assert not any(re.match(r"^    needs:", ln) for ln in lines), jid


def test_tests_triggers_cover_pull_requests_and_main_without_path_filters():
    on = "\n".join(top_block(TESTS.read_text(), "on"))
    assert re.search(r"^  pull_request:", on, re.M)
    assert re.search(r"^  push:", on, re.M)
    assert "'main'" in on or " main" in on
    # path filters on the workflow would stop required checks from reporting at all
    assert "paths:" not in on and "paths-ignore:" not in on


def test_concurrency_never_cancels_main():
    text = TESTS.read_text()
    conc = "\n".join(top_block(text, "concurrency"))
    group = re.search(r"group: (.+)", conc).group(1)
    cancel = re.search(r"cancel-in-progress: (.+)", conc).group(1)
    assert "cancel-in-progress: true" not in conc
    assert cancel.strip() == "${{ github.ref != 'refs/heads/main' }}"
    assert "github.ref == 'refs/heads/main' && github.run_id" in group   # unique group: never replaced while pending
    for name in ("r14-lock-review.yml", "r14-build-readiness.yml"):
        conc = "\n".join(top_block((WF / name).read_text(), "concurrency"))
        assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in conc, name


def test_every_job_in_every_workflow_has_a_timeout():
    for wf in sorted(WF.glob("*.yml")):
        for jid, lines in jobs(wf.read_text()).items():
            m = [re.match(r"^    timeout-minutes: (\d+)\s*$", ln) for ln in lines]
            m = [x for x in m if x]
            assert len(m) == 1 and 1 <= int(m[0].group(1)) <= 60, (wf.name, jid)


def test_collector_job_keeps_full_suite_behind_change_scope():
    lines = jobs(TESTS.read_text())["collector"]
    body = "\n".join(lines)
    assert "python3 .github/ci/change_scope.py collector" in body
    assert '[ "$out" = "run=false" ] || out=run=true' in body       # anything else runs
    assert "python -m pytest -q -p no:cacheprovider -rs tests" in body
    assert "fetch-depth: 0" in body


def test_r14_path_filters_include_their_inputs():
    for name, extra in (("r14-lock-review.yml", ()), ("r14-build-readiness.yml", ("scanner/Dockerfile*",))):
        on = "\n".join(top_block((WF / name).read_text(), "on"))
        for pat in (".github/**", "ops/provenance/**", "tests/test_r14_*", "**/requirements*", "**/*.lock") + extra:
            assert f"- '{pat}'" in on, (name, pat)


def test_yaml_structure_if_available():
    yaml = pytest.importorskip("yaml")
    for wf in sorted(WF.glob("*.yml")):
        doc = yaml.safe_load(wf.read_text())
        on = doc.get(True, doc.get("on"))                # YAML 1.1 reads the key `on` as True
        assert on, wf.name
        for jid, job in doc["jobs"].items():
            assert job["runs-on"] == "ubuntu-24.04", (wf.name, jid)
            assert isinstance(job["timeout-minutes"], int), (wf.name, jid)
    doc = yaml.safe_load(TESTS.read_text())
    assert {j["name"] for j in doc["jobs"].values()} >= set(REQUIRED)
    assert "pull_request" in doc[True]


# ------------------------------------------------------------------ change_scope.decide (pure)
@pytest.mark.parametrize("path", [
    "p2_forward/p2_forward/transport.py", "p2_forward/tests/test_collector.py", "p2_forward/requirements.txt",
    ".github/workflows/tests.yml", ".github/ci/requirements-test.txt", ".github/ci/change_scope.py",
    "tests/test_anything.py", "shared/db.py", "scanner/requirements.txt", "analyzer/requirements.lock",
    "constraints.txt", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "conftest.py", "x/conftest.py",
])
def test_inputs_always_run(path):
    assert cs.decide("collector", ["docs/ops/NOTE.md", path])[0] is True


def test_unrelated_paths_skip_only_collector():
    files = ["docs/ops/NOTE.md", "scanner/scanner.py", "deploy/rc/RECORD.md", "README.md", "research/x.py"]
    assert cs.decide("collector", files)[0] is False
    assert cs.decide("unknown-scope", files)[0] is True
    assert cs.decide("collector", [])[0] is True


# ------------------------------------------------------------------ change_scope end to end on a git repo
def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "ci@example.invalid")
    _git(tmp_path, "config", "user.name", "ci")
    (tmp_path / "p2_forward").mkdir()
    (tmp_path / "p2_forward" / "a.py").write_text("x = 1\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("a\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _commit(repo, rel, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", rel)
    return _git(repo, "rev-parse", "HEAD")


def _run(repo, event, ref, base, head, main_ref="refs/heads/main"):
    env = dict(os.environ, EVENT=event, REF=ref, BASE_SHA=base, HEAD_SHA=head, MAIN_REF=main_ref)
    p = subprocess.run(["python3", str(ROOT / ".github" / "ci" / "change_scope.py"), "collector"], cwd=repo, env=env,
                       capture_output=True, text=True)
    assert p.returncode == 0
    assert p.stdout.count("\n") == 1                 # exactly one output line for $GITHUB_OUTPUT
    return p.stdout.strip()


def test_e2e_pull_request_docs_only_skips_and_collector_change_runs(repo):
    base = _git(repo, "rev-parse", "HEAD")
    docs = _commit(repo, "docs/b.md", "b\n")
    assert _run(repo, "pull_request", "refs/pull/1/merge", base, docs) == "run=false"
    coll = _commit(repo, "p2_forward/a.py", "x = 2\n")
    assert _run(repo, "pull_request", "refs/pull/1/merge", base, coll) == "run=true"


def test_e2e_rename_out_of_component_runs(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "mv", "p2_forward/a.py", "docs/a.py")
    _git(repo, "commit", "-q", "-m", "mv")
    assert _run(repo, "pull_request", "refs/pull/1/merge", base, _git(repo, "rev-parse", "HEAD")) == "run=true"


def test_e2e_fail_safe_cases(repo):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, "docs/c.md", "c\n")
    assert _run(repo, "push", "refs/heads/main", base, head) == "run=true"
    assert _run(repo, "push", "refs/heads/develop", base, head) == "run=true"
    assert _run(repo, "workflow_dispatch", "refs/heads/main", "", head) == "run=true"
    assert _run(repo, "push", "refs/heads/integration/x", base, "f" * 40) == "run=true"   # unknown head
    assert _run(repo, "pull_request", "refs/pull/1/merge", "", head) == "run=true"
    assert _run(repo, "pull_request", "refs/pull/1/merge", head, head) == "run=true"      # empty diff
    # a push whose head is on main itself has an empty branch diff: run
    assert _run(repo, "push", "refs/heads/integration/x", base, head) == "run=true"
    # main ref not fetched: run
    _git(repo, "checkout", "-q", "-b", "feat", base)
    feat = _commit(repo, "docs/d.md", "d\n")
    assert _run(repo, "push", "refs/heads/integration/x", base, feat, main_ref="refs/remotes/none/main") == "run=true"


def test_e2e_push_uses_branch_diff_since_main_not_event_before(repo):
    """Regression (PR #92 scenario run): a push diffed from event.before could skip a collector change whose own
    run was cancelled by concurrency. The push range is the branch's whole change since its merge-base with main."""
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "feat")
    docs = _commit(repo, "docs/b.md", "b\n")
    assert _run(repo, "push", "refs/heads/integration/x", "0" * 40, docs) == "run=false"   # new branch, docs only
    a = _commit(repo, "p2_forward/a.py", "x = 3\n")                                       # A: collector change
    b = _commit(repo, "docs/c.md", "c\n")                                                 # B supersedes A
    assert _run(repo, "push", "refs/heads/integration/x", a, b) == "run=true"              # A's change still counts
    # a force push that drops the collector change goes back to docs-only relative to main
    _git(repo, "reset", "-q", "--hard", docs)
    d = _commit(repo, "docs/e.md", "e\n")
    assert _run(repo, "push", "refs/heads/integration/x", b, d) == "run=false"
    assert base != d


def test_virtualenv_cache_key_covers_python_image_and_requirements():
    j = jobs(TESTS.read_text())
    for jid in ("unit", "database"):
        body = "\n".join(j[jid])
        key = re.search(r"key: (ci-venv-.+)", body).group(1)
        for part in ("steps.py.outputs.python-version", "steps.img.outputs.id", "runner.arch",
                     "hashFiles('.github/ci/requirements-test.txt')"):
            assert part in key, (jid, part)
        assert "~/ci-venv/bin/python -m pip install -r .github/ci/requirements-test.txt" in body, jid


def test_virtualenv_cache_saved_only_from_main_push():
    """PR runs restore main's entry but never save their own (cache scope/eviction, CI_EFFICIENCY.md)."""
    j = jobs(TESTS.read_text())
    for jid in ("unit", "database"):
        body = "\n".join(j[jid])
        assert "uses: actions/cache@v4" not in body, jid            # no implicit post-job save
        assert "uses: actions/cache/restore@v4" in body and "uses: actions/cache/save@v4" in body, jid
        save = body.split("uses: actions/cache/save@v4", 1)[1]
        assert "github.event_name == 'push'" in body and "github.ref == 'refs/heads/main'" in body, jid
        assert "steps.venv.outputs.cache-hit != 'true'" in body, jid
