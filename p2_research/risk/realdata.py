"""P2-RM0 real sealed-data STRUCTURAL validation (predeclared plan RM0-VALIDATION-PLAN 1.0.0).

For every predeclared decision time T and fixture P0-P7: RiskSnapshot, coverage / quality states / refusals,
PIT truncation and poison counterfactuals, a past-input positive control, and the independent reference comparison.
No outcome, P&L, Sharpe, profit factor, win rate, predictive power or ranking is computed; no equity curve is used.

python -m p2_research.risk.realdata --dataset SRC --days 2026-10-04 2026-10-05 --out OUT --code-commit SHA
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import sys

from .. import reader as RD
from ..execution import model as XM
from . import contracts as RC
from . import pitcheck as PC
from . import portfolios as PF
from . import reference as REF
from . import snapshot as SN
from .market import load_risk_market

FORBIDDEN_OUT = ("/home/tradmin/research-data/trading-signal-bot/p2/",)
TOOL_VERSION = "p2rm0-realdata-v1.1"                # v1.1: D-RM0-1 positive-control applicability


class PlanError(ValueError):
    pass


def _ms(iso: str) -> int:
    d = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp()) * 1000


def plan_times(C, days) -> list:
    plan = C.plan
    if sorted(days) != sorted(plan["sealed_days"]):
        raise PlanError(f"days {days} differ from the predeclared sealed days {plan['sealed_days']}")
    lo, hi = RD.day_start_ms(min(days)), RD.day_start_ms(max(days)) + RD.DAY_MS
    out = []
    for iso in plan["decision_times_utc"]:
        t = _ms(iso)
        XM.require_outside_w3(t, "decision_time")
        if t * 1000 < XM.W3_END_US:
            raise PlanError(f"{iso} is not after the W3 end")
        if not lo <= t < hi:
            raise PlanError(f"{iso} lies outside the sealed days")
        if (t - 390_000) % 900_000:
            raise PlanError(f"{iso} is not a grid-15m-plus390s-v1 point")
        out.append(t)
    for iso in plan.get("offgrid_pit_probe_times_utc", []):
        t = _ms(iso)
        XM.require_outside_w3(t, "probe_time")
        if t * 1000 < XM.W3_END_US or not lo <= t < hi:
            raise PlanError(f"probe {iso} outside the eligible sealed range")
        if (t - 390_000) % 900_000 == 0:
            raise PlanError(f"probe {iso} must be off the decision grid")
        out.append(t)
    return sorted(set(out))


def _gz_bytes(lines) -> bytes:
    bio = io.BytesIO()
    with gzip.GzipFile(fileobj=bio, mode="wb", mtime=0, filename="", compresslevel=6) as gz:
        for ln in lines:
            gz.write(ln.encode("utf-8") + b"\n")
    return bio.getvalue()


def _snaps_at(M, T, C, pids):
    ctx = SN.Context(M, T, C)
    out = {}
    for pid in pids:
        fx = PF.build(pid, ctx.view, C)
        meta = {"fixture": pid, "fixture_contract": "RM0-PORTFOLIOS@1.0.0", "fixture_refusals": fx["fixture_refusals"],
                "selection_notes": fx["selection_notes"]}
        out[pid] = SN.build_snapshot(ctx, fx["positions"], portfolio_meta=meta)
    return out, dict(ctx.view.audit)


def _ref_params(C) -> dict:
    return {"lookback": C.vol["lookback_long_returns"], "min_obs_long": C.vol["min_obs_long"],
            "min_obs_corr": C.corr["min_obs"], "bar_ms": C.bar_ms, "btc_symbol": C.btc_reference.split(":")[-1]}


def run(base: str, days: list, out_dir: str, code_commit: str, pit: bool = True) -> dict:
    C = RC.default()
    rp = os.path.realpath(out_dir) + "/"
    if any(rp.startswith(f) for f in FORBIDDEN_OUT) or rp.startswith(os.path.realpath(base) + "/"):
        raise PlanError("output directory must be outside the dataset tree")
    Ts = plan_times(C, days)
    pids = C.plan["portfolios"]
    M = load_risk_market(base, days, query_times=Ts)
    lines, coverage, pit_rep, ref_rep = [], {}, {}, {}
    totals = collections.Counter()
    ref_par = _ref_params(C)
    for T in Ts:
        snaps, audit = _snaps_at(M, T, C, pids)
        iso = SN._utc(T)
        cov_t = {"universe_size": None, "w3_mask_audit": audit, "portfolios": {},
                 "kind": "decision_grid" if (T - 390_000) % 900_000 == 0 else "offgrid_pit_probe"}
        for pid in pids:
            s = snaps[pid]
            lines.append(SN.canonical_line(s))
            cov_t["universe_size"] = s["regime"]["universe_size"]
            cov_t["universe_id"] = s["regime"]["universe_id"]
            reasons = collections.Counter(u["reason"].split(":")[0] for u in s["unavailable"])
            cov_t["portfolios"][pid] = {
                "positions": len(s["positions"]), "fixture_refusals": s["inputs"]["portfolio"]["fixture_refusals"],
                "state_counts": s["quality"]["state_counts"], "worst": s["quality"]["worst"],
                "unavailable_reason_counts": dict(sorted(reasons.items())),
                "flags": [f["id"] for f in s["flags"]],
                "liquidity_depth_sufficiency": dict(sorted(collections.Counter(
                    v["depth_sufficiency"] for v in s["liquidity"]["per_position"].values()).items())),
                "covariance_condition": s["risk_contribution"]["covariance_condition"],
                "snapshot_id": s["snapshot_id"]}
            for st, n in s["quality"]["state_counts"].items():
                totals[f"state.{st}"] += n
            totals["snapshots"] += 1
            totals["fixture_refusals"] += len(s["inputs"]["portfolio"]["fixture_refusals"])
            rv = REF.metrics(M.candles, [(p["symbol"], p["signed_notional"]) for p in s["positions"]], T, ref_par)
            sv = REF.snapshot_values(s)
            d = REF.compare(rv, sv)
            ref_rep.setdefault(iso, {})[pid] = {"keys": len(rv), "diffs": d, "max_scaled_abs_diff": REF.max_abs_diff(rv, sv),
                                               "non_null_compared": sum(1 for k in rv if rv[k] is not None)}
            totals["reference_diffs"] += len(d)
            totals["reference_keys"] += len(rv)
        coverage[iso] = cov_t
        if pit:
            rep = {}
            for name, MM in (("truncated", PC.truncate(M, T)), ("poisoned", PC.poison(M, T, C.bar_ms))):
                other, _ = _snaps_at(MM, T, C, pids)
                diff = [pid for pid in pids if SN.canonical_line(other[pid]) != SN.canonical_line(snaps[pid])]
                rep[name] = {"compared": len(pids), "identical": len(pids) - len(diff), "different": diff}
                totals[f"pit_{name}_compared"] += len(pids)
                totals["pit_violations"] += len(diff)
            MP = PC.perturb_past(M, T, "BTCUSDT", C.bar_ms)
            consumers = PC.control_consumers(snaps["P1"])
            if MP is None or not consumers:
                why = ("no closed, available, non-W3 BTC bar at T" if MP is None else
                       "no reported metric consumes the perturbed bar (all BTC-candle metrics null; D-RM0-1)")
                rep["positive_control_past_btc_close_x1.5"] = {"applicable": False, "reason": why}
                totals["positive_control_not_applicable"] += 1
            else:
                ctl, _ = _snaps_at(MP, T, C, pids)
                changed = [pid for pid in pids if SN.canonical_line(ctl[pid]) != SN.canonical_line(snaps[pid])]
                ok = bool(changed)
                rep["positive_control_past_btc_close_x1.5"] = {"applicable": True, "consumers": consumers,
                                                                "changed": changed, "detected": ok}
                totals["positive_control_applicable"] += 1
                totals["positive_control_failures"] += 0 if ok else 1
            pit_rep[iso] = rep
    data = _gz_bytes(lines)
    logical = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    os.makedirs(out_dir, exist_ok=True)
    files = {"snapshots.jsonl.gz": data,
             "coverage.json": json.dumps(coverage, indent=1, sort_keys=True).encode(),
             "reference.json": json.dumps(ref_rep, indent=1, sort_keys=True).encode()}
    if pit:
        files["pit.json"] = json.dumps(pit_rep, indent=1, sort_keys=True).encode()
    for f, b in files.items():
        with open(os.path.join(out_dir, f), "wb") as fh:
            fh.write(b)
    man = {"record": "tsb.p2rm.realdata_validation", "record_version": 1, "tool_version": TOOL_VERSION,
           "code_commit": code_commit, "plan": {"id": C.plan["id"], "version": C.plan["version"],
                                                 "sha256": C.sums["validation_plan_v1.json"]},
           "rm0_contract_set_sha256": C.sha256, "market_data": M.meta, "loader_quality": M.quality,
           "decision_times": [SN._utc(t) for t in Ts], "portfolios": pids, "logical_hash": logical,
           "totals": dict(sorted(totals.items())),
           "files": {f: hashlib.sha256(b).hexdigest() for f, b in sorted(files.items())},
           "not_computed_by_design": ["returns of any strategy", "P&L", "Sharpe", "profit factor", "win rate",
                                      "predictive power", "rankings", "equity curves"]}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=1, sort_keys=True)
    return man


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--days", required=True, nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--code-commit", default="uncommitted")
    ap.add_argument("--no-pit", action="store_true")
    a = ap.parse_args(argv)
    man = run(a.dataset, a.days, a.out, a.code_commit, pit=not a.no_pit)
    print(json.dumps({"logical_hash": man["logical_hash"], "totals": man["totals"]}, indent=1, sort_keys=True))
    t = man["totals"]
    bad = t.get("pit_violations", 0) + t.get("reference_diffs", 0) + t.get("positive_control_failures", 0)
    return 0 if bad == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
