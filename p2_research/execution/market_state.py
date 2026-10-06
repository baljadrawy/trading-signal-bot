"""PIT market state for execution research (Execution Adapter side of the boundary).

Adapter: ``load_sealed`` reads SEALED days of the schema-v2 forward dataset through the P2-C reader's verification
(dataset identity, day seal, day-close listing, manifest / sidecar SHA-256, record count, per-record validation,
run chain, universe epochs) and keeps what execution needs: bookTicker states, depth ladders (with levels, unlike the
P2-C bundle which keeps only depth aggregates), stream confirmation boundaries, health / lifecycle / clock / gap
control records, run windows and universe epochs. Stdlib only; never imports ``p2_forward``; read-only.

Canonical state: book tuple ``BOOK`` and depth tuple ``DEPTH`` (field names below) plus control context.

PIT: ``PITMarketView(state, horizon_ms)`` is the ONLY path the execution model uses. Every accessor refuses a time
after the horizon (``PITViolation``) and returns only elements with ``available_at_ms <= t`` (re-asserted on every
returned element, so a faulty source cannot leak a future record).

Memory: with ``query_times`` the loader keeps, per stream, only the record that is the latest available at or
before each query time (bucketed by the first query time >= available_at), which is exact for those times and
bounded by (#streams x #query times). Without ``query_times`` everything is kept (tests / small data).
"""
from __future__ import annotations

import array
import bisect
import collections
import gzip
import json
import os
import zlib

from .. import reader as RD

LOADER_VERSION = "p2x-state-v1"
BOOK = ("available_at_ms", "sample_ms", "observed_at_ms", "bid", "ask", "bid_qty", "ask_qty", "seq", "unchanged",
        "clock_suspect", "tier", "cadence_ms", "boot8")
DEPTH = ("available_at_ms", "sample_ms", "observed_at_ms", "bids", "asks", "depth_levels", "seq", "unchanged",
         "clock_suspect", "tier", "cadence_ms", "boot8")
CONN_EVENTS = ("ws_connected", "ws_disconnected", "ws_connect_failed", "ws_rotation", "data_stall_reconnect",
               "ws_task_dead", "controlled_reconnect_test")


class PITViolation(Exception):
    pass


class StateError(Exception):
    pass


class _Stream:
    """Records of one (kind, symbol) sorted by bucket key; ``latest(t)`` = last record with key <= t."""

    def __init__(self):
        self.keys, self.recs = [], []

    def latest(self, t):
        i = bisect.bisect_right(self.keys, t)
        return self.recs[i - 1] if i else None


