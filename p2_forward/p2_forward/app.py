"""Forward market-intelligence collector (P2-E1): orchestration, sampling, gaps, backpressure, health.

One asyncio process; supervised tasks; a dedicated writer thread. Zero trading authority.
Modes (P2-CR): `bounded` (validation gates; unchanged P2-E1 behaviour, stops at max_runtime_s) and `continuous`
(explicit; no runtime limit; one logical dataset across runs; daily universe refresh / proactive rotation / day
checkpoints / day close; persistent incidents; fail-closed stops). See docs/p2/CONTINUOUS_OPERATIONS.md.
Entry point: `python -m p2_forward` (config path in env P2F_CONFIG, default /config/collector.json).

G2-Repeat revision: exact PIT sampling for any burst size (tracks.Held), every boundary processed after a stall,
explicit stream state machine with subscription acks and first-observation deadlines, data-liveness (not socket
liveness), supervised tasks, writer liveness, 418 closes all WebSockets, collision-free control-record ids,
explicit HEALTHY invariant, historical health records, disk-stop evidence and run provenance.
"""
from __future__ import annotations

import asyncio
import collections
import gc
import datetime as dt
import gzip
import hashlib
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

from . import cal
from . import config as C
from . import provenance as P
from . import record as R
from . import universe as U
from .guards import Backoff, ClockGuard, DiskGuard, RateGuard
from .incidents import IncidentLog
from .procwatch import ProcWatch
from .tracks import FAILED, NONE, OBSERVING, MarketTrack, StreamTrack
from .transport import RestClient, WSConnection
from .writer import (SegmentWriter, check_closed_days, close_day, dataset_bytes, new_stats, open_days,
                     recover_partials, sha256_file)

TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
IRREPLACEABLE = "IRREPLACEABLE_FORWARD_OBSERVATION"
RECOVERABLE = "RECOVERABLE_WHERE_ARCHIVE_AVAILABLE"
MARKET = "!miniTicker@arr"
EXIT_OK, EXIT_INCOMPLETE, EXIT_WRITER, EXIT_TASK, EXIT_STARTUP, EXIT_FAILCLOSED = 0, 2, 3, 4, 5, 6
TASK_PERIOD_S = {"sampler": 1.0, "candles": 900.0, "clock": 600.0, "disk": 60.0, "health": 10.0, "watchdog": 1.0,
                 "loopmon": 0.1}


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class StartupRefused(Exception):
    """Continuous-mode startup refused BEFORE anything is written (dataset identity / closed-day integrity)."""


