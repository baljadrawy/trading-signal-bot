"""Optional live-health views (healthview.py): integrity/coverage split and tiered coverage severity.

Both are OFF by default. These tests prove (a) flag-off output is byte-identical (the view IS the health dict, the
config hash and run-record config do not change), (b) the flag-on behaviour, and (c) the safety cases that must stay
DEGRADED. The `health` raw records keep the unfiltered state in every case."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from p2_forward import app as A, config as C, healthview as HV, procwatch, universe as U
from tests.test_regression_g2r import book, capture, depth, healthy_collector, mini, stop_writer

UNI = {**U.tier0_only(C.DEFAULTS), "tier1": ["ADAUSDT"], "tier2": ["SOLUSDT"]}
# Synthetic stream names for the pure policy tests (the policy only sees names and the stream table).
T1D, T1B, T2D, T2B, T0D, MARKET = "ada-t1-depth", "ada-t1-book", "sol-t2-depth", "sol-t2-book", "eth-t0-depth", "market"
ON = {"health_state_split": True, "health_coverage_tiering": True}


def info_table(over=None):
    base = {T1D: {"tier": 1, "kind": "depth", "last_ms": None, "stale_ms": 180_000, "gap_first_ms": None},
            T1B: {"tier": 1, "kind": "book", "last_ms": None, "stale_ms": 600_000, "gap_first_ms": None},
            T2D: {"tier": 2, "kind": "depth", "last_ms": None, "stale_ms": 15_000, "gap_first_ms": None},
            T2B: {"tier": 2, "kind": "book", "last_ms": None, "stale_ms": 600_000, "gap_first_ms": None},
            T0D: {"tier": 0, "kind": "depth", "last_ms": None, "stale_ms": 2000, "gap_first_ms": None},
            MARKET: {"tier": None, "kind": "market", "last_ms": None, "stale_ms": 10_000, "gap_first_ms": None}}
    for k, v in (over or {}).items():
        base[k] = {**base[k], **v}
    return base.get


def stream(c, tier, kind, symbol):
    """Name of the collector's own stream for (tier, kind, symbol)."""
    return next(t.name for t in c.tracks.values() if (t.tier, t.kind, t.symbol) == (tier, kind, symbol))


def policy(k=2, t=120):
    return HV.CoveragePolicy(k, t)


M0 = 10_000_000


class ConfigKeys(unittest.TestCase):
    def test_optional_keys_are_off_and_not_in_defaults(self):
        for k in HV_KEYS:
            self.assertNotIn(k, C.DEFAULTS)                      # absent from the effective config => same hash
        self.assertIs(C.opt({}, "health_state_split"), False)
        self.assertIs(C.opt({}, "health_coverage_tiering"), False)
        self.assertEqual((C.opt({}, "health_coverage_max_streams"), C.opt({}, "health_coverage_max_age_s")), (2, 120))

    def test_load_absent_or_explicit_default_is_identical(self):
        with tempfile.TemporaryDirectory() as d:
            p0, p1, p2 = (os.path.join(d, f"c{i}.json") for i in range(3))
            json.dump({}, open(p0, "w"))
            json.dump({k: C.OPTIONAL_DEFAULTS[k] for k in HV_KEYS}, open(p1, "w"))
            json.dump({"health_coverage_tiering": True}, open(p2, "w"))
            c0, c1, c2 = C.load(p0), C.load(p1), C.load(p2)
            self.assertEqual(c0, dict(C.DEFAULTS))
            self.assertEqual(c0, c1)
            self.assertEqual(C.config_hash(c0), C.config_hash(c1))
            self.assertEqual(C.config_hash(c0), C.config_hash(dict(C.DEFAULTS)))
            self.assertNotEqual(C.config_hash(c0), C.config_hash(c2))
            self.assertIs(c2["health_coverage_tiering"], True)

    def test_validation(self):
        base = {**C.DEFAULTS, "enabled": True, "max_runtime_s": 60}
        C.validate({**base, **ON, "health_coverage_max_streams": 3, "health_coverage_max_age_s": 300})
        for bad in ({"health_state_split": "yes"}, {"health_coverage_tiering": 1}, {"health_coverage_max_streams": 1},
                    {"health_coverage_max_streams": 21}, {"health_coverage_max_streams": True},
                    {"health_coverage_max_age_s": 5}, {"health_coverage_max_age_s": 601},
                    {"health_coverage_max_age_s": 60.5}):
            with self.assertRaises(C.ConfigError, msg=bad):
                C.validate({**base, **bad})
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json"); json.dump({"health_coverage_tierng": True}, open(p, "w"))
            with self.assertRaises(C.ConfigError):
                C.load(p)                                         # a typo is still an unknown key


