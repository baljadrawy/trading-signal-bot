"""Fakes for the WP2 tracker/telegram integration tests: a recording database, a fixed clock and
the pre-integration service modules loaded from a pinned commit.

``load_before(...)`` reads ``git show <BASE>:<path>`` (the source before the WP2 integration) and
loads it under a private module name; the tests skip when git or the object is unavailable.
Nothing here touches a real database, network or container.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BASE_COMMIT = "af319bb"          # last commit before the WP2 tracker/telegram integration
FIXED_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", str(sql)).strip()


class FakeConn:
    def __init__(self, db):
        self.db = db

    def transaction(self):
        db = self.db

        class _Tx:
            async def __aenter__(self_inner):
                db.log.append(("tx", "begin", ()))

            async def __aexit__(self_inner, *exc):
                db.log.append(("tx", "end", ()))
                return False
        return _Tx()

    async def fetch(self, sql, *args):
        return self.db._answer("fetch", sql, args)

    async def fetchrow(self, sql, *args):
        return self.db._answer("fetchrow", sql, args)

    async def fetchval(self, sql, *args):
        return self.db._answer("fetchval", sql, args)

    async def execute(self, sql, *args):
        return self.db._answer("execute", sql, args)


class FakeDB:
    """Records every call as ``(kind, normalized sql, args)``. ``rules`` is a list of
    ``(kind, substring, value_or_callable)``; the first match answers (a callable gets args)."""

    def __init__(self, rules=()):
        self.rules = list(rules)
        self.log = []

    def _answer(self, kind, sql, args):
        self.log.append((kind, _norm(sql), tuple(args)))
        for k, needle, value in self.rules:
            if k == kind and needle in sql:
                return value(*args) if callable(value) else value
        return [] if kind == "fetch" else None

    async def fetch(self, sql, *args):
        return self._answer("fetch", sql, args)

    async def fetchrow(self, sql, *args):
        return self._answer("fetchrow", sql, args)

    async def fetchval(self, sql, *args):
        return self._answer("fetchval", sql, args)

    async def execute(self, sql, *args):
        return self._answer("execute", sql, args)

    def acquire(self):
        db = self

        class _Acq:
            async def __aenter__(self_inner):
                db.log.append(("acquire", "", ()))
                return FakeConn(db)

            async def __aexit__(self_inner, *exc):
                return False
        return _Acq()


def fixed_datetime(now=FIXED_NOW):
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is not None else now.replace(tzinfo=None)
    return _DT


def _git_show(path: str) -> str:
    try:
        out = subprocess.run(["git", "show", f"{BASE_COMMIT}:{path}"], cwd=REPO, capture_output=True,
                             text=True, check=True, timeout=30)
    except Exception as exc:                                    # pragma: no cover
        pytest.skip(f"pre-integration source unavailable ({BASE_COMMIT}:{path}): {exc}")
    return out.stdout


def _load_source(name: str, source: str, tmp_dir: Path, extra_path: Path | None = None):
    target = tmp_dir / f"{name}.py"
    target.write_text(source, encoding="utf-8")
    added = []
    for p in (str(REPO), str(extra_path) if extra_path else None):
        if p and p not in sys.path:
            sys.path.insert(0, p)
            added.append(p)
    spec = importlib.util.spec_from_file_location(name, target)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        for p in added:
            if p != str(REPO):
                sys.path.remove(p)
    return mod


def load_before_tracker(tmp_dir: Path):
    name = "tsb_wp2_tracker_before"
    if name in sys.modules:
        return sys.modules[name]
    return _load_source(name, _git_show("trade_tracker/main.py"), tmp_dir, REPO / "trade_tracker")


def load_after_tracker():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import trade_tracker.main as tracker
    return tracker


def _with_ptb_stubs(loader):
    sys.path.insert(0, str(REPO / "tests"))
    from cr1_support import _stub_ptb
    saved = {k: sys.modules.get(k) for k in ("telegram", "telegram.ext", "whitelist")}
    tg_dir = str(REPO / "telegram")
    sys.path.insert(0, tg_dir)
    try:
        sys.modules.update(_stub_ptb())
        sys.modules.pop("whitelist", None)
        return loader()
    finally:
        sys.path.remove(tg_dir)
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


def load_before_telegram(tmp_dir: Path):
    name = "tsb_wp2_telegram_before"
    if name in sys.modules:
        return sys.modules[name]
    source = _git_show("telegram/main.py")
    return _with_ptb_stubs(lambda: _load_source(name, source, tmp_dir))


def load_after_telegram():
    sys.path.insert(0, str(REPO / "tests"))
    from cr1_support import load_telegram_main
    return load_telegram_main()


def patch_many(monkeypatch, modules, **attrs):
    """Set the same attributes on each module (fakes shared by the before and after runs)."""
    for mod in modules:
        for name, value in attrs.items():
            monkeypatch.setattr(mod, name, value)


def run(coro):
    import asyncio
    return asyncio.run(coro)


def namespace(**kw):
    return types.SimpleNamespace(**kw)