class ForwardMarketState:
    def __init__(self):
        self.book, self.depth = {}, {}                 # sym -> _Stream
        self.conf = {}                                 # (kind, sym) -> (sorted keys, max sample_ms per key)
        self.query_times = None                        # frozenset or None (full mode)
        self.runs, self.epochs, self.health, self.lifecycle, self.clock, self.gaps = [], [], [], [], [], []
        self.meta = {"source_kind": "synthetic", "dataset_id": None, "dataset_sha256": None, "days": [],
                     "seal_sha256": {}, "reader_version": RD.READER_VERSION, "loader_version": LOADER_VERSION}
        self.audit = None

    # ---------------- construction (in-memory) ----------------
    @classmethod
    def from_records(cls, book=(), depth=(), runs=(), health=(), lifecycle=(), clock=(), gaps=(), epochs=(), meta=None):
        """Full-mode state from canonical tuples (BOOK / DEPTH layouts) and control records."""
        S = cls()
        for kind, rows, store in (("book", book, S.book), ("depth", depth, S.depth)):
            by = collections.defaultdict(list)
            for sym, rec in rows:
                by[sym].append(rec)
            for sym, lst in by.items():
                lst.sort(key=lambda r: (r[0], r[1]))
                st = _Stream()
                st.keys, st.recs = [r[0] for r in lst], lst
                store[sym] = st
                samples = sorted(r[1] for r in lst)
                S.conf[(kind, sym)] = (samples, samples)
        S.runs = [dict(r) for r in runs]
        S.health = sorted(health, key=lambda h: h[0])
        S.lifecycle = sorted(lifecycle, key=lambda x: x[0])
        S.clock = sorted(clock, key=lambda x: x[0])
        S.gaps = list(gaps)
        S.epochs = sorted(epochs, key=lambda e: (e["effective_from_ms"], e["available_at_ms"]))
        if meta:
            S.meta.update(meta)
        return S

    # ---------------- raw accessors (no PIT guard: use PITMarketView) ----------------
    def _check_query(self, t):
        if self.query_times is not None and t not in self.query_times:
            raise StateError(f"time {t} is not a prepared query time of this pruned state")

    def latest(self, kind, sym, t):
        self._check_query(t)
        st = (self.book if kind == "book" else self.depth).get(sym)
        return st.latest(t) if st else None

    def last_sample(self, kind, sym, t):
        """Latest persisted sample boundary (sample_ms <= t) of the stream, or None."""
        self._check_query(t)
        c = self.conf.get((kind, sym))
        if not c:
            return None
        i = bisect.bisect_right(c[0], t)
        return c[1][i - 1] if i else None

    def keys_of(self, name):
        c = self.__dict__.setdefault("_keycache", {})
        lst = getattr(self, name)
        if name not in c or c[name][0] != len(lst):
            c[name] = (len(lst), [x[0] for x in lst])
        return c[name][1]

    def run_at(self, t):
        for r in self.runs:
            if r["ws_start_ms"] is not None and r["ws_start_ms"] <= t and (r["end_ms"] is None or t < r["end_ms"]):
                return r
        return None


class PITMarketView:
    """Read-only view of a state truncated at ``horizon_ms`` (the execution time)."""

    def __init__(self, state: ForwardMarketState, horizon_ms: int):
        self.S, self.horizon = state, int(horizon_ms)

    def _guard(self, t):
        if t > self.horizon:
            raise PITViolation(f"access at {t} > horizon {self.horizon}")

    def _ok(self, rec, t):
        if rec is not None and rec[0] > t:
            raise PITViolation(f"source returned a record available at {rec[0]} > {t}")
        return rec

    def book(self, sym, t):
        self._guard(t)
        return self._ok(self.S.latest("book", sym, t), t)

    def depth(self, sym, t):
        self._guard(t)
        return self._ok(self.S.latest("depth", sym, t), t)

    def last_sample(self, kind, sym, t):
        self._guard(t)
        s = self.S.last_sample(kind, sym, t)
        if s is not None and s > t:
            raise PITViolation(f"confirmation boundary {s} > {t}")
        return s

    def run_at(self, t):
        self._guard(t)
        return self.S.run_at(t)

    def epoch_at(self, t):
        self._guard(t)
        best = None
        for e in self.S.epochs:
            if e["effective_from_ms"] <= t and e["available_at_ms"] <= t:
                if best is None or (e["effective_from_ms"], e["available_at_ms"]) >= (best["effective_from_ms"],
                                                                                      best["available_at_ms"]):
                    best = e
        return best

    def health(self, t):
        self._guard(t)
        i = bisect.bisect_right(self.S.keys_of("health"), t)
        return self._ok(self.S.health[i - 1], t) if i else None

    def clock(self, t):
        self._guard(t)
        i = bisect.bisect_right(self.S.keys_of("clock"), t)
        return self._ok(self.S.clock[i - 1], t) if i else None

    def connection_events(self, t, boot8):
        self._guard(t)
        c = self.S.__dict__.setdefault("_conncache", {})
        if c.get("n") != len(self.S.lifecycle):
            c["n"], c["ev"] = len(self.S.lifecycle), [x for x in self.S.lifecycle if x[1] in CONN_EVENTS]
        return [x for x in c["ev"] if x[0] <= t and x[3] == boot8]

    def gaps_known(self, t, stream_key):
        self._guard(t)
        return [g for g in self.S.gaps if g["available_at_ms"] <= t and g["stream_key"] == stream_key]


