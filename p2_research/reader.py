"""Schema-v2 reader for the continuous forward dataset (resolves R13). Stdlib only; never imports ``p2_forward``.

Contract (see docs/p2/P2C_RESEARCH_LAYER.md, section "Schema reader"):
  * explicit schema identification: dataset.json and every record must be ``tsb.p2.forward`` with a SUPPORTED
    ``schema_version`` (currently {2}); anything else (older, newer, unknown type) raises ``UnsupportedSchema``;
  * SEALED days only by default: ``seals/D.json`` with result PASS for this dataset, day-close and manifest SHA-256
    equal to the seal, every segment's SHA-256 recomputed and equal to the manifest and its sidecar;
  * the active (unsealed) day is reachable only with ``experimental_active_day=True``; the bundle is then marked
    ``reproducible=False`` and the dataset builder refuses to mix it with sealed days;
  * deterministic: input order never matters (records are sorted by a total order), identical duplicates are
    dropped and counted, conflicting duplicates fail closed (``AmbiguityError``);
  * quality metadata is preserved, never hidden: clock_suspect, unchanged, recoverability, gap causes and
    day_split, health state, downtime, run boundaries, universe epochs;
  * read-only: files are opened for reading only; nothing is ever written under the dataset directory.
"""
from __future__ import annotations

import bisect
import collections
import datetime as dt
import gzip
import hashlib
import json
import os

SCHEMA_NAME = "tsb.p2.forward"
SUPPORTED_SCHEMA_VERSIONS = frozenset({2})
READER_VERSION = "p2c-reader-v2.2"                # v2.2: epochs beyond the range end ignored (P2-C1 R1)
KINDS = ("book", "depth", "market", "candle", "clock", "universe", "gap", "lifecycle", "health")
SAMPLED = ("book", "depth", "market")
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
PRODUCTION_CALENDAR = {"base": "1970-01-01T00:00:00+00:00", "epoch_hour": 0, "hour_ms": 3_600_000}
DEPTH_K = 10                                     # depth aggregates use the first 10 levels (depth20 comparable to 10)
FIELDS = {"schema": str, "schema_version": int, "obs_id": str, "type": str, "source": str, "transport": str,
          "endpoint": str, "recv_ts_ns": int, "observed_at_ms": int, "available_at_ms": int, "unchanged": bool,
          "clock_suspect": bool, "collector_version": str, "boot_id": str}
NULLABLE = ("symbol", "tier", "cadence_ms", "sample_ms", "exchange_event_time_ms", "exchange_seq", "queued_ts_ns",
            "blk", "recoverability", "payload")
UNCERTIFIED_SUFFIXES = (".partial", ".pending", ".certifying", ".tmp")
SEG_SUFFIX = ".jsonl.gz"
# Fallback freshness limits (SCHEMA.md section 3) when a run record carries none.
DEFAULT_STALE = {"book_t0": 120_000, "book_t12_dead": 600_000, "book_t12_suspect": 120_000,
                 "depth_by_tier": {"t0": 2_000, "t1": 180_000, "t2": 15_000}, "market": 10_000}


class ReaderError(Exception):
    def __init__(self, code: str, detail=None):
        super().__init__(f"{code}: {detail}" if detail is not None else code)
        self.code, self.detail = code, detail


class UnsupportedSchema(ReaderError):
    pass


class NotSealed(ReaderError):
    pass


class IntegrityError(ReaderError):
    pass


class AmbiguityError(ReaderError):
    pass


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def day_start_ms(day: str) -> int:
    d = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp()) * 1000


