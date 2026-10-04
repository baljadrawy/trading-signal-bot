"""Synthetic continuous-dataset generator mimicking the P2-CR collector layout (schema v2) for offline tests.

Writes: dataset.json, runs/run-*.json + downtime-*.json, control/stop-*.json, universe/*.json, raw/<type>/<day>/
segments (+ .sha256 + .idx), manifests/<day>.jsonl, days/<day>.json (day close), seals/<day>.json (+ report).
Deterministic (no wall clock, no RNG state shared with tests). Prices are smooth deterministic functions of time.
Never touches any real dataset: callers pass a fresh (temporary/scratch) directory.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import math
import os

CAL = {"base": "1970-01-01T00:00:00+00:00", "epoch_hour": 0, "hour_ms": 3_600_000}
TF = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
REAL_CAD = {"t0_book": 1000, "t1_book": 10000, "t2_book": 2000, "t0_depth": 1000, "t1_depth": 60000,
            "t2_depth": 5000, "market": 60000, "clock": 600000}
TEST_CAD = {"t0_book": 10000, "t1_book": 60000, "t2_book": 20000, "t0_depth": 10000, "t1_depth": 60000,
            "t2_depth": 30000, "market": 60000, "clock": 600000}


def ms(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def hour_key(t: int) -> str:
    return dt.datetime.fromtimestamp(t / 1000, tz=dt.timezone.utc).strftime("%Y%m%dT%H")


def day_of(t: int) -> str:
    return dt.datetime.fromtimestamp(t / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def wjson(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, sort_keys=True, indent=1)
        fh.write("\n")


def mid(sym: str, t: int) -> float:
    k = sum(ord(c) for c in sym)
    base = 10.0 + (k % 97) * 3.0
    x = (0.02 * math.sin(t / 3.7e6 + k) + 0.006 * math.sin(t / 5.3e5 + 2 * k) + 0.0015 * math.sin(t / 4.1e4 + k / 3)
         + 0.0004 * math.sin(t / 3.3e3 + k))
    return base * math.exp(x)


class Writer:
    def __init__(self, base, level=1):
        self.base, self.level, self.open, self.seq = base, level, {}, {}

    def put(self, r):
        hk = hour_key(r["recv_ts_ns"] // 1_000_000)
        key = (r["type"], hk, r["boot_id"])
        f = self.open.get(key)
        if f is None:
            n = self.seq.get(r["boot_id"], 0) + 1
            self.seq[r["boot_id"]] = n
            day = f"{hk[:4]}-{hk[4:6]}-{hk[6:8]}"
            rel = f"raw/{r['type']}/{day}/{r['type']}-{hk}Z-{r['boot_id'][:8]}-{n:06d}.jsonl.gz"
            p = os.path.join(self.base, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            raw = open(p, "wb")
            f = [gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=self.level), raw, rel, 0]
            self.open[key] = f
        f[0].write((json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n").encode())
        f[3] += 1

    def close(self):
        for f in self.open.values():
            f[0].close()
            f[1].close()
        self.open = {}


def refresh_hashes(base: str) -> None:
    """Recompute sidecars, .idx, manifests, day closes and seals (for existing days/seals). Used by mutation tests."""
    raw = os.path.join(base, "raw")
    man = {}
    for t in sorted(os.listdir(raw)):
        for d in sorted(os.listdir(os.path.join(raw, t))):
            dd = os.path.join(raw, t, d)
            for f in sorted(os.listdir(dd)):
                if not f.endswith(".jsonl.gz"):
                    continue
                p = os.path.join(dd, f)
                with gzip.open(p, "rt") as fh:
                    n = sum(1 for line in fh if line.strip())
                dig = sha(p)
                with open(p + ".sha256", "w") as fh:
                    fh.write(f"{dig}  {f}\n")
                with open(p[:-len(".jsonl.gz")] + ".idx", "w") as fh:
                    fh.write(json.dumps({"blk": 0, "end_offset": os.path.getsize(p), "records": n, "durable_ts_ns": 0}) + "\n")
                rel = os.path.relpath(p, base)
                man.setdefault(d, []).append({"segment": rel, "sha256": dig, "records": n, "bytes": os.path.getsize(p),
                                              "type": t, "boot_id": f.split("-")[-2], "certified_ms": 0,
                                              "certifier": "synthetic"})
    os.makedirs(os.path.join(base, "manifests"), exist_ok=True)
    for d, es in man.items():
        with open(os.path.join(base, "manifests", f"{d}.jsonl"), "w") as fh:
            for e in sorted(es, key=lambda e: e["segment"]):
                fh.write(json.dumps(e, sort_keys=True) + "\n")
    for d in sorted(os.listdir(os.path.join(base, "days"))) if os.path.isdir(os.path.join(base, "days")) else []:
        close_day(base, d[:-5])
    for d in sorted(os.listdir(os.path.join(base, "seals"))) if os.path.isdir(os.path.join(base, "seals")) else []:
        if len(d) == 15:
            seal_day(base, d[:-5])


def close_day(base, day):
    files = []
    raw = os.path.join(base, "raw")
    for t in sorted(os.listdir(raw)):
        dd = os.path.join(raw, t, day)
        for f in sorted(os.listdir(dd)) if os.path.isdir(dd) else []:
            p = os.path.join(dd, f)
            files.append({"path": os.path.relpath(p, base), "bytes": os.path.getsize(p)})
    mp = os.path.join(base, "manifests", f"{day}.jsonl")
    wjson(os.path.join(base, "days", f"{day}.json"),
          {"record": "tsb.p2.forward.day_close", "record_version": 1, "day": day, "files": files,
           "segments": sum(1 for f in files if f["path"].endswith(".jsonl.gz")),
           "bytes_total": sum(f["bytes"] for f in files), "manifest_sha256": sha(mp) if os.path.exists(mp) else None,
           "calendar": CAL})


def seal_day(base, day, result="PASS"):
    rp = os.path.join(base, "seals", f"{day}.report.json")
    wjson(rp, {"PASS": result == "PASS", "day": day, "verifier": "synthetic", "totals": {"unexplained": 0}})
    with open(os.path.join(base, "dataset.json")) as fh:
        ds = json.load(fh)
    wjson(os.path.join(base, "seals", f"{day}.json"),
          {"record": "tsb.p2.forward.day_seal", "record_version": 1, "day": day, "dataset_id": ds["dataset_id"],
           "result": result, "sealed_ms": 0, "calendar": CAL, "verifier": "synthetic", "report_sha256": sha(rp),
           "day_close_sha256": sha(os.path.join(base, "days", f"{day}.json")),
           "manifest_sha256": sha(os.path.join(base, "manifests", f"{day}.jsonl"))})


class Synth:
    """Configurable synthetic dataset. See ``default_spec`` for the knobs."""

    def __init__(self, base, spec):
        self.base, self.s = base, spec
        self.cad = spec.get("cadences", TEST_CAD)
        self.w = Writer(base, spec.get("gzip_level", 1))
        self.ctl_seq = {}

    # ------------------------------------------------------------------ helpers
    def rec(self, type_, obs_id, recv_ms, boot, *, symbol=None, tier=None, cadence=None, sample=None, ex=None, seq=None,
            payload=None, transport="ws", endpoint="collector", unchanged=False, cs=False, recover=None, avail=None,
            extra=None):
        r = {"schema": "tsb.p2.forward", "schema_version": 2, "obs_id": obs_id, "type": type_, "symbol": symbol,
             "tier": tier, "cadence_ms": cadence, "sample_ms": sample, "source": "binance_spot_public",
             "transport": transport, "endpoint": endpoint, "exchange_event_time_ms": ex, "exchange_seq": seq,
             "recv_ts_ns": recv_ms * 1_000_000 + 123, "queued_ts_ns": recv_ms * 1_000_000 + 999, "blk": 0,
             "observed_at_ms": recv_ms, "available_at_ms": recv_ms if avail is None else avail, "unchanged": unchanged,
             "clock_suspect": cs, "recoverability": recover, "collector_version": "synthetic-1.0", "boot_id": boot,
             "payload": payload}
        if extra:
            r.update(extra)
        return r

    def ctl(self, boot, kind, recv_ms, payload, obs_suffix=""):
        n = self.ctl_seq.get(boot, 0) + 1
        self.ctl_seq[boot] = n
        if kind == "lifecycle":
            oid = f"life|{boot}|{n}|{payload['event']}"
        elif kind == "health":
            oid = f"hlth|{boot}|{n}"
        else:
            oid = f"gap|{boot[:8]}|{n}|{obs_suffix}"
        rc = "IRREPLACEABLE_FORWARD_OBSERVATION" if kind == "gap" and not obs_suffix.startswith("candle") else (
            "RECOVERABLE_WHERE_ARCHIVE_AVAILABLE" if kind == "gap" else None)
        self.w.put(self.rec(kind, oid, recv_ms, boot, payload=payload, transport="internal", recover=rc,
                            symbol=payload.get("_sym") if isinstance(payload, dict) else None))

    def epochs(self):
        return self.s["epochs"]                     # [{effective_ms, tiers: {sym: tier}, stamp}]

    def epoch_at(self, t):
        cur = None
        for e in self.epochs():
            if e["effective_ms"] <= t:
                cur = e
        return cur

    def in_gap(self, stream, sym, t):
        for g in self.s.get("gaps", []):
            if g["stream"] == stream and g["symbol"] == sym and g["g0"] <= t <= g["g1"]:
                return g
        return None

    # ------------------------------------------------------------------ generate
    def generate(self):
        s, base = self.s, self.base
        os.makedirs(base, exist_ok=True)
        wjson(os.path.join(base, "dataset.json"),
              {"calendar": CAL, "collector_version": "synthetic-1.0", "created_ms": s["runs"][0]["ws"] - 60_000,
               "dataset_id": s.get("dataset_id", "synthetic-continuous"), "record": "tsb.p2.forward.dataset",
               "record_version": 1, "schema": "tsb.p2.forward", "schema_version": s.get("dataset_schema_version", 2)})
        ufiles = {}
        for e in self.epochs():
            boot8 = s["runs"][0]["boot"][:8]
            uid = f"uni|{e['stamp']}|tiers-v2"
            doc = {"universe_id": uid, "stamp": e["stamp"], "applied": True, "trusted": True, "rule_version": "tiers-v2",
                   "evaluated_ms": e["effective_ms"] - 1000}
            for k in (0, 1, 2):
                doc[f"tier{k}"] = sorted(x for x, tt in e["tiers"].items() if tt == k)
            rel = f"universe/universe-{e['stamp']}-{boot8}.json"
            wjson(os.path.join(base, rel), doc)
            ufiles[uid] = (rel, sha(os.path.join(base, rel)), doc)
            e["uid"] = uid
        self.ufiles = ufiles
        prev = None
        for i, R in enumerate(s["runs"]):
            self._run(R, prev, i)
            prev = R
        self.w.close()
        refresh_hashes(base)
        for d in s.get("close_days", []):
            close_day(base, d)
        for d in s.get("seal_days", []):
            seal_day(base, d)
        return self

    def _conns(self, ep):
        book = sorted(f"{x.lower()}@bookTicker" for x in ep["tiers"]) + ["!miniTicker@arr"]
        depth = sorted(f"{x.lower()}@depth{20 if t == 0 else 10}" for x, t in ep["tiers"].items())
        return {"conn0-book": book, "conn1-depth": depth}

    def _run(self, R, prev, idx):
        s, base, boot = self.s, self.base, R["boot"]
        W, P = R["ws"], R.get("stop")
        end = P if P is not None else s["span_end"]
        run_rec = {"record": "tsb.p2.forward.run", "record_version": 1, "schema": "tsb.p2.forward", "schema_version": 2,
                   "boot_id": boot, "created_ms": W - 5000, "mode": "continuous", "calendar": CAL,
                   "previous_run": ({"boot_id": prev["boot"]} if prev else None), "config": {},
                   "sampling_profile": {"cadence_ms": self.cad, "depth_levels": {"t0": 20, "t1": 10, "t2": 10}},
                   "semantics": {"stale_ms": {"book_t0": 120000, "book_t12_dead": 600000, "book_t12_suspect": 120000,
                                              "depth_by_tier": {"t0": 3 * self.cad["t0_depth"],
                                                                "t1": 3 * self.cad["t1_depth"],
                                                                "t2": 3 * self.cad["t2_depth"]},
                                              "market": 10000}}}
        rp = os.path.join(base, "runs", f"run-{boot}.json")
        wjson(rp, run_rec)
        cause = "first_run" if prev is None else ("clean_stop" if prev.get("stop") is not None else "crash_or_kill")
        wjson(os.path.join(base, "runs", f"downtime-{boot}.json"),
              {"record": "tsb.p2.forward.downtime", "record_version": 1, "boot_id": boot, "cause": cause,
               "calendar": CAL, "dataset_id": s.get("dataset_id", "synthetic-continuous"),
               "from_ms": prev.get("stop") if prev else None, "until_ms": W,
               "previous_run": ({"boot_id": prev["boot"], "clean_stop": prev.get("stop") is not None,
                                 "stop_requested_ms": prev.get("stop")} if prev else None),
               "run_record_file": f"runs/run-{boot}.json"})
        ep0 = self.epoch_at(W)
        L = lambda ev, t, **kw: self.ctl(boot, "lifecycle", t, {"event": ev, **kw})
        L("start", W - 3000, run_record_sha256=sha(rp))
        L("downtime", W, cause=cause)
        rel, dg, _ = self.ufiles[ep0["uid"]]
        L("universe_active", W, universe_id=ep0["uid"], file=rel, sha256=dg, effective_from_ms=W)
        L("ws_start", W, conns=self._conns(ep0))
        L("ws_connected", W + 50, conn="conn0-book")
        L("ws_connected", W + 60, conn="conn1-depth")
        # universe transitions inside this run
        for e in self.epochs():
            if W < e["effective_ms"] < end:
                rel, dg, _ = self.ufiles[e["uid"]]
                prev_ep = self.epoch_at(e["effective_ms"] - 1)
                added = sorted(set(e["tiers"]) - set(prev_ep["tiers"]))
                ret = [{"stream": f"{x.lower()}@bookTicker", "from": prev_ep["tiers"][x], "to": t}
                       for x, t in e["tiers"].items() if x in prev_ep["tiers"] and prev_ep["tiers"][x] != t]
                L("universe_transition", e["effective_ms"] + e.get("announce_delay_ms", 200),
                  effective_from_ms=e["effective_ms"], universe_id=e["uid"], file=rel, sha256=dg, added=added,
                  removed=sorted(set(prev_ep["tiers"]) - set(e["tiers"])), retiered=ret, conns=self._conns(e))
        # day checkpoints
        d0 = (W // 86_400_000 + 1) * 86_400_000
        while d0 < end:
            ep = self.epoch_at(d0)
            rel, dg, _ = self.ufiles[ep["uid"]]
            L("day_checkpoint", d0 + 1500, day_start_ms=d0, calendar=CAL, run_record_sha256=sha(rp),
              universe={"universe_id": ep["uid"], "file": rel, "sha256": dg, "effective_from_ms": ep["effective_ms"]},
              conns={c: {"up": True, "last_up_ms": W + 50, "streams": v} for c, v in self._conns(ep).items()})
            d0 += 86_400_000
        # reconnect events around ws_disconnect gaps
        for g in s.get("gaps", []):
            if W < g["g0"] < end and g.get("cause") == "ws_disconnect_reconnect":
                L("ws_disconnected", g["g0"] - 500, conn="conn0-book" if g["stream"] == "book" else "conn1-depth")
                L("ws_connected", g["g1"] + 100, conn="conn0-book" if g["stream"] == "book" else "conn1-depth")
        self._sampled(boot, W, end)
        self._market(boot, W, end)
        self._candles(boot, W, end)
        self._health_clock(boot, W, end)
        self._gaps(boot, W, end)
        if P is not None:
            L("stop", P, state="STOPPED")
            wjson(os.path.join(base, "control", f"stop-{boot[:8]}.json"),
                  {"boot_id": boot, "ws_start_ms": W, "stop_requested_ms": P, "state": "STOPPED", "exit_code": 0})

    def _sampled(self, boot, W, end):
        syms = sorted({x for e in self.epochs() for x in e["tiers"]})
        cs_win = self.s.get("clock_suspect_window")
        for kind in ("book", "depth"):
            for sym in syms:
                cads = sorted({self.cad[f"t{t}_{kind}"] for t in (0, 1, 2)})
                step = min(cads)
                b = (W // step + 1) * step
                last_seq = None
                while b < end:
                    ep = self.epoch_at(b)
                    tier = ep["tiers"].get(sym)
                    cad = self.cad[f"t{tier}_{kind}"] if tier is not None else None
                    if tier is None or b % cad or b < W + 2000 or self.in_gap(kind, sym, b):
                        b += step
                        continue
                    lag = 100 + (b // 1000 + len(sym)) % 700
                    obs = b - lag
                    m = mid(sym, obs)
                    spr = {0: 1.0, 1: 4.0, 2: 8.0}[tier] * 1e-4 * (1 + 0.3 * math.sin(obs / 7.7e5))
                    seq = obs // 100
                    unch = seq == last_seq
                    last_seq = seq
                    cs = bool(cs_win and cs_win[0] <= b <= cs_win[1])
                    if kind == "book":
                        p = {"u": seq, "s": sym, "b": f"{m * (1 - spr / 2):.8f}", "B": f"{1 + (obs % 977) / 100:.4f}",
                             "a": f"{m * (1 + spr / 2):.8f}", "A": f"{1 + (obs % 631) / 100:.4f}"}
                        oid = f"bt|{sym}|{seq}|c{cad}|t{b}"
                        self.w.put(self.rec("book", oid, obs, boot, symbol=sym, tier=tier, cadence=cad, sample=b, seq=seq,
                                            payload=p, endpoint=f"{sym.lower()}@bookTicker", unchanged=unch, cs=cs,
                                            recover="IRREPLACEABLE_FORWARD_OBSERVATION"))
                    else:
                        n = 20 if tier == 0 else 10
                        bids = [[f"{m * (1 - spr * (i + 0.5)):.8f}", f"{1 + ((obs // 1000 + i) % 13) / 4:.4f}"] for i in range(n)]
                        asks = [[f"{m * (1 + spr * (i + 0.5)):.8f}", f"{1 + ((obs // 1000 + 3 * i) % 11) / 4:.4f}"] for i in range(n)]
                        oid = f"dp{n}|{sym}|{seq}|c{cad}|t{b}"
                        self.w.put(self.rec("depth", oid, obs, boot, symbol=sym, tier=tier, cadence=cad, sample=b, seq=seq,
                                            payload={"lastUpdateId": seq, "bids": bids, "asks": asks},
                                            endpoint=f"{sym.lower()}@depth{n}", unchanged=unch, cs=cs,
                                            recover="IRREPLACEABLE_FORWARD_OBSERVATION", extra={"depth_levels": n}))
                    b += step

    def _market(self, boot, W, end):
        cad = self.cad["market"]
        b = (W // cad + 1) * cad
        while b < end:
            if not self.in_gap("market", "ALL", b):
                ep = self.epoch_at(b)
                comp, crecv = [], {}
                for sym in sorted(list(ep["tiers"]) + ["ZZZUSDT"]):
                    r = b - 200 - len(sym) * 10
                    comp.append({"e": "24hrMiniTicker", "E": r - 5, "s": sym, "c": f"{mid(sym, r):.8f}",
                                 "o": f"{mid(sym, r - 86_400_000):.8f}", "h": "0", "l": "0", "v": "1000",
                                 "q": f"{1e6 + len(sym) * 1000:.2f}"})
                    crecv[sym] = r
                newest = max(crecv.values())
                self.w.put(self.rec("market", f"mkt|t{b}", newest, boot, cadence=cad, sample=b, ex=newest - 5,
                                    payload=comp, endpoint="!miniTicker@arr", recover="IRREPLACEABLE_FORWARD_OBSERVATION",
                                    extra={"component_recv_ms": crecv, "startup_complete": b - W >= 60_000}))
            b += cad

    def _candles(self, boot, W, end):
        miss = {(c["symbol"], c["tf"], c["open_ms"]) for c in self.s.get("candle_misses", [])}
        syms = sorted({x for e in self.epochs() for x in e["tiers"]})
        for tf, L in TF.items():
            first_close = (W // L + 1) * L
            closes = [first_close - L] + list(range(first_close, end, L))     # catch-up candle + regular closes
            for B in closes:
                ep = self.epoch_at(max(B, W))
                for sym in syms:
                    if sym not in ep["tiers"]:
                        continue
                    o_ms = B - L
                    recv = max(B, W) + 10_000 + (len(sym) * 137) % 5000
                    if recv >= end:
                        continue
                    if (sym, tf, o_ms) in miss:
                        self.ctl(boot, "gap", recv, {"stream_key": f"candle|{tf}|{sym}", "stream": f"klines:{tf}",
                                                     "first_missing_ms": o_ms, "last_missing_ms": o_ms,
                                                     "missing_samples": 1, "duration_ms": L, "start_ms": o_ms,
                                                     "end_ms": o_ms + L, "cadence_ms": L, "cause": "candle_fetch_failed:500",
                                                     "causes": ["candle_fetch_failed:500"], "open_at_stop": False,
                                                     "_sym": sym},
                                 obs_suffix=f"candle|{tf}|{sym}|{o_ms}|{o_ms}|candle_fetch_failed:500")
                        continue
                    pts = [mid(sym, o_ms + i * (L // 16)) for i in range(16)] + [mid(sym, B - 1)]
                    vol = 100 + (o_ms // L + len(sym)) % 37 * 10
                    k = [o_ms, f"{pts[0]:.8f}", f"{max(pts):.8f}", f"{min(pts):.8f}", f"{pts[-1]:.8f}", f"{vol:.4f}",
                         B - 1, f"{vol * pts[-1]:.4f}", 100, "0", "0", "0"]
                    self.w.put(self.rec("candle", f"{sym}|{tf}|{o_ms}", recv, boot, symbol=sym, cadence=L, ex=B - 1,
                                        payload=k, transport="rest", endpoint=f"/api/v3/klines?interval={tf}",
                                        recover="RECOVERABLE_WHERE_ARCHIVE_AVAILABLE", avail=max(B, recv)))

    def _health_clock(self, boot, W, end):
        t = W + 1000
        while t < end:
            bad = sorted(f"{g['symbol'].lower()}@{'bookTicker' if g['stream'] == 'book' else 'depth10'}"
                         for g in self.s.get("gaps", []) if g["symbol"] != "ALL" and g["g0"] <= t <= g["g1"] + 1000)
            self.ctl(boot, "health", t, {"state": "DEGRADED" if bad else "HEALTHY", "reasons": [f"stream_gap:{x}" for x in bad],
                                         "streams_not_observing": bad})
            t += 60_000
        t = W + 2000
        cs_win = self.s.get("clock_suspect_window")
        while t < end:
            cs = bool(cs_win and cs_win[0] <= t <= cs_win[1])
            self.w.put(self.rec("clock", f"clk|{t + 3}", t, boot, ex=t + 3, transport="rest", endpoint="/api/v3/time",
                                payload={"serverTime": t + 3, "method": "min_rtt_of_3_midpoint_v1"}, cs=cs))
            t += self.cad["clock"]

    def _gaps(self, boot, W, end):
        for g in self.s.get("gaps", []):
            if not (W < g["g0"] < end):
                continue
            kind, sym = g["stream"], g["symbol"]
            if kind == "market":
                cad, key = self.cad["market"], "market|ALL"
            else:
                tier = self.epoch_at(g["g0"])["tiers"][sym]
                cad, key = self.cad[f"t{tier}_{kind}"], f"{kind}|{sym}"
            first = -(-g["g0"] // cad) * cad
            last = (g["g1"] // cad) * cad
            parts = []
            d0 = (first // 86_400_000 + 1) * 86_400_000
            if first < d0 <= last:
                parts.append((first, d0 - cad, True, d0 + 1000))
                parts.append((d0, last, False, last + cad + 300))
            else:
                parts.append((first, last, False, last + cad + 300))
            for a, b, split, recv in parts:
                cause = g.get("cause", "ws_disconnect_reconnect")
                p = {"stream_key": key, "stream": key, "first_missing_ms": a, "last_missing_ms": b,
                     "missing_samples": (b - a) // cad + 1, "duration_ms": b - a + cad, "start_ms": a, "end_ms": b + cad,
                     "cadence_ms": cad, "cause": cause, "causes": [cause], "open_at_stop": False}
                if split:
                    p["day_split"] = True
                if sym != "ALL":
                    p["_sym"] = sym
                self.ctl(boot, "gap", recv, p, obs_suffix=f"{key}|{a}|{b}|{cause}")


def default_spec(**over):
    """Two sealed days (D1, D2) + spillover; two runs with a clean stop/restart; a cross-midnight book gap (day split);
    a depth gap; a universe transition (add NEWUSDT, re-tier CCCUSDT 2->1); a missing candle; clock_suspect window."""
    D1, D2 = ms("2026-10-05T00:00:00Z"), ms("2026-10-06T00:00:00Z")
    t0 = {"BTCUSDT": 0, "ETHUSDT": 0, "AAAUSDT": 1, "BBBUSDT": 1, "CCCUSDT": 2, "DDDUSDT": 2, "EEEUSDT": 2}
    t1 = dict(t0, CCCUSDT=1, NEWUSDT=2)
    spec = {
        "dataset_id": "synthetic-continuous",
        "runs": [{"boot": "a1" * 16, "ws": D1 + 30_000, "stop": D1 + 20 * 3_600_000},
                 {"boot": "b2" * 16, "ws": D1 + 20 * 3_600_000 + 600_000, "stop": None}],
        "span_end": D2 + 86_400_000 + 3_600_000 + 600_000,
        "epochs": [{"effective_ms": D1, "stamp": "20261005T000000000000Z", "tiers": t0},
                   {"effective_ms": D2 + 6 * 3_600_000, "stamp": "20261006T055000000000Z", "tiers": t1,
                    "announce_delay_ms": 200}],
        "gaps": [{"stream": "book", "symbol": "DDDUSDT", "g0": D2 - 600_000, "g1": D2 + 300_000,
                  "cause": "ws_disconnect_reconnect"},
                 {"stream": "depth", "symbol": "AAAUSDT", "g0": D2 + 10 * 3_600_000, "g1": D2 + 10 * 3_600_000 + 1_800_000,
                  "cause": "stale_stream"}],
        "candle_misses": [{"symbol": "EEEUSDT", "tf": "15m", "open_ms": D2 + 12 * 3_600_000}],
        "clock_suspect_window": [D2 + 14 * 3_600_000, D2 + 14 * 3_600_000 + 1_200_000],
        "close_days": ["2026-10-05", "2026-10-06"],
        "seal_days": ["2026-10-05", "2026-10-06"],
    }
    spec.update(over)
    return spec
