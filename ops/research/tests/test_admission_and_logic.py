"""Admission refusals, protected windows, watchdog trigger logic, jobwrap lock, profiles.

No systemd units are started here; Collector inputs are fake files in a temp dir.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

from _helpers import make_env, write_health, write_monitor

from research_exec import admission, config, jobwrap
from research_exec.hostsignals import in_protected_window, steal_between
from research_exec.watchdog import freeze_triggers, kill_triggers

QUIET_STEAL = {"interval_s": 1.0, "steal_vcpu": 0.05, "busy_vcpu": 0.5, "steal_ratio": 0.09}
TMP = os.environ.get("TMPDIR")


def U(h, m, d=6):
    return dt.datetime(2026, 10, d, h, m, 30, tzinfo=dt.timezone.utc)


class TestWindows(unittest.TestCase):
    W = config.DEFAULTS["windows_utc"]

    def test_hourly(self):
        self.assertEqual(in_protected_window(self.W, U(10, 12)), (True, "hourly-seal"))
        self.assertEqual(in_protected_window(self.W, U(10, 24)), (True, "hourly-seal"))
        self.assertFalse(in_protected_window(self.W, U(10, 11))[0])
        self.assertFalse(in_protected_window(self.W, U(10, 25))[0])

    def test_daily_wraps_midnight(self):
        self.assertEqual(in_protected_window(self.W, U(23, 50))[1], "day-close")
        self.assertEqual(in_protected_window(self.W, U(0, 30))[1], "day-close")
        self.assertFalse(in_protected_window(self.W, U(23, 49))[0])
        self.assertFalse(in_protected_window(self.W, U(0, 45))[0])
        self.assertEqual(in_protected_window(self.W, U(1, 10))[1], "nightly-seal-backups")
        self.assertFalse(in_protected_window(self.W, U(1, 45))[0])
        self.assertFalse(in_protected_window(self.W, U(1, 9))[0])


class TestAdmission(unittest.TestCase):
    def setUp(self):
        self.env = make_env(TMP)
        self.cfg = config.load_config(self.env["config"])
        self.prof = config.resolve_profile(self.cfg, "TINT", workers=None, allow_elevated=False,
                                           attended=False, max_runtime_s=None)

    def tearDown(self):
        shutil.rmtree(self.env["dir"], ignore_errors=True)

    def ev(self, **kw):
        return admission.evaluate(self.cfg, self.prof, steal_sample=kw.pop("steal", QUIET_STEAL), **kw)

    def test_admits_when_all_clear(self):
        d = self.ev()
        self.assertTrue(d["admit"], d["reasons"])

    def test_refuses_unhealthy_collector(self):
        write_health(self.env["health"], state="DEGRADED")
        d = self.ev()
        self.assertFalse(d["admit"])
        self.assertIn("collector_state=DEGRADED", d["reasons"])

    def test_refuses_stale_health_and_lag(self):
        write_health(self.env["health"], ts_ms=int((time.time() - 120) * 1000), durable_lag_ms=9000,
                     beat_age_ms=8000)
        r = " ".join(self.ev()["reasons"])
        self.assertIn("health_stale", r)
        self.assertIn("durable_lag_ms=9000", r)
        self.assertIn("beat_age_ms=8000", r)

    def test_refuses_unreadable_health(self):
        os.unlink(self.env["health"])
        self.assertIn("collector_state=UNREADABLE", self.ev()["reasons"])

    def test_refuses_monitor_degraded_or_stale(self):
        write_monitor(self.env["monitor"], "CRITICAL")
        self.assertIn("monitor_severity=CRITICAL", self.ev()["reasons"])
        write_monitor(self.env["monitor"], "WARNING")
        old = time.time() - 3600
        os.utime(self.env["monitor"], (old, old))
        self.assertTrue(any(r.startswith("monitor_stale") for r in self.ev()["reasons"]))

    def test_refuses_inside_protected_window(self):
        d = self.ev(now_utc=U(10, 15))
        # evaluate() uses cfg windows; the test config has none -> admit. Use real windows:
        self.assertTrue(d["admit"])
        self.cfg["windows_utc"] = config.DEFAULTS["windows_utc"]
        d = self.ev(now_utc=U(10, 15))
        self.assertIn("protected_window=hourly-seal", d["reasons"])

    def test_refuses_when_lock_held(self):
        lp = admission.lock_path(self.cfg, "test-heavy")
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        fd = os.open(lp, os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            self.assertIn("lock_held=test-heavy", self.ev()["reasons"])
        finally:
            os.close(fd)
        self.assertTrue(self.ev()["admit"])

    def test_refuses_on_steal(self):
        self.cfg["admission"].update(steal_ratio_max=0.40, steal_vcpu_max=1.0)
        hi = {"interval_s": 5, "steal_vcpu": 1.5, "busy_vcpu": 2.0, "steal_ratio": 0.43}
        r = self.ev(steal=hi)["reasons"]
        self.assertTrue(any(x.startswith("steal_ratio") for x in r))
        self.assertTrue(any(x.startswith("steal_vcpu") for x in r))

    def test_steal_math(self):
        hz = os.sysconf("SC_CLK_TCK")
        a = {"busy": 0, "idle": 0, "steal": 0, "t": 0.0}
        b = {"busy": 3 * hz * 5, "idle": 0, "steal": 1 * hz * 5, "t": 5.0}
        s = steal_between(a, b)
        self.assertAlmostEqual(s["steal_vcpu"], 1.0)
        self.assertAlmostEqual(s["busy_vcpu"], 3.0)
        self.assertAlmostEqual(s["steal_ratio"], 0.25)


class TestWatchdogLogic(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load_config(None)
        self.ok = {"state": "HEALTHY", "health_age_s": 2, "durable_lag_ms": 800, "beat_age_ms": 100,
                   "loop_lag_max_60s_ms": 200}

    def ft(self, health=None, monitor=None, steal=0.3, psi=None, window=None, pause=False):
        return freeze_triggers(self.cfg, health or self.ok, monitor or {"severity": "WARNING"}, steal,
                               psi or {"some_avg10": 0.0}, window, pause)

    def test_clean(self):
        self.assertEqual(self.ft(), [])

    def test_each_freeze_trigger(self):
        self.assertTrue(self.ft(health=dict(self.ok, state="DEGRADED")))
        self.assertTrue(self.ft(health=dict(self.ok, durable_lag_ms=5001)))
        self.assertTrue(self.ft(health=dict(self.ok, beat_age_ms=3001)))
        self.assertTrue(self.ft(health=dict(self.ok, health_age_s=31)))
        self.assertTrue(self.ft(health=dict(self.ok, loop_lag_max_60s_ms=5001)))
        self.assertTrue(self.ft(monitor={"severity": "DEGRADED"}))
        self.assertTrue(self.ft(steal=2.1))
        self.assertTrue(self.ft(psi={"some_avg10": 1.5}))
        self.assertTrue(self.ft(window="hourly-seal"))
        self.assertTrue(self.ft(pause=True))
        self.assertEqual(self.ft(steal=None), [])     # not enough samples yet: no decision

    def test_kill_triggers(self):
        self.assertEqual(kill_triggers(self.cfg, 15.0, {"full_avg10": 0.0}, 10), [])
        self.assertTrue(kill_triggers(self.cfg, 2.5, {"full_avg10": 0.0}, 0))
        self.assertTrue(kill_triggers(self.cfg, 15.0, {"full_avg10": 12.0}, 0))
        self.assertTrue(kill_triggers(self.cfg, 15.0, {"full_avg10": 0.0}, 4201))


class TestProfilesAndJobwrap(unittest.TestCase):
    def test_profile_opt_in_and_bounds(self):
        cfg = config.load_config(None)
        p = config.resolve_profile(cfg, "R1", workers=None, allow_elevated=False, attended=False,
                                   max_runtime_s=None)
        self.assertEqual((p["workers"], p["cpu_quota_pct"]), (4, 400))
        with self.assertRaises(PermissionError):
            config.resolve_profile(cfg, "R2", workers=None, allow_elevated=False, attended=False,
                                   max_runtime_s=None)
        with self.assertRaises(PermissionError):
            config.resolve_profile(cfg, "R3", workers=None, allow_elevated=True, attended=False,
                                   max_runtime_s=None)
        with self.assertRaises(ValueError):
            config.resolve_profile(cfg, "R1", workers=5, allow_elevated=False, attended=False,
                                   max_runtime_s=None)
        self.assertEqual(config.resolve_profile(cfg, "R3", workers=6, allow_elevated=False,
                                                attended=True, max_runtime_s=60)["workers"], 6)

    def test_jobwrap_refuses_when_lock_busy_and_records(self):
        d = tempfile.mkdtemp(prefix="jw-", dir=TMP)
        try:
            lock = os.path.join(d, "x.lock")
            fd = os.open(lock, os.O_RDWR | os.O_CREAT)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                rc = jobwrap.main(os.path.join(d, "job"), lock, [sys.executable, "-c", "print(1)"])
            finally:
                os.close(fd)
            self.assertEqual(rc, jobwrap.EX_LOCK_BUSY)
            with open(os.path.join(d, "job", "jobwrap.json")) as fh:
                self.assertEqual(json.load(fh)["status"], "lock_busy")
            rc = jobwrap.main(os.path.join(d, "job2"), lock, [sys.executable, "-c", "print(1)"])
            self.assertEqual(rc, 0)
            with open(os.path.join(d, "job2", "jobwrap.json")) as fh:
                rec = json.load(fh)
            self.assertEqual((rec["status"], rec["exit_code"]), ("finished", 0))
            self.assertIn("cpu_usage_usec", rec["cgroup_at_exit"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