# ====================================================================== sealed-day adapter ======
def _f(x, what):
    return RD._f(x, what)


def _levels(side, oid):
    return tuple((_f(p, oid), _f(qv, oid)) for p, qv in side)


def _new_audit():
    return {"records": collections.Counter(), "key_sets": collections.defaultdict(collections.Counter),
            "payload_key_sets": collections.defaultdict(collections.Counter), "per_tier": collections.defaultdict(collections.Counter),
            "lag_ms": collections.defaultdict(lambda: array.array("q")), "market_component_age_ms": array.array("q"),
            "exchange_event_time_present": collections.Counter(), "depth_levels_hist": collections.defaultdict(collections.Counter),
            "candles": collections.Counter(), "lifecycle_events": collections.Counter(), "gap_causes": collections.Counter(),
            "health_states": collections.Counter(), "segments": 0}


class _Collector:
    def __init__(self, query_times):
        self.Q = sorted(query_times) if query_times is not None else None
        self.best = {"book": {}, "depth": {}}            # pruned: sym -> {bucket: rec}
        self.full = {"book": collections.defaultdict(list), "depth": collections.defaultdict(list)}
        self.conf = collections.defaultdict(dict)        # pruned: (kind, sym) -> {bucket: max sample}
        self.dup = collections.defaultdict(lambda: (array.array("q"), array.array("q")))
        self.A = _new_audit()

    def _bucket(self, t):
        i = bisect.bisect_left(self.Q, t)
        return self.Q[i] if i < len(self.Q) else None

    def add(self, kind, sym, rec):
        sm, cs = self.dup[(kind, sym)]
        sm.append(rec[1])
        cs.append(zlib.crc32(repr(rec).encode()))
        if self.Q is None:
            self.full[kind][sym].append(rec)
            return
        b = self._bucket(rec[0])
        if b is not None:
            d = self.best[kind].setdefault(sym, {})
            cur = d.get(b)
            if cur is None or (rec[0], rec[1]) > (cur[0], cur[1]):
                d[b] = rec
        b2 = self._bucket(rec[1])
        if b2 is not None:
            c = self.conf[(kind, sym)]
            if rec[1] > c.get(b2, -1):
                c[b2] = rec[1]

    def check_duplicates(self, quality):
        for (kind, sym), (sm, cs) in self.dup.items():
            order = sorted(range(len(sm)), key=lambda i: (sm[i], cs[i]))
            for a, b in zip(order, order[1:]):
                if sm[a] == sm[b]:
                    if cs[a] != cs[b]:
                        raise RD.AmbiguityError("CONFLICTING_SAMPLE", [kind, sym, sm[a]])
                    quality[f"duplicates_dropped.{kind}"] += 1
        self.dup.clear()

    def finish(self, S: ForwardMarketState):
        for kind, store in (("book", S.book), ("depth", S.depth)):
            if self.Q is None:
                for sym, lst in self.full[kind].items():
                    uniq = {}
                    for r in lst:
                        uniq.setdefault(r[1], r)                 # identical duplicates (checked) collapse
                    rows = sorted(uniq.values(), key=lambda r: (r[0], r[1]))
                    st = _Stream()
                    st.keys, st.recs = [r[0] for r in rows], rows
                    store[sym] = st
                    smp = sorted(uniq)
                    S.conf[(kind, sym)] = (smp, smp)
            else:
                for sym, d in self.best[kind].items():
                    st = _Stream()
                    st.keys = sorted(d)
                    st.recs = [d[k] for k in st.keys]
                    store[sym] = st
                for (k2, sym), d in self.conf.items():
                    if k2 == kind:
                        ks = sorted(d)
                        S.conf[(kind, sym)] = (ks, [d[k] for k in ks])


