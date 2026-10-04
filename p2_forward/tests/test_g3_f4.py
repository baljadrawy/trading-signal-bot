"""G3-F4 instrumentation: sampler lateness, event-loop pause detection, GC pause timing."""
import asyncio
import gc
import tempfile
import time
import unittest

from p2_forward import app as A
from tests.test_regression_g2r import mk, drain, lifes


class Instrumentation(unittest.TestCase):
    def test_loop_monitor_detects_single_multisecond_pause(self):
        async def go(c):
            t = asyncio.create_task(c.loopmon_task()); await asyncio.sleep(0.25)
            time.sleep(2.5)                                         # block the event loop once for 2.5 s
            await asyncio.sleep(0.3); c.stop_event.set(); await t
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); asyncio.run(go(c))
            ins = c.instrumentation()
            self.assertGreaterEqual(ins["loop_lag_max_ms"], 2300); self.assertEqual(ins["loop_lag_counts_ge"]["2000"], 1)
            self.assertEqual(ins["loop_lag_counts_ge"]["100"], 1)

    def test_sampler_lateness_counted_exactly(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); S = (A.now_ms() // 1000) * 1000
            c.last_sampled_ms = S - 4000
            c.sample_until(S - 1000, live=True)                     # boundaries processed ~1..3 s late
            ins = c.instrumentation()
            self.assertGreaterEqual(ins["sampler_lateness_max_ms"], 3000)
            self.assertEqual(ins["sampler_lateness_counts_ge"]["1000"], 3); self.assertEqual(ins["sampler_lateness_counts_ge"]["2000"], 2)

    def test_gc_pause_recorded_and_reported(self):
        async def go(c):
            gc.callbacks.append(c._gc_cb)
            try:
                c._gc_cb("start", {"generation": 2}); time.sleep(0.12); c._gc_cb("stop", {"generation": 2, "collected": 0})
                t = asyncio.create_task(c.loopmon_task()); await asyncio.sleep(0.25); c.stop_event.set(); await t
            finally:
                gc.callbacks.remove(c._gc_cb)
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); asyncio.run(go(c))
            self.assertGreaterEqual(c.instrumentation()["gc_pause_max_ms"], 100); self.assertEqual(c.gc_long, 1)
            ev = lifes(drain(c), "gc_pause"); self.assertEqual(len(ev), 1); self.assertEqual(ev[0]["generation"], 2)


if __name__ == "__main__":
    unittest.main()
