"""P2-X1 execution calibration on SEALED data: observed spread, quote / depth age, displayed depth, reconstruction
reliability, field availability (truth boundary) and the network RTT observation. Market structure only.

Everything is predeclared in ``contracts_v2/calibration_plan_v2.json`` (notional set, buckets, windows, timestamps)
and was committed before this tool touched real data. No returns, no P&L, no labels, no Paper, no W3: every
statistic uses only records at or after the W3 end and before the end of the last sealed day; execution timestamps
are the P2-C decision grid T plus the three scenario latencies (research instants, NOT observed order times).

Two populations:
  A. every persisted boundary of every book / depth stream in the window (age = sample_ms - observed_at_ms);
  B. execution timestamps t = T + L, read through the PIT view exactly as the execution model does.

Usage: python -m p2_research.execution.calibration --dataset DIR --days 2026-10-04 2026-10-05 --out OUTDIR
       [--code-commit SHA]
"""
from __future__ import annotations

import argparse
import array
import bisect
import collections
import gzip
import hashlib
import io
import json
import math
import os
import sys

from .. import builder as BD, ledger as LG, reader as RD
from . import model as M, quality as QL
from .coverage import code_tree_sha256
from .market_state import CONN_EVENTS, PITMarketView, load_sealed
from .schema import INVALID, canon, sha256_text

