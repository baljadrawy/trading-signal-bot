"""Independent verifier tests + offline end-to-end run (P2-E1 G2-Repeat; F26 / F27 / F52 / F53 and the whole pipeline).

The end-to-end test runs the REAL Collector.run() for ~8 s against a fake in-process Binance session (no network),
then judges the output ONLY with verifier/verify_independent.py. Mutation tests re-certify modified copies
(new SHA-256 / sidecar / idx / manifest) so each semantic check is exercised in isolation from checksum checks.
"""
import ast
import asyncio
import contextlib
import gzip
import importlib.util
import io
import json
import os
import pathlib
import shutil
import tempfile
import time
import unittest
from unittest import mock

from p2_forward import app as A, config as C

ROOT = pathlib.Path(__file__).resolve().parents[1]
VPATH = ROOT / "verifier" / "verify_independent.py"
_spec = importlib.util.spec_from_file_location("verify_independent", VPATH)
VI = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(VI)


# ---------------------------------------------------------------------------------------------- fake Binance session
class FakeWS:
    def __init__(self, url):
        self.closed = False
        self.streams = [url.split("streams=")[1]]
        self.pending = []
        self.u = 0
        now = time.time()
        self.next = {"book": now + 0.02, "depth": now + 0.3, "mini": now + 0.1}

    async def __aenter__(self): return self
    async def __aexit__(self, *a): self.closed = True; return False

    async def send_str(self, s):
        m = json.loads(s)
        self.streams += m["params"]
        self.pending.append({"result": None, "id": m["id"]})

    async def close(self): self.closed = True
    def __aiter__(self): return self

    async def __anext__(self):
        while True:
            if self.closed:
                raise StopAsyncIteration
            if self.pending:
                return mock.Mock(type=A.aiohttp.WSMsgType.TEXT, data=json.dumps(self.pending.pop(0)))
            k = min(self.next, key=self.next.get)
            wait = self.next[k] - time.time()
            if wait > 0:
                await asyncio.sleep(min(wait, 0.05)); continue
            self.u += 1
            if k == "book":
                self.next[k] += 0.05
                subs = [s for s in self.streams if s.endswith("@bookTicker")]
                if subs:
                    s = subs[self.u % len(subs)]
                    return self._m(s, {"u": self.u, "s": s.split("@")[0].upper(), "b": "1", "B": "1", "a": "2", "A": "1"})
            elif k == "depth":
                self.next[k] += 0.5
                subs = [s for s in self.streams if "@depth" in s]
                if subs:
                    s = subs[self.u % len(subs)]
                    return self._m(s, {"lastUpdateId": self.u, "bids": [["1", "1"]] * 5, "asks": [["2", "1"]] * 5})
            else:
                self.next[k] += 1.0
                if "!miniTicker@arr" in self.streams:
                    E = int(time.time() * 1000) - 3
                    return self._m("!miniTicker@arr", [{"e": "24hrMiniTicker", "E": E, "s": s, "c": "1"} for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")])

    def _m(self, stream, data):
        return mock.Mock(type=A.aiohttp.WSMsgType.TEXT, data=json.dumps({"stream": stream, "data": data}))


class FakeResp:
    def __init__(self, body): self.status, self.headers, self._b = 200, {"x-mbx-used-weight-1m": "3"}, json.dumps(body).encode()
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def read(self): return self._b


class FakeSession:
    def __init__(self): self.ws, self.gets = [], []
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    def ws_connect(self, url, **kw):
        w = FakeWS(url); self.ws.append(w); return w

    def get(self, url, params=None, timeout=None):
        self.gets.append(url)
        if url.endswith("/api/v3/time"):
            return FakeResp({"serverTime": int(time.time() * 1000) + 2})
        o = int(params["startTime"]); L = A.TF_MS[params["interval"]]
        return FakeResp([[o, "1", "1", "1", "1", "10", o + L - 1, "10", 5, "1", "1", "0"]])


ENV = {"P2F_GIT_COMMIT": "e2etest", "P2F_IMAGE_TAG": "tsb-p2-forward:e2e", "P2F_BUILD_TIME": "2026-10-02T00:00:00Z",
       "P2F_IMAGE_ID": "sha256:e2e"}


def run_e2e(d, runtime=8, **over):
    cfg = {**C.DEFAULTS, "enabled": True, "profile": "tier0_only", "max_runtime_s": runtime, "data_dir": d,
           "flush_interval_s": 0.2, "health_interval_s": 1.0, "health_record_interval_s": 2, "host_label": "e2e",
           "cadence_ms": {**C.DEFAULTS["cadence_ms"], "market": 2000}, "candle_timeframes": ["15m"],
           # test-only disk thresholds: the suite also runs inside the image on a 512 MB tmpfs, where the production
           # 60 GB floor would (correctly) trigger DISK_HARD_STOP
           "disk_warn_free_gb": 0.02, "disk_stop_free_gb": 0.01, **over}
    C.validate(cfg)
    c = A.Collector(cfg); sess = FakeSession(); c.session_factory = lambda: sess
    with mock.patch.dict(os.environ, ENV), contextlib.redirect_stderr(io.StringIO()):
        code = asyncio.run(c.run())
    return c, code, sess


# ---------------------------------------------------------------------------------------------- re-certification helper
def segs_of(base, typ):
    return sorted(pathlib.Path(base, "raw", typ).rglob("*.jsonl.gz"))


def recertify(base, seg, transform):
    seg = pathlib.Path(seg)
    lines = [json.loads(l) for l in gzip.open(seg, "rt")]
    lines = transform(lines)
    data = gzip.compress("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in lines).encode(), mtime=0)
    digest = VI.hashlib.sha256(data).hexdigest()
    idx = pathlib.Path(str(seg)[:-9] + ".idx"); side = pathlib.Path(str(seg) + ".sha256")
    for p in (seg, idx, side):
        os.chmod(p, 0o644)
    seg.write_bytes(data); side.write_text(f"{digest}  {seg.name}\n")
    blks = {}
    for r in lines:                                               # one idx line per block, durable after its records
        b = r.get("blk", 0); n, t = blks.get(b, (0, 0)); blks[b] = (n + 1, max(t, r.get("queued_ts_ns") or 0))
    idx.write_text("".join(json.dumps({"blk": b, "end_offset": len(data), "records": n, "durable_ts_ns": t + 1}) + "\n"
                           for b, (n, t) in sorted(blks.items())))
    for p in (seg, idx, side):
        os.chmod(p, 0o444)
    rel = str(seg.relative_to(base))
    for mf in pathlib.Path(base, "manifests").glob("*.jsonl"):
        out = []
        for l in mf.read_text().splitlines():
            e = json.loads(l)
            if e["segment"] == rel:
                e.update(sha256=digest, records=len(lines), bytes=len(data))
            out.append(json.dumps(e, sort_keys=True))
        mf.write_text("\n".join(out) + "\n")


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = os.path.join(cls.tmp.name, "data")
        os.makedirs(cls.base)
        cls.col, cls.code, cls.sess = run_e2e(cls.base)
        cls.rep = VI.verify(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def copy(self):
        d = tempfile.mkdtemp(dir=self.tmp.name)
        dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        return dst

    def test_e2e_run_passes_independent_verifier(self):
        r = self.rep
        self.assertEqual(self.code, 0)
        self.assertTrue(r["PASS"], json.dumps({k: r[k] for k in ("failures", "failure_examples")}, indent=1))
        self.assertEqual(r["totals"]["unexplained"], 0)
        self.assertEqual(set(r["coverage"]), {"btcusdt@bookTicker", "btcusdt@depth20", "ethusdt@bookTicker",
                                              "ethusdt@depth20", "!miniTicker@arr"})
        for name, c in r["coverage"].items():
            self.assertGreater(c["persisted"], 0, name)
        self.assertIn("HEALTHY", r["health"]["states"])
        h = json.load(open(os.path.join(self.base, "health", "collector_health.json")))
        self.assertEqual(h["state"], "STOPPED")
        self.assertEqual(r["window"]["stop_reason"], "max_runtime")
        self.assertFalse(self.col.candle_tasks)                                  # F7: nothing left running
        self.assertTrue(all(w.closed for w in self.sess.ws))
        self.assertEqual(sorted(os.listdir(os.path.join(self.base, "runs")))[0][:4], "run-")

    def test_absent_stream_fails(self):
        d = self.copy()
        for seg in segs_of(d, "depth"):
            recertify(d, seg, lambda ls: [x for x in ls if x["symbol"] != "ETHUSDT"])
        r = VI.verify(d)
        self.assertFalse(r["PASS"]); self.assertIn("ABSENT_STREAM", r["failures"])

    def test_full_window_missing_first_and_last_detected(self):
        d = self.copy()
        segs = segs_of(d, "book")
        allb = sorted((x["sample_ms"], str(s)) for s in segs for x in (json.loads(l) for l in gzip.open(s, "rt"))
                      if x["symbol"] == "BTCUSDT")
        first, last = allb[0][0], allb[-1][0]
        for s in segs:
            recertify(d, s, lambda ls: [x for x in ls if not (x["symbol"] == "BTCUSDT" and x["sample_ms"] in (first, last))])
        r = VI.verify(d)
        self.assertFalse(r["PASS"])
        ex = " ".join(r["failure_examples"].get("UNEXPLAINED_MISS", []))
        self.assertIn(f"btcusdt@bookTicker@{first}", ex); self.assertIn(f"btcusdt@bookTicker@{last}", ex)

    def test_middle_hole_unexplained(self):
        d = self.copy()
        seg = segs_of(d, "depth")[0]
        ms = sorted(json.loads(l)["sample_ms"] for l in gzip.open(seg, "rt") if json.loads(l)["symbol"] == "ETHUSDT")
        mid = ms[len(ms) // 2]
        recertify(d, seg, lambda ls: [x for x in ls if not (x["symbol"] == "ETHUSDT" and x["sample_ms"] == mid)])
        r = VI.verify(d)
        self.assertEqual(r["failures"].get("UNEXPLAINED_MISS"), 1)

    def test_false_gap_and_gap_seq_reuse(self):
        d = self.copy()
        seg = segs_of(d, "depth")[0]
        ms = sorted(json.loads(l)["sample_ms"] for l in gzip.open(seg, "rt") if json.loads(l)["symbol"] == "BTCUSDT")
        life = segs_of(d, "lifecycle")[0]
        boot = json.loads(gzip.open(life, "rt").readline())["boot_id"]
        def add(ls):
            base = dict(ls[0])
            out = list(ls)
            for seq in (9001, 9001):
                p = {"stream_key": "depth|BTCUSDT", "stream": "btcusdt@depth20", "first_missing_ms": ms[2],
                     "last_missing_ms": ms[2], "missing_samples": 1, "cadence_ms": 1000, "duration_ms": 1000,
                     "cause": "stale_stream", "causes": ["stale_stream"], "open_at_stop": False}
                out.append({**base, "type": "gap", "obs_id": f"gap|{boot[:8]}|{seq}|depth|BTCUSDT|{ms[2]}|{ms[2]}|stale_stream",
                            "payload": p, "symbol": "BTCUSDT", "cadence_ms": 1000, "recoverability": VI.IRR})
            return out
        recertify(d, life, add)
        r = VI.verify(d)
        self.assertIn("FALSE_GAP", r["failures"]); self.assertIn("GAP_SEQ_REUSED", r["failures"])

    def test_candle_idempotent_vs_conflicting(self):
        d = self.copy()
        life = segs_of(d, "lifecycle")[0]
        first = json.loads(gzip.open(life, "rt").readline())
        o = (first["observed_at_ms"] // 900_000) * 900_000 - 900_000
        k = [o, "1", "1", "1", "1", "10", o + 899_999, "10", 5, "1", "1", "0"]
        cand = {**first, "type": "candle", "obs_id": f"BTCUSDT|15m|{o}", "symbol": "BTCUSDT", "payload": k,
                "endpoint": "/api/v3/klines?interval=15m", "transport": "rest", "exchange_event_time_ms": o + 899_999,
                "cadence_ms": 900_000, "recoverability": VI.REC}
        cand["available_at_ms"] = max(o + 900_000, cand["observed_at_ms"])
        recertify(d, life, lambda ls: ls + [cand, dict(cand)])
        r = VI.verify(d)
        self.assertTrue(r["PASS"], r["failures"]); self.assertEqual(r["idempotent_duplicates"], 1)
        d2 = self.copy()
        life2 = segs_of(d2, "lifecycle")[0]
        recertify(d2, life2, lambda ls: ls + [cand, {**cand, "payload": k[:4] + ["2"] + k[5:]}])
        self.assertIn("CONFLICTING_DUPLICATE", VI.verify(d2)["failures"])

    def test_observed_after_sample_detected(self):
        d = self.copy()
        seg = segs_of(d, "book")[0]
        def bump(ls):
            ls[5] = {**ls[5], "recv_ts_ns": ls[5]["sample_ms"] * 1_000_000 + 1}
            ls[5]["observed_at_ms"] = ls[5]["recv_ts_ns"] // 1_000_000; ls[5]["available_at_ms"] = ls[5]["observed_at_ms"]
            return ls
        recertify(d, seg, bump)
        self.assertIn("OBSERVED_AFTER_SAMPLE", VI.verify(d)["failures"])

    def test_depth_levels_checked(self):
        d = self.copy()
        seg = segs_of(d, "depth")[0]
        recertify(d, seg, lambda ls: [{k: v for k, v in x.items() if k != "depth_levels"} if i == 3 else x for i, x in enumerate(ls)])
        self.assertIn("DEPTH_LEVELS_MISSING_OR_WRONG", VI.verify(d)["failures"])

    def test_checksum_tamper_detected(self):
        d = self.copy()
        seg = segs_of(d, "book")[0]
        os.chmod(seg, 0o644); seg.write_bytes(gzip.compress(b"{}\n")); os.chmod(seg, 0o444)
        f = VI.verify(d)["failures"]
        self.assertIn("CHECKSUM_SIDECAR_MISMATCH", f); self.assertIn("CHECKSUM_MANIFEST_MISMATCH", f)

    def test_provenance_unknown_fails(self):
        d = tempfile.mkdtemp(dir=self.tmp.name)
        with mock.patch.dict(os.environ, {k: "" for k in ENV}):
            cfg = {**C.DEFAULTS, "enabled": True, "max_runtime_s": 3, "data_dir": d, "flush_interval_s": 0.2,
                   "disk_warn_free_gb": 0.02, "disk_stop_free_gb": 0.01,
                   "health_interval_s": 1.0, "health_record_interval_s": 2, "candle_timeframes": []}
            c = A.Collector(cfg); c.session_factory = FakeSession
            with contextlib.redirect_stderr(io.StringIO()):
                asyncio.run(c.run())
        self.assertIn("PROVENANCE_UNKNOWN", VI.verify(d)["failures"])

    def test_verifier_has_no_collector_imports(self):
        tree = ast.parse(VPATH.read_text())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0]); self.assertEqual(n.level, 0)
        self.assertNotIn("p2_forward", mods)
        self.assertLessEqual(mods, {"__future__", "argparse", "bisect", "collections", "gzip", "hashlib", "json", "os", "stat", "sys"})


if __name__ == "__main__":
    unittest.main()
