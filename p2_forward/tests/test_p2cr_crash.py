"""P2-CR crash / restart correctness (CR-R07, V1 in-process complement): a continuous collector PROCESS is SIGKILLed
mid-run (no stop record, open partial segments, in-memory gaps lost), then a new run starts in the same logical
dataset. Required: recovery fail-closed, explicit crash downtime, no 1970 gap, run chain intact, and the crashed day
independently verifies with the downtime made explicit (never stitched)."""
import gzip
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from p2_forward import cal
from tests.test_p2cr_continuous import VC, setup_calendar, segs_of

PY = sys.executable
CWD = str(pathlib.Path(__file__).resolve().parents[1])


def driver(d, calp, seconds, **over):
    return subprocess.Popen([PY, "-m", "tests.cont_driver", d, json.dumps(calp), str(seconds), json.dumps(over)],
                            cwd=CWD, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def wait_for(pred, s):
    end = time.time() + s
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.1)
    return pred()


class CrashRestart(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = os.path.join(cls.tmp.name, "data")
        setup_calendar(hours_before_day_end=14)                       # day ends ~28 s after now
        cls.cal = cal.params()
        p = driver(cls.base, cls.cal, 600)
        cls.boot_a = p.stdout.readline().split()[1]
        hp = os.path.join(cls.base, "health", "collector_health.json")
        ok = wait_for(lambda: os.path.exists(hp) and json.load(open(hp)).get("state") == "HEALTHY", 30)
        time.sleep(3.3)                                                  # mid calendar hour: partial segments open
        cls.partials_at_kill = [f for _, _, fs in os.walk(os.path.join(cls.base, "raw")) for f in fs if f.endswith(".partial")]
        os.kill(p.pid, signal.SIGKILL); p.wait(10)
        cls.healthy_before_kill = ok
        q = driver(cls.base, cls.cal, 75)                               # restart: crosses the day end, closes the day
        cls.boot_b = q.stdout.readline().split()[1]
        cls.code_b = q.wait(240)
        cls.days = sorted(f[:-5] for f in os.listdir(os.path.join(cls.base, "days")))
        cls.reports = {d: VC.verify_day(cls.base, d, allow_test_calendar=True) for d in cls.days}

    @classmethod
    def tearDownClass(cls):
        cal.reset()
        cls.tmp.cleanup()

    def test_kill_happened_mid_write(self):
        self.assertTrue(self.healthy_before_kill)
        self.assertTrue(self.partials_at_kill)

    def test_restart_recovered_fail_closed_and_stopped_cleanly(self):
        self.assertEqual(self.code_b, 0)
        q = pathlib.Path(self.base, "quarantine")
        self.assertTrue(list(q.glob("*.partial.orig")) or list(pathlib.Path(self.base, "raw").rglob("*-recovered-*")))
        leftovers = [f for _, _, fs in os.walk(os.path.join(self.base, "raw")) for f in fs
                     if f.endswith((".partial", ".pending", ".certifying"))]
        self.assertEqual(leftovers, [])

    def test_crash_is_explicit_downtime_in_run_chain(self):
        d = json.load(open(os.path.join(self.base, "runs", f"downtime-{self.boot_b}.json")))
        self.assertEqual(d["cause"], "crash_or_kill")
        self.assertEqual(d["previous_run"]["boot_id"], self.boot_a)
        self.assertFalse(d["previous_run"]["clean_stop"])
        rp = VC.VI.Report(); VC.run_chain(self.base, rp)
        self.assertFalse(rp.failures, rp.failures)

    def test_no_epoch_gap(self):
        for s in segs_of(self.base, "gap"):
            for line in gzip.open(s, "rt"):
                p = json.loads(line)["payload"]
                self.assertGreater(p["first_missing_ms"], 1_700_000_000_000, p)

    def test_crashed_day_verifies_with_explicit_crash_downtime(self):
        self.assertTrue(self.days)
        crash_days = [d for d, r in self.reports.items() if any(x["end_kind"] == "crash" for x in r["info"]["runs"])]
        self.assertTrue(crash_days, {d: r["info"]["runs"] for d, r in self.reports.items()})
        for d, r in self.reports.items():
            self.assertTrue(r["PASS"], json.dumps({"day": d, "f": r["failures"], "ex": r["examples"]}, default=str)[:3000])
        r = self.reports[crash_days[0]]
        self.assertGreater(r["info"]["totals"].get("downtime_crash", 0), 0)
        self.assertEqual(r["info"]["totals"].get("unexplained", 0), 0)


if __name__ == "__main__":
    unittest.main()