CALIBRATION_VERSION = "p2x1-calibration-v1"
PLAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contracts_v2", "calibration_plan_v2.json")
FORBIDDEN_ROOT = LG.FORBIDDEN_ROOT
W3_END_MS = -(-M.W3_END_US // 1000)                    # first millisecond at or after the W3 end


def load_plan(path: str = PLAN_FILE) -> tuple:
    with open(path, "rb") as fh:
        raw = fh.read()
    plan = json.loads(raw)
    if plan.get("contract") != "tsb.p2x.calibration_plan" or plan.get("id") != "X1-CALIBRATION-PLAN":
        raise ValueError("not a P2-X1 calibration plan")
    return plan, hashlib.sha256(raw).hexdigest()


def pctl(xs, fs) -> dict:
    """Nearest-rank percentiles (plan: same method as P2-X0 coverage)."""
    n = len(xs)
    if not n:
        return {"n": 0}
    s = sorted(xs)
    out = {"n": n, "min": s[0], "max": s[-1]}
    for f in fs:
        out[f"p{f * 100:g}"] = s[min(n - 1, max(0, math.ceil(f * n) - 1))]
    return out


def bucket(v, bounds, labels) -> str:
    for b, lab in zip(bounds, labels):
        if v <= b:
            return lab
    return labels[len(bounds)]


def liq_bucket(v, bounds, labels) -> str:
    for b, lab in zip(bounds, labels):
        if v < b:
            return lab
    return labels[len(bounds)]


def _r(v, nd=6):
    return None if v is None else round(v, nd)


def _conn_kind(conn) -> str | None:
    c = str(conn or "").lower()
    return "book" if "book" in c else "depth" if "depth" in c else None


class Observer:
    """Read-only streaming statistics over every validated raw record of the loaded days (population A + audit)."""

    def __init__(self, w0: int, w1: int):
        self.w0, self.w1 = w0, w1
        self.book = collections.defaultdict(lambda: (array.array("q"), array.array("q"), array.array("d"),
                                                     array.array("b")))
        self.depth = collections.defaultdict(lambda: (array.array("q"), array.array("q"), array.array("d"),
                                                      array.array("d"), array.array("b")))
        self.cnt = collections.defaultdict(collections.Counter)
        self.keys = collections.defaultdict(collections.Counter)
        self.pkeys = collections.defaultdict(collections.Counter)
        self.event_time = collections.Counter()
        self.records = collections.Counter()
        self.pre_window = collections.Counter()
        self.clock = []
        self.market_delivery = array.array("q")

    def _in(self, r) -> bool:
        t = r["sample_ms"] if r["type"] in RD.SAMPLED else r["available_at_ms"]
        return t is not None and self.w0 <= t < self.w1

    def __call__(self, r) -> None:
        typ = r["type"]
        if not self._in(r):
            self.pre_window[typ if (r["sample_ms"] or r["available_at_ms"]) < self.w0 else typ + ".after_window"] += 1
            return
        self.records[typ] += 1
        self.keys[typ][",".join(sorted(r))] += 1
        p = r["payload"]
        if isinstance(p, dict):
            self.pkeys[typ][",".join(sorted(p))] += 1
        elif isinstance(p, list) and p and isinstance(p[0], dict):
            self.pkeys[typ][",".join(sorted(p[0]))] += 1
        if r["exchange_event_time_ms"] is not None:
            self.event_time[typ] += 1
        if typ == "book":
            b, a = float(p["b"]), float(p["a"])
            tier = int(r["tier"])
            c = self.cnt[f"book.t{tier}"]
            c["records"] += 1
            c["unchanged"] += bool(r["unchanged"])
            c["clock_suspect"] += bool(r["clock_suspect"])
            if b <= 0 or a <= 0:
                c["non_positive"] += 1
                return
            if b >= a:
                c["crossed_or_locked"] += 1
            st = self.book[r["symbol"]]
            st[0].append(r["sample_ms"])
            st[1].append(r["sample_ms"] - r["observed_at_ms"])
            st[2].append((a - b) / ((a + b) / 2) * 1e4)
            st[3].append(tier)
        elif typ == "depth":
            tier = int(r["tier"])
            c = self.cnt[f"depth.t{tier}"]
            c["records"] += 1
            c["unchanged"] += bool(r["unchanged"])
            bids, asks = p.get("bids") or [], p.get("asks") or []
            n = int(r["depth_levels"])
            c[f"levels N={n} bids={len(bids)} asks={len(asks)}"] += 1
            if not bids or not asks:
                c["empty_side"] += 1
                return
            disp = sum(float(px) * float(q) for px, q in bids[:RD.DEPTH_K]) + \
                sum(float(px) * float(q) for px, q in asks[:RD.DEPTH_K])
            b1, a1 = float(bids[0][0]), float(asks[0][0])
            if b1 >= a1:
                c["crossed_snapshot"] += 1
            st = self.depth[r["symbol"]]
            st[0].append(r["sample_ms"])
            st[1].append(r["sample_ms"] - r["observed_at_ms"])
            st[2].append(disp)
            st[3].append((a1 - b1) / ((a1 + b1) / 2) * 1e4)
            st[4].append(tier)
        elif typ == "clock":
            probes = [pr["t1_ms"] - pr["t0_ms"] for pr in (p.get("probes") or [])
                      if isinstance(pr, dict) and "t0_ms" in pr and "t1_ms" in pr]
            self.clock.append((r["available_at_ms"], p.get("rtt_ms"), p.get("skew_ms"), p.get("uncertainty_ms"),
                               p.get("state"), tuple(probes), r["endpoint"], r["source"]))
        elif typ == "market":
            if r["exchange_event_time_ms"] is not None and r.get("startup_complete", True):
                self.market_delivery.append(r["observed_at_ms"] - r["exchange_event_time_ms"])


def _windows(points, before, after):
    """Sorted, merged [start, end] windows."""
    w = sorted((a - before, b + after) for a, b in points)
    out = []
    for a, b in w:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _inside(windows, starts, t) -> bool:
    i = bisect.bisect_right(starts, t) - 1
    return i >= 0 and windows[i][0] <= t <= windows[i][1]


def population_a(O: Observer, S, plan) -> dict:
    fs = plan["percentiles"]
    ab, al = plan["buckets"]["quote_age_ms_upper_bounds"], plan["buckets"]["quote_age_labels"]
    pw = plan["proximity_windows_ms"]
    conn_ev = {"book": [], "depth": []}
    for x in S.lifecycle:
        if x[1] in CONN_EVENTS:
            k = _conn_kind((x[2] or {}).get("conn"))
            for kind in ((k,) if k else ("book", "depth")):
                conn_ev[kind].append(x[0])
    for k in conn_ev:
        conn_ev[k].sort()
    gaps = collections.defaultdict(list)
    for g in S.gaps:
        gaps[g["stream_key"]].append((g["first_missing_ms"], g["end_ms"]))
    out = {}
    for kind, store in (("book", O.book), ("depth", O.depth)):
        ages = collections.defaultdict(list)
        spreads = collections.defaultdict(list)
        disp = collections.defaultdict(list)
        cls = collections.defaultdict(collections.Counter)
        ev = conn_ev[kind]
        for sym in sorted(store):
            st = store[sym]
            gw = _windows(gaps.get(f"{kind}|{sym}", ()), pw["gap_adjacent"], pw["gap_adjacent"])
            gs = [w[0] for w in gw]
            tiers = st[-1]
            for i in range(len(st[0])):
                s, age, tier = st[0][i], st[1][i], f"t{tiers[i]}"
                j = bisect.bisect_right(ev, s) - 1
                if j >= 0 and s - ev[j] <= pw["post_connection_event"]:
                    c = "post_connection_event"
                elif gw and _inside(gw, gs, s):
                    c = "gap_adjacent"
                else:
                    c = "steady"
                cls[tier][c] += 1
                ages[(tier, "all")].append(age)
                ages[(tier, c)].append(age)
                ages[(tier, "bucket")].append(bucket(age, ab, al))
                if kind == "book":
                    spreads[(tier, "all")].append(st[2][i])
                    spreads[(tier, "age=" + bucket(age, ab, al))].append(st[2][i])
                else:
                    disp[tier].append(st[2][i])
                    spreads[(tier, "depth_l1_spread_bps")].append(st[3][i])
        res = {}
        for tier in sorted({k[0] for k in ages}):
            r = {"proximity_class_counts": dict(sorted(cls[tier].items())),
                 "age_ms": {c: pctl(ages[(tier, c)], fs) for c in ("all", "steady", "post_connection_event", "gap_adjacent")},
                 "age_bucket_counts": dict(sorted(collections.Counter(ages[(tier, "bucket")]).items())),
                 "record_counters": dict(sorted(O.cnt[f"{kind}.{tier}"].items()))}
            if kind == "book":
                r["spread_bps"] = {k[1]: pctl([_r(x) for x in v], fs) for k, v in sorted(spreads.items()) if k[0] == tier}
            else:
                r["displayed_notional_top10_both_sides_quote"] = pctl([_r(x, 2) for x in disp[tier]], fs)
                r["depth_l1_spread_bps"] = pctl([_r(x) for x in spreads[(tier, "depth_l1_spread_bps")]], fs)
            res[tier] = r
        out[kind] = res
    out["connection_events_in_window"] = dict(sorted(collections.Counter(
        f"{x[1]}:{(x[2] or {}).get('conn')}" for x in S.lifecycle if x[1] in CONN_EVENTS and O.w0 <= x[0] < O.w1).items()))
    out["gaps_in_window"] = dict(sorted(collections.Counter(
        f"{g['stream_key'].split('|')[0]}:{g['cause']}" for g in S.gaps if O.w0 <= g["available_at_ms"] < O.w1).items()))
    return out


def _walk_class(w, why):
    if w is None:
        return why
    return "supported.levels=1" if w["levels_used"] == 1 else "supported.levels>1"


def population_b(S, Ts, plan) -> tuple:
    fs = plan["percentiles"]
    lats = plan["execution_timestamps"]["latencies_ms"]
    Ns = plan["notional_set_quote"]
    ab, al = plan["buckets"]["quote_age_ms_upper_bounds"], plan["buckets"]["quote_age_labels"]
    lb, ll = (plan["buckets"]["liquidity_state_displayed_notional_upper_bounds_quote"],
              plan["buckets"]["liquidity_state_labels"])
    rows = []
    agg = collections.defaultdict(collections.Counter)
    dist = collections.defaultdict(list)
    counts = collections.Counter()
    for T in Ts:
        V0 = PITMarketView(S, T)
        ep, run_ = V0.epoch_at(T), V0.run_at(T)
        if ep is None or run_ is None:
            counts["decision_times_without_run_or_epoch"] += 1
            continue
        counts["decision_times"] += 1
        for sym in sorted(ep["tiers"]):
            tier = f"t{ep['tiers'][sym]}"
            counts[f"instrument_times.{tier}"] += 1
            ref0 = None
            for L in lats:
                t = T + L
                V = PITMarketView(S, t)
                b = V.book(sym, t)
                cb = QL.classify(V, "book", sym, t, b)
                d = V.depth(sym, t)
                cd = QL.classify(V, "depth", sym, t, d)
                h = V.health(t)
                hstate = "no_health" if h is None else ("HEALTHY" if h[1] == "HEALTHY" else "not_HEALTHY")
                k = f"{tier}.L{L}"
                row = {"T": T, "L": L, "symbol": sym, "tier": ep["tiers"][sym], "health": hstate,
                       "book": {"state": cb["state"], "flags": cb["flags"], "age_ms": cb["quote_age_ms"],
                                "confirmation_gap_ms": cb["confirmation_gap_ms"], "obs": M.book_ref(sym, b)},
                       "depth": {"state": cd["state"], "flags": cd["flags"], "age_ms": cd["quote_age_ms"],
                                 "confirmation_gap_ms": cd["confirmation_gap_ms"], "obs": M.depth_ref(sym, d)}}
                agg[f"book_state.{k}"][cb["state"]] += 1
                agg[f"depth_state.{k}"][cd["state"]] += 1
                for fl in cb["flags"]:
                    agg[f"book_flags.{k}"][fl] += 1
                for fl in cd["flags"]:
                    agg[f"depth_flags.{k}"][fl] += 1
                if b is not None:
                    exact = b[1] >= t
                    row["book"]["confirmed_exact"] = exact
                    agg[f"book_reconstruction.{k}"]["confirmed_exact" if exact else "latest_persisted_only"] += 1
                if cb["quote_age_ms"] is not None:
                    dist[f"book_age_ms.{k}"].append(cb["quote_age_ms"])
                    agg[f"book_age_bucket.{k}"][bucket(cb["quote_age_ms"], ab, al)] += 1
                if cb["confirmation_gap_ms"] is not None:
                    dist[f"book_confirmation_gap_ms.{k}"].append(cb["confirmation_gap_ms"])
                if cd["quote_age_ms"] is not None:
                    dist[f"depth_age_ms.{k}"].append(cd["quote_age_ms"])
                    agg[f"depth_age_bucket.{k}"][bucket(cd["quote_age_ms"], ab, al)] += 1
                spread = None
                if b is not None and cb["state"] != INVALID:
                    spread = (b[4] - b[3]) / ((b[4] + b[3]) / 2) * 1e4
                    row["book"]["spread_bps"] = _r(spread)
                    dist[f"spread_bps.{k}"].append(_r(spread))
                    dist[f"spread_bps_by_age.{tier}.{bucket(cb['quote_age_ms'], ab, al)}"].append(_r(spread))
                    dist[f"spread_bps_by_health.{tier}.{hstate}"].append(_r(spread))
                liq = "depth_unavailable"
                if d is not None and cd["state"] != INVALID and d[3] and d[4]:
                    disp = sum(p * q for p, q in d[3][:RD.DEPTH_K]) + sum(p * q for p, q in d[4][:RD.DEPTH_K])
                    liq = liq_bucket(disp, lb, ll)
                    row["depth"]["displayed_notional_top10"] = _r(disp, 2)
                    dist[f"depth_displayed_notional_top10.{k}"].append(_r(disp, 2))
                    if b is not None and cb["state"] != INVALID:
                        inc = {"buy": d[4][0][0] <= b[3], "sell": d[3][0][0] >= b[4]}
                        row["depth"]["l1_crosses_book_touch"] = inc
                        da = bucket(cd["quote_age_ms"], ab, al)
                        for sd, v in inc.items():
                            agg[f"depth_l1_crosses_book_touch.{k}"][f"{sd}.{v}"] += 1
                            agg[f"depth_l1_crosses_book_touch_by_depth_age.{tier}"][f"{da}.{sd}.{v}"] += 1
                row["liquidity_state"] = liq
                if spread is not None:
                    dist[f"spread_bps_by_liquidity.{tier}.{liq}"].append(_r(spread))
                walks = {}
                for side, sg in (("buy", 1), ("sell", -1)):
                    for N in Ns:
                        if cd["state"] == INVALID:
                            w, why = None, "depth_state_invalid"
                        else:
                            w, why = M.depth_walk(d, sg, N)
                        c = _walk_class(w, why)
                        walks[f"{side}.{int(N)}"] = c if w is None else {"class": c, "levels_used": w["levels_used"],
                                                                         "slippage_bps": _r(w["s"] * 1e4)}
                        agg[f"walk.{k}.{side}.{int(N)}"][c] += 1
                        if w is not None:
                            dist[f"walk_slippage_bps.{k}.{side}.{int(N)}"].append(_r(w["s"] * 1e4))
                row["walk"] = walks
                cur = (row["book"]["obs"], row["depth"]["obs"])
                if L == 0:
                    ref0 = cur
                else:
                    agg[f"latency_semantics.{k}"]["book_differs_from_T" if cur[0] != ref0[0] else "book_same_as_T"] += 1
                    agg[f"latency_semantics.{k}"]["depth_differs_from_T" if cur[1] != ref0[1] else "depth_same_as_T"] += 1
                rows.append(row)
    stats = {"counts": dict(sorted(counts.items())),
             "aggregates": {k: dict(sorted(v.items())) for k, v in sorted(agg.items())},
             "distributions": {k: pctl(v, fs) for k, v in sorted(dist.items())}}
    return stats, rows


def network_and_feed(O: Observer, plan) -> dict:
    fs = plan["percentiles"]
    ck = O.clock
    probes = [x for c in ck for x in c[5]]
    return {"clock_records": len(ck),
            "endpoints": dict(collections.Counter(f"{c[7]}:{c[6]}" for c in ck)),
            "clock_states": dict(sorted(collections.Counter(str(c[4]) for c in ck).items())),
            "rtt_min_of_3_ms": pctl([_r(c[1], 3) for c in ck if c[1] is not None], fs),
            "rtt_all_probes_ms": pctl([_r(x, 3) for x in probes], fs),
            "rtt_by_probe_position_ms": {str(i): dict(pctl([_r(c[5][i], 3) for c in ck if len(c[5]) > i], fs),
                                                      share_over_500ms=_r(sum(1 for c in ck if len(c[5]) > i and c[5][i] > 500)
                                                                          / max(1, sum(1 for c in ck if len(c[5]) > i)), 4))
                                         for i in range(max((len(c[5]) for c in ck), default=0))},
            "skew_ms": pctl([_r(c[2], 3) for c in ck if c[2] is not None], fs),
            "uncertainty_ms": pctl([_r(c[3], 3) for c in ck if c[3] is not None], fs),
            "market_observed_minus_exchange_event_ms": pctl(list(O.market_delivery), fs),
            "notes": ["RTT = t1 - t0 of a public market-data REST probe (/api/v3/time) from the collector host: a "
                      "MEASURED network lower-bound observation; it is NOT an order round trip and does not measure "
                      "order creation, exchange matching, acknowledgement or fill reporting",
                      "rtt_by_probe_position: probe 0 is the first request of each 10-minute clock check (after "
                      "~10 min idle); a larger probe-0 RTT is consistent with connection setup, which is not "
                      "itself observed (collector HTTP internals are not recorded)",
                      "market observed - exchange event time: !miniTicker@arr only (book / depth carry no event "
                      "time); raw host clock vs exchange clock (skew not removed) and includes up to ~1 s of "
                      "exchange-side batching: descriptive only"]}


def truth_boundary(O: Observer) -> dict:
    present = set(O.records)
    return {"records_in_window_by_type": dict(sorted(O.records.items())),
            "record_types_known_to_reader": list(RD.KINDS),
            "trade_or_aggtrade_records": sorted(t for t in present if "trade" in t.lower()),
            "exchange_event_time_present_by_type": dict(sorted(O.event_time.items())),
            "record_key_sets": {k: dict(v) for k, v in sorted(O.keys.items())},
            "payload_key_sets": {k: dict(v) for k, v in sorted(O.pkeys.items())},
            "pre_window_records_excluded": dict(sorted(O.pre_window.items()))}


def _gz(lines) -> tuple:
    raw = "".join(x + "\n" for x in lines).encode()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=6) as g:
        g.write(raw)
    return buf.getvalue(), hashlib.sha256(raw).hexdigest()


