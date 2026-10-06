"""P2-F0 synthetic calibration of the battery itself (``contracts/f0_calibration_plan_v1.json``).

    python -m p2_research.falsification.calibration --out DIR [--study ID ...] [--quick]

Synthetic data only. Studies:
  C1  core p-value calibration on dependent fat-tailed day series (false-positive rate of each p and of the max)
  C2  battery under a NET-ZERO null (the planted gross edge exactly pays the costs)
  C3  battery under a bull-market BETA null (no edge, strong common drift)
  C4  battery under the pure null (no edge, no drift)
  C5  in-sample power (14 frozen validation days) at planted net edges
  C6  forward-test power (one pre-registered candidate) at 28 / 56 days
  C7  adversarial generators reproducing the project's past false-edge classes
Results are deterministic for a given plan (seeds derived from the plan), written as canonical JSON.

Host safety: the runner sleeps while the UTC minute is inside a declared blackout window (seal cron :12-:25, day
close 23:50-00:45) and aborts if the Collector health file is not HEALTHY (read-only check, every round).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import random
import sys
import time

from . import battery as B
from . import contracts as C
from . import panel as PN
from . import stats as S
from . import synthetic as SY

HEALTH = "/home/tradmin/research-data/trading-signal-bot/p2/forward-continuous-v1/health/collector_health.json"
OK_VERDICTS = ("FORWARD_CONFIRMATION_REQUIRED", "PROVISIONAL")


class Abort(RuntimeError):
    pass


def _in_blackout(now, windows):
    m = now.hour * 60 + now.minute
    for w in windows:
        if w["kind"] == "hourly" and w["from_min"] <= now.minute < w["to_min"]:
            return True
        if w["kind"] == "daily":
            a, b = w["from_hm"], w["to_hm"]
            a, b = a[0] * 60 + a[1], b[0] * 60 + b[1]
            if (a <= m or m < b) if a > b else (a <= m < b):
                return True
    return False


class Guard:
    def __init__(self, plan, enabled=True):
        self.windows = plan["host_safety"]["blackout_utc"]
        self.enabled = enabled
        self.slept = 0.0

    def tick(self):
        if not self.enabled:
            return
        while _in_blackout(dt.datetime.now(dt.timezone.utc), self.windows):
            time.sleep(20)
            self.slept += 20
        try:
            with open(HEALTH, encoding="utf-8") as fh:
                st = json.load(fh).get("state")
        except (OSError, ValueError):
            st = None
        if st != "HEALTHY":
            raise Abort(f"collector health {st!r}: workload stopped")


def _wilson(k, n, z=1.959963984540054):
    if n == 0:
        return [0.0, 1.0]
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return [max(0.0, c - h), min(1.0, c + h)]


def _rate(k, n):
    return {"k": k, "n": n, "rate": k / n if n else None, "wilson95": _wilson(k, n)}


def _seed(plan_sha, *parts):
    return int(hashlib.sha256("|".join([plan_sha] + [str(p) for p in parts]).encode()).hexdigest()[:12], 16)


# ------------------------------------------------------------------ C1
def study_c1(cfg, plan_sha, guard):
    out = {}
    v2 = str(cfg.get("method", "v1")).startswith("v2")
    for gen in cfg["generators"]:
        for n in cfg["n_days"]:
            keys = ("p_boot", "p_batch", "p_fixedb", "p", "p_v1") if v2 else ("p_boot", "p_hac_t", "p")
            hits = {k: 0 for k in keys}
            for rep in range(cfg["reps"]):
                if rep % 200 == 0:
                    guard.tick()
                rng = random.Random(_seed(plan_sha, "C1", gen["id"], n, rep))
                x, prev, pe = [], 0.0, 0.0
                for _ in range(n):
                    e = SY._t4(rng) if gen["innov"] == "t4" else rng.gauss(0, 1)
                    if gen.get("kind") == "ma":
                        v, pe = e + pe, e
                    else:
                        prev = gen["phi"] * prev + e
                        v = prev
                    x.append(v)
                sb = _seed(plan_sha, "C1b", gen["id"], n, rep)
                if v2:
                    L = S.block_length(n, cfg["horizon_block"])
                    r = S.core_test_v2(x, L, cfg["bootstrap_reps"], sb)
                    r["p_batch"] = 1.0 if r["p_batch"] is None else r["p_batch"]
                    r["p_v1"] = S.core_test(x, cfg["horizon_block"], cfg["horizon_block"], cfg["bootstrap_reps"], sb)["p"]
                else:
                    r = S.core_test(x, cfg["mean_block"], cfg["hac_lag"], cfg["bootstrap_reps"], sb)
                for k in hits:
                    hits[k] += r[k] <= cfg["alpha"]
            out[f"{gen['id']}|n={n}"] = {k: _rate(v, cfg["reps"]) for k, v in hits.items()}
    return out


# ------------------------------------------------------------------ battery rounds
def _registration(cs_sha, proto, rd, pid, forward=None):
    return {"record": "tsb.p2f.candidate_registration", "trial_id": rd.trial_id(pid), "plan_id": pid,
            "f0_contract_set_sha256": cs_sha, "p2d0_sums_sha256": proto["dependencies"]["p2d0"]["sha256"],
            "p2x_v2_sums_sha256": proto["dependencies"]["p2x_v2"]["sha256"],
            "considered_trials": rd.all_trial_ids() if forward is None else [rd.trial_id(pid)],
            "forward_registration": forward,
            "dataset": {"dataset_id": "synthetic", "dataset_hash": hashlib.sha256(f"synthetic|{rd.seed}".encode()).hexdigest()}}


def _oracle(ev, rd, delta):
    """True expected net per candidate position = planted drift of the entry row - its expected cost."""
    hz = ev["candidate"]["horizon"]
    ds = 1.0 if hz == "24h" else 1.0 / 6.0
    rows = [r for r in ev["rows"]]
    end = max(int(v) for v in ev["window"]["day_start_ms"].values()) + PN.DAY_MS
    rows = [r for r in rows if r["label_end_ms"] <= end]
    pos = PN.build_positions(PN.by_symbol(rows), PN.signal_flags(rows), PN.HORIZON_MS[hz])
    raw = {(r["sym"], r["t_ms"]): r for r in rd.panels[hz]["rows"]}
    vals = []
    for p in pos:
        rr = raw[(p["sym"], p["t_ms"])]
        g = rd.g.get((hz, p["sym"], rr["_t"]), 0.0)
        cost = p["gross"] - (p["net_base"] if p["net_base"] is not None else p["gross"] - 0.0026)
        vals.append(delta * ds * g - cost)
    return S.mean(vals) if vals else None


def _naive_p(ev):
    """What a naive analysis would report: an iid t-test over positions (no clustering, no costs check)."""
    c = ev["candidate"]
    rows = ev["rows"]
    pos = PN.build_positions(PN.by_symbol(rows), PN.signal_flags(rows), PN.HORIZON_MS[c["horizon"]])
    v = [p["net_base"] for p in pos if p["net_base"] is not None]
    if len(v) < 3 or S.sd(v) == 0:
        return None
    t = S.mean(v) / (S.sd(v) / math.sqrt(len(v)))
    return S.t_sf(t, len(v) - 1)


def run_round(cs_sha, proto, plan, bat, cfg, seed, *, mode="null", delta=0.0, mu_day=0.0, ar=0.0, kind="in_sample",
              n_days=14, first_day=15, best_of=False, claimed=None, edge_family="H01"):
    rd = SY.Round(seed, plan, mode=mode, n_days=n_days, first_day=first_day, delta=delta, mu_day=mu_day, ar=ar,
                  kind=kind, edge_family=edge_family, only=[SY.CANDIDATE_PLAN] if kind == "forward" else None)
    cid = SY.CANDIDATE_PLAN
    if kind == "forward":
        freg = {"first_day": first_day, "n_days": n_days, "set_size": 1}
        ev = rd.evidence(cid, _registration(cs_sha, proto, rd, cid, freg))
        res = bat.evaluate(ev, {})
        return res, ev, rd, cid
    sums = []
    for c in rd.cells:
        ev = rd.evidence(c["plan_id"], _registration(cs_sha, proto, rd, c["plan_id"]))
        s = B.core_summary(bat, ev)
        s["kind"] = ev["candidate"]["kind"]
        sums.append(s)
    if best_of:
        elig = [s for s in sums if s["kind"] != "information" and s["p"] is not None]
        cid = min(elig, key=lambda s: (s["p"], s["plan_id"]))["plan_id"]
    ctx = B.round_context(sums, total_trials=len(rd.cells), exclude=rd.trial_id(cid))
    ev = rd.evidence(cid, _registration(cs_sha, proto, rd, cid), claimed=claimed)
    res = bat.evaluate(ev, ctx)
    return res, ev, rd, cid


def _tally(results):
    vt, ft = {}, {}
    for r in results:
        vt[r["verdict"]] = vt.get(r["verdict"], 0) + 1
        for x in r["reasons"]:
            ft[x] = ft.get(x, 0) + 1
    return vt, ft


def study_battery(cfg, plan_sha, guard, cs_sha, proto, plan, bat, sid):
    out = {}
    for cell in cfg["cells"]:
        res, oracles, naive, caught = [], [], 0, 0
        for rep in range(cfg["reps"]):
            guard.tick()
            seed = _seed(plan_sha, sid, cell["id"], rep)
            r, ev, rd, cid = run_round(cs_sha, proto, plan, bat, cfg, seed, mode=cell.get("mode", "null"),
                                       delta=cell.get("delta", 0.0), mu_day=cell.get("mu_day", 0.0),
                                       ar=cell.get("ar", 0.0), kind=cell.get("kind", "in_sample"),
                                       n_days=cell.get("n_days", 14), first_day=cell.get("first_day", 15),
                                       best_of=cell.get("best_of", False), claimed=cell.get("claimed"),
                                       edge_family=cell.get("edge_family", "H01"))
            res.append({"verdict": r["verdict"], "reasons": r["reasons"]})
            if r["verdict"] != "INVALID_EVIDENCE" and cell.get("oracle", True):
                o = _oracle(ev, rd, cell.get("delta", 0.0))
                if o is not None:
                    oracles.append(o)
            np_ = _naive_p(ev)
            naive += 1 if (np_ is not None and np_ <= 0.05) else 0
            ct = cell.get("catching_tests")
            if ct and r["verdict"] not in OK_VERDICTS and any(f"{t}:FAIL" in r["reasons"] for t in ct):
                caught += 1
        vt, ft = _tally(res)
        n = len(res)
        out[cell["id"]] = {"reps": n, "params": {k: v for k, v in cell.items() if k != "id"},
                           "verdicts": {k: _rate(v, n) for k, v in sorted(vt.items())},
                           "forward_eligible_rate": _rate(sum(vt.get(v, 0) for v in OK_VERDICTS), n),
                           "provisional_rate": _rate(vt.get("PROVISIONAL", 0), n),
                           "naive_position_ttest_rejects": _rate(naive, n),
                           "oracle_true_net_edge_mean": S.mean(oracles) if oracles else None,
                           "failing_tests": dict(sorted(ft.items()))}
        if cell.get("catching_tests"):
            out[cell["id"]]["caught_by_listed_tests"] = _rate(caught, n)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m p2_research.falsification.calibration")
    ap.add_argument("--out", required=True)
    ap.add_argument("--study", action="append")
    ap.add_argument("--quick", action="store_true", help="pilot: 1/10 of the repetitions (not evidence)")
    ap.add_argument("--no-guard", action="store_true")
    a = ap.parse_args(argv)
    cs = C.default()
    plan_doc = cs.calibration
    plan_sha = cs.sha256
    proto = cs.protocol
    prof = plan_doc["battery_reps_profile"]
    bat = cs.battery(reps_profile=prof)
    guard = Guard(plan_doc, enabled=not a.no_guard)
    os.makedirs(a.out, exist_ok=True)
    studies = a.study or [s["id"] for s in plan_doc["studies"]]
    t0 = time.time()
    for st in plan_doc["studies"]:
        if st["id"] not in studies:
            continue
        cfg = dict(st)
        if a.quick:
            cfg["reps"] = max(2, cfg["reps"] // 10)
        ts = time.time()
        try:
            if st["id"] == "C1":
                res = study_c1(cfg, plan_sha, guard)
            else:
                res = study_battery(cfg, plan_sha, guard, cs.sha256, proto, cs.plan, bat, st["id"])
        except Abort as e:
            sys.stderr.write(f"ABORT {e}\n")
            return 3
        doc = {"record": "tsb.p2f.calibration_result", "record_version": 1, "study": st["id"],
               "title": st["title"], "quick": a.quick, "f0_contract_set_sha256": cs.sha256,
               "battery_reps_profile": prof, "results": B._r(res)}
        with open(os.path.join(a.out, f"{st['id']}{'_quick' if a.quick else ''}.json"), "w", encoding="ascii") as fh:
            fh.write(json.dumps(doc, sort_keys=True, indent=1) + "\n")
        sys.stderr.write(f"{st['id']} done in {time.time() - ts:.0f}s (blackout sleep {guard.slept:.0f}s)\n")
    sys.stderr.write(f"total {time.time() - t0:.0f}s\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
