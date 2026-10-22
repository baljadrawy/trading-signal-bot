"""Synthetic tests for ops/monitoring/pipeline_liveness.py (no DB, no docker)."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

_PATH = os.path.join(os.path.dirname(__file__), "..", "ops", "monitoring", "pipeline_liveness.py")
_spec = importlib.util.spec_from_file_location("pipeline_liveness", _PATH)
pl = importlib.util.module_from_spec(_spec)
sys.modules["pipeline_liveness"] = pl
_spec.loader.exec_module(pl)

H = 3600.0
NOW = datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp() + 12 * H
SCAN = 300.0
# Built at runtime so no protected-looking literal sits in the file.
SECRET_REASON = "".join(["R", "EASON", "-", "do-not-leak-", str(4242)])


def ok_cycle(t, eligible=40):
    return pl.ScanCycle(t, pl.OK, eligible, 507)


def make_obs(hours=24.0, last_signal_ago=1.0, signal_every=2.0, eligible=40,
             cycles_until=0.0, analyzer=True, engine=True, deliver=True, window=None):
    """A healthy pipeline: a cycle every 5 min, analyzer + engine per cycle."""
    start = NOW - hours * H
    obs = pl.Observations(now=NOW, window_start=NOW - (window or hours) * H)
    t = start
    while t <= NOW - cycles_until * H:
        obs.scanner_cycles.append(ok_cycle(t, eligible))
        if analyzer and eligible:
            obs.analyzer_cycles.append(t + 5)
        if engine:
            obs.engine_ticks.append(t + 30)
        t += SCAN
    if last_signal_ago is not None:
        s = NOW - last_signal_ago * H
        while s >= start:
            obs.signals_saved.append(s)
            if deliver:
                obs.deliveries.append(s + 60)
            s -= signal_every * H
    return obs


class ClassifierStates(unittest.TestCase):
    def test_productive(self):
        v = pl.classify(make_obs())
        self.assertEqual(v.state, pl.PRODUCTIVE, v.reasons)

    def test_normal_low_signal_night_is_not_stalled(self):
        for quiet in (6.5, 10.0, 14.0, 23.5):
            v = pl.classify(make_obs(hours=36, last_signal_ago=quiet, signal_every=40))
            self.assertEqual(v.state, pl.IDLE_BY_DESIGN, (quiet, v.reasons))
            self.assertIn("no_signal_within_normal_low_signal_horizon", v.reasons)

    def test_no_signal_beyond_horizon_is_stalled(self):
        v = pl.classify(make_obs(hours=36, last_signal_ago=None))
        self.assertEqual(v.state, pl.STALLED)
        self.assertIn("no_signal_beyond_abnormal_horizon", v.reasons)

    def test_short_window_without_signal_is_idle_not_stalled(self):
        v = pl.classify(make_obs(hours=8, last_signal_ago=None))
        self.assertEqual(v.state, pl.IDLE_BY_DESIGN)
        self.assertIn("window_shorter_than_stall_horizon", v.reasons)

    def test_zero_eligible_market_is_idle(self):
        v = pl.classify(make_obs(hours=30, last_signal_ago=None, eligible=0))
        self.assertEqual(v.state, pl.IDLE_BY_DESIGN)
        self.assertIn("no_eligible_coins", v.reasons)

    def test_pause_marker_blocks(self):
        obs = make_obs(hours=24, last_signal_ago=3)
        obs.scanner_cycles = [c for c in obs.scanner_cycles if c.ts < NOW - 330]
        for i in range(1, 6):
            obs.scanner_cycles.append(pl.ScanCycle(NOW - (6 - i) * 60, pl.PAUSED))
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.BLOCKED_RISK_CONTROL)
        self.assertEqual(v.reasons, ["risk_control_pause_marker"])
        self.assertEqual(v.evidence["paused_cycles_consecutive"], 5)

    def test_pause_beats_long_quiet_and_undelivered(self):
        obs = make_obs(hours=48, last_signal_ago=None)
        obs.signals_saved.append(NOW - 30 * H)
        obs.scanner_cycles[-1] = pl.ScanCycle(NOW - 10, pl.PAUSED)
        self.assertEqual(pl.classify(obs).state, pl.BLOCKED_RISK_CONTROL)

    def test_upstream_timeouts(self):
        obs = make_obs()
        obs.scanner_cycles = [c for c in obs.scanner_cycles if c.ts < NOW - 3 * SCAN]
        for k in (3, 2, 1):
            obs.scanner_cycles.append(pl.ScanCycle(NOW - k * SCAN + 1, pl.FAILED, upstream_error=True))
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.UPSTREAM_OUTAGE)
        self.assertIn("scanner_cycles_failing_or_fetch_errors", v.reasons)

    def test_single_transient_timeout_does_not_flip(self):
        obs = make_obs()
        obs.scanner_cycles.insert(-1, pl.ScanCycle(NOW - 1, pl.FAILED, upstream_error=True))
        obs.scanner_cycles.sort(key=lambda c: c.ts)
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.PRODUCTIVE)
        self.assertIn("transient_upstream_error", v.reasons)

    def test_btc_fetch_errors_in_completed_cycles_count_as_outage(self):
        obs = make_obs()
        last = obs.scanner_cycles[-2:]
        obs.scanner_cycles[-2:] = [pl.ScanCycle(c.ts, pl.OK, 0, 507, True) for c in last]
        self.assertEqual(pl.classify(obs).state, pl.UPSTREAM_OUTAGE)

    def test_collector_states(self):
        obs = make_obs()
        obs.collector = {"state": "BANNED_418", "ts_ms": NOW * 1000}
        self.assertEqual(pl.classify(obs).state, pl.UPSTREAM_OUTAGE)
        obs.collector = {"state": "HEALTHY", "ts_ms": (NOW - 600) * 1000}
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.UPSTREAM_OUTAGE)
        self.assertIn("collector_health_stale", v.reasons)
        obs.collector = {"state": "DEGRADED", "ts_ms": NOW * 1000}
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.PRODUCTIVE)
        self.assertIn("collector_degraded_advisory", v.reasons)
        obs.collector = {"error": "unreadable"}
        self.assertEqual(pl.classify(obs).state, pl.UPSTREAM_OUTAGE)

    def test_scanner_silence(self):
        v = pl.classify(make_obs(cycles_until=0.4))
        self.assertEqual(v.state, pl.STALLED)
        self.assertEqual(v.reasons[0], "scanner_silent")

    def test_no_cycles_at_all(self):
        obs = pl.Observations(now=NOW, window_start=NOW - 2 * H)
        self.assertEqual(pl.classify(obs).state, pl.STALLED)

    def test_analyzer_silent_while_eligible(self):
        v = pl.classify(make_obs(analyzer=False))
        self.assertEqual(v.state, pl.STALLED)
        self.assertIn("analyzer_silent_while_scanner_eligible", v.reasons)

    def test_signal_engine_silent(self):
        v = pl.classify(make_obs(engine=False))
        self.assertEqual(v.state, pl.STALLED)
        self.assertIn("signal_engine_silent_while_analyzer_active", v.reasons)

    def test_delivery_lag(self):
        obs = make_obs()
        obs.signals_saved.append(NOW - 7 * H)   # one stuck: backlog never drains
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.STALLED)
        self.assertIn("signal_saved_not_delivered", v.reasons)

    def test_recent_undelivered_within_normal_lag(self):
        obs = make_obs()
        obs.signals_saved.append(NOW - 600)
        self.assertEqual(pl.classify(obs).state, pl.PRODUCTIVE)
        obs.signals_saved[-1] = NOW - 45 * 60
        self.assertEqual(pl.classify(obs).state, pl.STALLED)

    def test_delivery_logged_just_before_save_is_matched(self):
        obs = make_obs()
        obs.deliveries = [t - 61 - 5 for t in obs.deliveries]  # delivery 5 s before save line
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.PRODUCTIVE, v.reasons)
        self.assertIsNone(pl.backlog_since(obs.signals_saved, obs.deliveries))

    def test_backlog_episodes(self):
        self.assertEqual(pl.backlog_episodes([10, 20], [15, 50]), [5, 30])

    def test_delivery_expired(self):
        obs = make_obs()
        obs.delivery_failures.append(NOW - 600)
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.STALLED)
        self.assertIn("delivery_expired_undelivered", v.reasons)

    def test_after_pause_lifts_no_false_stall(self):
        obs = pl.Observations(now=NOW, window_start=NOW - 40 * H)
        obs.signals_saved.append(NOW - 39 * H)       # pre-pause leftover, never delivered
        t = NOW - 39.5 * H
        while t < NOW - 2 * H:
            obs.scanner_cycles.append(pl.ScanCycle(t, pl.PAUSED))
            t += SCAN
        while t <= NOW:
            obs.scanner_cycles.append(ok_cycle(t))
            obs.analyzer_cycles.append(t + 5)
            obs.engine_ticks.append(t + 30)
            t += SCAN
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.IDLE_BY_DESIGN, v.reasons)


class Hysteresis(unittest.TestCase):
    def v(self, state):
        return pl.Verdict(state, ["x"], {})

    def test_enter_requires_confirmation_and_exit_is_slower(self):
        s = pl.TrackerState()
        s, out = pl.step(s, self.v(pl.PRODUCTIVE), 0)
        self.assertEqual(out.state, pl.PRODUCTIVE)
        s, out = pl.step(s, self.v(pl.STALLED), 1)
        self.assertEqual(out.state, pl.PRODUCTIVE)
        self.assertEqual(out.reasons, ["hysteresis_hold"])
        s, out = pl.step(s, self.v(pl.PRODUCTIVE), 2)   # flap resets the candidate
        s, out = pl.step(s, self.v(pl.STALLED), 3)
        self.assertEqual(out.state, pl.PRODUCTIVE)
        s, out = pl.step(s, self.v(pl.STALLED), 4)
        self.assertEqual(out.state, pl.STALLED)
        for i in range(2):
            s, out = pl.step(s, self.v(pl.PRODUCTIVE), 5 + i)
            self.assertEqual(out.state, pl.STALLED)
        s, out = pl.step(s, self.v(pl.PRODUCTIVE), 8)
        self.assertEqual(out.state, pl.PRODUCTIVE)

    def test_healthy_to_healthy_is_immediate(self):
        s, _ = pl.step(pl.TrackerState(), self.v(pl.PRODUCTIVE), 0)
        s, out = pl.step(s, self.v(pl.IDLE_BY_DESIGN), 1)
        self.assertEqual(out.state, pl.IDLE_BY_DESIGN)

    def test_timeline_productive_then_blocked(self):
        obs = make_obs(hours=24, last_signal_ago=4, signal_every=1)
        cut = NOW - 6 * H
        obs.scanner_cycles = [c if c.ts < cut else pl.ScanCycle(c.ts, pl.PAUSED)
                              for c in obs.scanner_cycles]
        obs.analyzer_cycles = [t for t in obs.analyzer_cycles if t < cut]
        obs.signals_saved = [t for t in obs.signals_saved if t < cut]
        obs.deliveries = [t for t in obs.deliveries if t < cut]
        segs = pl.timeline(obs, 1800)
        states = [s["state"] for s in segs]
        self.assertEqual(states[-1], pl.BLOCKED_RISK_CONTROL)
        self.assertIn(pl.PRODUCTIVE, states)
        self.assertNotIn(pl.STALLED, states)


def _dts(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".5Z "


def _app(t, logger, level, msg):
    stamp = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return f"{_dts(t)}{stamp} | {logger} | {level} | {msg}"


def scanner_log(start, n_ok, n_paused, fail_at=None):
    lines, t = [], start
    for i in range(n_ok + n_paused):
        lines.append(_app(t, "scanner", "INFO", pl.SCAN_START + "..."))
        if i >= n_ok:
            lines.append(_app(t, "scanner_logic", "WARNING",
                              pl.PAUSE_MARKER + "️ text - " + SECRET_REASON))
            lines.append(_app(t, "scanner", "INFO", pl.SCAN_DONE + " 0 x"))
        elif fail_at == i:
            lines.append(_app(t + 10, "scanner_logic", "ERROR", pl.BTC_TREND_ERR + ": "))
            lines.append(_app(t + 20, "scanner", "WARNING", pl.SCAN_FAIL + " (1): TimeoutError"))
        else:
            lines.append(_app(t + 1, "scanner_logic", "INFO", pl.SCAN_TOTAL + " 507"))
            lines.append(_app(t + 1, "scanner_logic", "INFO", pl.SCAN_ELIGIBLE + " 39"))
            lines.append(_app(t + 1, "scanner", "INFO", pl.SCAN_DONE + " 39 x"))
        t += SCAN
    return lines


class Adapter(unittest.TestCase):
    def test_strip_cuts_reason(self):
        line = "w | " + pl.PAUSE_MARKER + "️ text " + SECRET_REASON
        cut = pl.strip_after_pause_marker(line)
        self.assertNotIn(SECRET_REASON, cut)
        self.assertTrue(cut.endswith(pl.PAUSE_MARKER))

    def test_parse_scanner_cycles(self):
        lines = scanner_log(NOW - 10 * SCAN, 5, 3, fail_at=2)
        lines.insert(0, "Traceback (most recent call last):")  # untimestamped noise
        cycles, errors = pl.parse_scanner(lines)
        self.assertEqual([c.outcome for c in cycles],
                         [pl.OK, pl.OK, pl.FAILED, pl.OK, pl.OK, pl.PAUSED, pl.PAUSED, pl.PAUSED])
        self.assertEqual(cycles[0].eligible, 39)
        self.assertEqual(cycles[0].total, 507)
        self.assertEqual(len(errors), 2)
        self.assertNotIn(SECRET_REASON, repr(cycles))

    def test_app_timestamp_fallback(self):
        stamp = datetime.fromtimestamp(NOW, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cycles, _ = pl.parse_scanner([f"{stamp} | scanner | INFO | {pl.SCAN_START}...",
                                      f"{stamp} | scanner | INFO | {pl.SCAN_DONE} 3 x"])
        self.assertEqual(cycles[0].ts, NOW)
        self.assertEqual(cycles[0].eligible, 3)

    def test_cli_end_to_end_blocked_without_reason(self):
        start = NOW - 30 * SCAN
        scan = scanner_log(start, 20, 10)
        ana = [_app(start + i * SCAN + 5, "analyzer", "INFO", pl.ANALYZER_CYCLE + " 39 x")
               for i in range(20)]
        eng = [_app(start + i * SCAN + 30, "signal_engine", "INFO", pl.ENGINE_NO_SIGNAL + " x")
               for i in range(30)]
        eng.append(_app(start + 4 * SCAN + 31, "signal_engine", "INFO", pl.ENGINE_SAVED + " ID: 7"))
        tg = [_app(start + 4 * SCAN + 90, "telegram_sender", "INFO", pl.TG_DELIVERED + ": X")]
        with tempfile.TemporaryDirectory() as d:
            args = ["--since", "3h", "--now", str(NOW), "--timeline", "30m"]
            for stage, lines in (("scanner", scan), ("analyzer", ana),
                                 ("signal_engine", eng), ("telegram", tg)):
                p = os.path.join(d, stage + ".log")
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")
                args += ["--log-file", f"{stage}={p}"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(pl.main(args), 0)
        text = buf.getvalue()
        out = json.loads(text)
        self.assertEqual(out["state"], pl.BLOCKED_RISK_CONTROL)
        self.assertNotIn(SECRET_REASON, text)
        self.assertNotIn("text -", text)
        self.assertEqual(out["evidence"]["paused_cycles_consecutive"], 10)

    def test_build_observations_counts(self):
        start = NOW - 4 * SCAN
        obs = pl.build_observations({
            "scanner": scanner_log(start, 4, 0),
            "signal_engine": [_app(start + 30, "signal_engine", "INFO", pl.ENGINE_NO_FRESH),
                              _app(start + 60, "signal_engine", "INFO", pl.ENGINE_SAVED + " ID: 1")],
            "telegram": [_app(start + 99, "telegram", "ERROR", "candidate 1 for signal 1 "
                              + pl.TG_EXPIRED + " after 2 deferral(s): x")],
        }, NOW, NOW - H)
        self.assertEqual(len(obs.scanner_cycles), 4)
        self.assertEqual(len(obs.engine_ticks), 2)
        self.assertEqual(len(obs.signals_saved), 1)
        self.assertEqual(len(obs.delivery_failures), 1)


class Derivation(unittest.TestCase):
    def test_derive_from_history(self):
        scans = [NOW - i * 301 for i in range(100)]
        sigs = [NOW - i * 4 * H for i in range(30)]   # 6/day
        th = pl.derive_thresholds(scans, sigs, days_observed=5)
        self.assertEqual(th.scan_interval_s, 301)
        self.assertEqual(th.productive_h, 4)
        self.assertGreaterEqual(th.stall_no_signal_h, 8)
        self.assertLess(th.productive_h, th.stall_no_signal_h)

    def test_collector_reader_keeps_only_state(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "h.json")
            with open(p, "w") as fh:
                json.dump({"state": "HEALTHY", "ts_ms": 5, "reasons": [SECRET_REASON]}, fh)
            self.assertEqual(pl.read_collector_health(p), {"state": "HEALTHY", "ts_ms": 5})
            self.assertEqual(pl.read_collector_health(p + "x"), {"error": "unreadable"})


if __name__ == "__main__":
    unittest.main()
