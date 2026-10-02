"""Pre-G3 closure tests: R04 (universe reconstruction), F25 (fail-closed initial universe), F42 (sanity checks and
refresh policy), the pinned G3 acceptance spec and the controlled reconnect. Offline only (fake exchange)."""
import asyncio
import contextlib
import copy
import gzip
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from p2_forward import app as A, config as C, universe as U, guards as G
from tests.test_regression_g2r import mk, healthy_collector, stop_writer, lifes, drain
from tests.test_verify_independent import VI, segs_of, recertify, ENV, FakeResp

SYN = ["BTCUSDT", "ETHUSDT"] + [f"A{i:02d}USDT" for i in range(30)]


def exchange_info(extra=True):
    syms = [{"symbol": s, "status": "TRADING", "baseAsset": s[:-4], "quoteAsset": "USDT"} for s in SYN]
    if extra:
        syms += [{"symbol": "USDCUSDT", "status": "TRADING", "baseAsset": "USDC", "quoteAsset": "USDT"},
                 {"symbol": "BRKUSDT", "status": "BREAK", "baseAsset": "BRK", "quoteAsset": "USDT"},
                 {"symbol": "币安USDT", "status": "TRADING", "baseAsset": "币安", "quoteAsset": "USDT"},
                 {"symbol": "NOTKUSDT", "status": "TRADING", "baseAsset": "NOTK", "quoteAsset": "USDT"},
                 {"symbol": "BADUSDT", "status": "TRADING", "baseAsset": "BAD", "quoteAsset": "USDT"},
                 {"symbol": "ETHBTC", "status": "TRADING", "baseAsset": "ETH", "quoteAsset": "BTC"}]
    return {"symbols": syms}


def tickers():
    out = [{"symbol": s, "quoteVolume": str(9e9 - i * 1e8), "openPrice": "1", "lastPrice": str(1 + (i % 7) / 100)}
           for i, s in enumerate(SYN)]
    out += [{"symbol": "USDCUSDT", "quoteVolume": "9e9", "openPrice": "1", "lastPrice": "1"},
            {"symbol": "BRKUSDT", "quoteVolume": "5e8", "openPrice": "1", "lastPrice": "1"},
            {"symbol": "BADUSDT", "quoteVolume": "abc", "openPrice": "1", "lastPrice": "1"},
            {"symbol": "GHOSTUSDT", "quoteVolume": "1e8", "openPrice": "1", "lastPrice": "1"},
            {"symbol": "ETHBTC", "quoteVolume": "1", "openPrice": "1", "lastPrice": "1"}]
    return out


TEST_CFG = {"profile": "recommended", "tier1_min_quote_volume": 6.5e9, "tier1_max": 12, "tier2_top_volume": 4,
            "tier2_top_movers": 2, "tier2_max": 6, "universe_min_usdt_trading": 20, "universe_max_invalid_fraction": 0.05,
            "universe_min_ticker_coverage": 0.9}


def cfg_with(**over):
    c = {**C.DEFAULTS, **TEST_CFG, **over}
    C.validate(c)
    return c


# ------------------------------------------------------------------------------------------------ R04
class UniverseR04(unittest.TestCase):
    def test_every_candidate_has_inputs_reason_rank_tier(self):
        u = U.evaluate(cfg_with(), exchange_info(), tickers())
        by = {c["symbol"]: c for c in u["candidates"]}
        self.assertEqual(by["USDCUSDT"]["excluded_reason"], "stable_or_fiat_base")
        self.assertEqual(by["BRKUSDT"]["excluded_reason"], "status_BREAK")
        self.assertEqual(by["币安USDT"]["excluded_reason"], "non_ascii_or_non_alnum")
        self.assertEqual(by["NOTKUSDT"]["excluded_reason"], "no_ticker")
        self.assertEqual(by["BADUSDT"]["excluded_reason"], "invalid_ticker")
        self.assertEqual(by["GHOSTUSDT"]["excluded_reason"], "not_in_exchangeinfo_spot")
        self.assertNotIn("ETHBTC", by)                                   # not USDT-quoted: not a candidate
        self.assertEqual(by["BTCUSDT"]["tier"], 0)
        self.assertEqual(len(u["tier1"]) + len(u["tier2"]), 12)          # tier1_max cap
        self.assertEqual(len(u["tier2"]), 6)
        self.assertTrue(any(c["excluded_reason"] == "rank_cut" for c in u["candidates"]))
        self.assertTrue(any(c["excluded_reason"] == "below_min_quote_volume" for c in u["candidates"]))
        self.assertEqual(by["A00USDT"]["quote_volume_raw"], tickers()[2]["quoteVolume"])
        ranks = sorted(c["volume_rank"] for c in u["candidates"] if c["volume_rank"])
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))
        self.assertEqual(U.evaluate(cfg_with(), exchange_info(), list(reversed(tickers()))), u)   # deterministic

    def test_hysteresis_member_with_reason(self):
        cfg = cfg_with()
        prior = {"tier1": ["A20USDT"], "tier2": [], "universe_id": "uni|prior|tiers-v2"}
        u = U.evaluate(cfg, exchange_info(), tickers(), prior)
        c = [x for x in u["candidates"] if x["symbol"] == "A20USDT"][0]
        self.assertEqual(c["hysteresis_reason"], "prior_member:uni|prior|tiers-v2"); self.assertEqual(c["tier"], 1)
        self.assertIn("A20USDT", u["hysteresis_members"])


