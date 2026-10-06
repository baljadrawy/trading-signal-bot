"""P2-C <-> P2-X contract closure (X1-JOIN 2.0.0, ``contracts_v2/p2c_join_v2.json``): a versioned adapter layer.

Nothing frozen is rewritten: P2-C rows (feature set p2c-fs 1.0.0) and P2-X v1 leg records keep their bytes and
ids. The adapter adds, per P2-C row, an EXECUTION REQUEST (canonical instrument identity, P2-C row reference,
decision-time epoch tier, scenario, side, notional, exit definition) and, per estimate, a JOINED RECORD that splits
the leg's fields by knowledge time (``result_schema_v2.json``: STATIC / DECISION on the decision side; EXECUTION /
UNAVAILABLE_BY_DESIGN on the label side). Join key: (instrument_id, decision_time_ms).

The join tool reads ONLY the P2-C manifest and the key / PIT columns of ``features.jsonl.gz`` (row_id, symbol,
decision_time_ms, tier, universe_id, feature_available_at) plus three decision-time data-quality values used for a
same-state consistency check (liq.spread_bps, dq.book_age_s). It never opens ``labels.jsonl.gz`` and computes no
return. Rows inside W3 are refused (unmatched with an explicit reason), never read for anything else.

Usage: python -m p2_research.execution.join --p2c DIR --dataset DIR --days 2026-10-04 2026-10-05 --out OUTDIR
       [--code-commit SHA]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import io
import json
import os
import sys

from .. import instrument as IN, ledger as LG, reader as RD
from . import contracts_v2 as CT2, model as M
from .coverage import code_tree_sha256
from .market_state import PITMarketView, load_sealed
from .schema import canon, sha256_text, with_id

JOIN_VERSION = "p2x1-join-v1"
REQUEST_RECORD, JOINED_RECORD = "tsb.p2x.execution_request", "tsb.p2x.joined_execution"
FORBIDDEN_ROOT = LG.FORBIDDEN_ROOT
DECISION_SIDE = ("STATIC", "DECISION")
LABEL_SIDE = ("EXECUTION", "UNAVAILABLE_BY_DESIGN")
KEY_COLUMNS = ("row_id", "symbol", "decision_time_ms", "tier", "universe_id", "run_boot8")
CHECK_FEATURES = ("liq.spread_bps", "dq.book_age_s")


class JoinError(ValueError):
    pass


# ---------------------------------------------------------------- identities ------
def p2c_identity(man: dict) -> dict:
    src = man["source"]
    return {"dataset_id": src["dataset_id"], "dataset_json_sha256": src["dataset_json_sha256"],
            "days": list(src["days"]), "seal_sha256": {d: v["seal_sha256"] for d, v in src["day_seals"].items()},
            "logical_hash": man["logical_hash"],
            "feature_set": {"id": man["feature_set"]["id"], "version": man["feature_set"]["version"],
                            "registry_sha256": man["feature_set"]["registry_sha256"]}}


def check_identity(p2c: dict, p2x_meta: dict) -> dict:
    """F3: P2-X ``market_data.dataset_sha256`` == P2-C ``source.dataset_json_sha256``; same dataset id; every P2-X
    day is a P2-C day with the SAME seal SHA. Anything else refuses the join (fail closed)."""
    probs = []
    if p2x_meta.get("dataset_id") != p2c["dataset_id"]:
        probs.append("dataset_id")
    if p2x_meta.get("dataset_sha256") != p2c["dataset_json_sha256"]:
        probs.append("dataset_sha256_vs_dataset_json_sha256")
    for d in p2x_meta.get("days") or []:
        if d not in p2c["seal_sha256"]:
            probs.append(f"day_not_in_p2c:{d}")
        elif (p2x_meta.get("seal_sha256") or {}).get(d) != p2c["seal_sha256"][d]:
            probs.append(f"seal_sha256:{d}")
    if probs:
        raise JoinError(f"JOIN_IDENTITY_MISMATCH: {probs}")
    return {"dataset_id": p2c["dataset_id"], "dataset_sha256": p2c["dataset_json_sha256"],
            "days": sorted(p2x_meta["days"]), "seal_sha256": {d: p2c["seal_sha256"][d] for d in sorted(p2x_meta["days"])}}


def row_ref(p2c: dict, row: dict) -> dict:
    """F2: the P2-C row a request / joined record pairs with."""
    return {"dataset_logical_hash": p2c["logical_hash"], "feature_set": dict(p2c["feature_set"]), "row_id": row["row_id"]}


# ---------------------------------------------------------------- request / joined record ------
def exit_definition(C, side: str) -> str:
    j = C.docs["p2c_join_v2.json"]
    return j["exit_definitions"]["p2x_exit_leg"]["id"] if side == "sell" else j["exit_definitions"]["p2x_entry_leg"]["id"]


def execution_request(C, p2c: dict, row: dict, scenario_id: str, side: str, notional: float) -> dict:
    inst = IN.binance_spot_instrument(row["symbol"])                     # F1: deterministic, crypto Binance spot only
    sc = C.scenario(scenario_id)
    rec = {"record": REQUEST_RECORD, "record_version": 1,
           "join_contract": {"id": C.docs["p2c_join_v2.json"]["id"], "version": C.docs["p2c_join_v2.json"]["version"]},
           "contract_set_sha256": C.sha256,
           "instrument": inst.as_dict(), "instrument_id_derivation": "p2_research.instrument.binance_spot_instrument",
           "decision_time_ms": int(row["decision_time_ms"]), "decision_epoch_tier": row["tier"],
           "universe_id": row["universe_id"], "p2c_row_ref": row_ref(p2c, row),
           "scenario": {"id": sc["id"], "version": sc["version"]}, "direction": "long", "side": side,
           "leg": M.SIDES[side][1], "order_notional": {"value": float(notional), "currency": inst.quote_currency},
           "exit_definition": exit_definition(C, side)}
    return with_id(rec, "request_id")


def _path_get(rec, path):
    cur = rec
    for p in path.split("."):
        cur = cur[p]
    return cur


def split_by_knowledge_time(C, leg: dict) -> tuple:
    """(decision_side, label_side, reference) per the frozen field map; an unmapped field refuses the split."""
    kt = C.knowledge_time
    nested = {p.split(".")[0] for p in kt if "." in p}
    dec, lab, ref, seen = {}, {}, {}, set()
    for k, v in leg.items():
        paths = [f"{k}.{s}" for s in v] if k in nested and isinstance(v, dict) else [k]
        if k in nested and v is None:
            paths = [p for p in kt if p.startswith(k + ".")]
        for p in paths:
            cls = kt.get(p)
            if cls is None:
                raise JoinError(f"FIELD_WITHOUT_KNOWLEDGE_TIME: {p}")
            val = _path_get(leg, p) if v is not None else None
            tgt = dec if cls in DECISION_SIDE else lab if cls in LABEL_SIDE else ref if cls == "REFERENCE" else None
            if tgt is None:
                raise JoinError(f"UNKNOWN_KNOWLEDGE_TIME_CLASS: {cls}")
            tgt[p] = val
            seen.add(p)
    missing = [p for p in kt if p not in seen]
    if missing:
        raise JoinError(f"MAPPED_FIELD_ABSENT: {missing}")
    return dec, lab, ref


def pit_violations(leg: dict, dec: dict, row: dict) -> list:
    """Structural PIT checks of one joined record (must be empty)."""
    out = []
    T = leg["decision_time_ms"]
    if T != row["decision_time_ms"]:
        out.append("decision_time_mismatch")
    age = leg["market_data_age"]["decision_book_quote_age_ms"]["value"]
    if age is not None and age < 0:
        out.append("decision_book_observed_after_T")
    fa = [v for v in (row.get("feature_available_at") or {}).values() if v is not None]
    if fa and max(fa) > T:
        out.append("p2c_feature_available_after_T")
    for p in dec:
        if p.split(".")[0] in ("bid", "ask", "mid", "touch", "fill", "tier", "depth_walk", "total_cost_bps"):
            out.append(f"execution_field_on_decision_side:{p}")
    if leg["execution_time_ms"] < T:
        out.append("execution_before_decision")
    return out


def joined_record(C, request: dict, leg: dict, row: dict) -> dict:
    dec, lab, ref = split_by_knowledge_time(C, leg)
    if "tier" in lab:
        lab["execution_record_tier"] = lab.pop("tier")                    # F5: record tier at execution time
    rec = {"record": JOINED_RECORD, "record_version": 1,
           "join_key": {"instrument_id": request["instrument"]["instrument_id"],
                        "decision_time_ms": request["decision_time_ms"]},
           "request_id": request["request_id"], "estimate_id": leg["estimate_id"],
           "p2c_row_ref": request["p2c_row_ref"], "decision_epoch_tier": request["decision_epoch_tier"],
           "exit_definition": request["exit_definition"],
           "knowledge_time_ms": {"decision_side": leg["decision_time_ms"], "label_side": leg["execution_time_ms"]},
           "decision_side": dec, "label_side": lab}
    return with_id(rec, "joined_id")


# ---------------------------------------------------------------- P2-C dataset access (keys only) ------
def read_p2c(p2c_dir: str) -> tuple:
    """(manifest, rows) from a P2-C research dataset dir: manifest logical hash and features file hash are verified;
    only key / PIT columns and the consistency-check values are kept. labels.jsonl.gz is never opened."""
    with open(os.path.join(p2c_dir, "manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    body = {k: v for k, v in man.items() if k not in ("logical_hash", "build_timestamp_utc", "output_dir",
                                                     "existing", "build_execution")}
    if hashlib.sha256(RD.canon(body).encode()).hexdigest() != man["logical_hash"]:
        raise JoinError("P2C_MANIFEST_LOGICAL_HASH_MISMATCH")
    h = hashlib.sha256()
    rows = []
    with gzip.open(os.path.join(p2c_dir, "features.jsonl.gz"), "rb") as fh:
        for line in fh:
            h.update(line)
            r = json.loads(line)
            keys = {k: r.get(k) for k in KEY_COLUMNS}
            try:
                M.require_outside_w3(int(r["decision_time_ms"]), "p2c_row")
            except LG.W3SealedError:                                     # W3 row: keys only, no value is retained
                rows.append({**keys, "feature_available_at_max": None, "check": {k: None for k in CHECK_FEATURES}})
                continue
            fa = r.get("feature_available_at") or {}
            rows.append({**keys,
                         "feature_available_at_max": max((v for v in fa.values() if v is not None), default=None),
                         "check": {k: (r.get("features") or {}).get(k) for k in CHECK_FEATURES}})
    if h.hexdigest() != man["files"]["features.jsonl.gz"]["sha256_uncompressed"]:
        raise JoinError("P2C_FEATURES_SHA_MISMATCH")
    if len(rows) != man["files"]["features.jsonl.gz"]["rows"]:
        raise JoinError("P2C_FEATURES_ROWCOUNT_MISMATCH")
    return man, rows


def partition(rows: list, lats: list, days: list) -> tuple:
    """(keyed {join_key: row}, unmatched reasons Counter, duplicate-key count). W3 rows are refused before any use."""
    end_ms = RD.day_start_ms(sorted(days)[-1]) + RD.DAY_MS
    keyed, unmatched, dup = {}, collections.Counter(), 0
    for r in rows:
        T = int(r["decision_time_ms"])
        try:
            for L in lats:
                M.require_outside_w3(T + L, "decision_or_execution_time")
        except LG.W3SealedError:
            unmatched["decision_time_inside_w3_refused"] += 1
            continue
        if T + max(lats) >= end_ms or RD.day_key(T) not in days:
            unmatched["execution_time_beyond_sealed_range"] += 1
            continue
        k = (IN.binance_spot_instrument(r["symbol"]).instrument_id, T)
        if k in keyed:
            dup += 1
            continue
        keyed[k] = r
    return keyed, unmatched, dup


def _inside(child, parent):
    c, p = os.path.realpath(child), os.path.realpath(parent)
    return c == p or c.startswith(p + os.sep)


def run(p2c_dir: str, base: str, days: list, out_dir: str, code_commit: str, notional: float = 50.0,
        contracts=None) -> dict:
    if _inside(out_dir, base) or _inside(out_dir, FORBIDDEN_ROOT) or _inside(out_dir, p2c_dir):
        raise SystemExit(f"refused: output {out_dir} inside an input tree")
    C = contracts or CT2.default()
    man, rows = read_p2c(p2c_dir)
    p2c = p2c_identity(man)
    days = sorted(days)
    scen = sorted(C.scenarios)
    lats = sorted({C.model(C.scenario(s)["latency_model"])["latency_ms"] for s in scen})
    rep = collections.defaultdict(collections.Counter)
    ids = collections.Counter(r["row_id"] for r in rows)
    rep["p2c_rows"]["total"] = len(rows)
    rep["p2c_rows"]["duplicate_row_ids"] = sum(1 for v in ids.values() if v > 1)
    keyed, unmatched, dup = partition(rows, lats, days)
    rep["ambiguity"]["duplicate_join_key_in_p2c"] = dup
    Ts = sorted({k[1] for k in keyed})
    qts = sorted({t + L for t in Ts for L in lats})
    S = load_sealed(base, days, query_times=qts)
    ident = check_identity(p2c, S.meta)
    # reverse direction: the P2-X-native universe at each T (same as-of rule) vs the P2-C rows
    native = set()
    for T in Ts:
        ep = PITMarketView(S, T).epoch_at(T)
        for sym in (ep or {}).get("tiers", {}):
            native.add((IN.binance_spot_instrument(sym).instrument_id, T))
    rep["reverse"]["p2x_native_keys"] = len(native)
    rep["reverse"]["p2x_native_without_p2c_row"] = len(native - set(keyed))
    rep["reverse"]["p2c_row_without_p2x_native_key"] = len(set(keyed) - native)
    buf, sha = io.BytesIO(), hashlib.sha256()
    gz = gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=6)
    n_lines = 0
    per_key = collections.Counter()
    pit = collections.Counter()
    cons = collections.Counter()
    for k in sorted(keyed):
        r = keyed[k]
        ep_tier = (PITMarketView(S, k[1]).epoch_at(k[1]) or {}).get("tiers", {}).get(r["symbol"])
        rep["tier"]["p2c_tier_equals_p2x_epoch_tier_at_T" if ep_tier == r["tier"] else "p2c_tier_differs_from_p2x_epoch_tier"] += 1
        row_pit = {"decision_time_ms": int(r["decision_time_ms"]),
                   "feature_available_at": {"max": r["feature_available_at_max"]}}
        for sc in scen:
            for side in ("buy", "sell"):
                req = execution_request(C, p2c, r, sc, side, notional)
                leg = M.estimate_leg(S, IN.binance_spot_instrument(r["symbol"]), side, notional, k[1], sc, contracts=C)
                j = joined_record(C, req, leg, r)
                v = pit_violations(leg, j["decision_side"], row_pit)
                for x in v:
                    pit[x] += 1
                per_key[(k, sc, side)] += 1
                rt = j["label_side"].get("execution_record_tier")
                rep["tier"]["execution_record_tier_differs_from_decision_epoch_tier" if (rt is not None and rt != r["tier"])
                            else "execution_record_tier_same_or_null"] += 1
                rep["coverage"][f"{sc}.{side}.fill_available" if leg["fill"]["value"] is not None
                                else f"{sc}.{side}.fill_unavailable"] += 1
                if sc == "EXEC-IDEALIZED" and side == "buy":
                    b, a = leg["decision_bid"]["value"], leg["decision_ask"]["value"]
                    xs = None if b is None else (a - b) / ((a + b) / 2) * 1e4
                    cs = r["check"]["liq.spread_bps"]
                    if cs is None or xs is None:
                        why = "" if xs is not None else ":" + ",".join(
                            f for f in leg["data_quality"]["decision_book"]["flags"] if f)
                        cons[f"spread.p2c_{'null' if cs is None else 'value'}_p2x_{'null' if xs is None else 'value'}{why}"] += 1
                    else:
                        cons["spread.equal" if abs(cs - xs) <= 1e-9 * max(1.0, abs(xs)) else "spread.MISMATCH"] += 1
                    ca = r["check"]["dq.book_age_s"]
                    xa = leg["market_data_age"]["decision_book_quote_age_ms"]["value"]
                    if ca is None or xa is None:
                        cons["book_age.one_side_null"] += 1
                    else:
                        cons["book_age.equal" if abs(ca * 1000 - xa) <= 1e-6 else "book_age.MISMATCH"] += 1
                line = canon(j)
                gz.write((line + "\n").encode())
                sha.update((line + "\n").encode())
                n_lines += 1
    gz.close()
    rep["ambiguity"]["join_keys_with_more_than_one_estimate_per_scenario_side"] = sum(1 for v in per_key.values() if v != 1)
    rep["matched"]["join_keys"] = len(keyed)
    rep["matched"]["joined_records"] = n_lines
    report = {"record": "tsb.p2x.join_report", "record_version": 1,
              "join_key": ["instrument_id", "decision_time_ms"],
              "join_key_unique_in_p2c": rep["ambiguity"]["duplicate_join_key_in_p2c"] == 0 and rep["p2c_rows"]["duplicate_row_ids"] == 0,
              "unmatched_p2c_rows": dict(sorted(unmatched.items())),
              "ambiguous": dict(sorted(rep["ambiguity"].items())),
              "pit_violations": dict(sorted(pit.items())), "pit_violations_total": sum(pit.values()),
              "same_state_consistency": dict(sorted(cons.items())),
              "counts": {k: dict(sorted(v.items())) for k, v in sorted(rep.items()) if k != "ambiguity"},
              "identity": ident, "p2c": {"logical_hash": p2c["logical_hash"], "feature_set": p2c["feature_set"]}}
    rep_txt = json.dumps(report, sort_keys=True, indent=1) + "\n"
    out = {"record": "tsb.p2x.join_manifest", "record_version": 1, "join_version": JOIN_VERSION,
           "code_commit": code_commit, "code_tree_sha256": code_tree_sha256(), "contract_set_sha256": C.sha256,
           "contract_files": C.sums, "market_data": S.meta, "p2c_manifest_logical_hash": man["logical_hash"],
           "p2c_features_sha256_uncompressed": man["files"]["features.jsonl.gz"]["sha256_uncompressed"],
           "segments": sorted((s["path"], s["sha256"], s["records"]) for s in S.provenance["segments"]),
           "estimate_notional": notional, "scenarios": scen, "decision_times": len(Ts),
           "files": {"joined.jsonl.gz": {"sha256_uncompressed": sha.hexdigest(), "records": n_lines},
                     "join_report.json": {"sha256": sha256_text(rep_txt)}}}
    out["logical_hash"] = sha256_text(canon(out))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "joined.jsonl.gz"), "wb") as fh:
        fh.write(buf.getvalue())
    with open(os.path.join(out_dir, "join_report.json"), "w", encoding="utf-8") as fh:
        fh.write(rep_txt)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out, sort_keys=True, indent=1) + "\n")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p2c", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--days", required=True, nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--code-commit", default="uncommitted")
    a = ap.parse_args(argv)
    m = run(a.p2c, a.dataset, a.days, a.out, a.code_commit)
    print(json.dumps({"logical_hash": m["logical_hash"], "joined": m["files"]["joined.jsonl.gz"]["records"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
