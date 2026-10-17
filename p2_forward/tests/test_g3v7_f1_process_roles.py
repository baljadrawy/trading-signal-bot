"""G3V7-F1 / spec v8: process-role classification of the container cgroup (adversarial). Docker HEALTHCHECK
execution is recognised only by command + cgroup + ancestry + Docker's own run window + lifetime + cadence +
structure; everything else (and anything unattributable) fails closed. v7 behaviour stays pinned."""
import copy
import json
import os
import tempfile
import unittest

from tests.test_g3_prereqs import run_g3_e2e, g3_test_spec, VI

CID = "c" * 64
SCOPE = f"0::/system.slice/docker-{CID}.scope"
SHIM, RUNCHOST = 500, 900
R = VI.G3_SPEC["cgroup"]["process_roles"]
HC = R["container_healthcheck"]
SHELL, PROBE = HC["shell_cmdline"], HC["probe_cmdline"]
T0 = 1_800_000_000_000


def cg(**kw):
    return dict(VI.G3_SPEC["cgroup"], _scope_cgroup=f"docker-{CID}.scope", _cid=CID, **kw)


def P(pid, cmd, ppid, comm, nspid=None, cgroup=SCOPE, parent=None):
    return {"pid": pid, "ppid": ppid, "nspid": nspid, "comm": comm, "cmdline": cmd, "cgroup": cgroup,
            "parent_cmdline": parent}


COL = P(100, "python -m p2_forward", SHIM, "python", 1, parent="/usr/bin/containerd-shim-runc-v2 -namespace moby -id " + CID)
TRK = P(107, R["tracker"]["cmdline_prefix"] + "5)", 100, "python", 8)
CERT = P(108, R["certifier"]["cmdline_prefix"] + "tracker_fd=6, pipe_handle=13) --multiprocessing-fork", 100, "python", 9)
RUNC_PARENT = f"runc --root /var/run/docker/runtime-runc/moby --log /run/containerd/io.containerd.runtime.v2.task/moby/{CID}/log.json --log-format json exec"


def runc(pid, comm="runc:[2:INIT]"):
    return P(pid, "runc init", RUNCHOST, comm, parent=RUNC_PARENT)


def shell(pid):
    return P(pid, SHELL, SHIM, "sh", parent="/usr/bin/containerd-shim-runc-v2 -namespace moby -id " + CID)


def probe(pid, sh):
    return P(pid, PROBE, sh, "python", parent=SHELL)


class World:
    """10 minutes: samples every 5 s; Docker runs every 30.5 s (0.5 s long) from T0+30 s; log fully covered."""

    def __init__(self, minutes=10):
        self.end = T0 + minutes * 60_000
        self.samples = [{"t_ms": t, "procs": [COL] + ([TRK, CERT] if t >= T0 + 2_000 else []), "escaped": []}
                        for t in range(T0, self.end, 5_000)]
        self.runs = [(t, t + 500, 0) for t in range(T0 + 30_000, self.end, 30_500)]
        self.cover = [(T0, self.end)]
        self.aux = []
        self.window = (T0 + 150_000, self.end)

    def at(self, t, *procs):
        s = {"t_ms": t, "procs": [COL, TRK, CERT] + list(procs), "escaped": []}
        self.samples.append(s); self.samples.sort(key=lambda x: x["t_ms"])
        return s

    def run_t(self, k):
        return self.runs[k][0]

    def classify(self, mode="strict", **kw):
        return VI.classify_processes(self.samples, cg(**kw), self.window, self.runs, self.cover, self.aux, mode=mode)