# ------------------------------------------------------------------------------------------------ F42
class SanityF42(unittest.TestCase):
    def check(self, ei, tk, needle, **over):
        ok, problems, _ = U.validate_inputs(cfg_with(**over), ei, tk)
        self.assertFalse(ok); self.assertTrue(any(needle in p for p in problems), problems)

    def test_malformed_missing_empty_duplicates_partial_invalid_inconsistent(self):
        ok, problems, stats = U.validate_inputs(cfg_with(), exchange_info(), tickers())
        self.assertTrue(ok, problems)
        self.check({"x": 1}, tickers(), "exchangeinfo_malformed")
        self.check(exchange_info(), {"x": 1}, "ticker_malformed")
        self.check({"symbols": []}, [], "empty_result")
        ei = exchange_info(); ei["symbols"].append(dict(ei["symbols"][3]))
        self.check(ei, tickers(), "duplicate_symbols")
        ei = exchange_info(); del ei["symbols"][4]["status"]
        self.check(ei, tickers(), "malformed_entries")
        self.check(exchange_info(), tickers()[:10], "ticker_coverage")              # suspiciously partial
        tk = tickers(); [t.update(quoteVolume="nan") for t in tk[:5]]
        self.check(exchange_info(), tk, "invalid_numeric_fraction")
        ei = exchange_info(); ei["symbols"][5]["baseAsset"] = "ZZZ"
        self.check(ei, tickers(), "symbol_quote_inconsistent")
        self.check(exchange_info(), tickers(), "too_few_usdt_trading", universe_min_usdt_trading=500)

    def test_refresh_policy_deterministic(self):
        prev, new = {"universe_id": "p"}, {"universe_id": "n"}
        self.assertEqual(U.refresh_decision(prev, new, []), (new, False, "accepted"))
        self.assertEqual(U.refresh_decision(prev, None, ["x"]), (prev, True, "kept_previous_degraded"))
        self.assertEqual(U.refresh_decision(None, None, ["x"]), (None, True, "fail_closed"))
        u = U.evaluate(cfg_with(), exchange_info(), tickers())
        moved = {**u, "tier1": [], "tier2": ["A29USDT"]}
        self.assertTrue(U.plausible_vs_prior(cfg_with(), moved, u))                 # >50 % membership change

    def test_refresh_failure_keeps_previous_and_degrades_until_success(self):
        async def go(d):
            c = healthy_collector(d)
            meta0 = c.universe_meta = {"universe_id": "uni|old|tiers-v2"}
            uni0 = c.universe
            with mock.patch.object(A.Collector, "fetch_universe", new=mock.AsyncMock(return_value=(None, ["ticker_coverage:0.4<0.95"]))):
                act = await c.refresh_universe()
            st = c.health_eval()
            kept = c.universe is uni0 and c.universe_meta is meta0
            good = U.evaluate(cfg_with(), exchange_info(), tickers())
            with mock.patch.object(A.Collector, "fetch_universe", new=mock.AsyncMock(return_value=(good, []))):
                act2 = await c.refresh_universe()
            return c, act, st, kept, act2
        with tempfile.TemporaryDirectory() as d:
            c, act, st, kept, act2 = asyncio.run(go(d))
            try:
                self.assertEqual(act, "kept_previous_degraded"); self.assertTrue(kept)
                self.assertEqual(st[0], "DEGRADED"); self.assertIn("universe_refresh_failed", st[1])
                self.assertEqual(act2, "accepted"); self.assertIsNone(c.universe_degraded)
                self.assertNotIn("universe_refresh_failed", c.health_eval()[1])
                self.assertTrue(any(json.load(open(os.path.join(d, "universe", f))).get("applied") is False
                                    for f in os.listdir(os.path.join(d, "universe"))))
            finally:
                stop_writer(c)