def ensure_dataset(base: str, cfg: dict) -> dict:
    """P2-CR Package E: one logical continuous dataset per directory, identified by an immutable dataset.json.
    Existing: must match dataset_id and calendar. Absent: only a fresh directory may become a dataset (a directory
    already holding collector data from another (e.g. bounded gate) run is refused, never adopted)."""
    p = os.path.join(base, "dataset.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("dataset_id") != cfg["dataset_id"]:
            raise StartupRefused(f"dataset_id_mismatch:{d.get('dataset_id')}!={cfg['dataset_id']}")
        if d.get("calendar") != cal.params():
            raise StartupRefused("dataset_calendar_mismatch")
        return d
    used = [x for x in ("raw", "runs", "manifests", "days", "universe", "control")
            if os.path.isdir(os.path.join(base, x)) and os.listdir(os.path.join(base, x))]
    if used:
        raise StartupRefused(f"dataset_identity_missing_in_nonempty_dir:{','.join(used)}")
    os.makedirs(base, exist_ok=True)
    d = {"record": "tsb.p2.forward.dataset", "record_version": 1, "dataset_id": cfg["dataset_id"],
         "created_ms": now_ms(), "calendar": cal.params(), "schema": C.SCHEMA, "schema_version": C.SCHEMA_VERSION,
         "collector_version": C.VERSION}
    with open(p + ".partial", "w", encoding="utf-8") as fh:
        json.dump(d, fh, sort_keys=True); fh.flush(); os.fsync(fh.fileno())
    os.rename(p + ".partial", p); os.chmod(p, 0o444)
    return d


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
        self.continuous = cfg["mode"] == "continuous"
        self.dataset = None
        if self.continuous:                                       # refuse BEFORE the writer creates anything
            self.dataset = ensure_dataset(self.base, cfg)
            bad = check_closed_days(self.base)
            if bad:
                raise StartupRefused("closed_day_integrity:" + ";".join(bad[:5]))
        self.stats = new_stats()
        self.q = queue.Queue(maxsize=cfg["queue_max"])
        self.enq = Enqueuer(self.q, cfg["queue_max"], self.stats)
        self.writer = SegmentWriter(self.base, self.boot_id, self.q, self.stats, cfg["flush_interval_s"],
                                    certify_grace_s=cfg["certify_shutdown_grace_s"], certifier_mode=cfg["certifier_mode"])
        self.writer_join_timeout_s = cfg["certify_shutdown_grace_s"] + 120
        self.certifier_dead_ms = collections.deque(maxlen=50)
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
        self.conn_outage = {}                     # P2F 1.6.0: conn name -> {"start", "opened", "failed"}
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
        # G3-F4 instrumentation (observability only; no behaviour change)
        self.lat_max_ms = 0; self.lat_recent = collections.deque(maxlen=600)
        self.lat_counts = {t: 0 for t in (100, 200, 500, 1000, 2000)}
        self.looplag_max_ms = 0; self.looplag_recent = collections.deque(maxlen=600)
        self.looplag_counts = {t: 0 for t in (100, 200, 500, 1000, 2000)}
        self.gc_pause_max_ms = 0; self.gc_long = 0
        self.gc_pending = collections.deque(maxlen=256)  # CR-R12: unreported >=100 ms pauses (drained every 100 ms)
        self.gc_events_dropped = 0                         # only if > 256 long pauses occur between two drains
        self._gc_t0 = {}
        self._gc_reported = 0
        # ---- P2-CR continuous-mode state (unused in bounded mode) ----
        self.task_periods = dict(TASK_PERIOD_S)
        if self.continuous:
            self.task_periods.update({"universe": 60.0, "days": 60.0, "rotation": 60.0,
                                      "procwatch": float(cfg["process_check_interval_s"])})
        self.closed_bytes = {}                 # day -> bytes (day-close records; read once)
        self.incidents = IncidentLog(self.base, self.boot_id) if self.continuous else None
        self.procwatch = ProcWatch(cfg["process_violation_checks"]) if self.continuous else None
        self.proc_state = None
        self.pending_transition = None         # F10: accepted universe waiting for its effective boundary
        self.epoch_start_ms = None             # effective_from_ms of the active universe epoch
        self.retired_streams = set()           # streams of a previous epoch (late messages are not "unknown")
        self.previous_run = None
        self.fc_times = {"quarantine": collections.deque(), "certification": collections.deque(),
                         "http_429": collections.deque()}
        self.fc_seen = {"quarantine": 0, "certification": 0, "http_429": 0}
        self.clock_critical_since = None
        self.day_close = {}                    # day -> last close attempt result
        self.universe_next_ms = None
        self.transitions = 0
        # ---- P2F rotation hand-off / sequence continuity (collector >= 1.5.0, continuous mode) ----
        self.epoch_n = 0                       # socket epochs: one per WebSocket session (each connect)
        self.superseded = {}                   # conn name -> old WSConnection being handed off (overlap phase)
        self.handoff_tasks = set()
        self.seq_reset_last = None             # last seq_reset detail (incident detail, additive)
        self.seq_regression_events = 0         # in-socket regression lifecycle records written (bounded)
        self.catchup_ns = int(cfg.get("seq_catchup_timeout_s", 30)) * 1_000_000_000

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

    def _conn_incidents(self, m: int) -> None:
        """P2F 1.6.0 connection-level incidents (continuous mode). One incident per outage, no per-tick updates:
        conn_outage:<conn> (DEGRADED, state-like: resolves when the connection is data-live again) after
        conn_outage_incident_s without data; conn_recovery_failed:<conn> (CRITICAL, latched: needs an operator
        acknowledgement) when the outage reaches conn_recovery_fail_s. The outage clock starts at the connection's last
        data message (or WS start), so a socket that is up but silent counts as an outage."""
        if self.incidents is None or self.ws_start_ms is None:
            return
        lim_o, lim_f = 1000 * self.cfg["conn_outage_incident_s"], 1000 * self.cfg["conn_recovery_fail_s"]
        for c in list(self.conns):
            a = self.activity.get(c.name)
            if a is None:
                continue
            st = self.conn_outage.get(c.name)
            if self.data_live_at(c.name, m):
                if st is not None:
                    if st["opened"]:
                        self.incidents.resolve(f"conn_outage:{c.name}")
                        self.lifecycle("conn_outage_resolved", {"conn": c.name, "start_ms": st["start"],
                                                                "duration_ms": m - st["start"],
                                                                "recovery_failed": st["failed"]})
                    del self.conn_outage[c.name]
                continue
            if st is None:
                st = self.conn_outage[c.name] = {"start": max(a.last_data_ms or 0, self.ws_start_ms),
                                                 "opened": False, "failed": False}
            dur = m - st["start"]
            detail = {"conn": c.name, "start_ms": st["start"], "outage_ms": dur, "last_data_ms": a.last_data_ms,
                      "connected": bool(getattr(c, "connected", False)), "reconnects": getattr(c, "reconnects", 0),
                      "recovering": bool(getattr(c, "recovering", False)),
                      "last_recovery": (list(getattr(c, "recoveries", []) or [])[-1:] or [None])[0]}
            if not st["opened"] and dur >= lim_o:
                st["opened"] = True
                self.incidents.raise_(f"conn_outage:{c.name}", "DEGRADED", detail, latched=False)
                self.lifecycle("conn_outage_open", detail)
            if not st["failed"] and dur >= lim_f:
                st["failed"] = True
                self.incidents.raise_(f"conn_recovery_failed:{c.name}", "CRITICAL",
                                      {"cause": "outage_exceeded_limit", **detail}, latched=True)

    def gap_record(self, g: dict, recoverability: str, extra: dict | None = None) -> None:
        self.gap_count += 1
        key = g.get("stream_key", "")
        covered = g.get("open_at_stop") or set(g.get("causes") or [g.get("cause")]) & {
            "backpressure_or_rejected", "disk_hard_stop", "never_ready"}      # explained by a stop / writer incident
        if self.incidents is not None and not covered and recoverability == IRREPLACEABLE and \
                g.get("duration_ms", 0) >= 1000 * self.cfg["tier0_loss_incident_s"] and (
                key.startswith("market|") or (key.split("|")[0] in ("book", "depth")
                                              and key.split("|")[-1] in self.cfg["tier0"])):
            self.incidents.raise_("observation_loss:tier0", "WARNING",          # durable, needs acknowledgement
                                  {k: g.get(k) for k in ("stream", "start_ms", "end_ms", "duration_ms", "cause",
                                                         "causes", "missing_samples")}, latched=True)
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
        self.streams, self.tracks = self._stream_defs(self.universe)
        cad, dl, hold, cfg = self.cfg["cadence_ms"], self.cfg["first_obs_deadline_s"], int(self.cfg["sample_hold_window_s"] * 1000), self.cfg
        self.market = MarketTrack(cad["market"], "conn0-book", cfg["market_stale_ms"], 1000 * dl["market"], hold,
                                  cfg["market_component_max_age_ms"])
        self.stream_conn = {n: t.conn for n, t in self.tracks.items()}
        self.stream_conn[MARKET] = "conn0-book"

    def _stream_defs(self, universe: dict) -> tuple:
        """Deterministic stream set of a universe (tier order 0, 2, 1; a symbol is in its highest tier only)."""
        cad, lv, cfg = self.cfg["cadence_ms"], self.cfg["depth_levels"], self.cfg
        dl, hold = cfg["first_obs_deadline_s"], int(cfg["sample_hold_window_s"] * 1000)
        st, tracks = {}, {}
        for tier, syms in ((0, universe["tier0"]), (2, universe["tier2"]), (1, universe["tier1"])):
            t = f"t{tier}"
            for s in syms:
                low = s.lower()
                nb, n = f"{low}@bookTicker", lv[t]
                nd = f"{low}@depth{n}"
                st[nb] = {"kind": "book", "symbol": s, "tier": tier, "cadence": cad[f"{t}_book"]}
                st[nd] = {"kind": "depth", "symbol": s, "tier": tier, "cadence": cad[f"{t}_depth"], "levels": n}
                tracks[nb] = StreamTrack(nb, "book", s, tier, cad[f"{t}_book"], "conn0-book",
                                         cfg["book_t0_stale_ms"] if tier == 0 else cfg["book_t12_dead_ms"],
                                         1000 * (dl["t0_book"] if tier == 0 else dl["t12_book"]), hold)
                tracks[nd] = StreamTrack(nd, "depth", s, tier, cad[f"{t}_depth"], "conn1-depth", cfg["depth_stale_ms_by_tier"][t],
                                         1000 * dl["depth"], hold, levels=n)
        return st, tracks

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
        uni["_raw"] = {"exchangeinfo": self.rest.last_body.pop("/api/v3/exchangeInfo", None),     # released once
                       "ticker": self.rest.last_body.pop("/api/v3/ticker/24hr", None)}            # persisted
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
        try:
            prior = self._prior_universe()
        except Exception as e:                                        # noqa: BLE001 - m5
            self.startup_failure = [f"prior_universe_unreadable:{type(e).__name__}"]
            return False
        n, backoff, problems = self.cfg["universe_load_attempts"], self.cfg["universe_retry_backoff_s"], []
        for attempt in range(1, n + 1):
            try:
                uni, problems = await self.fetch_universe(prior)
            except Exception as e:                                    # noqa: BLE001 - malformed shapes etc.
                uni, problems = None, [f"exception:{type(e).__name__}: {e}"[:200]]
            if uni is not None and not problems:
                try:
                    self.persist_universe(uni, applied=True)
                    return True
                except Exception as e:                                # noqa: BLE001 - m5: durable reason, then retry
                    problems = [f"persist_failed:{type(e).__name__}: {e}"[:200]]
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

    def persist_universe(self, uni: dict, applied: bool, activate: bool = True) -> dict:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        uid = R.universe_id(stamp, uni["rule_version"])
        raw = uni.pop("_raw", None) or {}
        for k, body in raw.items():                                  # M2: raw REST bodies, immutable, for re-derivation
            if body is None:
                continue
            rp = os.path.join(self.base, "universe", f"raw-{stamp}-{self.boot_id[:8]}-{k}.json.gz")
            data = gzip.compress(body, mtime=0)
            with open(rp + ".partial", "wb") as fh:
                fh.write(data); fh.flush(); os.fsync(fh.fileno())
            os.rename(rp + ".partial", rp); os.chmod(rp, 0o444)
            uni.setdefault("source", {}).setdefault(k, {}).update(
                raw_file=os.path.relpath(rp, self.base), raw_file_sha256=hashlib.sha256(data).hexdigest(),
                body_bytes=len(body))
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
        if applied and activate:
            self.universe, self.universe_meta = doc, meta
            self.build_streams()
        self.last_persisted_universe = doc                              # F10: the not-yet-active universe document
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
            if not isinstance(u, dict):
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
            if self.market is not None and self.market.on_array(
                    recv_ns, data, stale_guard_ns=self.catchup_ns if self.continuous else None) == "first":
                self._stream_ready(self.market)
            return
        tr = self.tracks.get(name)
        if tr is None:
            if name in self.retired_streams:                          # F10: rotation overlap after a transition
                self.stats["retired_stream_msgs"] = self.stats.get("retired_stream_msgs", 0) + 1; return
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
        if self.continuous:                                          # P2F 1.5.0: epoch-aware continuity
            self._on_seq(conn, tr, recv_ns, data, seq)
            return
        res = tr.on_msg(recv_ns, data, seq, overlap=False)           # bounded mode: unchanged pre-1.5.0 rule
        if res == "seq_regression":
            self.stats["rejected"]["seq_regression"] += 1           # older message (e.g. rotation overlap): ignore
        elif res == "seq_reset":
            self.stats["seq_reset"] = self.stats.get("seq_reset", 0) + 1
            self.lifecycle("seq_reset", {"stream": tr.name, "seq": seq})
        elif res == "first":
            self._stream_ready(tr)

    # ---------- P2F 1.5.0: socket epochs and sequence continuity (continuous mode) ----------
    def _epoch_of(self, conn) -> int:
        """Socket epoch of a message: assigned at each connect (on_state). Messages without a connection object
        (offline harness) share epoch 0."""
        ep = getattr(conn, "p2f_epoch", None) if conn is not None else 0
        if ep is None:
            ep = self._new_epoch(conn)
        return ep

    def _new_epoch(self, conn) -> int:
        self.epoch_n += 1
        try:
            conn.p2f_epoch = self.epoch_n
        except AttributeError:
            pass
        return self.epoch_n

    def _on_seq(self, conn, tr, recv_ns: int, data, seq: int) -> None:
        ep = self._epoch_of(conn)
        res, info = tr.on_seq(recv_ns, data, seq, ep, self.catchup_ns)
        st = self.stats
        if res == "first":
            self._stream_ready(tr)
        elif res == "seq_stale":
            st["seq_stale"] = st.get("seq_stale", 0) + 1                  # overlap / catch-up copy: never a regression
        elif res == "seq_regression":
            st["rejected"]["seq_regression"] += 1                         # genuine: the same socket went backwards
            if info is not None and self.seq_regression_events < 500:
                self.seq_regression_events += 1
                self.lifecycle("seq_regression", {"stream": tr.name, "conn": getattr(conn, "name", None), "epoch": ep,
                                                  "seq": seq, **info})
        elif res == "seq_reset":
            st["seq_reset"] = st.get("seq_reset", 0) + 1
            causes = st.setdefault("seq_reset_causes", {})
            causes[info["cause"]] = causes.get(info["cause"], 0) + 1
            self.seq_reset_last = {"stream": tr.name, "cause": info["cause"], "seq": seq, "hw": info["hw"]}
            self.lifecycle("seq_reset", {"stream": tr.name, "seq": seq, "conn": getattr(conn, "name", None), "epoch": ep,
                                         **{k: v for k, v in info.items() if k != "hw_recv_ns"},
                                         "hw_recv_ms": info["hw_recv_ns"] // 1_000_000})
        if info is not None and info.get("caught_up"):
            st["seq_catchups"] = st.get("seq_catchups", 0) + 1
            st["seq_catchup_max_ms"] = max(st.get("seq_catchup_max_ms", 0), info["behind_ms"])

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
        if self.continuous and state != "connected" and self.superseded.get(conn.name) is conn:
            # P2F 1.5.0: the OLD socket of a hand-off ended (e.g. server close after serverShutdown) while its
            # replacement is up: not a disconnect of the connection (no down transition, subscriptions of the
            # replacement untouched) and never a reconnect of the old object. The hand-off ends early, fail-closed.
            conn._closing = True
            self.lifecycle("ws_superseded_closed", {"conn": conn.name, "state": state,
                                                    "epoch": getattr(conn, "p2f_epoch", None)})
            return
        if self.continuous and state == "connected":
            self._new_epoch(conn)                                       # each WebSocket session = a new epoch
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
        self.lifecycle(f"ws_{state}", {"conn": conn.name, "reconnects": getattr(conn, "reconnects", 0),
                                       **({"epoch": getattr(conn, "p2f_epoch", None)} if self.continuous else {})})
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
        if self.continuous:                                            # P2-CR F: any 418 => stop, no auto-resume
            self.fail_closed("http_418", {"banned_until_mono": self.rate.banned_until})

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
                            on_sub_sent=self.on_sub_sent, on_sub_result=self.on_subscribe_result,
                            on_recovery=self.on_conn_recovery, close_grace_s=self.cfg["ws_close_grace_s"],
                            abort_wait_s=self.cfg["ws_abort_wait_s"])

    def on_conn_recovery(self, conn, res: dict) -> None:
        """P2F 1.6.0: every bounded session end is recorded; a WEDGED session (still alive after graceful close,
        transport abort and task cancel) is a failed recovery: CRITICAL latched incident, the object is retired (it
        can never deliver again) and replaced by a fresh connection object with its own task."""
        self.stats.setdefault("conn_session_ends", {})
        self.stats["conn_session_ends"][res["outcome"]] = self.stats["conn_session_ends"].get(res["outcome"], 0) + 1
        self.lifecycle("conn_recovery", {"conn": conn.name, **res})
        if res["outcome"] != "wedged":
            return
        if self.incidents is not None:
            self.incidents.raise_(f"conn_recovery_failed:{conn.name}", "CRITICAL",
                                  {"cause": "session_wedged", **res}, latched=True)
        if conn in self.conns and conn.name not in self.rotating and not self.stop_event.is_set():
            conn.retire()
            new = self._new_conn(conn.name, conn.streams)
            new.task = asyncio.create_task(new.run(), name=conn.name + "-replaced")
            self.conns[self.conns.index(conn)] = new
            self.lifecycle("ws_conn_replaced", {"conn": conn.name, "retired_gen": res.get("gen")})

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

    async def rotate(self, old: WSConnection, reason: str, streams: list | None = None) -> dict:
        """Overlap rollover: open a replacement, wait for its first message, then close the old connection.
        `streams` (F10): the replacement subscribes to a new stream list (universe transition).
        Continuous mode (P2F 1.5.0): between the replacement's first message and the close, a bounded per-stream
        HAND-OFF keeps the old socket until the replacement has reached, on every stream active during the overlap,
        the sequence the old socket had reached (frozen target). An incomplete hand-off fails closed (explicit
        uncertainty: WARNING incident + post-hand-off gaps); the old socket's final sequences are recorded and a
        post-close audit (lifecycle `ws_handoff`) records where the replacement reached them."""
        if old.name in self.rotating:
            return {"conn": old.name, "reason": reason, "skipped": "already_rotating"}
        self.rotating.add(old.name)
        new = None
        try:
            t0 = now_ms()
            new = self._new_conn(old.name, list(streams) if streams is not None else old.streams)
            new.task = asyncio.create_task(new.run(), name=old.name + "-r")
            handoff = None
            try:
                try:
                    await asyncio.wait_for(new.first_msg.wait(), timeout=60)
                    overlap_ok = True
                except asyncio.TimeoutError:
                    overlap_ok = False
                t1 = now_ms()
                if self.continuous and overlap_ok:
                    handoff = await self._handoff(old, new)
            except asyncio.CancelledError:                               # stop during a rotation: nothing leaks
                if self.continuous:
                    await new.close()
                raise
            await old.close()
            close_ns = time.time_ns()
            if self.superseded.get(old.name) is old:
                del self.superseded[old.name]
            if old in self.conns:
                self.conns[self.conns.index(old)] = new
            ev = {"conn": old.name, "reason": reason, "started_ms": t0, "new_first_msg_ms": t1, "overlap_ok": overlap_ok,
                  "old_last_msg_ms": (old.last_msg_ns or 0) // 1_000_000, "streams": len(new.streams)}
            audit = None
            if handoff is not None:
                ev["handoff"] = {k: v for k, v in handoff.items() if not k.startswith("_")}
                ev["handoff"]["close_ms"] = close_ns // 1_000_000
                audit = self._handoff_close(old, new, handoff, close_ns, reason)
            self.rotation["events"].append(ev)
            if len(self.rotation["events"]) > 50:                       # bounded history (continuous mode)
                del self.rotation["events"][:-50]
            self.lifecycle("ws_rotation", ev)
            if not overlap_ok and self.incidents is not None:            # F24: surfaced, never silent
                self.incidents.raise_(f"rotation_overlap_failed:{old.name}", "WARNING", ev)
            if handoff is not None and not handoff["complete"] and handoff["reason"] != "stopping" \
                    and self.incidents is not None:                      # P2F 1.5.0: continuity not established
                self.incidents.raise_(f"rotation_handoff_incomplete:{old.name}", "WARNING",
                                      {k: ev["handoff"][k] for k in ("reason", "pending", "pending_streams", "close_ms")})
            if audit is not None:
                t = self._spawn(self._handoff_audit(audit))
                if t is not None:
                    self.handoff_tasks.add(t); t.add_done_callback(self.handoff_tasks.discard)
            return ev
        finally:
            self.rotating.discard(old.name)
            if self.superseded.get(old.name) is old:
                del self.superseded[old.name]

    def _reached(self, name: str, ep, target: int) -> bool:
        tr = self.tracks.get(name)
        st = tr.seqc.eps.get(ep) if tr is not None else None
        return st is not None and st.last is not None and st.last >= target

    def _old_targets(self, names: list, old_ep, since_ns: int) -> dict:
        """Streams the OLD socket delivered at or after since_ns (active during the overlap) -> its seq now."""
        out = {}
        for n in names:
            tr = self.tracks.get(n)
            st = tr.seqc.eps.get(old_ep) if tr is not None else None
            if st is not None and st.last is not None and st.last_ns is not None and st.last_ns >= since_ns:
                out[n] = st.last
        return out

    async def _handoff(self, old, new) -> dict:
        """Bounded per-stream hand-off (P2F 1.5.0). Targets are FROZEN at first_msg + ws_handoff_min_s (a replacement
        with a constant lag never reaches a moving target): every stream the old socket delivered during the overlap
        must be reached by the replacement's own sequence. Ends at catch-up, timeout, old socket ended, replacement
        disconnected or stop; never waits longer than ws_handoff_timeout_s."""
        self.superseded[old.name] = old
        h0 = time.time_ns()
        mn, to = float(self.cfg["ws_handoff_min_s"]), float(self.cfg["ws_handoff_timeout_s"])
        old_ep, new_ep = getattr(old, "p2f_epoch", None), getattr(new, "p2f_epoch", None)
        olds = set(old.streams)
        names = [n for n in new.streams if n in olds and n in self.tracks]
        targets, reason = None, None
        while True:
            el = (time.time_ns() - h0) / 1e9
            if self.stop_event.is_set():
                reason = "stopping"
            elif getattr(old, "_closing", False) or not getattr(old, "connected", True):
                reason = "old_closed"
            elif not getattr(new, "connected", True):
                reason = "new_disconnected"
            if targets is None and (el >= mn or reason is not None):
                targets = self._old_targets(names, old_ep, h0)
            pending = [n for n, tg in (targets or {}).items() if not self._reached(n, new_ep, tg)]
            if reason is None and targets is not None and not pending:
                reason = "caught_up"
            elif reason is None and el >= to:
                reason = "timeout"
            if reason is not None:
                break
            await asyncio.sleep(0.05)
        return {"complete": not pending and reason in ("caught_up", "old_closed"), "reason": reason,
                "old_epoch": old_ep, "new_epoch": new_ep, "min_s": mn, "timeout_s": to, "duration_ms": (time.time_ns() - h0) // 1_000_000,
                "streams": len(names), "targets": len(targets or {}), "pending": len(pending),
                "pending_streams": sorted(pending)[:20], "_names": names, "_pending": pending,
                "_targets": targets or {}}

    def _handoff_close(self, old, new, handoff: dict, close_ns: int, reason: str) -> dict:
        """At the close of the old socket: record its FINAL per-stream sequence and the replacement's position,
        fail closed for pending streams (values received before the close are not persisted until the replacement
        delivers an accepted message), and arm a watch for the first replacement message reaching the old final."""
        old_ep, new_ep = handoff["old_epoch"], handoff["new_epoch"]
        streams, pend = {}, set(handoff["_pending"])
        for n in handoff["_names"]:
            tr = self.tracks.get(n)
            if tr is None:
                continue
            o, w = tr.seqc.eps.get(old_ep), tr.seqc.eps.get(new_ep)
            d = {"target": handoff["_targets"].get(n), "old_final": o.last if o else None,
                 "old_final_ms": (o.last_ns // 1_000_000) if o and o.last_ns else None,
                 "new_first": w.first if w else None, "new_first_ms": (w.first_ns // 1_000_000) if w else None,
                 "new_at_close": w.last if w else None, "await": n in pend and not handoff["complete"]}
            if d["await"]:
                tr.await_after_ns = close_ns
            if d["old_final"] is not None:
                hit = (w.last, w.last_ns) if w is not None and w.last is not None and w.last >= d["old_final"] else None
                tr.seqc.watch = {"ep": new_ep, "target": d["old_final"], "hit": hit, "before_close": hit is not None}
                d["_watch"] = tr.seqc.watch
            streams[n] = d
        return {"conn": old.name, "reason": reason, "old_epoch": old_ep, "new_epoch": new_ep, "close_ns": close_ns,
                "handoff": {k: v for k, v in handoff.items() if not k.startswith("_")}, "streams": streams}

    async def _handoff_audit(self, a: dict) -> None:
        """Post-close continuity audit: waits (bounded by seq_catchup_timeout_s) until the replacement reached every
        old final sequence, then records lifecycle `ws_handoff` with one continuity class per stream:
        proven (id ranges overlap), ahead (replacement already newer while both were open), resumed (replacement
        silent until after the close, then newer), quiet (no message on the replacement yet), unresolved (only
        OLDER messages: continuity NOT established -> fail closed), no_old (old socket never delivered)."""
        end, why = a["close_ns"] + self.catchup_ns, "deadline"
        try:
            while time.time_ns() < end and not self.stop_event.is_set():
                if all(d["_watch"]["hit"] is not None for d in a["streams"].values() if "_watch" in d):
                    why = "all_reached"; break
                await asyncio.sleep(0.1)
            else:
                why = "stopping" if self.stop_event.is_set() else why
        except asyncio.CancelledError:
            why = "stopping"
            self._handoff_record(a, why)
            raise
        self._handoff_record(a, why)

    def _handoff_record(self, a: dict, why: str) -> None:
        classes, out, unresolved = collections.Counter(), {}, []
        for n, d in sorted(a["streams"].items()):
            w = d.pop("_watch", None)
            hit = w["hit"] if w is not None else None
            if d["old_final"] is None:
                c = "no_old"
            elif hit is not None:
                c = "proven" if d["new_first"] is not None and d["new_first"] <= d["old_final"] else \
                    "ahead" if d["new_first_ms"] is not None and d["new_first_ms"] <= a["close_ns"] // 1_000_000 else "resumed"
                d["reach_seq"], d["reach_ms"] = hit[0], hit[1] // 1_000_000
                d["reached_before_close"] = bool(w.get("before_close"))
            else:
                tr = self.tracks.get(n)
                st = tr.seqc.eps.get(a["new_epoch"]) if tr is not None else None
                d["new_last"] = st.last if st is not None else None
                d["new_stale_n"] = st.stale_n if st is not None else None
                c = "quiet" if d["new_first"] is None and (st is None or st.first is None) else "unresolved"
                if c == "unresolved":
                    unresolved.append(n)
                    if tr is not None:
                        tr.await_after_ns = max(tr.await_after_ns or 0, a["close_ns"])   # fail closed from here on
            tr = self.tracks.get(n)
            if tr is not None and tr.seqc.watch is w:
                tr.seqc.watch = None
            d["class"] = c
            classes[c] += 1
            out[n] = {k: v for k, v in d.items() if v is not None}
        self.stats["handoffs"] = self.stats.get("handoffs", 0) + 1
        hc = self.stats.setdefault("handoff_classes", {})
        for k, v in classes.items():
            hc[k] = hc.get(k, 0) + v
        self.lifecycle("ws_handoff", {"conn": a["conn"], "reason": a["reason"], "old_epoch": a["old_epoch"],
                                      "new_epoch": a["new_epoch"], "close_ms": a["close_ns"] // 1_000_000,
                                      "audit_end": why, "handoff": a["handoff"], "classes": dict(classes),
                                      "unresolved": unresolved[:50], "streams": out})
        if unresolved and why != "stopping" and self.incidents is not None:
            self.incidents.raise_(f"rotation_handoff_incomplete:{a['conn']}", "WARNING",
                                  {"reason": "unresolved_after_close", "unresolved": unresolved[:20],
                                   "close_ms": a["close_ns"] // 1_000_000})

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
        base = getattr(tr, "deadline_base_ms", None)                  # F10: streams added by a universe transition
        if base is None:
            base = self.ws_start_ms if self.ws_start_ms is not None else self.started_ms
        return base + tr.deadline_rel_ms

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
                elif tr.await_after_ns is not None and val[0] < tr.await_after_ns <= s * 1_000_000:
                    cause = "awaiting_post_reconnect_data"     # P2F 1.5.0: hand-off continuity not established
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
        if self.continuous:
            if self.pending_transition is not None and sample_ms >= self.pending_transition["T"]:
                self._apply_transition(sample_ms)                   # F10: epoch switch exactly at a boundary
            if cal.is_day_start(sample_ms):
                self._day_boundary(sample_ms)                       # day-scoped, self-contained evidence
        for tr in self.tracks.values():
            if sample_ms % tr.cadence == 0:
                self._sample_track(tr, sample_ms)
        if self.market is not None and sample_ms % self.market.cadence == 0:
            self._sample_market(sample_ms)
        self.last_sampled_ms = sample_ms

    # ---------- P2-CR continuous mode: epochs, day boundaries ----------
    def _day_boundary(self, s: int) -> None:
        """At the first boundary of a calendar day: every open gap is split (closed through the previous boundary,
        recorded with day_split=True; a still-missing stream reopens at s), then a day checkpoint records the state a
        day verifier needs without reading earlier days: run, universe epoch, connection states."""
        n = 0
        for t in self.all_tracks():
            g = t.close_gap()
            if g is not None:
                self.gap_record(g, IRREPLACEABLE, {"day_split": True}); n += 1
        self.lifecycle("day_checkpoint", {
            "day": cal.day_key(s), "day_start_ms": s, "calendar": cal.params(),
            "dataset_id": self.cfg["dataset_id"], "run_record_file": self.writer.run_record,
            "run_record_sha256": self.run_record_sha,
            "universe": {**(self.universe_meta or {}), "effective_from_ms": self.epoch_start_ms},
            "conns": {name: {"up": self.conn_up_at(name, s), "last_up_ms": self.last_up(name, s), "streams": streams}
                      for name, streams in self._conn_streams()},
            "expected_streams": len(self.tracks) + (1 if self.market else 0), "gaps_split": n})

    def _apply_transition(self, s: int) -> None:
        """F10 / R05: the accepted universe becomes effective at boundary s (>= T). Streams no longer expected are
        retired (their open gaps closed and recorded), re-tiered streams continue with their received messages under
        the new cadence, added streams start with their first-observation deadline counted from s. Both connections
        are then rotated (overlap) to the new stream lists; nothing is bridged and no stream disappears silently."""
        pt, self.pending_transition = self.pending_transition, None
        doc, meta = pt["universe"], pt["meta"]
        new_streams, new_tracks = self._stream_defs(doc)
        added, removed, retiered = [], [], []
        for n, t in list(self.tracks.items()):
            nt = new_tracks.get(n)
            if nt is not None and nt.cadence == t.cadence and nt.tier == t.tier:
                new_tracks[n] = t                                   # unchanged: same track, state and open gap
                continue
            g = t.close_gap()
            if g is not None:
                self.gap_record(g, IRREPLACEABLE, {"universe_transition": meta["universe_id"]})
            if nt is None:
                removed.append(n); self.retired_streams.add(n)
            else:
                retiered.append({"stream": n, "symbol": t.symbol, "from_tier": t.tier, "to_tier": nt.tier,
                                 "from_cadence_ms": t.cadence, "to_cadence_ms": nt.cadence})
                nt.values, nt.ready_ms, nt.ready_ns, nt.msgs = t.values, t.ready_ms, t.ready_ns, t.msgs
                nt.seqc, nt.await_after_ns = t.seqc, t.await_after_ns        # P2F 1.5.0: continuity state too
                nt.sub, nt.sub_sent_ms, nt.ack_ms = t.sub, t.sub_sent_ms, t.ack_ms
                nt.deadline_base_ms = s
        for n, nt in new_tracks.items():
            if n not in self.tracks:
                added.append(n); nt.deadline_base_ms = s; self.retired_streams.discard(n)
        self.streams, self.tracks = new_streams, new_tracks
        self.stream_conn = {n: t.conn for n, t in new_tracks.items()}
        self.stream_conn[MARKET] = "conn0-book"
        prior = (self.universe_meta or {}).get("universe_id")
        self.universe, self.universe_meta = doc, {k: meta[k] for k in ("universe_id", "file", "sha256", "stamp", "applied")}
        self.epoch_start_ms = s
        self.transitions += 1
        conns = {name: streams for name, streams in self._conn_streams()}
        self.lifecycle("universe_transition", {
            "universe_id": meta["universe_id"], "file": meta["file"], "sha256": meta["sha256"], "effective_from_ms": s,
            "scheduled_ms": pt["T"], "prior_universe_id": prior, "added": sorted(added), "removed": sorted(removed),
            "retiered": retiered, "tiers": {k: len(doc[k]) for k in ("tier0", "tier1", "tier2")}, "conns": conns})
        for name in conns:
            self._spawn(self._rotate_to_current(name, "universe_transition"))

    async def _rotate_to_current(self, name: str, reason: str) -> None:
        """Rotate connection `name` to the CURRENT desired stream list (waits for a rotation already in flight)."""
        for _ in range(600):
            if name not in self.rotating:
                break
            await asyncio.sleep(0.5)
        want = dict(self._conn_streams()).get(name)
        c = self._conn_obj(name)
        if c is None or want is None or list(c.streams) == list(want):
            return
        await self.rotate(c, reason, want)

    def _writer_open_days(self) -> set:
        for _ in range(5):
            try:
                return {seg.day for seg in list(self.writer.segments.values())}
            except RuntimeError:                                     # dict changed size (writer thread): retry
                continue
        return {"__unknown__"}

    async def universe_task(self) -> None:
        """F10: one refresh per calendar day at day start + universe_refresh_at_s; failures retried every 30 min
        (the previous universe stays active and the collector is DEGRADED meanwhile, F42)."""
        while not self.stop_event.is_set():
            self.beats["universe"] = time.monotonic()
            m = now_ms()
            if self.universe_next_ms is None:
                t = cal.day_start_ms(cal.day_key(m)) + 1000 * self.cfg["universe_refresh_at_s"]
                self.universe_next_ms = t if t > m else t + cal.day_ms()
            if m >= self.universe_next_ms and self.pending_transition is None:
                action = await self.refresh_and_transition()
                nxt = cal.day_start_ms(cal.day_key(m)) + 1000 * self.cfg["universe_refresh_at_s"] + cal.day_ms()
                self.universe_next_ms = nxt if action in ("unchanged", "transition_scheduled") else \
                    min(nxt, now_ms() + 30 * 60_000)
            await self._sleep(max(1.0, min(30.0, (self.universe_next_ms - now_ms()) / 1000)))

    async def refresh_and_transition(self) -> str:
        try:
            uni, problems = await self.fetch_universe(self.universe)
        except Exception as e:                                        # noqa: BLE001
            uni, problems = None, [f"exception:{type(e).__name__}"]
        _, _, action = U.refresh_decision(self.universe, uni if not problems else None, problems)
        active_id = (self.universe_meta or {}).get("universe_id")
        if action != "accepted":
            self.universe_degraded = (problems or ["unknown"])[:5]
            self.incidents.raise_("universe_refresh_failed", "DEGRADED", {"problems": problems[:10]}, latched=False)
            self.lifecycle("universe_refresh", {"action": action, "degraded": True, "problems": problems[:20],
                                                "active_universe_id": active_id})
            return action
        self.universe_degraded = None
        self.incidents.resolve("universe_refresh_failed")
        same = all(sorted(uni[k]) == sorted(self.universe[k]) for k in ("tier0", "tier1", "tier2"))
        if same:
            meta = self.persist_universe(uni, applied=False)
            self.lifecycle("universe_refresh", {"action": "accepted", "changed": False, "degraded": False,
                                                "evaluated_universe_id": meta["universe_id"], "active_universe_id": active_id})
            return "unchanged"
        streams, _ = self._stream_defs(uni)
        nb = sum(1 for v in streams.values() if v["kind"] == "book") + 1
        nd = sum(1 for v in streams.values() if v["kind"] == "depth")
        if nb > 300 or nd > 300:                                      # never exceed the per-connection budget
            self.incidents.raise_("universe_stream_budget", "DEGRADED", {"book": nb, "depth": nd}, latched=False)
            self.lifecycle("universe_refresh", {"action": "rejected_stream_budget", "degraded": True,
                                                "active_universe_id": active_id})
            return "rejected_stream_budget"
        meta = self.persist_universe(uni, applied=True, activate=False)
        T = ((now_ms() + 1000 * self.cfg["universe_transition_delay_s"]) // 1000 + 1) * 1000
        self.pending_transition = {"T": T, "universe": self.last_persisted_universe, "meta": meta}
        self.lifecycle("universe_refresh", {"action": "accepted", "changed": True, "degraded": False,
                                            "universe_id": meta["universe_id"], "scheduled_effective_from_ms": T,
                                            "active_universe_id": active_id})
        return "transition_scheduled"

    async def rotation_task(self) -> None:
        """F24: proactive overlap rotation of each connection `ws_rotation_s` after its last (re)connect, i.e. before
        the exchange's 24 h connection lifetime ends it unplanned."""
        lim = 1000 * self.cfg["ws_rotation_s"]
        while not self.stop_event.is_set():
            self.beats["rotation"] = time.monotonic()
            m = now_ms()
            for c in list(self.conns):
                a = self.activity.get(c.name)
                up = a.last_up_since(m) if a else None
                if getattr(c, "connected", False) and up is not None and m - up >= lim and c.name not in self.rotating:
                    self._spawn(self.rotate(c, "proactive_lifetime"))
            await self._sleep(min(30.0, lim / 4000))

    async def days_task(self) -> None:
        """Day close (continuous): a past day whose files are all certified and listed in its manifest is closed
        (days/<day>.json); hot paths never scan it again. A mismatch is a manifest/checksum integrity failure."""
        loop = asyncio.get_running_loop()
        while not self.stop_event.is_set():
            self.beats["days"] = time.monotonic()
            m = now_ms()
            try:
                days = await loop.run_in_executor(None, open_days, self.base)
            except OSError as e:
                days = []
                self.incidents.raise_("day_scan_error", "DEGRADED", {"error": type(e).__name__})
            for day in days:
                if self.stop_event.is_set() or m < cal.day_end_ms(day) + 1000 * self.cfg["day_close_after_s"]:
                    continue
                res, info = await loop.run_in_executor(None, close_day, self.base, day, self._writer_open_days())
                self.day_close[day] = res if res != "not_ready" else f"not_ready:{info}"
                if res == "closed":
                    self.day_close.pop(day, None)
                    self.incidents.resolve(f"day_close_overdue:{day}")
                    self.lifecycle("day_closed", {"day": day, "segments": info["segments"], "bytes_total": info["bytes_total"],
                                                  "manifest_sha256": info["manifest_sha256"], "boots": info["boots"]})
                elif res == "mismatch":
                    self.fail_closed("day_close_mismatch", {"day": day, "problems": info[:10]})
                elif m > cal.day_end_ms(day) + 6 * cal.hour_ms():
                    self.incidents.raise_(f"day_close_overdue:{day}", "WARNING", {"reason": info}, latched=False)
            if len(self.day_close) > 30:
                for k in sorted(self.day_close)[:-30]:
                    self.day_close.pop(k, None)
            await self._sleep(min(60.0, cal.hour_ms() / 1000))           # production: every 60 s

    async def procwatch_task(self) -> None:
        while not self.stop_event.is_set():
            self.beats["procwatch"] = time.monotonic()
            viol, trans = self.procwatch.check()
            self.proc_state = {"enabled": self.procwatch.enabled, "checks": self.procwatch.checks,
                               "roles": self.procwatch.last, "violations": len(viol)}
            for t in trans:
                self.incidents.raise_("process_unexpected_transient", "WARNING", t)
            if viol:
                self.fail_closed("process_role_violation", {"processes": viol[:5]})
                return
            await self._sleep(self.cfg["process_check_interval_s"])

    def fail_closed(self, reason: str, detail=None) -> None:
        """P2-CR Package F: integrity / resource conditions stop the collector (graceful drain, exit 6); the container
        stays down (restart: "no") until an operator acts. Durable: incident + lifecycle + fatal marker."""
        if self.stop_reason is not None:
            return
        if self.incidents is not None:
            self.incidents.raise_(f"failclosed:{reason}", "CRITICAL", detail)
            self.incidents.flush()
        self.lifecycle("fail_closed_stop", {"reason": reason, "detail": detail})
        self.fatal(f"failclosed:{reason}", EXIT_FAILCLOSED)

    def _continuous_checks(self, m: int) -> None:
        """1 s fail-closed / incident evaluation (continuous mode). Transient non-integrity warnings never stop."""
        st, cfg = self.stats, self.cfg
        rate = {"quarantine": (st["segments_quarantined"], cfg["fc_quarantine_per_24h"], "DEGRADED"),
                "certification": (st["certification_failures"], cfg["fc_cert_failures_per_24h"], "DEGRADED"),
                "http_429": (self.rate.events.get("http_429", 0), cfg["fc_http429_per_24h"], "WARNING")}
        for key, (cur, lim, sev) in rate.items():
            dq = self.fc_times[key]
            if cur > self.fc_seen[key]:
                dq.extend([m] * (cur - self.fc_seen[key]))
                self.fc_seen[key] = cur
                self.incidents.raise_(key, sev, {"total": cur})
            while dq and m - dq[0] > 86_400_000:
                dq.popleft()
            if len(dq) >= lim:
                self.fail_closed(f"{key}_limit", {"count_24h": len(dq), "limit": lim}); return
        for key, cur in (("write_errors", st["write_errors"]), ("writer_rejected", sum(st["writer_rejected"].values())),
                         ("emit_failed", sum(st["emit_failed"].values())), ("seq_reset", st.get("seq_reset", 0)),
                         ("task_failed", st.get("task_failed_total", 0)), ("certifier_restarts", self.writer.certifier_restarts),
                         ("wall_clock_step", st.get("wall_clock_steps", 0)), ("handler_errors", st["handler_errors"])):
            if cur > self.fc_seen.get(key, 0):
                self.fc_seen[key] = cur
                self.incidents.raise_(key, "WARNING" if key in ("wall_clock_step", "handler_errors") else "DEGRADED",
                                      {"total": cur, **({"last": self.seq_reset_last, "causes": st.get("seq_reset_causes")}
                                                        if key == "seq_reset" else {})})
        ws = self.writer.status()
        if ws["beat_age_ms"] is not None and ws["beat_age_ms"] >= 1000 * cfg["fc_writer_stall_s"]:
            self.fail_closed("writer_stalled", {"beat_age_ms": ws["beat_age_ms"]}); return
        if ws["durable_lag_ms"] >= 1000 * cfg["fc_durable_lag_s"]:
            self.fail_closed("writer_not_durable", {"durable_lag_ms": ws["durable_lag_ms"]}); return
        if self.clock.state == "CRITICAL":
            self.clock_critical_since = self.clock_critical_since or m
            self.incidents.raise_("clock_critical", "CRITICAL", {"skew_ms": self.clock.last_skew_ms,
                                                                 "uncertainty_ms": self.clock.uncertainty_ms}, latched=False)
            if m - self.clock_critical_since >= 1000 * cfg["fc_clock_critical_s"]:
                self.fail_closed("clock_critical_persistent", {"since_ms": self.clock_critical_since}); return
        elif self.clock_critical_since is not None:
            self.clock_critical_since = None
            self.incidents.resolve("clock_critical")

    def sample_until(self, target_ms: int, live: bool = False) -> int:
        """F19: process EVERY boundary from the last processed one up to target (inclusive). Returns the count.
        live=True (sampler task / stop): a boundary processed > 2 s after it passed is attributed to the sampler."""
        start = target_ms if self.last_sampled_ms is None else self.last_sampled_ms + 1000
        n = 0
        for s in range(start, target_ms + 1, 1000):
            self._lateness = (now_ms() - s) if live else None
            if live:
                self._record_lateness(self._lateness)
            try:
                self.sample(s)
            finally:
                self._lateness = None
            n += 1
        return n

    def _record_lateness(self, lat: int) -> None:
        self.lat_max_ms = max(self.lat_max_ms, lat); self.lat_recent.append((now_ms(), lat))
        for t in self.lat_counts:
            if lat >= t:
                self.lat_counts[t] += 1

    def _gc_cb(self, phase, info) -> None:                      # G3-F4: GC pause timing (main process)
        if phase == "start":
            self._gc_t0[info.get("generation")] = (time.perf_counter(), time.time_ns())
        else:
            st = self._gc_t0.pop(info.get("generation"), None)
            if st:
                d = (time.perf_counter() - st[0]) * 1000
                self.gc_pause_max_ms = max(self.gc_pause_max_ms, round(d, 1))
                if d >= 100:
                    self.gc_long += 1
                    if len(self.gc_pending) == self.gc_pending.maxlen:
                        self.gc_events_dropped += 1                    # counted, never silent (CR-R12)
                    self.gc_pending.append({"generation": info.get("generation"), "start_ns": st[1],
                                            "end_ns": time.time_ns(), "duration_ms": round(d, 1),
                                            "collected": info.get("collected")})

    async def loopmon_task(self) -> None:
        """G3-F4: event-loop pause detector. Ticks every 100 ms; any oversleep is a loop pause (catches one long
        pause exactly, unlike sampling the processed boundary)."""
        while not self.stop_event.is_set():
            self.beats["loopmon"] = time.monotonic()
            t0 = time.monotonic()
            await asyncio.sleep(0.1)
            lag = int((time.monotonic() - t0 - 0.1) * 1000)
            self.looplag_max_ms = max(self.looplag_max_ms, lag); self.looplag_recent.append((now_ms(), lag))
            for t in self.looplag_counts:
                if lag >= t:
                    self.looplag_counts[t] += 1
            self._drain_gc_events()

    def _drain_gc_events(self) -> None:
        while self.gc_pending:                                      # CR-R12: no lifetime cap, bounded memory
            self.lifecycle("gc_pause", self.gc_pending.popleft()); self._gc_reported += 1

    def instrumentation(self) -> dict:
        m = now_ms()
        return {"sampler_lateness_max_ms": self.lat_max_ms,
                "sampler_lateness_max_60s_ms": max((l for t, l in self.lat_recent if m - t <= 60_000), default=0),
                "sampler_lateness_counts_ge": {str(k): v for k, v in self.lat_counts.items()},
                "loop_lag_max_ms": self.looplag_max_ms,
                "loop_lag_max_60s_ms": max((l for t, l in self.looplag_recent if m - t <= 60_000), default=0),
                "loop_lag_counts_ge": {str(k): v for k, v in self.looplag_counts.items()},
                "gc_pause_max_ms": self.gc_pause_max_ms, "gc_pauses_ge_100ms": self.gc_long,
                "gc_pause_events_reported": self._gc_reported, "gc_pause_events_dropped": self.gc_events_dropped}

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
            if status == 200 and data == []:                        # B2: no candle at all for that window
                first = await self._first_candle_open(sym, tf, deadline_mono)
                if first is not None and first > open_ms:
                    self.simple_gap(f"candle|{tf}|{sym}", open_ms, open_ms, TF_MS[tf], "candle_not_listed_yet",
                                    RECOVERABLE, {"first_open_ms": first})
                else:
                    self.stats["rejected"]["candle_unexpected"] += 1
                    self.simple_gap(f"candle|{tf}|{sym}", open_ms, open_ms, TF_MS[tf], "candle_unexpected_response",
                                    RECOVERABLE, {"first_open_ms": first})
                return
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

    async def _first_candle_open(self, sym: str, tf: str, deadline_mono: float):
        """Open time of the symbol's first-ever candle (klines from startTime=0, limit 1), retried like the job
        itself until its deadline (budget deferrals during the catch-up round are expected), else None."""
        while not self.stop_event.is_set():
            status, data, *_ = await self.rest.get("/api/v3/klines", {"symbol": sym, "interval": tf, "startTime": 0, "limit": 1})
            if status == 200:
                return int(data[0][0]) if isinstance(data, list) and data and isinstance(data[0], list) else None
            if time.monotonic() >= deadline_mono:
                return None
            await self._sleep(2 + random.random() * 3)
        return None

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
        """Disk guard. CR-B02: dataset size = closed days (day-close records) + open days + non-raw directories,
        measured in a worker thread (never a full historical walk, never on the event loop)."""
        loop = asyncio.get_running_loop()
        while not self.stop_event.is_set():
            self.beats["disk"] = time.monotonic()
            free = shutil.disk_usage(self.base).free
            size = await loop.run_in_executor(None, dataset_bytes, self.base, self.closed_bytes)
            self.beats["disk"] = time.monotonic()
            self.disk_free_gb, self.dir_gb = free / 1e9, size / 1e9
            st = self.disk.state(free, size)
            if st != self.disk_state:
                self.lifecycle("disk_state", {"state": st, "free_gb": round(self.disk_free_gb, 2), "dir_gb": round(self.dir_gb, 4)})
            self.disk_state = st
            if st == "HARD_STOP" and not self.writer.stop_writes.is_set():
                self.disk_hard_stop()
            if self.continuous:
                if st == "WARN":
                    self.incidents.raise_("disk_warning", "WARNING", {"free_gb": round(self.disk_free_gb, 2),
                                                                      "dataset_gb": round(self.dir_gb, 3)}, latched=False)
                elif st == "OK":
                    self.incidents.resolve("disk_warning")
                if st == "HARD_STOP":                                  # free < floor OR total dataset >= cap
                    self.fail_closed("disk_hard_stop", {"free_gb": round(self.disk_free_gb, 2),
                                                        "dataset_gb": round(self.dir_gb, 3)})
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
        self._conn_incidents(m)
        if self.writer.ident is not None and not self.writer.is_alive() and not self.writer.finished:
            self.fatal("writer_thread_dead", EXIT_WRITER)
            return
        cert = self.writer.certifier                                   # G3-F3: certifier supervised separately
        if self.writer.is_alive() and cert.ident is not None and not cert.is_alive() and not self.stop_event.is_set():
            self.certifier_dead_ms.append(m)
            self.lifecycle("certifier_dead", {"fatal": cert.fatal, "restarts": self.writer.certifier_restarts})
            if self.writer.certifier_restarts >= 3:
                self.fatal("certifier_failed_repeatedly", EXIT_TASK)
                return
            self.writer.restart_certifier()
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
        if self.continuous and not self.stop_event.is_set():
            self._continuous_checks(m)

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
        for name, period in self.task_periods.items():             # 1. required tasks alive + beating
            b = self.beats.get(name)
            limit = max(2 * period, 3.0) + (30.0 if name in ("candles", "clock", "disk", "days") else 0.0)
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
        cs = self.writer.certifier.status()                           # G3-F3: certifier health, separate from writer
        if self.writer.is_alive() and not cs["alive"]:
            hard.append("certifier_dead")
        elif cs.get("beat_age_ms") is None:                         # G3-F4-D1: readiness = child heartbeat published
            st0 = getattr(self.writer.certifier, "start_mono", None)
            (startup if st0 is not None and time.monotonic() - st0 < self.cfg["certifier_ready_timeout_s"]
             else hard).append("certifier_not_ready")
        elif cs["beat_age_ms"] > self.cfg["certifier_beat_limit_ms"]:
            hard.append("certifier_stale")
        if cs.get("scan_error"):
            hard.append("certifier_scan_error")
        elif cs["pending"] > self.cfg["certify_max_pending"] or \
                cs["oldest_pending_age_ms"] > 1000 * self.cfg["certify_max_pending_age_s"]:
            hard.append("certifier_backlog")
        if cs["failures"] and not self.continuous:                  # continuous: a latched incident (Package G)
            hard.append("certification_failed")
        if [x for x in self.certifier_dead_ms if m - x <= 600_000]:
            hard.append("certifier_restarted_10min")
        if self.stats["write_errors"] and not self.continuous:
            hard.append("write_errors")
        if sum(self.stats["writer_rejected"].values()) and not self.continuous:
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
            if t.kind == "book" and t.tier != 0 and age is not None and age > self.cfg["book_stale_suspect_ms"]:
                warn.append(f"stale_suspect:{t.name}")
            fresh = age is not None and age <= t.stale_ms          # G3-F1: every stream has a hard freshness bound
            live = self.conn_up_at(t.conn, m) and self.data_live_at(t.conn, m)
            up = self.last_up(t.conn, m)
            if up is not None and (last is None or last < up):          # B1: no own data since the (re)connect
                hard.append(f"awaiting_post_reconnect:{t.name}")
                continue
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
                                                            "not_ready", "awaiting_post_reconnect:")) for r in hard + startup):
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
        if not self.continuous:                                     # bounded: unchanged lifetime-sticky reasons
            if self.stats.get("seq_reset"):
                hard.append("seq_reset")
            if self.stats["segments_quarantined"]:
                hard.append("segments_quarantined")
            if sum(self.stats["emit_failed"].values()):
                hard.append("emit_failed")
        else:                                                       # continuous: one reason per active incident
            for inc in self.incidents.active():
                (hard if inc["severity"] in ("DEGRADED", "CRITICAL") else warn).append(f"incident:{inc['key']}")
            if self.rate.events.get("http_429"):
                warn.append(f"http_429_24h:{len(self.fc_times['http_429'])}")
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
                    "data_live": self.data_live_at(c.name, m), "msgs_per_s": self.activity[c.name].rate(m),
                    "gen": getattr(c, "gen", None), "recovering": bool(getattr(c, "recovering", False)),
                    "stale_dropped": getattr(c, "stale_dropped", 0), "wedged": bool(getattr(c, "wedged", False)),
                    "last_recovery": (list(getattr(c, "recoveries", []) or [])[-1:] or [None])[0],
                    "outage_ms": (m - self.conn_outage[c.name]["start"]) if c.name in self.conn_outage else None}
                   for c in self.conns],
            "streams": {t.name: {"state": t.state(), "sub": t.sub, "ready_ms": t.ready_ms,
                                 "freshness": self.freshness(t, m), "stale_ms": t.stale_ms,
                                 "last_msg_age_ms": None if t.last_recv_ms() is None else m - t.last_recv_ms(),
                                 "gap_open": None if t.gap is None else {"first": t.gap["first"], "n": t.gap["n"],
                                                                         "cause": t.gap["cause"]}}
                        for t in self.all_tracks()},
            "tasks": {k: round(time.monotonic() - v, 1) for k, v in sorted(self.beats.items())},
            "task_failures": {k: len(v) for k, v in self.task_failures.items()},
            "writer": self.writer.status(), "certifier": self.writer.certifier.status(),
            "instrumentation": self.instrumentation(),
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
                     "ip_used_weight_1m_seen": self.rate.observed, "ip_used_weight_1m_max": self.rate.observed_max,
                     "events": dict(self.rate.events),
                     "total_weight": self.rest.weight_used_total if self.rest else 0},
            "clock": {"state": self.clock.state, "skew_ms": self.clock.last_skew_ms,
                      "uncertainty_ms": self.clock.uncertainty_ms, "age_s": self.clock.age_s(), "method": C.CLOCK_METHOD},
            "disk": {"state": self.disk_state, "free_gb": self.disk_free_gb, "collector_dir_gb": self.dir_gb,
                     "marker": self.disk_marker},
            "rotation": self.rotation,
            **(self._continuous_health(m) if self.continuous else {}),
        }

    def _continuous_health(self, m: int) -> dict:
        ages = {}
        for c in self.conns:
            a = self.activity.get(c.name)
            up = a.last_up_since(m) if a else None
            ages[c.name] = None if up is None else round((m - up) / 1000)
        return {"mode": "continuous", "dataset_id": self.cfg["dataset_id"], "calendar": cal.params(),
                "incidents": self.incidents.summary(),
                "universe_epoch": {"universe_id": (self.universe_meta or {}).get("universe_id"),
                                   "effective_from_ms": self.epoch_start_ms, "transitions": self.transitions,
                                   "pending_effective_ms": (self.pending_transition or {}).get("T"),
                                   "next_refresh_ms": self.universe_next_ms, "refresh_degraded": self.universe_degraded},
                "connection_age_s": ages, "rotation_after_s": self.cfg["ws_rotation_s"],
                "day_close": dict(self.day_close), "process_check": self.proc_state,
                "fail_closed_windows_24h": {k: len(v) for k, v in self.fc_times.items()},
                "previous_run": (self.previous_run or {}).get("boot_id")}

    def counters(self) -> dict:
        st = self.stats
        return {"dropped": dict(st["dropped"]), "malformed": st["malformed"], "unknown_stream": st["unknown_stream"],
                "unknown_event": st["unknown_event"], "handler_errors": st["handler_errors"],
                "seq_regression": st["rejected"].get("seq_regression", 0), "seq_reset": st.get("seq_reset", 0),
                **({"seq_stale": st.get("seq_stale", 0), "seq_reset_causes": dict(st.get("seq_reset_causes", {})),
                    "seq_catchups": st.get("seq_catchups", 0), "seq_catchup_max_ms": st.get("seq_catchup_max_ms", 0),
                    "handoffs": st.get("handoffs", 0), "handoff_classes": dict(st.get("handoff_classes", {})),
                    "market_component_stale": self.market.stale_components if self.market else 0}
                   if self.continuous else {}),
                "rejected": dict(st["rejected"]), "emit_failed": dict(st["emit_failed"]),
                "writer_rejected": dict(st["writer_rejected"]), "write_errors": st["write_errors"],
                "segments_quarantined": st["segments_quarantined"], "duplicates_dropped": st["duplicates_dropped"],
                "recv_clock_regression": st.get("recv_clock_regression", 0), "wall_clock_steps": st.get("wall_clock_steps", 0),
                "task_failures": st.get("task_failed_total", 0),
                "data_stall_reconnects": st.get("data_stall_reconnects", 0),
                "subscribe_failed": st.get("subscribe_failed", 0), "subscribe_timeout": st.get("subscribe_timeout", 0),
                "never_ready": st.get("never_ready", 0), "clock_probe_failures": st.get("clock_probe_failures", 0),
                "market_component_expired": st.get("market_component_expired", 0), "gaps": self.gap_count,
                "catchup_boundaries": self.catchup_boundaries,
                "certification_failures": st.get("certification_failures", 0),
                "certifier_restarts": self.writer.certifier_restarts,
                "writer_max_beat_gap_ms": self.writer.max_beat_gap_ms,
                "writer_max_durable_lag_ms": self.writer.max_durable_lag_ms,
                "certify_max_ms": st.get("certify_max_ms"), "segments_finalized": st.get("segments_finalized", 0),
                "instrumentation": self.instrumentation()}

    def freshness(self, t, m: int) -> str:
        """G3-F1 vocabulary: fresh (age <= cadence) | aging (cadence < age <= threshold) | stale (> threshold) |
        disconnected | reconnecting (connected, no data since the connect) | not_ready."""
        last = t.last_recv_ms()
        if last is None:
            return "not_ready"
        if not self.conn_up_at(t.conn, m):
            return "disconnected"
        up = self.last_up(t.conn, m)
        if up is not None and last < up:
            return "reconnecting"
        age = m - last
        return "fresh" if age <= t.cadence else ("aging" if age <= t.stale_ms else "stale")

    def health_record(self, h: dict) -> None:
        """R02: compact historical health raw record (state at time T is reconstructable from raw data)."""
        compact = {k: h[k] for k in ("state", "reasons", "startup_reasons", "warnings", "uptime_s", "tasks", "task_failures",
                                     "queue_depth", "queue_peak", "loop_lag_ms", "catchup_boundaries", "last_sampled_ms",
                                     "dropped", "rejected", "malformed", "unknown_stream", "unknown_event",
                                     "handler_errors", "write_errors", "gaps_open", "gaps_closed_total", "clock", "disk")}
        compact["writer"] = {k: h["writer"][k] for k in ("alive", "beat_age_ms", "durable_lag_ms", "write_errors", "fatal",
                                                         "max_beat_gap_ms", "max_durable_lag_ms")}
        compact["certifier"] = h["certifier"]
        compact["instrumentation"] = h["instrumentation"]
        compact["ws"] = [{k: c[k] for k in ("conn", "connected", "reconnects", "data_live", "msgs_per_s")} for c in h["ws"]]
        by_state = collections.Counter(s["state"] for s in h["streams"].values())
        compact["streams_by_state"] = dict(by_state)
        compact["streams_not_observing"] = {n: s for n, s in sorted(h["streams"].items()) if s["state"] != OBSERVING}
        compact["streams_by_freshness"] = dict(collections.Counter(s["freshness"] for s in h["streams"].values()))
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
            if self.incidents is not None:
                self.incidents.poll_acks()
                self.incidents.poll_external()
                self.incidents.flush()
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
        if self.continuous:
            self.previous_run = self._previous_run()
        self.writer.start()
        timeout = aiohttp.ClientTimeout(total=30)
        sess = self.session_factory() if self.session_factory else \
            aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "tsb-p2-forward/" + C.VERSION})
        async with sess as self.session:
            self.rest = RestClient(self.session, self.rate, self.stats)
            gc.callbacks.append(self._gc_cb)
            if not await self.establish_universe():                  # F25: fail closed, graceful stop
                return await self._startup_failed(rec_gaps)
            self.run_record, rel, self.run_record_sha = P.write_run_record(self)
            self.writer.run_record = rel
            if hasattr(self.writer.certifier, "set_run_record"):      # G3-F4 review A1: before any rotation
                self.writer.certifier.set_run_record()
            self.lifecycle("start", {"config_hash": self.config_hash, "profile": self.cfg["profile"],
                                     "max_runtime_s": self.cfg["max_runtime_s"], "recovered": rec_gaps,
                                     "run_record_file": rel, "run_record_sha256": self.run_record_sha,
                                     "run_record": self.run_record,
                                     **({"mode": "continuous", "dataset_id": self.cfg["dataset_id"],
                                         "previous_run": self.previous_run} if self.continuous else {})})
            for g in rec_gaps:                                       # CR-R07: never a gap from 1970
                if g["last_salvaged_recv_ns"] is not None:
                    a = g["last_salvaged_recv_ns"] // 1_000_000
                else:
                    a = g.get("segment_start_ms") or self.started_ms
                self.simple_gap(f"crash|{g['type']}", a, self.started_ms, 0, "crash_recovery", IRREPLACEABLE,
                                {"salvaged": g["salvaged"], "source": g["source"],
                                 "start_basis": "last_salvaged_record" if g["last_salvaged_recv_ns"] is not None
                                 else "segment_hour_start"})
            self.state = "RUNNING"
            await self.start_ws()
            if self.continuous:
                self.epoch_start_ms = self.ws_start_ms
                self._record_downtime()
            named = [("sampler", self.sampler_task), ("candles", self.candle_task), ("clock", self.clock_task),
                     ("disk", self.disk_task), ("health", self.health_task), ("watchdog", self.watchdog_task),
                     ("loopmon", self.loopmon_task)]
            if self.continuous:
                named += [("days", self.days_task), ("rotation", self.rotation_task), ("procwatch", self.procwatch_task)]
                if self.cfg["profile"] != "tier0_only":
                    named.append(("universe", self.universe_task))
                else:
                    self.task_periods.pop("universe", None)
            tasks = [asyncio.create_task(self.supervise(n, f), name=n) for n, f in named]
            tasks.append(asyncio.create_task(self.rotation_test_task(), name="rotation_test"))
            tasks.append(asyncio.create_task(self.reconnect_test_task(), name="reconnect_test"))
            try:                                                     # continuous: no hidden runtime limit
                await asyncio.wait_for(self.stop_event.wait(),
                                       timeout=None if self.continuous else self.cfg["max_runtime_s"])
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
        self._stop_snapshot = (self.stats["certification_failures"], self.stats["segments_quarantined"])
        self.writer.stop(); self.writer.join(timeout=self.writer_join_timeout_s)
        self.finalize_stop()
        self.write_health(record=False)
        partials = [f for _, _, fs in os.walk(os.path.join(self.base, "raw")) for f in fs
                    if f.endswith((".partial", ".pending", ".certifying"))]
        if self.incidents is not None:
            self.incidents.flush()
        self.write_marker(f"stop-{self.boot_id[:8]}.json",                        # N1: final state outside the writer
                          {"event": "final_stop_state", "boot_id": self.boot_id, "ts_ms": now_ms(), "state": self.state,
                           "exit_code": self.exit_code, "reason": self.stop_reason,
                           "writer_finished": self.writer.finished, "writer_alive": self.writer.is_alive(),
                           "partials": len(partials), "counters": self.counters(),
                           "mode": self.cfg["mode"], "ws_start_ms": self.ws_start_ms,
                           "stop_requested_ms": stop_requested_ms, "last_boundary_ms": self.last_sampled_ms})
        return self.exit_code

    def _previous_run(self):
        """CR-R07: the most recent earlier run of this dataset (run records are written once per start)."""
        d = os.path.join(self.base, "runs")
        best = None
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not (f.startswith("run-") and f.endswith(".json")):
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    r = json.load(fh)
                key = (r["created_ms"], r["boot_id"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if r["boot_id"] != self.boot_id and (best is None or key > best[0]):
                best = (key, f, r["boot_id"])
        if best is None:
            return None
        boot = best[2]
        mp = os.path.join(self.base, "control", f"stop-{boot[:8]}.json")
        marker = None
        try:
            with open(mp, encoding="utf-8") as fh:
                marker = json.load(fh)
        except (OSError, ValueError):
            pass
        clean = marker is not None and marker.get("boot_id") == boot
        return {"boot_id": boot, "run_record_file": f"runs/{best[1]}", "created_ms": best[0][0],
                "stop_marker": os.path.relpath(mp, self.base) if clean else None, "clean_stop": clean,
                "state": (marker or {}).get("state") if clean else None,
                "exit_code": (marker or {}).get("exit_code") if clean else None,
                "reason": (marker or {}).get("reason") if clean else None,
                "ws_start_ms": (marker or {}).get("ws_start_ms") if clean else None,
                "stop_requested_ms": (marker or {}).get("stop_requested_ms") if clean else None,
                "last_boundary_ms": (marker or {}).get("last_boundary_ms") if clean else None}

    def _record_downtime(self) -> None:
        """CR-R07: the time between the previous run and this run's ws_start is explicit downtime, never stitched.
        Immutable runs/downtime-<boot>.json + lifecycle record. A crashed predecessor has no stop marker: its end is
        unknown to this run and is derived per stream by the verifier from the data actually on disk."""
        prev = self.previous_run
        cause = "first_run" if prev is None else ("clean_stop" if prev["clean_stop"] and prev["state"] == "STOPPED"
                                                  else "stopped_" + str(prev["state"]).lower() if prev["clean_stop"]
                                                  else "crash_or_kill")
        rec = {"record": "tsb.p2.forward.downtime", "record_version": 1, "dataset_id": self.cfg["dataset_id"],
               "boot_id": self.boot_id, "run_record_file": self.writer.run_record, "previous_run": prev, "cause": cause,
               "from_ms": (prev or {}).get("stop_requested_ms"), "until_ms": self.ws_start_ms,
               "calendar": cal.params()}
        d = os.path.join(self.base, "runs")
        P._atomic_ro(os.path.join(d, f"downtime-{self.boot_id}.json"),
                     (json.dumps(rec, sort_keys=True, indent=1) + "\n").encode("utf-8"))
        self.lifecycle("downtime", rec)
        if prev is not None and cause != "clean_stop":
            self.incidents.raise_(f"previous_run_{cause}", "WARNING" if prev["clean_stop"] else "DEGRADED",
                                  {"previous_boot": prev["boot_id"], "state": prev["state"]})

    writer_join_timeout_s = 420

    async def _startup_failed(self, rec_gaps) -> int:
        """F25: no trustworthy initial universe => durable reason, FAILED, graceful writer stop, exit 5."""
        self.run_record, rel, self.run_record_sha = P.write_run_record(self)
        self.writer.run_record = rel
        if hasattr(self.writer.certifier, "set_run_record"):
            self.writer.certifier.set_run_record()
        self.lifecycle("start", {"config_hash": self.config_hash, "profile": self.cfg["profile"],
                                 "max_runtime_s": self.cfg["max_runtime_s"], "recovered": rec_gaps,
                                 "run_record_file": rel, "run_record_sha256": self.run_record_sha,
                                 "run_record": self.run_record, "startup_failed": True})
        self.lifecycle("startup_failed", {"reason": "universe_unavailable", "problems": self.startup_failure[:20],
                                          "signal_received": self.stop_reason == "signal"})
        self.stop_reason = None                                       # m1: always FAILED / exit 5, even after SIGTERM
        self.fatal("startup_failed:universe_unavailable", EXIT_STARTUP)
        self.write_health(record=True)
        self.lifecycle("stop", {"reason": self.stop_reason, "stop_requested_ms": now_ms(), "last_boundary_ms": None,
                                "ws_start_ms": None, "uptime_s": round(time.monotonic() - self.started_mono, 1),
                                "counters": self.counters()})
        self._stop_snapshot = (self.stats["certification_failures"], self.stats["segments_quarantined"])
        self.writer.stop(); self.writer.join(timeout=self.writer_join_timeout_s)
        self.finalize_stop()
        self.write_health(record=False)
        if self.incidents is not None:
            self.incidents.raise_("startup_failed", "CRITICAL", {"problems": (self.startup_failure or [])[:10]})
            self.incidents.flush()
        self.write_marker(f"stop-{self.boot_id[:8]}.json",
                          {"event": "final_stop_state", "boot_id": self.boot_id, "ts_ms": now_ms(), "state": self.state,
                           "exit_code": self.exit_code, "reason": self.stop_reason, "writer_finished": self.writer.finished,
                           "writer_alive": self.writer.is_alive(), "partials": 0, "counters": self.counters(),
                           "mode": self.cfg["mode"], "ws_start_ms": None, "stop_requested_ms": None,
                           "last_boundary_ms": None})
        return self.exit_code

    def finalize_stop(self) -> str:
        """F51: STOPPED only if the writer thread finished cleanly and no .partial remains; else STOPPED_INCOMPLETE."""
        partials = [f for _, _, fs in os.walk(os.path.join(self.base, "raw")) for f in fs
                    if f.endswith((".partial", ".pending", ".certifying"))]          # G3-F3: uncertified = incomplete
        snap = getattr(self, "_stop_snapshot", None)
        no_new_failures = snap is None or snap == (self.stats["certification_failures"], self.stats["segments_quarantined"])
        complete = (not self.writer.is_alive()) and self.writer.finished and self.writer.certified_all is True \
            and self.writer.fatal is None and no_new_failures and not partials                     # F6
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
    try:
        col = Collector(cfg)
    except StartupRefused as e:                                       # nothing written; visible; operator action
        print(json.dumps({"p2f_alert": {"startup_refused": str(e)[:500]}}), file=sys.stderr, flush=True)
        return EXIT_STARTUP
    return asyncio.run(col.run())
