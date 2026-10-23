"""Synthetic tests for ops/monitoring/pipeline_liveness.py (no DB, no docker)."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import subprocess
import tempfile
import unittest
from unittest import mock
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
             cycles_until=0.0, analyzer=True, engine=True, deliver=True, window=None,
             zero_eligible_last_h=0.0):
    """A healthy pipeline: a cycle every 5 min, analyzer + engine per cycle.

    ``zero_eligible_last_h`` turns the last hours into 0-eligible cycles (the
    analyzer then has nothing to analyse): the eligible -> idle transition.
    """
    start = NOW - hours * H
    obs = pl.Observations(now=NOW, window_start=NOW - (window or hours) * H)
    t = start
    while t <= NOW - cycles_until * H:
        elig = 0 if t > NOW - zero_eligible_last_h * H else eligible
        obs.scanner_cycles.append(ok_cycle(t, elig))
        if analyzer and elig:
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

    def test_zero_eligible_market_is_idle_within_stall_horizon(self):
        v = pl.classify(make_obs(hours=8, last_signal_ago=None, eligible=0))
        self.assertEqual(v.state, pl.IDLE_BY_DESIGN)
        self.assertIn("no_eligible_coins", v.reasons)
        self.assertIn("window_shorter_than_stall_horizon", v.reasons)   # rule cannot fire
        v = pl.classify(make_obs(hours=30, window=30, last_signal_ago=None, eligible=0,
                                 zero_eligible_last_h=0))
        self.assertNotIn("window_shorter_than_stall_horizon", v.reasons)

    def test_sparse_failed_cycles_do_not_reset_zero_eligible_clock(self):
        obs = make_obs(hours=30, last_signal_ago=None, eligible=0)
        last = obs.scanner_cycles[-1].ts
        obs.scanner_cycles = [pl.ScanCycle(c.ts, pl.FAILED)
                              if int(c.ts) % int(2 * H) == 0 and last - c.ts > 4 * SCAN else c
                              for c in obs.scanner_cycles]
        self.assertGreater(sum(c.outcome == pl.FAILED for c in obs.scanner_cycles), 5)
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.UPSTREAM_OUTAGE, v.reasons)
        self.assertIn("zero_eligible_beyond_stall_horizon", v.reasons)

    def test_zero_eligible_beyond_stall_horizon_is_outage(self):
        v = pl.classify(make_obs(hours=30, last_signal_ago=None, eligible=0))
        self.assertEqual(v.state, pl.UPSTREAM_OUTAGE, v.reasons)
        self.assertIn("zero_eligible_beyond_stall_horizon", v.reasons)

    def test_empty_market_data_is_outage(self):
        obs = make_obs()
        obs.scanner_cycles[-2:] = [pl.ScanCycle(c.ts, pl.OK, 0, 0) for c in obs.scanner_cycles[-2:]]
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.UPSTREAM_OUTAGE, v.reasons)
        self.assertIn("scanner_market_data_empty", v.reasons)

    def test_eligible_then_idle_is_not_analyzer_stall(self):
        v = pl.classify(make_obs(hours=24, last_signal_ago=8, signal_every=40,
                                 zero_eligible_last_h=3))
        self.assertEqual(v.state, pl.IDLE_BY_DESIGN, v.reasons)
        v = pl.classify(make_obs(hours=24, zero_eligible_last_h=3))
        self.assertEqual(v.state, pl.PRODUCTIVE, v.reasons)

    def test_new_eligible_cycle_after_idle_stretch_is_not_analyzer_stall(self):
        obs = make_obs(hours=24, zero_eligible_last_h=3)
        obs.scanner_cycles.append(ok_cycle(NOW - 60))   # analyzer has not answered yet
        v = pl.classify(obs)
        self.assertNotIn("analyzer_silent_while_scanner_eligible", v.reasons)
        self.assertEqual(v.state, pl.PRODUCTIVE, v.reasons)

    def test_analyzer_dies_after_idle_stretch_is_stalled(self):
        obs = make_obs(hours=24, zero_eligible_last_h=3)
        t = NOW - 2 * H
        obs.scanner_cycles = [c for c in obs.scanner_cycles if c.ts < t]
        while t <= NOW:
            obs.scanner_cycles.append(ok_cycle(t))     # eligible again, analyzer silent
            t += SCAN
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.STALLED)
        self.assertIn("analyzer_silent_while_scanner_eligible", v.reasons)

    def test_paused_then_incomplete_cycle_still_blocked(self):
        obs = make_obs(hours=24, last_signal_ago=3)
        obs.scanner_cycles = [c for c in obs.scanner_cycles if c.ts < NOW - 1200]
        for k in (3, 2, 1):
            obs.scanner_cycles.append(pl.ScanCycle(NOW - k * SCAN, pl.PAUSED))
        obs.scanner_cycles.append(pl.ScanCycle(NOW - 5, pl.INCOMPLETE))
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.BLOCKED_RISK_CONTROL, v.reasons)
        self.assertEqual(v.evidence["paused_cycles_consecutive"], 3)

    def test_non_network_scanner_errors_are_stalled_not_outage(self):
        obs = make_obs()
        obs.scanner_cycles = [c for c in obs.scanner_cycles if c.ts < NOW - 3 * SCAN]
        for k in (3, 2, 1):
            obs.scanner_cycles.append(pl.ScanCycle(NOW - k * SCAN + 1, pl.FAILED))
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.STALLED, v.reasons)
        self.assertIn("scanner_cycles_failing_non_network_error", v.reasons)

    def test_future_dated_events_fail_safe(self):
        obs = make_obs(cycles_until=1.0)              # scanner otherwise silent for 1 h
        obs.scanner_cycles.append(ok_cycle(NOW + 2 * H))
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.STALLED)
        self.assertEqual(v.reasons[0], "future_dated_log_lines")
        obs = make_obs()
        obs.future_events = 1
        self.assertEqual(pl.classify(obs).reasons[0], "future_dated_log_lines")

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

    def test_collector_non_healthy_states_are_not_healthy(self):
        obs = make_obs()
        for state in ("FAILED", "STOPPED_INCOMPLETE", "BANNED_418"):
            obs.collector = {"state": state, "ts_ms": NOW * 1000}
            v = pl.classify(obs)
            self.assertEqual(v.state, pl.UPSTREAM_OUTAGE, state)
            self.assertIn("collector_state_outage", v.reasons)
        obs.collector = {"state": "SOMETHING_NEW", "ts_ms": NOW * 1000}
        self.assertIn("collector_state_unknown", pl.classify(obs).reasons)
        for bad in ({"state": "HEALTHY", "ts_ms": None}, {"state": None, "ts_ms": NOW * 1000}):
            obs.collector = bad
            v = pl.classify(obs)
            self.assertEqual(v.state, pl.UPSTREAM_OUTAGE, bad)
            self.assertIn("collector_health_unparseable", v.reasons)
        obs.collector = {"state": "HEALTHY", "ts_ms": (NOW + H) * 1000}
        self.assertIn("collector_health_future_dated", pl.classify(obs).reasons)
        obs.collector = {"state": "STARTING", "ts_ms": NOW * 1000}
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.PRODUCTIVE)
        self.assertIn("collector_degraded_advisory", v.reasons)
        obs.collector = {"state": "HEALTHY", "ts_ms": NOW * 1000}
        self.assertEqual(pl.classify(obs).reasons, ["signal_within_productive_horizon"])

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

    def test_gate_refusal_drains_backlog_and_blocks(self):
        obs = make_obs()
        for k in (5, 4, 3):                        # capacity full: every new save refused
            obs.signals_saved.append(NOW - k * 600)
            obs.delivery_refusals.append(NOW - k * 600 + 20)
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.BLOCKED_RISK_CONTROL, v.reasons)
        self.assertEqual(v.reasons, ["delivery_refused_by_risk_gate"])
        self.assertIsNone(v.evidence["delivery_backlog_age_s"])
        obs.signals_saved.append(NOW - 300)        # gate open again
        obs.deliveries.append(NOW - 280)
        self.assertEqual(pl.classify(obs).state, pl.PRODUCTIVE)

    def test_approval_request_is_terminal(self):
        obs = make_obs()
        obs.signals_saved.append(NOW - 2 * H)
        obs.approval_requests.append(NOW - 2 * H + 30)
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.PRODUCTIVE)     # a later delivery supersedes it
        self.assertIsNone(v.evidence["delivery_backlog_age_s"])

    def test_approvals_alone_are_never_productive(self):
        obs = make_obs(last_signal_ago=None)
        for k in (3, 1):
            obs.signals_saved.append(NOW - k * H)
            obs.approval_requests.append(NOW - k * H + 30)
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.IDLE_BY_DESIGN, v.reasons)
        self.assertEqual(v.reasons, ["awaiting_owner_approval"])
        self.assertEqual(v.evidence["deliveries"], 0)

    def test_all_signals_expiring_undelivered_is_stalled(self):
        # telegram failing > 2 h: every candidate expires, none delivered
        obs = make_obs(last_signal_ago=None)
        for k in (5, 3):
            obs.signals_saved.append(NOW - k * H)
            obs.delivery_failures.append(NOW - k * H + 2 * H)
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.STALLED, v.reasons)
        self.assertIn("delivery_expired_undelivered", v.reasons)
        self.assertNotIn("signal_saved_not_delivered", v.reasons)   # backlog drained
        self.assertEqual(v.evidence["deliveries"], 0)

    def test_fresh_signal_without_any_delivery_is_not_productive(self):
        obs = make_obs(last_signal_ago=None)
        obs.signals_saved.append(NOW - 600)            # pending, within normal lag
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.IDLE_BY_DESIGN, v.reasons)
        self.assertEqual(v.reasons, ["signal_not_yet_delivered"])

    def test_expired_candidate_does_not_stall_forever(self):
        obs = make_obs(last_signal_ago=None)
        obs.signals_saved.append(NOW - 3 * H)
        obs.delivery_failures.append(NOW - 3 * H + 600)
        self.assertEqual(pl.classify(obs).state, pl.STALLED)      # no later delivery yet
        obs.signals_saved.append(NOW - H)                          # telegram recovered
        obs.deliveries.append(NOW - H + 60)
        v = pl.classify(obs)
        self.assertEqual(v.state, pl.PRODUCTIVE, v.reasons)
        self.assertIsNone(v.evidence["delivery_backlog_age_s"])
        self.assertEqual(v.evidence["deliveries"], 1)

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

    def test_timeline_future_events_only_at_real_now(self):
        obs = make_obs(hours=12)
        obs.future_events = 1
        segs = pl.timeline(obs, 1800)
        self.assertNotIn(pl.STALLED, [sg["state"] for sg in segs])   # earlier steps clean
        self.assertEqual(segs[-1]["to"], pl._iso(NOW))                 # replay ends at now
        segs = pl.timeline(obs, 1800, enter_confirm=1)
        self.assertEqual(segs[-1]["state"], pl.STALLED)
        self.assertEqual(segs[-1]["reasons"][0], "future_dated_log_lines")
        self.assertEqual(segs[-1]["from"], pl._iso(NOW))
        self.assertEqual(pl.classify(obs.until(NOW - H)).state, pl.PRODUCTIVE)
        self.assertEqual(pl.classify(obs).state, pl.STALLED)        # single shot fail-safe

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
            "telegram": [
                _app(start + 99, "telegram", "ERROR",
                     "candidate 1 for signal 1 expired undelivered after 2 deferral(s): x"),
                _app(start + 120, "telegram", "ERROR",
                     "notification trade.closed 9 expired undelivered (TTL 24h)"),
                _app(start + 130, "telegram", "INFO",
                     pl.TG_REFUSED + " X إلى Telegram: " + SECRET_REASON),
                _app(start + 140, "telegram", "INFO", pl.TG_APPROVAL + ": X"),
            ],
        }, NOW, NOW - H)
        self.assertEqual(len(obs.scanner_cycles), 4)
        self.assertEqual(len(obs.engine_ticks), 2)
        self.assertEqual(len(obs.signals_saved), 1)
        self.assertEqual(len(obs.delivery_failures), 1)    # notification expiry not counted
        self.assertEqual(len(obs.delivery_refusals), 1)
        self.assertEqual(len(obs.approval_requests), 1)
        self.assertNotIn(SECRET_REASON, repr(obs))

    def test_redact_cuts_refusal_reason(self):
        line = "x | " + pl.TG_REFUSED + " SYM إلى Telegram: " + SECRET_REASON
        cut = pl.redact(line)
        self.assertTrue(cut.endswith(pl.TG_REFUSED))
        self.assertNotIn(SECRET_REASON, cut)

    def test_scanner_error_level_decides_network(self):
        t = NOW - 2 * SCAN
        lines = [_app(t, "scanner", "INFO", pl.SCAN_START + "..."),
                 _app(t + 1, "scanner", "ERROR", pl.SCAN_FAIL + " (1): KeyError: 'x'"),
                 _app(t + SCAN, "scanner", "INFO", pl.SCAN_START + "..."),
                 _app(t + SCAN + 1, "scanner", "WARNING",
                      pl.SCAN_FAIL + " (1): ClientConnectorError: x")]
        cycles, errors = pl.parse_scanner(lines)
        self.assertEqual([c.outcome for c in cycles], [pl.FAILED, pl.FAILED])
        self.assertEqual([c.upstream_error for c in cycles], [False, True])
        self.assertEqual(len(errors), 1)
        stamp = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z "
        for exc, net in (("TimeoutError", True), ("ValueError", False), ("", False)):
            self.assertEqual(pl._is_network_failure(stamp + pl.SCAN_FAIL + f" (2): {exc}: x"), net)

    def test_build_observations_clips_and_flags_future(self):
        obs = pl.build_observations({
            "analyzer": [_app(NOW - 2 * H, "analyzer", "INFO", pl.ANALYZER_CYCLE),   # before window
                         _app(NOW - 60, "analyzer", "INFO", pl.ANALYZER_CYCLE),
                         _app(NOW + 30, "analyzer", "INFO", pl.ANALYZER_CYCLE),     # within skew
                         _app(NOW + H, "analyzer", "INFO", pl.ANALYZER_CYCLE)],     # future
            "scanner": [_app(NOW + H, "scanner", "INFO", pl.SCAN_START + "...")],
        }, NOW, NOW - H)
        self.assertEqual(obs.analyzer_cycles, [NOW - 60, NOW])
        self.assertEqual(obs.scanner_cycles, [])
        self.assertEqual(obs.future_events, 2)
        v = pl.classify(obs)
        self.assertEqual((v.state, v.reasons[0]), (pl.STALLED, "future_dated_log_lines"))


class CliFailSafe(unittest.TestCase):
    def run_main(self, args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = pl.main(["--now", str(NOW)] + args)
        return rc, json.loads(buf.getvalue())

    def test_docker_failures_give_fixed_code_verdict(self):
        for effect, code in ((FileNotFoundError("docker"), "docker_unavailable"),
                             (subprocess.TimeoutExpired("docker", 1), "docker_logs_timeout"),
                             (None, "docker_logs_failed")):
            done = subprocess.CompletedProcess([], 1, stdout=b"Error: No such container: x")
            with mock.patch.object(pl.subprocess, "run",
                                   side_effect=effect, return_value=done) as run:
                rc, out = self.run_main([])
            self.assertNotEqual(rc, 0)
            self.assertEqual(out["state"], pl.STALLED)
            self.assertEqual(out["reasons"], ["log_source_unavailable"])
            self.assertEqual(set(out["evidence"]["log_source_errors"].values()), {code})
            self.assertNotIn("No such container", json.dumps(out))
            self.assertIsNotNone(run.call_args.kwargs.get("timeout"))

    def test_unreadable_log_file(self):
        with tempfile.TemporaryDirectory() as d:
            args = []
            for stage in pl.CONTAINERS:
                args += ["--log-file", f"{stage}={os.path.join(d, stage + '.missing')}"]
            rc, out = self.run_main(args)
        self.assertNotEqual(rc, 0)
        self.assertEqual(out["evidence"]["log_source_errors"]["scanner"], "log_file_unreadable")

    def test_invalid_state_file_is_no_prior_state(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            for bad in ({"state": "HEALTHY_ISH", "since": 1.0},
                        {"state": pl.PRODUCTIVE, "since": "x"}, ["not", "a", "dict"]):
                with open(p, "w") as fh:
                    json.dump(bad, fh)
                self.assertEqual(pl._load_tracker_state(p), pl.TrackerState())
            with open(p, "w") as fh:
                json.dump({"state": pl.STALLED, "since": 5.0, "candidate": "BOGUS",
                           "candidate_count": 4}, fh)
            self.assertEqual(pl._load_tracker_state(p), pl.TrackerState(pl.STALLED, 5.0, None, 0))
            for count, want in ((99, pl.EXIT_CONFIRM - 1), (-7, 0)):
                with open(p, "w") as fh:
                    json.dump({"state": pl.STALLED, "since": 5.0, "candidate": pl.PRODUCTIVE,
                               "candidate_count": count}, fh)
                st = pl._load_tracker_state(p)
                self.assertEqual(st, pl.TrackerState(pl.STALLED, 5.0, pl.PRODUCTIVE, want))
            with open(p, "w") as fh:
                json.dump({"state": pl.PRODUCTIVE, "since": 5.0, "candidate": pl.STALLED,
                           "candidate_count": 50}, fh)
            st = pl._load_tracker_state(p)
            self.assertEqual(st.candidate_count, pl.ENTER_CONFIRM - 1)
            # a clamped count still needs one real confirmation, never zero
            _, out = pl.step(pl.TrackerState(pl.STALLED, 5.0, pl.PRODUCTIVE, pl.EXIT_CONFIRM - 1),
                             pl.Verdict(pl.IDLE_BY_DESIGN, ["x"], {}), 6.0)
            self.assertEqual(out.state, pl.STALLED)
            for bad in ("9", 2.5, True):
                with open(p, "w") as fh:
                    json.dump({"state": pl.STALLED, "since": 5.0, "candidate": pl.PRODUCTIVE,
                               "candidate_count": bad}, fh)
                self.assertEqual(pl._load_tracker_state(p), pl.TrackerState())
            with open(p, "w") as fh:
                json.dump({"state": "BOGUS", "since": 1.0}, fh)
            logs = []
            for stage in pl.CONTAINERS:
                f = os.path.join(d, stage + ".log")
                open(f, "w").close()
                logs += ["--log-file", f"{stage}={f}"]
            rc, out = self.run_main(logs + ["--state-file", p])
            self.assertEqual(rc, 0)
            self.assertEqual(out["state"], out["raw_state"])   # first evaluation adopts raw
            with open(p) as fh:
                self.assertIn(json.load(fh)["state"], pl.STATES)


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