class ProcessRolesPass(unittest.TestCase):
    def test_baseline_collector_only_at_startup_then_triple(self):
        r = World().classify()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["collector_pid"], 100)

    def test_runc_stage_shell_stage_probe_stage_in_runs(self):
        w = World(); t = w.run_t(6)
        w.at(t + 100, runc(4001)); w.at(w.run_t(8) + 200, shell(4101)); w.at(w.run_t(10) + 300, shell(4201), probe(4207, 4201))
        r = w.classify()
        self.assertTrue(r["ok"], r); self.assertEqual(r["tiers"]["exact"], 4)

    def test_pre_exec_fork_of_shell_is_the_probe_child(self):
        w = World(); t = w.run_t(7)
        fork = P(4307, SHELL, 4301, "sh", parent=SHELL)             # sh forked its child, not yet exec'd python
        w.at(t + 100, shell(4301), fork)
        w.aux.append(dict(probe(4307, 4301), t_ms=t + 150, src="follow"))
        self.assertTrue(w.classify()["ok"])

    def test_partial_transient_reconciled_by_later_command_information(self):
        w = World(); t = w.run_t(9)
        w.at(t + 100, {"pid": 4401, "ppid": RUNCHOST, "comm": "runc:[1:CHILD]", "cmdline": "", "cgroup": SCOPE,
                       "parent_cmdline": RUNC_PARENT})                  # mid-exec: no command line yet
        w.aux.append(dict(runc(4401), t_ms=t + 150, src="follow"))
        r = w.classify(); self.assertTrue(r["ok"], r)

    def test_unreadable_pid_reconciled_by_adjacent_identified_chain_in_run(self):
        w = World(); t = w.run_t(11)
        w.at(t + 50, {"pid": 4500, "cgroup": None})                    # gone before /proc could be read
        w.aux += [dict(runc(4501), t_ms=t + 60, src="follow"), dict(shell(4501), t_ms=t + 120, src="follow"),
                  dict(probe(4507, 4501), t_ms=t + 200, src="follow")]
        r = w.classify(); self.assertTrue(r["ok"], r)
        self.assertEqual(r["tiers"]["unreadable_pid_adjacent_in_run"], 1)