# ------------------------------------------------------------------------------------------------ fake exchange
class FakeWS2:
    U = [0]                                    # update IDs are global and monotonic across connections (as on Binance)

    def __init__(self, url):
        self.closed = False
        self.streams = [url.split("streams=")[1]]
        self.pending, self.t = [], time.time()
        self.next_book, self.next_depth, self.next_mini = self.t + 0.05, self.t + 0.3, self.t + 0.1

    async def __aenter__(self): return self
    async def __aexit__(self, *a): self.closed = True; return False

    async def send_str(self, s):
        m = json.loads(s); self.streams += m["params"]; self.pending.append({"result": None, "id": m["id"]})

    async def close(self): self.closed = True
    def __aiter__(self): return self

    def _m(self, stream, data):
        return mock.Mock(type=A.aiohttp.WSMsgType.TEXT, data=json.dumps({"stream": stream, "data": data}))

    async def __anext__(self):
        while True:
            if self.closed:
                raise StopAsyncIteration
            if self.pending:
                p = self.pending.pop(0)
                return p if not isinstance(p, dict) else mock.Mock(type=A.aiohttp.WSMsgType.TEXT, data=json.dumps(p))
            now = time.time()
            if now >= self.next_book:
                self.next_book += 0.25
                for s in self.streams:
                    if s.endswith("@bookTicker"):
                        self.U[0] += 1; self.pending.append(self._m(s, {"u": self.U[0], "s": s.split("@")[0].upper(), "b": "1", "a": "2"}))
            elif now >= self.next_depth:
                self.next_depth += 1.0
                for s in self.streams:
                    if "@depth" in s:
                        n = int(s.split("@depth")[1]); self.U[0] += 1
                        self.pending.append(self._m(s, {"lastUpdateId": self.U[0], "bids": [["1", "1"]] * n, "asks": [["2", "1"]] * n}))
            elif now >= self.next_mini:
                self.next_mini += 1.0
                if "!miniTicker@arr" in self.streams:
                    E = int(now * 1000) - 3
                    self.pending.append(self._m("!miniTicker@arr", [{"e": "24hrMiniTicker", "E": E, "s": s, "c": "1"} for s in SYN]))
            else:
                await asyncio.sleep(min(self.next_book, self.next_depth, self.next_mini) - now)


class FakeExchange:
    def __init__(self, fail_universe=0):
        self.ws, self.gets, self.fail_universe = [], [], fail_universe

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False

    def ws_connect(self, url, **kw):
        w = FakeWS2(url); self.ws.append(w); return w

    def get(self, url, params=None, timeout=None):
        self.gets.append(url)
        if url.endswith("/api/v3/time"):
            return FakeResp({"serverTime": int(time.time() * 1000) + 2})
        if url.endswith(("/exchangeInfo", "/ticker/24hr")):
            if self.fail_universe:
                if url.endswith("/ticker/24hr"):
                    self.fail_universe -= 1
                return FakeResp(tickers()[:5] if url.endswith("/ticker/24hr") else exchange_info())   # partial
            return FakeResp(exchange_info() if url.endswith("/exchangeInfo") else tickers())
        o = int(params["startTime"]); L = A.TF_MS[params["interval"]]
        return FakeResp([[o, "1", "1", "1", "1", "10", o + L - 1, "10", 5, "1", "1", "0"]])


def g3_test_cfg(d, runtime=16, reconnect_at=7, **over):
    return {**C.DEFAULTS, **TEST_CFG, "enabled": True, "max_runtime_s": runtime, "data_dir": d,
            "flush_interval_s": 0.2, "health_interval_s": 1.0, "health_record_interval_s": 2, "host_label": "e2e",
            "cadence_ms": {**C.DEFAULTS["cadence_ms"], "t2_book": 1000, "t2_depth": 2000, "t1_book": 2000,
                           "t1_depth": 4000, "market": 2000},
            "candle_timeframes": ["15m"], "disk_warn_free_gb": 0.02, "disk_stop_free_gb": 0.01,
            "reconnect_test_at_s": reconnect_at, "universe_retry_backoff_s": [0.05], **over}


