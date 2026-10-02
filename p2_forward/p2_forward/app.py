"""Forward market-intelligence collector (P2-E1): orchestration, sampling, gaps, backpressure, health.

One asyncio process; supervised tasks; a dedicated writer thread. Zero trading authority. Bounded runtime only.
Entry point: `python -m p2_forward` (config path in env P2F_CONFIG, default /config/collector.json).
"""
from __future__ import annotations

import asyncio
import collections
import datetime as dt
import json
import os
import queue
import random
import shutil
import signal
import time
import uuid

import aiohttp

from . import config as C
from . import record as R
from . import universe as U
from .guards import Backoff, ClockGuard, DiskGuard, RateGuard
from .transport import RestClient, WSConnection
from .writer import SegmentWriter, new_stats, recover_partials, sha256_file

TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
IRREPLACEABLE = "IRREPLACEABLE_FORWARD_OBSERVATION"
RECOVERABLE = "RECOVERABLE_WHERE_ARCHIVE_AVAILABLE"
STALE_MS = {"depth": 5_000, "book_t0": 30_000, "book": 120_000, "market": 180_000}


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def priority(kind: str, tier) -> int:
    """0 = keep longest (Tier 0, candles, control records) ... 3 = shed first (Tier-1 depth)."""
    if kind in ("candle", "clock", "universe", "gap", "lifecycle") or tier == 0:
        return 0
    if kind == "market" or (kind == "book" and tier == 2):
        return 1
    if (kind == "depth" and tier == 2) or (kind == "book" and tier == 1):
        return 2
    return 3


class Enqueuer:
    """Bounded queue with priority shedding. Drops are counted and turned into explicit backpressure gaps."""

    LEVELS = ((0.95, 1), (0.80, 2), (0.60, 3))     # (fill ratio, drop priorities >= this)

    def __init__(self, q: queue.Queue, maxsize: int, stats: dict):
        self.q, self.max, self.stats = q, maxsize, stats
        self.drop_open = {}                          # type -> [first_ms, last_ms, count]
        self.peak = 0

    def put(self, rec: dict, prio: int) -> bool:
        size = self.q.qsize(); self.peak = max(self.peak, size)
        ratio = size / self.max
        for lvl, min_prio in self.LEVELS:
            if ratio >= lvl and prio >= min_prio:
                return self._drop(rec)
        rec["queued_ts_ns"] = time.time_ns()
        try:
            self.q.put_nowait(rec)
            return True
        except queue.Full:
            return self._drop(rec)

    def _drop(self, rec: dict) -> bool:
        t = rec.get("type", "?"); m = now_ms()
        self.stats["dropped"][t] += 1
        d = self.drop_open.setdefault(t, [m, m, 0]); d[1] = m; d[2] += 1
        return False

    def closed_drop_intervals(self, quiet_ms: int = 60_000, force: bool = False) -> list:
        out, m = [], now_ms()
        for t, (a, b, n) in list(self.drop_open.items()):
            if force or m - b >= quiet_ms:
                out.append((t, a, b, n)); del self.drop_open[t]
        return out


