"""Segment writer (dedicated thread): .partial -> periodic sync-flush+fsync -> close -> validate -> SHA-256 ->
atomic rename -> read-only certified segment. Only promoted segments with a matching .sha256 are captured data.

Layout under <data_dir>:
  raw/<type>/<YYYY-MM-DD>/<type>-<YYYYMMDDTHH>Z-<boot8>-<seq>.jsonl.gz(.partial)   + .sha256 + .idx
  manifests/<YYYY-MM-DD>.jsonl      one line per certified segment (append + fsync)
  quarantine/                       failed/salvaged originals (never deleted)
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


def validate_segment(path: str) -> dict:
    """Full decode + per-line schema validation + in-segment duplicate check. Raises nothing; returns a report."""
    rep = {"records": 0, "invalid": 0, "duplicates": 0, "decode_error": None, "first_recv_ns": None, "last_recv_ns": None}
    seen = set()
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
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

    def sync(self) -> int:
        self.gz.flush(zlib.Z_SYNC_FLUSH); self.fh.flush(); os.fsync(self.fh.fileno())
        durable = time.time_ns()
        self.idx.write(json.dumps({"blk": self.block, "end_offset": self.fh.tell(), "records": self.block_records,
                                   "durable_ts_ns": durable}) + "\n")
        self.idx.flush(); os.fsync(self.idx.fileno())
        self.block += 1; self.block_records = 0
        return durable


class SegmentWriter(threading.Thread):
    def __init__(self, data_dir: str, boot_id: str, q: queue.Queue, stats: dict, flush_interval_s: float = 2.0):
        super().__init__(name="segment-writer", daemon=True)
        self.base, self.boot8, self.q, self.stats = data_dir, boot_id[:8], q, stats
        self.flush_interval_s = flush_interval_s
        self.segments: dict = {}
        self.seq = collections.Counter()
        self.recent = collections.OrderedDict()           # bounded cross-segment duplicate filter
        self.stop_writes = threading.Event()               # disk hard stop / write failure gate
        self._stop_evt = threading.Event()
        self.last_durable_ns = None
        self.lock = threading.Lock()
        for d in ("raw", "manifests", "quarantine", "universe", "health"):
            os.makedirs(os.path.join(self.base, d), exist_ok=True)

    # ---- lifecycle ----
    def run(self) -> None:
        last_sync = time.monotonic()
        while not (self._stop_evt.is_set() and self.q.empty()):
            try:
                rec = self.q.get(timeout=0.2)
            except queue.Empty:
                rec = None
            if rec is not None:
                self._write(rec)
            if time.monotonic() - last_sync >= self.flush_interval_s:
                self._sync_all(); self._rotate_due(); last_sync = time.monotonic()
        self._sync_all()
        self.close_all()

    def stop(self) -> None:
        self._stop_evt.set()

    # ---- core ----
    def _write(self, rec: dict) -> None:
        if self.stop_writes.is_set():
            self.stats["dropped"][rec.get("type", "?")] += 1
            return
        oid = rec.get("obs_id")
        if oid in self.recent:
            self.stats["duplicates_dropped"] += 1
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
                self.last_durable_ns = seg.sync()
            except OSError as e:
                self._write_failure(key, e)

    def _rotate_due(self) -> None:
        now_key = _utc(time.time_ns()).strftime("%Y%m%dT%H")
        for key, seg in list(self.segments.items()):
            if seg.hour_key != now_key:
                self.segments.pop(key); self._promote(seg)

    def close_all(self) -> None:
        for key in list(self.segments):
            self._promote(self.segments.pop(key))

    # ---- promotion / quarantine ----
    def _promote(self, seg: _Segment) -> None:
        try:
            seg.sync(); seg.gz.close(); seg.fh.flush(); os.fsync(seg.fh.fileno()); seg.fh.close(); seg.idx.close()
        except OSError as e:
            self.stats["write_errors"] += 1
            self._quarantine(seg, f"close_failure:{type(e).__name__}"); return
        rep = validate_segment(seg.partial)
        if rep["decode_error"] or rep["invalid"] or rep["duplicates"] or rep["records"] != seg.records:
            self._quarantine(seg, f"validation:{json.dumps(rep, sort_keys=True)}"); return
        digest = sha256_file(seg.partial)
        with open(seg.final + ".sha256", "w", encoding="utf-8") as fh:
            fh.write(f"{digest}  {seg.name}\n"); fh.flush(); os.fsync(fh.fileno())
        os.rename(seg.partial, seg.final)
        os.rename(seg.idx_partial, seg.final[:-9] + ".idx")
        for p in (seg.final, seg.final + ".sha256", seg.final[:-9] + ".idx"):
            os.chmod(p, 0o444)
        _fsync_dir(seg.dir)
        entry = {"segment": os.path.relpath(seg.final, self.base), "sha256": digest, "records": rep["records"],
                 "bytes": os.path.getsize(seg.final), "type": seg.typ, "first_recv_ns": rep["first_recv_ns"],
                 "last_recv_ns": rep["last_recv_ns"], "boot": self.boot8}
        mpath = os.path.join(self.base, "manifests", f"{seg.day}.jsonl")
        with open(mpath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n"); fh.flush(); os.fsync(fh.fileno())
        self.stats["segments_promoted"] += 1

    def _quarantine(self, seg: _Segment, reason: str) -> None:
        qdir = os.path.join(self.base, "quarantine")
        for p in (seg.partial, seg.idx_partial):
            try:
                if not seg.fh.closed: seg.fh.close()
                if not seg.idx.closed: seg.idx.close()
            except OSError:
                pass
            if os.path.exists(p):
                os.rename(p, os.path.join(qdir, os.path.basename(p)))
        with open(os.path.join(qdir, "quarantine_log.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"segment": seg.name, "reason": reason, "ts_ns": time.time_ns()}) + "\n")
        self.stats["segments_quarantined"] += 1


def recover_partials(data_dir: str, boot_id: str, stats: dict) -> list:
    """Startup crash recovery: salvage every leftover .partial into a '-recovered' certified segment; move the
    original to quarantine (never delete). Returns gap descriptors for the crash interval."""
    gaps = []
    raw = os.path.join(data_dir, "raw")
    qdir = os.path.join(data_dir, "quarantine"); os.makedirs(qdir, exist_ok=True)
    for root, _, files in os.walk(raw):
        for f in sorted(files):
            if not f.endswith(".jsonl.gz.partial"):
                continue
            p = os.path.join(root, f)
            recs = salvage_partial(p)
            typ = f.split("-", 1)[0]
            if recs:
                q = queue.Queue()
                w = SegmentWriter(data_dir, boot_id, q, stats)
                seg = _Segment(data_dir, typ, f.split("-")[1][:11], boot_id[:8], 1, suffix="-recovered-" + f.split("-")[2])
                for r in recs:
                    seg.write(r)
                w._promote(seg)
            last = max((r["recv_ts_ns"] for r in recs), default=None)
            os.rename(p, os.path.join(qdir, f + ".orig"))
            idx = p[:-len(".jsonl.gz.partial")] + ".idx.partial"
            if os.path.exists(idx):
                os.rename(idx, os.path.join(qdir, os.path.basename(idx) + ".orig"))
            stats["recovered_records"] += len(recs)
            gaps.append({"type": typ, "salvaged": len(recs), "last_salvaged_recv_ns": last, "source": f})
    return gaps


def new_stats() -> dict:
    """Shared counters (written by the writer thread and the async tasks; GIL-safe increments)."""
    return {"written": collections.Counter(), "dropped": collections.Counter(), "duplicates_dropped": 0,
            "write_errors": 0, "last_write_error": None, "segments_promoted": 0, "segments_quarantined": 0,
            "recovered_records": 0, "malformed": 0, "rejected": collections.Counter()}
