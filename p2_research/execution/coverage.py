"""P2-X0 real-data STRUCTURAL validation: execution-data coverage only (no returns, no profitability, no W3).

For every decision time T of the P2-C grid (``grid-15m-plus390s-v1``) on SEALED days, strictly after the end of the
sealed holdout W3, and every symbol of the universe epoch known at T, it estimates both legs (buy / sell) under the
three frozen scenarios at a hypothetical order notional and aggregates: reconstructability of bid/ask, executable
availability, quote-age and confirmation distributions by tier, stale / missing rates, provenance classes, displayed
depth-walk coverage by notional and tier, latency semantics, and a post-hoc QA check that every boundary later known
to be inside a gap was already flagged in real time. Writes canonical, byte-reproducible outputs + a manifest with a
logical hash. Read-only on the dataset; refuses to write under the collector tree.

Usage: python -m p2_research.execution.coverage --dataset DIR --days 2026-10-04 --out OUTDIR [--code-commit SHA]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import io
import json
import math
import os
import sys

from .. import builder as BD, instrument as IN, ledger as LG, reader as RD
from . import X0_VERSION, contracts as CT, model as M, quality as QL
from .market_state import PITMarketView, load_sealed
from .schema import INVALID, canon, check_quantity_tree, sha256_text

COVERAGE_VERSION = "p2x-coverage-v1"
NOTIONALS = (10.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 5000.0, 10000.0)
ESTIMATE_NOTIONAL = 50.0                          # current Paper stake; an INPUT, not hard-wired into the model
FORBIDDEN_ROOT = LG.FORBIDDEN_ROOT
W3_END_MS = -(-M.W3_END_US // 1000)


def pct(xs) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)

    def p(f):
        return s[min(len(s) - 1, max(0, math.ceil(f * len(s)) - 1))]
    return {"n": len(s), "min": s[0], "p50": p(0.5), "p90": p(0.9), "p99": p(0.99), "max": s[-1]}


def _inside(child, parent):
    c, p = os.path.realpath(child), os.path.realpath(parent)
    return c == p or c.startswith(p + os.sep)


def _gz(lines) -> tuple:
    raw = "".join(x + "\n" for x in lines).encode()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=6) as g:
        g.write(raw)
    return buf.getvalue(), hashlib.sha256(raw).hexdigest()


def code_tree_sha256() -> str:
    root = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha256()
    for dp, dn, fn in sorted(os.walk(root)):
        dn.sort()
        for f in sorted(fn):
            if f.endswith((".py", ".json")):
                p = os.path.join(dp, f)
                with open(p, "rb") as fh:
                    h.update(os.path.relpath(p, root).encode() + b"\0" + hashlib.sha256(fh.read()).digest())
    return h.hexdigest()


def run(base: str, days: list, out_dir: str, code_commit: str, notional: float = ESTIMATE_NOTIONAL,
        notionals=NOTIONALS) -> dict:
    if _inside(out_dir, base) or _inside(out_dir, FORBIDDEN_ROOT):
        raise SystemExit(f"refused: output {out_dir} inside the dataset / collector tree")
    C = CT.default()
    # the grid of the requested days; the loader is then pruned to exactly the query times (T + each latency)
    rs = RD.day_start_ms(sorted(days)[0])
    re_ = RD.day_start_ms(sorted(days)[-1]) + RD.DAY_MS
    grid = BD.decision_times(rs, re_)
    Ts = [t for t in grid if t >= W3_END_MS]                 # nothing at or before the end of the sealed holdout W3
    lats = sorted({C.model(C.scenario(s)["latency_model"])["latency_ms"] for s in C.scenarios})
    qts = sorted({t + L for t in Ts for L in lats})
    S = load_sealed(base, days, query_times=qts)
    scen = sorted(C.scenarios)
    lines = []
    agg = collections.defaultdict(collections.Counter)
    ages = collections.defaultdict(list)
    walk = collections.defaultdict(collections.Counter)
    latency = collections.Counter()
    qa = collections.Counter()
    n_rows = collections.Counter({"decision_times_excluded_w3_or_before": len(grid) - len(Ts)})
    for T in Ts:
        V = PITMarketView(S, T)
        ep, run_ = V.epoch_at(T), V.run_at(T)
        if ep is None or run_ is None:
            n_rows["decision_times_without_run_or_epoch"] += 1
            continue
        n_rows["decision_times"] += 1
        for sym in sorted(ep["tiers"]):
            tier = f"t{ep['tiers'][sym]}"
            inst = IN.binance_spot_instrument(sym)
            n_rows[f"instrument_times.{tier}"] += 1
            # state at T (decision) for age distributions, book + depth
            b = V.book(sym, T)
            cb = QL.classify(V, "book", sym, T, b)
            d = V.depth(sym, T)
            cd = QL.classify(V, "depth", sym, T, d)
            agg[f"book_at_T.{tier}"][cb["state"]] += 1
            agg[f"depth_at_T.{tier}"][cd["state"]] += 1
            agg[f"book_staleness_at_T.{tier}"][cb["staleness"]] += 1
            agg[f"book_confirmation_at_T.{tier}"][cb["confirmation"]] += 1
            agg[f"depth_staleness_at_T.{tier}"][cd["staleness"]] += 1
            agg[f"depth_confirmation_at_T.{tier}"][cd["confirmation"]] += 1
            for fl in cb["flags"]:
                agg[f"book_flags_at_T.{tier}"][fl] += 1
            for fl in cd["flags"]:
                agg[f"depth_flags_at_T.{tier}"][fl] += 1
            if cb["quote_age_ms"] is not None:
                ages[f"book_quote_age_ms.{tier}"].append(cb["quote_age_ms"])
            if cb["confirmation_gap_ms"] is not None:
                ages[f"book_confirmation_gap_ms.{tier}"].append(cb["confirmation_gap_ms"])
            if cd["quote_age_ms"] is not None:
                ages[f"depth_quote_age_ms.{tier}"].append(cd["quote_age_ms"])
            if b is not None and cb["state"] != INVALID:
                ages[f"spread_bps.{tier}"].append(round((b[4] - b[3]) / ((b[4] + b[3]) / 2) * 1e4, 6))
            if d is not None and cd["state"] != INVALID:
                ages[f"depth_ask_displayed_notional.{tier}"].append(round(sum(p * x for p, x in d[4]), 2))
                ages[f"depth_bid_displayed_notional.{tier}"].append(round(sum(p * x for p, x in d[3]), 2))
                agg[f"depth_side_levels.{tier}"][f"N={d[5]} bids={len(d[3])} asks={len(d[4])}"] += 1
                if b is not None:
                    seqd = d[6] - b[7] if isinstance(d[6], int) and isinstance(b[7], int) else None
                    agg[f"depth_vs_book_seq.{tier}"]["depth_newer" if seqd and seqd > 0 else "same" if seqd == 0 else "book_newer"] += 1
            # post-hoc QA (never an estimate input): boundaries later known to be inside a gap of this stream
            for kind, cl in (("book", cb), ("depth", cd)):
                gs = [g for g in S.gaps if g["stream_key"] == f"{kind}|{sym}" and g["first_missing_ms"] <= T < g["end_ms"]]
                if gs:
                    qa[f"{kind}_inside_posthoc_gap"] += 1
                    qa[f"{kind}_inside_posthoc_gap.flagged_{cl['state']}"] += 1
            # depth-walk coverage by notional at the EXEC-BASE execution time
            TE = T + C.model(C.scenario("EXEC-BASE")["latency_model"])["latency_ms"]
            VE = PITMarketView(S, TE)
            de = VE.depth(sym, TE)
            cde = QL.classify(VE, "depth", sym, TE, de)
            for side, sg in (("buy", 1), ("sell", -1)):
                for N in notionals:
                    key = f"{tier}.{side}.{int(N)}"
                    if cde["state"] == INVALID:
                        walk[key]["depth_state_invalid"] += 1
                        continue
                    w, why = M.depth_walk(de, sg, N)
                    walk[key]["supported" if w else why] += 1
                    if w:
                        walk[key][f"levels_used={w['levels_used']}"] += 1
                        walk[key]["slippage_gt_0" if w["s"] > 0 else "slippage_eq_0"] += 1
            # the canonical estimates (both legs, three scenarios)
            refs = {}
            for sc in scen:
                for side in ("buy", "sell"):
                    e = M.estimate_leg(S, inst, side, notional, T, sc, contracts=C)
                    check_quantity_tree(e)
                    lines.append(canon(e))
                    k = f"{sc}.{side}.{tier}"
                    agg[f"estimates.{k}"]["n"] += 1
                    agg[f"estimates.{k}"]["fill_available" if e["fill"]["value"] is not None else "fill_unavailable"] += 1
                    agg[f"estimates.{k}"][f"state={e['data_quality']['state']}"] += 1
                    agg[f"estimates.{k}"][f"cost_provenance={e['cost_provenance']}"] += 1
                    if e["fill"]["value"] is None:
                        agg[f"unavailable_reasons.{sc}.{tier}"][(e["total_cost_bps"]["reason"] or "").split(":")[0]] += 1
                    for comp in ("bid", "ask", "mid", "touch", "fill", "spread_bps", "spread_cost_bps", "fee_bps",
                                 "slippage_bps", "interaction_bps", "total_cost_bps", "latency_drift_bps",
                                 "adverse_selection_bps", "market_impact_bps", "gross_return", "net_return"):
                        agg[f"provenance.{sc}.{comp}"][e[comp]["provenance"]] += 1
                    refs[(sc, side)] = e["source_refs"]
            for sc in scen:
                r = refs[(sc, "buy")]
                latency[f"{sc}.exec_book_differs_from_decision_book"] += r["book"] != r["decision_book"]
                latency[f"{sc}.n"] += 1
    est_gz, est_sha = _gz(lines)
    cov = {"record": "tsb.p2x.coverage", "record_version": 1,
           "counts": dict(sorted(n_rows.items())),
           "aggregates": {k: dict(sorted(v.items())) for k, v in sorted(agg.items())},
           "distributions": {k: pct(v) for k, v in sorted(ages.items())},
           "depth_walk_coverage": {k: dict(sorted(v.items())) for k, v in sorted(walk.items())},
           "latency_semantics": dict(sorted(latency.items())),
           "posthoc_gap_qa": dict(sorted(qa.items())),
           "audit": audit_summary(S)}
    cov_txt = json.dumps(cov, sort_keys=True, indent=1) + "\n"
    man = {"record": "tsb.p2x.coverage_manifest", "record_version": 1, "coverage_version": COVERAGE_VERSION,
           "x0_version": X0_VERSION, "code_commit": code_commit, "code_tree_sha256": code_tree_sha256(),
           "contract_set_sha256": C.sha256, "contract_files": C.sums, "market_data": S.meta,
           "segments": sorted((s["path"], s["sha256"], s["records"]) for s in S.provenance["segments"]),
           "runs": S.provenance["runs"], "universe_files": S.provenance["universe_files"],
           "reader_quality": S.quality, "decision_grid": BD.RG.DECISION_GRID, "w3_end_ms_exclusive_bound": W3_END_MS,
           "decision_time_range": [Ts[0], Ts[-1]] if Ts else None, "decision_times": len(Ts),
           "query_times": len(qts), "estimate_notional": notional, "walk_notionals": list(notionals),
           "scenarios": scen, "files": {"estimates.jsonl.gz": {"sha256_uncompressed": est_sha, "records": len(lines)},
                                        "coverage.json": {"sha256": sha256_text(cov_txt)}}}
    man["logical_hash"] = sha256_text(canon(man))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "estimates.jsonl.gz"), "wb") as fh:
        fh.write(est_gz)
    with open(os.path.join(out_dir, "coverage.json"), "w", encoding="utf-8") as fh:
        fh.write(cov_txt)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(man, sort_keys=True, indent=1) + "\n")
    return man


def audit_summary(S) -> dict:
    """Collector field audit from the loader pass over every record of the loaded days (+ spill-over hour)."""
    A = S.audit
    return {"records_by_type": dict(sorted(A["records"].items())),
            "record_key_sets": {k: dict(v) for k, v in sorted(A["key_sets"].items())},
            "payload_key_sets": {k: dict(v) for k, v in sorted(A["payload_key_sets"].items())},
            "exchange_event_time_present": dict(sorted(A["exchange_event_time_present"].items())),
            "per_stream_tier": {k: dict(sorted(v.items())) for k, v in sorted(A["per_tier"].items())},
            "sample_minus_observed_ms": {k: pct(list(v)) for k, v in sorted(A["lag_ms"].items())},
            "market_component_age_ms": pct(list(A["market_component_age_ms"])),
            "depth_levels": {k: dict(sorted(v.items())) for k, v in sorted(A["depth_levels_hist"].items())},
            "candles_by_tf": dict(sorted(A["candles"].items())),
            "lifecycle_events": dict(sorted((str(k), v) for k, v in A["lifecycle_events"].items())),
            "gap_causes": dict(sorted(A["gap_causes"].items())),
            "health_states": dict(sorted((str(k), v) for k, v in A["health_states"].items())),
            "segments_read": A["segments"],
            "trade_prints_captured": "aggTrade" in A["records"] or "trade" in A["records"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--days", required=True, nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--code-commit", default="uncommitted")
    ap.add_argument("--notional", type=float, default=ESTIMATE_NOTIONAL)
    a = ap.parse_args(argv)
    man = run(a.dataset, a.days, a.out, a.code_commit, a.notional)
    print(json.dumps({"logical_hash": man["logical_hash"], "decision_times": man["decision_times"],
                      "estimates": man["files"]["estimates.jsonl.gz"]["records"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
