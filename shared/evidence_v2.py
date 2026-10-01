"""Evidence recorder v2 — point-in-time decision events (P1 forward instrumentation).

Extends the v1 flight recorder (research/null_a/recorder.py, which stays byte-identical
and keeps writing its own files) with:

* deterministic identities: candle_id, candidate_id and an idempotency key per event;
* process lineage on every event: strategy_version, code_sha, config_hash, build_revision,
  boot_id and a per-process sequence number (a gap in seq = a lost event);
* decision-state-change emission: a repeated identical evaluation is suppressed and counted;
* multi-service use: it lives in shared/, which every image ships;
* persistence off the event loop (files are written from a worker thread);
* exposed health: errors, dropped events, queue depth and the last successful flush.

Contract for every public function: O(1) on the hot path, never raises into the caller,
never mutates its inputs (events are serialized at emit time, so later mutation of a
caller's dict cannot rewrite history). With EVIDENCE_V2_ENABLED=false it is a no-op.
"""
from __future__ import annotations

import asyncio
import dataclasses
import datetime as _dt
import hashlib
import itertools
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import OrderedDict, deque
from typing import Any

logger = logging.getLogger("evidence_v2")

SCHEMA = "tsb.evidence"
SCHEMA_VERSION = 2
_EXCLUDED_CODE_DIRS = {"__pycache__", ".git", "logs", "models", "data", "tests", ".venv", "venv"}
# Config fields that must never enter a hash or an event (secrets and connection details),
# plus fields that describe the process or the recorder rather than the strategy.
_SECRET_NAME_RE = re.compile(
    r"(KEY|SECRET|TOKEN|PASS|PWD|DSN|URL|URI|HOST|USER|CHAT|WEBHOOK|COOKIE|AUTH|_ID$|^ID$)", re.I)
_PROCESS_LOCAL = {"SERVICE_NAME", "HEALTH_MAX_AGE_SECONDS"}


# ------------------------------------------------------------------ canonical helpers ------
def _json_default(o: Any):
    if isinstance(o, _dt.datetime):
        if o.tzinfo is None:
            o = o.replace(tzinfo=_dt.timezone.utc)
        return o.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(o, _dt.date):
        return o.isoformat()
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    if isinstance(o, bytes):
        return o.hex()
    item = getattr(o, "item", None)          # numpy scalars
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return str(o)


