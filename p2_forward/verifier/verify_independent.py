#!/usr/bin/env python3
"""Independent verifier for tsb P2 forward data, schema v2 (P2-E1 G2-Repeat acceptance; F26 / F27 / F52 / F53).

INDEPENDENCE: this file imports NOTHING from the collector package (`p2_forward`). It reimplements the field list,
`obs_id` formatting, SHA-256 hashing, the cadence and boundary arithmetic, the expected-stream derivation and the
gap reconciliation from the documented contract (SCHEMA.md v2). A test enforces the no-import rule.

Documented, unavoidable shared assumptions:
  1. gzip / JSON decoding (Python stdlib);
  2. field meanings as defined in SCHEMA.md v2;
  3. configuration values (cadences, depth N, deadlines, Tier-0 symbols) are read AS DATA from the run's own run
     record; expected streams are re-derived from that config and cross-checked against the record's list;
  4. window anchors (ws_start_ms, stop_requested_ms) are read as data from the lifecycle records and
     sanity-checked against record receive times; per-stream `stream_ready.ready_ms` is used ONLY to tighten the
     startup excuse (a boundary is excused only if it precedes the deadline, the first persisted record's own
     receive time AND the claimed ready time), never to widen it;
  5. Binance message semantics.

Usage: python3 verify_independent.py <data_dir> [--boot BOOT_ID] [--json out.json]   (stdlib only, read-only)
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
import stat
import sys

TF = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
FIELDS_V2 = {"schema": str, "schema_version": int, "obs_id": str, "type": str, "source": str, "transport": str,
             "endpoint": str, "recv_ts_ns": int, "observed_at_ms": int, "available_at_ms": int, "unchanged": bool,
             "clock_suspect": bool, "collector_version": str, "boot_id": str}
NULLABLE = ("symbol", "tier", "cadence_ms", "sample_ms", "exchange_event_time_ms", "exchange_seq", "queued_ts_ns",
            "blk", "recoverability", "payload")
KINDS = {"book", "depth", "market", "candle", "clock", "universe", "gap", "lifecycle", "health"}
IRR, REC = "IRREPLACEABLE_FORWARD_OBSERVATION", "RECOVERABLE_WHERE_ARCHIVE_AVAILABLE"
CANDLE_MARGIN_MS = 15_000 + 300_000 + 60_000       # fetch offset + round spread + fetch time


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class Report:
    def __init__(self):
        self.failures = collections.Counter()
        self.examples = collections.defaultdict(list)
        self.info = {}

    def fail(self, code: str, example=None) -> None:
        self.failures[code] += 1
        if example is not None and len(self.examples[code]) < 5:
            self.examples[code].append(example)


def load_files(base: str, rp: Report) -> list:
    manifest = {}
    mdir = os.path.join(base, "manifests")
    for f in sorted(os.listdir(mdir)) if os.path.isdir(mdir) else []:
        with open(os.path.join(mdir, f), encoding="utf-8") as fh:
            for line in fh:
                e = json.loads(line)
                if e["segment"] in manifest:
                    rp.fail("MANIFEST_DUPLICATE_ENTRY", e["segment"])
                manifest[e["segment"]] = e
    segs, partials = [], []
    for root, _, files in os.walk(os.path.join(base, "raw")):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), base)
            if f.endswith(".partial"):
                partials.append(rel)
            elif f.endswith(".jsonl.gz"):
                segs.append(rel)
    for p in partials:
        rp.fail("LEFTOVER_PARTIAL", p)
    if set(segs) != set(manifest):
        for s in sorted(set(segs) - set(manifest)):
            rp.fail("SEGMENT_NOT_IN_MANIFEST", s)
        for s in sorted(set(manifest) - set(segs)):
            rp.fail("MANIFEST_ENTRY_WITHOUT_FILE", s)
    out = []
    for rel in sorted(segs):
        p = os.path.join(base, rel)
        d = sha256(p)
        try:
            with open(p + ".sha256", encoding="utf-8") as fh:
                side = fh.read().split()[0]
        except OSError:
            side = None
        if side != d:
            rp.fail("CHECKSUM_SIDECAR_MISMATCH", rel)
        if manifest.get(rel, {}).get("sha256") != d:
            rp.fail("CHECKSUM_MANIFEST_MISMATCH", rel)
        for q in (p, p + ".sha256", p[:-9] + ".idx"):
            if os.path.exists(q) and os.stat(q).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                rp.fail("NOT_READ_ONLY", os.path.relpath(q, base))
        lines = []
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                for line in fh:
                    lines.append(json.loads(line))
        except (OSError, EOFError, ValueError) as e:
            rp.fail("DECODE_ERROR", f"{rel}:{type(e).__name__}")
            continue
        idx_records = 0
        try:
            with open(p[:-9] + ".idx", encoding="utf-8") as fh:
                for line in fh:
                    idx_records += json.loads(line)["records"]
        except (OSError, ValueError, KeyError):
            rp.fail("IDX_UNREADABLE", rel)
        if idx_records != len(lines):
            rp.fail("IDX_RECORD_COUNT_MISMATCH", f"{rel}:{idx_records}!={len(lines)}")
        if manifest.get(rel, {}).get("records") != len(lines):
            rp.fail("MANIFEST_RECORD_COUNT_MISMATCH", rel)
        out.append((rel, lines, manifest.get(rel, {})))
    return out


def check_fields(r: dict, rp: Report) -> bool:
    for k, t in FIELDS_V2.items():
        if k not in r or not isinstance(r[k], t) or (t is int and isinstance(r[k], bool)):
            rp.fail("FIELD_MISSING_OR_TYPE", f"{r.get('obs_id')}:{k}"); return False
    for k in NULLABLE:
        if k not in r:
            rp.fail("FIELD_MISSING_OR_TYPE", f"{r.get('obs_id')}:{k}"); return False
    if r["schema"] != "tsb.p2.forward" or r["schema_version"] != 2:
        rp.fail("SCHEMA_NOT_V2", r["obs_id"]); return False
    if r["type"] not in KINDS:
        rp.fail("UNKNOWN_TYPE", r["obs_id"]); return False
    if r["observed_at_ms"] != r["recv_ts_ns"] // 1_000_000:
        rp.fail("OBSERVED_NE_RECV", r["obs_id"])
    if r["type"] != "candle" and r["available_at_ms"] != r["observed_at_ms"]:
        rp.fail("AVAILABLE_NE_OBSERVED", r["obs_id"])
    return True


def derive_expected(run: dict, rp: Report) -> dict:
    """Expected streams re-derived from the run's config (as data), cross-checked with its expected_streams list."""
    cfg = run["config"]
    cad, lv, dl = cfg["cadence_ms"], cfg["depth_levels"], cfg["first_obs_deadline_s"]
    exp = {}
    tiers = {0: run["universe"]["snapshot"]["tier0"], 1: run["universe"]["snapshot"]["tier1"],
             2: run["universe"]["snapshot"]["tier2"]}
    for tier, syms in tiers.items():
        t = f"t{tier}"
        for s in syms:
            exp[f"{s.lower()}@bookTicker"] = {"kind": "book", "symbol": s, "tier": tier, "cadence": cad[f"{t}_book"],
                                              "deadline_ms": 1000 * (dl["t0_book"] if tier == 0 else dl["t12_book"]),
                                              "key": f"book|{s}", "levels": None}
            n = lv[t]
            exp[f"{s.lower()}@depth{n}"] = {"kind": "depth", "symbol": s, "tier": tier, "cadence": cad[f"{t}_depth"],
                                            "deadline_ms": 1000 * dl["depth"], "key": f"depth|{s}", "levels": n}
    exp["!miniTicker@arr"] = {"kind": "market", "symbol": None, "tier": None, "cadence": cad["market"],
                              "deadline_ms": 1000 * dl["market"], "key": "market|ALL", "levels": None}
    listed = {e["stream"]: e for e in run.get("expected_streams", [])}
    if set(listed) != set(exp):
        rp.fail("RUN_RECORD_EXPECTED_STREAMS_DISAGREE", sorted(set(listed) ^ set(exp))[:10])
    for n, e in exp.items():
        l = listed.get(n)
        if l and (l["cadence_ms"] != e["cadence"] or l.get("depth_levels") != e["levels"]):
            rp.fail("RUN_RECORD_STREAM_PARAMS_DISAGREE", n)
    return exp


