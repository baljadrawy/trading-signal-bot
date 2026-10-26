"""Phase I-2: budget shadow mode in admission.evaluate (read-only, never changes the real decision).

Host signals are replaced by deterministic fakes so two evaluations can be compared byte for byte; budget probes
are injected fakes. No systemd, no real state dir, no research job.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import shutil
import time
import unittest
from unittest import mock

from _helpers import make_env

from research_exec import admission, config, launcher
from research_exec import budget as B

QUIET_STEAL = {"interval_s": 1.0, "steal_vcpu": 0.05, "busy_vcpu": 0.5, "steal_ratio": 0.09}
NOW = dt.datetime(2026, 10, 22, 10, 5, 0, tzinfo=dt.timezone.utc)
TMP = os.environ.get("TMPDIR")
BOOT = "boot-a"


class Fake:
    def __init__(self, lab=0, marker=None):
        self.units, self.pids, self.lab = {}, {os.getpid(): 1}, lab
        self.marker = [] if marker is None else marker
        self.w, self.m = NOW, 1000.0
        self.calls = 0

    def probes(self, **override):
        p = B.Probes(is_unit_active=lambda u: self.units.get(u, False), pid_start_ticks=lambda p: self.pids.get(p),
                     boot_id=lambda: BOOT, wall_utc=lambda: self.w, mono_s=lambda: self.m,
                     lab_slice_pct=lambda: self.lab, marker_procs_outside_slice=lambda: self.marker)
        for k, v in override.items():
            setattr(p, k, v)
        return p


def lease(job, pct, profile="R1", unit=None, pid=4321, ticks=7):
    return {"job_id": job, "unit": unit or f"rj-{job}.service", "profile": profile, "pct": pct, "boot_id": BOOT,
            "pid": pid, "pid_start_ticks": ticks, "admitted_utc": NOW.isoformat(),
            "expires_utc": (NOW + dt.timedelta(hours=12)).isoformat(), "mono_admitted": 900.0}


def boom(*_a):
    raise RuntimeError("probe exploded")


class TestBudgetShadow(unittest.TestCase):
    def setUp(self):
        self.env = make_env(TMP)
        self.cfg = config.load_config(self.env["config"])
        self.prof = config.resolve_profile(self.cfg, "TINT", workers=None, allow_elevated=False,
                                           attended=False, max_runtime_s=None)
        self.state = self.cfg["state_dir"]
        os.makedirs(self.state, exist_ok=True)
        self.bpath = os.path.join(self.state, "budget.json")
        hs = admission.hs     # deterministic host signals so whole decisions can be compared
        self.patches = [mock.patch.object(hs, "read_psi", lambda kind: {"some_avg60": 0.0, "kind": kind}),
                        mock.patch.object(hs, "mem_available_gib", lambda: 64.0),
                        mock.patch.object(hs, "disk_free_gb", lambda p: 500.0)]
        for name in ("read_health", "read_monitor"):         # file ages tick with wall time: freeze the 1st read
            self.patches.append(mock.patch.object(hs, name, self._frozen(getattr(hs, name))))
        for p in self.patches:
            p.start()
        self.fake = Fake()

    @staticmethod
    def _frozen(fn):
        memo = {}

        def read(path):
            if path not in memo:
                memo[path] = fn(path)
            return copy.deepcopy(memo[path])
        return read

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.env["dir"], ignore_errors=True)

    def cfg_with(self, shadow):
        c = copy.deepcopy(self.cfg)
        c["budget"]["shadow"] = shadow
        return c

    def ev(self, cfg, **kw):
        return admission.evaluate(cfg, self.prof, now_utc=NOW, steal_sample=QUIET_STEAL, job_id="job-x", **kw)

    def write_state(self, leases):
        B.save(self.bpath, dict(B.empty_state(), leases=leases))

    def listing(self):
        return {n: os.stat(os.path.join(self.state, n)).st_mtime_ns for n in sorted(os.listdir(self.state))}

    # --- default off -----------------------------------------------------------------------------------------
    def test_default_config_has_shadow_off_and_profiles_unchanged(self):
        self.assertIs(config.DEFAULTS["budget"]["shadow"], False)
        self.assertEqual(config.PROFILES["R1"]["cpu_quota_pct"], 400)
        self.assertEqual(config.PROFILES["R2"]["cpu_quota_pct"], 500)
        self.assertEqual(config.PROFILES["R3"]["cpu_quota_pct"], 800)
        self.assertEqual(config.PROFILES["LIGHT"]["cpu_quota_pct"], 200)

    def test_default_off_output_identical_to_feature_absent(self):
        absent = copy.deepcopy(self.cfg)
        del absent["budget"]                                    # config as it was before I-2
        self.write_state([lease("other", 400)])                  # would refuse if shadow ran
        with mock.patch.object(admission, "budget_shadow", side_effect=AssertionError("must not run")):
            d_absent = self.ev(absent)
            d_off = self.ev(self.cfg_with(False), budget_probes=self.fake.probes())
            d_truthy = self.ev(self.cfg_with("yes"))           # only a literal True enables it
        self.assertNotIn("budget_shadow", d_off)
        self.assertEqual(json.dumps(d_absent, sort_keys=True), json.dumps(d_off, sort_keys=True))
        self.assertEqual(json.dumps(d_absent), json.dumps(d_off))
        self.assertEqual(json.dumps(d_absent), json.dumps(d_truthy))

    # --- shadow on -------------------------------------------------------------------------------------------
    def real(self, d):
        return {k: v for k, v in d.items() if k != "budget_shadow"}

    def test_on_healthy_records_shadow_real_unchanged(self):
        base = self.ev(self.cfg_with(False))
        d = self.ev(self.cfg_with(True), budget_probes=self.fake.probes())
        self.assertEqual(self.real(d), base)
        self.assertTrue(d["admit"], d["reasons"])
        bs = d["budget_shadow"]
        self.assertEqual(set(bs), {"admit", "reasons", "capacity_pct", "held_pct", "probe_errors"})
        self.assertTrue(bs["admit"], bs)
        self.assertEqual((bs["capacity_pct"], bs["held_pct"], bs["probe_errors"], bs["reasons"]), (400, 0, [], []))

    def test_on_budget_exceeded_shadow_refuses_real_admits(self):
        self.fake.units["rj-other.service"] = True
        self.write_state([lease("other", 300)])                 # 300 held + 200 requested > 400
        base = self.ev(self.cfg_with(False))
        d = self.ev(self.cfg_with(True), budget_probes=self.fake.probes())
        self.assertTrue(d["admit"])
        self.assertEqual(self.real(d), base)
        bs = d["budget_shadow"]
        self.assertFalse(bs["admit"])
        self.assertEqual(bs["held_pct"], 300)
        self.assertTrue(any(r.startswith("budget_exceeded") for r in bs["reasons"]), bs["reasons"])

    def test_shadow_never_turns_a_real_refusal_into_admit(self):
        cfg = self.cfg_with(True)
        cfg["admission"]["disk_free_gb_min"] = 10_000.0        # real check refuses
        base = self.ev(self.cfg_with(False) | {"admission": cfg["admission"]})
        d = self.ev(cfg, budget_probes=self.fake.probes())
        self.assertFalse(d["admit"])
        self.assertTrue(d["budget_shadow"]["admit"])
        self.assertEqual(self.real(d), base)

    def test_probe_raising_is_recorded_not_raised(self):
        base = self.ev(self.cfg_with(False))
        for name in ("lab_slice_pct", "marker_procs_outside_slice", "boot_id", "wall_utc", "mono_s"):
            with self.subTest(probe=name):
                d = self.ev(self.cfg_with(True), budget_probes=self.fake.probes(**{name: boom}))
                self.assertEqual(self.real(d), base)
                bs = d["budget_shadow"]
                self.assertFalse(bs["admit"])
                self.assertIn("probe_error", bs["reasons"])
                self.assertTrue(any(e.startswith(name) and "probe exploded" in e for e in bs["probe_errors"]),
                                bs["probe_errors"])

    def test_probe_raising_on_lease_paths(self):
        self.write_state([lease("other", 100)])
        base = self.ev(self.cfg_with(False))
        for name in ("is_unit_active", "pid_start_ticks"):
            with self.subTest(probe=name):
                d = self.ev(self.cfg_with(True), budget_probes=self.fake.probes(**{name: boom}))
                self.assertEqual(self.real(d), base)
                self.assertFalse(d["budget_shadow"]["admit"])
                self.assertTrue(d["budget_shadow"]["probe_errors"])

    def test_default_host_probes_failure_is_contained(self):
        with mock.patch("research_exec.budget_probes.host_probes", side_effect=OSError("no systemd")):
            d = self.ev(self.cfg_with(True))
        self.assertTrue(d["admit"])
        self.assertFalse(d["budget_shadow"]["admit"])
        self.assertTrue(any("no systemd" in e for e in d["budget_shadow"]["probe_errors"]))

    def test_corrupt_budget_json_refuses_shadow_and_is_untouched(self):
        with open(self.bpath, "w") as fh:
            fh.write("{not json")
        before = (open(self.bpath, "rb").read(), os.stat(self.bpath).st_mtime_ns)
        base = self.ev(self.cfg_with(False))
        d = self.ev(self.cfg_with(True), budget_probes=self.fake.probes())
        self.assertEqual(self.real(d), base)
        bs = d["budget_shadow"]
        self.assertFalse(bs["admit"])
        self.assertTrue(bs["reasons"][0].startswith("budget_state_unreadable"), bs["reasons"])
        self.assertEqual((open(self.bpath, "rb").read(), os.stat(self.bpath).st_mtime_ns), before)

    def test_no_file_written_in_state_dir(self):
        self.ev(self.cfg_with(False))                           # creates the pre-existing profile lock file only
        before = self.listing()
        self.ev(self.cfg_with(True), budget_probes=self.fake.probes())
        self.assertEqual(self.listing(), before)
        self.assertNotIn("budget.json", before)
        # with a state file present (a reclaimable lease), reconcile runs on a copy: the file is not rewritten
        self.write_state([lease("dead", 100, pid=999999)])
        snap = (open(self.bpath, "rb").read(), self.listing())
        self.fake.m = 5000.0                                    # past grace: reconcile WOULD reclaim
        d = self.ev(self.cfg_with(True), budget_probes=self.fake.probes())
        self.assertEqual(d["budget_shadow"]["held_pct"], 0)
        self.assertEqual((open(self.bpath, "rb").read(), self.listing()), snap)

    def test_missing_state_dir_is_not_created(self):
        shutil.rmtree(self.state)
        cfg = self.cfg_with(True)
        cfg["budget"]["state_dir"] = os.path.join(self.env["dir"], "no-such-budget-dir")
        d = self.ev(cfg, budget_probes=self.fake.probes())
        self.assertTrue(d["budget_shadow"]["admit"], d["budget_shadow"])
        self.assertFalse(os.path.exists(cfg["budget"]["state_dir"]))


    # --- review fixes: non-dict budget, time bound, error formatting -------------------------------------------
    def test_non_dict_budget_is_ignored_like_main(self):
        absent = copy.deepcopy(self.cfg)
        del absent["budget"]
        d_absent = self.ev(absent)
        for v in ("x", [1], 5, None):
            with self.subTest(budget=v):
                c = copy.deepcopy(self.cfg)
                c["budget"] = v
                with mock.patch.object(admission, "budget_shadow", side_effect=AssertionError("must not run")):
                    d = self.ev(c)
                self.assertEqual(json.dumps(d), json.dumps(d_absent))
                bs = admission.budget_shadow(c, self.prof, "job-x", self.fake.probes())   # direct call: ignored too
                self.assertTrue(bs["admit"], bs)

    def test_bad_deadline_value_fails_shadow_closed(self):
        base = self.ev(self.cfg_with(False))
        for v in ("x", 0, -1):
            with self.subTest(shadow_deadline_s=v):
                c = self.cfg_with(True)
                c["budget"]["shadow_deadline_s"] = v
                d = self.ev(c, budget_probes=self.fake.probes())
                self.assertEqual(self.real(d), base)
                self.assertFalse(d["budget_shadow"]["admit"])
                self.assertTrue(any(e.startswith("shadow: ValueError") for e in d["budget_shadow"]["probe_errors"]))

    def test_slow_probe_hits_deadline_fake_clock(self):
        clock = [100.0]

        def slow_lab():
            clock[0] += 5.0                                     # probe "takes" 5 s on the fake clock
            return 0
        probes = self.fake.probes(lab_slice_pct=slow_lab,
                                  marker_procs_outside_slice=lambda: self.fail("probe after the deadline ran"))
        base = self.ev(self.cfg_with(False))
        with mock.patch.object(admission, "_clock", lambda: clock[0]):
            d = self.ev(self.cfg_with(True), budget_probes=probes)
        self.assertEqual(self.real(d), base)
        self.assertTrue(d["admit"])
        bs = d["budget_shadow"]
        self.assertFalse(bs["admit"])
        self.assertEqual(bs["reasons"], ["shadow_deadline_exceeded", "probe_error"])
        self.assertEqual(bs["probe_errors"], ["shadow: deadline exceeded (shadow_deadline_s=2)"])
        self.assertEqual((bs["capacity_pct"], bs["held_pct"]), (None, None))

    def test_slow_probe_real_clock_is_bounded(self):
        c = self.cfg_with(True)
        c["budget"]["shadow_deadline_s"] = 0.05
        probes = self.fake.probes(lab_slice_pct=lambda: time.sleep(0.15) or 0)
        t0 = time.monotonic()
        bs = admission.budget_shadow(c, self.prof, "job-x", probes)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertIn("shadow_deadline_exceeded", bs["reasons"])
        self.assertFalse(bs["admit"])

    def test_default_host_probes_get_short_systemctl_timeout(self):
        with mock.patch("research_exec.budget_probes.host_probes", return_value=self.fake.probes()) as hp:
            d = self.ev(self.cfg_with(True))
        hp.assert_called_once_with(systemctl_timeout_s=admission.SHADOW_DEADLINE_S)
        self.assertTrue(d["budget_shadow"]["admit"], d["budget_shadow"])

    def test_empty_message_exception_is_recorded(self):
        def silent():
            raise RuntimeError()
        d = self.ev(self.cfg_with(True), budget_probes=self.fake.probes(boot_id=silent))
        self.assertEqual(d["budget_shadow"]["probe_errors"], ["boot_id: RuntimeError"])   # recorded once
        self.write_state([lease("other", 100)])                 # reconcile probes the lease's unit (non-strict)
        with mock.patch.object(B, "check", side_effect=RuntimeError()):
            d = self.ev(self.cfg_with(True), budget_probes=self.fake.probes(is_unit_active=boom))
        errs = d["budget_shadow"]["probe_errors"]
        self.assertEqual(errs, ["is_unit_active: RuntimeError: probe exploded", "shadow: RuntimeError"])
        self.assertTrue(d["admit"])
        self.assertFalse(d["budget_shadow"]["admit"])

    # --- launcher wiring (systemd-run, systemctl and host probes are all mocked) --------------------------------
    def launch(self, cfg, job_id="job-l1"):
        run = mock.Mock(return_value=mock.Mock(returncode=0, stderr="", stdout=""))
        with mock.patch.object(launcher, "_run", run), \
                mock.patch.object(launcher, "active_state", return_value="inactive"), \
                mock.patch("research_exec.budget_probes.host_probes", return_value=self.fake.probes()), \
                mock.patch.object(launcher.adm, "evaluate", wraps=admission.evaluate) as ev:
            rc = launcher.launch(cfg, job_id=job_id, owner="agent:test", profile=self.prof, cmd=["/bin/true"],
                                 steal_sample=QUIET_STEAL, log=lambda *a: None)
        jd = os.path.join(cfg["state_dir"], "jobs", job_id)
        with open(os.path.join(jd, "admission.json")) as fh:
            adm_rec = json.load(fh)
        return rc, adm_rec, ev, run, jd

    def test_launcher_shadow_refusal_still_launches(self):
        self.fake.units["rj-other.service"] = True
        self.write_state([lease("other", 300)])                 # shadow: 300 + 200 > 400 refuses
        rc, rec, ev, run, jd = self.launch(self.cfg_with(True))
        self.assertEqual(ev.call_args.kwargs["job_id"], "job-l1")
        self.assertEqual(rc, 0)
        self.assertTrue(rec["admit"], rec["reasons"])
        self.assertFalse(rec["budget_shadow"]["admit"])
        self.assertTrue(any(r.startswith("budget_exceeded") for r in rec["budget_shadow"]["reasons"]))
        self.assertTrue(any(a.args[0][0] == "systemd-run" for a in run.call_args_list), run.call_args_list)
        self.assertFalse(os.path.exists(os.path.join(jd, "job_record.json")))

    def test_launcher_non_dict_budget_does_not_crash(self):
        c = copy.deepcopy(self.cfg)
        c["budget"] = "x"
        rc, rec, _ev, _run, _jd = self.launch(c, job_id="job-l2")
        self.assertEqual(rc, 0)
        self.assertNotIn("budget_shadow", rec)

if __name__ == "__main__":
    unittest.main()
