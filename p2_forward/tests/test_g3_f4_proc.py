"""G3-F4: process-isolated certifier lifecycle + instrumentation (spawn; bounded)."""
import asyncio, glob, os, signal, subprocess, sys, tempfile, time, unittest
from p2_forward import writer as Wm, app as A
from p2_forward.certproc import ProcessCertifier
from tests.test_g3_f3 import one_segment, manifest, BOOT
from tests.test_regression_g2r import mk, healthy_collector, stop_writer, lifes


def pc(d):
    return ProcessCertifier(d, BOOT, Wm.new_stats(), lambda: None)


class Readiness(unittest.TestCase):
    def test_ready_and_init_failures(self):
        with tempfile.TemporaryDirectory() as d:
            c = pc(d); c.start(); self.assertTrue(c.wait_ready(10)); self.assertTrue(c.drain(5))
            c = pc(d); c.inject[0] = 1; c.start(); self.assertFalse(c.wait_ready(10)); c.join(5)
            self.assertNotEqual(c.proc.exitcode, 0); self.assertIn("injected init failure", c.fatal)
            c = pc(d); c.inject[0] = 2; c.start(); self.assertFalse(c.wait_ready(10)); c.join(5)
            self.assertEqual(c.proc.exitcode, 7); self.assertIn("exitcode=7", c.fatal)

    def test_health_never_healthy_before_readiness(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d, certifier_mode="process", certifier_ready_timeout_s=1)
            c.state = "RUNNING"; c.ws_start_ms = A.now_ms()
            cert = pc(d); cert.inject[0] = 3; cert.start_mono = time.monotonic(); cert.start()
            cert.start_mono = time.monotonic(); c.writer.certifier = cert
            st, hard, startup, _ = c.health_eval()
            self.assertNotEqual(st, "HEALTHY"); self.assertIn("certifier_not_ready", startup)   # bounded init: STARTING
            time.sleep(1.2)
            st, hard, _, _ = c.health_eval()
            self.assertIn("certifier_not_ready", hard); self.assertNotEqual(st, "HEALTHY")      # past timeout: hard
            self.assertTrue(cert.wait_ready(5)); self.assertTrue(cert.drain(5))


