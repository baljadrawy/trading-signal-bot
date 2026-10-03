"""In-container driver: the REAL Collector (app.py), writer, process certifier, health and durability paths, connected
over real aiohttp/TLS to the offline fake exchange (loopback only). Harness-only changes, none in production code:

  * DNS: a static resolver maps the two allow-listed Binance hostnames to 127.0.0.1:8443 (TLS via a test CA);
    the collector's URL allow-list, paths and client code are untouched.
  * Rotation: writer._utc is replaced IN THE PARENT ONLY by a virtual clock (one "hour" key per STRESS_HOUR_S
    seconds) so many finalize -> certify cycles happen in a bounded run. Record timestamps stay real wall time.
  * Steady-state heap: the writer's 200 k duplicate filter is pre-filled (as after ~2 h of G3) so GC work is
    representative of a late-run heap rather than a fresh process.
  * Telemetry: a 1 s snapshot task (reads attributes / shared Values only, never a filesystem scan).
"""
import asyncio
import datetime as dt
import gc
import json
import os
import random
import socket
import ssl
import sys
import time

import aiohttp
from aiohttp.abc import AbstractResolver

from p2_forward import app as A, config as C, writer as W

HOSTS = {"data-stream.binance.vision", "data-api.binance.vision"}


class MapResolver(AbstractResolver):
    def __init__(self, port):
        self.port = port

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host not in HOSTS:
            raise OSError(f"stress harness resolver: {host} not served offline")
        return [{"hostname": host, "host": "127.0.0.1", "port": self.port, "family": socket.AF_INET, "proto": 0,
                 "flags": socket.AI_NUMERICHOST}]

    async def close(self):
        pass


class GcProbe:
    """Harness-side GC accounting (count / total / max per second); independent of the collector's own callback."""

    def __init__(self):
        self.t0, self.count, self.total_ms, self.max_ms, self.win_max_ms, self.win = {}, [0, 0, 0], 0.0, 0.0, 0.0, []

    def cb(self, phase, info):
        g = info.get("generation")
        if phase == "start":
            self.t0[g] = (time.perf_counter(), time.thread_time())
        else:
            t = self.t0.pop(g, None)
            if t is not None:
                d = (time.perf_counter() - t[0]) * 1000
                cpu = (time.thread_time() - t[1]) * 1000            # main-thread CPU actually spent in this GC
                self.count[g] += 1; self.total_ms += d
                self.max_ms = max(self.max_ms, d); self.win_max_ms = max(self.win_max_ms, d)
                if d >= 20:
                    self.win.append([g, round(d, 1), time.time_ns() // 1_000_000, round(cpu, 1)])


async def telemetry(c, path, gp):
    last_ll = 0
    with open(path, "a", encoding="utf-8", buffering=1) as fh:
        while True:
            await asyncio.sleep(1.0)
            m = A.now_ms()
            cert = c.writer.certifier
            ll = [(t, l) for t, l in list(c.looplag_recent) if t > last_ll]
            if ll:
                last_ll = ll[-1][0]
            rec = {"t_ms": m, "state": c.state, "health": c.health_state_last, "ins": c.instrumentation(), "q": c.q.qsize(), "q_peak": c.enq.peak,
                   "w": c.writer.status(),
                   "cert": {"pid": cert.ident, "alive": cert.is_alive(), "busy_since_ns": cert.busy_since_ns,
                            "beat_ns": cert._beat.value, "last_ms": cert._last.value, "max_ms": cert._max.value,
                            "promoted": cert._prom.value, "failures": cert._fail.value},
                   "gc": {"count": list(gp.count), "total_ms": round(gp.total_ms, 1), "max_ms": round(gp.max_ms, 1),
                          "win_max_ms": round(gp.win_max_ms, 1), "ge20": gp.win},
                   "ll_max": max((l for _, l in ll), default=0), "ll_n": len(ll),
                   "ll_ge": [[t, l] for t, l in ll if l >= 50]}
            gp.win_max_ms, gp.win = 0.0, []
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")


def run() -> int:
    hour_s = int(os.environ.get("STRESS_HOUR_S", "180"))
    runtime = int(os.environ["STRESS_RUNTIME_S"])
    out = os.environ.get("STRESS_OUT", "/out")
    prefill = int(os.environ.get("STRESS_PREFILL", "200000"))
    random.seed(int(os.environ.get("STRESS_SEED", "42")))

    cfg = dict(C.DEFAULTS)
    cfg.update({"enabled": True, "profile": "recommended", "max_runtime_s": runtime, "data_dir": "/data",
                "host_label": "offline-stress-harness"})
    C.validate(cfg)

    base = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
    k0 = time.time_ns() // (hour_s * 1_000_000_000)

    def vutc(ns):                                  # virtual hour key, parent writer only (rotation acceleration)
        return base + dt.timedelta(hours=int(ns // (hour_s * 1_000_000_000)) - k0)
    W._utc = vutc

    c = A.Collector(cfg)
    for i in range(prefill):                       # steady-state duplicate-filter heap (~2 h of G3 records)
        c.writer.recent[f"stressfill|book|S{i % 518:03d}USDT|{1791000000000 + i * 1000}"] = None

    ctx = ssl.create_default_context(cafile=os.environ["STRESS_TLS_CA"])
    port = int(os.environ.get("STRESS_FAKEX_PORT", "8443"))
    c.session_factory = lambda: aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30), headers={"User-Agent": "tsb-p2-forward/" + C.VERSION},
        connector=aiohttp.TCPConnector(resolver=MapResolver(port), ssl=ctx))

    gp = GcProbe()
    gc.callbacks.append(gp.cb)
    ident = {"pid": os.getpid(), "p2_forward_file": A.__file__, "python": sys.version, "hour_s": hour_s,
             "runtime_s": runtime, "prefill": prefill, "gc_threshold": gc.get_threshold(), "config_hash": C.config_hash(cfg),
             "cgroup": open("/proc/self/cgroup").read().strip(), "start_ms": A.now_ms()}
    with open(os.path.join(out, "harness_identity.json"), "w") as fh:
        json.dump(ident, fh, indent=1)

    async def main():
        t = asyncio.create_task(telemetry(c, os.path.join(out, "telemetry.jsonl"), gp))
        try:
            return await c.run()
        finally:
            t.cancel()

    code = asyncio.run(main())
    with open(os.path.join(out, "harness_exit.json"), "w") as fh:
        json.dump({"exit_code": code, "state": c.state, "end_ms": A.now_ms(), "counters": c.counters()}, fh, indent=1,
                  default=str)
    return code