def canonical_json(obj: Any) -> str:
    """Stable serialization (sorted keys, no whitespace) used for hashing and for records."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default,
                      ensure_ascii=False, allow_nan=True)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_ms() -> int:
    return int(time.time() * 1000)


def to_ms(value: Any) -> int | None:
    """UTC epoch milliseconds from a datetime (naive = UTC), epoch ms int, or None."""
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_dt.timezone.utc)
        return int(value.timestamp() * 1000)
    return int(value)


def ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return (_dt.datetime.fromtimestamp(ms / 1000, _dt.timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


# ------------------------------------------------------------------ identities -------------
def candle_id(symbol: str | None, timeframe: str | None, candle_open_time_ms: int | None) -> str | None:
    """Exchange-native candle identity: SYMBOL|timeframe|open-time (Binance kline open, UTC ms)."""
    if not symbol or not timeframe or candle_open_time_ms is None:
        return None
    return f"{symbol}|{timeframe}|{int(candle_open_time_ms)}"


def candidate_id(candle: str | None, trade_type: str | None, strategy_version: str | None) -> str | None:
    """Deterministic candidate identity: one setup type on one closed candle under one strategy
    version. Re-analysing the same candle yields the same id; a new candle yields a new one."""
    if candle is None:
        return None
    return "cand_" + sha256_hex(f"candidate|v1|{candle}|{trade_type or '-'}|{strategy_version or '-'}")[:24]


def event_id(service: str, event_type: str, subject: Any, discriminator: Any) -> str:
    """Idempotency key. The same logical fact always maps to the same id."""
    return "evt_" + sha256_hex(canonical_json(
        [SCHEMA, SCHEMA_VERSION, service, event_type, subject, discriminator]))[:32]


_CODE_SHA_CACHE: dict[str, str] = {}


def compute_code_sha(root: str | None = None) -> str:
    """Content digest of the Python code the process runs (relative path + file digest of every
    *.py under the application root, excluding mounted data/log/model directories and tests).
    Independent of build arguments, so it also identifies single-file overlays."""
    root = os.path.abspath(root or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cached = _CODE_SHA_CACHE.get(root)
    if cached:
        return cached
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _EXCLUDED_CODE_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
            except OSError:
                digest = "unreadable"
            h.update(os.path.relpath(path, root).replace(os.sep, "/").encode())
            h.update(b"\0" + digest.encode() + b"\n")
    _CODE_SHA_CACHE[root] = h.hexdigest()
    return _CODE_SHA_CACHE[root]


def strategy_config_snapshot(cfg: Any) -> dict:
    """Non-secret configuration that can change decisions. Secret-looking names, per-process
    fields and recorder settings are excluded, so enabling the recorder never moves the hash."""
    if dataclasses.is_dataclass(cfg):
        names = [f.name for f in dataclasses.fields(cfg)]
    else:
        names = [n for n in vars(cfg) if n.isupper()]
    out = {}
    for name in sorted(names):
        if (_SECRET_NAME_RE.search(name) or name in _PROCESS_LOCAL
                or name.startswith("EVIDENCE") or name == "ENABLE_EVIDENCE_RECORDER"):
            continue
        out[name] = getattr(cfg, name, None)
    return out


def compute_config_hash(cfg: Any) -> str:
    return sha256_hex(canonical_json(strategy_config_snapshot(cfg)))


def process_identity(cfg: Any, root: str | None = None) -> dict:
    """Lineage fields stamped on every event of this process."""
    return {
        "strategy_version": getattr(cfg, "APP_VERSION", None),
        "code_sha": compute_code_sha(root),
        "config_hash": compute_config_hash(cfg),
        "build_revision": os.getenv("BUILD_REVISION", "unknown"),
        "phase_id": getattr(cfg, "EVIDENCE_PHASE_ID", "") or None,
    }


# ------------------------------------------------------------------ sinks ------------------
class JsonlDailySink:
    """Append-only JSON Lines, one directory per service and one file per UTC day:
    <directory>/<service>/events-YYYY-MM-DD.jsonl. Called only from the flusher thread.
    One process writes one service directory, so there is a single writer per file."""

    def __init__(self, directory: str, service: str, fsync: bool = True):
        self.directory = os.path.join(os.path.abspath(directory), service)
        self.fsync = fsync

    def write(self, batch: list) -> None:
        os.makedirs(self.directory, exist_ok=True)
        by_day: dict[str, list[str]] = {}
        for day, line in batch:
            by_day.setdefault(day, []).append(line)
        for day, lines in by_day.items():
            path = os.path.join(self.directory, f"events-{day}.jsonl")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("".join(line + "\n" for line in lines))
                fh.flush()
                if self.fsync:
                    os.fsync(fh.fileno())

    def write_stats(self, stats: dict) -> None:
        os.makedirs(self.directory, exist_ok=True)
        path = os.path.join(self.directory, "_recorder_stats.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(canonical_json(stats))
        os.replace(tmp, path)


class ListSink:
    """In-memory sink for tests."""

    def __init__(self):
        self.lines: list[str] = []
        self.stats: dict | None = None

    def write(self, batch: list) -> None:
        self.lines.extend(line for _, line in batch)

    def write_stats(self, stats: dict) -> None:
        self.stats = stats

    def records(self) -> list[dict]:
        return [json.loads(line) for line in self.lines]


# ------------------------------------------------------------------ recorder ---------------
class RecorderV2:
    def __init__(self, service: str, sink, identity: dict | None = None, *, enabled: bool = True,
                 max_queue: int = 10000, batch_size: int = 500, flush_interval_s: float = 2.0,
                 flush_retry_count: int = 3, flush_backoff_ms: float = 100.0,
                 state_cache_size: int = 50000, stats_interval_s: float = 600.0, clock_ms=now_ms):
        self.service = service
        self.sink = sink
        self.enabled = enabled
        self.identity = dict(identity or {})
        self.max_queue = max(1, int(max_queue))
        self.batch_size = max(1, int(batch_size))
        self.flush_interval_s = flush_interval_s
        self.flush_retry_count = max(0, int(flush_retry_count))
        self.flush_backoff_ms = flush_backoff_ms
        self.state_cache_size = max(1, int(state_cache_size))
        self.stats_interval_s = stats_interval_s
        self._clock_ms = clock_ms
        self.boot_id = secrets.token_hex(6)
        self.started_at_ms = clock_ms()
        self._seq = 0
        self._q: deque = deque()
        self._qlock = threading.Lock()          # the flusher thread and the loop share the queue
        self._state: OrderedDict = OrderedDict()
        self._lat = [0.0] * 4096                 # ring buffer; slicing is atomic under the GIL
        self._lat_n = 0
        self.emitted = self.suppressed = self.dropped = 0
        self.errors = self.hook_errors = self.flush_failures = self.flushed = 0
        self.state_evictions = 0
        self.max_depth_seen = 0
        self.last_flush_ok_ms: int | None = None
        self.last_error: str | None = None
        self.last_error_ms: int | None = None
        self._last_stats_event_ms = 0
        self._flush_lock: asyncio.Lock | None = None

    # ---- hot path -------------------------------------------------------------------------
    def emit(self, event_type: str, subject: dict, payload: dict | None = None, *,
             state: Any = None, dedup_key: str | None = None, event_time_ms: int | None = None,
             transition: bool = False) -> bool:
        """Queue one event. Returns True if queued. Never raises.

        dedup_key/state: the event is emitted only when `state` differs from the last state
        recorded for `dedup_key` (a decision-state change); identical repeats are counted in
        `suppressed`. transition=True marks stream events whose same state may legitimately
        recur later; their idempotency key includes the event time."""
        if not self.enabled:
            return False
        t0 = time.perf_counter()
        try:
            restated = False
            digest = None
            if dedup_key is not None:
                digest = sha256_hex(canonical_json(state))[:20]
                prev = self._state.get(dedup_key)
                if prev == digest:
                    self.suppressed += 1
                    return False
                restated = prev is None
                # P1-FIX (MINOR-2): the dedup state is committed only AFTER the queue has
                # accepted the record (below). A dropped or unserializable event is not marked
                # as seen, so a later identical emit can still record it (one attempt per call;
                # no internal retry loop, never blocks).
            with self._qlock:
                self._seq += 1                 # a dropped event still consumes a number: gaps = loss
                seq = self._seq
                if len(self._q) >= self.max_queue:
                    self.dropped += 1
                    return False
            recorded = self._clock_ms()
            etime = int(event_time_ms) if event_time_ms is not None else recorded
            discriminator = [state, etime] if transition else state
            record = {
                "schema": SCHEMA, "schema_version": SCHEMA_VERSION,
                "event_id": event_id(self.service, event_type, subject, discriminator),
                "event_type": event_type, "service": self.service,
                "boot_id": self.boot_id, "seq": seq,
                "event_time_ms": etime, "recorded_at_ms": recorded,
                "restated": restated,
                **self.identity,
                "subject": subject, "state": state, "payload": payload or {},
            }
            line = canonical_json(record)       # frozen now: later caller mutations cannot leak in
            day = _dt.datetime.fromtimestamp(recorded / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")
            with self._qlock:
                if len(self._q) >= self.max_queue:   # filled up while serializing: drop, not seen
                    self.dropped += 1
                    return False
                self._q.append((day, line))
                self.emitted += 1
                if len(self._q) > self.max_depth_seen:
                    self.max_depth_seen = len(self._q)
            if dedup_key is not None:                # accepted: now it counts as seen
                self._state[dedup_key] = digest
                self._state.move_to_end(dedup_key)
                if len(self._state) > self.state_cache_size:
                    self._state.popitem(last=False)
                    self.state_evictions += 1
            return True
        except Exception as exc:                # serialization or internal failure
            self.errors += 1
            self._note_error(exc)
            return False
        finally:
            self._lat[self._lat_n % 4096] = (time.perf_counter() - t0) * 1000.0
            self._lat_n += 1

    def note_hook_error(self, exc: BaseException) -> None:
        """A caller-side hook failed while building an event (counted, never raised)."""
        try:
            self.hook_errors += 1
            self._note_error(exc)
        except Exception:
            pass

    def _note_error(self, exc: BaseException) -> None:
        self.last_error = f"{type(exc).__name__}: {exc}"[:300]
        self.last_error_ms = self._clock_ms()
        try:
            logger.warning("evidence_v2 [%s] %s", self.service, self.last_error)
        except Exception:
            pass

    # ---- flushing (off the hot path) ---------------------------------------------------------
    def _peek_batch(self) -> list:
        with self._qlock:
            n = min(self.batch_size, len(self._q))
            return list(itertools.islice(self._q, 0, n))

    def _write_with_retry(self, batch: list) -> bool:
        for attempt in range(self.flush_retry_count + 1):
            try:
                self.sink.write(batch)
                return True
            except Exception as exc:
                self.flush_failures += 1
                self._note_error(exc)
                if attempt < self.flush_retry_count:
                    time.sleep(self.flush_backoff_ms * (2 ** attempt) / 1000.0)
        return False

    def _commit_batch(self, n: int) -> None:
        # Only the (single, locked) flusher removes from the left; emit only appends on the
        # right, so the first n entries are exactly the batch that was written.
        with self._qlock:
            for _ in range(n):
                self._q.popleft()
        self.flushed += n
        self.last_flush_ok_ms = self._clock_ms()

    def _write_batch_sync(self) -> int:
        batch = self._peek_batch()
        if not batch or not self._write_with_retry(batch):
            return 0                            # failed batches stay queued (bounded by max_queue)
        self._commit_batch(len(batch))
        return len(batch)

    def flush_now(self) -> int:
        """Synchronous drain (tests, shutdown). Failed batches stay queued. Never raises."""
        total = 0
        try:
            while self._q:
                n = self._write_batch_sync()
                if n == 0:
                    break
                total += n
        except Exception as exc:
            self._note_error(exc)
        return total

    async def flush_async(self) -> int:
        """Drain from a worker thread so file I/O and retry back-off never block the loop."""
        if self._flush_lock is None:
            self._flush_lock = asyncio.Lock()
        total = 0
        async with self._flush_lock:
            while True:
                batch = self._peek_batch()
                if not batch:
                    break
                if not await asyncio.to_thread(self._write_with_retry, batch):
                    break
                self._commit_batch(len(batch))
                total += len(batch)
        return total

    def maybe_emit_stats(self) -> None:
        now = self._clock_ms()
        if now - self._last_stats_event_ms >= self.stats_interval_s * 1000:
            self._last_stats_event_ms = now
            self.emit("recorder.stats", {"service": self.service}, self.stats(), transition=True,
                      state={"boot_id": self.boot_id}, event_time_ms=now)

    def _write_stats_file(self, stats: dict | None = None) -> None:
        writer = getattr(self.sink, "write_stats", None)
        if writer:
            writer(stats if stats is not None else self.stats())

    async def run_flusher(self) -> None:
        """Background task: flush every interval, publish stats. Buries all errors."""
        while True:
            try:
                await asyncio.sleep(self.flush_interval_s)
                self.maybe_emit_stats()
                await self.flush_async()
                await asyncio.to_thread(self._write_stats_file, self.stats())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._note_error(exc)

    def shutdown(self, timeout_ms: float = 2000.0) -> int:
        """Bounded synchronous drain; returns the number of events still pending."""
        deadline = time.monotonic() + timeout_ms / 1000.0
        try:
            self.emit("recorder.stopping", {"service": self.service}, self.stats(), transition=True,
                      state={"boot_id": self.boot_id})
            while self._q and time.monotonic() < deadline:
                if self._write_batch_sync() == 0:
                    break
            self._write_stats_file()
        except Exception as exc:
            self._note_error(exc)
        return len(self._q)

    # ---- health ------------------------------------------------------------------------------
    def stats(self) -> dict:
        lat = sorted(self._lat[:min(self._lat_n, len(self._lat))])

        def pct(p):
            return round(lat[min(len(lat) - 1, int(p * len(lat)))], 4) if lat else 0.0
        return {
            "enabled": self.enabled, "service": self.service, "boot_id": self.boot_id,
            "seq": self._seq, "queue_depth": len(self._q), "max_queue": self.max_queue,
            "started_at": ms_to_iso(self.started_at_ms),
            "max_depth_seen": self.max_depth_seen, "emitted": self.emitted,
            "suppressed_repeats": self.suppressed, "dropped": self.dropped,
            "errors": self.errors, "hook_errors": self.hook_errors,
            "flush_failures": self.flush_failures, "flushed": self.flushed,
            "state_keys": len(self._state), "state_evictions": self.state_evictions,
            "last_flush_ok_at": ms_to_iso(self.last_flush_ok_ms),
            "last_error": self.last_error, "last_error_at": ms_to_iso(self.last_error_ms),
            "emit_latency_ms_p50": pct(0.50), "emit_latency_ms_p95": pct(0.95),
            "emit_latency_ms_p99": pct(0.99),
        }

    def health(self) -> dict:
        """Compact subset for service_heartbeats.metadata."""
        s = self.stats()
        return {k: s[k] for k in ("queue_depth", "dropped", "errors", "hook_errors",
                                  "flush_failures", "last_flush_ok_at", "last_error", "seq")}


# ------------------------------------------------------------------ process singleton ------
_RECORDERS: dict[str, RecorderV2] = {}
_INIT_ERRORS: dict[str, str] = {}


def _config():
    from shared.config import config
    return config


def enabled() -> bool:
    try:
        return bool(getattr(_config(), "EVIDENCE_V2_ENABLED", False))
    except Exception:
        return False


def get_recorder(service: str) -> RecorderV2 | None:
    """The process recorder for `service`, created lazily; None when disabled or unavailable."""
    if not enabled():
        return None
    rec = _RECORDERS.get(service)
    if rec is not None or service in _INIT_ERRORS:
        return rec
    try:
        cfg = _config()
        rec = RecorderV2(
            service, JsonlDailySink(cfg.EVIDENCE_V2_DIR, service, fsync=cfg.EVIDENCE_V2_FSYNC),
            process_identity(cfg), max_queue=cfg.EVIDENCE_V2_MAX_QUEUE,
            batch_size=cfg.EVIDENCE_V2_BATCH_SIZE, flush_interval_s=cfg.EVIDENCE_V2_FLUSH_INTERVAL_S,
            state_cache_size=cfg.EVIDENCE_V2_STATE_CACHE, stats_interval_s=cfg.EVIDENCE_V2_STATS_INTERVAL_S)
        rec.emit("recorder.started", {"service": service},
                 {"schema": SCHEMA, "schema_version": SCHEMA_VERSION,
                  "strategy_config": strategy_config_snapshot(cfg),
                  "settings": {"max_queue": rec.max_queue, "batch_size": rec.batch_size,
                               "flush_interval_s": rec.flush_interval_s,
                               "state_cache_size": rec.state_cache_size}},
                 transition=True, state={"boot_id": rec.boot_id})
        _RECORDERS[service] = rec
        return rec
    except Exception as exc:                    # visible, never fatal
        _INIT_ERRORS[service] = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning("evidence_v2 recorder for %s unavailable: %s", service, _INIT_ERRORS[service])
        return None


def emit(service: str, event_type: str, subject: dict, payload: dict | None = None, **kw) -> bool:
    """Module-level fail-safe emit."""
    try:
        rec = get_recorder(service)
        return rec.emit(event_type, subject, payload, **kw) if rec is not None else False
    except Exception:
        return False


def is_recorded(service: str, dedup_key: str, state: Any) -> bool:
    """True when `state` is the state last ACCEPTED into the queue for `dedup_key` (P1-FIX: a
    dropped event is never marked as seen). False when disabled or on any error. Never raises."""
    try:
        rec = _RECORDERS.get(service)
        return bool(rec is not None and
                    rec._state.get(dedup_key) == sha256_hex(canonical_json(state))[:20])
    except Exception:
        return False


def dropped_count(service: str) -> int:
    """Events dropped on a full queue by this service's recorder (0 when disabled). Never raises."""
    try:
        rec = _RECORDERS.get(service)
        return int(rec.dropped) if rec is not None else 0
    except Exception:
        return 0