class ProcessRolesFail(unittest.TestCase):
    def assertUnexpected(self, r, why=None):
        self.assertFalse(r["ok"])
        if why:
            self.assertTrue(any(why in u[2] for u in r["unexpected"] + r["unresolved"]), r["unexpected"] + r["unresolved"])

    def test_arbitrary_python(self):
        w = World(); w.at(w.run_t(6) + 100, P(5001, "python -c import time; time.sleep(9)", SHIM, "python"))
        self.assertUnexpected(w.classify(), "wrong_command")

    def test_arbitrary_shell(self):
        w = World(); w.at(w.run_t(6) + 100, P(5002, "/bin/sh -c sleep 5", SHIM, "sh"))
        self.assertUnexpected(w.classify(), "wrong_command")

    def test_long_lived_imitation_of_the_healthcheck(self):
        w = World()
        for dt in (0, 5_000, 10_000):
            w.at(w.run_t(6) + 100 + dt, shell(5003))
        self.assertUnexpected(w.classify(), "long_lived")

    def test_similar_executable_wrong_command(self):
        w = World(); w.at(w.run_t(6) + 100, P(5004, PROBE.replace("collector_health.json", "other.json"), 4001, "python"))
        self.assertUnexpected(w.classify(), "wrong_command")

    def test_exact_command_outside_any_docker_run(self):
        w = World(); w.at(w.run_t(6) + 10_000, shell(5005))       # exact command, impossible timing / not Docker's
        self.assertUnexpected(w.classify(), "outside_healthcheck_run")

    def test_exact_command_at_impossible_cadence(self):
        w = World(); w.runs.append((w.run_t(6) + 5_000, w.run_t(6) + 5_500, 0)); w.runs.sort()
        w.at(w.run_t(6) + 100, shell(5006)); w.at(w.run_t(6) + 5_100, shell(5016))
        self.assertUnexpected(w.classify(), "impossible_cadence")

    def test_extra_child_spawned_by_the_healthcheck(self):
        w = World(); t = w.run_t(6)
        w.at(t + 100, shell(5101), probe(5107, 5101), P(5110, "sleep 1", 5107, "sleep"))
        self.assertUnexpected(w.classify(), "wrong_command")
        w = World(); w.at(t + 100, shell(5101), probe(5107, 5101), probe(5111, 5107))   # probe-like child of probe
        self.assertUnexpected(w.classify(), "bad_ancestry")

    def test_shell_with_wrong_parent(self):
        w = World(); w.at(w.run_t(6) + 100, P(5201, SHELL, 100, "sh"))   # spawned by the collector, not Docker
        self.assertUnexpected(w.classify(), "bad_ancestry")

    def test_process_outside_intended_cgroup(self):
        w = World(); w.at(w.run_t(6) + 100, P(5301, SHELL, SHIM, "sh", cgroup="0::/system.slice/docker-" + "d" * 64 + ".scope"))
        self.assertUnexpected(w.classify(), "outside_cgroup")
        w = World(); s = w.at(w.run_t(6) + 100); s["escaped"] = [P(5302, "python -c pass", 100, "python", cgroup="0::/user.slice")]
        r = w.classify(); self.assertFalse(r["ok"]); self.assertTrue(any(f[1] == "process_escape" for f in r["per_sample_failures"]))

    def test_unknown_transient_that_cannot_be_reconciled(self):
        w = World(); w.at(w.run_t(6) + 12_000, {"pid": 5401, "cgroup": None})   # gone, outside any run
        self.assertUnexpected(w.classify(), "outside_healthcheck_run")
        w = World(); t = w.run_t(6); w.at(t + 50, {"pid": 9999, "cgroup": None}); w.aux.append(dict(shell(5501), t_ms=t + 100))
        self.assertUnexpected(w.classify(), "partial_in_run_unattributed")        # in a run but not adjacent

    def test_second_certifier_and_missing_certifier(self):
        w = World(); w.at(w.run_t(6) + 10_000, dict(CERT, pid=109, nspid=10))
        r = w.classify(); self.assertTrue(any(f[1] == "role_counts" for f in r["per_sample_failures"]))
        w = World(); w.samples.append({"t_ms": w.run_t(8) + 9_000, "procs": [COL, TRK], "escaped": []})
        r = w.classify(); self.assertTrue(any(f[1] == "role_counts" for f in r["per_sample_failures"]))

    def test_unexpected_persistent_runc_or_shell(self):
        w = World()
        for dt in range(0, 20_000, 5_000):
            w.at(w.run_t(6) + 100 + dt, runc(5601))
        self.assertUnexpected(w.classify(), "long_lived")

    def test_strict_mode_needs_the_docker_health_log(self):
        w = World(); w.cover = []; w.at(w.run_t(6) + 100, shell(5701))
        self.assertUnexpected(w.classify(), "no_healthcheck_log")

    def test_collector_must_be_container_pid_1(self):
        w = World()
        for s in w.samples:
            s["procs"] = [dict(o, nspid=7) if o["pid"] == 100 else o for o in s["procs"]]
        self.assertFalse(w.classify()["ok"])


