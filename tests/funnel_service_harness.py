"""Drive the real scanner, analyzer and signal_engine ``main()`` coroutines with in-memory fakes.

No network, database, docker or wall-clock dependence: the loops end when the fake sleep raises
``Stop`` (a BaseException, so the services' ``except Exception`` handlers do not swallow it).
Every database call is captured in order, so two runs can be compared byte for byte.
"""
import asyncio
import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("", "signal_engine", "analyzer", "scanner", "tests"):
    p = str(ROOT / sub) if sub else str(ROOT)
    if p not in sys.path:
        sys.path.insert(0, p)

from shared import evidence_v2 as ev2            # noqa: E402
from shared.config import config                  # noqa: E402
from shared.database import Database              # noqa: E402
from evidence_v2_fakes import IDENT               # noqa: E402

_LOADED = {}


class Stop(BaseException):
    pass


def load_service(name):
    """Load ``<name>/main.py`` by path under a unique module name (cached)."""
    if name not in _LOADED:
        spec = importlib.util.spec_from_file_location(f"wp2_funnel_{name}_main", ROOT / name / "main.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _LOADED[name] = mod
    return _LOADED[name]


class AsyncioProxy:
    """The module's ``asyncio`` with a sleep that ends the loop after ``cycles`` sleeps."""

    def __init__(self, cycles):
        self.cycles, self.sleeps = cycles, []

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        if len(self.sleeps) >= self.cycles:
            raise Stop()


class FakeDB:
    """Records every call; ``route(kind, sql, args)`` answers reads."""

    def __init__(self, route):
        self.route, self.calls = route, []

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, copy.deepcopy(args)))
        return self.route("fetch", sql, args)

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, copy.deepcopy(args)))
        return self.route("fetchval", sql, args)

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, copy.deepcopy(args)))
        return self.route("fetchrow", sql, args)

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, copy.deepcopy(args)))
        return None

    async def executemany(self, sql, args):
        self.calls.append(("executemany", sql, copy.deepcopy(list(args))))
        return None

    def install(self, monkeypatch):
        for n in ("fetch", "fetchval", "fetchrow", "execute", "executemany"):
            monkeypatch.setattr(Database, n, getattr(self, n))

        async def _noop(*a, **k):
            return None
        monkeypatch.setattr(Database, "connect", _noop)
        monkeypatch.setattr(Database, "disconnect", _noop)

    def trace(self, exclude=()):
        return json.dumps([c for c in self.calls if c[1] not in exclude], sort_keys=True, default=str)


class Health:
    def __init__(self):
        self.calls = []

    def install(self, monkeypatch, mod):
        async def started(service, metadata=None):
            self.calls.append(("started", service))

        async def success(service, metadata=None):
            self.calls.append(("success", service, json.loads(json.dumps(metadata, default=str))))

        async def failure(service, error, *a, **k):
            self.calls.append(("failure", service, type(error).__name__))

        async def schema(service):
            return None

        async def alert(*a, **k):
            return None
        for n, f in (("mark_started", started), ("mark_success", success), ("mark_failure", failure),
                     ("require_schema", schema), ("send_alert", alert)):
            if hasattr(mod, n):
                monkeypatch.setattr(mod, n, f)

    def without_funnel(self):
        """Heartbeats minus the added 'funnel' entry and minus the evidence-v2 queue gauges,
        which with recording on also count the funnel events in the same bounded queue."""
        out = []
        for c in self.calls:
            if c[0] == "success" and isinstance(c[2], dict):
                c = (c[0], c[1], {k: v for k, v in c[2].items() if k not in ("funnel", "evidence_v2")})
            out.append(c)
        return out

    def funnel_health(self):
        return [c[2].get("funnel") for c in self.calls if c[0] == "success" and isinstance(c[2], dict)]


def set_recording(monkeypatch, service, on):
    """FUNNEL_RECORDING plus an in-memory evidence-v2 recorder (always enabled, so the only
    difference between two runs is the funnel flag). Returns the recorder."""
    monkeypatch.setenv("FUNNEL_RECORDING", "on" if on else "off")
    monkeypatch.setattr(config, "EVIDENCE_V2_ENABLED", True)
    ev2.reset_for_tests()
    rec = ev2.RecorderV2(service, ev2.ListSink(), IDENT)
    ev2._RECORDERS[service] = rec
    return rec


def events(rec, event_type=None):
    rec.flush_now()
    out = rec.sink.records()
    return [e for e in out if event_type is None or e["event_type"] == event_type]


def run_main(mod, cycles=1):
    proxy = AsyncioProxy(cycles)
    mod_asyncio = mod.asyncio
    mod.asyncio = proxy
    try:
        asyncio.run(mod.main())
    except Stop:
        pass
    finally:
        mod.asyncio = mod_asyncio
    return proxy
