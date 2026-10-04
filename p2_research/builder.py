"""Deterministic research-dataset builder (P2-C). Offline; reads sealed days read-only; writes only under an
allowed output root (never inside the collector dataset or the P2 raw-data tree).

Usage:
  python -m p2_research.builder --dataset DIR --days 2026-10-05[,2026-10-06] --code-commit SHA
         [--out /home/tradmin/research-data/trading-signal-bot/p2c] [--experimental-active-day]

Outputs (directory ``<out>/<dataset_id>/<fs>-<ls>/<logical_hash[:16]>/``):
  features.jsonl.gz  one row per (symbol, decision_time): features, feature_available_at, feature_null_reasons
  labels.jsonl.gz    same row_id: forward labels (mkt.* / exe.*), label_null_reasons, post-hoc quality flags
  excluded.jsonl.gz  structurally excluded (symbol, decision_time) with reason
  manifest.json      provenance, versions, counts, quality summary, logical hash (build timestamp excluded)
Identical inputs (source bytes, days, versions, code) => identical logical hash and identical content files.
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
import shutil
import sys
import tempfile

from . import PACKAGE_VERSION, features as FE, labels as LB, registry as RG
from .reader import READER_VERSION, ReaderError, canon, load_days

UNIVERSE_POLICY = "universe-asof-all-tiers-v1"
DEFAULT_OUT = "/home/tradmin/research-data/trading-signal-bot/p2c"
FORBIDDEN_ROOT = "/home/tradmin/research-data/trading-signal-bot/p2"
MANIFEST_RECORD = "tsb.p2c.research_dataset"


class BuildError(Exception):
    pass


def code_tree_sha256() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    h = hashlib.sha256()
    for f in sorted(os.listdir(here)):
        if f.endswith(".py"):
            with open(os.path.join(here, f), "rb") as fh:
                h.update(f.encode() + b"\0" + fh.read() + b"\0")
    return h.hexdigest()


def _inside(child: str, parent: str) -> bool:
    c, p = os.path.realpath(child), os.path.realpath(parent)
    return c == p or c.startswith(p.rstrip("/") + "/")


def check_out_root(out_root: str, dataset_dir: str) -> None:
    if _inside(out_root, dataset_dir) or _inside(out_root, FORBIDDEN_ROOT) or _inside(dataset_dir, out_root):
        raise BuildError(f"output root not allowed (inside source/collector tree): {out_root}")
    allowed = [DEFAULT_OUT, tempfile.gettempdir(), "/tmp"]
    if not any(_inside(out_root, a) for a in allowed):
        raise BuildError(f"output root must be under {DEFAULT_OUT} or a scratch/temp dir: {out_root}")


def _gz_lines(lines: list) -> tuple:
    raw = "".join(x + "\n" for x in lines).encode()
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=6) as gz:
        gz.write(raw)
    return buf.getvalue(), hashlib.sha256(raw).hexdigest()


def decision_times(start_ms: int, end_ms: int) -> list:
    g = RG.DECISION_GRID
    t = (start_ms // g["step_ms"]) * g["step_ms"] + g["offset_ms"]
    out = []
    while t < end_ms:
        if t >= start_ms:
            out.append(t)
        t += g["step_ms"]
    return out


def build_rows(B) -> tuple:
    feats, labs, excl = [], [], []
    nulls, lnulls = collections.Counter(), collections.Counter()
    posthoc = 0
    reg_ids = [f["id"] for f in RG.FEATURES]
    for T in decision_times(B.range_start_ms, B.range_end_ms):
        V = FE.PITView(B, T)
        syms = sorted(V.epoch["tiers"]) if V.epoch is not None else []
        reason = ("beyond_observed_data" if B.observed_until_ms is None or T > B.observed_until_ms else
                  "in_downtime" if V.run is None else "no_universe_epoch_known" if V.epoch is None else None)
        if reason:
            excl += ([{"row_id": f"{s}|{T}", "symbol": s, "decision_time_ms": T, "reason": reason} for s in syms] or
                     [{"row_id": f"*|{T}", "symbol": None, "decision_time_ms": T, "reason": reason}])
            continue
        ctx, btc = FE.market_context(V), FE.btc_context(V)
        for s in syms:
            o = FE.compute(V, s, ctx, btc)
            if sorted(o.v) != sorted(reg_ids):
                raise BuildError(f"feature set mismatch for {s}@{T}: {sorted(set(o.v) ^ set(reg_ids))}")
            for k, a in o.a.items():
                if o.v[k] is not None and (a is None or a > T):
                    raise FE.PITViolation(f"{k} for {s}@{T}: feature_available_at={a} > decision_time")
            for k, r in o.r.items():
                nulls[f"{k}:{r}"] += 1
            rid = f"{s}|{T}"
            feats.append(canon({"row_id": rid, "symbol": s, "decision_time_ms": T, "tier": V.epoch["tiers"][s],
                                "universe_id": V.epoch["universe_id"], "run_boot8": V.run["boot8"],
                                "features": o.v, "feature_available_at": o.a, "feature_null_reasons": o.r}))
            L, R = LB.compute_labels(B, s, T)
            for k, r in R.items():
                lnulls[f"{k}:{r}"] += 1
            # post-hoc quality: a gap record covering T that became known only AFTER T (label side only)
            keys = {f"book|{s}", f"depth|{s}", "market|ALL"}
            ph = any(g["stream_key"] in keys and g["available_at_ms"] > T and g["first_missing_ms"] <= T < g["end_ms"]
                     for g in B.gaps)
            posthoc += ph
            labs.append(canon({"row_id": rid, "symbol": s, "decision_time_ms": T, "labels": L,
                               "label_null_reasons": R, "qa": {"posthoc_gap_at_decision": ph}}))
    return feats, labs, excl, nulls, lnulls, posthoc


def build(dataset_dir: str, days: list, out_root: str = DEFAULT_OUT, *, code_commit: str,
          feature_set: str = RG.FEATURE_SET_VERSION, label_set: str = LB.LABEL_SET_VERSION,
          universe_policy: str = UNIVERSE_POLICY, experimental_active_day: bool = False, build_ts: str | None = None,
          write: bool = True) -> dict:
    if feature_set != RG.FEATURE_SET_VERSION:
        raise BuildError(f"unsupported feature set version {feature_set}")
    if label_set != LB.LABEL_SET_VERSION:
        raise BuildError(f"unsupported label set version {label_set}")
    if universe_policy != UNIVERSE_POLICY:
        raise BuildError(f"unsupported universe policy {universe_policy}")
    if not code_commit:
        raise BuildError("code_commit required")
    check_out_root(out_root, dataset_dir)
    B = load_days(dataset_dir, days, experimental_active_day=experimental_active_day)
    feats, labs, excl, nulls, lnulls, posthoc = build_rows(B)
    fz, fsha = _gz_lines(feats)
    lz, lsha = _gz_lines(labs)
    ez, esha = _gz_lines([canon(x) for x in excl])
    symbols = sorted({json.loads(x)["symbol"] for x in feats})
    times = [json.loads(x)["decision_time_ms"] for x in feats[:1] + feats[-1:]]
    manifest = {
        "record": MANIFEST_RECORD, "record_version": 1, "package_version": PACKAGE_VERSION,
        "reader_version": READER_VERSION, "code_commit": code_commit, "code_tree_sha256": code_tree_sha256(),
        "source": {"dataset_id": B.dataset["dataset_id"], "dataset_json_sha256": B.dataset["_sha256"],
                   "days": B.days, "mode": B.mode, "reproducible": B.reproducible,
                   "schema": "tsb.p2.forward", "schema_versions_consumed": [2], "day_seals": B.provenance["days"],
                   "segments": B.provenance["segments"], "run_records": B.provenance["runs"],
                   "universe_files": B.provenance["universe_files"]},
        "feature_set": {"id": RG.FEATURE_SET_ID, "version": RG.FEATURE_SET_VERSION, "registry_sha256": RG.registry_sha256(),
                        "count": len(RG.FEATURES), "decision_grid": RG.DECISION_GRID},
        "label_set": {"id": LB.LABEL_SET_ID, "version": LB.LABEL_SET_VERSION, "horizons": list(LB.HORIZONS),
                      "decline_threshold": LB.DECLINE_THRESHOLD, "fee_bps_per_side": LB.FEE_BPS_PER_SIDE,
                      "definitions_sha256": hashlib.sha256(canon(LB.label_definitions()).encode()).hexdigest()},
        "universe_policy": UNIVERSE_POLICY,
        "row_count": len(feats), "excluded_count": len(excl),
        "excluded_by_reason": dict(sorted(collections.Counter(x["reason"] for x in excl).items())),
        "symbols": symbols, "time_range_ms": [min(times), max(times)] if times else None,
        "range_ms": [B.range_start_ms, B.range_end_ms], "observed_until_ms": B.observed_until_ms,
        "quality_summary": {"reader": B.summary()["quality"], "downtime_intervals": B.downtime,
                            "feature_nulls": dict(sorted(nulls.items())), "label_nulls": dict(sorted(lnulls.items())),
                            "rows_posthoc_gap_at_decision": posthoc, "gaps": len(B.gaps),
                            "epochs": [{k: e[k] for k in ("effective_from_ms", "available_at_ms", "universe_id", "kind")}
                                       for e in B.epochs]},
        "files": {"features.jsonl.gz": {"sha256_uncompressed": fsha, "rows": len(feats)},
                  "labels.jsonl.gz": {"sha256_uncompressed": lsha, "rows": len(labs)},
                  "excluded.jsonl.gz": {"sha256_uncompressed": esha, "rows": len(excl)}},
    }
    manifest["logical_hash"] = hashlib.sha256(canon(manifest).encode()).hexdigest()
    manifest["build_timestamp_utc"] = build_ts or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not write:
        return manifest
    sub = "EXPERIMENTAL-nonreproducible" if not B.reproducible else f"{RG.FEATURE_SET_ID}{RG.FEATURE_SET_VERSION}-{LB.LABEL_SET_ID}{LB.LABEL_SET_VERSION}"
    final = os.path.join(out_root, B.dataset["dataset_id"], sub, manifest["logical_hash"][:16])
    if os.path.exists(final):
        with open(os.path.join(final, "manifest.json"), encoding="utf-8") as fh:
            old = json.load(fh)
        if old.get("logical_hash") != manifest["logical_hash"]:
            raise BuildError(f"existing build dir with different logical hash: {final}")
        manifest["output_dir"], manifest["existing"] = final, True
        return manifest
    os.makedirs(os.path.dirname(final), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".build-", dir=os.path.dirname(final))
    try:
        for name, data in (("features.jsonl.gz", fz), ("labels.jsonl.gz", lz), ("excluded.jsonl.gz", ez)):
            with open(os.path.join(tmp, name), "wb") as fh:
                fh.write(data)
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, sort_keys=True, indent=1)
            fh.write("\n")
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    manifest["output_dir"] = final
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--days", required=True, help="comma-separated consecutive YYYY-MM-DD")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--code-commit", required=True)
    ap.add_argument("--experimental-active-day", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    try:
        m = build(a.dataset, a.days.split(","), a.out, code_commit=a.code_commit,
                  experimental_active_day=a.experimental_active_day, write=not a.no_write)
    except (ReaderError, BuildError, FE.PITViolation) as e:
        print(json.dumps({"result": "REFUSED", "error": type(e).__name__, "detail": str(e)}))
        return 2
    print(json.dumps({"result": "OK", "logical_hash": m["logical_hash"], "rows": m["row_count"],
                      "excluded": m["excluded_count"], "mode": m["source"]["mode"],
                      "reproducible": m["source"]["reproducible"], "output_dir": m.get("output_dir")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