HV_KEYS = sorted(C.OPTIONAL_DEFAULTS)


class Classification(unittest.TestCase):
    def test_known_reasons(self):
        integ = ["writer_dead", "writer_stale", "writer_not_durable", "certifier_dead", "certifier_not_ready",
                 "certifier_stale", "certifier_scan_error", "certifier_backlog", "certification_failed",
                 "certifier_restarted_10min", "write_errors", "writer_rejected_records", "disk_hard_stop", "seq_reset",
                 "segments_quarantined", "emit_failed", "queue_drops", "incident:conn_outage:conn0-book",
                 "incident:quarantine"]
        cov = [f"stale:{T1D}", f"gap_open:{T1D}:stale_stream", f"gap_short:{T0D}:conn_data_stale",
               "conn_not_data_live:conn1-depth", f"awaiting_post_reconnect:{T1D}", f"not_ready:{T1D}",
               f"stream_failed:{T1D}:FAILED", "not_acked:a,b", "expected_ne_observing", f"coverage_clearing:{T1D}"]
        ops = ["task_no_beat:sampler", "task_stale:clock", "banned_418", "clock_unknown", "clock_stale",
               "clock_critical", "handler_exceptions_10min", "task_failed_10min", "wall_clock_step_10min",
               "universe_refresh_failed"]
        for r in integ:
            self.assertEqual(HV.classify(r), "integrity", r)
        for r in cov:
            self.assertEqual(HV.classify(r), "coverage", r)
        for r in ops:
            self.assertEqual(HV.classify(r), "operational", r)
        self.assertEqual(HV.classify("some_future_reason"), "integrity")      # fail closed

    def test_split_states(self):
        self.assertEqual(HV.split_states([], []), ("OK", "OK"))
        self.assertEqual(HV.split_states([f"stale:{T1D}"], []), ("OK", "DEGRADED"))
        self.assertEqual(HV.split_states(["writer_stale", f"stale:{T1D}"], []), ("DEGRADED", "DEGRADED"))
        self.assertEqual(HV.split_states(["clock_stale"], []), ("OK", "OK"))
        self.assertEqual(HV.split_states([], ["certifier_not_ready", f"not_ready:{T1D}"]), ("STARTING", "STARTING"))
        self.assertEqual(HV.split_states([], [], duplicates_dropped=3), ("WARNING", "OK"))
        self.assertEqual(HV.split_states(["emit_failed"], [], duplicates_dropped=3), ("DEGRADED", "OK"))