class Collector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.boot_id = uuid.uuid4().hex
        self.base = cfg["data_dir"]
        self.stats = new_stats()
        self.q = queue.Queue(maxsize=cfg["queue_max"])
        self.enq = Enqueuer(self.q, cfg["queue_max"], self.stats)
        self.writer = SegmentWriter(self.base, self.boot_id, self.q, self.stats, cfg["flush_interval_s"])
        self.rate = RateGuard(cfg["rest_budget_weight_per_min"], cfg["rest_defer_used_weight"], cfg["rest_pause_used_weight"])
        self.disk = DiskGuard(cfg["disk_warn_free_gb"], cfg["disk_stop_free_gb"], cfg["dir_stop_gb"])
        self.clock = ClockGuard(cfg["clock_warn_ms"], cfg["clock_crit_ms"])
        self.state = "STARTING"
        self.disk_state, self.disk_free_gb, self.dir_gb = "UNKNOWN", None, None
        self.universe = None
        self.streams = {}          # stream name -> {kind, symbol, tier, cadence, levels}
        self.slots = {}            # stream name -> (recv_ns, payload, seq)
        self.last_persisted_seq = {}
        self.market = {}           # symbol -> (recv_ns, obj)
        self.gaps_open = {}        # stream key -> {start_ms, cause}
        self.gap_count = 0
        self.conns = []
        self.rotation = {"tests": 0, "events": []}
        self.started_mono = time.monotonic()
        self.stop_event = asyncio.Event()
        self.last_obs = {}
        self.session = None
        self.rest = None
        self.config_hash = C.config_hash(cfg)

    # ---------- records ----------
    def emit(self, kind: str, rec: dict, tier=None) -> None:
        if self.clock.suspect():
            rec["clock_suspect"] = True
        errs = R.validate(rec)
        if errs:
            self.stats["rejected"][errs[0]] += 1
            return
        if self.enq.put(rec, priority(kind, tier)):
            self.last_obs[kind if kind != "candle" else f"candle_{rec['endpoint'].split('interval=')[-1]}"] = now_ms()

    def lifecycle(self, event: str, payload: dict) -> None:
        self.emit("lifecycle", R.make(type="lifecycle", obs_id=R.lifecycle_id(self.boot_id, f"{event}|{now_ms()}"),
                                      symbol=None, payload={"event": event, **payload}, boot_id=self.boot_id,
                                      endpoint="collector", transport="internal", recv_ts_ns=time.time_ns()))

    def gap(self, key: str, start_ms: int, end_ms: int, cause: str, recoverability: str, extra: dict | None = None) -> None:
        self.gap_count += 1
        self.emit("gap", R.make(type="gap", obs_id=R.gap_id(key, start_ms, cause), symbol=key.split("|")[-1] if "|" in key else None,
                                payload={"stream_key": key, "start_ms": start_ms, "end_ms": end_ms,
                                         "duration_ms": max(0, end_ms - start_ms), "cause": cause, **(extra or {})},
                                boot_id=self.boot_id, endpoint="collector", transport="internal",
                                recv_ts_ns=time.time_ns(), recoverability=recoverability))

    # ---------- universe / streams ----------
    def build_streams(self) -> None:
        cad, lv = self.cfg["cadence_ms"], self.cfg["depth_levels"]
        st = {}
        for tier, syms in ((0, self.universe["tier0"]), (2, self.universe["tier2"]), (1, self.universe["tier1"])):
            t = f"t{tier}"
            for s in syms:
                low = s.lower()
                st[f"{low}@bookTicker"] = {"kind": "book", "symbol": s, "tier": tier, "cadence": cad[f"{t}_book"]}
                n = lv[t]
                st[f"{low}@depth{n}"] = {"kind": "depth", "symbol": s, "tier": tier, "cadence": cad[f"{t}_depth"], "levels": n}
        self.streams = st

    async def load_universe(self) -> None:
        if self.cfg["profile"] == "tier0_only":
            self.universe = U.tier0_only(self.cfg)
        else:
            s1, ei, r1, *_ = await self.rest.get("/api/v3/exchangeInfo", {"permissions": "SPOT", "symbolStatus": "TRADING"}, urgent=True)
            s2, tk, r2, *_ = await self.rest.get("/api/v3/ticker/24hr", {"type": "MINI"}, urgent=True)
            if s1 != 200 or s2 != 200:
                raise RuntimeError(f"universe refresh failed: {s1}/{s2}")
            self.universe = U.compute(self.cfg, ei, tk, self._prior_tier1())
            self.universe["source_recv_ns"] = [r1, r2]
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = os.path.join(self.base, "universe", f"universe-{stamp}.json")
        tmp = path + ".partial"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({**self.universe, "stamp": stamp, "boot_id": self.boot_id, "config_hash": self.config_hash}, fh, sort_keys=True)
            fh.flush(); os.fsync(fh.fileno())
        os.rename(tmp, path); os.chmod(path, 0o444)
        self.emit("universe", R.make(type="universe", obs_id=R.universe_id(stamp, self.universe["rule_version"]), symbol=None,
                                     payload={**self.universe, "file": os.path.basename(path), "sha256": sha256_file(path)},
                                     boot_id=self.boot_id, endpoint="universe", transport="rest" if self.cfg["profile"] != "tier0_only" else "internal",
                                     recv_ts_ns=time.time_ns()))
        self.build_streams()

    def _prior_tier1(self) -> set:
        out, cutoff = set(), time.time() - self.cfg["tier1_hysteresis_days"] * 86400
        d = os.path.join(self.base, "universe")
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            p = os.path.join(d, f)
            if f.endswith(".json") and os.path.getmtime(p) >= cutoff:
                try:
                    u = json.load(open(p, encoding="utf-8"))
                    out |= set(u.get("tier1", [])) | set(u.get("tier2", []))
                except (OSError, ValueError):
                    pass
        return out

    # ---------- websocket ----------
    def on_message(self, conn, obj, recv_ns: int) -> None:
        if obj is None or not isinstance(obj, dict) or "stream" not in obj:
            self.stats["malformed"] += 1; return
        name, data = obj["stream"], obj.get("data")
        if name == "!miniTicker@arr":
            if isinstance(data, list):
                for t in data:
                    s = t.get("s") if isinstance(t, dict) else None
                    if s and s.endswith("USDT"):
                        ring = self.market.get(s)
                        if ring is None:
                            ring = self.market[s] = collections.deque(maxlen=3)
                        ring.append((recv_ns, t, 0))
            return
        meta = self.streams.get(name)
        if meta is None or not isinstance(data, dict):
            self.stats["malformed"] += 1; return
        seq = data.get("u") if meta["kind"] == "book" else data.get("lastUpdateId")
        if not isinstance(seq, int):
            self.stats["malformed"] += 1; return
        ring = self.slots.get(name)
        if ring is None:
            ring = self.slots[name] = collections.deque(maxlen=8)
        if ring and seq < ring[-1][2]:
            self.stats["rejected"]["seq_regression"] += 1        # older message (e.g. rotation overlap): ignore
            return
        ring.append((recv_ns, data, seq))

    def on_shutdown_event(self, conn, obj, recv_ns: int) -> None:
        self.lifecycle("server_shutdown_event", {"conn": conn.name, "recv_ns": recv_ns})
        asyncio.get_running_loop().create_task(self.rotate(conn, reason="serverShutdown"))

    def on_state(self, conn, state: str) -> None:
        self.lifecycle(f"ws_{state}", {"conn": conn.name, "reconnects": conn.reconnects})

    def _conn_streams(self) -> list:
        book = sorted(n for n, m in self.streams.items() if m["kind"] == "book")
        depth = sorted(n for n, m in self.streams.items() if m["kind"] == "depth")
        return [("conn0-book", book + ["!miniTicker@arr"]), ("conn1-depth", depth)]

    async def start_ws(self) -> None:
        for name, streams in self._conn_streams():
            if len(streams) > 300:
                raise RuntimeError("stream budget exceeded (<= 300 per connection)")
            c = WSConnection(name, streams, self.session, self.on_message, self.on_shutdown_event, self.on_state,
                             backoff=Backoff(), guard=self.rate)
            self.conns.append(c)
            c.task = asyncio.create_task(c.run(), name=name)

    async def rotate(self, old: WSConnection, reason: str) -> dict:
        """Overlap rollover: open a replacement, wait for its first message, then close the old connection."""
        t0 = now_ms()
        new = WSConnection(old.name, old.streams, self.session, self.on_message, self.on_shutdown_event, self.on_state,
                           backoff=Backoff(), guard=self.rate)
        new.task = asyncio.create_task(new.run(), name=old.name + "-r")
        try:
            await asyncio.wait_for(new.first_msg.wait(), timeout=60)
            overlap_ok = True
        except asyncio.TimeoutError:
            overlap_ok = False
        t1 = now_ms()
        await old.close()
        idx = self.conns.index(old); self.conns[idx] = new
        ev = {"conn": old.name, "reason": reason, "started_ms": t0, "new_first_msg_ms": t1, "overlap_ok": overlap_ok,
              "old_last_msg_ms": (old.last_msg_ns or 0) // 1_000_000}
        self.rotation["events"].append(ev)
        self.lifecycle("ws_rotation", ev)
        return ev

    # ---------- sampling ----------
    def _stale_limit(self, meta) -> int:
        if meta["kind"] == "depth":
            return STALE_MS["depth"]
        return STALE_MS["book_t0"] if meta["tier"] == 0 else STALE_MS["book"]

    @staticmethod
    def _at_or_before(ring, sample_ms: int):
        if not ring:
            return None
        for item in reversed(ring):
            if item[0] // 1_000_000 <= sample_ms:
                return item
        return None

    def sample(self, sample_ms: int) -> None:
        for name, meta in self.streams.items():
            if sample_ms % meta["cadence"]:
                continue
            slot = self._at_or_before(self.slots.get(name), sample_ms)   # PIT: never a message received after the sample
            key = f"{meta['kind']}|{meta['symbol']}"
            fresh = slot is not None and sample_ms - slot[0] // 1_000_000 <= self._stale_limit(meta)
            if not fresh:
                if key not in self.gaps_open:
                    start = slot[0] // 1_000_000 if slot else int(self.started_ms)
                    cause = "disconnected" if not any(c.connected for c in self.conns) else "stale_stream"
                    self.gaps_open[key] = {"start_ms": start, "cause": cause}
                continue
            if key in self.gaps_open:
                g = self.gaps_open.pop(key)
                self.gap(key, g["start_ms"], slot[0] // 1_000_000, g["cause"], IRREPLACEABLE)
            recv_ns, data, seq = slot
            unchanged = self.last_persisted_seq.get(name) == seq
            self.last_persisted_seq[name] = seq
            if meta["kind"] == "book":
                oid = R.book_id(meta["symbol"], seq, meta["cadence"], sample_ms)
            else:
                oid = R.depth_id(meta["levels"], meta["symbol"], seq, meta["cadence"], sample_ms)
            self.emit(meta["kind"], R.make(type=meta["kind"], obs_id=oid, symbol=meta["symbol"], payload=data,
                                           boot_id=self.boot_id, endpoint=name, transport="ws", recv_ts_ns=recv_ns,
                                           exchange_seq=seq, tier=meta["tier"], cadence_ms=meta["cadence"],
                                           sample_ms=sample_ms, unchanged=unchanged, recoverability=IRREPLACEABLE),
                      tier=meta["tier"])
        if sample_ms % self.cfg["cadence_ms"]["market"] == 0 and self.market:
            items = sorted((s, (v[0], v[1])) for s, v in ((s, self._at_or_before(r, sample_ms)) for s, r in self.market.items()) if v)
            if not items:
                return
            last_recv = max(r for _, (r, _) in items)
            ex = max((o.get("E") for _, (_, o) in items if isinstance(o.get("E"), int)), default=None)
            self.emit("market", R.make(type="market", obs_id=R.market_id(sample_ms), symbol=None,
                                       payload=[o for _, (_, o) in items], boot_id=self.boot_id, endpoint="!miniTicker@arr",
                                       transport="ws", recv_ts_ns=last_recv, exchange_event_time_ms=ex, sample_ms=sample_ms,
                                       cadence_ms=self.cfg["cadence_ms"]["market"], recoverability=IRREPLACEABLE))

    async def sampler_task(self) -> None:
        while not self.stop_event.is_set():
            nxt = (now_ms() // 1000 + 1) * 1000
            await asyncio.sleep(max(0, nxt - now_ms()) / 1000)
            self.sample(nxt)
            for t, a, b, n in self.enq.closed_drop_intervals():
                self.gap(f"backpressure|{t}", a, b, "backpressure", IRREPLACEABLE if t in ("book", "depth", "market") else RECOVERABLE, {"dropped": n})

    # ---------- REST tasks ----------
    async def candle_job(self, sym: str, tf: str, open_ms: int, deadline_mono: float) -> None:
        params = {"symbol": sym, "interval": tf, "startTime": open_ms, "endTime": open_ms, "limit": 1}
        while not self.stop_event.is_set():
            status, data, recv_ns, *_ = await self.rest.get("/api/v3/klines", params)
            if status == 200:
                if not (isinstance(data, list) and len(data) == 1 and int(data[0][0]) == open_ms and int(data[0][6]) < recv_ns // 1_000_000):
                    self.stats["rejected"]["candle_unexpected"] += 1; return
                k = data[0]
                self.emit("candle", R.make(type="candle", obs_id=R.candle_id(sym, tf, open_ms), symbol=sym, payload=k,
                                           boot_id=self.boot_id, endpoint=f"/api/v3/klines?interval={tf}", transport="rest",
                                           recv_ts_ns=recv_ns, exchange_event_time_ms=int(k[6]),
                                           available_at_ms=max(int(k[6]) + 1, recv_ns // 1_000_000),
                                           recoverability=RECOVERABLE))
                return
            if status in ("own_budget", "deferred_ip_weight", "rest_blocked", "paused_ip_weight", "circuit_open", "network_error", 429) \
                    and time.monotonic() < deadline_mono:
                await asyncio.sleep(2 + random.random() * 3); continue
            self.gap(f"candle|{tf}|{sym}", open_ms, open_ms + TF_MS[tf] - 1, f"candle_fetch_failed:{status}", RECOVERABLE)
            return

    def _candle_symbols(self) -> list:
        u = self.universe
        return sorted(set(u["tier0"]) | set(u["tier1"]) | set(u["tier2"]))

    async def candle_round(self, boundary_ms: int, tfs: list) -> None:
        jobs = [(s, tf, boundary_ms - TF_MS[tf]) for tf in tfs for s in self._candle_symbols()]
        window = 300.0 if len(tfs) > 1 else 120.0
        deadline = time.monotonic() + window + 600
        tasks = []
        for i, (s, tf, o) in enumerate(jobs):
            await asyncio.sleep(window / max(1, len(jobs)))
            if self.stop_event.is_set():
                break
            tasks.append(asyncio.create_task(self.candle_job(s, tf, o, deadline)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def candle_task(self) -> None:
        first = True
        while not self.stop_event.is_set():
            if first:                                                  # catch-up: last closed candle of every TF
                tfs = list(self.cfg["candle_timeframes"]); boundary = None; first = False
                for tf in tfs:
                    b = (now_ms() // TF_MS[tf]) * TF_MS[tf]
                    asyncio.create_task(self.candle_round(b, [tf]))
                continue
            nxt = (now_ms() // TF_MS["15m"] + 1) * TF_MS["15m"]
            await self._sleep_until(nxt + 5_000 + int(random.random() * 10_000))
            if self.stop_event.is_set():
                break
            tfs = [tf for tf in self.cfg["candle_timeframes"] if nxt % TF_MS[tf] == 0]
            asyncio.create_task(self.candle_round(nxt, tfs))

    async def clock_task(self) -> None:
        while not self.stop_event.is_set():
            status, data, recv_ns, t0, t1 = await self.rest.get("/api/v3/time", urgent=True)
            if status == 200 and isinstance(data, dict) and isinstance(data.get("serverTime"), int):
                st = self.clock.update(data["serverTime"], t0, t1)
                self.emit("clock", R.make(type="clock", obs_id=R.clock_id(data["serverTime"]), symbol=None,
                                          payload={"serverTime": data["serverTime"], "t0_ms": t0, "t1_ms": t1,
                                                   "rtt_ms": t1 - t0, "skew_ms": self.clock.last_skew_ms, "state": st},
                                          boot_id=self.boot_id, endpoint="/api/v3/time", transport="rest", recv_ts_ns=recv_ns,
                                          exchange_event_time_ms=data["serverTime"]))
            await self._sleep(self.cfg["cadence_ms"]["clock"] / 1000)

    async def disk_task(self) -> None:
        while not self.stop_event.is_set():
            free = shutil.disk_usage(self.base).free
            size = 0
            for root, _, files in os.walk(self.base):
                for f in files:
                    try:
                        size += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            self.disk_free_gb, self.dir_gb = free / 1e9, size / 1e9
            st = self.disk.state(free, size)
            if st != self.disk_state:
                self.lifecycle("disk_state", {"state": st, "free_gb": round(self.disk_free_gb, 2), "dir_gb": round(self.dir_gb, 4)})
            self.disk_state = st
            if st == "HARD_STOP":
                self.writer.stop_writes.set()
            await self._sleep(60)

    # ---------- health ----------
    def health(self) -> dict:
        m = now_ms()
        state = self.state
        if state == "RUNNING":
            if self.disk_state == "HARD_STOP":
                state = "DEGRADED_DISK"
            elif self.rate.banned():
                state = "BANNED_418"
            elif self.clock.state == "CRITICAL" or self.stats["write_errors"] or any(not c.connected for c in self.conns):
                state = "DEGRADED"
        return {
            "ts_ms": m, "version": C.VERSION, "boot_id": self.boot_id, "state": state, "profile": self.cfg["profile"],
            "config_hash": self.config_hash, "uptime_s": round(time.monotonic() - self.started_mono, 1),
            "ws": [{"conn": c.name, "connected": c.connected, "streams": len(c.streams), "reconnects": c.reconnects,
                    "last_msg_age_ms": (m - c.last_msg_ns // 1_000_000) if c.last_msg_ns else None} for c in self.conns],
            "last_obs_age_ms": {k: m - v for k, v in sorted(self.last_obs.items())},
            "last_durable_write_ms": (self.writer.last_durable_ns or 0) // 1_000_000 or None,
            "queue_depth": self.q.qsize(), "queue_peak": self.enq.peak,
            "dropped": dict(self.stats["dropped"]), "written": dict(self.stats["written"]),
            "duplicates_dropped": self.stats["duplicates_dropped"], "rejected": dict(self.stats["rejected"]),
            "malformed": self.stats["malformed"], "write_errors": self.stats["write_errors"],
            "segments": {"open": sorted(self.writer.segments), "promoted": self.stats["segments_promoted"],
                         "quarantined": self.stats["segments_quarantined"]},
            "gaps_open": len(self.gaps_open), "gaps_closed_total": self.gap_count,
            "universe": {k: len(self.universe[k]) for k in ("tier0", "tier1", "tier2")} if self.universe else None,
            "rest": {"own_weight_1m": self.rate.own_used(), "budget": self.cfg["rest_budget_weight_per_min"],
                     "ip_used_weight_1m_seen": self.rate.observed, "events": dict(self.rate.events),
                     "total_weight": self.rest.weight_used_total if self.rest else 0},
            "clock": {"state": self.clock.state, "skew_ms": self.clock.last_skew_ms},
            "disk": {"state": self.disk_state, "free_gb": self.disk_free_gb, "collector_dir_gb": self.dir_gb},
            "rotation": self.rotation,
        }

    def write_health(self) -> None:
        d = os.path.join(self.base, "health"); os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "collector_health.json"); tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.health(), fh, sort_keys=True, default=str)
        os.replace(tmp, p)

    async def health_task(self) -> None:
        while not self.stop_event.is_set():
            self.write_health()
            await self._sleep(self.cfg["health_interval_s"])

    # ---------- helpers ----------
    async def _sleep(self, s: float) -> None:
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=s)
        except asyncio.TimeoutError:
            pass

    async def _sleep_until(self, target_ms: int) -> None:
        await self._sleep(max(0.0, (target_ms - now_ms()) / 1000))

    async def rotation_test_task(self) -> None:
        at = self.cfg["rotation_test_at_s"]
        if at <= 0:
            return
        await self._sleep(at)
        if not self.stop_event.is_set() and self.conns:
            ev = await self.rotate(self.conns[0], reason="controlled_rotation_test")
            self.rotation["tests"] += 1
            self.rotation["test_result"] = ev

    # ---------- run ----------
    async def run(self) -> int:
        self.started_ms = now_ms()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop_event.set)
        rec_gaps = recover_partials(self.base, self.boot_id, self.stats)
        self.writer.start()
        self.lifecycle("start", {"config_hash": self.config_hash, "profile": self.cfg["profile"],
                                 "max_runtime_s": self.cfg["max_runtime_s"], "recovered": rec_gaps})
        for g in rec_gaps:
            self.gap(f"crash|{g['type']}", (g["last_salvaged_recv_ns"] or 0) // 1_000_000, self.started_ms, "crash_recovery",
                     IRREPLACEABLE, {"salvaged": g["salvaged"], "source": g["source"]})
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "tsb-p2-forward/" + C.VERSION}) as self.session:
            self.rest = RestClient(self.session, self.rate, self.stats)
            await self.load_universe()
            self.state = "RUNNING"
            await self.start_ws()
            tasks = [asyncio.create_task(c(), name=c.__name__) for c in
                     (self.sampler_task, self.candle_task, self.clock_task, self.disk_task, self.health_task, self.rotation_test_task)]
            reason = "max_runtime"
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.cfg["max_runtime_s"])
                reason = "signal"
            except asyncio.TimeoutError:
                pass
            self.stop_event.set()
            self.state = "STOPPING"
            for c in self.conns:
                await c.close()
            for t in tasks + [getattr(c, "task", None) for c in self.conns]:
                if t is not None:
                    t.cancel()
            await asyncio.gather(*[t for t in tasks if t], return_exceptions=True)
        m = now_ms()
        for key, g in list(self.gaps_open.items()):
            self.gap(key, g["start_ms"], m, g["cause"] + "_open_at_stop", IRREPLACEABLE)
        for t, a, b, n in self.enq.closed_drop_intervals(force=True):
            self.gap(f"backpressure|{t}", a, b, "backpressure", IRREPLACEABLE, {"dropped": n})
        self.lifecycle("stop", {"reason": reason, "uptime_s": round(time.monotonic() - self.started_mono, 1)})
        self.writer.stop(); self.writer.join(timeout=120)
        self.state = "STOPPED"
        self.write_health()
        return 0


async def disabled_loop(cfg: dict) -> int:
    """G1 OFF state: no network, no capture; only a health file saying DISABLED."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    d = os.path.join(cfg["data_dir"], "health"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "collector_health.json")
    while not stop.is_set():
        with open(p + ".tmp", "w", encoding="utf-8") as fh:
            json.dump({"ts_ms": now_ms(), "version": C.VERSION, "state": "DISABLED", "config_hash": C.config_hash(cfg)}, fh)
        os.replace(p + ".tmp", p)
        try:
            await asyncio.wait_for(stop.wait(), timeout=cfg["health_interval_s"])
        except asyncio.TimeoutError:
            pass
    return 0


def main() -> int:
    cfg = C.load(os.environ.get("P2F_CONFIG", "/config/collector.json"))
    if not cfg["enabled"]:
        return asyncio.run(disabled_loop(cfg))
    return asyncio.run(Collector(cfg).run())
