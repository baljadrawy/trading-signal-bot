"""G3-F4 spec v7: process-isolated certifier + one-cgroup evidence + observability requirements (verifier side)."""
import copy
import json
import os
import shutil
import tempfile
import unittest

from tests.test_g3_prereqs import run_g3_e2e, g3_test_spec, VI, segs_of, recertify

CPU_STAT = "usage_usec={u},user_usec=1,system_usec=1,nr_periods={p},nr_throttled={t},throttled_usec={tu},"


def cg_tsv(path, t0, t1, step_ms=5000, cpu_max="50000 100000", mem="402653184", pids="64", roles=None, old=False,
           cert_pid=lambda t: 9):
    with open(path, "w") as fh:
        fh.write("utc_ns\tcpu_max\tcpu_stat\tmemory_max\tpids_max\tmemory_current\tpids_current\tprocs\n")
        for i, t in enumerate(range(t0, t1 + 1, step_ms)):
            st = CPU_STAT.format(u=i * 2_500_000, p=i * 50, t=i * 4, tu=i * 100_000)
            if old:
                fh.write(f"{t * 1_000_000}\t{cpu_max}\t{st}\n"); continue
            pr = roles(t) if roles else f"1=collector,7=tracker,{cert_pid(t)}=certifier,"
            fh.write(f"{t * 1_000_000}\t{cpu_max}\t{st}\t{mem}\t{pids}\t150000000\t9\t{pr}\n")
    return path


class SpecV7(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = os.path.join(cls.tmp.name, "data"); os.makedirs(cls.base)
        run_g3_e2e(cls.base)
        r = VI.verify(cls.base, spec=g3_test_spec())
        cls.ws, cls.stop = r["window"]["ws_start_ms"], r["window"]["stop_requested_ms"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def spec(self):
        s = g3_test_spec(); s["cgroup"]["require_capture"] = True
        return s

    def run_v(self, tsv=None, spec=None, base=None):
        return VI.verify(base or self.base, spec=spec or self.spec(), cgroup=VI.read_cgroup(tsv))

    def tsv(self, name="cg.tsv", **kw):
        return cg_tsv(os.path.join(self.tmp.name, name), self.ws - 5000, self.stop + 5000, **kw)

    def test_v7_is_v6_plus_additions_only(self):
        v6, v7 = json.loads(json.dumps(VI.G3_SPEC_V6)), json.loads(json.dumps(VI.G3_SPEC))
        for k, v in v6.items():
            if k == "name":
                continue
            if k == "certifier":
                self.assertEqual({x: v7[k][x] for x in v}, v)          # v6 certifier values unchanged
            else:
                self.assertEqual(v7[k], v, k)
        self.assertEqual(VI.G3_SPEC["name"], "g3-recommended-6h-v7")

    def test_good_cgroup_evidence_passes_and_reports_throttling(self):
        r = self.run_v(self.tsv())
        self.assertTrue(r["PASS"] and r["acceptance"], r["failures"])
        self.assertIn("throttled_period_fraction", r["cgroup"]["throttling"])
        ins = r["instrumentation"]
        self.assertTrue(ins["report_only"]); self.assertGreater(ins["independent_sampler_lateness_ms"]["boundaries"], 0)
        for k in VI.G3_SPEC["instrumentation"]["required_keys"]:
            self.assertIn(k, ins["collector"])

    def test_missing_capture_fails_closed(self):
        self.assertIn("ACC_CGROUP_NOT_PROVIDED", self.run_v(None)["failures"])

    def test_cpu_cap_must_be_half_cpu_total(self):
        self.assertIn("ACC_CGROUP_CPU_MAX", self.run_v(self.tsv(cpu_max="100000 100000"))["failures"])

    def test_limits_pinned(self):
        self.assertIn("ACC_CGROUP_LIMITS", self.run_v(self.tsv(mem="max"))["failures"])
        self.assertIn("ACC_CGROUP_LIMITS", self.run_v(self.tsv(pids="128"))["failures"])

    def test_v6_monitor_format_has_no_process_evidence(self):
        self.assertIn("ACC_CGROUP_PROCESS_EVIDENCE_MISSING", self.run_v(self.tsv(old=True))["failures"])

    def test_certifier_outside_the_cgroup_or_missing_detected(self):
        mid = (self.ws + self.stop) // 2
        f = self.run_v(self.tsv(roles=lambda t: "1=collector,7=tracker," if abs(t - mid) < 3000 else
                                "1=collector,7=tracker,9=certifier,"))["failures"]
        self.assertIn("ACC_CGROUP_PROCESS_SET", f)
        f = self.run_v(self.tsv(roles=lambda t: "1=collector,9=certifier,12=other,"))["failures"]
        self.assertIn("ACC_CGROUP_PROCESS_SET", f)

    def test_certifier_pid_change_detected(self):
        mid = (self.ws + self.stop) // 2
        f = self.run_v(self.tsv(cert_pid=lambda t: 9 if t < mid else 31))["failures"]
        self.assertIn("ACC_CERTIFIER_PID_CHANGED", f)

    def test_sampling_gap_detected(self):
        self.assertIn("ACC_CGROUP_SAMPLING_GAP", self.run_v(self.tsv(step_ms=25_000))["failures"])

    def test_certifier_architecture_pinned(self):
        s = self.spec(); s["certifier"]["mode"] = "thread"
        self.assertIn("ACC_CERTIFIER_ARCHITECTURE_NOT_SPEC", self.run_v(self.tsv(), spec=s)["failures"])
        s = self.spec(); s["certifier"]["ready_timeout_s"] = 30
        self.assertIn("ACC_CERTIFIER_ARCHITECTURE_NOT_SPEC", self.run_v(self.tsv(), spec=s)["failures"])

    def test_instrumentation_missing_from_health_records_detected(self):
        d = tempfile.mkdtemp(dir=self.tmp.name); dst = os.path.join(d, "data"); shutil.copytree(self.base, dst)
        def strip(ls):
            for x in ls:
                x["payload"].pop("instrumentation", None)
            return ls
        for seg in segs_of(dst, "health"):
            recertify(dst, seg, strip)
        self.assertIn("ACC_INSTRUMENTATION_MISSING", self.run_v(self.tsv(), base=dst)["failures"])

    def test_cli_accepts_cgroup_tsv(self):
        spec = os.path.join(self.tmp.name, "spec7.json"); json.dump(self.spec(), open(spec, "w"))
        out = os.path.join(self.tmp.name, "rep7.json")
        rc = VI.main([self.base, "--spec", spec, "--cgroup-tsv", self.tsv("cli.tsv"), "--json", out])
        rep = json.load(open(out))
        self.assertEqual(rc, 0, rep["failures"]); self.assertIn("cgroup", rep)


if __name__ == "__main__":
    unittest.main()
