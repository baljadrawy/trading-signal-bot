"""Segment writer (hot path) + asynchronous certifier (G3-F3).

Segment lifecycle (file names are the authoritative, crash-safe state; SCHEMA.md section 1a):
  ACTIVE                          <name>.jsonl.gz.partial   + .idx.partial      (writer; synced every flush interval)
  FINALIZED_PENDING_CERTIFICATION <name>.jsonl.gz.pending   + .idx.pending      (writer: closed, fsynced, renamed)
  CERTIFYING                      <name>.jsonl.gz.certifying + .idx.pending     (certifier owns it)
  CERTIFIED                       <name>.jsonl.gz + .sha256 + .idx, 0444, manifest entry
  FAILED                          quarantine/ (+ quarantine_log.jsonl); never deleted
The writer never decodes, validates or hashes a finished segment: it finalizes it and hands it off by an atomic
rename, so hourly certification cannot block the hot write path. A single bounded certifier thread (serialized,
throttled) performs the unchanged certification. Only CERTIFIED segments are research data.

Layout under <data_dir>:
  raw/<type>/<YYYY-MM-DD>/<type>-<YYYYMMDDTHH>Z-<boot8>-<seq>.jsonl.gz(.partial)   + .sha256 + .idx
  manifests/<YYYY-MM-DD>.jsonl      one line per certified segment (append + fsync)
  quarantine/                       failed/salvaged originals (never deleted)

Durability (R16): every record is durable (sync-flush + fsync + .idx block line) within `flush_interval_s` of
being written. A segment with no new records in the current block is NOT re-synced and gets no .idx line: its
data is already durable at its last non-empty block. Closing always finalizes, fsyncs and certifies.
Disk HARD_STOP (R03): only observation records are refused; control records (lifecycle / gap / health) are still
written so the stop interval is visible in raw data.
"""
from __future__ import annotations

import collections
import datetime as dt
import gzip
import hashlib
import json
import os
import queue
import threading
import time
import zlib

from . import record as R

CONTROL_TYPES = frozenset({"lifecycle", "gap", "health"})
CERTIFIER_VERSION = "certifier-v1"
PENDING, CERTIFYING = ".pending", ".certifying"


def _utc(ns: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ns / 1e9, dt.timezone.utc)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def validate_segment(path: str, progress=None, throttle: bool = False) -> dict:
    """Full decode + per-line schema validation + in-segment duplicate check. Raises nothing; returns a report.
    `progress` is called every 500 lines (certifier heartbeat); `throttle` yields the CPU periodically so a
    certification can never starve the writer / event loop inside the 0.5-CPU container."""
    rep = {"records": 0, "invalid": 0, "duplicates": 0, "decode_error": None, "first_recv_ns": None, "last_recv_ns": None}
    seen = set()
    n = 0
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                n += 1
                if n % 500 == 0:
                    if progress is not None:
                        progress()
                    if throttle:
                        time.sleep(0.002)
                try:
                    rec = json.loads(line)
                except ValueError:
                    rep["invalid"] += 1; continue
                if R.validate(rec):
                    rep["invalid"] += 1; continue
                if rec["obs_id"] in seen:
                    rep["duplicates"] += 1
                seen.add(rec["obs_id"]); rep["records"] += 1
                t = rec["recv_ts_ns"]
                rep["first_recv_ns"] = t if rep["first_recv_ns"] is None else min(rep["first_recv_ns"], t)
                rep["last_recv_ns"] = t if rep["last_recv_ns"] is None else max(rep["last_recv_ns"], t)
    except (OSError, EOFError, zlib.error) as e:
        rep["decode_error"] = type(e).__name__
    return rep


def salvage_partial(path: str) -> list:
    """Decode a crashed .partial up to the last complete sync-flushed line; return the valid records."""
    with open(path, "rb") as fh:
        data = fh.read()
    d = zlib.decompressobj(31)
    try:
        text = d.decompress(data)
    except zlib.error:
        text = b""
    out = []
    for line in text.split(b"\n")[:-1]:              # last fragment may be incomplete
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not R.validate(rec):
            out.append(rec)
    return out