def verify(base: str, boot: str | None = None) -> dict:
    rp = Report()
    segs = load_files(base, rp)
    recs = []
    for rel, lines, _ in segs:
        for r in lines:
            if isinstance(r, dict) and check_fields(r, rp):
                recs.append(r)
    boots = sorted({r["boot_id"] for r in recs})
    if boot is None:
        if len(boots) != 1:
            rp.fail("BOOT_AMBIGUOUS_OR_EMPTY", boots)
            return finish(rp, base)
        boot = boots[0]
    recs = [r for r in recs if r["boot_id"] == boot]
    by = collections.defaultdict(list)
    for r in recs:
        by[r["type"]].append(r)
    life = sorted(by["lifecycle"], key=lambda r: r["recv_ts_ns"])
    ev = collections.defaultdict(list)
    for r in life:
        ev[r["payload"].get("event")].append(r)
    for need in ("start", "ws_start", "stop"):
        if len(ev[need]) != 1:
            rp.fail(f"LIFECYCLE_{need.upper()}_COUNT", len(ev[need]))
    if rp.failures.get("LIFECYCLE_START_COUNT") or rp.failures.get("LIFECYCLE_WS_START_COUNT") or rp.failures.get("LIFECYCLE_STOP_COUNT"):
        return finish(rp, base)
    start, wsr, stop = ev["start"][0], ev["ws_start"][0], ev["stop"][0]
    ws_start = wsr["payload"]["ws_start_ms"]
    stop_req = stop["payload"]["stop_requested_ms"]
    if not (start["observed_at_ms"] <= ws_start + 5 and ws_start <= wsr["observed_at_ms"] + 5 and stop_req <= stop["observed_at_ms"]):
        rp.fail("WINDOW_ANCHORS_INCONSISTENT", [ws_start, stop_req])

    # ---- provenance (R01 / R06) ----
    rr_rel = start["payload"].get("run_record_file")
    rr_path = os.path.join(base, rr_rel) if rr_rel else None
    run = None
    if not rr_path or not os.path.exists(rr_path):
        rp.fail("RUN_RECORD_MISSING")
        return finish(rp, base)
    if sha256(rr_path) != start["payload"].get("run_record_sha256"):
        rp.fail("RUN_RECORD_SHA_MISMATCH")
    if os.stat(rr_path).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        rp.fail("NOT_READ_ONLY", rr_rel)
    with open(rr_path, encoding="utf-8") as fh:
        run = json.load(fh)
    if run != start["payload"].get("run_record"):
        rp.fail("RUN_RECORD_EMBED_MISMATCH")
    for k in ("build", "code", "runtime", "config", "config_hash", "semantics", "sampling_profile", "universe",
              "endpoints", "expected_streams", "schema_doc", "host_label"):
        if k not in run:
            rp.fail("RUN_RECORD_FIELD_MISSING", k)
    for k in ("git_commit", "image_tag", "image_id_runtime_claim", "build_time"):
        if run.get("build", {}).get(k) in (None, "", "unknown"):
            rp.fail("PROVENANCE_UNKNOWN", k)
    sd = run.get("schema_doc", {})
    sdp = os.path.join(base, sd.get("file", "-"))
    if not os.path.exists(sdp) or sha256(sdp) != sd.get("sha256"):
        rp.fail("SCHEMA_DOC_MISSING_OR_MISMATCH")
    if run.get("semantics", {}).get("sample_semantics") != "latest_received_at_or_before_sample_ms":
        rp.fail("SAMPLE_SEMANTICS_UNDECLARED")
    exp = derive_expected(run, rp)
    cfg = run["config"]

    # ---- duplicates (F26) ----
    seen = {}
    idem = 0
    for r in recs:
        o = r["obs_id"]
        if o in seen:
            if r["type"] in ("candle", "universe"):
                if json.dumps(seen[o]["payload"], sort_keys=True) == json.dumps(r["payload"], sort_keys=True):
                    idem += 1
                else:
                    rp.fail("CONFLICTING_DUPLICATE", o)
            else:
                rp.fail("DUPLICATE_OBS_ID", o)
        else:
            seen[o] = r
    rp.info["idempotent_duplicates"] = idem
    last_recv = stop["recv_ts_ns"]
    for r in recs:
        if r["recv_ts_ns"] > last_recv:
            rp.fail("RECORD_AFTER_STOP", r["obs_id"])

    # ---- sampled streams ----
    gaps = collections.defaultdict(list)
    gap_seq = set()
    for g in by["gap"]:
        p = g["payload"]
        parts = g["obs_id"].split("|")
        try:
            gseq = int(parts[2])
        except (IndexError, ValueError):
            gseq = None
        want = f"gap|{boot[:8]}|{gseq}|{p.get('stream_key')}|{p.get('first_missing_ms')}|{p.get('last_missing_ms')}|{p.get('cause')}"
        if g["obs_id"] != want:
            rp.fail("GAP_ID_MISMATCH", g["obs_id"])
        if gseq in gap_seq:
            rp.fail("GAP_SEQ_REUSED", gseq)
        gap_seq.add(gseq)
        cadence = p.get("cadence_ms") or 0
        if cadence and (p["last_missing_ms"] - p["first_missing_ms"]) // cadence + 1 != p.get("missing_samples"):
            rp.fail("GAP_COUNT_INCONSISTENT", g["obs_id"])
        if cadence and p.get("duration_ms") != p["last_missing_ms"] - p["first_missing_ms"] + cadence:
            rp.fail("GAP_DURATION_INCONSISTENT", g["obs_id"])
        if cadence and (p["first_missing_ms"] % cadence or p["last_missing_ms"] % cadence):
            rp.fail("GAP_NOT_ALIGNED", g["obs_id"])
        gaps[p.get("stream_key")].append(p)
    ready = {}
    for r in ev.get("stream_ready", []):
        n, rm = r["payload"].get("stream"), r["payload"].get("ready_ms")
        if n in ready:
            rp.fail("STREAM_READY_DUPLICATE", n)
        ready[n] = rm
    streams = collections.defaultdict(list)
    for t in ("book", "depth", "market"):
        for r in by[t]:
            streams[r["endpoint"]].append(r)
    unexpected = sorted(set(streams) - set(exp))
    for u in unexpected:
        rp.fail("UNEXPECTED_STREAM", u)
    cov = {}
    totals = collections.Counter()
    for name, e in sorted(exp.items()):
        rs = sorted(streams.get(name, []), key=lambda r: r["sample_ms"])
        cad = e["cadence"]
        if not rs:
            rp.fail("ABSENT_STREAM", name)                              # F52: an absent stream always fails
        prev = None
        for r in rs:
            s = r["sample_ms"]
            if not isinstance(s, int) or s % cad:
                rp.fail("SAMPLE_NOT_ALIGNED", r["obs_id"]); continue
            if r["recv_ts_ns"] > s * 1_000_000:
                rp.fail("OBSERVED_AFTER_SAMPLE", r["obs_id"])           # strict PIT (ns)
            if r["cadence_ms"] != cad:
                rp.fail("CADENCE_MISMATCH", r["obs_id"])
            if e["kind"] in ("book", "depth"):
                if r["exchange_event_time_ms"] is not None:
                    rp.fail("BOOK_DEPTH_EXCHANGE_TIME_NOT_NULL", r["obs_id"])
                if r["symbol"] != e["symbol"] or r["tier"] != e["tier"]:
                    rp.fail("SYMBOL_OR_TIER_MISMATCH", r["obs_id"])
                if e["kind"] == "book":
                    want = f"bt|{e['symbol']}|{r['exchange_seq']}|c{cad}|t{s}"
                    if r["payload"].get("u") != r["exchange_seq"]:
                        rp.fail("SEQ_NE_PAYLOAD", r["obs_id"])
                else:
                    want = f"dp{e['levels']}|{e['symbol']}|{r['exchange_seq']}|c{cad}|t{s}"
                    if r.get("depth_levels") != e["levels"]:
                        rp.fail("DEPTH_LEVELS_MISSING_OR_WRONG", r["obs_id"])
                    pl = r["payload"]
                    if pl.get("lastUpdateId") != r["exchange_seq"]:
                        rp.fail("SEQ_NE_PAYLOAD", r["obs_id"])
                    if len(pl.get("bids", [])) > e["levels"] or len(pl.get("asks", [])) > e["levels"]:
                        rp.fail("DEPTH_ARRAY_EXCEEDS_N", r["obs_id"])
                if r["obs_id"] != want:
                    rp.fail("OBS_ID_MISMATCH", r["obs_id"])
                if prev is not None:
                    if r["exchange_seq"] < prev["exchange_seq"]:
                        rp.fail("SEQ_DECREASING", r["obs_id"])
                    if r["unchanged"] != (r["exchange_seq"] == prev["exchange_seq"]):
                        rp.fail("UNCHANGED_INCONSISTENT", r["obs_id"])
                elif r["unchanged"]:
                    rp.fail("UNCHANGED_INCONSISTENT", r["obs_id"])
            else:
                if r["obs_id"] != f"mkt|t{s}":
                    rp.fail("OBS_ID_MISMATCH", r["obs_id"])
                comp = r.get("component_recv_ms")
                if not isinstance(comp, dict) or not isinstance(r.get("startup_complete"), bool):
                    rp.fail("MARKET_FIELDS_MISSING", r["obs_id"])
                else:
                    syms = sorted(x.get("s") for x in r["payload"])
                    if syms != sorted(comp) or (comp and max(comp.values()) != r["observed_at_ms"]) \
                            or any(v > s for v in comp.values()):
                        rp.fail("MARKET_COMPONENTS_INCONSISTENT", r["obs_id"])
            if prev is not None:
                if s <= prev["sample_ms"]:
                    rp.fail("SAMPLE_NOT_INCREASING", r["obs_id"])
                if r["recv_ts_ns"] < prev["recv_ts_ns"]:
                    rp.fail("RECV_DECREASING", r["obs_id"])
            if not (ws_start < s < stop_req):
                rp.fail("RECORD_OUTSIDE_WINDOW", r["obs_id"])
            prev = r
        # ---- full-window boundary reconciliation (F53) ----
        persisted = {r["sample_ms"] for r in rs}
        first_persisted = min(persisted) if persisted else None
        deadline = ws_start + e["deadline_ms"]
        excuse_limit = deadline
        if rs:
            excuse_limit = min(excuse_limit, rs[0]["observed_at_ms"])
            rd = ready.get(name)
            if rd is None:
                rp.fail("STREAM_READY_LIFECYCLE_MISSING", name)
            else:
                excuse_limit = min(excuse_limit, rd)
        glist = sorted(gaps.get(e["key"], []), key=lambda g: g["first_missing_ms"])
        for a, b in zip(glist, glist[1:]):
            if b["first_missing_ms"] <= a["last_missing_ms"]:
                rp.fail("OVERLAPPING_GAPS", e["key"])
        covered = set()
        for g in glist:
            for b in range(g["first_missing_ms"], g["last_missing_ms"] + 1, cad):
                if b in persisted:
                    rp.fail("FALSE_GAP", f"{e['key']}@{b}")
                if not (ws_start < b < stop_req):
                    rp.fail("GAP_OUTSIDE_WINDOW", f"{e['key']}@{b}")
                covered.add(b)
        b0 = (ws_start // cad + 1) * cad
        c = collections.Counter()
        first_miss = last_miss = None
        for b in range(b0, stop_req, cad):
            if b >= stop_req:
                break
            if b in persisted:
                c["persisted"] += 1
            elif b in covered:
                c["gap_covered"] += 1
            elif b < excuse_limit and (first_persisted is None or b < first_persisted):
                c["startup_excused"] += 1
            else:
                c["unexplained"] += 1
                first_miss = b if first_miss is None else first_miss; last_miss = b
                rp.fail("UNEXPLAINED_MISS", f"{name}@{b}")
        c["expected"] = sum(1 for _ in range(b0, stop_req, cad))
        c["window_first"], c["window_last"] = b0, ((stop_req - 1) // cad) * cad
        c["first_persisted"] = first_persisted
        c["gaps"] = len(glist)
        c["coverage_after_ready"] = round(c["persisted"] / max(1, c["expected"] - c["startup_excused"]), 6)
        c["unchanged"] = sum(1 for r in rs if r["unchanged"])
        if first_miss is not None:
            c["first_unexplained"], c["last_unexplained"] = first_miss, last_miss
        cov[name] = dict(c)
        for k in ("expected", "persisted", "gap_covered", "startup_excused", "unexplained"):
            totals[k] += c[k]
    known_keys = {e["key"] for e in exp.values()}
    for k in gaps:
        if k not in known_keys and not str(k).startswith(("candle|", "backpressure|", "crash|")):
            rp.fail("GAP_UNKNOWN_STREAM_KEY", k)

    # ---- candles ----
    tfs = cfg["candle_timeframes"]
    syms = sorted(set(run["universe"]["snapshot"]["tier0"]) | set(run["universe"]["snapshot"]["tier1"]) |
                  set(run["universe"]["snapshot"]["tier2"]))
    got = {}
    for r in by["candle"]:
        k = r["payload"]
        tf = r["endpoint"].split("interval=")[-1]
        if tf not in TF:
            rp.fail("CANDLE_BAD_TF", r["obs_id"]); continue
        o, cl = int(k[0]), int(k[6])
        if o % TF[tf] or cl != o + TF[tf] - 1:
            rp.fail("CANDLE_MISALIGNED", r["obs_id"])
        if not (r["available_at_ms"] > cl and r["available_at_ms"] == max(cl + 1, r["observed_at_ms"])):
            rp.fail("CANDLE_AVAILABILITY", r["obs_id"])
        if r["obs_id"] != f"{r['symbol']}|{tf}|{o}":
            rp.fail("OBS_ID_MISMATCH", r["obs_id"])
        if r["exchange_event_time_ms"] != cl:
            rp.fail("CANDLE_EXCHANGE_TIME", r["obs_id"])
        got[(r["symbol"], tf, o)] = r
    cgaps = {(g["stream_key"], g["first_missing_ms"]) for k, gl in gaps.items() if str(k).startswith("candle|") for g in gl}
    exp_c = set()
    for tf in tfs:
        L = TF[tf]
        for s in syms:
            if ws_start + CANDLE_MARGIN_MS < stop_req:
                exp_c.add((s, tf, (ws_start // L) * L - L))                   # catch-up candle
            b = (ws_start // L + 1) * L
            while b + CANDLE_MARGIN_MS < stop_req:
                exp_c.add((s, tf, b - L)); b += L
    missing_c = 0
    for s, tf, o in sorted(exp_c):
        if (s, tf, o) not in got and (f"candle|{tf}|{s}", o) not in cgaps:
            missing_c += 1; rp.fail("UNEXPLAINED_MISSING_CANDLE", f"{s}|{tf}|{o}")
    rp.info["candles"] = {"expected_min": len(exp_c), "got": len(got), "unexplained_missing": missing_c,
                          "by_tf": dict(collections.Counter(tf for _, tf, _ in got))}

    # ---- clock (F5 / R17) ----
    clk = sorted(by["clock"], key=lambda r: r["recv_ts_ns"])
    worst = None
    for r in clk:
        p = r["payload"]
        if p.get("method") != "min_rtt_of_3_midpoint_v1" or not p.get("probes"):
            rp.fail("CLOCK_METHOD_MISSING", r["obs_id"]); continue
        best = min(p["probes"], key=lambda q: (q["t1_ms"] - q["t0_ms"], q["t0_ms"]))
        rtt = best["t1_ms"] - best["t0_ms"]
        skew = best["serverTime"] - (best["t0_ms"] + best["t1_ms"]) / 2.0
        if abs(skew - p["skew_ms"]) > 1e-6 or abs(rtt / 2.0 - p["uncertainty_ms"]) > 1e-6 or best["serverTime"] != p["serverTime"]:
            rp.fail("CLOCK_RECOMPUTE_MISMATCH", r["obs_id"])
        excess = max(0.0, abs(skew) - rtt / 2.0)
        worst = excess if worst is None else max(worst, excess)
        if r["obs_id"] != f"clk|{p['serverTime']}":
            rp.fail("OBS_ID_MISMATCH", r["obs_id"])
    need_clk = max(1, (stop_req - ws_start) // cfg["cadence_ms"]["clock"])
    if len(clk) < need_clk:
        rp.fail("CLOCK_RECORDS_TOO_FEW", f"{len(clk)}<{need_clk}")
    rp.info["clock"] = {"records": len(clk), "max_excess_over_uncertainty_ms": worst,
                        "skew_ms": [round(r["payload"]["skew_ms"], 1) for r in clk if "skew_ms" in r["payload"]],
                        "uncertainty_ms": [r["payload"].get("uncertainty_ms") for r in clk]}

    # ---- health history (R02) ----
    hl = sorted(by["health"], key=lambda r: r["recv_ts_ns"])
    interval = 1000 * cfg["health_record_interval_s"]
    tol = 15_000
    prev_t = start["observed_at_ms"]
    states = collections.Counter()
    for r in hl:
        t = r["observed_at_ms"]
        if t - prev_t > interval + tol:
            rp.fail("HEALTH_HISTORY_HOLE", f"{prev_t}->{t}")
        st = r["payload"].get("state")
        states[st] += 1
        prev_t = t
        if r["obs_id"].split("|")[:2] != ["hlth", boot]:
            rp.fail("OBS_ID_MISMATCH", r["obs_id"])
    if stop["observed_at_ms"] - prev_t > interval + tol:
        rp.fail("HEALTH_HISTORY_HOLE", f"{prev_t}->stop")
    non_ok = [{"t": r["observed_at_ms"], "state": r["payload"]["state"], "reasons": r["payload"].get("reasons")}
              for r in hl if r["payload"].get("state") not in ("HEALTHY", "STARTING", "STOPPING")]
    starting_late = [r["observed_at_ms"] for r in hl if r["payload"].get("state") == "STARTING"
                     and r["observed_at_ms"] > ws_start + 130_000]
    rp.info["health"] = {"records": len(hl), "states": dict(states), "non_healthy": non_ok[:20],
                         "starting_after_130s": len(starting_late)}

    # ---- lifecycle facts ----
    for e_ in ("fatal", "task_failed", "handler_exception", "subscribe_failed", "subscribe_timeout", "never_ready",
               "disk_hard_stop", "binance_ban_418", "ws_task_dead"):
        if ev.get(e_):
            rp.info.setdefault("lifecycle_alerts", {})[e_] = len(ev[e_])
    rp.info["lifecycle_counts"] = {k: len(v) for k, v in sorted(ev.items())}
    rp.info["window"] = {"ws_start_ms": ws_start, "stop_requested_ms": stop_req, "runtime_s": (stop_req - ws_start) / 1000,
                         "max_runtime_s": cfg.get("max_runtime_s"), "stop_reason": stop["payload"].get("reason")}
    rp.info["coverage"] = cov
    rp.info["totals"] = dict(totals)
    rp.info["by_type"] = {k: len(v) for k, v in sorted(by.items())}
    rp.info["gaps"] = [{k: g[k] for k in ("stream_key", "first_missing_ms", "last_missing_ms", "missing_samples", "cause",
                                          "causes", "open_at_stop") if k in g} for gl in gaps.values() for g in gl]
    return finish(rp, base, segs)


def finish(rp: Report, base: str, segs=None) -> dict:
    q = os.path.join(base, "quarantine")
    qfiles = sorted(os.listdir(q)) if os.path.isdir(q) else []
    if qfiles:
        rp.fail("QUARANTINE_NOT_EMPTY", qfiles[:5])
    ctl = os.path.join(base, "control")
    cfiles = sorted(os.listdir(ctl)) if os.path.isdir(ctl) else []
    for f in cfiles:
        if f.startswith("fatal-"):
            rp.fail("FATAL_MARKER_PRESENT", f)
    rp.info["control_markers"] = cfiles
    if segs is not None:
        rp.info["segments"] = len(segs)
        rp.info["records"] = sum(len(l) for _, l, _ in segs)
        rp.info["bytes_by_type"] = dict(collections.Counter())
        bt = collections.Counter()
        it = collections.Counter()
        for rel, _, m in segs:
            t = os.path.basename(rel).split("-", 1)[0]
            bt[t] += m.get("bytes", 0); it[t] += m.get("idx_bytes", 0)
        rp.info["bytes_by_type"], rp.info["idx_bytes_by_type"] = dict(bt), dict(it)
    return {"PASS": not rp.failures, "failures": dict(rp.failures), "failure_examples": dict(rp.examples), **rp.info}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir"); ap.add_argument("--boot"); ap.add_argument("--json")
    a = ap.parse_args(argv)
    rep = verify(a.data_dir, a.boot)
    out = json.dumps(rep, indent=1, sort_keys=True, default=str)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    print(json.dumps({"PASS": rep["PASS"], "failures": rep["failures"], "totals": rep.get("totals"),
                      "records": rep.get("records"), "segments": rep.get("segments")}, sort_keys=True))
    return 0 if rep["PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
