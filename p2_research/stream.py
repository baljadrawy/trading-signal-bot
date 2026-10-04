"""Bounded per-day streaming build for multi-day sealed ranges (P2-C delta E; closes open item O1 by design).

The in-memory builder keeps every sampled record of the whole range (~1 GB per production day). Here the sampled
streams (book / depth / market, >99 % of the volume) are processed one day at a time; only bounded state crosses a
day boundary:

  * sampled records with ``available_at_ms > next_day_start - CARRY_MS`` (2 h >= the longest sampled-stream feature
    lookback of 1 h after the +390 s grid offset), plus per stream ONE sentinel = the latest record at or before that
    cutoff (so "latest record known at T" and its stale / previous-run reason are identical to the full build);
  * candles, control records (gaps, health, lifecycle, clock), universe epochs and run windows. These are small
    (well under 1 % of the volume) and kept for the whole range so the 24-25 h candle warm-up, the 1d/2-candle
    feature, history-gap reasons and late candle re-fetches behave exactly as in the full build;
  * for labels, only the book observations a label actually asks for (first book after T, after T+1h/4h/24h),
    resolved while the day that contains them is loaded, stored as 5-field tuples.

Every segment is read exactly once (a day's first hour is read with the previous day as its 1 h spill-over). Labels
and the post-hoc gap flag are computed at the end of the range with the full candle store and the full gap list,
exactly like the in-memory build. Rows whose decision time lies after everything observed so far are held back
until the observation horizon is known (``beyond_observed_data`` semantics are therefore identical too).

Equivalence contract (tested): for the same sealed days, versions and code, ``build_streaming`` produces the same
manifest (same ``logical_hash``) and byte-identical uncompressed features / labels / excluded content as the in-memory
``builder.build``. The manifest additionally carries ``build_execution`` (outside the logical hash).
"""
from __future__ import annotations

import bisect
import collections
import datetime as dt
import gzip
import hashlib
import json
import os
import shutil
import tempfile

from . import features as FE, labels as LB, reader as RD, registry as RG
from .builder import (BuildError, decision_times, excluded_entries, feature_row, label_core, make_manifest,
                      output_subdir, posthoc_gap, structural_reason)
from .reader import DAY_MS, HOUR_MS, AmbiguityError, Bundle, IntegrityError, canon, day_key, day_start_ms, hour_key

FEATURE_SAMPLED_LOOKBACK_MS = 3_600_000          # liq.spread_norm_1h window; other lookbacks: 15 min, 5 min
CARRY_MS = 2 * HOUR_MS
STREAM_VERSION = "p2c-stream-v1"
assert CARRY_MS >= FEATURE_SAMPLED_LOOKBACK_MS + 900_000


def _in_hour(rel: str, hk: str) -> bool:
    return f"-{hk}Z-" in os.path.basename(rel)


class _LabelView:
    """What ``labels.compute_labels`` needs: full candle store, run chain, range, and pre-resolved book lookups."""

    def __init__(self, G: Bundle, memo: dict):
        self.G, self.memo = G, memo
        self.candles, self.coverage_end_ms, self.range_end_ms = G.candles, G.coverage_end_ms, G.range_end_ms

    def run_at(self, t):
        return self.G.run_at(t)

    def first_after(self, kind, sym, t):
        if kind != "book" or (sym, t) not in self.memo:
            raise BuildError(f"unresolved label lookup {kind} {sym}@{t}")
        return self.memo[(sym, t)]


def _prune(lst: list, cutoff: int) -> list:
    """Keep records with available > cutoff plus the latest one at or before it (sentinel)."""
    i = bisect.bisect_right([x[0] for x in lst], cutoff)
    return lst[i - 1:] if i > 0 else lst


class _GzOut:
    def __init__(self, path: str):
        self.raw = open(path, "wb")
        self.gz = gzip.GzipFile(filename="", mode="wb", fileobj=self.raw, mtime=0, compresslevel=6)
        self.sha, self.rows = hashlib.sha256(), 0

    def write(self, line: str) -> None:
        b = (line + "\n").encode()
        self.gz.write(b)
        self.sha.update(b)
        self.rows += 1

    def close(self) -> str:
        self.gz.close()
        self.raw.close()
        return self.sha.hexdigest()


