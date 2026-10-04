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
  days/<YYYY-MM-DD>.json            P2-CR day-close record (continuous mode): the day directory is final; hot paths
                                    (certifier scans, health, disk accounting, recovery) never walk closed days again

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

from . import cal
from . import record as R

CONTROL_TYPES = frozenset({"lifecycle", "gap", "health"})
CERTIFIER_VERSION = "certifier-v1"
PENDING, CERTIFYING = ".pending", ".certifying"


DAYS_DIR = "days"
SEGMENT_SUFFIXES = (".jsonl.gz", ".jsonl.gz.sha256", ".idx")


def _utc(ns: int) -> dt.datetime:
    """Calendar time (hour resolution) of a wall-clock instant: the segment hour key (cal.py; production = UTC)."""
    return cal.utc_of_ms(ns // 1_000_000)


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
        for l in fh:
            try:
                if json.loads(l).get("segment") == rel:
                    return True
            except ValueError:                                         # torn line (repaired at startup)
                continue
    return False


def repair_manifests(base: str, stats: dict) -> None:
    """F3: a crash mid-append can leave a torn trailing line: keep it in quarantine, truncate to the last newline."""
    md = os.path.join(base, "manifests")
    for f in sorted(os.listdir(md)) if os.path.isdir(md) else []:
        p = os.path.join(md, f)
        data = open(p, "rb").read()
        if data and not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1
            qdir = os.path.join(base, "quarantine"); os.makedirs(qdir, exist_ok=True)
            with open(os.path.join(qdir, f + f".torn-{time.time_ns()}"), "wb") as fh:
                fh.write(data[cut:])
            with open(p, "r+b") as fh:
                fh.truncate(cut); fh.flush(); os.fsync(fh.fileno())
            stats["manifest_repairs"] = stats.get("manifest_repairs", 0) + 1


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
    if os.path.exists(os.path.join(base, DAYS_DIR, f"{day}.json")):    # P2-CR: a closed day never changes
        quarantine_files(base, [cert_path, idx_pend if os.path.exists(idx_pend) else None],
                         "conflict:day_closed", name, stats)
        return False
    if os.path.exists(final):                                         # never two certified copies of one name
        quarantine_files(base, [cert_path, idx_pend if os.path.exists(idx_pend) else None],
                         "conflict:certified_copy_exists", name, stats)
        return False
    # idx source: .idx.pending, or .idx already renamed by an interrupted certification (final data not yet renamed)
    idx_src = idx_pend if os.path.exists(idx_pend) else (idx_final if os.path.exists(idx_final) else None)
    t0 = time.monotonic()
    expected = _idx_records(idx_src) if idx_src else None
    rep = validate_segment(cert_path, progress=progress, throttle=throttle)
    if rep["decode_error"] or rep["invalid"] or rep["duplicates"] or expected is None or rep["records"] != expected:
        quarantine_files(base, [cert_path, idx_src], f"certification:{json.dumps({**rep, 'expected': expected}, sort_keys=True)}",
                         name, stats)
        stats["certification_failures"] += 1
        return False
    digest = sha256_file(cert_path)
    with open(final + ".sha256.tmp", "w", encoding="utf-8") as fh:
        fh.write(f"{digest}  {name}\n"); fh.flush(); os.fsync(fh.fileno())
    os.rename(final + ".sha256.tmp", final + ".sha256")
    if idx_src != idx_final:
        os.rename(idx_src, idx_final)
    os.rename(cert_path, final)                                       # the final data name is ALWAYS the last rename
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


def closed_days(base: str) -> set:
    d = os.path.join(base, DAYS_DIR)
    return {f[:-5] for f in os.listdir(d) if f.endswith(".json")} if os.path.isdir(d) else set()


def segment_days(base: str) -> set:
    """Every day directory that exists under raw/<type>/ (directory names only: O(types x days))."""
    raw, out = os.path.join(base, "raw"), set()
    if not os.path.isdir(raw):
        return out
    with os.scandir(raw) as it:                                  # d_type from the directory entry: no per-day stat
        for t in it:
            if t.is_dir():
                with os.scandir(t.path) as days:
                    out.update(x.name for x in days if x.is_dir())
    return out


def open_days(base: str) -> list:
    """Days not yet closed. Bounded mode never closes a day, so this is every day (pre-P2-CR behaviour)."""
    return sorted(segment_days(base) - closed_days(base))


def day_dirs(base: str, days) -> list:
    raw, out = os.path.join(base, "raw"), []
    if not os.path.isdir(raw):
        return out
    for t in sorted(os.listdir(raw)):
        for day in days:
            p = os.path.join(raw, t, day)
            if os.path.isdir(p):
                out.append(p)
    return out


def scan_lifecycle(base: str, days=None) -> dict:
    """Classify every segment file of the OPEN days (or of `days`) by its lifecycle state (names are authoritative).
    P2-CR (CR-B02): cost depends on the open days only, never on the age of the dataset."""
    out = {"active": [], "pending": [], "certifying": [], "certified": []}
    if not os.path.isdir(os.path.join(base, "raw")):
        return out
    for d in day_dirs(base, open_days(base) if days is None else days):
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if f.endswith(".jsonl.gz.partial"):
                out["active"].append(p)
            elif f.endswith(".jsonl.gz" + PENDING):
                out["pending"].append(p)
            elif f.endswith(".jsonl.gz" + CERTIFYING):
                out["certifying"].append(p)
            elif f.endswith(".jsonl.gz"):
                out["certified"].append(p)
    return out


def _manifest_entries(base: str, day: str) -> tuple:
    mp = os.path.join(base, "manifests", f"{day}.jsonl")
    out, torn = {}, 0
    if os.path.exists(mp):
        with open(mp, encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                    out[e["segment"]] = e
                except (ValueError, KeyError, TypeError):
                    torn += 1
    return out, torn, mp


def close_day(base: str, day: str, open_segment_days) -> tuple:
    """P2-CR day close. Returns ("closed", record) | ("not_ready", reason) | ("mismatch", problems).
    Preconditions (fail closed): the writer has no open segment in `day`; no .partial / .pending / .certifying file;
    the certified files and the day manifest match exactly (entries, sidecars, .idx, 0444). Cheap: names, sizes and
    sidecar digests only (the independent seal re-hashes and re-validates every segment)."""
    if os.path.exists(os.path.join(base, DAYS_DIR, f"{day}.json")):
        return "not_ready", "already_closed"
    if day in set(open_segment_days):
        return "not_ready", "writer_segment_open"
    st = scan_lifecycle(base, [day])
    if st["active"] or st["pending"] or st["certifying"]:
        return "not_ready", f"uncertified:{len(st['active'])}/{len(st['pending'])}/{len(st['certifying'])}"
    man, torn, mp = _manifest_entries(base, day)
    problems, files = [], []
    certified = {os.path.relpath(p, base) for p in st["certified"]}
    if torn:
        problems.append(f"manifest_torn_lines:{torn}")
    for rel in sorted(certified - set(man)):
        problems.append(f"certified_not_in_manifest:{rel}")
    for rel in sorted(set(man) - certified):
        problems.append(f"manifest_entry_without_file:{rel}")
    for d in day_dirs(base, [day]):
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            rel = os.path.relpath(p, base)
            if not f.endswith(SEGMENT_SUFFIXES):
                problems.append(f"unexpected_file:{rel}"); continue
            stt = os.stat(p)
            if stt.st_mode & 0o222:
                problems.append(f"not_read_only:{rel}")
            files.append({"path": rel, "bytes": stt.st_size})
    for rel in sorted(certified & set(man)):
        p = os.path.join(base, rel)
        try:
            with open(p + ".sha256", encoding="utf-8") as fh:
                side = fh.read().split()[0]
        except (OSError, IndexError):
            side = None
        if side != man[rel].get("sha256"):
            problems.append(f"sidecar_manifest_mismatch:{rel}")
        if not os.path.exists(p[:-9] + ".idx"):
            problems.append(f"idx_missing:{rel}")
    if problems:
        return "mismatch", problems[:50]
    with open(mp, "rb") as fh:
        msha = hashlib.sha256(fh.read()).hexdigest() if certified else None
    rec = {"record": "tsb.p2.forward.day_close", "record_version": 1, "day": day, "closed_ms": time.time_ns() // 1_000_000,
           "calendar": cal.params(), "segments": len(certified), "files": files,
           "bytes_total": sum(f["bytes"] for f in files), "manifest_file": os.path.relpath(mp, base) if certified else None,
           "manifest_sha256": msha, "boots": sorted({os.path.basename(r).split("-")[2] for r in certified})}
    dd = os.path.join(base, DAYS_DIR); os.makedirs(dd, exist_ok=True)
    path = os.path.join(dd, f"{day}.json")
    tmp = path + ".partial"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, sort_keys=True); fh.flush(); os.fsync(fh.fileno())
    os.rename(tmp, path); os.chmod(path, 0o444); _fsync_dir(dd)
    return "closed", rec


def check_closed_days(base: str) -> list:
    """Startup integrity (names and sizes only, once per start): every closed day's directories still hold exactly
    the files recorded at close. Anything else (a late write after a clock step, a missing or altered file) is a
    problem the caller must fail closed on."""
    problems = []
    for day in sorted(closed_days(base)):
        try:
            with open(os.path.join(base, DAYS_DIR, f"{day}.json"), encoding="utf-8") as fh:
                rec = json.load(fh)
            want = {f["path"]: f["bytes"] for f in rec["files"]}
        except (OSError, ValueError, KeyError, TypeError):
            problems.append(f"day_record_unreadable:{day}"); continue
        have = {}
        for d in day_dirs(base, [day]):
            for f in os.listdir(d):
                p = os.path.join(d, f)
                have[os.path.relpath(p, base)] = os.path.getsize(p)
        if have != want:
            extra, miss = sorted(set(have) - set(want)), sorted(set(want) - set(have))
            changed = sorted(k for k in set(have) & set(want) if have[k] != want[k])
            problems.append(f"closed_day_changed:{day}:extra={extra[:3]}:missing={miss[:3]}:size={changed[:3]}")
    return problems


def dataset_bytes(base: str, closed_cache: dict) -> int:
    """Total bytes of the logical dataset: closed days from their day-close records (cached; read once), open days
    and every non-raw directory by listing (O(open days + days)), never the full raw tree."""
    for day in closed_days(base) - set(closed_cache):
        try:
            with open(os.path.join(base, DAYS_DIR, f"{day}.json"), encoding="utf-8") as fh:
                closed_cache[day] = int(json.load(fh)["bytes_total"])
        except (OSError, ValueError, KeyError, TypeError):
            closed_cache[day] = 0                                    # unreadable: check_closed_days reports it
    total = sum(closed_cache.values())
    for d in day_dirs(base, open_days(base)):
        for f in os.listdir(d):
            try:
                total += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    for top in os.listdir(base) if os.path.isdir(base) else []:
        p = os.path.join(base, top)
        if top == "raw":
            continue
        if os.path.isfile(p):
            total += os.path.getsize(p); continue
        for root, _, files in os.walk(p):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return total


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
        try:
            pend = self.pending()
        except OSError:
            return {"alive": self.is_alive(), "fatal": self.fatal, "beat_age_ms": (now - self.beat_ns) // 1_000_000,
                    "pending": None, "oldest_pending_age_ms": None, "scan_error": True, "busy_ms": None,
                    "last_ms": None, "max_ms": None, "failures": self.stats["certification_failures"],
                    "certified": self.stats["segments_promoted"]}
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
        """Shutdown (F1): certify everything within the grace. True only if the certifier thread has STOPPED (joined,
        so no certification is mid-flight, incl. its manifest append) and nothing is pending/certifying."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end and self.is_alive():
            if not self.pending() and self.busy_since_ns is None:
                break
            self.nudge.set(); time.sleep(0.2)
        self.stop()
        self.join(max(0.0, end - time.monotonic()))
        if self.is_alive():
            return False
        if self.pending() and time.monotonic() < end:
            self.run_once()                                           # thread gone: finish inline within the grace
        return not self.pending()

    def stop(self) -> None:
        self._stop_evt.set(); self.nudge.set()


class SegmentWriter(threading.Thread):
    def __init__(self, data_dir: str, boot_id: str, q: queue.Queue, stats: dict, flush_interval_s: float = 2.0,
                 certify_grace_s: float = 300.0, certifier_mode: str = "thread"):
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
        self.certifier_mode = certifier_mode
        self.certifier = self._new_certifier()
        self.certifier_restarts = 0

    def _new_certifier(self):
        if self.certifier_mode == "process":                       # G3-F4: separate process, same cgroup
            from .certproc import ProcessCertifier
            return ProcessCertifier(self.base, self.boot_id, self.stats, lambda: self.run_record)
        return Certifier(self.base, self.boot_id, self.stats, lambda: self.run_record)

    # ---- lifecycle ----
    def start(self) -> None:
        super().start()
        self.certifier.start()

    def restart_certifier(self) -> None:
        old = self.certifier
        if hasattr(old, "_sync_stats"):                               # G3-F4 review: keep the dead worker's counters
            old._sync_stats()
        self.certifier = self._new_certifier()
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
            self.certified_all = self.certifier.drain(self.certify_grace_s) is True
            self.finished = True
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
            if self.pending_since_ns is None:                          # F8: from ENQUEUE (queue time included)
                self.pending_since_ns = rec.get("queued_ts_ns") or time.time_ns()
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
            if os.path.exists(seg.final + PENDING):                    # handed off already: certifier owns it
                self.certifier.submit(seg.final + PENDING); return
            self._quarantine(seg, f"finalize_failure:{type(e).__name__}")
            for orphan in (seg.final[:-9] + ".idx" + PENDING,):
                if os.path.exists(orphan):
                    quarantine_files(self.base, [orphan], "finalize_failure:orphan_idx", seg.name, self.stats)
            return
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


def complete_manifests(data_dir: str, boot_id: str, stats: dict, run_record=None) -> int:
    """Certified file without a manifest entry (a certifier died after the final rename, before the manifest
    append): checksum re-verified against its sidecar, fully re-validated, then the manifest entry is completed
    (recovered=True); mismatch -> quarantine. Used at startup recovery and by a RESTARTED certifier process before it
    reports ready (G3-F4 review), so a live certifier restart can never leave an unlisted certified segment."""
    n = 0
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
        if not os.path.exists(p[:-9] + ".idx") and os.path.exists(p[:-9] + ".idx" + PENDING):   # F2
            os.rename(p[:-9] + ".idx" + PENDING, p[:-9] + ".idx")
        rep = validate_segment(p)
        exp = _idx_records(p[:-9] + ".idx")
        if rep["decode_error"] or rep["invalid"] or rep["duplicates"] or exp is None or rep["records"] != exp:  # F10
            quarantine_files(data_dir, [p, p + ".sha256", p[:-9] + ".idx"], "recovery:certified_failed_validation",
                             os.path.basename(p), stats)
            continue
        for q in (p, p + ".sha256", p[:-9] + ".idx"):
            if os.path.exists(q):
                os.chmod(q, 0o444)
        _manifest_append(data_dir, p, rel, day, side, rep, run_record, boot_id, True)
        stats["recovered_manifest_completed"] = stats.get("recovered_manifest_completed", 0) + 1
        n += 1
    return n


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
    repair_manifests(data_dir, stats)                                 # F3
    dirs = day_dirs(data_dir, open_days(data_dir))                    # P2-CR: open days only (closed days are final)
    for root in dirs:                                                 # F4: finalize renames interrupted midway
        for f in os.listdir(root):
            p = os.path.join(root, f)
            if f.endswith(".jsonl.gz" + PENDING):
                stem = p[: -len(".jsonl.gz" + PENDING)]
                if os.path.exists(stem + ".idx.partial") and not os.path.exists(stem + ".idx" + PENDING):
                    os.rename(stem + ".idx.partial", stem + ".idx" + PENDING)
    for root in dirs:
        for f in sorted(os.listdir(root)):
            if not f.endswith(".jsonl.gz.partial"):
                continue
            p = os.path.join(root, f)
            stem = p[: -len(".jsonl.gz.partial")]
            rep = validate_segment(p)
            idx_now = stem + ".idx.partial" if os.path.exists(stem + ".idx.partial") else stem + ".idx" + PENDING
            expected = _idx_records(idx_now)
            if not rep["decode_error"] and not rep["invalid"] and expected is not None and rep["records"] == expected:
                if idx_now != stem + ".idx" + PENDING:
                    os.rename(idx_now, stem + ".idx" + PENDING)
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
            for ix in (stem + ".idx.partial", stem + ".idx" + PENDING):
                if os.path.exists(ix):
                    os.rename(ix, os.path.join(qdir, os.path.basename(ix) + ".orig"))
            stats["recovered_records"] += len(recs)
            try:
                seg_start = cal.hour_key_start_ms(f.split("-")[1][:11])
            except (ValueError, IndexError):
                seg_start = None
            gaps.append({"type": typ, "salvaged": len(recs), "last_salvaged_recv_ns": last, "source": f,
                         "segment_start_ms": seg_start})
    st = scan_lifecycle(data_dir)
    for p in sorted(st["certifying"] + st["pending"]):
        certify(data_dir, p, stats, boot_id, recovered=True)
        stats["recovered_pending_certified"] = stats.get("recovered_pending_certified", 0) + 1
    complete_manifests(data_dir, boot_id, stats)
    for root in day_dirs(data_dir, open_days(data_dir)):              # F4: orphan sidecars are never left silently
        for f in os.listdir(root):
            p = os.path.join(root, f)
            for suf in (".idx.partial", ".idx" + PENDING, ".idx", ".jsonl.gz.sha256"):
                if f.endswith(suf):
                    stem = p[: -len(suf)] if suf != ".jsonl.gz.sha256" else p[: -len(".sha256")][:-9]
                    if not any(os.path.exists(stem + ".jsonl.gz" + x) for x in ("", ".partial", PENDING, CERTIFYING)):
                        quarantine_files(data_dir, [p], "recovery:orphan_sidecar", f, stats)
                        stats["orphan_sidecars"] = stats.get("orphan_sidecars", 0) + 1
                    break
    return gaps


def new_stats() -> dict:
    """Shared counters (written by the writer thread and the async tasks; GIL-safe increments)."""
    return {"written": collections.Counter(), "dropped": collections.Counter(), "duplicates_dropped": 0,
            "write_errors": 0, "last_write_error": None, "segments_promoted": 0, "segments_quarantined": 0,
            "recovered_records": 0, "malformed": 0, "rejected": collections.Counter(),
            "writer_rejected": collections.Counter(), "duplicates_by_type": collections.Counter(),
            "unknown_stream": 0, "unknown_event": 0, "handler_errors": 0,
            "segments_finalized": 0, "certification_failures": 0}