def g3_test_spec(runtime=16, reconnect_at=7):
    s = copy.deepcopy(VI.G3_SPEC)
    s.update(name="g3-e2e-test-spec", max_runtime_s=runtime, runtime_tolerance_s=2, health_record_interval_s=2,
             candle_timeframes=["15m"])
    s["cadence_ms"].update(t2_book=1000, t2_depth=2000, t1_book=2000, t1_depth=4000, market=2000)
    s["universe"].update(min_quote_volume=6.5e9, tier1_max=12, tier2=[4, 2, 6])
    s["reconnect"].update(at_s=reconnect_at, recover_within_s=6, reconnect_within_s=6)
    s["resources"]["require_monitor"] = False
    s["health"]["startup_s"] = 3
    s["health"]["max_non_healthy_fraction"] = 0.5          # 16 s run: the reconnect is a large share of it
    return s


def run_g3_e2e(d, fail_universe=0, **over):
    cfg = g3_test_cfg(d, **over); C.validate(cfg)
    c = A.Collector(cfg); sess = FakeExchange(fail_universe); c.session_factory = lambda: sess
    with mock.patch.dict(os.environ, ENV), contextlib.redirect_stderr(io.StringIO()):
        code = asyncio.run(c.run())
    return c, code, sess


class G3EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = os.path.join(cls.tmp.name, "data"); os.makedirs(cls.base)
        cls.col, cls.code, cls.sess = run_g3_e2e(cls.base)
        cls.rep = VI.verify(cls.base, spec=g3_test_spec(), expect_image="sha256:e2e", expect_commit="e2etest")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def copy(self):
        d = tempfile.mkdtemp(dir=self.tmp.name); dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        return dst

    def test_recommended_profile_with_controlled_reconnect_passes_g3_spec(self):
        r = self.rep
        self.assertEqual(self.code, 0)
        self.assertTrue(r["PASS"] and r["acceptance"], json.dumps({"f": r["failures"], "ex": r["failure_examples"]}, indent=1, default=str))
        cr = r["controlled_reconnect"]
        self.assertGreater(cr["outage_s"], 0); self.assertGreaterEqual(cr["recovered_ms"], cr["reconnect_ms"])
        self.assertTrue(cr["collector_recovered_record"])
        u = r["universe"]
        self.assertEqual((u["tier1"], u["tier2"]), (6, 6))
        for reason in ("stable_or_fiat_base", "status_BREAK", "non_ascii_or_non_alnum", "no_ticker", "invalid_ticker",
                       "not_in_exchangeinfo_spot", "rank_cut", "below_min_quote_volume"):
            self.assertIn(reason, u["exclusions"])
        self.assertEqual(r["totals"]["unexplained"], 0)
        self.assertTrue(any(g["causes"] and set(g["causes"]) & {"ws_disconnect_reconnect", "awaiting_post_reconnect_data"}
                            for g in r["gaps"]))

    def test_universe_tamper_detected(self):
        d = self.copy()
        seg = segs_of(d, "universe")[0]
        def tamper(ls):
            for c in ls[0]["payload"]["candidates"]:
                if c["excluded_reason"] == "rank_cut":
                    c["excluded_reason"] = "below_min_quote_volume"; break
            return ls
        recertify(d, seg, tamper)
        f = VI.verify(d)["failures"]
        self.assertIn("UNIVERSE_RECORD_NE_FILE", f); self.assertIn("UNIVERSE_EXCLUSION_RECOMPUTE_MISMATCH", f)

    def test_pre_reconnect_value_after_reconnect_detected(self):
        d = self.copy()
        cr = self.rep["controlled_reconnect"]
        def stale(ls):
            for x in ls:
                if x["endpoint"] == "btcusdt@bookTicker" and x["sample_ms"] > cr["reconnect_ms"]:
                    t = cr["disconnect_ms"] - 50
                    x["recv_ts_ns"] = t * 1_000_000; x["observed_at_ms"] = x["available_at_ms"] = t
                    break
            return ls
        for seg in segs_of(d, "book"):
            recertify(d, seg, stale)
        r = VI.verify(d, spec=g3_test_spec())
        self.assertIn("PRE_RECONNECT_VALUE_PERSISTED", r["failures"])

    def test_g2r_spec_cannot_accept_g3_run_and_vice_versa(self):
        self.assertFalse(VI.verify(self.base, spec=VI.G2R_SPEC)["acceptance"])
        self.assertFalse(VI.verify(self.base, spec=VI.G3_SPEC)["acceptance"])     # pinned real G3 values