class _Segment:
    def __init__(self, base: str, typ: str, hour_key: str, boot8: str, seq: int, suffix: str = ""):
        day = f"{hour_key[:4]}-{hour_key[4:6]}-{hour_key[6:8]}"
        self.dir = os.path.join(base, "raw", typ, day)
        os.makedirs(self.dir, exist_ok=True)
        self.name = f"{typ}-{hour_key}Z-{boot8}-{seq:04d}{suffix}.jsonl.gz"
        self.final = os.path.join(self.dir, self.name)
        self.partial = self.final + ".partial"
        self.idx_partial = self.final[:-9] + ".idx.partial"
        self.fh = open(self.partial, "wb")
        self.gz = gzip.GzipFile(filename="", mode="wb", fileobj=self.fh, mtime=0, compresslevel=6)
        self.idx = open(self.idx_partial, "w", encoding="utf-8")
        self.day, self.hour_key, self.typ = day, hour_key, typ
        self.block, self.records, self.block_records = 0, 0, 0

    def write(self, rec: dict) -> None:
        rec["blk"] = self.block
        self.gz.write((json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8"))
        self.records += 1; self.block_records += 1

    def sync(self, force: bool = False):
        """Make the current block durable. Idle block (no records since the last sync) => no-op (R16)."""
        if self.block_records == 0 and not force:
            return None
        self.gz.flush(zlib.Z_SYNC_FLUSH); self.fh.flush(); os.fsync(self.fh.fileno())
        durable = time.time_ns()
        self.idx.write(json.dumps({"blk": self.block, "end_offset": self.fh.tell(), "records": self.block_records,
                                   "durable_ts_ns": durable}) + "\n")
        self.idx.flush(); os.fsync(self.idx.fileno())
        self.block += 1; self.block_records = 0
        return durable

    def finalize(self) -> str:
        """Close, fsync and hand off: .partial -> .pending (atomic; the durable handoff). Returns the pending path."""
        if self.block_records:
            self.sync(force=True)
        self.gz.close(); self.fh.flush(); os.fsync(self.fh.fileno()); self.fh.close()
        self.idx.flush(); os.fsync(self.idx.fileno()); self.idx.close()
        os.rename(self.idx_partial, self.final[:-9] + ".idx" + PENDING)
        os.rename(self.partial, self.final + PENDING)
        _fsync_dir(self.dir)
        return self.final + PENDING


def _idx_records(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return sum(json.loads(l)["records"] for l in fh)
    except (OSError, ValueError, KeyError):
        return None


def _manifest_has(base: str, day: str, rel: str) -> bool:
    mp = os.path.join(base, "manifests", f"{day}.jsonl")
    if not os.path.exists(mp):
        return False
    with open(mp, encoding="utf-8") as fh:
        return any(json.loads(l).get("segment") == rel for l in fh if l.strip())


def quarantine_files(base: str, paths: list, reason: str, name: str, stats: dict) -> None:
    qdir = os.path.join(base, "quarantine"); os.makedirs(qdir, exist_ok=True)
    for p in paths:
        if p and os.path.exists(p):
            os.rename(p, os.path.join(qdir, os.path.basename(p)))
    with open(os.path.join(qdir, "quarantine_log.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"segment": name, "reason": reason, "ts_ns": time.time_ns()}) + "\n"); fh.flush(); os.fsync(fh.fileno())
    stats["segments_quarantined"] += 1


def certify(base: str, cert_path: str, stats: dict, boot_id: str, run_record=None, progress=None, throttle=False,
            recovered: bool = False) -> bool:
    """Certify one FINALIZED segment (path ends with .certifying or .pending). Unchanged guarantees: full gzip/JSONL
    decode, per-record schema validation, in-segment duplicates, record count = .idx total, SHA-256 sidecar,
    atomic promotion, read-only, manifest entry (idempotent). Failure => quarantine (fail closed)."""
    suf = CERTIFYING if cert_path.endswith(CERTIFYING) else PENDING
    final = cert_path[: -len(suf)]
    stem = final[:-9]
    idx_pend, idx_final = stem + ".idx" + PENDING, stem + ".idx"
    name, d = os.path.basename(final), os.path.dirname(final)
    rel = os.path.relpath(final, base)
    day = os.path.basename(d)
    if os.path.exists(final):                                         # never two certified copies of one name
        quarantine_files(base, [cert_path], "conflict:certified_copy_exists", name, stats)
        return False
    t0 = time.monotonic()
    expected = _idx_records(idx_pend)
    rep = validate_segment(cert_path, progress=progress, throttle=throttle)
    if rep["decode_error"] or rep["invalid"] or rep["duplicates"] or expected is None or rep["records"] != expected:
        quarantine_files(base, [cert_path, idx_pend], f"certification:{json.dumps({**rep, 'expected': expected}, sort_keys=True)}",
                         name, stats)
        stats["certification_failures"] += 1
        return False
    digest = sha256_file(cert_path)
    with open(final + ".sha256.tmp", "w", encoding="utf-8") as fh:
        fh.write(f"{digest}  {name}\n"); fh.flush(); os.fsync(fh.fileno())
    os.rename(final + ".sha256.tmp", final + ".sha256")
    os.rename(cert_path, final)
    os.rename(idx_pend, idx_final)
    for p in (final, final + ".sha256", idx_final):
        os.chmod(p, 0o444)
    _fsync_dir(d)
    _manifest_append(base, final, rel, day, digest, rep, run_record, boot_id, recovered)
    stats["segments_promoted"] += 1
    dur = int((time.monotonic() - t0) * 1000)
    stats["certify_last_ms"] = dur
    stats["certify_max_ms"] = max(stats.get("certify_max_ms", 0), dur)
    return True


def _manifest_append(base, final, rel, day, digest, rep, run_record, boot_id, recovered):
    if _manifest_has(base, day, rel):                                 # idempotent (crash after manifest append)
        return
    name = os.path.basename(final)
    entry = {"segment": rel, "sha256": digest, "records": rep["records"], "bytes": os.path.getsize(final),
             "type": name.split("-", 1)[0], "first_recv_ns": rep["first_recv_ns"], "last_recv_ns": rep["last_recv_ns"],
             "boot": name.split("-")[2], "boot_id": boot_id, "run_record": run_record,
             "idx_bytes": os.path.getsize(final[:-9] + ".idx"), "certified_ms": time.time_ns() // 1_000_000,
             "certifier": CERTIFIER_VERSION, "recovered": recovered}
    os.makedirs(os.path.join(base, "manifests"), exist_ok=True)
    mpath = os.path.join(base, "manifests", f"{day}.jsonl")
    with open(mpath, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n"); fh.flush(); os.fsync(fh.fileno())


def scan_lifecycle(base: str) -> dict:
    """Classify every segment file under raw/ by its lifecycle state (names are authoritative)."""
    out = {"active": [], "pending": [], "certifying": [], "certified": []}
    for root, _, files in os.walk(os.path.join(base, "raw")):
        for f in files:
            p = os.path.join(root, f)
            if f.endswith(".jsonl.gz.partial"):
                out["active"].append(p)
            elif f.endswith(".jsonl.gz" + PENDING):
                out["pending"].append(p)
            elif f.endswith(".jsonl.gz" + CERTIFYING):
                out["certifying"].append(p)
            elif f.endswith(".jsonl.gz"):
                out["certified"].append(p)
    return out


class Certifier(threading.Thread):
    """Single, serialized, throttled certification worker. The filesystem (*.pending) is the authoritative queue:
    `submit` only nudges; a periodic scan finds anything pending (also after a restart)."""

    def __init__(self, base: str, boot_id: str, stats: dict, run_record_ref):
        super().__init__(name="segment-certifier", daemon=True)
        self.base, self.boot_id, self.stats, self.run_record_ref = base, boot_id, stats, run_record_ref
        self.nudge = threading.Event()
        self._stop_evt = threading.Event()
        self.beat_ns = time.time_ns()
        self.fatal = None
        self.busy_since_ns = None
        self.slow_test_hook = None                                   # tests: inject slowness

    def submit(self, path: str) -> None:
        self.nudge.set()

    def pending(self) -> list:
        st = scan_lifecycle(self.base)
        return st["pending"] + st["certifying"]

    def status(self) -> dict:
        now = time.time_ns()
        pend = self.pending()
        ages = []
        for p in pend:
            try:
                ages.append((now - os.stat(p).st_mtime_ns) // 1_000_000)
            except OSError:
                pass
        return {"alive": self.is_alive(), "fatal": self.fatal, "beat_age_ms": (now - self.beat_ns) // 1_000_000,
                "pending": len(pend), "oldest_pending_age_ms": max(ages, default=0),
                "busy_ms": None if self.busy_since_ns is None else (now - self.busy_since_ns) // 1_000_000,
                "last_ms": self.stats.get("certify_last_ms"), "max_ms": self.stats.get("certify_max_ms"),
                "failures": self.stats["certification_failures"], "certified": self.stats["segments_promoted"]}

    def _beat(self) -> None:
        self.beat_ns = time.time_ns()

    def run_once(self) -> int:
        n = 0
        for p in sorted(self.pending()):
            self._beat()
            cp = p if p.endswith(CERTIFYING) else p[: -len(PENDING)] + CERTIFYING
            try:
                if p.endswith(PENDING):
                    os.rename(p, cp)
                self.busy_since_ns = time.time_ns()
                if self.slow_test_hook:
                    self.slow_test_hook(self)
                certify(self.base, cp, self.stats, self.boot_id, self.run_record_ref(), progress=self._beat, throttle=True)
            except OSError as e:
                self.stats["certification_failures"] += 1
                self.stats["last_certify_error"] = f"{type(e).__name__}: {e}"[:200]
            finally:
                self.busy_since_ns = None
            n += 1
            self._beat()
        return n

    def run(self) -> None:
        try:
            while not self._stop_evt.is_set():
                self._beat()
                self.nudge.wait(1.0); self.nudge.clear()
                self.run_once()
        except BaseException as e:                                    # noqa: BLE001 - made visible by health/supervisor
            self.fatal = f"{type(e).__name__}: {e}"[:300]
            raise

    def drain(self, timeout_s: float) -> bool:
        """Shutdown: certify everything pending within the grace; True if nothing remains."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            if not self.pending():
                return True
            if not self.is_alive():
                self.run_once()
            else:
                self.nudge.set(); time.sleep(0.2)
        return not self.pending()

    def stop(self) -> None:
        self._stop_evt.set(); self.nudge.set()


class SegmentWriter(threading.Thread):
    def __init__(self, data_dir: str, boot_id: str, q: queue.Queue, stats: dict, flush_interval_s: float = 2.0,
                 certify_grace_s: float = 300.0):
        super().__init__(name="segment-writer", daemon=True)
        self.base, self.boot8, self.q, self.stats = data_dir, boot_id[:8], q, stats
        self.flush_interval_s = flush_interval_s
        self.segments: dict = {}
        self.seq = collections.Counter()
        self.recent = collections.OrderedDict()           # bounded cross-segment duplicate filter
        self.stop_writes = threading.Event()               # disk hard stop: observation records refused (R03)
        self._stop_evt = threading.Event()
        self.last_durable_ns = None
        self.pending_since_ns = None                       # first not-yet-durable record (durable-lag, F43)
        self.beat_ns = None                                # HOT PATH heartbeat (F43 / G3-F3)
        self.max_beat_gap_ms = 0                           # G3-F3 measurement: worst hot-path heartbeat gap
        self.max_durable_lag_ms = 0                        # G3-F3 measurement: worst write -> fsync latency
        self.fatal = None
        self.finished = False
        self.certified_all = None                          # shutdown: everything certified within the grace?
        self.run_record = None
        self.boot_id = boot_id
        self.certify_grace_s = certify_grace_s
        self.lock = threading.Lock()
        for d in ("raw", "manifests", "quarantine", "universe", "health"):
            os.makedirs(os.path.join(self.base, d), exist_ok=True)
        self.certifier = Certifier(self.base, boot_id, stats, lambda: self.run_record)
        self.certifier_restarts = 0

    # ---- lifecycle ----
    def start(self) -> None:
        super().start()
        self.certifier.start()

    def restart_certifier(self) -> None:
        old = self.certifier
        self.certifier = Certifier(self.base, self.boot_id, self.stats, lambda: self.run_record)
        self.certifier.slow_test_hook = old.slow_test_hook
        self.certifier_restarts += 1
        self.certifier.start()

    def _beat(self) -> None:
        now = time.time_ns()
        if self.beat_ns is not None:
            self.max_beat_gap_ms = max(self.max_beat_gap_ms, (now - self.beat_ns) // 1_000_000)
        self.beat_ns = now

    def run(self) -> None:
        try:
            last_sync = time.monotonic()
            while not (self._stop_evt.is_set() and self.q.empty()):
                self._beat()
                try:
                    rec = self.q.get(timeout=0.2)
                except queue.Empty:
                    rec = None
                if rec is not None:
                    self._write_guarded(rec)
                if time.monotonic() - last_sync >= self.flush_interval_s:
                    self._sync_all(); self._rotate_due(); last_sync = time.monotonic()
            self._sync_all()
            self.close_all()
            self.finished = True
            self.certified_all = self.certifier.drain(self.certify_grace_s)
            self.certifier.stop()
        except BaseException as e:                         # noqa: BLE001 - recorded, made visible by the supervisor
            self.fatal = f"{type(e).__name__}: {e}"[:300]
            raise

    def status(self) -> dict:
        now = time.time_ns()
        return {"alive": self.is_alive(), "finished": self.finished, "fatal": self.fatal,
                "beat_age_ms": None if self.beat_ns is None else (now - self.beat_ns) // 1_000_000,
                "durable_lag_ms": 0 if self.pending_since_ns is None else (now - self.pending_since_ns) // 1_000_000,
                "last_durable_ms": None if self.last_durable_ns is None else self.last_durable_ns // 1_000_000,
                "max_beat_gap_ms": self.max_beat_gap_ms, "max_durable_lag_ms": self.max_durable_lag_ms,
                "write_errors": self.stats["write_errors"], "rejected": self.stats["writer_rejected"]}

    def stop(self) -> None:
        self._stop_evt.set()

    # ---- core ----
    def _write_guarded(self, rec) -> None:
        """One bad record must never kill the writer (F43): non-I/O failures reject and count that record."""
        try:
            self._write(rec)
        except OSError:
            raise
        except Exception as e:                             # noqa: BLE001
            self.stats["writer_rejected"][type(e).__name__] += 1

    def _write(self, rec: dict) -> None:
        if self.stop_writes.is_set() and rec.get("type") not in CONTROL_TYPES:
            self.stats["dropped"][rec.get("type", "?")] += 1
            return
        oid = rec.get("obs_id")
        if oid in self.recent:
            self.stats["duplicates_dropped"] += 1
            self.stats["duplicates_by_type"][rec.get("type", "?")] += 1
            return
        self.recent[oid] = None
        if len(self.recent) > 200_000:
            self.recent.popitem(last=False)
        hour_key = _utc(time.time_ns()).strftime("%Y%m%dT%H")      # writer wall clock: monotonic rotation
        key = rec["type"]
        try:
            seg = self.segments.get(key)
            if seg is not None and seg.hour_key != hour_key:
                self._promote(seg); seg = None
            if seg is None:
                self.seq[key] += 1
                seg = self.segments[key] = _Segment(self.base, key, hour_key, self.boot8, self.seq[key])
            seg.write(rec)
            if self.pending_since_ns is None:
                self.pending_since_ns = time.time_ns()
            self.stats["written"][key] += 1
        except OSError as e:
            self._write_failure(key, e)

    def _write_failure(self, key: str, err: Exception) -> None:
        self.stats["write_errors"] += 1
        self.stats["last_write_error"] = type(err).__name__
        seg = self.segments.pop(key, None)
        if seg is not None:
            self._quarantine(seg, f"write_failure:{type(err).__name__}")

    def _sync_all(self) -> None:
        for key, seg in list(self.segments.items()):
            try:
                d = seg.sync()
                if d is not None:
                    self.last_durable_ns = d
            except OSError as e:
                self._write_failure(key, e)
        if self.pending_since_ns is not None:
            self.max_durable_lag_ms = max(self.max_durable_lag_ms, (time.time_ns() - self.pending_since_ns) // 1_000_000)
        self.pending_since_ns = None

    def _rotate_due(self) -> None:
        now_key = _utc(time.time_ns()).strftime("%Y%m%dT%H")
        for key, seg in list(self.segments.items()):
            if seg.hour_key != now_key:
                self.segments.pop(key); self._promote(seg)

    def close_all(self) -> None:
        for key in list(self.segments):
            self._promote(self.segments.pop(key))

    # ---- finalize + hand-off (hot path does NOT certify) ----
    def _promote(self, seg: _Segment) -> None:
        try:
            p = seg.finalize()
        except OSError as e:
            self.stats["write_errors"] += 1
            self._quarantine(seg, f"finalize_failure:{type(e).__name__}"); return
        self.stats["segments_finalized"] += 1
        self.certifier.submit(p)

    def _quarantine(self, seg: _Segment, reason: str) -> None:
        for f in (seg.fh, seg.idx):
            try:
                if not f.closed:
                    f.close()
            except OSError:
                pass
        quarantine_files(self.base, [seg.partial, seg.idx_partial], reason, seg.name, self.stats)


def recover_partials(data_dir: str, boot_id: str, stats: dict) -> list:
    """Startup crash recovery; every segment is classified deterministically (names are authoritative):
    - ACTIVE .partial: if the gzip stream is complete and matches its .idx it was finalized-but-not-handed-off ->
      .pending; otherwise salvage to a '-recovered' segment and quarantine the original (never delete);
    - CERTIFYING (crash during certification) and PENDING: certified now (idempotent; quarantined on failure);
    - certified file without manifest entry (crash after promotion, before the manifest): checksum re-verified
      against its sidecar and the manifest entry completed; mismatch -> quarantine.
    Returns gap descriptors for salvaged (crash-interrupted) segments."""
    gaps = []
    raw = os.path.join(data_dir, "raw")
    os.makedirs(os.path.join(data_dir, "quarantine"), exist_ok=True)
    for root, _, files in os.walk(raw):
        for f in sorted(files):
            if not f.endswith(".jsonl.gz.partial"):
                continue
            p = os.path.join(root, f)
            stem = p[: -len(".jsonl.gz.partial")]
            rep = validate_segment(p)
            expected = _idx_records(stem + ".idx.partial")
            if not rep["decode_error"] and not rep["invalid"] and expected is not None and rep["records"] == expected:
                os.rename(stem + ".idx.partial", stem + ".idx" + PENDING)
                os.rename(p, stem + ".jsonl.gz" + PENDING)
                stats["recovered_finalized"] = stats.get("recovered_finalized", 0) + 1
                continue
            recs = salvage_partial(p)
            typ = f.split("-", 1)[0]
            if recs:
                seg = _Segment(data_dir, typ, f.split("-")[1][:11], boot_id[:8], 1, suffix="-recovered-" + f.split("-")[2])
                for r in recs:
                    seg.write(r)
                pend = seg.finalize()
                certify(data_dir, pend, stats, boot_id, recovered=True)
            last = max((r["recv_ts_ns"] for r in recs), default=None)
            qdir = os.path.join(data_dir, "quarantine")
            os.rename(p, os.path.join(qdir, f + ".orig"))
            if os.path.exists(stem + ".idx.partial"):
                os.rename(stem + ".idx.partial", os.path.join(qdir, os.path.basename(stem) + ".idx.partial.orig"))
            stats["recovered_records"] += len(recs)
            gaps.append({"type": typ, "salvaged": len(recs), "last_salvaged_recv_ns": last, "source": f})
    st = scan_lifecycle(data_dir)
    for p in sorted(st["certifying"] + st["pending"]):
        certify(data_dir, p, stats, boot_id, recovered=True)
        stats["recovered_pending_certified"] = stats.get("recovered_pending_certified", 0) + 1
    for p in sorted(scan_lifecycle(data_dir)["certified"]):
        rel = os.path.relpath(p, data_dir); day = os.path.basename(os.path.dirname(p))
        if os.path.exists(p + ".sha256.tmp"):                         # an unrenamed temp sidecar is never authoritative
            os.remove(p + ".sha256.tmp")
        if _manifest_has(data_dir, day, rel):
            continue
        side = None
        if os.path.exists(p + ".sha256"):
            with open(p + ".sha256", encoding="utf-8") as fh:
                side = fh.read().split()[0]
        if side is None or side != sha256_file(p):
            quarantine_files(data_dir, [p, p + ".sha256", p[:-9] + ".idx"], "recovery:certified_without_valid_sidecar",
                             os.path.basename(p), stats)
            continue
        rep = validate_segment(p)
        for q in (p, p + ".sha256", p[:-9] + ".idx"):
            if os.path.exists(q):
                os.chmod(q, 0o444)
        _manifest_append(data_dir, p, rel, day, side, rep, None, boot_id, True)
        stats["recovered_manifest_completed"] = stats.get("recovered_manifest_completed", 0) + 1
    return gaps


def new_stats() -> dict:
    """Shared counters (written by the writer thread and the async tasks; GIL-safe increments)."""
    return {"written": collections.Counter(), "dropped": collections.Counter(), "duplicates_dropped": 0,
            "write_errors": 0, "last_write_error": None, "segments_promoted": 0, "segments_quarantined": 0,
            "recovered_records": 0, "malformed": 0, "rejected": collections.Counter(),
            "writer_rejected": collections.Counter(), "duplicates_by_type": collections.Counter(),
            "unknown_stream": 0, "unknown_event": 0, "handler_errors": 0,
            "segments_finalized": 0, "certification_failures": 0}
