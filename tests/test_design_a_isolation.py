"""Design A v1.0 isolation (brief item 25): no runtime, network, file or database dependency, and
no production module, script, image, scheduler or compose file refers to the package."""
import ast
import json
import os
import pathlib
import re
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, ".")
import design_a_synthetic as syn  # noqa: E402
from research.design_a import state as S  # noqa: E402

PKG = pathlib.Path("research/design_a")
STDLIB = {"__future__", "collections.abc", "contextlib", "dataclasses", "datetime", "decimal",
          "enum"}
REUSED = {"research.mechanisms.costs", "research.mechanisms.simulate",
          "research.data_governance.governance"}
FORBIDDEN_MODULES = {"socket", "ssl", "http.client", "urllib.request", "asyncio", "subprocess",
                     "sqlite3", "requests", "aiohttp", "asyncpg", "psycopg", "psycopg2", "numpy",
                     "pandas"}
NOT_RUNTIME = {"research", "tests", "docs"}       # the package, its tests and its spec live here
DATA_DIRS = {"results", "runs", "evidence", "data", "__pycache__", "node_modules"}
CODE_AND_CONFIG = {".py", ".sh", ".yml", ".yaml", ".tmpl", ".service", ".slice", ".timer",
                   ".conf", ".cfg", ".ini", ".toml", ".txt", ".sql", ""}


def runtime_files():
    """Code and configuration outside research/, tests/ and docs/: modules, scripts (with or
    without an extension), Dockerfiles, compose files, scheduler and systemd templates, and the
    JSON records under deploy/ and ops/; plus the research files that runtime images copy. Data
    and result directories, caches, data formats, binaries and files over 2 MB are never read."""
    out = []
    for root in pathlib.Path(".").iterdir():
        if root.name.startswith(".") or root.name in NOT_RUNTIME:
            continue
        for f in ([root] if root.is_file() else root.rglob("*")):
            if (not f.is_file() or DATA_DIRS & set(f.parts)
                    or any(part.startswith("bt_cache") for part in f.parts)):
                continue
            suffix = "" if f.name.startswith("Dockerfile") else f.suffix
            config_json = suffix == ".json" and f.parts[0] in {"deploy", "ops"}
            if (suffix in CODE_AND_CONFIG or config_json) and f.stat().st_size <= 2_000_000:
                out.append(f)
    out += list(pathlib.Path("research").glob("*.py"))
    out += list(pathlib.Path("research/null_a").rglob("*.py"))
    return out


def copy_sources(dockerfile_text):
    """Source paths of every COPY/ADD (also ONBUILD), with continued and JSON-array forms."""
    lines = [line for line in dockerfile_text.splitlines() if not line.lstrip().startswith("#")]
    joined = re.sub(r"\\[ \t]*\n", " ", "\n".join(lines))
    for line in joined.splitlines():
        m = re.match(r"\s*(?:ONBUILD\s+)?(COPY|ADD)\s+(.*)", line, re.IGNORECASE)
        if not m:
            continue
        rest = m.group(2).strip()
        while rest.startswith("--"):
            rest = rest.split(None, 1)[1] if " " in rest else ""
        args = json.loads(rest) if rest.startswith("[") else rest.split()
        yield from args[:-1]


def covers_package(source):
    s = source.removeprefix("./")
    return (s in {"", ".", "*", "research", "research/"} or s.startswith(("research/*", "research*"))
            or "design_a" in s)


def test_the_package_imports_only_the_stdlib_and_three_reviewed_research_modules():
    files = sorted(PKG.glob("*.py"))
    assert {p.name for p in files} == {"__init__.py", "state.py", "timing.py", "decision.py",
                                       "ledger.py"}
    for p in files:
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name in STDLIB, f"{p.name}: import {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert (module in STDLIB | REUSED or module == "research.design_a"
                        or module.startswith("research.design_a.")), f"{p.name}: from {module}"
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in {
                    "open", "eval", "exec", "compile", "__import__", "input"}:
                pytest.fail(f"{p.name}: {node.func.id}()")
            elif isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv", "system",
                                                                    "popen"}:
                pytest.fail(f"{p.name}: .{node.attr}")


def test_importing_the_package_loads_no_network_database_or_dataframe_module():
    code = ("import sys; sys.path.insert(0, '.'); import research.design_a.ledger; "
            "print(' '.join(sorted(sys.modules)))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
                         timeout=120)
    loaded = set(out.stdout.split())
    assert "research.design_a.ledger" in loaded
    assert not loaded & FORBIDDEN_MODULES, sorted(loaded & FORBIDDEN_MODULES)


def test_a_full_replay_runs_with_the_network_disabled(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert any(e.event is S.Event.EXECUTED for e in syn.scenario().ledger)


def test_nothing_that_runs_in_production_refers_to_the_package():
    files = runtime_files()
    names = {str(f) for f in files}
    for required in ("docker-compose.yml", "ops/compose-safe", "signal_engine/Dockerfile"):
        assert required in names, required
    for f in files:
        data = f.read_bytes()
        assert b"\0" in data[:8192] or b"design_a" not in data, f


def test_the_dockerfile_parser_sees_every_form():
    sample = ('COPY --chown=a:b x/ y/\nCOPY ["research", "/app/research"]\nADD a \\\n'
              '# a comment inside the continuation\n  research/ /r/\nONBUILD COPY research/* /s/\n')
    assert list(copy_sources(sample)) == ["x/", "research", "a", "research/", "research/*"]
    assert [covers_package(s) for s in ("research", "research/*", "./", "research/null_a/",
                                        "research/continuous_learner.py", "shared/")] == [
        True, True, True, False, False, False]


def test_no_runtime_image_copies_the_package():
    dockerfiles = [f for f in runtime_files() if f.name.startswith("Dockerfile")]
    assert len(dockerfiles) >= 9
    for p in dockerfiles:
        for source in copy_sources(p.read_text(encoding="utf-8")):
            assert not covers_package(source), f"{p}: {source}"