class SpecV8AndVerifier(unittest.TestCase):
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

    def files(self, detail=True, escaped=False, cfg=None, log=True, extra=None):
        d = tempfile.mkdtemp(dir=self.tmp.name)
        tsv, hl, hcfg = (os.path.join(d, n) for n in ("cg.tsv", "hl.jsonl", "hc.json"))
        with open(tsv, "w") as fh:
            fh.write("h\n")
            for i, t in enumerate(range(self.ws - 5_000, self.stop + 5_000, 1_000)):
                procs = [COL, TRK, CERT] + ((extra or {}).get(i) or [])
                det = {"cid": CID, "procs": procs, "follow": [], "escaped": [P(1, "x", 100, "x")] if escaped and i == 3 else []}
                st = f"usage_usec={i*1000},nr_periods={i*10},nr_throttled=0,throttled_usec=0,"
                fh.write(f"{t*1_000_000}\t50000 100000\t{st}\t402653184\t64\t1\t3\t100=collector,107=tracker,108=certifier,"
                         + (f"\t{json.dumps(det)}" if detail else "") + "\n")
        with open(hl, "w") as fh:
            if log:
                for t in range(self.ws - 5_000, self.stop + 10_000, 1_000):
                    fh.write(json.dumps({"t_ms": t, "health": {"Status": "healthy", "Log": [
                        {"Start": "1970-01-01T00:00:00Z", "End": "1970-01-01T00:00:00.5Z", "ExitCode": 0}]}}) + "\n")
        with open(hcfg, "w") as fh:
            json.dump(cfg or HC["docker_healthcheck"], fh)
        return tsv, hl, hcfg

    def run_v(self, spec=None, **kw):
        tsv, hl, hcfg = self.files(**kw)
        s = spec or g3_test_spec(); s["cgroup"]["require_capture"] = True
        s["health"]["startup_s"] = 3
        return VI.verify(self.base, spec=s, cgroup=VI.read_cgroup(tsv), healthcheck=VI.read_healthcheck(hl, hcfg))

    def test_v8_pass_with_full_identity_evidence(self):
        r = self.run_v()
        self.assertTrue(r["PASS"] and r["acceptance"], r["failures"])
        self.assertIn("process_roles", r)

    def test_v8_requires_identity_detail_log_and_config(self):
        self.assertIn("ACC_CGROUP_PROCESS_EVIDENCE_MISSING", self.run_v(detail=False)["failures"])
        self.assertIn("ACC_HEALTHCHECK_LOG_INCOMPLETE", self.run_v(log=False)["failures"])
        bad = copy.deepcopy(HC["docker_healthcheck"]); bad["Interval"] = 5_000_000_000
        self.assertIn("ACC_HEALTHCHECK_CONFIG_NOT_SPEC", self.run_v(cfg=bad)["failures"])

    def test_v8_escape_and_unexpected_process_fail(self):
        self.assertIn("ACC_PROCESS_ESCAPE", self.run_v(escaped=True)["failures"])
        f = self.run_v(extra={12: [P(7001, "python -c import os", SHIM, "python")]})["failures"]
        self.assertIn("ACC_CGROUP_PROCESS_SET", f)

    def test_v8_is_v7_plus_process_role_correction_only(self):
        v7, v8 = json.loads(json.dumps(VI.G3_SPEC_V7)), json.loads(json.dumps(VI.G3_SPEC))
        self.assertEqual({k for k in set(v7) | set(v8) if v7.get(k) != v8.get(k)}, {"name", "cgroup"})
        self.assertEqual({k: v for k, v in v8["cgroup"].items() if k in v7["cgroup"]}, v7["cgroup"])   # v7 keys unchanged
        self.assertEqual(VI.G3_SPEC["name"], "g3-recommended-6h-v8")

    def test_v7_behaviour_preserved(self):
        s = copy.deepcopy(VI.G3_SPEC_V7)
        s2 = g3_test_spec(); s2.update({k: v for k, v in s.items() if k in ("cgroup", "name")}); s2["cgroup"]["require_capture"] = True
        s2["health"]["startup_s"] = 3
        tsv, hl, hcfg = self.files()
        with open(tsv) as fh:
            lines = fh.readlines()
        lines[12] = lines[12].replace("108=certifier,", "108=certifier,7001=other,")
        with open(tsv, "w") as fh:
            fh.writelines(lines)
        f = VI.verify(self.base, spec=s2, cgroup=VI.read_cgroup(tsv))["failures"]
        self.assertIn("ACC_CGROUP_PROCESS_SET", f)                          # v7: any 'other' role still fails


if __name__ == "__main__":
    unittest.main()
