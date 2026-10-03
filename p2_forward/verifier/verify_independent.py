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

Two verdicts:
  * integrity / consistency (always): files, records, identities, PIT, full-window boundary reconciliation;
  * ACCEPTANCE (--acceptance g2r or --spec file.json): a PREDECLARED, pinned specification that the run's own
    configuration cannot loosen (review B1): exact streams / cadences / depth N / deadlines / stale limits,
    bounded runtime with stop reason max_runtime, gap budget and forbidden gap causes, health-history budget,
    forbidden lifecycle alerts, zero error counters, clock excess bound, final STOPPED marker, expected image /
    commit identities.

What this verifier CANNOT check independently (documented): data liveness of a connection between persisted
samples (no raw message log is kept); whether a held value was the exchange's true latest state (only that it
was the latest the collector received). Freshness ages ARE checked independently against the pinned limits.

Usage: python3 verify_independent.py <data_dir> [--boot BOOT_ID] [--acceptance g2r | --spec spec.json]
       [--expect-image-id ID] [--expect-commit SHA] [--json out.json]   (stdlib only, read-only)
"""
from __future__ import annotations

import argparse
import bisect
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

# Predeclared G2-Repeat acceptance specification (pinned here, NOT read from the run).
G2R_SPEC = {
    "name": "g2r-tier0-2h-v1",
    "profile": "tier0_only", "tier0": ["BTCUSDT", "ETHUSDT"], "tier1": [], "tier2": [],
    "cadence_ms": {"t0_book": 1000, "t0_depth": 1000, "market": 60000, "clock": 600000},
    "depth_levels_t0": 20, "candle_timeframes": ["15m", "1h", "4h", "1d"],
    "first_obs_deadline_s": {"t0_book": 30, "depth": 30, "market": 30},
    "stale_ms": {"depth": 2000, "book_t0": 120000, "market": 10000}, "conn_data_live_ms": 10000,
    "health_record_interval_s": 60, "max_runtime_s": 7200, "runtime_tolerance_s": 5,
    "gap_budget": {"max_fraction_per_stream": 0.005, "min_allowance_boundaries": 2, "max_gap_ms": 120000,
                   "allowed_causes": ["ws_disconnect_reconnect", "conn_data_stale", "stale_stream",
                                      "awaiting_post_reconnect_data"]},
    "candle_gap_allowed_causes": ["candle_fetch_interrupted_at_stop", "candle_not_fetched_at_stop"],
    "health": {"max_non_healthy_fraction": 0.10, "startup_s": 130,
               "allowed_degraded_reason_prefixes": ["stale:", "conn_not_data_live:", "gap_open:", "gap_short:", "not_acked:"]},
    "forbidden_lifecycle": ["fatal", "task_failed", "handler_exception", "subscribe_failed", "subscribe_timeout",
                            "never_ready", "ws_task_dead", "binance_ban_418", "disk_hard_stop", "seq_reset",
                            "wall_clock_step", "candle_exception"],
    "zero_counters": ["malformed", "unknown_stream", "unknown_event", "handler_errors", "seq_regression", "seq_reset",
                      "write_errors", "segments_quarantined", "duplicates_dropped", "recv_clock_regression",
                      "wall_clock_steps", "task_failures", "subscribe_failed", "subscribe_timeout", "never_ready"],
    "zero_counter_maps": ["dropped", "emit_failed", "writer_rejected"],
    "clock_max_excess_ms": 500, "clock_max_spacing_s": 1200,
}


G3_SPEC = {
    "name": "g3-recommended-6h-v4",
    "depth_stale_ms_by_tier": {"t0": 2000, "t1": 180000, "t2": 15000}, "book_t12_dead_ms": 600000,
    "freshness_justification": (
        "Tier0 depth 2 s: G2R-validated (push inter-arrival 971-1039 ms, one missed push tolerated). Tier1/2 depth "
        "3 x cadence (P2-E0 rule 'depth: 3x cadence'): T2 5 s -> 15 s, T1 60 s -> 180 s; diagnostic G3 showed "
        "~0.9 pushes/s per stream with ~1.4 % of boundaries > 2 s old, i.e. 2 s misclassified a quiet book as "
        "missing; 3 x cadence still detects a dead stream within 15 s / 180 s. Tier1/2 bookTicker is event-driven "
        "(diagnostic max age 40.7 s, p99 19.8 s); a hard dead-stream bound of 600 s (~15 x observed max) replaces "
        "the former warning-only path so a dead book stream cannot hide behind a live shared connection."),
    "profile": "recommended", "tier0": ["BTCUSDT", "ETHUSDT"], "tier1": None, "tier2": None,  # None: from the
    # independently reconstructed universe (R04); limits below
    "universe": {"min_quote_volume": 10_000_000, "tier1_max": 150, "tier2": [20, 10, 30], "expect_no_prior": True,
                 "max_attempt_failures": 2},
    "cadence_ms": {"t0_book": 1000, "t0_depth": 1000, "t2_book": 2000, "t2_depth": 5000, "t1_book": 10000,
                   "t1_depth": 60000, "market": 60000, "clock": 600000},
    "depth_levels": {"t0": 20, "t1": 10, "t2": 10}, "depth_levels_t0": 20,
    "candle_timeframes": ["15m", "1h", "4h", "1d"],
    "first_obs_deadline_s": {"t0_book": 30, "depth": 30, "market": 30, "t12_book": 120},
    "stale_ms": {"depth": 2000, "book_t0": 120000, "market": 10000}, "conn_data_live_ms": 10000,
    "health_record_interval_s": 60, "max_runtime_s": 21600, "runtime_tolerance_s": 5,
    "gap_budget": {"max_fraction_per_stream": 0.005, "min_allowance_boundaries": 2, "max_gap_ms": 120000,
                   "allowed_causes": ["ws_disconnect_reconnect", "conn_data_stale", "stale_stream",
                                      "awaiting_post_reconnect_data"]},
    "candle_gap_allowed_causes": ["candle_fetch_interrupted_at_stop", "candle_not_fetched_at_stop",
                                  "candle_not_listed_yet"],
    "health": {"max_non_healthy_time_fraction": 0.05, "startup_s": 150,
               "allowed_degraded_reason_prefixes": ["stale:", "conn_not_data_live:", "gap_open:", "gap_short:", "not_acked:",
                                                    "awaiting_post_reconnect:"]},
    "reconnect": {"at_s": 10800, "conn": "conn0-book", "trigger_tolerance_s": 5, "detect_within_s": 5,
                  "reconnect_within_s": 60, "recover_within_s": 180},
    "forbidden_lifecycle": ["fatal", "task_failed", "handler_exception", "subscribe_failed", "subscribe_timeout",
                            "never_ready", "ws_task_dead", "binance_ban_418", "disk_hard_stop", "seq_reset",
                            "wall_clock_step", "candle_exception", "startup_failed", "universe_refresh"],
    "zero_counters": ["malformed", "unknown_stream", "unknown_event", "handler_errors", "seq_regression", "seq_reset",
                      "write_errors", "segments_quarantined", "duplicates_dropped", "recv_clock_regression",
                      "wall_clock_steps", "task_failures", "subscribe_failed", "subscribe_timeout", "never_ready"],
    "zero_counter_maps": ["dropped", "emit_failed", "writer_rejected"],
    "clock_max_excess_ms": 500, "clock_max_spacing_s": 1200,
    "rest": {"ip_weight_max": 2400, "forbidden_events": ["http_429", "http_418"]},
    "resources": {"mem_max_mib": 345, "pids_max": 64, "require_monitor": True},
    "storage": {"design_band_mb_day": [122, 446], "report_only": True},
}


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


def compact(r):
    """Memory: book/depth payloads are reduced to the fields this verifier checks (sizes kept)."""
    if isinstance(r, dict) and r.get("type") in ("book", "depth") and isinstance(r.get("payload"), dict):
        p = r["payload"]
        if r["type"] == "book":
            r["payload"] = {"s": p.get("s"), "u": p.get("u")}
        else:
            r["payload"] = {"lastUpdateId": p.get("lastUpdateId"), "_n_bids": len(p.get("bids") or []),
                            "_n_asks": len(p.get("asks") or [])}
    return r


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
                    lines.append(compact(json.loads(line)))
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


EXCLUSION_REASONS = {None, "tier0_not_trading", "not_in_exchangeinfo_spot", "stable_or_fiat_base", "non_ascii_or_non_alnum",
                     "no_ticker", "invalid_ticker", "rank_cut", "below_min_quote_volume"}


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def check_universe(rp: Report, by: dict, ev: dict, run: dict, base: str, ws_start: int) -> None:
    """R04: reconstruct the ACTIVE universe independently from the persisted per-candidate raw inputs (documented
    tiers-v2 rules, re-implemented here) and require it to equal the persisted tiers and the run record."""
    if (run.get("universe") or {}).get("rule_version") == "tiers-v1":
        rp.info["universe"] = {"legacy": "tiers-v1 (pre-R04): per-candidate reconstruction not available; tiers from "
                                         "the run record only"}
        return
    act = ev.get("universe_active", [])
    if len(act) != 1:
        rp.fail("UNIVERSE_ACTIVE_COUNT", len(act)); return
    a = act[0]["payload"]
    if a.get("effective_from_ms") != ws_start:
        rp.fail("UNIVERSE_EFFECTIVE_FROM_NE_WS_START", [a.get("effective_from_ms"), ws_start])
    recs = [r for r in by["universe"] if r["obs_id"] == a.get("universe_id")]
    if len(recs) != 1:
        rp.fail("UNIVERSE_RECORD_MISSING", a.get("universe_id")); return
    u = recs[0]["payload"]
    fp = os.path.join(base, a.get("file", "-"))
    if not os.path.exists(fp) or sha256(fp) != a.get("sha256") or u.get("sha256") != a.get("sha256"):
        rp.fail("UNIVERSE_FILE_MISSING_OR_SHA_MISMATCH", a.get("file"))
    elif os.stat(fp).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        rp.fail("NOT_READ_ONLY", a.get("file"))
    else:
        with open(fp, encoding="utf-8") as fh:
            doc = json.load(fh)
        if {k: v for k, v in u.items() if k not in ("file", "sha256")} != doc:
            rp.fail("UNIVERSE_RECORD_NE_FILE")
    snap = run["universe"]["snapshot"] or {}
    for k in ("tier0", "tier1", "tier2"):
        if snap.get(k) != u.get(k):
            rp.fail("UNIVERSE_RUN_RECORD_MISMATCH", k)
    cands = u.get("candidates") or []
    if u.get("profile") == "tier0_only":
        if sorted(c["symbol"] for c in cands) != sorted(u["tier0"]):
            rp.fail("UNIVERSE_TIER0_CANDIDATES")
        rp.info["universe"] = {"profile": "tier0_only", "tier0": u["tier0"]}
        return
    cfg = run["config"]
    src = u.get("source") or {}
    raw = {}
    for k in ("exchangeinfo", "ticker"):                         # M2: rebuild candidates from the raw REST bodies
        sk = src.get(k) or {}
        rf = os.path.join(base, sk.get("raw_file") or "-")
        if not os.path.exists(rf):
            rp.fail("UNIVERSE_RAW_INPUTS_MISSING", k); continue
        if sha256(rf) != sk.get("raw_file_sha256"):
            rp.fail("UNIVERSE_RAW_FILE_SHA_MISMATCH", k); continue
        with gzip.open(rf, "rb") as fh:
            body = fh.read()
        if hashlib.sha256(body).hexdigest() != sk.get("body_sha256"):
            rp.fail("UNIVERSE_RAW_BODY_SHA_MISMATCH", k); continue
        raw[k] = json.loads(body)
        if sk.get("recv_ns") is None or sk["recv_ns"] > ws_start * 1_000_000:
            rp.fail("UNIVERSE_SOURCE_AFTER_EFFECTIVE_FROM", k)        # m7: PIT
    if u.get("evaluated_ms") is None or u["evaluated_ms"] > ws_start:
        rp.fail("UNIVERSE_EVALUATED_AFTER_EFFECTIVE_FROM")
    if len(raw) == 2:
        ei = {x["symbol"]: x for x in raw["exchangeinfo"].get("symbols", []) if isinstance(x, dict) and x.get("quoteAsset") == "USDT"}
        tk = {x["symbol"]: x for x in raw["ticker"] if isinstance(x, dict) and isinstance(x.get("symbol"), str)}
        nm = sorted(set(ei) | {x for x in tk if x.endswith("USDT")} | set(cfg["tier0"]))
        rebuilt = [[x, (ei.get(x) or {}).get("status"), (ei.get(x) or {}).get("baseAsset"), x in ei, x in tk,
                    (tk.get(x) or {}).get("quoteVolume"), (tk.get(x) or {}).get("openPrice"), (tk.get(x) or {}).get("lastPrice")]
                   for x in nm]
        stored = [[c.get("symbol"), c.get("status"), c.get("base"), c.get("in_exchangeinfo"), c.get("in_ticker"),
                   c.get("quote_volume_raw"), c.get("open_raw"), c.get("last_raw")] for c in cands]
        if rebuilt != stored:
            rp.fail("UNIVERSE_CANDIDATES_NE_RAW_INPUTS", {"rebuilt": len(rebuilt), "stored": len(stored),
                                                          "diff": sorted({r[0] for r in rebuilt} ^ {r[0] for r in stored})[:10]})
        ih = hashlib.sha256(json.dumps([[r[0], r[1], r[2], r[5], r[6], r[7]] for r in rebuilt]).encode()).hexdigest()
        if ih != u.get("inputs_sha256"):
            rp.fail("UNIVERSE_INPUTS_SHA_MISMATCH")
    if u.get("candidate_count") != len(cands):
        rp.fail("UNIVERSE_CANDIDATE_COUNT_MISMATCH")
    th = u.get("thresholds", {})
    if (th.get("min_quote_volume"), th.get("tier1_max"), th.get("tier2")) != \
            (cfg["tier1_min_quote_volume"], cfg["tier1_max"], [cfg["tier2_top_volume"], cfg["tier2_top_movers"], cfg["tier2_max"]]):
        rp.fail("UNIVERSE_THRESHOLDS_NE_CONFIG")
    stable, t0 = set(cfg["stable_bases"]), set(cfg["tier0"])
    names = [c["symbol"] for c in cands]
    if names != sorted(set(names)):
        rp.fail("UNIVERSE_CANDIDATES_NOT_UNIQUE_SORTED")
    elig = {}
    for c in cands:
        sym = c["symbol"]
        if c.get("excluded_reason") not in EXCLUSION_REASONS and not str(c.get("excluded_reason")).startswith("status_"):
            rp.fail("UNIVERSE_UNKNOWN_EXCLUSION_REASON", sym)
        if sym in t0:
            continue
        qv, o, l = _f(c.get("quote_volume_raw")), _f(c.get("open_raw")), _f(c.get("last_raw"))
        if not c.get("in_exchangeinfo"):
            want = "not_in_exchangeinfo_spot"
        elif c.get("status") != "TRADING":
            want = f"status_{c.get('status')}"
        elif c.get("base") in stable:
            want = "stable_or_fiat_base"
        elif not (sym.isascii() and sym.isalnum()):
            want = "non_ascii_or_non_alnum"
        elif not c.get("in_ticker"):
            want = "no_ticker"
        elif qv is None or o is None or l is None or qv < 0:
            want = "invalid_ticker"
        else:
            want = "ELIGIBLE"
            elig[sym] = (qv, (l / o - 1.0) if o > 0 else 0.0)
        if want != "ELIGIBLE" and c.get("excluded_reason") != want:
            rp.fail("UNIVERSE_EXCLUSION_RECOMPUTE_MISMATCH", f"{sym}:{c.get('excluded_reason')}!={want}")
        if bool(c.get("eligible")) != (want == "ELIGIBLE"):
            rp.fail("UNIVERSE_ELIGIBILITY_MISMATCH", sym)
    order = sorted(elig, key=lambda x: (-elig[x][0], x))
    rank = {x: i + 1 for i, x in enumerate(order)}
    above = [x for x in order if elig[x][0] >= cfg["tier1_min_quote_volume"]][: cfg["tier1_max"]]
    if u.get("eligible_count") != len(elig):
        rp.fail("UNIVERSE_ELIGIBLE_COUNT_MISMATCH", [u.get("eligible_count"), len(elig)])
    prior = set()
    if u.get("prior_universe_id"):                                 # load the prior artifact itself (M2)
        rp.info["universe_prior"] = u.get("prior_universe_id")
        pu = None
        ud = os.path.join(base, "universe")
        for f in sorted(os.listdir(ud)) if os.path.isdir(ud) else []:
            if f.endswith(".json"):
                with open(os.path.join(ud, f), encoding="utf-8") as fh:
                    d_ = json.load(fh)
                if isinstance(d_, dict) and d_.get("universe_id") == u["prior_universe_id"]:
                    pu = d_
        if pu is None:
            rp.fail("UNIVERSE_PRIOR_ARTIFACT_MISSING", u["prior_universe_id"])
        else:
            prior = (set(pu.get("tier1", [])) | set(pu.get("tier2", []))) & set(elig)
            prior -= set(t0)
    prior -= set(above)
    if sorted(prior) != sorted(u.get("hysteresis_members") or []):
        rp.fail("UNIVERSE_HYSTERESIS_RECOMPUTE_MISMATCH")
    t1all = set(above) | prior
    vol = sorted(t1all, key=lambda x: (-elig[x][0], x))[: cfg["tier2_top_volume"]]
    mov = sorted(t1all - set(vol), key=lambda x: (-abs(elig[x][1]), x))[: cfg["tier2_top_movers"]]
    t2 = sorted((vol + mov)[: cfg["tier2_max"]])
    t1 = sorted(t1all - set(t2))
    if t1 != u.get("tier1") or t2 != u.get("tier2") or sorted(t0) != u.get("tier0"):
        rp.fail("UNIVERSE_TIERS_RECOMPUTE_MISMATCH", {"tier1_diff": sorted(set(t1) ^ set(u.get("tier1") or []))[:10],
                                                      "tier2_diff": sorted(set(t2) ^ set(u.get("tier2") or []))[:10]})
    for c in cands:
        sym = c["symbol"]
        if sym in elig and c.get("volume_rank") != rank[sym]:
            rp.fail("UNIVERSE_RANK_MISMATCH", sym)
        want_tier = 0 if sym in t0 else 2 if sym in t2 else 1 if sym in t1 else None
        if c.get("tier") != want_tier:
            rp.fail("UNIVERSE_CANDIDATE_TIER_MISMATCH", sym)
        if sym in elig:                                             # eligible: selected, rank cut or below volume
            want = None if sym in t1all else ("rank_cut" if elig[sym][0] >= cfg["tier1_min_quote_volume"]
                                              else "below_min_quote_volume")
            if c.get("excluded_reason") != want:
                rp.fail("UNIVERSE_EXCLUSION_RECOMPUTE_MISMATCH", f"{sym}:{c.get('excluded_reason')}!={want}")
            if (sym in prior) != bool(c.get("hysteresis_reason")):
                rp.fail("UNIVERSE_HYSTERESIS_REASON_MISMATCH", sym)
    rp.info["universe"] = {"universe_id": a.get("universe_id"), "candidates": len(cands), "eligible": len(elig),
                           "tier0": sorted(t0), "tier1": len(t1), "tier2": len(t2), "hysteresis": sorted(prior),
                           "exclusions": {str(k): v for k, v in collections.Counter(c.get("excluded_reason") or "selected"
                                                                                    for c in cands).items()},
                           "source": {k: {"recv_ns": v.get("recv_ns"), "body_sha256": v.get("body_sha256")}
                                      for k, v in (u.get("source") or {}).items()},
                           "validation": u.get("validation")}


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
                                              "key": f"book|{s}", "levels": None,
                                              "stale_ms": cfg["book_t0_stale_ms"] if tier == 0 else cfg.get("book_t12_dead_ms")}
            n = lv[t]
            exp[f"{s.lower()}@depth{n}"] = {"kind": "depth", "symbol": s, "tier": tier, "cadence": cad[f"{t}_depth"],
                                            "deadline_ms": 1000 * dl["depth"], "key": f"depth|{s}", "levels": n,
                                            "stale_ms": (cfg.get("depth_stale_ms_by_tier") or {}).get(t, cfg["depth_stale_ms"])}
    exp["!miniTicker@arr"] = {"kind": "market", "symbol": None, "tier": None, "cadence": cad["market"],
                              "deadline_ms": 1000 * dl["market"], "key": "market|ALL", "levels": None,
                              "stale_ms": cfg["market_stale_ms"]}
    sp = getattr(rp, "spec", None)                              # review F1: pinned values win over the run's config
    if sp is not None:
        if "depth_stale_ms_by_tier" in sp:
            for n_, e_ in exp.items():
                e_["stale_ms"] = (sp["depth_stale_ms_by_tier"][f"t{e_['tier']}"] if e_["kind"] == "depth" else
                                  sp["stale_ms"]["book_t0"] if e_["kind"] == "book" and e_["tier"] == 0 else
                                  sp["book_t12_dead_ms"] if e_["kind"] == "book" else sp["stale_ms"]["market"])
        elif "depth_stale_ms_by_tier" in cfg:
            rp.fail("ACC_SPEC_MISSING_FRESHNESS")                   # fail closed: spec predates per-tier freshness
    listed = {e["stream"]: e for e in run.get("expected_streams", [])}
    if set(listed) != set(exp):
        rp.fail("RUN_RECORD_EXPECTED_STREAMS_DISAGREE", sorted(set(listed) ^ set(exp))[:10])
    for n, e in exp.items():
        l = listed.get(n)
        if l and (l["cadence_ms"] != e["cadence"] or l.get("depth_levels") != e["levels"]):
            rp.fail("RUN_RECORD_STREAM_PARAMS_DISAGREE", n)
    return exp


def read_monitor(tsv: str | None, log: str | None) -> dict | None:
    """Gate-monitor evidence (docker stats every 60 s + container exit line). Plain data, parsed here."""
    if not tsv or not log:
        return None
    mem, pids, cpu = [], [], []
    with open(tsv, encoding="utf-8") as fh:
        rows = [l.rstrip("\n").split("\t") for l in fh][1:]
    for r in rows:
        if len(r) > 3 and "MiB" in r[2]:
            mem.append(float(r[2].split("MiB")[0])); pids.append(int(r[3] or 0)); cpu.append(float(r[1].rstrip("%") or 0))
    out = {"samples": len(rows), "mem_max_mib": max(mem, default=None), "pids_max": max(pids, default=None),
           "cpu_avg_pct": round(sum(cpu) / len(cpu), 2) if cpu else None, "cpu_max_pct": max(cpu, default=None)}
    with open(log, encoding="utf-8") as fh:
        last = [l for l in fh if "container exited:" in l][-1:]
    if last:
        kv = dict(x.split("=", 1) for x in last[0].split("container exited:")[1].split() if "=" in x)
        out.update(exit=int(kv.get("exit", -1)), oom={"true": True, "false": False}.get(kv.get("oom")),
                   restarts=int(kv.get("restarts", -1)), status=kv.get("status"))
    return out


def verify(base: str, boot: str | None = None, spec: dict | None = None, expect_image: str | None = None,
           expect_commit: str | None = None, monitor: dict | None = None) -> dict:
    rp = Report()
    rp.spec, rp.expect_image, rp.expect_commit, rp.monitor = spec, expect_image, expect_commit, monitor
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
    tier0_syms = run["universe"]["snapshot"]["tier0"]
    check_universe(rp, by, ev, run, base, ws_start)
    conn_of = {}
    for cname, streams in (wsr["payload"].get("conns") or {}).items():
        for n in streams:
            conn_of[n] = cname
    for n, e in exp.items():
        if conn_of.get(n) is None:
            rp.fail("STREAM_WITHOUT_CONNECTION", n)
    conn_ev = collections.defaultdict(list)                     # conn -> [(t_ms, up)] from lifecycle records
    for name_, up in (("ws_connected", True), ("ws_disconnected", False), ("ws_connect_failed", False)):
        for r in ev.get(name_, []):
            conn_ev[r["payload"].get("conn")].append((r["observed_at_ms"], up))
    for k in conn_ev:
        conn_ev[k].sort()
    rp.info["connection_events"] = {k: len(v) for k, v in conn_ev.items()}

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
    ctl = []
    for r in recs:                                                    # review m1: control-record sequence 1..N
        parts = r["obs_id"].split("|")
        try:
            if r["type"] == "gap":
                ctl.append(int(parts[2]))
            elif r["type"] in ("lifecycle", "health"):
                ctl.append(int(parts[2]))
        except (IndexError, ValueError):
            rp.fail("CONTROL_ID_UNPARSEABLE", r["obs_id"])
    if sorted(ctl) != list(range(1, len(ctl) + 1)):
        miss = sorted(set(range(1, max(ctl, default=0) + 1)) - set(ctl))
        rp.fail("CONTROL_SEQ_NOT_CONTIGUOUS", miss[:10] or "duplicates")
    rp.info["control_records"] = len(ctl)
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
        n = r["payload"].get("stream")
        rn = r["payload"].get("ready_ns")
        rm = r["payload"].get("ready_ms")
        if n in ready:
            rp.fail("STREAM_READY_DUPLICATE", n)
        ready[n] = rn if isinstance(rn, int) else (rm + 1) * 1_000_000 - 1 if isinstance(rm, int) else None
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
            st_up = None                                              # connection state at s (lifecycle data)
            for t_, up_ in conn_ev.get(conn_of.get(name), []):
                if t_ <= s:
                    st_up = (t_, up_)
                else:
                    break
            if st_up is None or not st_up[1]:
                rp.fail("SAMPLE_WHILE_CONNECTION_DOWN", r["obs_id"])
            elif r["observed_at_ms"] < st_up[0]:
                rp.fail("PRE_RECONNECT_VALUE_PERSISTED", r["obs_id"])   # stale value from before the (re)connect
            lim = e["stale_ms"]
            if lim is not None and e["kind"] != "market" and s - r["observed_at_ms"] > lim:
                rp.fail("STALE_VALUE_PERSISTED", r["obs_id"])              # independent freshness (review M6)
            if e["kind"] in ("book", "depth"):
                if e["kind"] == "book" and r["payload"].get("s") != e["symbol"]:
                    rp.fail("PAYLOAD_SYMBOL_MISMATCH", r["obs_id"])
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
                    if pl.get("_n_bids", 0) > e["levels"] or pl.get("_n_asks", 0) > e["levels"]:
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
                    if comp and lim is not None and s - max(comp.values()) > lim:
                        rp.fail("STALE_VALUE_PERSISTED", r["obs_id"])
                    if r["startup_complete"] and not set(tier0_syms) <= set(comp):
                        rp.fail("MARKET_MISSING_TIER0_SYMBOL", r["obs_id"])
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
        # a boundary b is startup-excused only if b < deadline, b*1e6 < recv_ns of the first persisted value and
        # b*1e6 < ready_ns (first message, claimed): ns resolution (review M1), tighten-only use of the claim
        excuse_ns = deadline * 1_000_000
        if rs:
            excuse_ns = min(excuse_ns, rs[0]["recv_ts_ns"])
            rd = ready.get(name)
            if rd is None:
                rp.fail("STREAM_READY_LIFECYCLE_MISSING", name)
            else:
                excuse_ns = min(excuse_ns, rd)
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
            elif b * 1_000_000 < excuse_ns and (first_persisted is None or b < first_persisted):
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
    # B1 general rule: a HEALTHY health record can never be written while any stream has an open gap
    hl_all = sorted(((r["observed_at_ms"], r["payload"].get("state")) for r in by["health"]))
    pers_by_key = {e["key"]: sorted(x["sample_ms"] for x in streams.get(n, [])) for n, e in exp.items()}
    for key, glist in gaps.items():
        ps = pers_by_key.get(key)
        if ps is None:
            continue
        for g in glist:
            i = bisect.bisect_right(ps, g["last_missing_ms"])
            close = ps[i] if i < len(ps) else stop_req
            for t_, st_ in hl_all:
                if st_ == "HEALTHY" and g["first_missing_ms"] + 2000 <= t_ < close:   # 2 s = sampler-stall bound
                    rp.fail("HEALTHY_DURING_OPEN_GAP", f"{key}@{t_}")
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
        good = [q for q in p["probes"] if q["t1_ms"] >= q["t0_ms"]]
        if not good:
            rp.fail("CLOCK_NO_VALID_PROBE", r["obs_id"]); continue
        best = min(good, key=lambda q: (q["t1_ms"] - q["t0_ms"], q["t0_ms"]))
        rtt = best["t1_ms"] - best["t0_ms"]
        skew = best["serverTime"] - (best["t0_ms"] + best["t1_ms"]) / 2.0
        if abs(skew - p["skew_ms"]) > 1e-6 or abs(rtt / 2.0 - p["uncertainty_ms"]) > 1e-6 or best["serverTime"] != p["serverTime"]:
            rp.fail("CLOCK_RECOMPUTE_MISMATCH", r["obs_id"])
        excess = max(0.0, abs(skew) - rtt / 2.0)
        worst = excess if worst is None else max(worst, excess)
        if r["obs_id"] != f"clk|{p['serverTime']}":
            rp.fail("OBS_ID_MISMATCH", r["obs_id"])
    max_sp = 2 * cfg["cadence_ms"]["clock"]                          # F50 freshness bound, not a count (review M4)
    pts = [ws_start] + [r["observed_at_ms"] for r in clk] + [stop_req]
    if not clk or clk[0]["observed_at_ms"] - ws_start > 120_000:
        rp.fail("CLOCK_FIRST_PROBE_LATE_OR_MISSING")
    for a, b in zip(pts, pts[1:]):
        if b - a > max_sp:
            rp.fail("CLOCK_SPACING_EXCEEDED", f"{a}->{b}")
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
    rp.info["stop_counters"] = stop["payload"].get("counters")
    rp.info["clock_excess_worst_ms"] = worst
    rp.info["_ctx"] = {"ev": {k: [x["payload"] for x in v] for k, v in ev.items()}, "health": [r["payload"] for r in hl],
                       "ev_t": {k: [(x["observed_at_ms"], x["payload"]) for x in v] for k, v in ev.items()},
                       "health_t": [r["observed_at_ms"] for r in hl], "gaps_by_key": {k: v for k, v in gaps.items()},
                       "run": run, "ws_start": ws_start, "stop_req": stop_req, "exp": exp, "cov": cov,
                       "conn_of": conn_of, "conn_ev": dict(conn_ev),
                       "first_after": {n: sorted((x["sample_ms"], x["observed_at_ms"]) for x in streams.get(n, []))
                                       for n in exp},
                       "candles_got": sorted(f"{a}|{b}|{c}" for a, b, c in got)}
    rp.info["by_type"] = {k: len(v) for k, v in sorted(by.items())}
    rp.info["gaps"] = [{k: g[k] for k in ("stream_key", "first_missing_ms", "last_missing_ms", "missing_samples", "cause",
                                          "causes", "open_at_stop") if k in g} for gl in gaps.values() for g in gl]
    return finish(rp, base, segs)


def acceptance(rp: Report, spec: dict, expect_image: str | None, expect_commit: str | None) -> None:
    """Predeclared acceptance checks (review B1). Every failure is prefixed ACC_."""
    ctx = rp.info.get("_ctx")
    if ctx is None:
        rp.fail("ACC_NOT_EVALUABLE"); return
    run, cfg, ev, ws_start, stop_req = ctx["run"], ctx["run"]["config"], ctx["ev"], ctx["ws_start"], ctx["stop_req"]
    uni = run["universe"]["snapshot"]
    # pinned specification
    if cfg.get("profile") != spec["profile"] or sorted(uni["tier0"]) != sorted(spec["tier0"]) or \
            (spec["tier1"] is not None and sorted(uni["tier1"]) != spec["tier1"]) or \
            (spec["tier2"] is not None and sorted(uni["tier2"]) != spec["tier2"]):
        rp.fail("ACC_UNIVERSE_NOT_SPEC", [cfg.get("profile"), uni["tier0"], uni["tier1"], uni["tier2"]])
    for k, v in spec["cadence_ms"].items():
        if cfg["cadence_ms"].get(k) != v:
            rp.fail("ACC_CADENCE_NOT_SPEC", f"{k}={cfg['cadence_ms'].get(k)}")
    if cfg["depth_levels"].get("t0") != spec["depth_levels_t0"]:
        rp.fail("ACC_DEPTH_N_NOT_SPEC")
    for k, v in (spec.get("depth_levels") or {}).items():
        if cfg["depth_levels"].get(k) != v:
            rp.fail("ACC_DEPTH_N_NOT_SPEC", k)
    us = spec.get("universe")
    if us:
        ui = rp.info.get("universe") or {}
        if (cfg["tier1_min_quote_volume"], cfg["tier1_max"], [cfg["tier2_top_volume"], cfg["tier2_top_movers"],
                                                               cfg["tier2_max"]]) != (us["min_quote_volume"], us["tier1_max"], us["tier2"]):
            rp.fail("ACC_UNIVERSE_RULES_NOT_SPEC")
        if not ui.get("universe_id"):
            rp.fail("ACC_UNIVERSE_NOT_RECONSTRUCTED")
        elif ui["tier1"] + ui["tier2"] > us["tier1_max"] or ui["tier2"] > us["tier2"][2] or ui["tier1"] + ui["tier2"] == 0:
            rp.fail("ACC_UNIVERSE_SIZE", [ui["tier1"], ui["tier2"]])
        if us.get("expect_no_prior") and (ui.get("hysteresis") or rp.info.get("universe_prior")):
            rp.fail("ACC_UNIVERSE_UNEXPECTED_PRIOR")
        if len(ev.get("universe_attempt_failed", [])) > us["max_attempt_failures"]:
            rp.fail("ACC_UNIVERSE_ATTEMPTS", len(ev.get("universe_attempt_failed", [])))
    if list(cfg["candle_timeframes"]) != spec["candle_timeframes"]:
        rp.fail("ACC_CANDLE_TF_NOT_SPEC")
    for k, v in spec["first_obs_deadline_s"].items():
        if cfg["first_obs_deadline_s"].get(k) != v:
            rp.fail("ACC_DEADLINE_NOT_SPEC", k)
    if (cfg["depth_stale_ms"], cfg["book_t0_stale_ms"], cfg["market_stale_ms"]) != \
            (spec["stale_ms"]["depth"], spec["stale_ms"]["book_t0"], spec["stale_ms"]["market"]) or \
            cfg["conn_data_live_ms"] != spec["conn_data_live_ms"]:
        rp.fail("ACC_STALE_LIMITS_NOT_SPEC")
    if "depth_stale_ms_by_tier" in spec and (cfg.get("depth_stale_ms_by_tier") != spec["depth_stale_ms_by_tier"]
                                             or cfg.get("book_t12_dead_ms") != spec["book_t12_dead_ms"]):
        rp.fail("ACC_FRESHNESS_THRESHOLDS_NOT_SPEC", [cfg.get("depth_stale_ms_by_tier"), cfg.get("book_t12_dead_ms")])
    for n_, e_ in ctx["exp"].items():                          # verifier applies the PINNED values, not the run's
        if "depth_stale_ms_by_tier" in spec:
            want = (spec["depth_stale_ms_by_tier"][f"t{e_['tier']}"] if e_["kind"] == "depth" else
                    spec["stale_ms"]["book_t0"] if e_["kind"] == "book" and e_["tier"] == 0 else
                    spec["book_t12_dead_ms"] if e_["kind"] == "book" else spec["stale_ms"]["market"])
            if e_["stale_ms"] != want:
                rp.fail("ACC_STREAM_FRESHNESS_NOT_SPEC", n_)
    if cfg["health_record_interval_s"] != spec["health_record_interval_s"] or cfg["max_runtime_s"] != spec["max_runtime_s"]:
        rp.fail("ACC_RUNTIME_OR_HEALTH_INTERVAL_NOT_SPEC")
    # bounded runtime + clean stop
    stop = ev["stop"][0]
    runtime_s = (stop_req - ws_start) / 1000
    if stop.get("reason") != "max_runtime" or abs(runtime_s - spec["max_runtime_s"]) > spec["runtime_tolerance_s"]:
        rp.fail("ACC_RUNTIME_OR_STOP_REASON", [stop.get("reason"), runtime_s])
    markers = rp.info.get("control_markers_data", {})
    fin = [m for n, m in markers.items() if n.startswith("stop-")]
    if len(fin) != 1 or fin[0].get("state") != "STOPPED" or fin[0].get("exit_code") != 0 or fin[0].get("partials") != 0:
        rp.fail("ACC_FINAL_STOP_STATE", fin)
    # identities
    b = run.get("build", {})
    if expect_image is not None and b.get("image_id_runtime_claim") != expect_image:
        rp.fail("ACC_IMAGE_ID_MISMATCH", [b.get("image_id_runtime_claim"), expect_image])
    if expect_commit is not None and b.get("git_commit") != expect_commit:
        rp.fail("ACC_COMMIT_MISMATCH", [b.get("git_commit"), expect_commit])
    # lifecycle alerts + counters
    for e in spec["forbidden_lifecycle"]:
        if ev.get(e):
            rp.fail(f"ACC_LIFECYCLE_{e.upper()}", len(ev[e]))
    cnt = stop.get("counters") or {}
    for k in spec["zero_counters"]:
        if cnt.get(k):
            rp.fail(f"ACC_COUNTER_{k.upper()}", cnt.get(k))
    for k in spec["zero_counter_maps"]:
        if sum((cnt.get(k) or {}).values()):
            rp.fail(f"ACC_COUNTER_{k.upper()}", cnt.get(k))
    rej = {k: v for k, v in (cnt.get("rejected") or {}).items() if v}
    if rej:
        rp.fail("ACC_COUNTER_REJECTED", rej)
    # controlled reconnect (G3)
    rc = spec.get("reconnect")
    rwin = None
    if rc:
        rwin = check_reconnect(rp, rc, ctx, ws_start)
    elif ev.get("controlled_reconnect_test"):
        rp.fail("ACC_UNPLANNED_RECONNECT_TEST")
    # REST policy
    rs = spec.get("rest")
    if rs:
        seen = [max((p.get("rest") or {}).get("ip_used_weight_1m_seen") or 0,
                    (p.get("rest") or {}).get("ip_used_weight_1m_max") or 0) for p in ctx["health"]]
        evs = collections.Counter()
        for p in ctx["health"]:
            for k, v in ((p.get("rest") or {}).get("events") or {}).items():
                evs[k] = max(evs[k], v)
        if not any("rest" in p for p in ctx["health"]):
            rp.fail("ACC_REST_EVIDENCE_MISSING")
        if seen and max(seen) > rs["ip_weight_max"]:
            rp.fail("ACC_REST_IP_WEIGHT", max(seen))
        for k in rs["forbidden_events"]:
            if evs.get(k):
                rp.fail(f"ACC_REST_{k.upper()}", evs[k])
        rp.info["rest_policy"] = {"ip_weight_max_seen": max(seen) if seen else None, "events_max": dict(evs)}
    # resources (monitor evidence, container exit)
    rr = spec.get("resources")
    if rr:
        mon = rp.monitor or {}
        if not mon and rr.get("require_monitor"):
            rp.fail("ACC_RESOURCES_NOT_PROVIDED")
        elif mon:
            if mon.get("mem_max_mib", 0) > rr["mem_max_mib"] or mon.get("pids_max", 0) > rr["pids_max"]:
                rp.fail("ACC_RESOURCE_LIMIT", {k: mon.get(k) for k in ("mem_max_mib", "pids_max")})
            if mon.get("exit") != 0 or mon.get("oom") is not False or mon.get("restarts") != 0:
                rp.fail("ACC_CONTAINER_EXIT", {k: mon.get(k) for k in ("exit", "oom", "restarts")})
            rp.info["resources"] = mon
    st = spec.get("storage")
    if st:
        total = sum(rp.info.get("bytes_by_type", {}).values()) + sum(rp.info.get("idx_bytes_by_type", {}).values())
        hours = (stop_req - ws_start) / 3_600_000
        mbd = total / 1e6 * 24 / hours if hours else None
        lo, hi = st["design_band_mb_day"]
        rp.info["storage_projection"] = {"mb_per_day": None if mbd is None else round(mbd, 1), "design_band": [lo, hi],
                                         "within_design_band": None if mbd is None else lo <= mbd <= hi,
                                         "report_only": st.get("report_only", True)}
    # gap budget on sampled streams
    gb = spec["gap_budget"]
    for name, e in ctx["exp"].items():
        c = ctx["cov"].get(name, {})
        exp_n = max(1, c.get("expected", 0) - c.get("startup_excused", 0))
        allowance = max(gb["min_allowance_boundaries"], int(gb["max_fraction_per_stream"] * exp_n))   # NB2: declared floor
        if not rwin and c.get("gap_covered", 0) > allowance:
            rp.fail("ACC_GAP_BUDGET_EXCEEDED", f"{name}:{c.get('gap_covered')}>{allowance} of {exp_n}")
        n_rc = 0
        on_rc = bool(rwin) and ctx["conn_of"].get(name) == (spec.get("reconnect") or {}).get("conn")
        inwin = (lambda g: on_rc and rwin[0] <= g["first_missing_ms"] and g["last_missing_ms"] <= rwin[1])
        if rwin:
            n_rc = sum(g["missing_samples"] for g in ctx["gaps_by_key"].get(e["key"], []) if inwin(g))
        if c.get("gap_covered", 0) - n_rc > allowance:
            rp.fail("ACC_GAP_BUDGET_EXCLUDING_RECONNECT_EXCEEDED", f"{name}:{c.get('gap_covered') - n_rc}>{allowance}")
        for g in ctx["gaps_by_key"].get(e["key"], []):
            if rwin and inwin(g):
                if set(g.get("causes") or [g.get("cause")]) - set(gb["allowed_causes"]):
                    rp.fail("ACC_GAP_CAUSE_FORBIDDEN", f"{name}:{g.get('causes')}")
                continue                                           # reconnect-window gap: checked by check_reconnect
            if g.get("duration_ms", 0) > gb["max_gap_ms"]:
                rp.fail("ACC_GAP_TOO_LONG", f"{name}:{g.get('duration_ms')}")
            bad = set(g.get("causes") or [g.get("cause")]) - set(gb["allowed_causes"])
            if bad:
                rp.fail("ACC_GAP_CAUSE_FORBIDDEN", f"{name}:{sorted(bad)}")
    for k, gl in ctx["gaps_by_key"].items():
        if str(k).startswith("candle|"):
            for g in gl:
                if g.get("cause") not in spec["candle_gap_allowed_causes"]:
                    rp.fail("ACC_CANDLE_GAP_CAUSE", f"{k}:{g.get('cause')}")
                if g.get("cause") == "candle_not_listed_yet" and not (
                        isinstance(g.get("first_open_ms"), int) and g["first_open_ms"] > g["first_missing_ms"]):
                    rp.fail("ACC_CANDLE_NOT_LISTED_UNPROVEN", k)
        elif str(k).startswith(("backpressure|", "crash|")):
            rp.fail("ACC_GAP_FORBIDDEN_KEY", k)
    # health history budget
    hs, ts = ctx["health"], ctx["health_t"]
    h = spec["health"]
    non_ok = 0
    for p, t in zip(hs, ts):
        st = p.get("state")
        if st in ("HEALTHY", "STOPPING") or (st == "STARTING" and t <= ws_start + 1000 * h["startup_s"]):
            continue
        non_ok += 1
        reasons = p.get("reasons") or []
        bad = [r for r in reasons if not r.startswith(tuple(h["allowed_degraded_reason_prefixes"])) or
               (r.startswith(("gap_short:", "gap_open:")) and r.rsplit(":", 1)[-1] not in gb["allowed_causes"])]
        if st != "DEGRADED" or not reasons or bad:
            rp.fail("ACC_HEALTH_STATE_FORBIDDEN", {"t": t, "state": st, "reasons": reasons[:5]})
    if "max_non_healthy_time_fraction" in h:                   # G3: time-based (records bunch around blips)
        def gap_only_(reasons):                                  # time charged ONLY to short/open gaps with an
            return bool(reasons) and all(                         # allowed cause is bounded by the gap budget;
                r.startswith(("gap_short:", "gap_open:")) and r.rsplit(":", 1)[-1] in spec["gap_budget"]["allowed_causes"]
                for r in reasons)                                 # not charged twice (N-1)
        pts = list(zip(ts, [p.get("state") for p in hs], [p.get("reasons") or [] for p in hs])) + [(stop_req, "END", [])]
        bad_ms = tot_ms = 0
        for (t1_, s1_, r1_), (t2_, _, _) in zip(pts, pts[1:]):
            lo, hi = max(t1_, ws_start + 1000 * h["startup_s"]), t2_
            if rwin:
                if lo < rwin[1] and hi > rwin[0]:
                    segs_ = [(lo, min(hi, rwin[0])), (max(lo, rwin[1]), hi)]
                else:
                    segs_ = [(lo, hi)]
            else:
                segs_ = [(lo, hi)]
            for a_, b_ in segs_:
                if b_ > a_:
                    tot_ms += b_ - a_
                    if s1_ not in ("HEALTHY", "STOPPING") and not gap_only_(r1_):
                        bad_ms += b_ - a_
        frac = bad_ms / tot_ms if tot_ms else 0.0
        rp.info["health_non_healthy_time_fraction"] = round(frac, 5)
        if frac > h["max_non_healthy_time_fraction"]:
            rp.fail("ACC_HEALTH_TIME_BUDGET_EXCEEDED", round(frac, 5))
    elif hs and non_ok / len(hs) > h["max_non_healthy_fraction"]:
        rp.fail("ACC_HEALTH_BUDGET_EXCEEDED", f"{non_ok}/{len(hs)}")
    if not any(p.get("state") == "HEALTHY" for p in hs):
        rp.fail("ACC_NEVER_HEALTHY")
    # clock
    w = rp.info.get("clock_excess_worst_ms")
    if w is None or w > spec["clock_max_excess_ms"]:
        rp.fail("ACC_CLOCK_EXCESS", w)
    rp.info["acceptance_spec"] = spec["name"]


def check_reconnect(rp: Report, rc: dict, ctx: dict, ws_start: int):
    """G3 controlled reconnect: detection, health change, durable gap evidence, no stale pre-reconnect values,
    re-subscription + acks, freshness of the first post-reconnect values, HEALTHY only after full recovery.
    Returns the reconnect window [trigger, recovered] (ms) or None."""
    ev = ctx["ev"]
    tests = ev.get("controlled_reconnect_test", [])
    if len(tests) != 1:
        rp.fail("ACC_RECONNECT_TEST_COUNT", len(tests)); return None
    t = tests[0]
    trig = t.get("trigger_ms")
    if t.get("conn") != rc["conn"] or abs(trig - (ws_start + 1000 * rc["at_s"])) > 1000 * rc["trigger_tolerance_s"]:
        rp.fail("ACC_RECONNECT_NOT_AS_PLANNED", {"conn": t.get("conn"), "trigger_ms": trig})
        return None
    evs = ctx["conn_ev"].get(rc["conn"], [])
    downs = [x for x, up in evs if not up and x >= trig]
    if not downs or downs[0] - trig > 1000 * rc["detect_within_s"]:
        rp.fail("ACC_RECONNECT_DISCONNECT_NOT_DETECTED"); return None
    d0 = downs[0]
    ups = [x for x, up in evs if up and x > d0]
    if not ups or ups[0] - d0 > 1000 * rc["reconnect_within_s"]:
        rp.fail("ACC_RECONNECT_NOT_RECONNECTED"); return None
    u0 = ups[0]
    streams = [n for n, c in ctx["conn_of"].items() if c == rc["conn"] and n in ctx["exp"]]
    evt = ctx["ev_t"]
    sent = set()
    for t_, p in evt.get("subscribe_sent", []):
        if p.get("conn") == rc["conn"] and t_ >= u0:
            sent |= set(p.get("streams") or [])
    acked = set()
    for t_, p in evt.get("subscribe_ack", []):
        if p.get("conn") == rc["conn"] and t_ >= u0:
            acked |= set(p.get("streams") or [])
    initial = set()
    for t_, p in evt.get("subscribe_sent", []):
        if p.get("conn") == rc["conn"] and t_ < d0:
            initial |= set(p.get("streams") or [])
    if not sent or sent != initial or not sent <= acked:
        rp.fail("ACC_RECONNECT_RESUBSCRIBE_NOT_ACKED", {"not_acked": sorted(sent - acked)[:10],
                                                        "not_resent": sorted(initial - sent)[:10]})
    rec_t = u0
    for n in streams:
        post = [(s_, o_) for s_, o_ in ctx["first_after"].get(n, []) if s_ > d0]
        if not post:
            rp.fail("ACC_RECONNECT_STREAM_NOT_RECOVERED", n); continue
        s1, o1 = post[0]
        if o1 < u0:
            rp.fail("ACC_RECONNECT_STALE_VALUE", n)
        if s1 - u0 > 1000 * rc["recover_within_s"]:
            rp.fail("ACC_RECONNECT_RECOVERY_SLOW", f"{n}:{(s1 - u0) / 1000}s")
        rec_t = max(rec_t, s1)
    hs = list(zip(ctx["health_t"], ctx["health"]))
    if not any(d0 <= t_ <= rec_t and p.get("state") == "DEGRADED" for t_, p in hs):
        rp.fail("ACC_RECONNECT_HEALTH_NOT_DEGRADED")
    first_ok = [t_ for t_, p in hs if t_ > d0 and p.get("state") == "HEALTHY"]
    if not first_ok or first_ok[0] < u0:                         # never HEALTHY while the connection is down; the
        rp.fail("ACC_RECONNECT_HEALTHY_TOO_EARLY", {"first_healthy": first_ok[:1], "reconnect": u0})   # gap rule
    # (HEALTHY_DURING_OPEN_GAP, all streams) covers HEALTHY before every stream observes again
    recov = ev.get("controlled_reconnect_recovered", [])
    if len(recov) != 1:
        rp.fail("ACC_RECONNECT_RECOVERED_RECORD", len(recov))
    rp.info["controlled_reconnect"] = {"trigger_ms": trig, "disconnect_ms": d0, "reconnect_ms": u0, "recovered_ms": rec_t,
                                       "outage_s": (u0 - d0) / 1000, "recovery_s": (rec_t - d0) / 1000,
                                       "streams": len(streams), "first_healthy_after_ms": first_ok[:1],
                                       "collector_recovered_record": recov[:1]}
    return [trig, rec_t + 1000 * rc["recover_within_s"]]


def finish(rp: Report, base: str, segs=None) -> dict:
    q = os.path.join(base, "quarantine")
    qfiles = sorted(os.listdir(q)) if os.path.isdir(q) else []
    if qfiles:
        rp.fail("QUARANTINE_NOT_EMPTY", qfiles[:5])
    ctl = os.path.join(base, "control")
    cfiles = sorted(os.listdir(ctl)) if os.path.isdir(ctl) else []
    data = {}
    for f in cfiles:
        if f.startswith("fatal-"):
            rp.fail("FATAL_MARKER_PRESENT", f)
        if f.startswith("disk_stop-"):
            rp.fail("DISK_STOP_MARKER_PRESENT", f)
        try:
            with open(os.path.join(ctl, f), encoding="utf-8") as fh:
                data[f] = json.load(fh)
        except (OSError, ValueError):
            rp.fail("CONTROL_MARKER_UNREADABLE", f)
    rp.info["control_markers"] = cfiles
    rp.info["control_markers_data"] = data
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
    if rp.spec is not None:
        acceptance(rp, rp.spec, rp.expect_image, rp.expect_commit)
    info = {k: v for k, v in rp.info.items() if k != "_ctx"}
    return {"PASS": not rp.failures, "failures": dict(rp.failures), "failure_examples": dict(rp.examples),
            "acceptance": None if rp.spec is None else not any(k.startswith("ACC_") for k in rp.failures), **info}


def str_keys(o):
    """JSON export: every mapping key as a string (None / int keys must never break or drop a report)."""
    if isinstance(o, dict):
        return {("null" if k is None else str(k)): str_keys(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [str_keys(v) for v in o]
    return o


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir"); ap.add_argument("--boot"); ap.add_argument("--json")
    ap.add_argument("--acceptance", choices=["g2r", "g3"]); ap.add_argument("--spec")
    ap.add_argument("--expect-image-id"); ap.add_argument("--expect-commit")
    ap.add_argument("--resources-tsv"); ap.add_argument("--monitor-log")
    ap.add_argument("--print-spec", action="store_true")
    a = ap.parse_args(argv)
    spec = {"g2r": G2R_SPEC, "g3": G3_SPEC}.get(a.acceptance)
    if a.print_spec:
        print(json.dumps(spec, indent=1, sort_keys=True)); return 0
    if a.spec:
        with open(a.spec, encoding="utf-8") as fh:
            spec = json.load(fh)
    rep = verify(a.data_dir, a.boot, spec, a.expect_image_id, a.expect_commit,
                 monitor=read_monitor(a.resources_tsv, a.monitor_log))
    out = json.dumps(str_keys(rep), indent=1, sort_keys=True, default=str)       # G3-F2: never fail on key types
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    print(json.dumps({"PASS": rep["PASS"], "acceptance": rep["acceptance"], "failures": rep["failures"], "totals": rep.get("totals"),
                      "records": rep.get("records"), "segments": rep.get("segments")}, sort_keys=True))
    return 0 if rep["PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
