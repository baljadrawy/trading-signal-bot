"""Shared synthetic fixture: one base dataset per test process (copied for mutation tests)."""
import atexit
import os
import shutil
import tempfile

from .synth import Synth, default_spec, ms

D1, D2 = "2026-10-05", "2026-10-06"
D1_MS, D2_MS = ms("2026-10-05T00:00:00Z"), ms("2026-10-06T00:00:00Z")
_ROOT = tempfile.mkdtemp(prefix="p2c-test-")
atexit.register(shutil.rmtree, _ROOT, True)
_BASE = None


def base_dataset() -> str:
    """Path of the shared, never-mutated base dataset (two sealed days)."""
    global _BASE
    if _BASE is None:
        _BASE = os.path.join(_ROOT, "base")
        Synth(_BASE, default_spec()).generate()
    return _BASE


def copy_dataset(name: str) -> str:
    dst = os.path.join(_ROOT, name)
    shutil.copytree(base_dataset(), dst)
    return dst


def new_dataset(name: str, **spec_over) -> str:
    dst = os.path.join(_ROOT, name)
    Synth(dst, default_spec(**spec_over)).generate()
    return dst


def scratch(name: str) -> str:
    p = os.path.join(_ROOT, name)
    os.makedirs(p, exist_ok=True)
    return p