def _audit_record(A, r):
    t = r["type"]
    A["records"][t] += 1
    A["key_sets"][t][",".join(sorted(r))] += 1
    p = r["payload"]
    if isinstance(p, dict):
        A["payload_key_sets"][t][",".join(sorted(p))] += 1
    elif isinstance(p, list) and t == "market" and p:
        A["payload_key_sets"][t][",".join(sorted(p[0]))] += 1
    if r["exchange_event_time_ms"] is not None:
        A["exchange_event_time_present"][t] += 1
    if t in ("book", "depth"):
        tier = f"t{r['tier']}"
        pt = A["per_tier"][f"{t}.{tier}"]
        pt["records"] += 1
        pt["unchanged"] += bool(r["unchanged"])
        pt["clock_suspect"] += bool(r["clock_suspect"])
        pt[f"cadence_ms={r['cadence_ms']}"] += 1
        A["lag_ms"][f"{t}.{tier}"].append(r["sample_ms"] - r["observed_at_ms"])
    if t == "depth":
        pl = r["payload"] or {}
        A["depth_levels_hist"][f"t{r['tier']}"][f"N={r['depth_levels']} bids={len(pl.get('bids') or [])} asks={len(pl.get('asks') or [])}"] += 1
    elif t == "market":
        A["per_tier"]["market"]["records"] += 1
        A["per_tier"]["market"]["startup_incomplete"] += not r.get("startup_complete")
        for s, ms in (r.get("component_recv_ms") or {}).items():
            A["market_component_age_ms"].append(r["sample_ms"] - int(ms))
    elif t == "candle":
        A["candles"][r["obs_id"].split("|")[1]] += 1
    elif t == "lifecycle":
        A["lifecycle_events"][(r["payload"] or {}).get("event")] += 1
    elif t == "gap":
        p = r["payload"] or {}
        A["gap_causes"][f"{str(p.get('stream_key')).split('|')[0]}:{p.get('cause')}"] += 1
    elif t == "health":
        A["health_states"][(r["payload"] or {}).get("state")] += 1


def _ingest(C: _Collector, B, r, ctrl, boots):
    t = r["type"]
    boots.add(r["boot_id"])
    boot8 = RD._i(r["boot_id"][:8])
    oid = r["obs_id"]
    if t == "book":
        p = r["payload"] or {}
        if p.get("s") not in (None, r["symbol"]):
            raise RD.IntegrityError("BOOK_SYMBOL_MISMATCH", oid)
        rec = (r["available_at_ms"], r["sample_ms"], r["observed_at_ms"], _f(p.get("b"), oid), _f(p.get("a"), oid),
               _f(p.get("B"), oid), _f(p.get("A"), oid), r["exchange_seq"], r["unchanged"], r["clock_suspect"],
               RD._i(r["tier"]), RD._i(r["cadence_ms"]), boot8)
        C.add("book", r["symbol"], rec)
    elif t == "depth":
        p = r["payload"] or {}
        rec = (r["available_at_ms"], r["sample_ms"], r["observed_at_ms"], _levels(p.get("bids") or [], oid),
               _levels(p.get("asks") or [], oid), RD._i(r["depth_levels"]), r["exchange_seq"], r["unchanged"],
               r["clock_suspect"], RD._i(r["tier"]), RD._i(r["cadence_ms"]), boot8)
        C.add("depth", r["symbol"], rec)
    elif t in ("market", "candle"):
        pass                                             # validated + audited; not execution inputs in X0
    else:
        RD._ingest(B, r, ctrl)                           # control records: reader dedupe / conflict semantics


