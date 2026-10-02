"""Forward market-intelligence collector (P2-E1): orchestration, sampling, gaps, backpressure, health.

One asyncio process; supervised tasks; a dedicated writer thread. Zero trading authority. Bounded runtime only.
Entry point: `python -m p2_forward` (config path in env P2F_CONFIG, default /config/collector.json).

G2-Repeat revision: exact PIT sampling for any burst size (tracks.Held), every boundary processed after a stall,
explicit stream state machine with subscription acks and first-observation deadlines, data-liveness (not socket
liveness), supervised tasks, writer liveness, 418 closes all WebSockets, collision-free control-record ids,
explicit HEALTHY invariant, historical health records, disk-stop evidence and run provenance.
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
import sys
import time
import uuid

import aiohttp

from . import config as C
from . import provenance as P
from . import record as R
from . import universe as U
from .guards import Backoff, ClockGuard, DiskGuard, RateGuard
from .tracks import FAILED, NONE, OBSERVING, MarketTrack, StreamTrack
from .transport import RestClient, WSConnection
from .writer import SegmentWriter, new_stats, recover_partials, sha256_file

TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
IRREPLACEABLE = "IRREPLACEABLE_FORWARD_OBSERVATION"
RECOVERABLE = "RECOVERABLE_WHERE_ARCHIVE_AVAILABLE"
MARKET = "!miniTicker@arr"
EXIT_OK, EXIT_INCOMPLETE, EXIT_WRITER, EXIT_TASK, EXIT_STARTUP = 0, 2, 3, 4, 5
TASK_PERIOD_S = {"sampler": 1.0, "candles": 900.0, "clock": 600.0, "disk": 60.0, "health": 10.0, "watchdog": 1.0}


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def priority(kind: str, tier) -> int:
    """0 = keep longest (Tier 0, candles, control records) ... 3 = shed first (Tier-1 depth)."""
    if kind in ("candle", "clock", "universe", "gap", "lifecycle", "health") or tier == 0:
        return 0
    if kind == "market" or (kind == "book" and tier == 2):
        return 1
    if (kind == "depth" and tier == 2) or (kind == "book" and tier == 1):
        return 2
    return 3


class Enqueuer:
    """Bounded queue with priority shedding. Drops are counted and turned into explicit gaps."""

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


class ConnActivity:
    """Per-connection data liveness (F40): receive times of DATA messages (pings never count) + up/down history."""

    def __init__(self):
        self.first_in_sec = collections.OrderedDict()     # second -> first data recv_ms in that second
        self.count_in_sec = collections.OrderedDict()     # second -> number of data messages
        self.transitions = collections.deque(maxlen=512)  # (ms, up)

    last_data_ms = None

    def data(self, recv_ms: int) -> None:
        self.last_data_ms = recv_ms
        sec = recv_ms // 1000
        if sec not in self.first_in_sec:
            self.first_in_sec[sec] = recv_ms
            while len(self.first_in_sec) > 400:
                self.first_in_sec.popitem(last=False)
        self.count_in_sec[sec] = self.count_in_sec.get(sec, 0) + 1
        while len(self.count_in_sec) > 70:
            self.count_in_sec.popitem(last=False)

    def data_in(self, lo_ms: int, hi_ms: int) -> bool:
        for sec in range(hi_ms // 1000, lo_ms // 1000 - 1, -1):
            r = self.first_in_sec.get(sec)
            if r is not None and lo_ms <= r <= hi_ms:
                return True
        return False

    def up_at(self, ms: int):
        last = None
        for t, up in self.transitions:
            if t <= ms:
                last = up
            else:
                break
        return last

    def last_up_since(self, ms: int):
        """Time of the most recent connect (up transition) at or before ms, or None (M3)."""
        last = None
        for t, up in self.transitions:
            if t > ms:
                break
            if up:
                last = t
        return last

    def rate(self, now: int) -> float:
        sec = now // 1000
        return round(sum(n for s, n in self.count_in_sec.items() if sec - 60 <= s < sec) / 60.0, 2)


class Collector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.boot_id = uuid.uuid4().hex
        self.base = cfg["data_dir"]
        self.stats = new_stats()
        self.q = queue.Queue(maxsize=cfg["queue_max"])
        self.enq = Enqueuer(self.q, cfg["queue_max"], self.stats)
        self.writer = SegmentWriter(self.base, self.boot_id, self.q, self.stats, cfg["flush_interval_s"])
        self.rate = RateGuard(cfg["rest_budget_weight_per_min"], cfg["rest_defer_used_weight"], cfg["rest_pause_used_weight"],
                              urgent_reserve=cfg["rest_urgent_reserve"])
        self.rate.ban_callbacks.append(self.on_ban)
        self.disk = DiskGuard(cfg["disk_warn_free_gb"], cfg["disk_stop_free_gb"], cfg["dir_stop_gb"])
        self.clock = ClockGuard(cfg["clock_warn_ms"], cfg["clock_crit_ms"])
        self.state = "STARTING"
        self.disk_state, self.disk_free_gb, self.dir_gb = "UNKNOWN", None, None
        self.universe = None
        self.streams = {}          # stream name -> {kind, symbol, tier, cadence, levels}
        self.tracks = {}           # stream name -> StreamTrack (book / depth)
        self.market = None         # MarketTrack
        self.stream_conn = {}      # stream name -> connection name
        self.activity = collections.defaultdict(ConnActivity)
        self.conns = []
        self.rotating = set()
        self.rotation = {"tests": 0, "events": []}
        self.started_mono = time.monotonic()
        self.started_ms = now_ms()
        self.ws_start_ms = None
        self.ready_ms = None       # all expected streams first observed
        self.last_sampled_ms = None
        self.stop_event = asyncio.Event()
        self.stop_reason = None
        self.exit_code = EXIT_OK
        self.ctl_seq = 0
        self.gap_count = 0
        self.beats = {}
        self.task_failures = collections.defaultdict(collections.deque)
        self.candle_tasks = set()
        self.aux_tasks = set()
        self.handler_err_ms = collections.deque(maxlen=1000)
        self.loop_lag = collections.deque(maxlen=120)     # (ms, lag_ms)
        self.catchup_boundaries = 0
        self.ban_since_ms = None
        self.health_state_last = None
        self.health_record_last_mono = None
        self.disk_marker = None
        self.session = None
        self.rest = None
        self.run_record = None
        self.run_record_sha = None
        self.config_hash = C.config_hash(cfg)
        self.session_factory = None            # tests: offline fake session; production: aiohttp.ClientSession
        self.task_restart_delay_s = 1.0
        self.stats["emit_failed"] = collections.Counter()
        self.task_fail_ms = collections.deque(maxlen=100)
        self.wall_step_ms = collections.deque(maxlen=100)
        self.wall_offset = time.time() - time.monotonic()
        self.data_stall_forced = {}
        self.expired_syms = set()
        self._lateness = None
        self.universe_meta = None          # {universe_id, file, sha256, stamp} of the ACTIVE universe (R04)
        self.universe_degraded = None      # F42: reason while a refresh failed and the previous universe is kept
        self.startup_failure = None        # F25: reasons when no trustworthy initial universe could be established
        self.reconnect_test = None         # G3 controlled reconnect state

    @property
    def stream_state(self) -> dict:
        return {t.name: {"state": t.state(), "sub": t.sub, "ready_ms": t.ready_ms, "conn": t.conn}
                for t in self.all_tracks()}

    # ---------- records ----------
    def _seq(self) -> int:
        self.ctl_seq += 1
        return self.ctl_seq

    def emit(self, kind: str, rec: dict, tier=None) -> bool:
        if self.clock.suspect():
            rec["clock_suspect"] = True
        errs = R.validate(rec)
        ok = not errs and self.enq.put(rec, priority(kind, tier))
        if errs:
            self.stats["rejected"][errs[0]] += 1
        if not ok and kind not in ("book", "depth", "market"):     # sampled kinds get per-boundary gaps instead
            self.stats["emit_failed"][kind] += 1
        return ok

    def lifecycle(self, event: str, payload: dict) -> None:
        self.emit("lifecycle", R.make(type="lifecycle", obs_id=R.lifecycle_id(self.boot_id, self._seq(), event),
                                      symbol=None, payload={"event": event, **payload}, boot_id=self.boot_id,
                                      endpoint="collector", transport="internal", recv_ts_ns=time.time_ns()))

    def gap_record(self, g: dict, recoverability: str, extra: dict | None = None) -> None:
        self.gap_count += 1
        key = g["stream_key"]
        self.emit("gap", R.make(type="gap", obs_id=R.gap_id(self.boot_id, self._seq(), key, g["first_missing_ms"],
                                                            g["last_missing_ms"], g["cause"]),
                                symbol=key.split("|")[-1] if "|" in key else None, payload={**g, **(extra or {})},
                                boot_id=self.boot_id, endpoint="collector", transport="internal",
                                recv_ts_ns=time.time_ns(), recoverability=recoverability, cadence_ms=g.get("cadence_ms")))

    def simple_gap(self, key: str, first_ms: int, last_ms: int, cadence: int, cause: str, recoverability: str,
                   extra: dict | None = None) -> None:
        n = (last_ms - first_ms) // cadence + 1 if cadence else 1
        self.gap_record({"stream_key": key, "stream": key, "first_missing_ms": first_ms, "last_missing_ms": last_ms,
                         "missing_samples": n, "cadence_ms": cadence, "duration_ms": last_ms - first_ms + cadence,
                         "cause": cause, "causes": [cause], "open_at_stop": False, "start_ms": first_ms,
                         "end_ms": last_ms + cadence}, recoverability, extra)

    # ---------- universe / streams ----------
    def build_streams(self) -> None:
        cad, lv, cfg = self.cfg["cadence_ms"], self.cfg["depth_levels"], self.cfg
        dl, hold = cfg["first_obs_deadline_s"], int(cfg["sample_hold_window_s"] * 1000)
        st, tracks = {}, {}
        for tier, syms in ((0, self.universe["tier0"]), (2, self.universe["tier2"]), (1, self.universe["tier1"])):
            t = f"t{tier}"
            for s in syms:
                low = s.lower()
                nb, n = f"{low}@bookTicker", lv[t]
                nd = f"{low}@depth{n}"
                st[nb] = {"kind": "book", "symbol": s, "tier": tier, "cadence": cad[f"{t}_book"]}
                st[nd] = {"kind": "depth", "symbol": s, "tier": tier, "cadence": cad[f"{t}_depth"], "levels": n}
                tracks[nb] = StreamTrack(nb, "book", s, tier, cad[f"{t}_book"], "conn0-book",
                                         cfg["book_t0_stale_ms"] if tier == 0 else 10 ** 15,
                                         1000 * (dl["t0_book"] if tier == 0 else dl["t12_book"]), hold)
                tracks[nd] = StreamTrack(nd, "depth", s, tier, cad[f"{t}_depth"], "conn1-depth", cfg["depth_stale_ms"],
                                         1000 * dl["depth"], hold, levels=n)
        self.streams, self.tracks = st, tracks
        self.market = MarketTrack(cad["market"], "conn0-book", cfg["market_stale_ms"], 1000 * dl["market"], hold,
                                  cfg["market_component_max_age_ms"])
        self.stream_conn = {n: t.conn for n, t in tracks.items()}
        self.stream_conn[MARKET] = "conn0-book"

    def expected_streams(self) -> list:
        out = [{"stream": n, "kind": t.kind, "symbol": t.symbol, "tier": t.tier, "cadence_ms": t.cadence,
                "depth_levels": t.levels, "conn": t.conn, "stale_ms": t.stale_ms, "first_obs_deadline_ms": t.deadline_rel_ms}
               for n, t in sorted(self.tracks.items())]
        m = self.market
        if m is None:
            return out
        out.append({"stream": MARKET, "kind": "market", "symbol": None, "tier": None, "cadence_ms": m.cadence,
                    "depth_levels": None, "conn": m.conn, "stale_ms": m.stale_ms, "first_obs_deadline_ms": m.deadline_rel_ms})
        return out

    def all_tracks(self) -> list:
        return list(self.tracks.values()) + ([self.market] if self.market else [])

    async def fetch_universe(self, prior: dict | None) -> tuple:
        """One REST evaluation. Returns (universe | None, problems). F42: never authoritative unless sane."""
        params_ei = {"permissions": "SPOT", "showPermissionSets": "false"}       # all statuses: survivorship (R04)
        params_tk = {"type": "MINI"}
        s1, ei, r1, *_ = await self.rest.get("/api/v3/exchangeInfo", params_ei, urgent=True)
        s2, tk, r2, *_ = await self.rest.get("/api/v3/ticker/24hr", params_tk, urgent=True)
        if s1 != 200 or s2 != 200:
            return None, [f"http_status:{s1}/{s2}"]
        ok, problems, stats = U.validate_inputs(self.cfg, ei, tk)
        if not ok:
            return None, problems
        uni = U.evaluate(self.cfg, ei, tk, prior)
        uni["validation"] = stats
        uni["source"] = {"exchangeinfo": {"path": "/api/v3/exchangeInfo", "params": params_ei, "recv_ns": r1,
                                          "body_sha256": self.rest.last_body_sha256.get("/api/v3/exchangeInfo")},
                         "ticker": {"path": "/api/v3/ticker/24hr", "params": params_tk, "recv_ns": r2,
                                    "body_sha256": self.rest.last_body_sha256.get("/api/v3/ticker/24hr")}}
        return uni, U.plausible_vs_prior(self.cfg, uni, prior)

    async def establish_universe(self) -> bool:
        """F25: bounded attempts with backoff; every failed attempt is durable (lifecycle); no trustworthy universe
        => False (the caller fails closed). No silent fallback to an unknown or partial universe."""
        if self.cfg["profile"] == "tier0_only":
            self.persist_universe(U.tier0_only(self.cfg), applied=True)
            return True
        prior = self._prior_universe()
        n, backoff, problems = self.cfg["universe_load_attempts"], self.cfg["universe_retry_backoff_s"], []
        for attempt in range(1, n + 1):
            try:
                uni, problems = await self.fetch_universe(prior)
            except Exception as e:                                    # noqa: BLE001 - malformed shapes etc.
                uni, problems = None, [f"exception:{type(e).__name__}: {e}"[:200]]
            if uni is not None and not problems:
                self.persist_universe(uni, applied=True)
                return True
            self.lifecycle("universe_attempt_failed", {"attempt": attempt, "of": n, "problems": problems[:20]})
            if attempt < n:
                await self._sleep(backoff[min(attempt - 1, len(backoff) - 1)])
                if self.stop_event.is_set():
                    break
        self.startup_failure = problems or ["stopped_during_universe_load"]
        return False

    async def refresh_universe(self) -> str:
        """F42 refresh policy (deterministic; NOT scheduled in E1 — daily refresh / re-subscription is F10).
        A suspicious or failed refresh never replaces the active universe; the collector is DEGRADED until a
        refresh succeeds. A successful evaluation is persisted (applied=False: re-subscription is F10)."""
        try:
            uni, problems = await self.fetch_universe(self.universe)
        except Exception as e:                                        # noqa: BLE001
            uni, problems = None, [f"exception:{type(e).__name__}"]
        keep, degraded, action = U.refresh_decision(self.universe, uni if not problems else None, problems)
        if action == "accepted":
            self.universe_degraded = None
            self.persist_universe(uni, applied=False)
        else:
            self.universe_degraded = (problems or ["unknown"])[:5]
        self.lifecycle("universe_refresh", {"action": action, "degraded": degraded, "problems": problems[:20],
                                            "active_universe_id": (self.universe_meta or {}).get("universe_id")})
        return action

    def persist_universe(self, uni: dict, applied: bool) -> dict:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        uid = R.universe_id(stamp, uni["rule_version"])
        doc = {**uni, "universe_id": uid, "stamp": stamp, "evaluated_ms": now_ms(), "boot_id": self.boot_id,
               "config_hash": self.config_hash, "applied": applied, "trusted": True}
        path = os.path.join(self.base, "universe", f"universe-{stamp}-{self.boot_id[:8]}.json")
        tmp = path + ".partial"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, sort_keys=True)
            fh.flush(); os.fsync(fh.fileno())
        os.rename(tmp, path); os.chmod(path, 0o444)
        meta = {"universe_id": uid, "file": os.path.relpath(path, self.base), "sha256": sha256_file(path), "stamp": stamp,
                "applied": applied}
        self.emit("universe", R.make(type="universe", obs_id=uid, symbol=None, payload={**doc, "file": meta["file"],
                                                                                       "sha256": meta["sha256"]},
                                     boot_id=self.boot_id, endpoint="universe",
                                     transport="rest" if self.cfg["profile"] != "tier0_only" else "internal",
                                     recv_ts_ns=time.time_ns()))
        if applied:
            self.universe, self.universe_meta = doc, meta
            self.build_streams()
        return meta

    def _prior_universe(self):
        """Most recent trustworthy APPLIED universe in this data directory within the hysteresis window."""
        cutoff_ms, best = now_ms() - self.cfg["tier1_hysteresis_days"] * 86_400_000, None
        d = os.path.join(self.base, "universe")
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    u = json.load(fh)
            except (OSError, ValueError):
                continue
            if u.get("trusted") and u.get("applied") and u.get("rule_version") == U.RULE_VERSION \
                    and u.get("evaluated_ms", 0) >= cutoff_ms and (best is None or u["evaluated_ms"] > best["evaluated_ms"]):
                best = u
        return best

    # ---------- websocket callbacks ----------
    def on_message(self, conn, obj, recv_ns: int) -> None:
        if obj is None or not isinstance(obj, dict):
            self.stats["malformed"] += 1; return
        if "stream" not in obj:
            self.stats["unknown_event"] += 1; return                    # F41: counted separately, warned in health
        name, data = obj["stream"], obj.get("data")
        cname = self.stream_conn.get(name)
        if name == MARKET:
            if not isinstance(data, list):
                self.stats["malformed"] += 1; return
            r = recv_ns // 1_000_000
            if cname:
                self.activity[cname].data(r)
            if self.market is not None and self.market.on_array(recv_ns, data) == "first":
                self._stream_ready(self.market)
            return
        tr = self.tracks.get(name)
        if tr is None:
            self.stats["unknown_stream"] += 1; return
        if not isinstance(data, dict):
            self.stats["malformed"] += 1; return
        seq = data.get("u") if tr.kind == "book" else data.get("lastUpdateId")
        if not isinstance(seq, int):
            self.stats["malformed"] += 1; return
        self.activity[cname].data(recv_ns // 1_000_000)
        latest = tr.values.latest
        if latest is not None and recv_ns < latest[0]:
            self.stats["recv_clock_regression"] = self.stats.get("recv_clock_regression", 0) + 1
        res = tr.on_msg(recv_ns, data, seq)
        if res == "seq_regression":
            self.stats["rejected"]["seq_regression"] += 1           # older message (e.g. rotation overlap): ignore
        elif res == "seq_reset":
            self.stats["seq_reset"] = self.stats.get("seq_reset", 0) + 1
            self.lifecycle("seq_reset", {"stream": tr.name, "seq": seq})
        elif res == "first":
            self._stream_ready(tr)

    def _stream_ready(self, tr) -> None:
        self.lifecycle("stream_ready", {"stream": tr.name, "ready_ms": tr.ready_ms, "ready_ns": tr.ready_ns,
                                        "sub": tr.sub, "late": tr.never_ready_reported})
        if self.ready_ms is None and all(t.ready_ms is not None for t in self.all_tracks()):
            self.ready_ms = now_ms()
            self.lifecycle("all_streams_ready", {"ready_ms": self.ready_ms})

    def on_handler_error(self, conn, exc: BaseException) -> None:
        self.stats["handler_errors"] += 1
        self.handler_err_ms.append(now_ms())
        n = self.stats["handler_errors"]
        if n == 1 or n % 100 == 0:
            self.lifecycle("handler_exception", {"conn": getattr(conn, "name", None), "error": f"{type(exc).__name__}: {exc}"[:200],
                                                 "count": n})

    def on_sub_sent(self, conn, req_id: int, streams: list, sent_ms: int) -> None:
        for n in streams:
            t = self._track(n)
            if t is not None:
                t.sub, t.sub_sent_ms, t.ack_ms = "SENT", sent_ms, None
        self.lifecycle("subscribe_sent", {"conn": conn.name, "id": req_id, "streams": streams})

    def on_subscribe_result(self, conn, obj: dict) -> None:
        req = getattr(conn, "sub_requests", {}).get(obj.get("id"))
        streams = req["streams"] if req else [s for s in getattr(conn, "streams", [])]
        if req:
            req["resolved"] = True
        m = now_ms()
        if obj.get("error") is not None or "result" not in obj or obj.get("result") is not None:
            for n in streams:
                t = self._track(n)
                if t is not None:
                    t.sub = "FAILED"
            self.stats["subscribe_failed"] = self.stats.get("subscribe_failed", 0) + len(streams)
            self.lifecycle("subscribe_failed", {"conn": conn.name, "id": obj.get("id"), "error": obj.get("error"),
                                                "result": obj.get("result"), "streams": streams})
            return
        for n in streams:
            t = self._track(n)
            if t is not None and t.sub != "FAILED":
                t.sub, t.ack_ms = "ACKED", m
        self.lifecycle("subscribe_ack", {"conn": conn.name, "id": obj.get("id"), "streams": streams})

    def _track(self, name: str):
        return self.market if name == MARKET else self.tracks.get(name)

    def on_shutdown_event(self, conn, obj, recv_ns: int) -> None:
        dup = conn.name in self.rotating
        self.lifecycle("server_shutdown_event", {"conn": conn.name, "recv_ns": recv_ns, "already_rotating": dup})
        if not dup:                                                     # F6: rotation idempotent per connection
            self._spawn(self.rotate(conn, reason="serverShutdown"))

    def on_state(self, conn, state: str) -> None:
        m = now_ms()
        if state == "connected":
            self.activity[conn.name].transitions.append((m, True))
            if conn.streams:
                t = self._track(conn.streams[0])
                if t is not None:
                    t.sub, t.ack_ms = "URL", m                          # first stream subscribed via the URL
        elif state in ("disconnected", "connect_failed", "error"):
            self.activity[conn.name].transitions.append((m, False))
            for n in conn.streams:
                t = self._track(n)
                if t is not None and t.sub not in ("FAILED",):
                    t.sub = "PENDING"
        self.lifecycle(f"ws_{state}", {"conn": conn.name, "reconnects": getattr(conn, "reconnects", 0)})
        if self.state == "RUNNING" and self.ws_start_ms is not None:
            try:
                self.write_health()                    # connection transitions are reflected in health immediately
            except OSError:
                pass

    def on_ban(self) -> None:
        """F23: HTTP 418 => stop ALL Binance activity, including open WebSockets, until the ban ends."""
        self.ban_since_ms = now_ms()
        self.lifecycle("binance_ban_418", {"banned_until_mono": self.rate.banned_until})
        for c in self.conns:
            self._spawn(c.suspend())

    def _spawn(self, coro):
        try:
            t = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close(); return None
        self.aux_tasks.add(t); t.add_done_callback(self.aux_tasks.discard)
        return t

    def _conn_streams(self) -> list:
        book = sorted(n for n, t in self.tracks.items() if t.kind == "book")
        depth = sorted(n for n, t in self.tracks.items() if t.kind == "depth")
        return [("conn0-book", book + [MARKET]), ("conn1-depth", depth)]

    def _new_conn(self, name: str, streams: list) -> WSConnection:
        return WSConnection(name, streams, self.session, self.on_message, self.on_shutdown_event, self.on_state,
                            backoff=Backoff(), guard=self.rate, on_error=self.on_handler_error,
                            on_sub_sent=self.on_sub_sent, on_sub_result=self.on_subscribe_result)

    async def start_ws(self) -> None:
        self.ws_start_ms = now_ms()
        self.lifecycle("ws_start", {"ws_start_ms": self.ws_start_ms,
                                    "conns": {n: s for n, s in self._conn_streams()}})
        self.lifecycle("universe_active", {**(self.universe_meta or {}), "effective_from_ms": self.ws_start_ms,
                                           "tiers": {k: len(self.universe[k]) for k in ("tier0", "tier1", "tier2")}})
        for name, streams in self._conn_streams():
            if len(streams) > 300:
                raise RuntimeError("stream budget exceeded (<= 300 per connection)")
            c = self._new_conn(name, streams)
            self.conns.append(c)
            c.task = asyncio.create_task(c.run(), name=name)

    async def rotate(self, old: WSConnection, reason: str) -> dict:
        """Overlap rollover: open a replacement, wait for its first message, then close the old connection."""
        if old.name in self.rotating:
            return {"conn": old.name, "reason": reason, "skipped": "already_rotating"}
        self.rotating.add(old.name)
        try:
            t0 = now_ms()
            new = self._new_conn(old.name, old.streams)
            new.task = asyncio.create_task(new.run(), name=old.name + "-r")
            try:
                await asyncio.wait_for(new.first_msg.wait(), timeout=60)
                overlap_ok = True
            except asyncio.TimeoutError:
                overlap_ok = False
            t1 = now_ms()
            await old.close()
            if old in self.conns:
                self.conns[self.conns.index(old)] = new
            ev = {"conn": old.name, "reason": reason, "started_ms": t0, "new_first_msg_ms": t1, "overlap_ok": overlap_ok,
                  "old_last_msg_ms": (old.last_msg_ns or 0) // 1_000_000}
            self.rotation["events"].append(ev)
            self.lifecycle("ws_rotation", ev)
            return ev
        finally:
            self.rotating.discard(old.name)

    # ---------- sampling ----------
    def _conn_obj(self, name: str):
        for c in self.conns:
            if c.name == name:
                return c
        return None

    def conn_up_at(self, name: str, s: int) -> bool:
        up = self.activity[name].up_at(s) if name in self.activity else None
        if up is None:                                    # no recorded transition (synthetic test conns): current state
            c = self._conn_obj(name)
            return bool(c is not None and c.connected)
        return up

    def last_up(self, name: str, s: int):
        a = self.activity.get(name)
        return None if a is None else a.last_up_since(s)

    def data_live_at(self, name: str, s: int) -> bool:
        """Data message within the live window AND after the connection's most recent (re)connect (M3)."""
        a = self.activity.get(name)
        if a is None:
            return False
        lo = s - self.cfg["conn_data_live_ms"]
        up = a.last_up_since(s)
        if up is not None:
            lo = max(lo, up)
        return a.data_in(lo, s)

    def _deadline_abs(self, tr) -> int:
        return (self.ws_start_ms if self.ws_start_ms is not None else self.started_ms) + tr.deadline_rel_ms

    def _liveness_cause(self, tr, s: int):
        """None when the stream's OWN connection is up and data-live at s; otherwise the missing cause.
        A boundary processed > 2 s late is attributed to the sampler / event loop (m4)."""
        if self._lateness is not None and self._lateness > 2000:
            return "sampler_stall"
        if self.ban_since_ms is not None and s >= self.ban_since_ms and self.rate.banned():
            return "banned_418"
        if not self.conn_up_at(tr.conn, s):
            return "ws_disconnect_reconnect"
        if not self.data_live_at(tr.conn, s):
            return "conn_data_stale"
        if self.writer.stop_writes.is_set():
            return "disk_hard_stop"
        return None

    def _sample_track(self, tr: StreamTrack, s: int) -> None:
        val, why = tr.values.at_or_before(s)
        if why == NONE:                                       # nothing received at or before s yet
            if s >= self._deadline_abs(tr):
                tr.missing(s, "never_ready")                 # F38: never silent; startup before deadline is excused
            return
        cause = self._liveness_cause(tr, s)
        if cause is None:
            if val is None:
                cause = "sampler_stall"                       # EVICTED: PIT proof older than the hold window
            elif s - val[0] // 1_000_000 > tr.stale_ms:
                cause = "stale_stream"
            else:
                up = self.last_up(tr.conn, s)
                if up is not None and val[0] // 1_000_000 < up:
                    cause = "awaiting_post_reconnect_data"     # M3: value from before the reconnect is not live
        if cause is not None:
            tr.missing(s, cause)
            return
        recv_ns, data, seq = val
        unchanged = tr.last_persisted_seq == seq
        if tr.kind == "book":
            oid = R.book_id(tr.symbol, seq, tr.cadence, s)
            extra = None
        else:
            oid = R.depth_id(tr.levels, tr.symbol, seq, tr.cadence, s)
            extra = {"depth_levels": tr.levels}
        ok = self.emit(tr.kind, R.make(type=tr.kind, obs_id=oid, symbol=tr.symbol, payload=data, boot_id=self.boot_id,
                                       endpoint=tr.name, transport="ws", recv_ts_ns=recv_ns, exchange_seq=seq, tier=tr.tier,
                                       cadence_ms=tr.cadence, sample_ms=s, unchanged=unchanged,
                                       recoverability=IRREPLACEABLE, extra=extra), tier=tr.tier)
        if not ok:
            tr.missing(s, "backpressure_or_rejected")
            return
        self._persisted(tr, s, seq)

    def _persisted(self, tr, s: int, seq) -> None:
        g = tr.close_gap()
        if g is not None:
            self.gap_record(g, IRREPLACEABLE)
        tr.last_persisted_seq = seq
        tr.last_persisted_sample_ms = s
        if tr.first_sample_ms is None:
            tr.first_sample_ms = s

    def _sample_market(self, s: int) -> None:
        m = self.market
        comps, why = m.components_at(s)
        if why == NONE:
            if s >= self._deadline_abs(m):
                m.missing(s, "never_ready")
            return
        cause = self._liveness_cause(m, s)
        s_ns = s * 1_000_000
        if cause is None:
            if comps is None:
                cause = "sampler_stall"
            else:
                live = {k: v for k, v in comps.items() if v[0] <= s_ns and s - v[0] // 1_000_000 <= m.max_age_ms}
                new_exp = set(comps) - set(live) - self.expired_syms
                if new_exp:
                    self.expired_syms |= new_exp
                    self.stats["market_component_expired"] = len(self.expired_syms)
                newest = max((v[0] for v in live.values()), default=None)
                up = self.last_up(m.conn, s)
                if newest is None:
                    cause = "no_value"
                elif s - newest // 1_000_000 > m.stale_ms:
                    cause = "stale_stream"
                elif up is not None and newest // 1_000_000 < up:
                    cause = "awaiting_post_reconnect_data"
        if cause is not None:
            m.missing(s, cause)
            return
        items = sorted(live.items())
        last_ns = max(v[0] for _, v in items)
        ex = max((v[1].get("E") for _, v in items if isinstance(v[1].get("E"), int)), default=None)
        if ex is not None and ex > last_ns // 1_000_000 + R.FUTURE_TOLERANCE_MS:
            ex = None
        ok = self.emit("market", R.make(type="market", obs_id=R.market_id(s), symbol=None,
                                        payload=[v[1] for _, v in items], boot_id=self.boot_id, endpoint=MARKET,
                                        transport="ws", recv_ts_ns=last_ns, exchange_event_time_ms=ex, sample_ms=s,
                                        cadence_ms=m.cadence, recoverability=IRREPLACEABLE,
                                        extra={"component_recv_ms": {k: v[0] // 1_000_000 for k, v in items},
                                               "startup_complete": s - m.ready_ms >= self.cfg["market_startup_ms"]}))
        if not ok:
            m.missing(s, "backpressure_or_rejected")
            return
        self._persisted(m, s, None)

    def sample(self, sample_ms: int) -> None:
        """Process exactly one boundary for every stream whose cadence divides it."""
        for tr in self.tracks.values():
            if sample_ms % tr.cadence == 0:
                self._sample_track(tr, sample_ms)
        if self.market is not None and sample_ms % self.market.cadence == 0:
            self._sample_market(sample_ms)
        self.last_sampled_ms = sample_ms

    def sample_until(self, target_ms: int, live: bool = False) -> int:
        """F19: process EVERY boundary from the last processed one up to target (inclusive). Returns the count.
        live=True (sampler task / stop): a boundary processed > 2 s after it passed is attributed to the sampler."""
        start = target_ms if self.last_sampled_ms is None else self.last_sampled_ms + 1000
        n = 0
        for s in range(start, target_ms + 1, 1000):
            self._lateness = (now_ms() - s) if live else None
            try:
                self.sample(s)
            finally:
                self._lateness = None
            n += 1
        return n

    async def sampler_task(self) -> None:
        if self.last_sampled_ms is None:
            base = self.ws_start_ms if self.ws_start_ms is not None else now_ms()
            self.last_sampled_ms = (base // 1000) * 1000            # first processed boundary is > ws_start
        while not self.stop_event.is_set():
            self.beats["sampler"] = time.monotonic()
            m = now_ms()
            target = ((m - 1) // 1000) * 1000                       # newest boundary strictly before now
            if target > self.last_sampled_ms:
                behind = (target - self.last_sampled_ms) // 1000
                if behind > 1:
                    self.catchup_boundaries += behind - 1
                self.sample_until(target, live=True)
                self.loop_lag.append((m, m - target))
            for t, a, b, n in self.enq.closed_drop_intervals():
                if t not in ("book", "depth", "market"):             # sampled streams already get per-boundary gaps
                    self.simple_gap(f"backpressure|{t}", a, b, 0, "backpressure", RECOVERABLE, {"dropped": n})
            nxt = ((now_ms()) // 1000 + 1) * 1000
            await asyncio.sleep(max(0.0, (nxt + 2 - now_ms()) / 1000))

    # ---------- REST tasks ----------
    async def candle_job(self, sym: str, tf: str, open_ms: int, deadline_mono: float) -> None:
        try:
            await self._candle_job(sym, tf, open_ms, deadline_mono)
        except asyncio.CancelledError:
            self.simple_gap(f"candle|{tf}|{sym}", open_ms, open_ms, TF_MS[tf], "candle_fetch_interrupted_at_stop", RECOVERABLE)
            raise
        except Exception as e:                                       # noqa: BLE001 - never swallowed silently
            self.lifecycle("candle_exception", {"symbol": sym, "tf": tf, "open_ms": open_ms, "error": f"{type(e).__name__}: {e}"[:200]})
            self.simple_gap(f"candle|{tf}|{sym}", open_ms, open_ms, TF_MS[tf], "candle_exception", RECOVERABLE)

    async def _candle_job(self, sym: str, tf: str, open_ms: int, deadline_mono: float) -> None:
        params = {"symbol": sym, "interval": tf, "startTime": open_ms, "endTime": open_ms, "limit": 1}
        while True:
            if self.stop_event.is_set():
                self.simple_gap(f"candle|{tf}|{sym}", open_ms, open_ms, TF_MS[tf], "candle_fetch_interrupted_at_stop", RECOVERABLE)
                return
            status, data, recv_ns, *_ = await self.rest.get("/api/v3/klines", params)
            if status == 200:
                if not (isinstance(data, list) and len(data) == 1 and int(data[0][0]) == open_ms and int(data[0][6]) < recv_ns // 1_000_000):
                    self.stats["rejected"]["candle_unexpected"] += 1
                    self.simple_gap(f"candle|{tf}|{sym}", open_ms, open_ms, TF_MS[tf], "candle_unexpected_response", RECOVERABLE)
                    return
                k = data[0]
                self.emit("candle", R.make(type="candle", obs_id=R.candle_id(sym, tf, open_ms), symbol=sym, payload=k,
                                           boot_id=self.boot_id, endpoint=f"/api/v3/klines?interval={tf}", transport="rest",
                                           recv_ts_ns=recv_ns, exchange_event_time_ms=int(k[6]), cadence_ms=TF_MS[tf],
                                           available_at_ms=max(int(k[6]) + 1, recv_ns // 1_000_000),
                                           recoverability=RECOVERABLE))
                return
            transient = status in ("own_budget", "deferred_ip_weight", "rest_blocked", "paused_ip_weight", "circuit_open",
                                   "network_error", "malformed", 429) or (isinstance(status, int) and 500 <= status < 600)
            if transient and time.monotonic() < deadline_mono:
                await self._sleep(2 + random.random() * 3); continue
            if self.stop_event.is_set():
                return
            self.simple_gap(f"candle|{tf}|{sym}", open_ms, open_ms, TF_MS[tf], f"candle_fetch_failed:{status}", RECOVERABLE)
            return

    def _candle_symbols(self) -> list:
        u = self.universe
        return sorted(set(u["tier0"]) | set(u["tier1"]) | set(u["tier2"]))

    def _track_task(self, coro):
        t = asyncio.get_running_loop().create_task(coro)
        self.candle_tasks.add(t); t.add_done_callback(self.candle_tasks.discard)        # F7: tracked
        return t

    async def candle_round(self, boundary_ms: int, tfs: list) -> None:
        jobs = [(s, tf, boundary_ms - TF_MS[tf]) for tf in tfs for s in self._candle_symbols()]
        window = 300.0 if len(tfs) > 1 else 120.0
        deadline = time.monotonic() + window + 600
        tasks = []
        for i, (s, tf, o) in enumerate(jobs):
            try:
                await self._sleep(window / max(1, len(jobs)))
            except asyncio.CancelledError:
                self._candles_not_fetched(jobs[i:]); raise
            if self.stop_event.is_set():
                self._candles_not_fetched(jobs[i:]); break
            tasks.append(self._track_task(self.candle_job(s, tf, o, deadline)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _candles_not_fetched(self, jobs) -> None:
        for s, tf, o in jobs:
            self.simple_gap(f"candle|{tf}|{s}", o, o, TF_MS[tf], "candle_not_fetched_at_stop", RECOVERABLE)

    async def candle_round_jobs(self, jobs: list, window: float) -> None:
        deadline = time.monotonic() + window + 600
        tasks = []
        for i, (s, tf, o) in enumerate(jobs):
            try:
                await self._sleep(window / max(1, len(jobs)))
            except asyncio.CancelledError:
                self._candles_not_fetched(jobs[i:]); raise
            if self.stop_event.is_set():
                self._candles_not_fetched(jobs[i:]); break
            tasks.append(self._track_task(self.candle_job(s, tf, o, deadline)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def candle_task(self) -> None:
        self.beats["candles"] = time.monotonic()
        m0 = now_ms()                                               # catch-up: last closed candle of every TF,
        jobs = [(s, tf, (m0 // TF_MS[tf]) * TF_MS[tf] - TF_MS[tf])    # one budget-spread round (300 s)
                for tf in self.cfg["candle_timeframes"] for s in self._candle_symbols()]
        self._track_task(self.candle_round_jobs(jobs, 300.0))
        while not self.stop_event.is_set():
            self.beats["candles"] = time.monotonic()
            nxt = (now_ms() // TF_MS["15m"] + 1) * TF_MS["15m"]
            await self._sleep_until(nxt + 5_000 + int(random.random() * 10_000))
            self.beats["candles"] = time.monotonic()
            if self.stop_event.is_set():
                break
            tfs = [tf for tf in self.cfg["candle_timeframes"] if nxt % TF_MS[tf] == 0]
            self._track_task(self.candle_round(nxt, tfs))

    async def clock_task(self) -> None:
        while not self.stop_event.is_set():
            self.beats["clock"] = time.monotonic()
            probes, raw = [], []
            for i in range(self.cfg["clock_probes"]):
                status, data, recv_ns, t0, t1 = await self.rest.get("/api/v3/time", urgent=True)
                if status == 200 and isinstance(data, dict) and isinstance(data.get("serverTime"), int):
                    probes.append((data["serverTime"], t0, t1)); raw.append((data["serverTime"], t0, t1, recv_ns))
                if i + 1 < self.cfg["clock_probes"]:
                    await self._sleep(1.0)
            if probes:
                st = self.clock.update_samples(probes)
                best = min(raw, key=lambda p: (p[2] - p[1], p[1]))
                self.emit("clock", R.make(type="clock", obs_id=R.clock_id(best[0]), symbol=None,
                                          payload={"method": C.CLOCK_METHOD, "serverTime": best[0], "t0_ms": best[1],
                                                   "t1_ms": best[2], "rtt_ms": best[2] - best[1],
                                                   "skew_ms": self.clock.last_skew_ms,
                                                   "uncertainty_ms": self.clock.uncertainty_ms, "state": st,
                                                   "probes": [{"serverTime": s, "t0_ms": a, "t1_ms": b} for s, a, b, _ in raw],
                                                   "probes_requested": self.cfg["clock_probes"]},
                                          boot_id=self.boot_id, endpoint="/api/v3/time", transport="rest", recv_ts_ns=best[3],
                                          exchange_event_time_ms=best[0]))
            else:
                self.stats["clock_probe_failures"] = self.stats.get("clock_probe_failures", 0) + 1
                self.lifecycle("clock_round_failed", {"probes": self.cfg["clock_probes"]})
                await self._sleep(30)                                 # retry soon; never wait a full period blind
                continue
            await self._sleep(self.cfg["cadence_ms"]["clock"] / 1000)

    async def disk_task(self) -> None:
        while not self.stop_event.is_set():
            self.beats["disk"] = time.monotonic()
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
            if st == "HARD_STOP" and not self.writer.stop_writes.is_set():
                self.disk_hard_stop()
            await self._sleep(60)

    def disk_hard_stop(self) -> None:
        """R03: observations refused (sticky); control records still written; durable evidence OUTSIDE the
        segment writer path: a tiny fsynced marker file plus a stderr line (container log)."""
        self.writer.stop_writes.set()
        m = now_ms()
        info = {"event": "disk_hard_stop", "boot_id": self.boot_id, "ts_ms": m, "free_gb": self.disk_free_gb,
                "collector_dir_gb": self.dir_gb, "thresholds": {"stop_free_gb": self.cfg["disk_stop_free_gb"],
                                                                "dir_stop_gb": self.cfg["dir_stop_gb"]}}
        self.disk_marker = self.write_marker(f"disk_stop-{self.boot_id[:8]}-{m}.json", info)
        print(json.dumps({"p2f_alert": info}), file=sys.stderr, flush=True)
        self.lifecycle("disk_hard_stop", {**info, "marker": self.disk_marker})

    def write_marker(self, name: str, info: dict):
        d = os.path.join(self.base, "control")
        try:
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, name)
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(info, fh, sort_keys=True, default=str); fh.flush(); os.fsync(fh.fileno())
            os.chmod(p, 0o444)
            return os.path.relpath(p, self.base)
        except OSError as e:
            print(json.dumps({"p2f_alert": {"marker_write_failed": name, "error": type(e).__name__}}), file=sys.stderr, flush=True)
            return None

    # ---------- supervision ----------
    async def supervise(self, name: str, fn) -> None:
        """F21 / F48: an unexpected exit or exception becomes a lifecycle `task_failed`, a health reason and a
        restart with backoff. More than 5 failures in 10 min => FAILED, collector stops with a non-zero exit."""
        delay = self.task_restart_delay_s
        while not self.stop_event.is_set():
            try:
                await fn()
                if self.stop_event.is_set():
                    return
                err = "exited_unexpectedly"
            except asyncio.CancelledError:
                raise
            except Exception as e:                                   # noqa: BLE001
                err = f"{type(e).__name__}: {e}"[:200]
            fails = self.task_failures[name]
            fails.append(time.monotonic())
            while fails and time.monotonic() - fails[0] > 600:
                fails.popleft()
            self.task_fail_ms.append(now_ms())
            self.stats["task_failed_total"] = self.stats.get("task_failed_total", 0) + 1
            self.lifecycle("task_failed", {"task": name, "error": err, "failures_10min": len(fails)})
            if len(fails) > 5:
                self.fatal(f"task_failed_repeatedly:{name}", EXIT_TASK)
                return
            await self._sleep(delay); delay = min(60.0, delay * 2)
            self.beats.pop(name, None)

    def fatal(self, reason: str, code: int) -> None:
        if self.stop_reason is None:
            self.stop_reason = reason
            self.exit_code = code
            self.state = "FAILED"
            self.write_marker(f"fatal-{self.boot_id[:8]}-{now_ms()}.json",
                              {"event": "fatal", "reason": reason, "boot_id": self.boot_id, "ts_ms": now_ms(),
                               "writer": self.writer.status()})
            print(json.dumps({"p2f_alert": {"fatal": reason, "boot_id": self.boot_id}}), file=sys.stderr, flush=True)
            self.lifecycle("fatal", {"reason": reason})
        self.stop_event.set()

    async def watchdog_task(self) -> None:
        """1 s checks: writer liveness (F43), SUBSCRIBE ack deadlines (F37), first-observation deadlines (F38),
        dead connection tasks, handler-error bursts (F20)."""
        while not self.stop_event.is_set():
            self.beats["watchdog"] = time.monotonic()
            self.watchdog_once()
            await self._sleep(1.0)

    def watchdog_once(self) -> None:
        m = now_ms()
        self._check_reconnect_recovered()
        off = time.time() - time.monotonic()                        # m3: wall-clock step detection
        if abs(off - self.wall_offset) > 1.0:
            self.wall_step_ms.append(m)
            self.stats["wall_clock_steps"] = self.stats.get("wall_clock_steps", 0) + 1
            self.lifecycle("wall_clock_step", {"delta_ms": round((off - self.wall_offset) * 1000, 1)})
        self.wall_offset = off
        live_ms = self.cfg["conn_data_live_ms"] + 5000                 # M2: data stall => forced reconnect
        for c in list(self.conns):
            a = self.activity.get(c.name)
            up = a.last_up_since(m) if a else None
            if getattr(c, "connected", False) and up is not None and m - up > live_ms and c.name not in self.rotating \
                    and (a.last_data_ms is None or m - a.last_data_ms > live_ms) \
                    and m - self.data_stall_forced.get(c.name, 0) > 30_000:
                self.data_stall_forced[c.name] = m
                self.stats["data_stall_reconnects"] = self.stats.get("data_stall_reconnects", 0) + 1
                self.lifecycle("data_stall_reconnect", {"conn": c.name, "last_data_ms": a.last_data_ms})
                self._spawn(c.force_reconnect("data_stall"))
        if self.writer.ident is not None and not self.writer.is_alive() and not self.writer.finished:
            self.fatal("writer_thread_dead", EXIT_WRITER)
            return
        tmo = self.cfg["subscribe_ack_timeout_s"] * 1000
        for c in list(self.conns):
            for rid, req in list(getattr(c, "sub_requests", {}).items()):
                if not req.get("resolved") and m - req["sent_ms"] > tmo:
                    req["resolved"] = True
                    for n in req["streams"]:
                        t = self._track(n)
                        if t is not None and t.sub == "SENT":
                            t.sub = "TIMEOUT"
                    self.stats["subscribe_timeout"] = self.stats.get("subscribe_timeout", 0) + len(req["streams"])
                    self.lifecycle("subscribe_timeout", {"conn": c.name, "id": rid, "streams": req["streams"]})
                    self._spawn(c.force_reconnect("subscribe_timeout"))
            task = getattr(c, "task", None)
            if task is not None and task.done() and not getattr(c, "_closing", False) and not self.stop_event.is_set() \
                    and c.name not in self.rotating:
                err = None if task.cancelled() else task.exception()
                self.lifecycle("ws_task_dead", {"conn": c.name, "error": repr(err)[:200]})
                new = self._new_conn(c.name, c.streams)
                new.task = asyncio.create_task(new.run(), name=c.name + "-restart")
                self.conns[self.conns.index(c)] = new
        for t in self.all_tracks():
            if t.ready_ms is None and not t.never_ready_reported and m >= self._deadline_abs(t):
                t.never_ready_reported = True
                self.stats["never_ready"] = self.stats.get("never_ready", 0) + 1
                self.lifecycle("never_ready", {"stream": t.name, "deadline_ms": self._deadline_abs(t), "sub": t.sub})
        recent = [x for x in self.handler_err_ms if m - x <= 60_000]
        if len(recent) >= 50:
            self.handler_err_ms.clear()
            for c in self.conns:
                self._spawn(c.force_reconnect("handler_error_burst"))

    # ---------- health ----------
    def health_eval(self) -> tuple:
        """Explicit HEALTHY invariant (F54). Returns (state, hard_reasons, startup_reasons, warnings)."""
        m, mono = now_ms(), time.monotonic()
        hard, startup, warn = [], [], []
        if self.state in ("STOPPING", "STOPPED", "STOPPED_INCOMPLETE", "FAILED"):
            return self.state, [], [], []
        if self.state == "STARTING" or self.ws_start_ms is None:
            return "STARTING", [], ["not_started"], []
        up_s = mono - self.started_mono
        for name, period in TASK_PERIOD_S.items():                 # 1. required tasks alive + beating
            b = self.beats.get(name)
            limit = max(2 * period, 3.0) + (30.0 if name in ("candles", "clock") else 0.0)
            if b is None:
                (startup if up_s < 30 else hard).append(f"task_no_beat:{name}")
            elif mono - b > limit:
                hard.append(f"task_stale:{name}")
        ws = self.writer.status()
        if not ws["alive"] or ws["fatal"]:
            hard.append("writer_dead")
        elif ws["beat_age_ms"] is None or ws["beat_age_ms"] > 5000:
            hard.append("writer_stale")
        if ws["durable_lag_ms"] > 10_000:
            hard.append("writer_not_durable")
        if self.stats["write_errors"]:
            hard.append("write_errors")
        if sum(self.stats["writer_rejected"].values()):
            hard.append("writer_rejected_records")
        expected = {t.name for t in self.all_tracks()}              # 2./3. streams
        acked = {t.name for t in self.all_tracks() if t.sub in ("ACKED", "URL")}
        observing = set()
        for t in self.all_tracks():
            st = t.state()
            last = t.last_recv_ms()
            if st == FAILED:
                hard.append(f"stream_failed:{t.name}:{t.sub}")
                continue
            if t.ready_ms is None:
                (startup if m < self._deadline_abs(t) else hard).append(f"not_ready:{t.name}")
                continue
            age = None if last is None else m - last
            if t.kind == "book" and t.tier != 0:
                if age is not None and age > self.cfg["book_stale_suspect_ms"]:
                    warn.append(f"stale_suspect:{t.name}")
                fresh = True
            else:
                fresh = age is not None and age <= t.stale_ms
            live = self.conn_up_at(t.conn, m) and self.data_live_at(t.conn, m)
            gap_old = t.gap is not None and (t.gap["last"] - t.gap["first"] + t.cadence) > 3 * t.cadence
            if not fresh:
                hard.append(f"stale:{t.name}")
            if not live:
                hard.append(f"conn_not_data_live:{t.conn}")
            if t.gap is not None:                                    # NB1: an open gap is always named, with its cause
                hard.append(f"{'gap_open' if gap_old else 'gap_short'}:{t.name}:{t.gap['cause']}")
            if fresh and live and t.gap is None:
                observing.add(t.name)
        if not (expected == acked):
            missing_ack = sorted(expected - acked)
            (startup if m < self.ws_start_ms + 1000 * self.cfg["subscribe_ack_timeout_s"] else hard).append(
                f"not_acked:{','.join(missing_ack[:10])}")
        if expected != observing and not any(r.startswith(("stale:", "gap_open:", "gap_short:", "conn_not", "stream_failed",
                                                            "not_ready")) for r in hard + startup):
            hard.append("expected_ne_observing")
        if self.disk_state == "HARD_STOP" or self.writer.stop_writes.is_set():  # 4.
            hard.append("disk_hard_stop")
        if self.rate.banned():
            hard.append("banned_418")
        age_c = self.clock.age_s()
        if age_c is None:
            (startup if up_s < 60 else hard).append("clock_unknown")
        elif age_c > 2 * self.cfg["cadence_ms"]["clock"] / 1000:
            hard.append("clock_stale")
        elif self.clock.state != "OK":
            hard.append(f"clock_{self.clock.state.lower()}")
        if [x for x in self.handler_err_ms if m - x <= 600_000]:
            hard.append("handler_exceptions_10min")
        if [x for x in self.task_fail_ms if m - x <= 600_000]:
            hard.append("task_failed_10min")                          # M5
        if [x for x in self.wall_step_ms if m - x <= 600_000]:
            hard.append("wall_clock_step_10min")
        if self.stats.get("seq_reset"):
            hard.append("seq_reset")
        if self.stats["segments_quarantined"]:
            hard.append("segments_quarantined")
        if sum(self.stats["emit_failed"].values()):
            hard.append("emit_failed")
        if self.universe_degraded:
            hard.append("universe_refresh_failed")                  # F42: previous universe kept, DEGRADED
        if self.enq.drop_open:
            hard.append("queue_drops")
        for k in ("malformed", "unknown_stream", "unknown_event"):
            if self.stats[k]:
                warn.append(f"{k}:{self.stats[k]}")
        if self.stats.get("recv_clock_regression"):
            warn.append(f"recv_clock_regression:{self.stats['recv_clock_regression']}")
        if self.stats["rejected"].get("seq_regression"):
            warn.append(f"seq_regression:{self.stats['rejected']['seq_regression']}")
        if self.stats.get("subscribe_failed") or self.stats.get("subscribe_timeout"):
            warn.append("subscription_errors_seen")
        if self.disk_state == "HARD_STOP" or self.writer.stop_writes.is_set():
            state = "DEGRADED_DISK"
        elif self.rate.banned():
            state = "BANNED_418"
        elif hard:
            state = "DEGRADED"
        elif startup:
            state = "STARTING"
        else:
            state = "HEALTHY"
        return state, hard, startup, warn

    def health(self) -> dict:
        m = now_ms()
        state, hard, startup, warn = self.health_eval()
        lags = [lag for t, lag in self.loop_lag if m - t <= 60_000]
        return {
            "ts_ms": m, "version": C.VERSION, "schema_version": C.SCHEMA_VERSION, "boot_id": self.boot_id, "state": state,
            "reasons": hard, "startup_reasons": startup, "warnings": warn, "profile": self.cfg["profile"],
            "config_hash": self.config_hash, "run_record_sha256": self.run_record_sha,
            "uptime_s": round(time.monotonic() - self.started_mono, 1),
            "ws": [{"conn": c.name, "connected": bool(getattr(c, "connected", False)), "streams": len(c.streams),
                    "reconnects": getattr(c, "reconnects", 0),
                    "last_msg_age_ms": (m - c.last_msg_ns // 1_000_000) if getattr(c, "last_msg_ns", None) else None,
                    "data_live": self.data_live_at(c.name, m), "msgs_per_s": self.activity[c.name].rate(m)}
                   for c in self.conns],
            "streams": {t.name: {"state": t.state(), "sub": t.sub, "ready_ms": t.ready_ms,
                                 "last_msg_age_ms": None if t.last_recv_ms() is None else m - t.last_recv_ms(),
                                 "gap_open": None if t.gap is None else {"first": t.gap["first"], "n": t.gap["n"],
                                                                         "cause": t.gap["cause"]}}
                        for t in self.all_tracks()},
            "tasks": {k: round(time.monotonic() - v, 1) for k, v in sorted(self.beats.items())},
            "task_failures": {k: len(v) for k, v in self.task_failures.items()},
            "writer": self.writer.status(),
            "queue_depth": self.q.qsize(), "queue_peak": self.enq.peak,
            "loop_lag_ms": {"last": lags[-1] if lags else None, "max_60s": max(lags) if lags else None},
            "catchup_boundaries": self.catchup_boundaries, "last_sampled_ms": self.last_sampled_ms,
            "dropped": dict(self.stats["dropped"]), "written": dict(self.stats["written"]),
            "duplicates_dropped": self.stats["duplicates_dropped"], "rejected": dict(self.stats["rejected"]),
            "malformed": self.stats["malformed"], "unknown_stream": self.stats["unknown_stream"],
            "unknown_event": self.stats["unknown_event"], "handler_errors": self.stats["handler_errors"],
            "write_errors": self.stats["write_errors"], "counters": self.counters(),
            "segments": {"open": sorted(self.writer.segments), "promoted": self.stats["segments_promoted"],
                         "quarantined": self.stats["segments_quarantined"]},
            "gaps_open": sum(1 for t in self.all_tracks() if t.gap is not None), "gaps_closed_total": self.gap_count,
            "universe": {k: len(self.universe[k]) for k in ("tier0", "tier1", "tier2")} if self.universe else None,
            "rest": {"own_weight_1m": self.rate.own_used(), "budget": self.cfg["rest_budget_weight_per_min"],
                     "ip_used_weight_1m_seen": self.rate.observed, "events": dict(self.rate.events),
                     "total_weight": self.rest.weight_used_total if self.rest else 0},
            "clock": {"state": self.clock.state, "skew_ms": self.clock.last_skew_ms,
                      "uncertainty_ms": self.clock.uncertainty_ms, "age_s": self.clock.age_s(), "method": C.CLOCK_METHOD},
            "disk": {"state": self.disk_state, "free_gb": self.disk_free_gb, "collector_dir_gb": self.dir_gb,
                     "marker": self.disk_marker},
            "rotation": self.rotation,
        }

    def counters(self) -> dict:
        st = self.stats
        return {"dropped": dict(st["dropped"]), "malformed": st["malformed"], "unknown_stream": st["unknown_stream"],
                "unknown_event": st["unknown_event"], "handler_errors": st["handler_errors"],
                "seq_regression": st["rejected"].get("seq_regression", 0), "seq_reset": st.get("seq_reset", 0),
                "rejected": dict(st["rejected"]), "emit_failed": dict(st["emit_failed"]),
                "writer_rejected": dict(st["writer_rejected"]), "write_errors": st["write_errors"],
                "segments_quarantined": st["segments_quarantined"], "duplicates_dropped": st["duplicates_dropped"],
                "recv_clock_regression": st.get("recv_clock_regression", 0), "wall_clock_steps": st.get("wall_clock_steps", 0),
                "task_failures": st.get("task_failed_total", 0),
                "data_stall_reconnects": st.get("data_stall_reconnects", 0),
                "subscribe_failed": st.get("subscribe_failed", 0), "subscribe_timeout": st.get("subscribe_timeout", 0),
                "never_ready": st.get("never_ready", 0), "clock_probe_failures": st.get("clock_probe_failures", 0),
                "market_component_expired": st.get("market_component_expired", 0), "gaps": self.gap_count,
                "catchup_boundaries": self.catchup_boundaries}

    def health_record(self, h: dict) -> None:
        """R02: compact historical health raw record (state at time T is reconstructable from raw data)."""
        compact = {k: h[k] for k in ("state", "reasons", "startup_reasons", "warnings", "uptime_s", "tasks", "task_failures",
                                     "queue_depth", "queue_peak", "loop_lag_ms", "catchup_boundaries", "last_sampled_ms",
                                     "dropped", "rejected", "malformed", "unknown_stream", "unknown_event",
                                     "handler_errors", "write_errors", "gaps_open", "gaps_closed_total", "clock", "disk")}
        compact["writer"] = {k: h["writer"][k] for k in ("alive", "beat_age_ms", "durable_lag_ms", "write_errors", "fatal")}
        compact["ws"] = [{k: c[k] for k in ("conn", "connected", "reconnects", "data_live", "msgs_per_s")} for c in h["ws"]]
        by_state = collections.Counter(s["state"] for s in h["streams"].values())
        compact["streams_by_state"] = dict(by_state)
        compact["streams_not_observing"] = {n: s for n, s in sorted(h["streams"].items()) if s["state"] != OBSERVING}
        compact["health_ts_ms"] = h["ts_ms"]
        compact["counters"] = h["counters"]
        compact["rest"] = h["rest"]
        compact["universe_id"] = (self.universe_meta or {}).get("universe_id")
        self.emit("health", R.make(type="health", obs_id=R.health_id(self.boot_id, self._seq()), symbol=None,
                                   payload=compact, boot_id=self.boot_id, endpoint="collector", transport="internal",
                                   recv_ts_ns=time.time_ns()))
        self.health_record_last_mono = time.monotonic()

    def write_health(self, record: bool | None = None) -> dict:
        h = self.health()
        d = os.path.join(self.base, "health"); os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "collector_health.json"); tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(h, fh, sort_keys=True, default=str)
        os.replace(tmp, p)
        due = (self.health_record_last_mono is None or
               time.monotonic() - self.health_record_last_mono >= self.cfg["health_record_interval_s"])
        if record or (record is None and (due or h["state"] != self.health_state_last)):
            self.health_record(h)
        self.health_state_last = h["state"]
        return h

    async def health_task(self) -> None:
        while not self.stop_event.is_set():
            self.beats["health"] = time.monotonic()
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

    async def reconnect_test_task(self) -> None:
        """G3: exactly ONE predeclared controlled reconnect of `reconnect_test_conn` at ws_start + reconnect_test_at_s.
        Triggered internally (no external action on the running collector): the socket is closed, the normal
        reconnect path (backoff, re-subscribe, acks, post-reconnect freshness) must recover."""
        at = self.cfg["reconnect_test_at_s"]
        if at <= 0:
            return
        await self._sleep_until(self.ws_start_ms + int(at * 1000))
        if self.stop_event.is_set():
            return
        c = self._conn_obj(self.cfg["reconnect_test_conn"])
        if c is None:
            self.lifecycle("controlled_reconnect_test", {"conn": self.cfg["reconnect_test_conn"], "error": "conn_missing"})
            return
        m = now_ms()
        self.reconnect_test = {"conn": c.name, "trigger_ms": m, "recovered_ms": None}
        self.lifecycle("controlled_reconnect_test", {"conn": c.name, "trigger_ms": m, "planned_at_s": at,
                                                     "planned_ms": self.ws_start_ms + int(at * 1000)})
        await c.force_reconnect("controlled_reconnect_test")

    def _check_reconnect_recovered(self) -> None:
        rt = self.reconnect_test
        if rt is None or rt["recovered_ms"] is not None:
            return
        a = self.activity.get(rt["conn"])
        up = a.last_up_since(now_ms()) if a else None
        if up is None or up <= rt["trigger_ms"]:
            return
        trs = [t for t in self.all_tracks() if t.conn == rt["conn"]]
        if all(t.gap is None and t.last_persisted_sample_ms is not None and t.last_persisted_sample_ms >= up
               and (t.last_recv_ms() or 0) >= up for t in trs):
            rt["recovered_ms"] = now_ms()
            self.lifecycle("controlled_reconnect_recovered", {"conn": rt["conn"], "trigger_ms": rt["trigger_ms"],
                                                              "reconnected_ms": up, "recovered_ms": rt["recovered_ms"],
                                                              "streams": len(trs)})

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
            loop.add_signal_handler(sig, self._signal_stop)
        rec_gaps = recover_partials(self.base, self.boot_id, self.stats)
        self.writer.start()
        timeout = aiohttp.ClientTimeout(total=30)
        sess = self.session_factory() if self.session_factory else \
            aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "tsb-p2-forward/" + C.VERSION})
        async with sess as self.session:
            self.rest = RestClient(self.session, self.rate, self.stats)
            if not await self.establish_universe():                  # F25: fail closed, graceful stop
                return await self._startup_failed(rec_gaps)
            self.run_record, rel, self.run_record_sha = P.write_run_record(self)
            self.writer.run_record = rel
            self.lifecycle("start", {"config_hash": self.config_hash, "profile": self.cfg["profile"],
                                     "max_runtime_s": self.cfg["max_runtime_s"], "recovered": rec_gaps,
                                     "run_record_file": rel, "run_record_sha256": self.run_record_sha,
                                     "run_record": self.run_record})
            for g in rec_gaps:
                a = (g["last_salvaged_recv_ns"] or 0) // 1_000_000
                self.simple_gap(f"crash|{g['type']}", a, self.started_ms, 0, "crash_recovery", IRREPLACEABLE,
                                {"salvaged": g["salvaged"], "source": g["source"]})
            self.state = "RUNNING"
            await self.start_ws()
            tasks = [asyncio.create_task(self.supervise(n, f), name=n) for n, f in
                     (("sampler", self.sampler_task), ("candles", self.candle_task), ("clock", self.clock_task),
                      ("disk", self.disk_task), ("health", self.health_task), ("watchdog", self.watchdog_task))]
            tasks.append(asyncio.create_task(self.rotation_test_task(), name="rotation_test"))
            tasks.append(asyncio.create_task(self.reconnect_test_task(), name="reconnect_test"))
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.cfg["max_runtime_s"])
            except asyncio.TimeoutError:
                pass
            if self.stop_reason is None:
                self.stop_reason = "max_runtime"
            stop_requested_ms = now_ms()
            self.stop_event.set()
            if self.state != "FAILED":
                self.state = "STOPPING"
            self.write_health(record=True)                            # m2: health history reaches the stop
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for t in list(self.candle_tasks) + list(self.aux_tasks):
                t.cancel()
            await asyncio.gather(*self.candle_tasks, *self.aux_tasks, return_exceptions=True)
            final = ((stop_requested_ms - 1) // 1000) * 1000          # every boundary strictly before the stop
            if self.last_sampled_ms is not None and final > self.last_sampled_ms:
                self.sample_until(final, live=True)
            for c in self.conns:
                await c.close()
            await asyncio.gather(*[c.task for c in self.conns if getattr(c, "task", None)], return_exceptions=True)
        for tr in self.all_tracks():
            g = tr.close_gap(open_at_stop=True)
            if g is not None:
                self.gap_record(g, IRREPLACEABLE)
        for t, a, b, n in self.enq.closed_drop_intervals(force=True):
            if t not in ("book", "depth", "market"):
                self.simple_gap(f"backpressure|{t}", a, b, 0, "backpressure", RECOVERABLE, {"dropped": n})
        self.write_health(record=True)
        self.lifecycle("stop", {"reason": self.stop_reason, "stop_requested_ms": stop_requested_ms,
                                "last_boundary_ms": self.last_sampled_ms, "ws_start_ms": self.ws_start_ms,
                                "uptime_s": round(time.monotonic() - self.started_mono, 1),
                                "counters": self.counters()})
        self.writer.stop(); self.writer.join(timeout=self.writer_join_timeout_s)
        self.finalize_stop()
        self.write_health(record=False)
        partials = [f for _, _, fs in os.walk(os.path.join(self.base, "raw")) for f in fs if f.endswith(".partial")]
        self.write_marker(f"stop-{self.boot_id[:8]}.json",                        # N1: final state outside the writer
                          {"event": "final_stop_state", "boot_id": self.boot_id, "ts_ms": now_ms(), "state": self.state,
                           "exit_code": self.exit_code, "reason": self.stop_reason,
                           "writer_finished": self.writer.finished, "writer_alive": self.writer.is_alive(),
                           "partials": len(partials), "counters": self.counters()})
        return self.exit_code

    writer_join_timeout_s = 120

    async def _startup_failed(self, rec_gaps) -> int:
        """F25: no trustworthy initial universe => durable reason, FAILED, graceful writer stop, exit 5."""
        self.run_record, rel, self.run_record_sha = P.write_run_record(self)
        self.writer.run_record = rel
        self.lifecycle("start", {"config_hash": self.config_hash, "profile": self.cfg["profile"],
                                 "max_runtime_s": self.cfg["max_runtime_s"], "recovered": rec_gaps,
                                 "run_record_file": rel, "run_record_sha256": self.run_record_sha,
                                 "run_record": self.run_record, "startup_failed": True})
        self.lifecycle("startup_failed", {"reason": "universe_unavailable", "problems": self.startup_failure[:20]})
        self.fatal("startup_failed:universe_unavailable", EXIT_STARTUP)
        self.write_health(record=True)
        self.lifecycle("stop", {"reason": self.stop_reason, "stop_requested_ms": now_ms(), "last_boundary_ms": None,
                                "ws_start_ms": None, "uptime_s": round(time.monotonic() - self.started_mono, 1),
                                "counters": self.counters()})
        self.writer.stop(); self.writer.join(timeout=self.writer_join_timeout_s)
        self.finalize_stop()
        self.write_health(record=False)
        self.write_marker(f"stop-{self.boot_id[:8]}.json",
                          {"event": "final_stop_state", "boot_id": self.boot_id, "ts_ms": now_ms(), "state": self.state,
                           "exit_code": self.exit_code, "reason": self.stop_reason, "writer_finished": self.writer.finished,
                           "writer_alive": self.writer.is_alive(), "partials": 0, "counters": self.counters()})
        return self.exit_code

    def finalize_stop(self) -> str:
        """F51: STOPPED only if the writer thread finished cleanly and no .partial remains; else STOPPED_INCOMPLETE."""
        partials = [f for _, _, fs in os.walk(os.path.join(self.base, "raw")) for f in fs if f.endswith(".partial")]
        complete = (not self.writer.is_alive()) and self.writer.finished and not partials
        if self.state != "FAILED":
            self.state = "STOPPED" if complete else "STOPPED_INCOMPLETE"
            if not complete:
                self.exit_code = EXIT_INCOMPLETE
        if not complete:
            print(json.dumps({"p2f_alert": {"stop_incomplete": True, "partials": partials[:20],
                                            "writer_alive": self.writer.is_alive()}}), file=sys.stderr, flush=True)
        return self.state

    def _signal_stop(self) -> None:
        if self.stop_reason is None:
            self.stop_reason = "signal"
        self.stop_event.set()


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