class PolicyTolerates(unittest.TestCase):
    def test_single_quiet_tier1_depth_is_healthy_with_warning(self):
        p = policy()
        hard = [f"stale:{T1D}", f"gap_short:{T1D}:stale_stream"]
        warn = ["malformed:1"]
        r = p.apply("DEGRADED", hard, [], warn, M0, info_table({T1D: {"last_ms": M0 - 200_000}}))
        self.assertEqual(r["state"], "HEALTHY")
        self.assertEqual(r["reasons"], [])
        self.assertEqual(r["warnings"][:2], ["malformed:1", "coverage:streams_stale:1"])
        self.assertIn(f"coverage_tolerated:stale:{T1D}", r["warnings"])
        self.assertEqual(r["coverage_state"], "WARNING")
        self.assertEqual(r["detail"]["raw_state"], "DEGRADED"); self.assertTrue(r["detail"]["tolerated"])
        self.assertEqual((hard, warn), ([f"stale:{T1D}", f"gap_short:{T1D}:stale_stream"], ["malformed:1"]))  # no mutation

    def test_tier2_book_and_gap_open_under_t(self):
        p = policy()
        r = p.apply("DEGRADED", [f"gap_open:{T2B}:stale_stream"], [], [], M0,
                    info_table({T2B: {"gap_first_ms": M0 - 60_000}}))
        self.assertEqual(r["state"], "HEALTHY")

    def test_startup_reasons_still_starting(self):
        r = policy().apply("DEGRADED", [f"stale:{T1D}"], ["clock_unknown"], [], M0, info_table())
        self.assertEqual(r["state"], "STARTING")

    def test_k_is_configurable(self):
        hard = [f"stale:{T1D}", f"stale:{T2B}"]
        self.assertEqual(policy(k=2).apply("DEGRADED", hard, [], [], M0, info_table())["state"], "DEGRADED")
        r = policy(k=3).apply("DEGRADED", hard, [], [], M0, info_table())
        self.assertEqual(r["state"], "HEALTHY"); self.assertIn("coverage:streams_stale:2", r["warnings"])


class PolicyStaysDegraded(unittest.TestCase):
    def deg(self, hard, info=None, p=None, m=M0):
        r = (p or policy()).apply("DEGRADED", hard, [], [], m, info or info_table())
        self.assertEqual(r["state"], "DEGRADED", hard)
        self.assertEqual(r["reasons"][:len(hard)], hard)                    # every original reason kept, in order
        self.assertEqual(r["coverage_state"], "DEGRADED" if any(HV.classify(x) == "coverage" for x in hard) else "OK")
        self.assertFalse(r["detail"]["tolerated"])
        return r

    def test_tier0_market_unknown(self):
        self.deg([f"stale:{T0D}"])
        self.deg([f"gap_short:{T0D}:stale_stream"])
        self.deg([f"stale:{MARKET}"])
        self.deg(["stale:no-such-stream"])

    def test_other_gap_causes(self):
        for cause in ("conn_data_stale", "ws_disconnect_reconnect", "sampler_stall", "backpressure_or_rejected",
                      "awaiting_post_reconnect_data", "disk_hard_stop"):
            self.deg([f"gap_short:{T1D}:{cause}"])

    def test_age_at_or_beyond_t(self):
        self.deg([f"gap_open:{T1D}:stale_stream"], info_table({T1D: {"gap_first_ms": M0 - 120_000}}))
        self.deg([f"stale:{T1D}"], info_table({T1D: {"last_ms": M0 - 180_000 - 120_000}}))

    def test_too_many_streams(self):
        self.deg([f"stale:{T1D}", f"stale:{T2B}"])

    def test_connection_and_stream_state_reasons(self):
        for extra in ("conn_not_data_live:conn1-depth", f"awaiting_post_reconnect:{T1D}", f"not_ready:{T2B}",
                      f"stream_failed:{T1D}:FAILED", "not_acked:x", "expected_ne_observing"):
            self.deg([f"stale:{T1D}", extra])

    def test_integrity_and_operational_reasons(self):
        for extra in ("writer_stale", "writer_not_durable", "certifier_backlog", "write_errors", "segments_quarantined",
                      "disk_hard_stop", "queue_drops", "incident:conn_outage:conn0-book", "seq_reset", "clock_stale",
                      "task_stale:sampler", "handler_exceptions_10min", "universe_refresh_failed", "a_new_reason"):
            self.deg([f"stale:{T1D}", extra])
            self.deg([extra])

    def test_pass_through_states(self):
        p = policy()
        for st in ("DEGRADED_DISK", "BANNED_418", "STOPPING", "STOPPED", "STOPPED_INCOMPLETE", "FAILED"):
            r = p.apply(st, [f"stale:{T1D}"], [], [], M0, info_table())
            self.assertEqual((r["state"], r["reasons"]), (st, [f"stale:{T1D}"]))
        r = p.apply("STARTING", [], ["not_started"], [], M0, info_table())
        self.assertEqual((r["state"], r["coverage_state"]), ("STARTING", None))
        self.assertEqual(p.streams, {})                                   # pass-through never touches episodes