def _read_segment(C, B, base, rel, d, mans, ctrl, boots, observer=None):
    if d not in mans:
        mans[d] = RD._manifest(base, d)
    p = os.path.join(base, rel)
    dig = RD.sha256_file(p)
    ent = mans[d].get(rel)
    if ent is None or ent.get("sha256") != dig:
        raise RD.IntegrityError("SEGMENT_SHA_NE_MANIFEST", rel)
    try:
        with open(p + ".sha256", encoding="utf-8") as fh:
            side = fh.read().split()[0]
    except (OSError, IndexError):
        side = None
    if side != dig:
        raise RD.IntegrityError("SEGMENT_SHA_NE_SIDECAR", rel)
    n = 0
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                RD.validate_record(r)
                if observer is not None:
                    observer(r)                          # read-only side channel (P2-X1 calibration); never alters state
                _audit_record(C.A, r)
                _ingest(C, B, r, ctrl, boots)
                n += 1
    except (OSError, EOFError, ValueError) as e:
        if isinstance(e, RD.ReaderError):
            raise
        raise RD.IntegrityError("SEGMENT_DECODE_ERROR", f"{rel}:{type(e).__name__}") from None
    if ent.get("records") is not None and ent["records"] != n:
        raise RD.IntegrityError("SEGMENT_RECORD_COUNT_NE_MANIFEST", rel)
    C.A["segments"] += 1
    B.provenance["segments"].append({"path": rel, "sha256": dig, "records": n})


def load_sealed(base: str, days: list, query_times=None, observer=None) -> ForwardMarketState:
    """Load consecutive SEALED days (plus the last day's spill-over hour). Unsealed days are refused.

    ``observer`` (P2-X1, optional): a callable receiving every validated raw record (a deep copy is NOT made; the
    observer must treat it as read-only). It never changes the returned state (tested)."""
    ds = RD.open_dataset(base)
    days = sorted(set(days))
    if not days:
        raise RD.ReaderError("NO_DAYS")
    for a, b in zip(days, days[1:]):
        if RD.day_start_ms(b) - RD.day_start_ms(a) != RD.DAY_MS:
            raise RD.ReaderError("DAYS_NOT_CONSECUTIVE", [a, b])
    B = RD.Bundle()
    B.days, B.dataset = days, dict(ds)
    B.range_start_ms, B.range_end_ms = RD.day_start_ms(days[0]), RD.day_start_ms(days[-1]) + RD.DAY_MS
    sealed, want = {}, []
    for d in days:
        sealed[d] = RD._seal_check(base, ds, d)
        segs, unc = RD._segments(base, d)
        if unc:
            raise RD.IntegrityError("UNCERTIFIED_FILE_IN_SEALED_DAY", unc[:3])
        if sorted(segs) != sealed[d]["day_close_files"]:
            raise RD.IntegrityError("DAY_SEGMENTS_NE_DAY_CLOSE", d)
        want += [(s, d) for s in segs]
    nxt = RD.day_key(B.range_end_ms)
    spill, unc = RD._segments(base, nxt, hours={RD.hour_key(B.range_end_ms)})
    if unc:
        raise RD.IntegrityError("SPILLOVER_NOT_FINAL", unc[:3])
    want += [(s, nxt) for s in spill]
    C = _Collector(query_times)
    mans, ctrl, boots = {}, {}, set()
    for rel, d in sorted(set(want)):
        _read_segment(C, B, base, rel, d, mans, ctrl, boots, observer)
    C.check_duplicates(B.quality)
    recs = sorted((v[1] for v in ctrl.values()), key=lambda r: (r["available_at_ms"], r["recv_ts_ns"], r["obs_id"]))
    RD.process_control(B, recs, set())
    RD._runs(B, base, boots)
    RD._epochs(B, base)
    S = ForwardMarketState()
    C.finish(S)
    S.query_times = frozenset(query_times) if query_times is not None else None
    S.runs, S.epochs, S.health, S.lifecycle, S.clock, S.gaps = B.runs, B.epochs, B.health, B.lifecycle, B.clock, B.gaps
    S.downtime, S.range_start_ms, S.range_end_ms = B.downtime, B.range_start_ms, B.range_end_ms
    S.meta = {"source_kind": "tsb.p2.forward schema v2 (sealed days)", "dataset_id": ds["dataset_id"],
              "dataset_sha256": ds["_sha256"], "days": list(days),
              "seal_sha256": {d: sealed[d]["seal_sha256"] for d in days}, "reader_version": RD.READER_VERSION,
              "loader_version": LOADER_VERSION}
    S.provenance = B.provenance
    S.quality = dict(sorted(B.quality.items()))
    S.audit = C.A
    return S