def _plan(base: str, days: list):
    ds = RD.open_dataset(base)
    days = sorted(set(days))
    if not days:
        raise RD.ReaderError("NO_DAYS")
    for a, b in zip(days, days[1:]):
        if day_start_ms(b) - day_start_ms(a) != DAY_MS:
            raise RD.ReaderError("DAYS_NOT_CONSECUTIVE", [a, b])
    G = Bundle()
    G.days, G.dataset = days, {k: v for k, v in ds.items()}
    G.range_start_ms, G.range_end_ms = day_start_ms(days[0]), day_start_ms(days[-1]) + DAY_MS
    segs = {}
    for d in days:
        sealed = RD._seal_check(base, ds, d)
        G.provenance["days"][d] = {k: v for k, v in sealed.items() if k != "day_close_files"}
        s, unc = RD._segments(base, d)
        if unc:
            raise IntegrityError("UNCERTIFIED_FILE_IN_SEALED_DAY", unc[:3])
        G.quality["uncertified_files_skipped"] += len(unc)
        if sorted(s) != sealed["day_close_files"]:
            raise IntegrityError("DAY_SEGMENTS_NE_DAY_CLOSE", d)
        segs[d] = s
    nxt = day_key(G.range_end_ms)
    spill, unc = RD._segments(base, nxt, hours={hour_key(G.range_end_ms)})
    if unc:
        raise IntegrityError("SPILLOVER_NOT_FINAL", unc[:3])
    G.coverage_end_ms = G.range_end_ms
    # window k reads: day k (all hours for k = 0, else hours 01-23) + the first hour of day k+1 (or the spill-over)
    windows = []
    for k, d in enumerate(days):
        own_h0 = hour_key(day_start_ms(d))
        w = [(r, d, False) for r in segs[d] if k == 0 or not _in_hour(r, own_h0)]
        if k + 1 < len(days):
            h0 = hour_key(day_start_ms(days[k + 1]))
            w += [(r, days[k + 1], False) for r in segs[days[k + 1]] if _in_hour(r, h0)]
        else:
            w += [(r, nxt, True) for r in spill]
        windows.append(sorted(w))
    read = [x[0] for w in windows for x in w]
    want = {r for d in days for r in segs[d]} | set(spill)
    if len(read) != len(set(read)) or set(read) != want:             # every segment exactly once
        raise BuildError("streaming plan does not read every segment exactly once")
    return G, windows