class Hysteresis(unittest.TestCase):
    def test_warning_clears_after_two_clean_evaluations(self):
        p, it = policy(), info_table()
        self.assertEqual(p.apply("DEGRADED", [f"stale:{T1D}"], [], [], M0, it)["state"], "HEALTHY")
        r1 = p.apply("HEALTHY", [], [], [], M0 + 10_000, it)
        self.assertEqual((r1["state"], r1["coverage_state"]), ("HEALTHY", "WARNING"))
        self.assertIn("coverage:streams_stale:1", r1["warnings"])
        r2 = p.apply("HEALTHY", [], [], [], M0 + 20_000, it)
        self.assertEqual((r2["state"], r2["coverage_state"], r2["warnings"]), ("HEALTHY", "OK", []))
        self.assertEqual(p.streams, {})

    def test_flapping_stream_keeps_its_episode_age(self):
        p, it = policy(), info_table()
        m = M0
        for i in range(12):                                   # stale / clean / stale ... every 10 s, never 2 clean
            st = p.apply("DEGRADED", [f"stale:{T1D}"], [], [], m, it)["state"] if i % 2 == 0 else \
                p.apply("HEALTHY", [], [], [], m, it)["state"]
            self.assertEqual(st, "HEALTHY", i)
            m += 10_000
        self.assertEqual(p.streams[T1D]["since_ms"], M0)
        r = p.apply("DEGRADED", [f"stale:{T1D}"], [], [], M0 + 120_000, it)
        self.assertEqual(r["state"], "DEGRADED")              # 120 s since the episode began: T reached

    def test_episode_age_reaches_t(self):
        p, it = policy(), info_table()
        self.assertEqual(p.apply("DEGRADED", [f"stale:{T1D}"], [], [], M0, it)["state"], "HEALTHY")
        self.assertEqual(p.apply("DEGRADED", [f"stale:{T1D}"], [], [], M0 + 119_000, it)["state"], "HEALTHY")
        self.assertEqual(p.apply("DEGRADED", [f"stale:{T1D}"], [], [], M0 + 120_000, it)["state"], "DEGRADED")

    def test_degraded_episode_needs_two_clean_evaluations(self):
        p, it = policy(), info_table()
        self.assertEqual(p.apply("DEGRADED", [f"stale:{T0D}"], [], [], M0, it)["state"], "DEGRADED")
        r1 = p.apply("HEALTHY", [], [], [], M0 + 10_000, it)
        self.assertEqual((r1["state"], r1["reasons"], r1["coverage_state"]),
                         ("DEGRADED", [f"coverage_clearing:{T0D}"], "DEGRADED"))
        r2 = p.apply("HEALTHY", [], [], [], M0 + 20_000, it)
        self.assertEqual((r2["state"], r2["reasons"]), ("HEALTHY", []))

    def test_clearing_degraded_stream_blocks_a_new_tolerable_one(self):
        p, it = policy(k=3), info_table()
        p.apply("DEGRADED", [f"stale:{T0D}"], [], [], M0, it)
        r = p.apply("DEGRADED", [f"stale:{T1D}"], [], [], M0 + 10_000, it)
        self.assertEqual(r["state"], "DEGRADED"); self.assertIn(f"coverage_clearing:{T0D}", r["reasons"])

    def test_clearing_streams_count_toward_k(self):
        p, it = policy(k=2), info_table()
        p.apply("DEGRADED", [f"stale:{T1D}"], [], [], M0, it)
        r = p.apply("DEGRADED", [f"stale:{T2B}"], [], [], M0 + 10_000, it)   # T1D still clearing: n = 2 = K
        self.assertEqual(r["state"], "DEGRADED")