def day_key(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def hour_key(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).strftime("%Y%m%dT%H")


def _f(x, what):
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise IntegrityError("UNPARSABLE_NUMBER", what) from None
    if v != v or v in (float("inf"), float("-inf")):
        raise IntegrityError("NON_FINITE_NUMBER", what)
    return v


# ------------------------------------------------------------------ dataset identity ------
def open_dataset(base: str) -> dict:
    p = os.path.join(base, "dataset.json")
    if not os.path.exists(p):
        raise IntegrityError("DATASET_IDENTITY_MISSING", base)
    d = _json(p)
    if d.get("record") != "tsb.p2.forward.dataset" or d.get("record_version") != 1:
        raise UnsupportedSchema("DATASET_RECORD_UNSUPPORTED", [d.get("record"), d.get("record_version")])
    if d.get("schema") != SCHEMA_NAME:
        raise UnsupportedSchema("SCHEMA_NAME", d.get("schema"))
    if d.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchema("SCHEMA_VERSION_UNSUPPORTED", d.get("schema_version"))
    if d.get("calendar") != PRODUCTION_CALENDAR:
        raise UnsupportedSchema("NON_PRODUCTION_CALENDAR", d.get("calendar"))
    if not d.get("dataset_id"):
        raise IntegrityError("DATASET_ID_MISSING")
    return {**d, "_sha256": sha256_file(p)}


def sealed_days(base: str) -> list:
    """Days with a PASS seal for this dataset (no verification here; ``load_days`` verifies)."""
    sd = os.path.join(base, "seals")
    out = []
    for f in sorted(os.listdir(sd)) if os.path.isdir(sd) else []:
        if len(f) == 15 and f.endswith(".json"):
            try:
                if _json(os.path.join(sd, f)).get("result") == "PASS":
                    out.append(f[:-5])
            except (OSError, ValueError):
                continue
    return out


def _manifest(base: str, day: str) -> dict:
    mp = os.path.join(base, "manifests", f"{day}.jsonl")
    man = {}
    if not os.path.exists(mp):
        return man
    with open(mp, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            e = json.loads(line)
            if e["segment"] in man and man[e["segment"]] != e:
                raise IntegrityError("MANIFEST_CONFLICTING_ENTRY", e["segment"])
            man[e["segment"]] = e
    return man


def _seal_check(base: str, ds: dict, day: str) -> dict:
    sp = os.path.join(base, "seals", f"{day}.json")
    if not os.path.exists(sp):
        raise NotSealed("DAY_NOT_SEALED", day)
    s = _json(sp)
    if s.get("record") != "tsb.p2.forward.day_seal" or s.get("record_version") != 1:
        raise UnsupportedSchema("SEAL_RECORD_UNSUPPORTED", [s.get("record"), s.get("record_version")])
    if s.get("result") != "PASS":
        raise NotSealed("SEAL_NOT_PASS", [day, s.get("result")])
    if s.get("day") != day or s.get("dataset_id") != ds["dataset_id"]:
        raise IntegrityError("SEAL_IDENTITY_MISMATCH", [day, s.get("day"), s.get("dataset_id")])
    dcp = os.path.join(base, "days", f"{day}.json")
    if not os.path.exists(dcp):
        raise IntegrityError("DAY_CLOSE_MISSING", day)
    if s.get("day_close_sha256") is not None and sha256_file(dcp) != s["day_close_sha256"]:
        raise IntegrityError("DAY_CLOSE_SHA_MISMATCH", day)
    mp = os.path.join(base, "manifests", f"{day}.jsonl")
    if not os.path.exists(mp) or sha256_file(mp) != s.get("manifest_sha256"):
        raise IntegrityError("MANIFEST_SHA_MISMATCH", day)
    rpp = os.path.join(base, "seals", f"{day}.report.json")
    if s.get("report_sha256") is not None and (not os.path.exists(rpp) or sha256_file(rpp) != s["report_sha256"]):
        raise IntegrityError("SEAL_REPORT_SHA_MISMATCH", day)
    dc = _json(dcp)
    return {"seal_sha256": sha256_file(sp), "day_close_sha256": sha256_file(dcp), "manifest_sha256": sha256_file(mp),
            "day_close_files": sorted(f["path"] for f in dc.get("files", []) if f["path"].endswith(SEG_SUFFIX))}


def _segments(base: str, day: str, hours=None) -> tuple:
    """(certified segment paths of ``day`` [restricted to ``hours``], uncertified paths seen)."""
    raw = os.path.join(base, "raw")
    segs, unc = [], []
    for t in sorted(os.listdir(raw)) if os.path.isdir(raw) else []:
        dd = os.path.join(raw, t, day)
        if not os.path.isdir(dd):
            continue
        for f in sorted(os.listdir(dd)):
            if hours is not None and not any(f"-{h}Z-" in f for h in hours):
                continue
            rel = os.path.relpath(os.path.join(dd, f), base)
            if f.endswith(UNCERTIFIED_SUFFIXES):
                unc.append(rel)
            elif f.endswith(SEG_SUFFIX):
                segs.append(rel)
    return segs, unc


# ------------------------------------------------------------------ record validation ------
def validate_record(r) -> None:
    if not isinstance(r, dict):
        raise IntegrityError("RECORD_NOT_OBJECT")
    if r.get("schema") != SCHEMA_NAME:
        raise UnsupportedSchema("RECORD_SCHEMA_NAME", r.get("schema"))
    v = r.get("schema_version")
    if not isinstance(v, int) or isinstance(v, bool) or v not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchema("RECORD_SCHEMA_VERSION_UNSUPPORTED", [r.get("obs_id"), v])
    if r.get("type") not in KINDS:
        raise UnsupportedSchema("UNKNOWN_RECORD_TYPE", [r.get("obs_id"), r.get("type")])
    for k, t in FIELDS.items():
        if k not in r or not isinstance(r[k], t) or (t is int and isinstance(r[k], bool)):
            raise IntegrityError("FIELD_MISSING_OR_TYPE", [r.get("obs_id"), k])
    for k in NULLABLE:
        if k not in r:
            raise IntegrityError("FIELD_MISSING", [r.get("obs_id"), k])
    if r["observed_at_ms"] != r["recv_ts_ns"] // 1_000_000:
        raise IntegrityError("OBSERVED_NE_RECV", r["obs_id"])
    if r["type"] == "candle":
        p = r["payload"]
        if not (isinstance(p, list) and len(p) >= 8):
            raise IntegrityError("CANDLE_PAYLOAD", r["obs_id"])
        if r["available_at_ms"] != max(int(p[6]) + 1, r["observed_at_ms"]):
            raise IntegrityError("CANDLE_AVAILABILITY", r["obs_id"])
    elif r["available_at_ms"] != r["observed_at_ms"]:
        raise IntegrityError("AVAILABLE_NE_OBSERVED", r["obs_id"])
    if r["type"] in SAMPLED:
        s = r["sample_ms"]
        if not isinstance(s, int) or r["recv_ts_ns"] > s * 1_000_000:
            raise IntegrityError("OBSERVED_AFTER_SAMPLE", r["obs_id"])
        if r["type"] == "depth" and not (isinstance(r.get("depth_levels"), int) and r["depth_levels"] > 0):
            raise IntegrityError("DEPTH_LEVELS_MISSING", r["obs_id"])
        if r["type"] == "market" and not isinstance(r.get("component_recv_ms"), dict):
            raise IntegrityError("MARKET_FIELDS_MISSING", r["obs_id"])


# ------------------------------------------------------------------ the bundle ------
class Bundle:
    """Normalized, read-only view of one or more consecutive days (plus the last day's spillover hour).

    Sampled streams are kept as compact tuples sorted by (available_at_ms, sample_ms); see BOOK_/DEPTH_ fields.
    """
    BOOK_FIELDS = ("available_at_ms", "sample_ms", "observed_at_ms", "bid", "ask", "bid_qty", "ask_qty", "seq",
                   "unchanged", "clock_suspect", "tier", "cadence_ms", "boot8")
    DEPTH_FIELDS = ("available_at_ms", "sample_ms", "observed_at_ms", "bid_notional", "ask_notional",
                    "top1_notional", "n_bid", "n_ask", "depth_levels", "seq", "unchanged", "clock_suspect", "tier",
                    "cadence_ms", "boot8")

    def __init__(self):
        self.days, self.mode, self.reproducible = [], "sealed", True
        self.range_start_ms = self.range_end_ms = self.coverage_end_ms = None
        self.book = collections.defaultdict(list)
        self.depth = collections.defaultdict(list)
        self.market = []                 # (avail, sample, observed, startup_complete, clock_suspect, {sym: (c, o, q)})
        self.candles = collections.defaultdict(dict)   # (sym, tf) -> open_ms -> (open,o,h,l,c,v,close,qv,avail,cs)
        self.gaps, self.health, self.lifecycle, self.clock = [], [], [], []
        self.universe_docs = {}          # universe_id -> {tiers, file, sha256}
        self.epochs = []                 # sorted (effective_from_ms, available_at_ms, universe_id, kind, boot8)
        self.runs = []                   # run windows
        self.run_sha = {}                # boot_id -> run-record SHA-256
        self.provenance = {"segments": [], "days": {}, "runs": {}, "universe_files": {}, "schema_versions": [2]}
        self.quality = collections.Counter()
        self._keys = {}

    # -------- sorted-key helpers (bisect) --------
    def keys(self, kind: str, sym=None) -> list:
        k = (kind, sym)
        if k not in self._keys:
            seq = {"book": self.book.get(sym, []), "depth": self.depth.get(sym, []), "market": self.market,
                   "health": self.health, "lifecycle": self.lifecycle}[kind]
            self._keys[k] = [x[0] for x in seq]
        return self._keys[k]

    def latest(self, kind: str, sym, t_ms: int):
        """Latest element with available_at_ms <= t_ms (None if none)."""
        seq = {"book": self.book.get(sym, []), "depth": self.depth.get(sym, []), "market": self.market,
               "health": self.health, "lifecycle": self.lifecycle}[kind]
        i = bisect.bisect_right(self.keys(kind, sym), t_ms)
        return seq[i - 1] if i else None

    def first_after(self, kind: str, sym, t_ms: int):
        """First element with available_at_ms > t_ms (labels / execution only, never features)."""
        seq = {"book": self.book.get(sym, []), "depth": self.depth.get(sym, [])}[kind]
        i = bisect.bisect_right(self.keys(kind, sym), t_ms)
        return seq[i] if i < len(seq) else None

    def window(self, kind: str, sym, lo_ms: int, hi_ms: int) -> list:
        """Elements with lo < available_at_ms <= hi."""
        seq = {"book": self.book.get(sym, []), "depth": self.depth.get(sym, []), "market": self.market}[kind]
        ks = self.keys(kind, sym)
        return seq[bisect.bisect_right(ks, lo_ms):bisect.bisect_right(ks, hi_ms)]

    def epoch_at(self, t_ms: int):
        """Universe epoch as KNOWN at t: effective_from <= t AND its announcing record available <= t."""
        best = None
        for e in self.epochs:
            if e["effective_from_ms"] <= t_ms and e["available_at_ms"] <= t_ms:
                if best is None or (e["effective_from_ms"], e["available_at_ms"]) >= (best["effective_from_ms"],
                                                                                      best["available_at_ms"]):
                    best = e
        return best

    def run_at(self, t_ms: int):
        for r in self.runs:
            if r["ws_start_ms"] is not None and r["ws_start_ms"] <= t_ms and (r["end_ms"] is None or t_ms < r["end_ms"]):
                return r
        return None

    def summary(self) -> dict:
        return {"days": list(self.days), "mode": self.mode, "reproducible": self.reproducible,
                "book_records": sum(len(v) for v in self.book.values()),
                "depth_records": sum(len(v) for v in self.depth.values()), "market_records": len(self.market),
                "candles": sum(len(v) for v in self.candles.values()), "gaps": len(self.gaps),
                "health": len(self.health), "lifecycle": len(self.lifecycle), "epochs": len(self.epochs),
                "runs": len(self.runs), "quality": dict(sorted(self.quality.items()))}


def read_segment(B: Bundle, base: str, rel: str, d: str, mans: dict, ctrl: dict, spill: bool) -> None:
    """Verify one certified segment (manifest SHA, sidecar SHA, record count), validate and ingest every record."""
    if d not in mans:
        mans[d] = _manifest(base, d)
    p = os.path.join(base, rel)
    dig = sha256_file(p)
    ent = mans[d].get(rel)
    if ent is None or ent.get("sha256") != dig:
        raise IntegrityError("SEGMENT_SHA_NE_MANIFEST", rel)
    try:
        with open(p + ".sha256", encoding="utf-8") as fh:
            side = fh.read().split()[0]
    except (OSError, IndexError):
        side = None
    if side != dig:
        raise IntegrityError("SEGMENT_SHA_NE_SIDECAR", rel)
    n = 0
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                validate_record(r)
                _ingest(B, r, ctrl)
                n += 1
    except (OSError, EOFError, ValueError) as e:
        if isinstance(e, ReaderError):
            raise
        raise IntegrityError("SEGMENT_DECODE_ERROR", f"{rel}:{type(e).__name__}") from None
    if ent.get("records") is not None and ent["records"] != n:
        raise IntegrityError("SEGMENT_RECORD_COUNT_NE_MANIFEST", rel)
    B.provenance["segments"].append({"path": rel, "sha256": dig, "records": n, "spill": spill})


# ------------------------------------------------------------------ loading ------
def load_days(base: str, days: list, experimental_active_day: bool = False) -> Bundle:
    """Load consecutive ``days`` (YYYY-MM-DD). Sealed days only unless ``experimental_active_day`` (one day only)."""
    ds = open_dataset(base)
    days = sorted(set(days))
    if not days:
        raise ReaderError("NO_DAYS")
    for a, b in zip(days, days[1:]):
        if day_start_ms(b) - day_start_ms(a) != DAY_MS:
            raise ReaderError("DAYS_NOT_CONSECUTIVE", [a, b])
    B = Bundle()
    B.days, B.dataset = days, {k: v for k, v in ds.items()}
    B.range_start_ms, B.range_end_ms = day_start_ms(days[0]), day_start_ms(days[-1]) + DAY_MS
    sealed = {}
    if experimental_active_day:
        if len(days) != 1:
            raise ReaderError("EXPERIMENTAL_SINGLE_DAY_ONLY", days)
        if os.path.exists(os.path.join(base, "seals", f"{days[0]}.json")):
            raise ReaderError("EXPERIMENTAL_FLAG_ON_SEALED_DAY", days[0])
        B.mode, B.reproducible = "experimental_active_day", False
    else:
        for d in days:
            sealed[d] = _seal_check(base, ds, d)
            B.provenance["days"][d] = {k: v for k, v in sealed[d].items() if k != "day_close_files"}
    # -------- segment list: own days + spillover hour (first hour of the next day) --------
    want = []
    for d in days:
        segs, unc = _segments(base, d)
        if unc and not experimental_active_day:
            raise IntegrityError("UNCERTIFIED_FILE_IN_SEALED_DAY", unc[:3])
        B.quality["uncertified_files_skipped"] += len(unc)
        if not experimental_active_day and sorted(segs) != sealed[d]["day_close_files"]:
            raise IntegrityError("DAY_SEGMENTS_NE_DAY_CLOSE", d)
        want += [(s, d) for s in segs]
    nxt = day_key(B.range_end_ms)
    spill, unc = _segments(base, nxt, hours={hour_key(B.range_end_ms)})
    if unc and not experimental_active_day:
        raise IntegrityError("SPILLOVER_NOT_FINAL", unc[:3])
    want += [(s, nxt) for s in spill]
    B.coverage_end_ms = B.range_end_ms                 # candles closing <= day end are fetched in the spill hour
    mans = {}
    recs_ctrl = {}
    for rel, d in sorted(set(want)):
        read_segment(B, base, rel, d, mans, recs_ctrl, spill=d == nxt)
    _finalize(B, base, recs_ctrl)
    return B


_INTERN = {}


def _i(v):
    """Share identical small immutable values (boot ids, cadences, tiers) across millions of tuples (memory)."""
    return _INTERN.setdefault(v, v)


def _ingest(B: Bundle, r: dict, ctrl: dict) -> None:
    t = r["type"]
    cs = r["clock_suspect"]
    if cs:
        B.quality[f"clock_suspect.{t}"] += 1
    boot8 = _i(r["boot_id"][:8])
    if t == "book":
        p = r["payload"] or {}
        if p.get("s") not in (None, r["symbol"]):
            raise IntegrityError("BOOK_SYMBOL_MISMATCH", r["obs_id"])
        B.book[r["symbol"]].append((r["available_at_ms"], r["sample_ms"], r["observed_at_ms"],
                                   _f(p.get("b"), r["obs_id"]), _f(p.get("a"), r["obs_id"]),
                                   _f(p.get("B"), r["obs_id"]), _f(p.get("A"), r["obs_id"]), r["exchange_seq"],
                                   r["unchanged"], cs, _i(r["tier"]), _i(r["cadence_ms"]), boot8))
        if r["unchanged"]:
            B.quality["unchanged.book"] += 1
    elif t == "depth":
        p = r["payload"] or {}
        bids, asks = p.get("bids") or [], p.get("asks") or []
        bn = sum(_f(x[0], r["obs_id"]) * _f(x[1], r["obs_id"]) for x in bids[:DEPTH_K])
        an = sum(_f(x[0], r["obs_id"]) * _f(x[1], r["obs_id"]) for x in asks[:DEPTH_K])
        t1 = (_f(bids[0][0], 0) * _f(bids[0][1], 0) if bids else 0.0) + (_f(asks[0][0], 0) * _f(asks[0][1], 0) if asks else 0.0)
        B.depth[r["symbol"]].append((r["available_at_ms"], r["sample_ms"], r["observed_at_ms"], bn, an, t1, len(bids),
                                    len(asks), _i(r["depth_levels"]), r["exchange_seq"], r["unchanged"], cs,
                                    _i(r["tier"]), _i(r["cadence_ms"]), boot8))
        if r["unchanged"]:
            B.quality["unchanged.depth"] += 1
    elif t == "market":
        comp = {}
        for m in r["payload"] or []:
            s = m.get("s")
            if not isinstance(s, str):
                raise IntegrityError("MARKET_COMPONENT", r["obs_id"])
            comp[s] = (_f(m.get("c"), s), _f(m.get("o"), s), _f(m.get("q"), s))
        B.market.append((r["available_at_ms"], r["sample_ms"], r["observed_at_ms"], bool(r.get("startup_complete")),
                         cs, comp, r["obs_id"]))
    elif t == "candle":
        k = r["payload"]
        sym, tf, open_ms = r["obs_id"].split("|")
        if tf not in TF_MS or int(k[0]) != int(open_ms) or sym != r["symbol"]:
            raise IntegrityError("CANDLE_IDENTITY", r["obs_id"])
        if int(k[0]) % TF_MS[tf] or int(k[6]) != int(k[0]) + TF_MS[tf] - 1:
            raise IntegrityError("CANDLE_MISALIGNED", r["obs_id"])
        tup = (int(k[0]), _f(k[1], "o"), _f(k[2], "h"), _f(k[3], "l"), _f(k[4], "c"), _f(k[5], "v"), int(k[6]),
               _f(k[7], "qv"), r["available_at_ms"], cs)
        cur = B.candles[(sym, tf)].get(tup[0])
        if cur is None:
            B.candles[(sym, tf)][tup[0]] = tup
        elif cur[:8] == tup[:8]:                   # idempotent re-fetch: keep the EARLIEST availability (first known)
            B.quality["duplicates_dropped.candle"] += 1
            if tup[8] < cur[8]:
                B.candles[(sym, tf)][tup[0]] = tup
        else:
            raise AmbiguityError("CONFLICTING_CANDLE", r["obs_id"])
    else:                                            # control records: dedupe by obs_id on canonical content
        c = canon(r)
        prev = ctrl.get(r["obs_id"])
        if prev is not None:
            if prev[0] != c:
                raise AmbiguityError("CONFLICTING_DUPLICATE", r["obs_id"])
            B.quality[f"duplicates_dropped.{t}"] += 1
            return
        ctrl[r["obs_id"]] = (c, r)


def _dedupe_sampled(B: Bundle, kind: str, store: dict, flagged: set | None = None) -> None:
    for sym, lst in store.items():
        lst.sort(key=lambda x: (x[1], x[11 if kind == "book" else 13], x[0], x[7 if kind == "book" else 9]))
        out = []
        for x in lst:
            if out and out[-1][1] == x[1]:
                if out[-1] == x:
                    B.quality[f"duplicates_dropped.{kind}"] += 1
                    continue
                raise AmbiguityError("CONFLICTING_SAMPLE", [kind, sym, x[1]])
            out.append(x)
        if any(a[0] > b[0] for a, b in zip(out, out[1:])):
            if flagged is None:
                B.quality[f"out_of_order_resolved.{kind}"] += 1
            else:
                flagged.add((kind, sym))
        out.sort(key=lambda x: (x[0], x[1]))
        store[sym] = out


def _finalize(B: Bundle, base: str, ctrl: dict) -> None:
    finalize_sampled(B)
    recs = sorted((v[1] for v in ctrl.values()), key=lambda r: (r["available_at_ms"], r["recv_ts_ns"], r["obs_id"]))
    boots = set()
    process_control(B, recs, boots)
    _runs(B, base, boots)
    _epochs(B, base)
    # observation horizon: the latest availability of anything loaded. Decisions after it have no data (active day /
    # collector stopped); the builder excludes them instead of emitting rows of nulls.
    ends = [v[-1][0] for v in B.book.values() if v] + [v[-1][0] for v in B.depth.values() if v]
    ends += [B.market[-1][0]] if B.market else []
    ends += [r["available_at_ms"] for r in recs[-1:]]
    B.observed_until_ms = max(ends) if ends else None


def finalize_sampled(B: Bundle, flagged: set | None = None) -> None:
    """Dedupe + availability-sort the sampled streams (book/depth/market). ``flagged`` (streaming only) collects the
    (kind, symbol) pairs whose sample order had availability inversions instead of counting them here."""
    _dedupe_sampled(B, "book", B.book, flagged)
    _dedupe_sampled(B, "depth", B.depth, flagged)
    B.market.sort(key=lambda x: (x[1], x[0]))
    mk = []
    for x in B.market:
        if mk and mk[-1][1] == x[1]:
            if mk[-1] == x:
                B.quality["duplicates_dropped.market"] += 1
                continue
            raise AmbiguityError("CONFLICTING_SAMPLE", ["market", x[1]])
        mk.append(x)
    B.market = sorted(mk, key=lambda x: (x[0], x[1]))


def process_control(B: Bundle, recs: list, boots: set) -> None:
    """Append control records (already deduplicated, sorted by availability) to gaps/health/lifecycle/clock."""
    for r in recs:
        t, p = r["type"], r["payload"] or {}
        boots.add(r["boot_id"])
        if t == "gap":
            g = {"available_at_ms": r["available_at_ms"], "stream_key": p.get("stream_key"),
                 "first_missing_ms": p.get("first_missing_ms"), "last_missing_ms": p.get("last_missing_ms"),
                 "cadence_ms": p.get("cadence_ms"), "cause": p.get("cause"), "causes": p.get("causes") or [p.get("cause")],
                 "day_split": bool(p.get("day_split")), "open_at_stop": bool(p.get("open_at_stop")),
                 "recoverability": r["recoverability"], "boot8": r["boot_id"][:8], "obs_id": r["obs_id"]}
            if not isinstance(g["first_missing_ms"], int) or not isinstance(g["last_missing_ms"], int) or \
                    not isinstance(g["cadence_ms"], int) or g["last_missing_ms"] < g["first_missing_ms"]:
                raise IntegrityError("GAP_FIELDS", r["obs_id"])
            g["end_ms"] = g["last_missing_ms"] + g["cadence_ms"]
            B.gaps.append(g)
            B.quality[f"gap_cause.{g['cause']}"] += 1
            if g["day_split"]:
                B.quality["gap_day_split"] += 1
        elif t == "health":
            B.health.append((r["available_at_ms"], p.get("state"), frozenset(p.get("streams_not_observing") or []),
                             tuple(p.get("reasons") or [])))
            if p.get("state") != "HEALTHY":
                B.quality["health_not_healthy_records"] += 1
        elif t == "lifecycle":
            B.lifecycle.append((r["available_at_ms"], p.get("event"), p, r["boot_id"][:8]))
        elif t == "clock":
            B.clock.append((r["available_at_ms"], p.get("serverTime"), r["clock_suspect"]))
        elif t == "universe":
            pass                                      # artifacts are read from universe/ by the epoch's claimed SHA


def _runs(B: Bundle, base: str, boots: set) -> None:
    rd = os.path.join(base, "runs")
    chain = []
    for f in sorted(os.listdir(rd)) if os.path.isdir(rd) else []:
        if f.startswith("run-") and f.endswith(".json"):
            rr = _json(os.path.join(rd, f))
            if rr.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
                raise UnsupportedSchema("RUN_RECORD_SCHEMA_VERSION", f)
            boot = rr["boot_id"]
            dtp = os.path.join(rd, f"downtime-{boot}.json")
            dtr = _json(dtp) if os.path.exists(dtp) else None
            stp = os.path.join(base, "control", f"stop-{boot[:8]}.json")
            stop = _json(stp) if os.path.exists(stp) else None
            chain.append({"boot_id": boot, "created_ms": rr.get("created_ms"), "record": rr, "downtime": dtr,
                          "stop": stop, "sha256": sha256_file(os.path.join(rd, f))})
    chain.sort(key=lambda x: (x["created_ms"], x["boot_id"]))
    for i, c in enumerate(chain):
        ws = (c["downtime"] or {}).get("until_ms")
        end = (c["stop"] or {}).get("stop_requested_ms")
        if end is None and i + 1 < len(chain):
            nd = chain[i + 1]["downtime"] or {}
            end = nd.get("from_ms") if nd.get("from_ms") is not None else nd.get("until_ms")
        sem = (c["record"].get("semantics") or {}).get("stale_ms") or DEFAULT_STALE
        B.runs.append({"boot_id": c["boot_id"], "boot8": c["boot_id"][:8], "ws_start_ms": ws, "end_ms": end,
                       "clean_stop": c["stop"] is not None, "downtime_cause": (c["downtime"] or {}).get("cause"),
                       "downtime_from_ms": (c["downtime"] or {}).get("from_ms"), "stale_ms": sem,
                       "cadence_ms": (c["record"].get("sampling_profile") or {}).get("cadence_ms")})
        B.run_sha[c["boot_id"]] = c["sha256"]
    check_run_boots(B, boots)
    # downtime intervals intersecting the range (explicit; never stitched)
    iv = []
    prev_end = None
    for r in B.runs:
        if r["ws_start_ms"] is None:
            continue
        lo = prev_end if prev_end is not None else B.range_start_ms
        if r["ws_start_ms"] > lo:
            a, b = max(lo, B.range_start_ms), min(r["ws_start_ms"], B.range_end_ms)
            if b > a:
                iv.append({"from_ms": a, "until_ms": b, "cause": r["downtime_cause"]})
        prev_end = r["end_ms"] if r["end_ms"] is not None else B.range_end_ms
    if prev_end is not None and prev_end < B.range_end_ms:
        iv.append({"from_ms": max(prev_end, B.range_start_ms), "until_ms": B.range_end_ms, "cause": "collector_stopped"})
    B.downtime = iv
    B.quality["downtime_ms"] = sum(x["until_ms"] - x["from_ms"] for x in iv)


def check_run_boots(B: Bundle, boots: set) -> None:
    """Every record's boot_id must belong to the run chain; record the run-record SHA of each boot seen."""
    missing = boots - set(B.run_sha)
    if missing:
        raise IntegrityError("RECORD_OF_UNKNOWN_RUN", sorted(missing)[:3])
    for boot in boots:
        B.provenance["runs"][boot] = B.run_sha[boot]


def _universe_doc(B: Bundle, base: str, meta: dict) -> dict:
    uid = meta.get("universe_id")
    if uid in B.universe_docs:
        return B.universe_docs[uid]
    f = meta.get("file")
    p = os.path.join(base, f) if f else None
    if not p or not os.path.exists(p) or sha256_file(p) != meta.get("sha256"):
        raise IntegrityError("UNIVERSE_FILE_MISSING_OR_SHA_MISMATCH", [uid, f])
    doc = _json(p)
    if doc.get("universe_id") != uid:
        raise IntegrityError("UNIVERSE_ID_MISMATCH", uid)
    tiers = {}
    for tier, key in ((0, "tier0"), (1, "tier1"), (2, "tier2")):
        for s in doc.get(key) or []:
            if s in tiers:
                raise AmbiguityError("SYMBOL_IN_TWO_TIERS", [uid, s])
            tiers[s] = tier
    B.universe_docs[uid] = {"tiers": tiers, "file": f, "sha256": meta.get("sha256")}
    B.provenance["universe_files"][f] = meta.get("sha256")
    return B.universe_docs[uid]


def _epochs(B: Bundle, base: str, items=None) -> None:
    """Universe epochs from lifecycle records (all of ``B.lifecycle`` or only the new ``items`` when streaming)."""
    for avail, ev, p, boot8 in (B.lifecycle if items is None else items):
        if ev == "universe_active":
            meta, eff, kind = p, p.get("effective_from_ms"), "ws_start"
        elif ev == "universe_transition":
            meta, eff, kind = p, p.get("effective_from_ms"), "transition"
        elif ev == "day_checkpoint":
            meta = p.get("universe") or {}
            eff, kind = p.get("day_start_ms"), "checkpoint"
        else:
            continue
        if not isinstance(eff, int):
            raise IntegrityError("EPOCH_EFFECTIVE_FROM_MISSING", [ev, boot8])
        if max(eff, avail) >= B.range_end_ms:
            # announced in the spill-over hour for the NEXT day (e.g. the D+1 universe refresh at 00:10): it can never
            # be the epoch known at a decision time of this range; its artifact is not opened (P2-C1 regression R1)
            B.quality["universe_epochs_beyond_range_ignored"] += 1
            continue
        doc = _universe_doc(B, base, meta)
        B.epochs.append({"effective_from_ms": eff, "available_at_ms": avail, "universe_id": meta.get("universe_id"),
                         "kind": kind, "boot8": boot8, "tiers": doc["tiers"]})
    B.epochs.sort(key=lambda e: (e["effective_from_ms"], e["available_at_ms"], e["universe_id"]))
    B.quality["universe_epochs"] = len(B.epochs)
    B.quality["universe_transitions"] = sum(1 for e in B.epochs if e["kind"] == "transition")