def hook_error(service: str, exc: BaseException) -> None:
    try:
        rec = _RECORDERS.get(service)
        if rec is not None:
            rec.note_hook_error(exc)
    except Exception:
        pass


def health(service: str) -> dict | None:
    """Heartbeat metadata fragment; None when the recorder is disabled (metadata unchanged)."""
    try:
        if not enabled():
            return None
        if service in _INIT_ERRORS:
            return {"init_error": _INIT_ERRORS[service]}
        rec = _RECORDERS.get(service)
        return rec.health() if rec is not None else None
    except Exception:
        return None


def start_flusher(service: str):
    """Create the flusher task for `service` (call from a running event loop)."""
    try:
        rec = get_recorder(service)
        if rec is None:
            return None
        return asyncio.get_running_loop().create_task(rec.run_flusher(), name=f"evidence-v2-{service}")
    except Exception:
        return None


async def stop(service: str, task=None, timeout_ms: float = 2000.0) -> int:
    """Cancel the flusher and drain what is left. Returns pending events. Never raises."""
    try:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        rec = _RECORDERS.get(service)
        if rec is None:
            return 0
        return await asyncio.to_thread(rec.shutdown, timeout_ms)
    except Exception:
        return -1


def reset_for_tests() -> None:
    _RECORDERS.clear()
    _INIT_ERRORS.clear()