class RuntimeDeath(unittest.TestCase):
    def test_crash_detected_recoverable_restart(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d, certifier_mode="process")
            try:
                cert = c.writer.certifier; self.assertTrue(cert.wait_ready(10))
                cert.crash.value = 1; one_segment(d).finalize(); cert.submit("x"); cert.join(10)
                self.assertFalse(cert.is_alive()); self.assertIn("exitcode=3", cert.fatal)
                self.assertIn("certifier_dead", c.health_eval()[1])
                self.assertTrue(Wm.scan_lifecycle(d)["certifying"])                 # pending work preserved
                got = []; orig = c.enq.put; c.enq.put = lambda r, p: got.append(r) or orig(r, p)
                c.watchdog_once(); self.assertTrue(lifes(got, "certifier_dead"))
                new = c.writer.certifier; self.assertIsNot(new, cert); self.assertTrue(new.wait_ready(10))
                for _ in range(100):                                                 # done = nothing pending AND the
                    if not new.pending() and new.busy_since_ns is None: break        # worker idle (manifest appended
                    time.sleep(0.1)                                                  # after the final rename)
                self.assertEqual(len(manifest(d)), 1)                               # recovered + certified once
            finally:
                stop_writer(c)

    def test_sigterm_honoured_and_parent_death(self):
        with tempfile.TemporaryDirectory() as d:
            c = pc(d); c.start(); c.wait_ready(10); os.kill(c.ident, signal.SIGTERM); c.join(5)
            self.assertFalse(c.is_alive()); self.assertEqual(c.proc.exitcode, -signal.SIGTERM)
        out = subprocess.run([sys.executable, "-m", "tests.dev_parent_death"], capture_output=True, text=True, timeout=30,
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        pid = int(out.stdout.strip().split()[-1])
        for _ in range(60):
            if not os.path.exists(f"/proc/{pid}") or "Z" in open(f"/proc/{pid}/stat").read().split()[2]: break
            time.sleep(0.1)
        self.assertTrue(not os.path.exists(f"/proc/{pid}") or "Z" in open(f"/proc/{pid}/stat").read().split()[2])


class GilIsolation(unittest.TestCase):
    def test_cpu_heavy_certification_does_not_starve_event_loop(self):
        with tempfile.TemporaryDirectory() as d:
            c = pc(d); c.inject[1] = 3000; c.start(); c.wait_ready(10)
            one_segment(d).finalize(); c.submit("x")
            async def measure():
                worst, t_end = 0.0, time.monotonic() + 3.0
                while time.monotonic() < t_end:
                    t0 = time.monotonic(); await asyncio.sleep(0.01); worst = max(worst, time.monotonic() - t0 - 0.01)
                return worst
            time.sleep(0.2); busy = c.busy_since_ns is not None
            worst = asyncio.run(measure())
            self.assertTrue(busy); self.assertLess(worst, 0.2)                  # child burned CPU in its own interpreter
            self.assertTrue(c.drain(20)); self.assertEqual(len(manifest(d)), 1)


class BacklogAndShutdown(unittest.TestCase):
    def test_backlog_visible_and_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            c = healthy_collector(d, certifier_mode="process", certify_max_pending=0)
            try:
                cert = c.writer.certifier; cert.wait_ready(10); cert.slow_s.value = 2.0
                one_segment(d).finalize(); cert.submit("x"); time.sleep(0.5)
                self.assertIn("certifier_backlog", c.health_eval()[1])
                for _ in range(60):                                    # done = nothing pending AND worker idle
                    if not cert.pending() and cert.busy_since_ns is None: break
                    time.sleep(0.1)
                self.assertNotIn("certifier_backlog", c.health_eval()[1]); self.assertEqual(len(manifest(d)), 1)
            finally:
                stop_writer(c)

    def test_drain_normal_slow_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            c = pc(d); c.start(); c.wait_ready(10); c.slow_s.value = 1.0; one_segment(d).finalize(); c.submit("x")
            self.assertTrue(c.drain(15)); self.assertEqual(len(manifest(d)), 1)
        with tempfile.TemporaryDirectory() as d:
            c = pc(d); c.start(); c.wait_ready(10); c.slow_s.value = 30.0; one_segment(d).finalize(); c.submit("x")
            time.sleep(0.3); t = time.monotonic(); ok = c.drain(1.0)
            self.assertFalse(ok); self.assertLess(time.monotonic() - t, 3.0)        # bounded, never hangs
            self.assertTrue(Wm.scan_lifecycle(d)["certifying"])                     # preserved for recovery
            c.proc.terminate(); c.join(5)


class InjectedPause(unittest.TestCase):
    def test_2500ms_block_seen_by_sampler_lateness_and_loop_monitor(self):
        with tempfile.TemporaryDirectory() as d:
            c = mk(d); c.ws_start_ms = A.now_ms(); c.last_sampled_ms = (A.now_ms() // 1000) * 1000
            async def go():
                ts = [asyncio.create_task(c.sampler_task()), asyncio.create_task(c.loopmon_task())]
                await asyncio.sleep(1.2); time.sleep(2.5); await asyncio.sleep(1.5)
                c.stop_event.set(); await asyncio.gather(*ts, return_exceptions=True)
            asyncio.run(go())
            ins = c.instrumentation()
            self.assertGreaterEqual(ins["sampler_lateness_max_ms"], 1500); self.assertGreaterEqual(ins["loop_lag_max_ms"], 2300)
            self.assertGreaterEqual(ins["sampler_lateness_counts_ge"]["1000"], 1); self.assertEqual(ins["loop_lag_counts_ge"]["2000"], 1)
            self.assertIn("instrumentation", c.counters()); self.assertIn("instrumentation", c.health())


if __name__ == "__main__":
    unittest.main()