class StartupF25(unittest.TestCase):
    def test_transient_universe_failure_then_success(self):
        with tempfile.TemporaryDirectory() as d:
            c, code, sess = run_g3_e2e(d, fail_universe=2, runtime=4, reconnect_at=0)
            self.assertEqual(code, 0)
            att = [json.loads(l)["payload"] for s in segs_of(d, "lifecycle") for l in gzip.open(s, "rt")
                   if json.loads(l)["payload"].get("event") == "universe_attempt_failed"]
            self.assertEqual(len(att), 2); self.assertTrue(any("ticker_coverage" in p for p in att[0]["problems"]))

    def test_initial_universe_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            c, code, sess = run_g3_e2e(d, fail_universe=99, runtime=4, reconnect_at=0)
            self.assertEqual(code, A.EXIT_STARTUP); self.assertEqual(c.state, "FAILED")
            self.assertEqual(sess.ws, [])                                          # never opened a WebSocket
            ctl = os.listdir(os.path.join(d, "control"))
            self.assertTrue(any(f.startswith("fatal-") for f in ctl))
            fin = json.load(open(os.path.join(d, "control", [f for f in ctl if f.startswith("stop-")][0])))
            self.assertEqual((fin["state"], fin["exit_code"], fin["writer_finished"]), ("FAILED", 5, True))
            ev = [json.loads(l)["payload"]["event"] for s in segs_of(d, "lifecycle") for l in gzip.open(s, "rt")]
            self.assertEqual(ev.count("universe_attempt_failed"), 3); self.assertIn("startup_failed", ev)
            self.assertNotIn("ws_start", ev)
            self.assertFalse(VI.verify(d)["PASS"])                                 # can never pass verification
            h = json.load(open(os.path.join(d, "health", "collector_health.json")))
            self.assertEqual(h["state"], "FAILED")


class Misc(unittest.TestCase):
    def test_urgent_reserve(self):
        t = [0.0]; g = G.RateGuard(budget=100, clock=lambda: t[0], urgent_reserve=20)
        self.assertTrue(g.allow(80)[0]); self.assertEqual(g.allow(2), (False, "own_budget"))
        self.assertTrue(g.allow(2, urgent=True)[0])

    def test_catchup_is_one_budget_spread_round(self):
        async def go(d):
            c = mk(d, candle_timeframes=["15m", "1h", "4h", "1d"])
            seen = {}
            async def fake_round(jobs, window):
                seen["jobs"], seen["window"] = jobs, window
            c.candle_round_jobs = fake_round
            with mock.patch.object(A.Collector, "_sleep", new=lambda self, s: asyncio.sleep(0)):
                t = asyncio.create_task(c.candle_task()); await asyncio.sleep(0.02); c.stop_event.set(); await t
            await asyncio.gather(*c.candle_tasks, return_exceptions=True)
            return seen
        with tempfile.TemporaryDirectory() as d:
            seen = asyncio.run(go(d))
            self.assertEqual(len(seen["jobs"]), 4 * 2); self.assertEqual(seen["window"], 300.0)

    def test_config_one_connection_test_per_run(self):
        with self.assertRaises(C.ConfigError):
            C.validate({**C.DEFAULTS, "rotation_test_at_s": 10, "reconnect_test_at_s": 10})

    def test_pinned_g3_spec_values(self):
        s = VI.G3_SPEC
        self.assertEqual((s["max_runtime_s"], s["reconnect"]["at_s"], s["reconnect"]["conn"]), (21600, 10800, "conn0-book"))
        self.assertEqual(s["cadence_ms"], {"t0_book": 1000, "t0_depth": 1000, "t2_book": 2000, "t2_depth": 5000,
                                           "t1_book": 10000, "t1_depth": 60000, "market": 60000, "clock": 600000})
        self.assertEqual(s["depth_levels"], {"t0": 20, "t1": 10, "t2": 10})


if __name__ == "__main__":
    unittest.main()


class SpecPin(unittest.TestCase):
    def test_exported_spec_files_equal_pinned_constants(self):
        import pathlib
        d = pathlib.Path(__file__).resolve().parents[1] / "verifier" / "specs"
        self.assertEqual(json.loads((d / "g3-recommended-6h-v1.json").read_text()), json.loads(json.dumps(VI.G3_SPEC)))
        self.assertEqual(json.loads((d / "g2r-tier0-2h-v1.json").read_text()), json.loads(json.dumps(VI.G2R_SPEC)))