def fed_collector(d, **over):
    """healthy_collector with Tier-1 / Tier-2 streams fresh too."""
    c = healthy_collector(d, universe=dict(UNI), **over)
    m = A.now_ms()
    for conn in c.conns:                                  # connected long ago: an old value is stale, not pre-reconnect
        tr = c.activity[conn.name].transitions
        tr.clear(); tr.append((m - 1_000_000, True))
    for sym in ("adausdt", "solusdt"):
        book(c, 1, m - 100, sym); depth(c, 1, m - 100, sym=sym, n=10)
    mini(c, m - 100)
    return c


def read_file(d):
    with open(os.path.join(d, "health", "collector_health.json"), "rb") as fh:
        return fh.read()


def names(c):
    return stream(c, 1, "depth", "ADAUSDT"), stream(c, 0, "depth", "ETHUSDT"), stream(c, 1, "book", "ADAUSDT")


class AppFlagOff(unittest.TestCase):
    def test_view_is_identity_and_file_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            c = fed_collector(d)
            t1d, t0d, t1b = names(c)
            try:
                self.assertIsNone(c.coverage_policy)
                for prep in (lambda: None,
                             lambda: setattr(c.tracks[t1d].values, "latest", ((A.now_ms() - 200_000) * 1_000_000, {}, 9))):
                    prep()
                    h = c.health()
                    self.assertIs(c.health_view(h), h)
                    fixed = dict(h)
                    c.health = lambda fixed=fixed: fixed                  # freeze the input, compare the bytes written
                    c.write_health()
                    self.assertEqual(read_file(d), json.dumps(fixed, sort_keys=True, default=str).encode())
                    del c.health
                    for k in ("integrity_state", "coverage_state", "coverage_policy"):
                        self.assertNotIn(k, json.loads(read_file(d)))
                self.assertEqual(json.loads(read_file(d))["state"], "DEGRADED")   # unchanged semantics: one stale stream
            finally:
                stop_writer(c)


class AppFlagOn(unittest.TestCase):
    def test_split_only_is_additive(self):
        with tempfile.TemporaryDirectory() as d:
            c = fed_collector(d, health_state_split=True)
            t1d, t0d, t1b = names(c)
            try:
                self.assertIsNone(c.coverage_policy)
                h = c.health(); v = c.health_view(h)
                self.assertEqual({k: v[k] for k in h}, h)                 # every existing key and value unchanged
                self.assertEqual(set(v) - set(h), {"integrity_state", "coverage_state"})
                self.assertEqual((v["state"], v["integrity_state"], v["coverage_state"]), ("HEALTHY", "OK", "OK"))
                c.tracks[t1d].values.latest = ((A.now_ms() - 200_000) * 1_000_000, {}, 9)
                c.write_health()
                f = json.loads(read_file(d))
                self.assertEqual((f["state"], f["integrity_state"], f["coverage_state"]), ("DEGRADED", "OK", "DEGRADED"))
            finally:
                stop_writer(c)

    def test_tiering_live_file_only_raw_record_unfiltered(self):
        with tempfile.TemporaryDirectory() as d:
            c = fed_collector(d, **ON)
            t1d, t0d, t1b = names(c)
            try:
                self.assertEqual(c.health_eval()[0], "HEALTHY")
                got = capture(c)
                c.tracks[t1d].values.latest = ((A.now_ms() - 200_000) * 1_000_000, {}, 9)   # 20 s past its 180 s bound
                c.write_health(record=True)
                f = json.loads(read_file(d))
                self.assertEqual((f["state"], f["reasons"], f["integrity_state"], f["coverage_state"]),
                                 ("HEALTHY", [], "OK", "WARNING"))
                self.assertIn("coverage:streams_stale:1", f["warnings"])
                self.assertEqual(f["coverage_policy"]["raw_state"], "DEGRADED")
                rec = [r for r in got if r["type"] == "health"][-1]["payload"]
                self.assertEqual(rec["state"], "DEGRADED"); self.assertIn(f"stale:{t1d}", rec["reasons"])
                for k in ("integrity_state", "coverage_state", "coverage_policy"):
                    self.assertNotIn(k, rec)                              # dataset health records are unchanged
                self.assertEqual(c.health_state_last, "DEGRADED")         # record cadence follows the raw state
            finally:
                stop_writer(c)

    def test_tiering_safety_cases_in_app(self):
        with tempfile.TemporaryDirectory() as d:
            c = fed_collector(d, **ON)
            t1d, t0d, t1b = names(c)
            try:
                self.assertEqual(c.health_eval()[0], "HEALTHY")
                c.tracks[t1d].values.latest = ((A.now_ms() - 400_000) * 1_000_000, {}, 9)  # 220 s stale >= T
                c.write_health()
                f = json.loads(read_file(d))
                self.assertEqual((f["state"], f["reasons"]), ("DEGRADED", [f"stale:{t1d}"]))
                c.tracks[t1d].values.latest = ((A.now_ms() - 100) * 1_000_000, {}, 10)
                c.write_health(); c.write_health()                         # clearing hysteresis: 2 clean evaluations
                self.assertEqual(json.loads(read_file(d))["state"], "HEALTHY")
                c.tracks[t0d].values.latest = ((A.now_ms() - 2500) * 1_000_000, {}, 11)    # Tier 0: never tolerated
                c.write_health()
                f = json.loads(read_file(d))
                self.assertEqual(f["state"], "DEGRADED"); self.assertIn(f"stale:{t0d}", f["reasons"])
                c.tracks[t0d].values.latest = ((A.now_ms() - 100) * 1_000_000, {}, 12)
                c.write_health(); c.write_health()
                c.tracks[t1b].values.latest = ((A.now_ms() - 700_000) * 1_000_000, {}, 13)
                c.beats["sampler"] = time.monotonic() - 10                # an operational reason alongside
                c.write_health()
                f = json.loads(read_file(d))
                self.assertEqual(f["state"], "DEGRADED"); self.assertIn("task_stale:sampler", f["reasons"])
            finally:
                stop_writer(c)


