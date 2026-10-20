"""G6 step 1: research units must never use host swap (MemorySwapMax=0).

Pure argv checks: no systemd unit is started and no Collector file is read.
"""
from __future__ import annotations

import unittest
from unittest import mock

import _helpers  # noqa: F401  (puts the package root on sys.path)

from research_exec import config, launcher


class TestResearchSwapIsolation(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load_config()

    def _profile(self, name, **kw):
        return config.resolve_profile(self.cfg, name, workers=None, allow_elevated=True,
                                      attended=True, max_runtime_s=None, **kw)

    def test_job_unit_disables_swap_for_every_profile(self):
        for name in self.cfg["profiles"]:
            args = launcher.build_job_cmd(self.cfg, "t1", "test", self._profile(name), "/tmp/j",
                                          "/tmp/l", ["/bin/true"], "/tmp", [])
            props = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
            self.assertIn("MemorySwapMax=0", props, name)
            # existing envelope unchanged
            p = self.cfg["profiles"][name]
            self.assertIn(f"MemoryHigh={p['memory_high']}", props, name)
            self.assertIn(f"MemoryMax={p['memory_max']}", props, name)
            self.assertIn(f"OOMScoreAdjust={p['oom_score_adj']}", props, name)
            self.assertIn("OOMPolicy=kill", props, name)

    def test_watchdog_unit_disables_swap(self):
        args = launcher.build_watchdog_cmd(self.cfg, "t1", "test", self._profile("R1"), "/tmp/j", None)
        props = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
        self.assertIn("MemorySwapMax=0", props)
        self.assertIn("MemoryMax=128M", props)

    def test_slice_runtime_properties_disable_swap(self):
        with mock.patch.object(launcher, "_run") as run:
            run.return_value = mock.Mock(returncode=0, stderr="")
            out = launcher.ensure_slice(self.cfg)
        cmd = out["cmd"]
        self.assertIn("--runtime", cmd)
        self.assertIn("research.slice", cmd)
        self.assertIn("MemorySwapMax=0", cmd)
        self.assertIn(f"MemoryMax={self.cfg['slice']['memory_max']}", cmd)


if __name__ == "__main__":
    unittest.main()