def _inside_dir(child, parent):
    c, p = os.path.realpath(child), os.path.realpath(parent)
    return c == p or c.startswith(p + os.sep)


def run(base: str, days: list, out_dir: str, code_commit: str, plan_path: str = PLAN_FILE) -> dict:
    if _inside_dir(out_dir, base) or _inside_dir(out_dir, FORBIDDEN_ROOT):
        raise SystemExit(f"refused: output {out_dir} inside the dataset / collector tree")
    plan, plan_sha = load_plan(plan_path)
    days = sorted(days)
    w0 = W3_END_MS
    w1 = RD.day_start_ms(days[-1]) + RD.DAY_MS
    lats = plan["execution_timestamps"]["latencies_ms"]
    grid = BD.decision_times(RD.day_start_ms(days[0]), w1)
    Ts = [t for t in grid if t >= w0 and t + max(lats) < w1]
    qts = sorted({t + L for t in Ts for L in lats})
    O = Observer(w0, w1)
    S = load_sealed(base, days, query_times=qts, observer=O)
    popa = population_a(O, S, plan)
    popb, rows = population_b(S, Ts, plan)
    cal = {"record": "tsb.p2x.calibration", "record_version": 1,
           "window_ms": [w0, w1], "population_a_all_boundaries": popa, "population_b_execution_timestamps": popb,
           "network_and_feed": network_and_feed(O, plan), "truth_boundary_field_audit": truth_boundary(O)}
    cal_txt = json.dumps(cal, sort_keys=True, indent=1) + "\n"
    pts_gz, pts_sha = _gz(canon(r) for r in rows)
    man = {"record": "tsb.p2x.calibration_manifest", "record_version": 1, "calibration_version": CALIBRATION_VERSION,
           "plan": {"id": plan["id"], "version": plan["version"], "sha256": plan_sha},
           "code_commit": code_commit, "code_tree_sha256": code_tree_sha256(), "market_data": S.meta,
           "segments": sorted((s["path"], s["sha256"], s["records"]) for s in S.provenance["segments"]),
           "runs": S.provenance["runs"], "universe_files": S.provenance["universe_files"],
           "reader_quality": S.quality, "decision_grid": BD.RG.DECISION_GRID, "window_ms": [w0, w1],
           "decision_times": len(Ts), "decision_time_range": [Ts[0], Ts[-1]] if Ts else None,
           "query_times": len(qts),
           "files": {"exec_points.jsonl.gz": {"sha256_uncompressed": pts_sha, "records": len(rows)},
                     "calibration.json": {"sha256": sha256_text(cal_txt)}}}
    man["logical_hash"] = sha256_text(canon(man))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "exec_points.jsonl.gz"), "wb") as fh:
        fh.write(pts_gz)
    with open(os.path.join(out_dir, "calibration.json"), "w", encoding="utf-8") as fh:
        fh.write(cal_txt)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(man, sort_keys=True, indent=1) + "\n")
    return man


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--days", required=True, nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--code-commit", default="uncommitted")
    a = ap.parse_args(argv)
    man = run(a.dataset, a.days, a.out, a.code_commit)
    print(json.dumps({"logical_hash": man["logical_hash"], "decision_times": man["decision_times"],
                      "exec_points": man["files"]["exec_points.jsonl.gz"]["records"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
