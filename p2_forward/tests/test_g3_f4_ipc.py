"""G3-F4 review F1: a certifier process killed at ANY instant must never block the collector (event loop / writer).

Before the fix, shared state used multiprocessing locks/conditions: a worker SIGKILLed while idle inside
Event.wait() left the condition's sleeper count behind, and the parent's next Event.set() (submit / drain / stop)
blocked forever in Condition.notify_all(). Every call below is run in a thread with a hard bound."""
import os
import random
import signal
import tempfile
import threading
import time
import unittest

from p2_forward import writer as Wm
from p2_forward.certproc import ProcessCertifier
from tests.test_g3_f3 import one_segment, BOOT


def bounded(fn, *a, limit=5.0):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", fn(*a)), daemon=True)
    t0 = time.monotonic(); t.start(); t.join(limit)
    return (not t.is_alive()), out.get("r"), time.monotonic() - t0


def started(d):
    c = ProcessCertifier(d, BOOT, Wm.new_stats(), lambda: None); c.start()
    assert c.wait_ready(10)
    return c


class KilledWorkerNeverBlocks(unittest.TestCase):
    def test_idle_worker_sigkill_then_submit_status_drain_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            c = started(d); time.sleep(1.3)                               # idle in its 1 s wake-up wait
            os.kill(c.ident, signal.SIGKILL); c.join(5)
            for fn, a in ((c.submit, ("x",)), (c.status, ()), (c.stop, ())):
                ok, _, dt = bounded(fn, *a)
                self.assertTrue(ok, f"{fn.__name__} blocked after worker SIGKILL"); self.assertLess(dt, 2.0)
            ok, r, dt = bounded(c.drain, 1.0)
            self.assertTrue(ok); self.assertFalse(r); self.assertLess(dt, 3.0)         # abnormal exit: fail closed

    def test_sigkill_with_pending_work_drain_false_and_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            c = started(d); c.slow_s.value = 30.0; one_segment(d).finalize(); c.submit("x")
            for _ in range(50):
                if c.busy_since_ns:
                    break
                time.sleep(0.05)
            os.kill(c.ident, signal.SIGKILL); c.join(5)
            ok, r, dt = bounded(c.drain, 1.0)
            self.assertTrue(ok); self.assertFalse(r); self.assertLess(dt, 3.0)         # fail closed, never hangs
            self.assertTrue(Wm.scan_lifecycle(d)["certifying"])                        # preserved for recovery

    def test_sigkill_at_random_instants(self):
        rnd = random.Random(20261003)
        with tempfile.TemporaryDirectory() as d:
            for i in range(12):
                c = started(d)
                if i % 3 == 0:
                    one_segment(d).finalize(); c.submit("x")
                time.sleep(rnd.uniform(0.0, 1.2))
                os.kill(c.ident, signal.SIGKILL); c.join(5)
                for fn, a in ((c.submit, ("x",)), (c.status, ()), (c.drain, (0.5,))):
                    ok, _, _ = bounded(fn, *a)
                    self.assertTrue(ok, f"iteration {i}: {fn.__name__} blocked")
                for p in Wm.scan_lifecycle(d)["certifying"] + Wm.scan_lifecycle(d)["pending"]:
                    r = ProcessCertifier(d, BOOT, Wm.new_stats(), lambda: None)        # recovery certifies leftovers
                    r.start(); self.assertTrue(r.drain(20)); break

    def test_no_lock_based_shared_state(self):
        from multiprocessing import synchronize, sharedctypes
        with tempfile.TemporaryDirectory() as d:
            c = ProcessCertifier(d, BOOT, Wm.new_stats(), lambda: None)
            for k, v in vars(c).items():
                self.assertNotIsInstance(v, (synchronize.Event, synchronize.Lock, synchronize.RLock,
                                             synchronize.Condition, synchronize.Semaphore), k)
                self.assertNotIsInstance(v, sharedctypes.SynchronizedBase, k)


if __name__ == "__main__":
    unittest.main()
