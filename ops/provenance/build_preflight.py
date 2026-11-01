#!/usr/bin/env python3
"""R1.4-B / WP-A06 (R5.b) fail-closed canonical-build preflight; no Docker/network/server access.

It refuses (exit 2) an unlabelled or unprovenanced build. It never builds, tags or pushes anything;
it reads the checkout and runs read-only ``git`` commands (``GIT_OPTIONAL_LOCKS=0``).

Layers (every issue refuses):

* ``check(root, service, revision)``: static build inputs. Every FROM pinned by sha256 digest;
  a committed exact ``requirements.lock``; ``revision`` a full 40-hex commit SHA (so ``unknown``
  or an empty value is refused); and in the Dockerfile the provenance build arguments declared
  without a default, the labels fed from them, and the provenance guard ``RUN`` line
  (``guard_line``) that makes a ``docker build`` without explicit, well-formed values fail.
* ``check_source(root, revision)``: the checkout. ``root`` is the top of a git work tree whose
  HEAD resolves to a commit, ``revision`` is an existing commit equal to HEAD, and the tree is
  clean (no staged, unstaged or untracked path; gitignored paths are not counted).
* ``strategy_source_hashes(root)``: the StrategyVersion ``source_hash`` of every strategy family,
  computed by the checkout's own ``shared/strategy_identity.py`` over its declared closure
  (bot services only; the collector has no trading authority and carries no strategy label).
* ``preflight(...)`` combines them. When ready it returns the exact build arguments and labels a
  release build must use; with ``declared`` it also refuses build arguments that are missing or
  differ from what the checkout proves.

Labels (Dockerfile ``LABEL``, fed from the build arguments):
  org.opencontainers.image.revision   the commit (BUILD_REVISION; collector: P2F_GIT_COMMIT)
  tsb.build.tree_clean                ``true`` (BUILD_TREE_CLEAN; the guard accepts nothing else)
  tsb.strategy.source_hashes          ``<strategy_id>:<sha256>,...`` sorted by strategy_id
                                      (STRATEGY_SOURCE_HASHES; bot services only)
``APP_VERSION`` keeps its default on purpose: it is part of today's A44 setup key (WP-A06 note).

CLI exit codes: 0 ready, 2 refused (any issue, or a usage error).
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SERVICES = ("scanner", "analyzer", "signal_engine", "trade_tracker", "telegram")
COLLECTOR = "collector"
ALL_SERVICES = SERVICES + (COLLECTOR,)
SOURCE_DIR = {**{s: s for s in SERVICES}, COLLECTOR: "p2_forward"}
REVISION_ARG = {**{s: "BUILD_REVISION" for s in SERVICES}, COLLECTOR: "P2F_GIT_COMMIT"}
TREE_CLEAN_ARG = "BUILD_TREE_CLEAN"
STRATEGY_ARG = "STRATEGY_SOURCE_HASHES"
REVISION_LABEL = "org.opencontainers.image.revision"
TREE_CLEAN_LABEL = "tsb.build.tree_clean"
STRATEGY_LABEL = "tsb.strategy.source_hashes"
REPORT_SCHEMA = "tsb-r14-build-preflight/2"

BASE = re.compile(r"^FROM\s+[^\s]+@sha256:[0-9a-f]{64}(?:\s+AS\s+\w+)?\s*$", re.I | re.M)
PIN = re.compile(r"^[A-Za-z0-9_.-]+==[^\s;#]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
STRATEGY_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
GIT_TIMEOUT_S = 60


def provenance_args(service):
    """(build argument, label) pairs the Dockerfile of ``service`` must declare and feed."""
    pairs = [(REVISION_ARG[service], REVISION_LABEL), (TREE_CLEAN_ARG, TREE_CLEAN_LABEL)]
    if service in SERVICES:
        pairs.append((STRATEGY_ARG, STRATEGY_LABEL))
    return tuple(pairs)


def guard_line(service):
    """The exact Dockerfile line that fails a build without explicit, well-formed provenance."""
    rev = REVISION_ARG[service]
    tests = [f'[ "${{#{rev}}}" -eq 40 ]', f'[ "${TREE_CLEAN_ARG}" = true ]']
    if service in SERVICES:
        tests.append(f'[ -n "${STRATEGY_ARG}" ]')
    return f'RUN case "${rev}" in *[!0-9a-f]*|"") exit 64;; esac; ' + " && ".join(tests)


def _dockerfile_issues(content, service):
    issues = []
    from_lines = re.findall(r"^FROM\s+.*$", content, re.M)
    if not from_lines or any(not BASE.fullmatch(line) for line in from_lines):
        issues.append("every FROM must use an immutable sha256 digest")
    for arg, label in provenance_args(service):
        declared = re.findall(rf"^\s*ARG\s+{arg}\b(=?)", content, re.M)
        if not declared:
            issues.append(f"missing {arg} build argument")
        elif any(declared):
            issues.append(f"{arg} must have no default (a build must pass it explicitly)")
        if label not in content:
            issues.append("missing OCI revision label" if label == REVISION_LABEL else f"missing {label} label")
        elif not re.search(rf'{re.escape(label)}=("?)\$(?:\{{{arg}\}}|{arg}\b)\1', content):
            issues.append(f"{label} label must be fed from ${arg}")
    if guard_line(service) not in (line.strip() for line in content.splitlines()):
        issues.append("missing provenance guard RUN line (build_preflight.guard_line)")
    return issues


def check(root, service, revision):
    """Static build inputs; returns sorted issues (empty means this layer passes)."""
    issues = []
    if service not in ALL_SERVICES:
        return ["unknown service"]
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        issues.append("revision must be a full 40-character commit SHA")
    dockerfile = Path(root) / SOURCE_DIR[service] / "Dockerfile"
    lock = Path(root) / SOURCE_DIR[service] / "requirements.lock"
    if not dockerfile.is_file():
        issues.append("missing Dockerfile")
    else:
        issues.extend(_dockerfile_issues(dockerfile.read_text(), service))
    if not lock.is_file():
        issues.append("missing committed requirements.lock")
    else:
        pins = {}
        for line in lock.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if not PIN.fullmatch(line):
                issues.append("lock contains non-exact or unsupported entry")
                continue
            name, version = line.split("==", 1)
            key = re.sub(r"[-_.]+", "-", name).lower()
            if key in pins and pins[key] != version:
                issues.append("conflicting duplicate lock entry")
            pins[key] = version
        if not pins:
            issues.append("lock has no pinned distributions")
    return sorted(set(issues))


def _git(root, *args):
    """Read-only git in ``root``; inherited GIT_* variables are dropped so ``root`` decides."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_S, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_source(root, revision):
    """Checkout provenance: returns ``(issues, head)``; ``head`` is None when HEAD is unresolved."""
    r = _git(root, "rev-parse", "--is-inside-work-tree")
    if r is None or r.returncode != 0 or r.stdout.strip() != "true":
        return ["root is not a git work tree"], None
    issues = []
    top = _git(root, "rev-parse", "--show-toplevel")
    if top is None or top.returncode != 0 or Path(top.stdout.strip()).resolve() != Path(root).resolve():
        issues.append("root is not the top of its git work tree")
    r = _git(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    head = r.stdout.strip() if r is not None and r.returncode == 0 else ""
    if not SHA.fullmatch(head):
        issues.append("commit missing: HEAD does not resolve to a commit")
        head = None
    if isinstance(revision, str) and SHA.fullmatch(revision):
        r = _git(root, "cat-file", "-e", f"{revision}^{{commit}}")
        if r is None or r.returncode != 0:
            issues.append("commit missing: revision is not a commit in this repository")
        elif head is not None and revision != head:
            issues.append("revision is not the checked-out HEAD commit")
    r = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none")
    if r is None or r.returncode != 0:
        issues.append("working-tree status unreadable (treated as dirty)")
    elif r.stdout:
        entries = [e for e in r.stdout.split("\0") if e]
        issues.append(f"working tree is dirty: {len(entries)} status entries (modified, staged or untracked)")
    return sorted(set(issues)), head


def _load_identity_module(root):
    path = Path(root) / "shared" / "strategy_identity.py"
    if not path.is_file():
        raise ValueError("shared/strategy_identity.py missing from the checkout")
    name = "_tsb_build_preflight_strategy_identity"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module      # dataclasses resolve annotations through sys.modules
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def strategy_source_hashes(root):
    """{strategy_id: source_hash} from the checkout's own strategy_identity.DRAFT_MANIFESTS."""
    si = _load_identity_module(root)
    manifests = si.DRAFT_MANIFESTS
    if not manifests:
        raise ValueError("no strategy manifests declared")
    out = {}
    for sid in sorted(manifests):
        digest = si.compute_closure(manifests[sid], si.read_closure_sources(Path(root), manifests[sid]))
        out[sid] = digest.source_hash
    return out


def format_strategy_hashes(hashes):
    """Canonical label value: ``<strategy_id>:<sha256>`` pairs joined by commas, sorted by id."""
    if not hashes:
        raise ValueError("no strategy source hashes")
    for sid, value in hashes.items():
        if not isinstance(sid, str) or not STRATEGY_ID.fullmatch(sid):
            raise ValueError(f"invalid strategy_id {sid!r}")
        if not isinstance(value, str) or not HEX64.fullmatch(value):
            raise ValueError(f"invalid source_hash for {sid}")
    return ",".join(f"{sid}:{hashes[sid]}" for sid in sorted(hashes))


def parse_strategy_hashes(text):
    """Inverse of ``format_strategy_hashes``; refuses anything not in canonical form."""
    if not isinstance(text, str) or not text:
        raise ValueError("empty strategy source hashes")
    out = {}
    for item in text.split(","):
        sid, sep, value = item.partition(":")
        if not sep or sid in out:
            raise ValueError("malformed strategy source hashes")
        out[sid] = value
    if format_strategy_hashes(out) != text:
        raise ValueError("strategy source hashes are not in canonical form")
    return out


def preflight(root, service, revision, declared=None):
    """Full refusal check; returns the report dict (``ready`` is True only with no issue)."""
    root = Path(root)
    if service not in ALL_SERVICES:
        return {"schema": REPORT_SCHEMA, "service": service, "ready": False, "issues": ["unknown service"],
                "revision": None, "build_args": None, "labels": None}
    issues = list(check(root, service, revision))
    source_issues, head = check_source(root, revision)
    issues.extend(source_issues)
    expected = {REVISION_ARG[service]: revision, TREE_CLEAN_ARG: "true"}
    if service in SERVICES:
        try:
            expected[STRATEGY_ARG] = format_strategy_hashes(strategy_source_hashes(root))
        except Exception as exc:  # fail closed: any loader or closure failure refuses the build
            issues.append(f"strategy identity unavailable: {type(exc).__name__}: {exc}")
    if declared is not None:
        for arg, _label in provenance_args(service):
            if arg not in declared:
                issues.append(f"declared build arguments omit {arg}")
            elif arg in expected and declared[arg] != expected[arg]:
                issues.append(f"declared {arg} does not match the checkout")
    issues = sorted(set(issues))
    ready = not issues
    labels = {label: expected[arg] for arg, label in provenance_args(service)} if ready else None
    return {"schema": REPORT_SCHEMA, "service": service, "ready": ready, "issues": issues,
            "revision": head if ready else None, "build_args": dict(sorted(expected.items())) if ready else None,
            "labels": dict(sorted(labels.items())) if ready else None}


def _build_arg(text):
    key, sep, value = text.partition("=")
    if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
        raise argparse.ArgumentTypeError("expected KEY=VALUE")
    return key, value


def main(argv=None):
    parser = argparse.ArgumentParser(description="Refuse an unlabelled or unprovenanced build (no Docker).")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--service", required=True, choices=ALL_SERVICES)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--build-arg", dest="build_args", action="append", type=_build_arg, default=None,
                        metavar="KEY=VALUE", help="a build argument the build will pass; checked against the checkout")
    args = parser.parse_args(argv)
    declared = None
    if args.build_args is not None:
        declared = {}
        for key, value in args.build_args:
            if key in declared and declared[key] != value:
                parser.error(f"conflicting --build-arg {key}")
            declared[key] = value
    report = preflight(args.root, args.service, args.revision, declared)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
