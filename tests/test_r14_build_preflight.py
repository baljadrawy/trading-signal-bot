"""R1.4-B / WP-A06 (R5.b) build-provenance preflight. Deterministic: synthetic Dockerfiles and
synthetic git repositories in tmp_path; the real-repository tests only read committed files."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("preflight", ROOT / "ops/provenance/build_preflight.py")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)
SHA = "a" * 40
DIGEST = "b" * 64
GIT = shutil.which("git", path="/usr/bin:/bin") or shutil.which("git")
SH = "/bin/sh" if Path("/bin/sh").exists() else None
needs_git = pytest.mark.skipif(GIT is None, reason="git not available")


def canonical_dockerfile(service, base=f"python@sha256:{DIGEST}"):
    rev = mod.REVISION_ARG[service]
    lines = [f"FROM {base}", "ARG APP_VERSION=sb-2026.08"]
    lines += [f"ARG {arg}" for arg, _ in mod.provenance_args(service)]
    labels = [f"{label}=${arg}" for arg, label in mod.provenance_args(service)]
    lines.append("LABEL org.opencontainers.image.version=$APP_VERSION \\")
    lines += [f"      {item} \\" for item in labels[:-1]] + [f"      {labels[-1]}"]
    lines.append(mod.guard_line(service))
    assert rev in lines[2]
    return "\n".join(lines) + "\n"


def fixture(tmp_path, docker=None, lock="alpha==1.0\nbeta==2.0\n", service="scanner"):
    p = tmp_path / mod.SOURCE_DIR[service]
    p.mkdir(parents=True, exist_ok=True)
    (p / "Dockerfile").write_text(canonical_dockerfile(service) if docker is None else docker)
    if lock is not None:
        (p / "requirements.lock").write_text(lock)
    return tmp_path


# ── static layer: check() ─────────────────────────────────────────────────────────────────

def test_clean_synthetic(tmp_path):
    assert mod.check(fixture(tmp_path), "scanner", SHA) == []


def test_missing_lock(tmp_path):
    assert "missing committed requirements.lock" in mod.check(fixture(tmp_path, lock=None), "scanner", SHA)


def test_mutable_base(tmp_path):
    root = fixture(tmp_path, docker=canonical_dockerfile("scanner", base="python:3.12-slim"))
    assert any("immutable" in i for i in mod.check(root, "scanner", SHA))


def test_unknown_revision(tmp_path):
    assert any("revision" in i for i in mod.check(fixture(tmp_path), "scanner", "unknown"))


def test_loose_lock(tmp_path):
    assert any("non-exact" in i for i in mod.check(fixture(tmp_path, lock="alpha>=1\n"), "scanner", SHA))


def test_duplicate_conflict(tmp_path):
    assert any("conflicting" in i for i in mod.check(fixture(tmp_path, lock="Alpha==1\nalpha==2\n"), "scanner", SHA))


def test_missing_label(tmp_path):
    docker = canonical_dockerfile("scanner").replace("      org.opencontainers.image.revision=$BUILD_REVISION \\\n", "")
    assert "missing OCI revision label" in mod.check(fixture(tmp_path, docker=docker), "scanner", SHA)


def test_unknown_service(tmp_path):
    assert mod.check(tmp_path, "postgres", SHA) == ["unknown service"]


@pytest.mark.parametrize("service", mod.ALL_SERVICES)
@pytest.mark.parametrize("revision", ["", "unknown", None, "abc1234", "A" * 40, SHA + "0"])
def test_missing_or_unknown_revision_refused_for_all_six_services(tmp_path, service, revision):
    issues = mod.check(fixture(tmp_path, service=service), service, revision)
    assert "revision must be a full 40-character commit SHA" in issues
    assert mod.check(tmp_path, service, SHA) == []


def test_collector_is_covered_with_its_own_argument(tmp_path):
    assert "collector" in mod.ALL_SERVICES and "collector" not in mod.SERVICES
    assert mod.provenance_args("collector") == (("P2F_GIT_COMMIT", mod.REVISION_LABEL),
                                                ("BUILD_TREE_CLEAN", mod.TREE_CLEAN_LABEL))
    assert (tmp_path / "p2_forward" / "Dockerfile").exists() is False
    assert mod.check(tmp_path, "collector", SHA) == ["missing Dockerfile", "missing committed requirements.lock"]


@pytest.mark.parametrize("service", mod.ALL_SERVICES)
def test_any_default_on_a_provenance_argument_is_refused(tmp_path, service):
    for arg, _label in mod.provenance_args(service):
        docker = canonical_dockerfile(service).replace(f"ARG {arg}\n", f"ARG {arg}=unknown\n")
        issues = mod.check(fixture(tmp_path, docker=docker, service=service), service, SHA)
        assert f"{arg} must have no default (a build must pass it explicitly)" in issues


@pytest.mark.parametrize("arg,label", [("BUILD_TREE_CLEAN", "tsb.build.tree_clean"),
                                       ("STRATEGY_SOURCE_HASHES", "tsb.strategy.source_hashes")])
def test_tree_clean_and_strategy_arguments_and_labels_required(tmp_path, arg, label):
    base = canonical_dockerfile("analyzer")
    no_arg = base.replace(f"ARG {arg}\n", "")
    assert f"missing {arg} build argument" in mod.check(fixture(tmp_path, docker=no_arg, service="analyzer"),
                                                        "analyzer", SHA)
    literal = base.replace(f"{label}=${arg}", f"{label}=true")
    assert f"{label} label must be fed from ${arg}" in mod.check(
        fixture(tmp_path, docker=literal, service="analyzer"), "analyzer", SHA)
    no_label = "\n".join(line for line in base.splitlines() if f"{label}=" not in line) + "\n"
    no_label = no_label.replace("$BUILD_TREE_CLEAN \\\n" + mod.guard_line("analyzer"),
                                "$BUILD_TREE_CLEAN\n" + mod.guard_line("analyzer"))
    assert f"missing {label} label" in mod.check(fixture(tmp_path, docker=no_label, service="analyzer"),
                                                 "analyzer", SHA)


def test_braced_and_quoted_label_reference_accepted(tmp_path):
    docker = canonical_dockerfile("telegram").replace("=$BUILD_TREE_CLEAN", '="${BUILD_TREE_CLEAN}"')
    assert mod.check(fixture(tmp_path, docker=docker, service="telegram"), "telegram", SHA) == []


def test_guard_line_required(tmp_path):
    docker = canonical_dockerfile("trade_tracker").replace(mod.guard_line("trade_tracker") + "\n", "")
    assert "missing provenance guard RUN line (build_preflight.guard_line)" in mod.check(
        fixture(tmp_path, docker=docker, service="trade_tracker"), "trade_tracker", SHA)


# ── real repository: Dockerfile contract and the r14-build-readiness workflow contract ───────

def test_workflow_contract_unchanged():
    """Mirrors .github/workflows/r14-build-readiness.yml ("Check known missing locks")."""
    assert mod.SERVICES == ("scanner", "analyzer", "signal_engine", "trade_tracker", "telegram")
    for service in mod.SERVICES:
        gaps = mod.check(ROOT, service, "a" * 40)
        assert "missing committed requirements.lock" in gaps, (service, gaps)


@pytest.mark.parametrize("service", mod.SERVICES)
def test_real_bot_dockerfiles_meet_the_provenance_contract(service):
    assert mod.check(ROOT, service, SHA) == ["missing committed requirements.lock"]
    text = (ROOT / service / "Dockerfile").read_text()
    assert "ARG BUILD_REVISION=" not in text
    assert "ARG APP_VERSION=sb-2026.08" in text      # A44 setup key input, deliberately unchanged


def test_real_collector_is_refused_until_labelled():
    issues = mod.check(ROOT, "collector", SHA)
    assert issues and "unknown service" not in issues


@pytest.mark.skipif(SH is None, reason="/bin/sh not available")
@pytest.mark.parametrize("service", mod.SERVICES)
def test_real_guard_line_refuses_unprovenanced_build_arguments(service):
    """Runs the exact guard of the committed Dockerfile under /bin/sh (as `docker build` would)."""
    line = next(l.strip() for l in (ROOT / service / "Dockerfile").read_text().splitlines()
                if l.strip().startswith("RUN case "))
    assert line == mod.guard_line(service)
    script = line[len("RUN "):]
    good = {"BUILD_REVISION": "0123456789abcdef" * 2 + "01234567", "BUILD_TREE_CLEAN": "true",
            "STRATEGY_SOURCE_HASHES": "demo_alpha:" + "c" * 64}

    def rc(**over):
        env = {"PATH": "/usr/bin:/bin", **good, **over}
        env = {k: v for k, v in env.items() if v is not None}
        return subprocess.run([SH, "-c", script], env=env, capture_output=True).returncode

    assert rc() == 0
    for bad in ({"BUILD_REVISION": None}, {"BUILD_REVISION": ""}, {"BUILD_REVISION": "unknown"},
                {"BUILD_REVISION": "A" * 40}, {"BUILD_REVISION": "a" * 39}, {"BUILD_REVISION": "a" * 41},
                {"BUILD_TREE_CLEAN": None}, {"BUILD_TREE_CLEAN": "false"}, {"BUILD_TREE_CLEAN": "1"},
                {"STRATEGY_SOURCE_HASHES": None}, {"STRATEGY_SOURCE_HASHES": ""}):
        assert rc(**bad) != 0, bad


# ── strategy label value ────────────────────────────────────────────────────────────────

def test_strategy_hash_label_format_roundtrip_and_refusals():
    hashes = {"zeta_b": "1" * 64, "alpha_a": "2" * 64}
    text = mod.format_strategy_hashes(hashes)
    assert text == "alpha_a:" + "2" * 64 + ",zeta_b:" + "1" * 64
    assert mod.parse_strategy_hashes(text) == hashes
    for bad in ({}, {"Bad": "1" * 64}, {"ok_id": "xyz"}):
        with pytest.raises(ValueError):
            mod.format_strategy_hashes(bad)
    for bad in ("", "alpha_a", "zeta_b:" + "1" * 64 + ",alpha_a:" + "2" * 64, text + "," + text.split(",")[0]):
        with pytest.raises(ValueError):
            mod.parse_strategy_hashes(bad)


def test_real_strategy_hashes_match_the_identity_module():
    import sys
    sys.path.insert(0, str(ROOT))
    try:
        from shared import strategy_identity as si
    finally:
        sys.path.remove(str(ROOT))
    expected = {sid: si.compute_closure(m, si.read_closure_sources(ROOT, m)).source_hash
                for sid, m in si.DRAFT_MANIFESTS.items()}
    assert mod.strategy_source_hashes(ROOT) == expected
    assert set(expected) == set(si.CURRENT_FAMILY_IDS)


# ── source layer: synthetic git repositories ───────────────────────────────────────────

GIT_ENV = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "synthetic", "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
           "GIT_COMMITTER_NAME": "synthetic", "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
           "GIT_AUTHOR_DATE": "1700000000 +0000", "GIT_COMMITTER_DATE": "1700000000 +0000"}
SYNTHETIC_MANIFESTS = (
    "\n\n# synthetic closure for the preflight tests\n"
    "DRAFT_MANIFESTS = MappingProxyType({\n"
    "    'demo_alpha': StrategyRuleManifest(strategy_id='demo_alpha', files=(\n"
    "        ClosureFile(path='engine/rules.py', role='synthetic decision rule'),)),\n"
    "})\n")


def git(root, *args):
    r = subprocess.run([GIT, "-C", str(root), "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
                       env=GIT_ENV, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def commit_all(root, message="synthetic"):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def make_repo(tmp_path, service="scanner", identity=True):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    fixture(root, service=service)
    (root / ".gitignore").write_text("ignored.out\n")
    (root / "engine").mkdir()
    (root / "engine" / "rules.py").write_text("THRESHOLD_NAME = 'synthetic'\n")
    (root / "notes.txt").write_text("outside the closure\n")
    if identity:
        (root / "shared").mkdir()
        (root / "shared" / "strategy_identity.py").write_text(
            (ROOT / "shared" / "strategy_identity.py").read_text() + SYNTHETIC_MANIFESTS)
    return root, commit_all(root)


def oracle_source_hash(data):
    """Independent recomputation of SOURCE_SCHEME over one file (no strategy_identity import)."""
    files = [["engine/rules.py", hashlib.sha256(data).hexdigest()]]
    doc = json.dumps({"scheme": "tsb-strategy-source/1", "files": files}, sort_keys=True,
                     separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(doc.encode("ascii")).hexdigest()


@needs_git
def test_clean_repo_is_ready_with_exact_build_arguments(tmp_path):
    root, head = make_repo(tmp_path)
    report = mod.preflight(root, "scanner", head)
    expected_hashes = "demo_alpha:" + oracle_source_hash((root / "engine" / "rules.py").read_bytes())
    assert report == {
        "schema": "tsb-r14-build-preflight/2", "service": "scanner", "ready": True, "issues": [], "revision": head,
        "build_args": {"BUILD_REVISION": head, "BUILD_TREE_CLEAN": "true", "STRATEGY_SOURCE_HASHES": expected_hashes},
        "labels": {"org.opencontainers.image.revision": head, "tsb.build.tree_clean": "true",
                   "tsb.strategy.source_hashes": expected_hashes}}
    assert mod.preflight(root, "scanner", head) == report     # deterministic


@needs_git
@pytest.mark.parametrize("change", ["modified", "staged", "untracked", "deleted"])
def test_dirty_tree_is_refused(tmp_path, change):
    root, head = make_repo(tmp_path)
    if change == "modified":
        (root / "notes.txt").write_text("edited\n")
    elif change == "staged":
        (root / "notes.txt").write_text("edited\n")
        git(root, "add", "notes.txt")
    elif change == "untracked":
        (root / "engine" / "extra.py").write_text("X = 1\n")
    else:
        (root / "notes.txt").unlink()
    report = mod.preflight(root, "scanner", head)
    assert report["ready"] is False and report["build_args"] is None and report["labels"] is None
    assert any(i.startswith("working tree is dirty") for i in report["issues"]), report["issues"]


@needs_git
def test_gitignored_file_does_not_count_as_dirty(tmp_path):
    root, head = make_repo(tmp_path)
    (root / "ignored.out").write_text("local output\n")
    assert mod.preflight(root, "scanner", head)["ready"] is True


@needs_git
def test_revision_must_be_the_checked_out_head(tmp_path):
    root, first = make_repo(tmp_path)
    (root / "notes.txt").write_text("second\n")
    second = commit_all(root)
    assert mod.preflight(root, "scanner", second)["ready"] is True
    assert "revision is not the checked-out HEAD commit" in mod.preflight(root, "scanner", first)["issues"]


@needs_git
def test_missing_commit_is_refused(tmp_path):
    root, _head = make_repo(tmp_path)
    issues = mod.preflight(root, "scanner", "0" * 40)["issues"]
    assert "commit missing: revision is not a commit in this repository" in issues


@needs_git
def test_repository_without_commits_is_refused(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    git(root, "init", "-q")
    issues, head = mod.check_source(root, SHA)
    assert head is None
    assert "commit missing: HEAD does not resolve to a commit" in issues


def test_not_a_git_work_tree_is_refused(tmp_path):
    fixture(tmp_path)
    issues, head = mod.check_source(tmp_path / "scanner", SHA)
    if GIT is None:
        assert issues == ["root is not a git work tree"]
    else:
        assert head is None and issues == ["root is not a git work tree"]
    assert mod.preflight(tmp_path / "scanner", "scanner", SHA)["ready"] is False


@needs_git
def test_subdirectory_root_is_refused(tmp_path):
    root, head = make_repo(tmp_path)
    issues, _ = mod.check_source(root / "engine", head)
    assert "root is not the top of its git work tree" in issues


@needs_git
def test_inherited_git_environment_is_ignored(tmp_path, monkeypatch):
    root, head = make_repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert mod.preflight(root, "scanner", head)["ready"] is True


@needs_git
def test_preflight_does_not_rewrite_the_index(tmp_path):
    root, head = make_repo(tmp_path)
    index = root / ".git" / "index"
    before = index.read_bytes()
    os.utime(root / "notes.txt", (1800000000, 1800000000))   # stat change, same content
    assert mod.preflight(root, "scanner", head)["ready"] is True
    assert index.read_bytes() == before
    assert not (root / ".git" / "index.lock").exists()


@needs_git
def test_strategy_label_follows_the_closure_only(tmp_path):
    root, head = make_repo(tmp_path)
    base = mod.preflight(root, "scanner", head)["build_args"]["STRATEGY_SOURCE_HASHES"]
    (root / "notes.txt").write_text("outside the closure, changed\n")
    head2 = commit_all(root)
    outside = mod.preflight(root, "scanner", head2)
    assert outside["ready"] and outside["build_args"]["STRATEGY_SOURCE_HASHES"] == base
    (root / "engine" / "rules.py").write_text("THRESHOLD_NAME = 'changed'\n")
    head3 = commit_all(root)
    inside = mod.preflight(root, "scanner", head3)
    assert inside["ready"] and inside["build_args"]["STRATEGY_SOURCE_HASHES"] != base
    assert inside["build_args"]["STRATEGY_SOURCE_HASHES"] == "demo_alpha:" + oracle_source_hash(
        b"THRESHOLD_NAME = 'changed'\n")


@needs_git
def test_missing_identity_module_refuses_bot_service(tmp_path):
    root, head = make_repo(tmp_path, identity=False)
    report = mod.preflight(root, "scanner", head)
    assert report["ready"] is False
    assert any(i.startswith("strategy identity unavailable") for i in report["issues"])


@needs_git
def test_unresolvable_closure_refuses_bot_service(tmp_path):
    root, _ = make_repo(tmp_path)
    (root / "engine" / "rules.py").unlink()
    head = commit_all(root)
    issues = mod.preflight(root, "scanner", head)["issues"]
    assert any(i.startswith("strategy identity unavailable: ClosureError") for i in issues), issues


@needs_git
def test_collector_ready_without_strategy_label(tmp_path):
    root, head = make_repo(tmp_path, service="collector", identity=False)
    report = mod.preflight(root, "collector", head)
    assert report["ready"] is True, report["issues"]
    assert report["build_args"] == {"BUILD_TREE_CLEAN": "true", "P2F_GIT_COMMIT": head}
    assert report["labels"] == {"org.opencontainers.image.revision": head, "tsb.build.tree_clean": "true"}


@needs_git
def test_declared_build_arguments_are_checked(tmp_path):
    root, head = make_repo(tmp_path)
    good = mod.preflight(root, "scanner", head)["build_args"]
    assert mod.preflight(root, "scanner", head, dict(good, APP_VERSION="sb-2026.08"))["ready"] is True
    for key, value, message in (
            ("BUILD_REVISION", "unknown", "declared BUILD_REVISION does not match the checkout"),
            ("BUILD_TREE_CLEAN", "false", "declared BUILD_TREE_CLEAN does not match the checkout"),
            ("STRATEGY_SOURCE_HASHES", "demo_alpha:" + "0" * 64,
             "declared STRATEGY_SOURCE_HASHES does not match the checkout")):
        assert message in mod.preflight(root, "scanner", head, dict(good, **{key: value}))["issues"]
        missing = {k: v for k, v in good.items() if k != key}
        assert f"declared build arguments omit {key}" in mod.preflight(root, "scanner", head, missing)["issues"]


@needs_git
def test_cli_contract_and_exit_codes(tmp_path):
    root, head = make_repo(tmp_path)

    def run(*argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = mod.main(list(argv))
        return code, json.loads(buf.getvalue())

    code, report = run("--root", str(root), "--service", "scanner", "--revision", head)
    assert code == 0 and report["ready"] is True
    assert {"schema", "service", "ready", "issues"} <= set(report)
    args = [f"--build-arg={k}={v}" for k, v in report["build_args"].items()]
    assert run("--root", str(root), "--service", "scanner", "--revision", head, *args)[0] == 0
    code, report = run("--root", str(root), "--service", "scanner", "--revision", head,
                       "--build-arg", "BUILD_TREE_CLEAN=true")
    assert code == 2 and "declared build arguments omit BUILD_REVISION" in report["issues"]
    (root / "notes.txt").write_text("dirty\n")
    code, report = run("--root", str(root), "--service", "scanner", "--revision", head)
    assert code == 2 and report["ready"] is False
    code, report = run("--root", str(root), "--service", "scanner", "--revision", "unknown")
    assert code == 2 and "revision must be a full 40-character commit SHA" in report["issues"]
    with contextlib.redirect_stderr(io.StringIO()):
        for argv in (["--root", str(root), "--service", "scanner"],
                     ["--root", str(root), "--service", "postgres", "--revision", head],
                     ["--root", str(root), "--service", "scanner", "--revision", head, "--build-arg", "novalue"]):
            with pytest.raises(SystemExit) as exc:
                mod.main(argv)
            assert exc.value.code == 2