class Consumers(unittest.TestCase):
    """Every reader of collector_health.json reads keys by name; additive keys change none of their decisions."""

    def hc(self, doc):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "health"))
            with open(os.path.join(d, "health", "collector_health.json"), "w") as fh:
                json.dump(doc, fh)
            code = procwatch.HC_CMD[len('python -c "'):-1].replace("/data/", d + "/")
            return subprocess.run([sys.executable, "-c", code]).returncode

    def test_container_healthcheck(self):
        now = int(time.time() * 1000)
        extra = {"integrity_state": "DEGRADED", "coverage_state": "DEGRADED", "coverage_policy": {"raw_state": "X"}}
        for st, want in (("HEALTHY", 0), ("STARTING", 0), ("DEGRADED", 1), ("DEGRADED_DISK", 1)):
            self.assertEqual(self.hc({"ts_ms": now, "state": st}), want, st)
            self.assertEqual(self.hc({"ts_ms": now, "state": st, **extra}), want, st)

    def test_monitor_sample_fields(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ops"))
        import p2f_cont_monitor as MON
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            ds, out = os.path.join(d, "ds"), os.path.join(d, "out")
            os.makedirs(os.path.join(ds, "health"))
            doc = {"ts_ms": int(time.time() * 1000), "state": "DEGRADED", "reasons": [f"stale:{T1D}"], "warnings": []}
            res = []
            for extra in ({}, {"integrity_state": "OK", "coverage_state": "DEGRADED"}):
                json.dump({**doc, **extra}, open(os.path.join(ds, "health", "collector_health.json"), "w"))
                mon = MON.Monitor(SimpleNamespace(out=out, dataset=ds, cid="0" * 64, once=True))
                s = mon.sample(); s.pop("t_ms"); s.pop("_limits"); s.pop("health_age_s"); s.pop("disk_free_gb")
                res.append(s)
            self.assertEqual(res[0], res[1])


if __name__ == "__main__":
    unittest.main()
