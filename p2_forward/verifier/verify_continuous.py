#!/usr/bin/env python3
"""Independent DAY verifier for a continuous-mode dataset (P2-CR; multiple runs, universe epochs, explicit downtime).

INDEPENDENCE: imports nothing from the collector package (`p2_forward`); only stdlib and the sibling independent
verifier (`verify_independent`: field contract, universe re-derivation, expected-stream derivation). The bounded
single-run verifier (`verify_independent.verify`) is unchanged; this module adds day-scoped, multi-run verification.

What a PASS for day D means (every boundary of every expected stream in [D 00:00, D+1 00:00) is accounted for):
  * files: every segment of D (and the next day's first hour, where records about D's last seconds land) is
    certified: sidecar = manifest SHA-256 = recomputed SHA-256, .idx record count = decoded lines, 0444; D's file set
    equals the collector's day-close record (days/D.json) and D's manifest exactly; no partial / pending / certifying;
  * runs: each run active in D is identified by an immutable run record (SHA-checked); a run starting in D has a
    downtime record naming its predecessor; a run that ended without a stop record (crash / kill) is closed only by
    its successor's downtime record (otherwise the day cannot be verified yet: fail closed);
  * epochs: the expected stream set of each (run, universe) epoch is re-derived from the run's configuration and the
    epoch's universe artifact, whose tiers are independently recomputed from its persisted raw REST inputs (PIT);
  * boundaries: each expected boundary is PERSISTED (strict PIT, aligned, connection up, post-(re)connect, fresh),
    GAP-COVERED (an explicit gap record of that run), STARTUP-EXCUSED (before a run's or an added stream's
    first-observation deadline AND before its first persisted value), DOWNTIME (between runs: explicit clean stop or
    an explicit downtime record; never stitched), or UNEXPLAINED (=> FAIL);
  * no duplicate observation ids, no record outside its run's window, candles / clock / health continuity per run.

Usage: python3 verify_continuous.py <dataset_dir> --day YYYY-MM-DD [--json out.json] [--allow-test-calendar]
       python3 verify_continuous.py <dataset_dir> --run-chain [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_independent as VI                                      # noqa: E402  (independent sibling, stdlib only)

PRODUCTION_CALENDAR = {"hour_ms": 3_600_000, "epoch_hour": 0, "base": "1970-01-01T00:00:00+00:00"}
SEG_SUFFIXES = (".jsonl.gz", ".jsonl.gz.sha256", ".idx")
VERIFIER_VERSION = "verify-continuous-v1"


# ---------------- calendar (re-implemented; no collector import) ----------------
class Calendar:
    def __init__(self, p: dict):
        self.hour_ms, self.epoch_hour = int(p["hour_ms"]), int(p["epoch_hour"])
        self.base = dt.datetime.fromisoformat(p["base"])

    def day_start(self, day: str) -> int:
        d = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
        return (int((d - self.base).total_seconds() // 3600) + self.epoch_hour) * self.hour_ms

    def day_end(self, day: str) -> int:
        return self.day_start(day) + 24 * self.hour_ms

    def hour_key(self, ms: int) -> str:
        return (self.base + dt.timedelta(hours=ms // self.hour_ms - self.epoch_hour)).strftime("%Y%m%dT%H")

    def day_key(self, ms: int) -> str:
        return (self.base + dt.timedelta(hours=ms // self.hour_ms - self.epoch_hour)).strftime("%Y-%m-%d")


def _json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _ro(path) -> bool:
    return not (os.stat(path).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


# ---------------- run chain (runs/ + control/ only: O(runs)) ----------------
def run_chain(base: str, rp: VI.Report) -> list:
    """Runs ordered by creation; each with its downtime record and stop marker. Checks the chain is unbroken."""
    rd, out = os.path.join(base, "runs"), []
    for f in sorted(os.listdir(rd)) if os.path.isdir(rd) else []:
        if f.startswith("run-") and f.endswith(".json"):
            p = os.path.join(rd, f)
            r = _json(p)
            if not _ro(p):
                rp.fail("NOT_READ_ONLY", f"runs/{f}")
            boot = r.get("boot_id")
            dtp = os.path.join(rd, f"downtime-{boot}.json")
            mk = os.path.join(base, "control", f"stop-{boot[:8]}.json")
            out.append({"boot_id": boot, "file": f"runs/{f}", "sha256": VI.sha256(p), "created_ms": r.get("created_ms"),
                        "record": r, "downtime": _json(dtp) if os.path.exists(dtp) else None,
                        "stop_marker": _json(mk) if os.path.exists(mk) else None})
    out.sort(key=lambda x: (x["created_ms"], x["boot_id"]))
    for i, r in enumerate(out):
        if r["record"].get("mode") != "continuous":
            rp.fail("RUN_NOT_CONTINUOUS_MODE", r["boot_id"])
        d = r["downtime"]
        started = (r["stop_marker"] or {}).get("ws_start_ms") is not None or d is not None
        if not started:
            continue                                           # failed before ws_start: no epoch, no downtime record
        if d is None:
            rp.fail("DOWNTIME_RECORD_MISSING", r["boot_id"]); continue
        prev = d.get("previous_run")
        want_prev = out[i - 1]["boot_id"] if i else None
        if (prev or {}).get("boot_id") != want_prev:
            rp.fail("RUN_CHAIN_BROKEN", {"run": r["boot_id"], "names": (prev or {}).get("boot_id"), "expected": want_prev})
        if i == 0 and d.get("cause") != "first_run":
            rp.fail("FIRST_RUN_CAUSE", d.get("cause"))
        if i and want_prev is not None:
            pm = out[i - 1]["stop_marker"]
            clean = pm is not None and pm.get("boot_id") == want_prev
            if bool((prev or {}).get("clean_stop")) != clean:
                rp.fail("DOWNTIME_CLEAN_FLAG_WRONG", r["boot_id"])
            if clean and (prev or {}).get("stop_requested_ms") != pm.get("stop_requested_ms"):
                rp.fail("DOWNTIME_FROM_NE_STOP", r["boot_id"])
    return out


# ---------------- files of a day ----------------
def load_day_files(base: str, day: str, cal: Calendar, rp: VI.Report) -> tuple:
    """(records, file_count). D's own segments (full set) + the next day's first-hour segments (spillover)."""
    nxt = cal.day_key(cal.day_end(day))
    n_spill = min(24, max(1, -(-60_000 // cal.hour_ms)))              # >= 60 s of the next day (production: 1 h)
    spill_hours = {cal.hour_key(cal.day_end(day) + i * cal.hour_ms) for i in range(n_spill)}
    raw = os.path.join(base, "raw")
    want = []
    for t in sorted(os.listdir(raw)) if os.path.isdir(raw) else []:
        for d_, spill in ((day, False), (nxt, True)):
            dd = os.path.join(raw, t, d_)
            if not os.path.isdir(dd):
                continue
            for f in sorted(os.listdir(dd)):
                if spill and not any(f"-{h}Z-" in f for h in spill_hours):
                    continue
                want.append((os.path.relpath(os.path.join(dd, f), base), d_, spill))
    man = {}
    for d_ in (day, nxt):
        mp = os.path.join(base, "manifests", f"{d_}.jsonl")
        if os.path.exists(mp):
            with open(mp, encoding="utf-8") as fh:
                for line in fh:
                    e = json.loads(line)
                    if e["segment"] in man:
                        rp.fail("MANIFEST_DUPLICATE_ENTRY", e["segment"])
                    man[e["segment"]] = e
    # day-close record (collector) must match D's directory listing and manifest
    dcp = os.path.join(base, "days", f"{day}.json")
    own = {rel for rel, d_, sp in want if not sp}
    if not os.path.exists(dcp):
        rp.fail("DAY_NOT_CLOSED", day)
    else:
        dc = _json(dcp)
        if not _ro(dcp):
            rp.fail("NOT_READ_ONLY", f"days/{day}.json")
        listed = {f["path"]: f["bytes"] for f in dc.get("files", [])}
        have = {rel: os.path.getsize(os.path.join(base, rel)) for rel in own}
        if listed != have:
            rp.fail("DAY_CLOSE_LISTING_MISMATCH", sorted(set(listed) ^ set(have))[:5] or "sizes")
        mp = os.path.join(base, "manifests", f"{day}.jsonl")
        if dc.get("manifest_sha256") is not None and (not os.path.exists(mp) or VI.sha256(mp) != dc["manifest_sha256"]):
            rp.fail("DAY_CLOSE_MANIFEST_SHA_MISMATCH", day)
        rp.info["day_close"] = {"sha256": VI.sha256(dcp), "segments": dc.get("segments"), "bytes_total": dc.get("bytes_total"),
                                "calendar": dc.get("calendar")}
    own_segs = {rel for rel in own if rel.endswith(".jsonl.gz")}
    day_man = {k for k, e in man.items() if k.split("/")[2] == day}
    for s in sorted(own_segs - day_man):
        rp.fail("SEGMENT_NOT_IN_MANIFEST", s)
    for s in sorted(day_man - own_segs):
        rp.fail("MANIFEST_ENTRY_WITHOUT_FILE", s)
    recs, nfiles = [], 0
    for rel, d_, spill in want:
        p = os.path.join(base, rel)
        f = os.path.basename(rel)
        if f.endswith((".partial", ".pending", ".certifying", ".tmp")):
            rp.fail("UNCERTIFIED_FILE_PRESENT", rel); continue
        if not f.endswith(SEG_SUFFIXES):
            rp.fail("UNEXPECTED_FILE", rel); continue
        if not _ro(p):
            rp.fail("NOT_READ_ONLY", rel)
        if not f.endswith(".jsonl.gz"):
            stem = p[:-len(".jsonl.gz.sha256")] if f.endswith(".sha256") else p[:-len(".idx")]
            if not os.path.exists(stem + ".jsonl.gz"):
                rp.fail("ORPHAN_SIDECAR", rel)
            continue
        nfiles += 1
        dig = VI.sha256(p)
        try:
            with open(p + ".sha256", encoding="utf-8") as fh_:
                side = fh_.read().split()[0]
        except (OSError, IndexError):
            side = None
        if side != dig:
            rp.fail("CHECKSUM_SIDECAR_MISMATCH", rel)
        if (man.get(rel) or {}).get("sha256") != dig:
            rp.fail("CHECKSUM_MANIFEST_MISMATCH", rel)
        lines = []
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                for line in fh:
                    lines.append(VI.compact(json.loads(line)))
        except (OSError, EOFError, ValueError) as e:
            rp.fail("DECODE_ERROR", f"{rel}:{type(e).__name__}"); continue
        n_idx = 0
        try:
            with open(p[:-9] + ".idx", encoding="utf-8") as fh:
                for line in fh:
                    n_idx += json.loads(line)["records"]
        except (OSError, ValueError, KeyError):
            rp.fail("IDX_UNREADABLE", rel)
        if n_idx != len(lines):
            rp.fail("IDX_RECORD_COUNT_MISMATCH", f"{rel}:{n_idx}!={len(lines)}")
        if (man.get(rel) or {}).get("records") != len(lines):
            rp.fail("MANIFEST_RECORD_COUNT_MISMATCH", rel)
        for r in lines:
            if isinstance(r, dict) and VI.check_fields(r, rp):
                r["_file"] = rel
                r["_spill"] = spill
                recs.append(r)
    return recs, nfiles


# ---------------- epochs ----------------
def _derive(cfg: dict, tiers: dict, listed=None, rp=None) -> dict:
    """Expected streams of a (config, universe) epoch via the independent derivation."""
    pseudo = {"config": cfg, "universe": {"snapshot": tiers}, "expected_streams": listed if listed is not None else []}
    sub = VI.Report()
    exp = VI.derive_expected(pseudo, sub)
    if rp is not None and listed is not None:
        for k, v in sub.failures.items():
            rp.failures[k] += v
    return exp


def _universe_check(base, rp, meta: dict, cfg: dict, run_snapshot=None) -> dict | None:
    """Universe artifact of an epoch: SHA as claimed, tiers recomputed from raw inputs, PIT vs effective_from."""
    fp = os.path.join(base, meta.get("file") or "-")
    if not os.path.exists(fp) or VI.sha256(fp) != meta.get("sha256"):
        rp.fail("UNIVERSE_FILE_MISSING_OR_SHA_MISMATCH", meta.get("file")); return None
    doc = _json(fp)
    if doc.get("universe_id") != meta.get("universe_id"):
        rp.fail("UNIVERSE_ID_MISMATCH", meta.get("universe_id")); return None
    sub = VI.Report()
    act = {"payload": {**{k: meta.get(k) for k in ("universe_id", "file", "sha256")},
                       "effective_from_ms": meta["effective_from_ms"]}}
    rec = {"obs_id": doc["universe_id"], "payload": {**doc, "file": meta.get("file"), "sha256": meta.get("sha256")}}
    snap = run_snapshot or {k: doc.get(k) for k in ("tier0", "tier1", "tier2")}
    VI.check_universe(sub, {"universe": [rec]}, {"universe_active": [act]},
                      {"universe": {"rule_version": doc.get("rule_version"), "snapshot": snap}, "config": cfg},
                      base, meta["effective_from_ms"])
    for k, v in sub.failures.items():
        rp.failures[k] += v
        for ex in sub.examples.get(k, []):
            if len(rp.examples[k]) < 5:
                rp.examples[k].append(ex)
    return doc


def verify_day(base: str, day: str, allow_test_calendar: bool = False) -> dict:
    rp = VI.Report()
    rp.spec = None
    ds_p = os.path.join(base, "dataset.json")
    if not os.path.exists(ds_p):
        rp.fail("DATASET_IDENTITY_MISSING")
        return _finish(rp, base, day)
    ds = _json(ds_p)
    calp = ds.get("calendar") or {}
    if calp != PRODUCTION_CALENDAR and not allow_test_calendar:
        rp.fail("NON_PRODUCTION_CALENDAR", calp)
        return _finish(rp, base, day)
    cal = Calendar(calp)
    D0, D1 = cal.day_start(day), cal.day_end(day)
    rp.info.update({"dataset_id": ds.get("dataset_id"), "day": day, "day_start_ms": D0, "day_end_ms": D1, "calendar": calp})
    chain = run_chain(base, rp)
    by_boot = {r["boot_id"]: r for r in chain}
    order = [r["boot_id"] for r in chain]
    recs, nfiles = load_day_files(base, day, cal, rp)
    rp.info["files"] = nfiles

    life = collections.defaultdict(list)                               # boot -> lifecycle records (sorted)
    by = collections.defaultdict(lambda: collections.defaultdict(list))  # boot -> type -> records
    for r in recs:
        if r["boot_id"] not in by_boot:
            rp.fail("RECORD_OF_UNKNOWN_RUN", r["obs_id"]); continue
        by[r["boot_id"]][r["type"]].append(r)
        if r["type"] == "lifecycle":
            life[r["boot_id"]].append(r)
    for b in life:
        life[b].sort(key=lambda r: r["recv_ts_ns"])

    def ev(boot, name, lo=None, hi=None):
        return [r for r in life.get(boot, []) if r["payload"].get("event") == name
                and (lo is None or r["observed_at_ms"] >= lo) and (hi is None or r["observed_at_ms"] < hi)]

    # ---- per-run windows inside D ----
    runs = []
    for boot in order:
        r = by_boot[boot]
        cp = [x for x in ev(boot, "day_checkpoint") if x["payload"].get("day_start_ms") == D0]
        wss = ev(boot, "ws_start")
        wss_d = [x for x in wss if D0 <= x["payload"]["ws_start_ms"] < D1]
        cp_next = [x for x in ev(boot, "day_checkpoint") if x["payload"].get("day_start_ms") == D1]
        stops = ev(boot, "stop")
        if not cp and not wss_d:
            if any(not r["_spill"] and r["observed_at_ms"] < D1 for t_ in by[boot].values() for r in t_):
                rp.fail("RUN_RECORDS_WITHOUT_EPOCH_START", boot)
            continue
        if len(cp) > 1 or len(wss_d) > 1 or len(stops) > 1:
            rp.fail("RUN_ANCHOR_DUPLICATED", boot)
        start_kind = "checkpoint" if cp else "ws_start"
        lo = D0 if cp else wss_d[0]["payload"]["ws_start_ms"]
        if cp and wss_d:
            rp.fail("CHECKPOINT_AND_WS_START_SAME_DAY", boot)
        stop_ms = stops[0]["payload"]["stop_requested_ms"] if stops else None
        if cp_next:
            end_kind, hi = "day_end", D1
        elif stop_ms is not None:
            end_kind, hi = "stop", min(stop_ms, D1)
        else:
            end_kind, hi = "crash", None                                # resolved per stream below
            succ = next((x for x in chain if (x["downtime"] or {}).get("previous_run", {}) and
                         x["downtime"]["previous_run"].get("boot_id") == boot), None)
            if succ is None:
                rp.fail("CRASHED_RUN_UNRESOLVED_NO_SUCCESSOR", boot)
            elif succ["downtime"]["previous_run"].get("clean_stop"):
                rp.fail("CRASH_BUT_SUCCESSOR_CLAIMS_CLEAN", boot)
        # run record identity
        if start_kind == "ws_start":
            st = ev(boot, "start")
            if len(st) != 1:
                rp.fail("LIFECYCLE_START_COUNT", [boot, len(st)])
            elif st[0]["payload"].get("run_record_sha256") != r["sha256"] or st[0]["payload"].get("run_record") != r["record"]:
                rp.fail("RUN_RECORD_SHA_MISMATCH", boot)
            d = r["downtime"]
            if d is None or d.get("until_ms") != lo:
                rp.fail("DOWNTIME_UNTIL_NE_WS_START", boot)
        else:
            p = cp[0]["payload"]
            if p.get("run_record_sha256") != r["sha256"] or p.get("run_record_file") != r["file"]:
                rp.fail("CHECKPOINT_RUN_RECORD_MISMATCH", boot)
            if p.get("calendar") != calp:
                rp.fail("CHECKPOINT_CALENDAR_MISMATCH", boot)
        runs.append({"boot": boot, "lo": lo, "hi": hi, "start_kind": start_kind, "end_kind": end_kind,
                     "cfg": r["record"]["config"], "run": r["record"], "cp": cp[0]["payload"] if cp else None,
                     "ws": wss_d[0]["payload"] if wss_d else None, "stop_ms": stop_ms})
    if not runs:
        rp.fail("NO_RUN_ACTIVE_IN_DAY")
        return _finish(rp, base, day)

    # ---- epochs per run ----
    epochs = []
    for R in runs:
        boot, cfg = R["boot"], R["cfg"]
        if R["start_kind"] == "ws_start":
            ua = ev(R["boot"], "universe_active")
            if len(ua) != 1:
                rp.fail("UNIVERSE_ACTIVE_COUNT", [boot, len(ua)]); continue
            meta = {**ua[0]["payload"]}
            if meta.get("effective_from_ms") != R["lo"]:
                rp.fail("UNIVERSE_EFFECTIVE_FROM_NE_WS_START", boot)
            conns = R["ws"].get("conns") or {}
            snap = (R["run"].get("universe") or {}).get("snapshot")
            doc = _universe_check(base, rp, meta, cfg, run_snapshot=snap)
            listed = R["run"].get("expected_streams")
            cur = {"lo": R["lo"], "lo_exclusive": True, "meta": meta, "doc": doc, "conns": conns, "kind": "ws_start",
                   "listed": listed, "added": None}
        else:
            meta = dict(R["cp"]["universe"])
            conns = {k: v.get("streams") for k, v in (R["cp"].get("conns") or {}).items()}
            doc = _universe_check(base, rp, meta, cfg)
            cur = {"lo": D0, "lo_exclusive": False, "meta": meta, "doc": doc, "conns": conns, "kind": "checkpoint",
                   "listed": None, "added": None}
        seq = [cur]
        for t in ev(boot, "universe_transition"):
            p = t["payload"]
            if not (R["lo"] <= p["effective_from_ms"] < D1):
                continue
            meta2 = {k: p.get(k) for k in ("universe_id", "file", "sha256")}
            meta2["effective_from_ms"] = p["effective_from_ms"]
            doc2 = _universe_check(base, rp, meta2, cfg)
            seq.append({"lo": p["effective_from_ms"], "lo_exclusive": False, "meta": meta2, "doc": doc2,
                        "conns": p.get("conns") or {}, "kind": "transition", "listed": None,
                        "added": set(p.get("added") or []), "retiered": {x["stream"] for x in p.get("retiered") or []}})
        for i, e in enumerate(seq):
            e["boot"], e["cfg"], e["run_hi"] = boot, cfg, R["hi"]
            e["hi"] = seq[i + 1]["lo"] if i + 1 < len(seq) else R["hi"]
            if e["doc"] is None:
                continue
            tiers = {k: e["doc"].get(k) for k in ("tier0", "tier1", "tier2")}
            e["exp"] = _derive(cfg, tiers, e["listed"], rp if e["listed"] is not None else None)
            conn_of = {n: c for c, ss in (e["conns"] or {}).items() for n in (ss or [])}
            for n in e["exp"]:
                if n not in conn_of:
                    rp.fail("STREAM_WITHOUT_CONNECTION", [boot, n])
                if sum(1 for c, ss in (e["conns"] or {}).items() if n in (ss or [])) > 1:
                    rp.fail("DUPLICATE_SUBSCRIPTION", [boot, n])
            e["conn_of"] = conn_of
            epochs.append(e)
    rp.info["runs"] = [{k: R[k] for k in ("boot", "lo", "hi", "start_kind", "end_kind")} for R in runs]
    rp.info["epochs"] = [{"boot": e["boot"][:8], "kind": e["kind"], "lo": e["lo"], "hi": e["hi"],
                          "universe_id": e["meta"].get("universe_id"), "streams": len(e.get("exp") or {})} for e in epochs]

    # ---- connection events per boot (initial state from the checkpoint) ----
    conn_ev = {}
    for R in runs:
        ce = collections.defaultdict(list)
        if R["cp"]:
            for c, st in (R["cp"].get("conns") or {}).items():
                ce[c].append((st.get("last_up_ms") if st.get("up") else D0 - 1, bool(st.get("up"))))
        for name_, up in (("ws_connected", True), ("ws_disconnected", False), ("ws_connect_failed", False)):
            for x in ev(R["boot"], name_):
                ce[x["payload"].get("conn")].append((x["observed_at_ms"], up))
        for k in ce:
            ce[k].sort()
        conn_ev[R["boot"]] = ce

    # ---- duplicates, windows ----
    seen = {}
    for r in recs:
        o = r["obs_id"]
        if o in seen:
            if r["type"] in ("candle", "universe"):
                if json.dumps(seen[o]["payload"], sort_keys=True) != json.dumps(r["payload"], sort_keys=True):
                    rp.fail("CONFLICTING_DUPLICATE", o)
            else:
                rp.fail("DUPLICATE_OBS_ID", o)
        else:
            seen[o] = r
    for R in runs:
        if R["stop_ms"] is not None:
            stop_r = ev(R["boot"], "stop")[0]
            for t_, rs_ in by[R["boot"]].items():
                for r in rs_:
                    if r["recv_ts_ns"] > stop_r["recv_ts_ns"]:
                        rp.fail("RECORD_AFTER_STOP", r["obs_id"])

    # ---- stream boundary reconciliation ----
    totals = collections.Counter()
    downtime = collections.Counter()
    streams_all = set()
    for e in epochs:
        streams_all |= set(e.get("exp") or {})
    succ_ws = {}                                                        # boot -> next run's ws_start in D (or D1)
    for i, R in enumerate(runs):
        nxt = next((x for x in runs[i + 1:] if x["start_kind"] == "ws_start"), None)
        succ_ws[R["boot"]] = nxt["lo"] if nxt else D1
    persisted_any = collections.defaultdict(set)                       # (key) -> boundaries persisted by any boot
    accounted = collections.defaultdict(set)                           # key -> boundaries accounted (any class)
    cov_info = {}
    for e in epochs:
        boot = e["boot"]
        if not e.get("exp"):
            continue
        gaps = collections.defaultdict(list)
        for g in by[boot]["gap"]:
            gaps[g["payload"].get("stream_key")].append(g["payload"])
        ready = {}
        for x in ev(boot, "stream_ready"):
            rn = x["payload"].get("ready_ns")
            ready.setdefault(x["payload"].get("stream"), rn)
        recs_by_stream = collections.defaultdict(list)
        for t_ in ("book", "depth", "market"):
            for r in by[boot][t_]:
                recs_by_stream[r["endpoint"]].append(r)
        for name, x in sorted(e["exp"].items()):
            cad = x["cadence"]
            lo, hi = e["lo"], e["hi"]
            crash_end = None
            if hi is None:                                              # crashed run: per-stream accounted end
                last = [r["sample_ms"] for r in recs_by_stream.get(name, []) if r["cadence_ms"] == cad]
                last += [g["last_missing_ms"] for g in gaps.get(x["key"], []) if g.get("cadence_ms") == cad]
                crash_end = (max(last) + cad) if last else lo
                hi = crash_end
            rs = sorted((r for r in recs_by_stream.get(name, []) if r["cadence_ms"] == cad
                         and (lo < r["sample_ms"] if e["lo_exclusive"] else lo <= r["sample_ms"]) and r["sample_ms"] < hi),
                        key=lambda r: r["sample_ms"])
            prev = None
            for r in rs:
                s = r["sample_ms"]
                if s % cad:
                    rp.fail("SAMPLE_NOT_ALIGNED", r["obs_id"]); continue
                if r["recv_ts_ns"] > s * 1_000_000:
                    rp.fail("OBSERVED_AFTER_SAMPLE", r["obs_id"])
                st_up = None
                for t_, up_ in conn_ev[boot].get(e["conn_of"].get(name), []):
                    if t_ <= s:
                        st_up = (t_, up_)
                    else:
                        break
                if st_up is None or not st_up[1]:
                    rp.fail("SAMPLE_WHILE_CONNECTION_DOWN", r["obs_id"])
                elif r["observed_at_ms"] < st_up[0]:
                    rp.fail("PRE_RECONNECT_VALUE_PERSISTED", r["obs_id"])
                lim = x["stale_ms"]
                if lim is not None and x["kind"] != "market" and s - r["observed_at_ms"] > lim:
                    rp.fail("STALE_VALUE_PERSISTED", r["obs_id"])
                if x["kind"] in ("book", "depth"):
                    if r["symbol"] != x["symbol"] or r["tier"] != x["tier"]:
                        rp.fail("SYMBOL_OR_TIER_MISMATCH", r["obs_id"])
                    want = (f"bt|{x['symbol']}|{r['exchange_seq']}|c{cad}|t{s}" if x["kind"] == "book" else
                            f"dp{x['levels']}|{x['symbol']}|{r['exchange_seq']}|c{cad}|t{s}")
                    if r["obs_id"] != want:
                        rp.fail("OBS_ID_MISMATCH", r["obs_id"])
                    if prev is not None:
                        if r["exchange_seq"] < prev["exchange_seq"]:
                            rp.fail("SEQ_DECREASING", r["obs_id"])
                        if r["unchanged"] != (r["exchange_seq"] == prev["exchange_seq"]):
                            rp.fail("UNCHANGED_INCONSISTENT", r["obs_id"])
                    elif r["unchanged"] and e["kind"] == "ws_start":
                        rp.fail("UNCHANGED_INCONSISTENT", r["obs_id"])
                elif r["obs_id"] != f"mkt|t{s}":
                    rp.fail("OBS_ID_MISMATCH", r["obs_id"])
                prev = r
            persisted = {r["sample_ms"] for r in rs}
            covered = set()
            for g in gaps.get(x["key"], []):
                if g.get("cadence_ms") != cad:
                    continue
                for b in range(g["first_missing_ms"], g["last_missing_ms"] + 1, cad):
                    if b in persisted:
                        rp.fail("FALSE_GAP", f"{x['key']}@{b}")
                    covered.add(b)
            # startup excuse: ws_start epochs (deadline from ws_start) and streams added by a transition (from T)
            excuse_ns = None
            if e["kind"] == "ws_start" or (e["kind"] == "transition" and name in (e["added"] or set())):
                excuse_ns = (lo + x["deadline_ms"]) * 1_000_000
                if rs:
                    excuse_ns = min(excuse_ns, rs[0]["recv_ts_ns"])
                if ready.get(name) is not None:
                    excuse_ns = min(excuse_ns, ready[name])
            first_p = min(persisted) if persisted else None
            b = (lo // cad + 1) * cad if e["lo_exclusive"] else -(-lo // cad) * cad
            c = collections.Counter()
            while b < hi and b < D1:
                if b >= D0:
                    if b in persisted:
                        c["persisted"] += 1
                    elif b in covered:
                        c["gap_covered"] += 1
                    elif excuse_ns is not None and b * 1_000_000 < excuse_ns and (first_p is None or b < first_p):
                        c["startup_excused"] += 1
                    else:
                        c["unexplained"] += 1
                        rp.fail("UNEXPLAINED_MISS", f"{boot[:8]}:{name}@{b}")
                    accounted[x["key"] + f"|c{cad}"].add(b)
                b += cad
            if crash_end is not None:                                   # crash: explicit downtime until successor
                b2, end2 = crash_end, succ_ws.get(boot, D1)
                while b2 < end2:
                    if D0 <= b2 < D1 and b2 not in accounted[x["key"] + f"|c{cad}"]:
                        c["downtime_crash"] += 1
                    b2 += cad
            cov_info[f"{boot[:8]}|{e['kind']}|{e['lo']}|{name}"] = dict(c)
            for k_ in ("persisted", "gap_covered", "startup_excused", "unexplained", "downtime_crash"):
                totals[k_] += c[k_]
    # downtime between runs (clean stops / before the first run / after the last run of the day)
    lo_runs = sorted((R["lo"], R["hi"] or D1, R["end_kind"], R["boot"]) for R in runs)
    cursor, intervals = D0, []
    for lo_, hi_, kind, boot in lo_runs:
        if lo_ > cursor:
            nxt_boot = by_boot[boot]
            d = nxt_boot["downtime"]
            if d is None:
                rp.fail("DOWNTIME_UNEXPLAINED", [cursor, lo_])
            else:
                downtime[d.get("cause", "unknown")] += lo_ - cursor
                intervals.append({"from_ms": cursor, "until_ms": lo_, "cause": d.get("cause"), "next_boot": boot})
        cursor = max(cursor, hi_)
    if cursor < D1:
        last = lo_runs[-1]
        if last[2] == "stop":
            downtime["collector_stopped"] += D1 - cursor
            intervals.append({"from_ms": cursor, "until_ms": D1, "cause": "collector_stopped", "next_boot": None})
        elif last[2] != "crash":
            rp.fail("DAY_TAIL_UNACCOUNTED", [cursor, D1])
    rp.info["totals"] = dict(totals)
    rp.info["downtime_ms"] = dict(downtime)
    rp.info["downtime_intervals"] = intervals
    rp.info["coverage"] = cov_info

    # ---- candles (per epoch; symbols of the epoch's universe) ----
    got = {}
    for R in runs:
        for r in by[R["boot"]]["candle"]:
            tf = r["endpoint"].split("interval=")[-1]
            k = r["payload"]
            if tf not in VI.TF:
                rp.fail("CANDLE_BAD_TF", r["obs_id"]); continue
            o, cl = int(k[0]), int(k[6])
            if o % VI.TF[tf] or cl != o + VI.TF[tf] - 1 or r["exchange_event_time_ms"] != cl:
                rp.fail("CANDLE_MISALIGNED", r["obs_id"])
            if not (r["available_at_ms"] > cl and r["available_at_ms"] == max(cl + 1, r["observed_at_ms"])):
                rp.fail("CANDLE_AVAILABILITY", r["obs_id"])
            got[(r["symbol"], tf, o)] = r
    cg = {(g["payload"]["stream_key"], g["payload"]["first_missing_ms"]) for R in runs for g in by[R["boot"]]["gap"]
          if str(g["payload"].get("stream_key")).startswith("candle|")}
    miss = 0
    for e in epochs:
        if not e.get("doc"):
            continue
        hi = e["hi"] if e["hi"] is not None else e["lo"]
        syms = sorted(set(e["doc"]["tier0"]) | set(e["doc"]["tier1"]) | set(e["doc"]["tier2"]))
        for tf in e["cfg"]["candle_timeframes"]:
            L = VI.TF[tf]
            b = (e["lo"] // L + 1) * L
            while b + VI.CANDLE_MARGIN_MS < min(hi, D1):
                if b >= D0:
                    for s in syms:
                        if (s, tf, b - L) not in got and (f"candle|{tf}|{s}", b - L) not in cg:
                            miss += 1; rp.fail("UNEXPLAINED_MISSING_CANDLE", f"{s}|{tf}|{b - L}")
                b += L
    rp.info["candles"] = {"got": len(got), "unexplained_missing": miss}

    # ---- clock and health continuity per run ----
    for R in runs:
        hi = R["hi"] if R["hi"] is not None else max([r["observed_at_ms"] for t_ in by[R["boot"]].values() for r in t_] or [R["lo"]])
        clk = sorted((r for r in by[R["boot"]]["clock"] if R["lo"] <= r["observed_at_ms"] < D1), key=lambda r: r["recv_ts_ns"])
        pts = [R["lo"]] + [r["observed_at_ms"] for r in clk] + [min(hi, D1)]
        lim = 2 * R["cfg"]["cadence_ms"]["clock"]
        if R["start_kind"] == "checkpoint":
            lim += R["cfg"]["cadence_ms"]["clock"]                    # last probe of the run lies in the previous day
        for a, b in zip(pts, pts[1:]):
            if b - a > lim:
                rp.fail("CLOCK_SPACING_EXCEEDED", f"{R['boot'][:8]}:{a}->{b}")
        hl = sorted((r for r in by[R["boot"]]["health"] if r["observed_at_ms"] < min(hi, D1)), key=lambda r: r["recv_ts_ns"])
        iv = 1000 * R["cfg"]["health_record_interval_s"] + 15_000
        hp = [R["lo"]] + [r["observed_at_ms"] for r in hl if r["observed_at_ms"] >= R["lo"]] + [min(hi, D1)]
        for a, b in zip(hp, hp[1:]):
            if b - a > iv:
                rp.fail("HEALTH_HISTORY_HOLE", f"{R['boot'][:8]}:{a}->{b}")
    rp.info["by_type"] = dict(collections.Counter(r["type"] for r in recs))
    return _finish(rp, base, day)


def _finish(rp: VI.Report, base: str, day) -> dict:
    me = os.path.abspath(__file__)
    return {"PASS": not rp.failures, "verifier": VERIFIER_VERSION, "verifier_sha256": VI.sha256(me),
            "verify_independent_sha256": VI.sha256(VI.__file__), "dataset": os.path.abspath(base), "day": day,
            "failures": dict(rp.failures), "examples": {k: v for k, v in rp.examples.items()},
            "info": {k: v for k, v in rp.info.items() if k != "coverage"}, "coverage": rp.info.get("coverage")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--day")
    ap.add_argument("--run-chain", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--allow-test-calendar", action="store_true")
    a = ap.parse_args(argv)
    if a.run_chain:
        rp = VI.Report()
        ch = run_chain(a.base, rp)
        out = {"PASS": not rp.failures, "failures": dict(rp.failures), "examples": dict(rp.examples),
               "runs": [{"boot_id": r["boot_id"], "created_ms": r["created_ms"],
                         "cause": (r["downtime"] or {}).get("cause"), "clean_stop_marker": r["stop_marker"] is not None,
                         "state": (r["stop_marker"] or {}).get("state")} for r in ch]}
    else:
        out = verify_day(a.base, a.day, a.allow_test_calendar)
    s = json.dumps(out, sort_keys=True, indent=1, default=str)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            fh.write(s + "\n")
    print(json.dumps({k: out[k] for k in ("PASS", "failures") if k in out}, sort_keys=True, default=str)[:4000])
    return 0 if out["PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