# ------------------------------------------------------------------ point-in-time helpers --
_CONFIG_HASH_CACHE: dict[int, str] = {}


def _cached_config_hash(cfg: Any) -> str:
    key = id(cfg)
    if key not in _CONFIG_HASH_CACHE:
        _CONFIG_HASH_CACHE[key] = compute_config_hash(cfg)
    return _CONFIG_HASH_CACHE[key]


def candle_pit(df: Any, timeframe: str, klines_fetched_at_ms: int | None) -> dict:
    """Exchange timestamps of the last CLOSED candle in a prepared OHLCV frame (index = Binance
    kline open time, UTC; `close_time` column = Binance close time in ms). Reads only; {} on error."""
    try:
        if df is None or len(df) == 0:
            return {}
        open_ms = int(df.index[-1].value // 1_000_000)
        if "close_time" in getattr(df, "columns", ()):
            close_ms = int(df["close_time"].iloc[-1])
        else:
            from shared.candle import candle_seconds
            close_ms = open_ms + candle_seconds(timeframe) * 1000 - 1
        return {"pit_version": 1, "candle_open_time_ms": open_ms, "candle_close_time_ms": close_ms,
                "klines_fetched_at_ms": klines_fetched_at_ms, "bars": int(len(df))}
    except Exception:
        return {}


def candidate_pit(pit: dict, symbol: str, timeframe: str, trade_type: str | None, cfg: Any,
                  weights: Any = None) -> dict:
    """Complete the analyzer's point-in-time block with the candidate identity and lineage.
    Returns a new dict; {} on error (the analysis result itself never depends on this)."""
    try:
        out = dict(pit or {})
        strategy_version = getattr(cfg, "APP_VERSION", None)
        cid = candle_id(symbol, timeframe, out.get("candle_open_time_ms"))
        out.update({
            "candle_id": cid,
            "candidate_id": candidate_id(cid, trade_type, strategy_version),
            "strategy_version": strategy_version,
            "code_sha": compute_code_sha(),
            "config_hash": _cached_config_hash(cfg),
            "weights_hash": (sha256_hex(canonical_json(weights))[:16] if weights is not None else None),
            "analyzed_at_ms": now_ms(),
        })
        return out
    except Exception:
        return {}


# ------------------------------------------------------------------ outcome vocabulary (P1-R) --
# One normalized code per terminal or non-terminal outcome, shared by every service. Events keep
# their detailed lowercase `reason` (unchanged P1 terms); `outcome_code` is the cross-service key.
# Pure functions of the values the runtime already decided on: they classify, never decide.
OUTCOME_CODES = (
    "POLICY_READY",        # signal persisted with decision_source=policy_ready + runtime signal.ready
    "INCOMPLETE_SIGNAL",   # save_signal refused a signal that failed assert_signal_complete
    "DELIVERED",           # telegram passed the candidate to the risk guard (telegram_sent=true)
    "AWAITING_APPROVAL",   # telegram sent an owner approval request (manual-approval flow)
    "B3_BLOCKED",          # loss-streak circuit breaker (B3) blocked delivery or admission
    "PAUSED",              # any other trading pause, incl. fail-closed missing/inconsistent risk state
    "CAPACITY",            # portfolio/open-trade capacity reached
    "RISK_REJECTED",       # other risk-guard hard stops (loss limits, exposure, concentration)
    "STALE",               # signal older than the admission window when its delivery event was handled
    "NOT_READY",           # not deliverable/trackable under the readiness contract
    "BLACKLISTED",         # symbol blacklisted
    "REJECTED",            # owner rejected the approval request
    "ENTRY_REJECTED",      # fill model rejected the entry (signal invalidated before fill)
    "DUPLICATE",           # already sent / already registered / repeat event for the same signal
    "SIGNAL_MISSING",      # event refers to a signal row that does not exist
    "ENTRY_MARKET",        # fill model would fill at market now (non-terminal; admission follows)
    "AWAITING_FILL",       # limit order waiting for the planned entry (non-terminal)
    "NO_FILL",             # admission window closed while the limit order was still unfilled
    "NO_PRICE",            # no current price to evaluate the entry (non-terminal)
    "BRACKET_INVALID",     # bracket construction failed
    "EXPIRED",             # admission window closed after a non-fill deferral (see last_outcome_code)
    "EXPIRED_UNOBSERVED",  # admission window closed; this process never observed an attempt
    "OPENED",              # paper trade registered (TRACKED)
    "DEFERRED_UNOBSERVED", # delivery event deferred; no admission attempt observed yet
    "UNKNOWN",             # unrecognized value (classification only; never a decision)
    "DELIVERY_FAILED",     # telegram candidate handling raised; runtime fail() scheduled a retry
)


def pause_outcome_code(reason: Any) -> str:
    """Code for a telegram delivery refusal (`can_deliver_candidate` block_reason)."""
    r = str(reason or "")
    if r.startswith("portfolio_capacity"):
        return "CAPACITY"
    if r.endswith("loss_streak_halt"):          # 'risk:loss_streak_halt' pause row = B3
        return "B3_BLOCKED"
    return "PAUSED"


_RISK_PAUSE_REASONS = {"manual_pause", "trading_paused", "risk_state_missing", "risk_state_inconsistent"}


def risk_outcome_code(reason: Any) -> str:
    """Code for a trade_tracker risk-guard rejection (RiskDecision.reason)."""
    r = str(reason or "")
    if r.endswith("loss_streak_halt"):          # 'loss_streak_halt' or pause reason 'risk:loss_streak_halt'
        return "B3_BLOCKED"
    if r == "max_open_trades" or r.startswith("portfolio_capacity"):
        return "CAPACITY"
    if r in _RISK_PAUSE_REASONS or r.startswith("risk:") or r == "إيقاف يدوي":
        return "PAUSED"
    return "RISK_REJECTED"


def candidate_skip(event_type: str, signal: Any) -> tuple[str, str]:
    """(reason, code) for a candidate event telegram acks without delivery. Mirrors
    shared.signal_readiness.is_deliverable_for_event (tested to agree with it)."""
    def get(key):
        try:
            return signal[key]
        except Exception:
            return None
    if signal is None:
        return "signal_missing", "SIGNAL_MISSING"
    if get("telegram_sent"):
        return "already_sent", "DUPLICATE"
    if event_type == "signal.ready":
        return "not_ready", "NOT_READY"
    if event_type == "signal.reviewed":
        return "legacy_not_approved", "NOT_READY"
    return "unsupported_event_type", "NOT_READY"


def admission_outcome_code(outcome: str, reason: Any = None) -> str:
    """Code for a trade_tracker admission.decision outcome."""
    return {
        "admitted": "OPENED", "no_price": "NO_PRICE", "bracket_invalid": "BRACKET_INVALID",
        "already_registered": "DUPLICATE", "halt_under_admission_lock": "B3_BLOCKED",
    }.get(outcome) or (risk_outcome_code(reason) if outcome == "risk_rejected" else "RISK_REJECTED")


def entry_outcome_code(action: Any) -> str:
    """Code for a trade_tracker entry.attempt (fill model action)."""
    return {"limit_wait": "AWAITING_FILL", "reject": "ENTRY_REJECTED", "market": "ENTRY_MARKET"}.get(
        str(action), "UNKNOWN")


def expiry_outcome_code(last_code: str | None) -> str:
    """Terminal code when a signal leaves the admission window without a trade."""
    if last_code is None:
        return "EXPIRED_UNOBSERVED"
    if last_code == "AWAITING_FILL":
        return "NO_FILL"
    return "EXPIRED"