def build_streaming(dataset_dir: str, days: list, out_root: str, *, code_commit: str, build_ts: str | None = None,
                    write: bool = True) -> dict:
    G, windows = _plan(dataset_dir, days)
    RD._runs(G, dataset_dir, set())                  # run chain + downtime from run files (boots checked at the end)
    reg_ids = [f["id"] for f in RG.FEATURES]
    final_parent = os.path.join(out_root, G.dataset["dataset_id"], output_subdir(G))
    if write:
        os.makedirs(final_parent, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix=".build-", dir=final_parent)
    else:
        tmp = tempfile.mkdtemp(prefix="p2c-stream-")
    try:
        fout = _GzOut(os.path.join(tmp, "features.jsonl.gz"))
        mans, digests, boots, flagged = {}, {}, set(), set()
        memo = {}                                     # (sym, t) -> None (pending) | first book after t (5-tuple)
        queue = collections.deque()                   # decided-per-T entries waiting for the observation horizon
        excl, label_wait, symbols, span = [], [], set(), [None, None]
        nulls, lnulls = collections.Counter(), collections.Counter()
        running_max = None
        peak_window_records = 0

        def release(horizon):
            while queue and horizon is not None and queue[0]["T"] <= horizon:
                e = queue.popleft()
                if e["sr"]:
                    excl.extend(excluded_entries(e["syms"], e["T"], e["sr"]))
                    continue
                nulls.update(e["nulls"])
                for s, line in e["rows"]:
                    fout.write(line)
                    label_wait.append((s, e["T"]))
                    symbols.add(s)
                if e["rows"]:
                    span[0] = e["T"] if span[0] is None else span[0]
                    span[1] = e["T"]

        for k, (d, w) in enumerate(zip(G.days, windows)):
            ctrl = {}
            for rel, dd, spill in w:
                RD.read_segment(G, dataset_dir, rel, dd, mans, ctrl, spill=spill)
            RD.finalize_sampled(G, flagged)
            new = []
            for oid, (c, r) in ctrl.items():
                h = hashlib.sha256(c.encode()).digest()
                if oid in digests:
                    if digests[oid] != h:
                        raise AmbiguityError("CONFLICTING_DUPLICATE", oid)
                    G.quality[f"duplicates_dropped.{r['type']}"] += 1
                    continue
                digests[oid] = h
                new.append(r)
            new.sort(key=lambda r: (r["available_at_ms"], r["recv_ts_ns"], r["obs_id"]))
            n_life = len(G.lifecycle)
            RD.process_control(G, new, boots)
            RD._epochs(G, dataset_dir, G.lifecycle[n_life:])
            G._keys = {}
            ends = [v[-1][0] for v in G.book.values() if v] + [v[-1][0] for v in G.depth.values() if v]
            ends += [G.market[-1][0]] if G.market else []
            ends += [new[-1]["available_at_ms"]] if new else []
            if ends:
                running_max = max(ends) if running_max is None else max(running_max, max(ends))
            peak_window_records = max(peak_window_records, sum(len(v) for v in G.book.values()) +
                                      sum(len(v) for v in G.depth.values()) + len(G.market))
            # ---- decisions of day d: features now (PIT: only data <= T, all inside this window) ----
            d0 = day_start_ms(d)
            for T in decision_times(d0, d0 + DAY_MS):
                V = FE.PITView(G, T)
                e = {"T": T, "syms": sorted(V.epoch["tiers"]) if V.epoch is not None else [],
                     "sr": structural_reason(V), "rows": [], "nulls": collections.Counter()}
                if e["sr"] is None:
                    ctx, btc = FE.market_context(V), FE.btc_context(V)
                    for s in e["syms"]:
                        e["rows"].append((s, feature_row(V, s, ctx, btc, reg_ids, e["nulls"])))
                        for t in (T, *(T + H for H in LB.HORIZONS.values())):
                            memo.setdefault((s, t), None)
                queue.append(e)
            # ---- resolve label book lookups whose time lies in this day (data up to day end + 1 h is loaded) ----
            for key in [key for key, v in memo.items() if v is None and d0 <= key[1] < d0 + DAY_MS]:
                x = G.first_after("book", key[0], key[1])
                memo[key] = None if x is None else x[:5]
            release(running_max)
            # ---- carry only bounded sampled state into the next day ----
            if k + 1 < len(G.days):
                cut = d0 + DAY_MS - CARRY_MS
                G.book = collections.defaultdict(list, {s: _prune(v, cut) for s, v in G.book.items()})
                G.depth = collections.defaultdict(list, {s: _prune(v, cut) for s, v in G.depth.items()})
                G.market = _prune(G.market, cut)
                G._keys = {}
        # ---- end of range: observation horizon, run provenance, quality counters ----
        G.observed_until_ms = running_max
        release(running_max)
        for e in queue:                               # decision times after everything observed
            excl.extend(excluded_entries(e["syms"], e["T"], "beyond_observed_data"))
        queue.clear()
        RD.check_run_boots(G, boots)
        for kind, _sym in sorted(flagged):
            G.quality[f"out_of_order_resolved.{kind}"] += 1
        G.book, G.depth, G.market, G._keys = collections.defaultdict(list), collections.defaultdict(list), [], {}
        G.provenance["segments"].sort(key=lambda x: x["path"])
        fsha = fout.close()
        # ---- labels (full candle store + resolved book lookups) and post-hoc gap flag (full gap list) ----
        LV, lout, posthoc = _LabelView(G, memo), _GzOut(os.path.join(tmp, "labels.jsonl.gz")), 0
        for s, T in label_wait:
            row = label_core(LV, s, T, lnulls)
            ph = posthoc_gap(G.gaps, s, T)
            posthoc += ph
            row["qa"] = {"posthoc_gap_at_decision": ph}
            lout.write(canon(row))
        lsha = lout.close()
        eout = _GzOut(os.path.join(tmp, "excluded.jsonl.gz"))
        for x in excl:
            eout.write(canon(x))
        esha = eout.close()
        files = {"features.jsonl.gz": {"sha256_uncompressed": fsha, "rows": fout.rows},
                 "labels.jsonl.gz": {"sha256_uncompressed": lsha, "rows": lout.rows},
                 "excluded.jsonl.gz": {"sha256_uncompressed": esha, "rows": eout.rows}}
        times = [] if span[0] is None else span
        manifest = make_manifest(G, code_commit, files, excl, sorted(symbols), times, nulls, lnulls, posthoc,
                                 fout.rows)
        manifest["build_timestamp_utc"] = build_ts or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest["build_execution"] = {"mode": STREAM_VERSION, "carry_ms": CARRY_MS, "days": len(G.days),
                                       "peak_window_sampled_records": peak_window_records,
                                       "label_lookups": len(memo)}
        if not write:
            return manifest
        final = os.path.join(final_parent, manifest["logical_hash"][:16])
        if os.path.exists(final):
            with open(os.path.join(final, "manifest.json"), encoding="utf-8") as fh:
                old = json.load(fh)
            if old.get("logical_hash") != manifest["logical_hash"]:
                raise BuildError(f"existing build dir with different logical hash: {final}")
            manifest["output_dir"], manifest["existing"] = final, True
            return manifest
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, sort_keys=True, indent=1)
            fh.write("\n")
        os.rename(tmp, final)
        tmp = None
        manifest["output_dir"] = final
        return manifest
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
