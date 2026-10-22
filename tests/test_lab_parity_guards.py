"""L1 parity guards that need no lab adapter yet (lab/PARITY_TEST_SPEC.md, P5 and P6b).

P5  shared-module pins: the production modules the lab adapter will reuse are pinned by git blob hash. A change to
    any of them fails here until the lab parity suite has been re-reviewed against the new blob and the pin updated.
P6b production isolation: no production module imports `lab`, and no production Dockerfile copies `lab/` into an
    image, so production behaviour cannot depend on lab code.

Pure static checks: no network, database, container or protected data.
"""
import ast
import hashlib
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Pinned at the merge base with main (0abb22d). The spec names `research/mechanisms/costs.py`; that path does not exist.
# The cost module in the tree is research/foundation/costs.py. `execution.py` is the production shared/execution.py,
# not research/data_governance/execution.py.
PINS = {
    "shared/triple_barrier.py": "cce68c7795fba99cce09b6ee18b390a2f375083c",
    "shared/partial_exits.py": "d3397f030803c8a757f0c8cb4da956d04b7477c1",
    "shared/entry_execution.py": "9d89954ad3db8a03e37906480764c14e9530b07a",
    "shared/execution.py": "a5aa270f954b933611fe859389501a19686351d2",
    "research/foundation/costs.py": "e9d65275582caf5c1f8335609782c228d7efc752",
}

PRODUCTION_SERVICES = ("scanner", "analyzer", "signal_engine", "trade_tracker", "telegram")
PRODUCTION_DIRS = PRODUCTION_SERVICES + ("shared", "p2_forward", "ops")


def git_blob(path: pathlib.Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@pytest.mark.parametrize("rel", sorted(PINS))
def test_p5_shared_module_pinned(rel):
    p = ROOT / rel
    assert p.is_file(), f"pinned shared module missing: {rel}"
    assert git_blob(p) == PINS[rel], (
        f"{rel} changed (blob {git_blob(p)}). Re-run and re-review the lab parity suite (P1-P4, P7) against it, "
        "then update the pin in this file.")


def _imports(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


def test_p6b_no_production_module_imports_lab():
    offenders = []
    for d in PRODUCTION_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "tests" in p.relative_to(ROOT).parts:
                continue
            try:
                mods = list(_imports(p))
            except SyntaxError:
                continue                     # not importable either; other suites own syntax
            offenders += [f"{p.relative_to(ROOT)}: import {m}" for m in mods if m == "lab" or m.startswith("lab.")]
    assert not offenders, offenders


@pytest.mark.parametrize("svc", PRODUCTION_SERVICES)
def test_p6b_no_production_image_copies_lab(svc):
    df = ROOT / svc / "Dockerfile"
    assert df.is_file()
    for line in df.read_text().splitlines():
        if re.match(r"^\s*(COPY|ADD)\b", line, re.I):
            srcs = line.split()[1:-1]
            srcs = [s for s in srcs if not s.startswith("--")]
            assert not any(s.rstrip("/") in ("lab", ".") or s.startswith("lab/") for s in srcs), (svc, line)


def test_guard_self_check_detects_a_lab_import(tmp_path):
    p = tmp_path / "m.py"
    p.write_text("import os\nfrom lab.account import Account\n")
    assert "lab.account" in list(_imports(p))
