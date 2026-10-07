"""G3 readiness (collector resize 0.5/384 MiB -> 1.5/768 MiB): monitor limits from the cgroup, binding limits, the
fail-closed G3 preflight gate and the bounded waiter. Stdlib only, no Docker, no real cgroup writes (fake trees)."""
import copy
import datetime as dt
import gzip
import hashlib
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CID = "cd" * 32
BOOT = "acae43bfe9f241e49b6c3f2f47d9c151"
IMG = "sha256:" + "69" * 32
TAG = "tsb-p2-forward:p2f-150-test"
OLD_TAG, OLD_IMG = "tsb-p2-forward:p2cr-test", "sha256:" + "75" * 32
HASH = "7e" * 32
FAKEPID = "4242"


def load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sys.path.insert(0, str(path.parent))
    sp.loader.exec_module(m)
    return m


M = load("g3r_mon", ROOT / "ops" / "p2f_cont_monitor.py")
B = load("g3r_bind", ROOT / "ops" / "p2f_monitor_bind.py")
G = load("g3r_gate", ROOT / "ops" / "p2f_g3_preflight.py")


def ms(s):
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def wj(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        json.dump(obj, fh)


def wt(p, data, mode="w"):
    with open(p, mode) as fh:
        fh.write(data)


def sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def scope_tree(root, cid=CID, cpu="50000 100000", mem="402653184", swap="0", pids="64", anon=150 << 20, procs="1"):
    s = os.path.join(root, f"docker-{cid}.scope")
    os.makedirs(s, exist_ok=True)
    files = {"cgroup.procs": procs, "cpu.stat": "usage_usec 1000\nnr_periods 10\nnr_throttled 0\n",
             "memory.events": "oom_kill 0\n", "memory.stat": f"anon {anon}\n", "memory.current": str(anon + (50 << 20)),
             "pids.current": "6", "memory.swap.current": "0", "cpu.max": cpu, "memory.max": mem,
             "memory.swap.max": swap, "pids.max": pids}
    for f, v in files.items():
        if v is None:
            if os.path.exists(os.path.join(s, f)):
                os.unlink(os.path.join(s, f))
            continue
        with open(os.path.join(s, f), "w") as fh:
            fh.write(v + "\n")
    return s


class Args:
    def __init__(self, ds, out, cid=CID):
        self.dataset, self.out, self.cid, self.once = ds, out, cid, True
        self.collector_cmdline, self.ident, self.limit_expect = "python -m p2_forward", {}, None


# ===================================================================== monitor: limits from the cgroup
class MonitorLimits(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        d = self.td.name
        self.cg = os.path.join(d, "cg")
        self.ds = os.path.join(d, "ds")
        wj(os.path.join(self.ds, "health", "collector_health.json"), {"state": "HEALTHY", "ts_ms": G.now_ms()})
        self.out = os.path.join(d, "mon")
        self._cg = M.CGROOT
        M.CGROOT = self.cg

    def tearDown(self):
        M.CGROOT = self._cg
        self.td.cleanup()

    def mon(self, expect=None):
        a = Args(self.ds, self.out)
        a.limit_expect = expect
        return M.Monitor(a)

    def evaluate(self, m):
        s = m.sample()
        return s, m.evaluate(dict(s, _binding={}), [])

    def test_read_limits_parses_current_and_target(self):
        cur = M.read_limits(scope_tree(self.cg))
        self.assertEqual((cur["memory_max_bytes"], cur["cpu_quota_cores"], cur["memory_swap_max_bytes"], cur["pids_max"]),
                         (402653184, 0.5, 0, 64))
        self.assertEqual(cur["problems"], [])
        tgt = M.read_limits(scope_tree(self.cg, cpu="150000 100000", mem="805306368"))
        self.assertEqual((tgt["memory_max_bytes"], tgt["cpu_quota_cores"], tgt["cpu_max_raw"]), (805306368, 1.5, "150000 100000"))

    def test_pct_uses_the_real_limit_not_384mib(self):
        scope_tree(self.cg, cpu="150000 100000", mem="805306368", anon=400 << 20)
        s, (sev, why) = self.evaluate(self.mon())
        self.assertEqual(s["mem_limit_bytes"], 805306368)
        self.assertAlmostEqual(s["mem_pct_of_limit"], 52.1, places=1)     # the old constant would say 104 % CRITICAL
        self.assertNotIn("memory_ge_90pct", why)
        self.assertEqual(s["cpu_quota_cores"], 1.5)

    def test_thresholds_still_fire_against_the_real_limit(self):
        scope_tree(self.cg, anon=int(0.95 * 402653184))
        _, (sev, why) = self.evaluate(self.mon())
        self.assertEqual(sev, "CRITICAL")
        self.assertIn("memory_ge_90pct", why)
        scope_tree(self.cg, cpu="150000 100000", mem="805306368", anon=int(0.8 * 805306368))
        _, (sev, why) = self.evaluate(self.mon())
        self.assertIn("memory_ge_75pct", why)

    def test_unlimited_memory_and_cpu_are_visible_warnings_not_guesses(self):
        scope_tree(self.cg, cpu="max 100000", mem="max", swap="max")
        s, (sev, why) = self.evaluate(self.mon())
        self.assertIsNone(s["mem_pct_of_limit"])
        self.assertIsNone(s["cpu_quota_cores"])
        self.assertIn("memory_limit_unknown", why)
        self.assertIn("limit_cpu.max_unlimited", why)
        self.assertIn("limit_memory.swap.max_unlimited", why)
        self.assertEqual(sev, "WARNING")

    def test_missing_and_malformed_files_fail_visible(self):
        scope_tree(self.cg, mem=None, cpu="garbage")
        s, (sev, why) = self.evaluate(self.mon())
        self.assertIsNone(s["mem_pct_of_limit"])
        self.assertIn("memory_limit_unknown", why)
        self.assertIn("limit_memory.max_unreadable", why)
        self.assertIn("limit_cpu.max_malformed", why)

    def test_changed_limit_on_the_same_container_is_flagged(self):
        scope_tree(self.cg)
        m = self.mon()
        _, (_, why) = self.evaluate(m)
        self.assertFalse([w for w in why if w.startswith("limit_mismatch")])
        scope_tree(self.cg, mem="805306368")                              # e.g. a `docker update` behind our back
        s, (sev, why) = self.evaluate(m)
        self.assertIn("limit_mismatch:memory.max", why)
        self.assertEqual(s["_limits"]["expected_source"], "first_observation")

    def test_binding_expectation_match_and_mismatch(self):
        scope_tree(self.cg, cpu="150000 100000", mem="805306368")
        exp = {"cpu.max": "150000 100000", "memory.max": "805306368", "memory.swap.max": "0", "pids.max": "64"}
        s, (_, why) = self.evaluate(self.mon(expect=exp))
        self.assertEqual(s["_limits"]["mismatch"], [])
        self.assertEqual(s["_limits"]["expected_source"], "binding")
        _, (_, why) = self.evaluate(self.mon(expect=dict(exp, **{"memory.max": "402653184"})))
        self.assertIn("limit_mismatch:memory.max", why)

    def test_limit_expectation_from_binding(self):
        self.assertIsNone(M.limit_expectation({"cid": CID}))                 # legacy binding: no expectation
        self.assertEqual(M.limit_expectation({"limits": {"memory.max": "805306368", "source": "x"}}),
                         {"memory.max": "805306368"})

    def test_once_writes_additive_status_and_consumers_still_parse(self):
        scope_tree(self.cg, procs=str(os.getpid()))
        rc = M.main(["--dataset", self.ds, "--cid", CID, "--out", self.out, "--once"])
        self.assertEqual(rc, 0)
        st = json.load(open(os.path.join(self.out, "status.json")))
        for k in ("t_ms", "severity", "severity_reasons", "monitor", "mem_pct_of_limit"):
            self.assertIn(k, st)                                              # unchanged keys G2 reads
        self.assertEqual(st["limits"]["memory_max_raw"], "402653184")
        self.assertEqual(st["limits"]["cpu_quota_cores"], 0.5)
        self.assertNotIn("_limits", st)
        day = [x for x in os.listdir(self.out) if x[:2] == "20"][0]
        smp = json.loads(open(os.path.join(self.out, day, "samples.jsonl")).readline())
        self.assertNotIn("_limits", smp)
        self.assertNotIn("limits", smp)
        self.assertIn("mem_limit_bytes", smp)
        hs = pathlib.Path("/home/tradmin/tsb-g1g2-worktree/ops/research/research_exec/hostsignals.py")
        if not hs.exists():
            self.skipTest("G2 worktree not present")
        H = load("g3r_hs", hs)
        mv = H.read_monitor(os.path.join(self.out, "status.json"))
        self.assertIn(mv["severity"], ("INFO", "WARNING"))
        self.assertEqual(H.monitor_problems(mv, ok_severities=["INFO", "WARNING"], max_age_s=180, monitor_unit=None), [])


# ===================================================================== bind: limits recorded and cross-checked
class BindLimits(unittest.TestCase):
    def test_expected_cgroup_from_hostconfig(self):
        cur = B.expected_cgroup({"NanoCpus": 500000000, "CpuPeriod": 0, "Memory": 402653184, "MemorySwap": 402653184, "PidsLimit": 64})
        self.assertEqual(cur, {"cpu.max": "50000 100000", "memory.max": "402653184", "memory.swap.max": "0", "pids.max": "64"})
        tgt = B.expected_cgroup({"NanoCpus": 1500000000, "Memory": 805306368, "MemorySwap": 805306368, "PidsLimit": 64})
        self.assertEqual(tgt, {"cpu.max": "150000 100000", "memory.max": "805306368", "memory.swap.max": "0", "pids.max": "64"})
        self.assertEqual(B.expected_cgroup({"Memory": 100, "MemorySwap": 0})["memory.swap.max"], "100")   # docker default 2x
        self.assertEqual(B.expected_cgroup({"Memory": 100, "MemorySwap": -1})["memory.swap.max"], "max")
        self.assertEqual(B.expected_cgroup({})["memory.max"], "max")

    def test_limits_check_detects_docker_cgroup_disagreement(self):
        with tempfile.TemporaryDirectory() as d:
            old = B.M.CGROOT                                  # the bind tool's own monitor-module instance
            B.M.CGROOT = d
            try:
                scope_tree(d)
                hc = {"NanoCpus": 500000000, "Memory": 402653184, "MemorySwap": 402653184, "PidsLimit": 64}
                lim, bad = B.limits_check({"cid": CID, "hostconfig": hc})
                self.assertEqual(bad, [])
                self.assertEqual(lim["memory.max"], "402653184")
                lim, bad = B.limits_check({"cid": CID, "hostconfig": dict(hc, Memory=805306368, MemorySwap=805306368)})
                self.assertTrue(any(b.startswith("limit_memory.max") for b in bad))
            finally:
                B.M.CGROOT = old


# ===================================================================== G3 preflight gate
NOW = ms("2026-10-08T03:30:00Z")


class FakeEnv(G.Env):
    def __init__(self, x, fx):
        super().__init__(x)
        self.fx = fx

    def docker_inspect(self, name):
        if self.fx.get("inspect_error"):
            raise RuntimeError("no such container")
        return copy.deepcopy(self.fx["inspect"])

    def image_id(self, tag):
        return self.fx["images"].get(tag)

    def unit_show(self, unit):
        return dict(self.fx["unit"])

    def run_chain(self):
        return dict(self.fx["run_chain"])

    def read(self, p):
        if p == f"/proc/{FAKEPID}/cmdline":
            return "python\0-m\0p2_forward\0"
        return super().read(p)


def build(d):
    """A complete, PASSING production-shaped fixture. Each test breaks exactly one thing."""
    ds = os.path.join(d, "ds")
    ops = os.path.join(d, "ops")
    mon = os.path.join(ops, "monitor", "p2-forward-continuous-v1")
    cg = os.path.join(d, "cg")
    bk = os.path.join(d, "bk")
    wj(os.path.join(ds, "dataset.json"), {"dataset_id": "p2-forward-continuous-v1"})
    created = ms("2026-10-07T13:28:15Z")
    wj(os.path.join(ds, "runs", f"run-{BOOT}.json"), {
        "boot_id": BOOT, "created_ms": created, "config_hash": HASH, "collector_version": "p2cr-collector-1.5.0",
        "build": {"image_id_runtime_claim": IMG, "image_tag": TAG, "git_commit": "cd2935e"}})
    rot_close = ms("2026-10-08T00:10:20Z")
    ev = {"conn": "conn0-book", "reason": "universe_transition", "started_ms": rot_close - 5000, "overlap_ok": True,
          "handoff": {"complete": True, "reason": "caught_up", "pending": 0, "close_ms": rot_close}}
    wj(os.path.join(ds, "health", "collector_health.json"), {
        "ts_ms": NOW - 2000, "state": "HEALTHY", "reasons": [], "warnings": [], "boot_id": BOOT, "config_hash": HASH,
        "version": "p2cr-collector-1.5.0",
        "counters": {"handoffs": 1, "handoff_classes": {"proven": 70}, "seq_reset": 0, "seq_reset_causes": {}, "seq_stale": 12},
        "rotation": {"events": [ev]}, "connection_age_s": {"conn0-book": 12000, "conn1-depth": 12000},
        "rotation_after_s": 82800,
        "universe_epoch": {"next_refresh_ms": ms("2026-10-09T00:10:00Z"), "refresh_degraded": None, "pending_effective_ms": None}})
    lc = os.path.join(ds, "raw", "lifecycle", "2026-10-08")
    os.makedirs(lc)
    recs = [{"boot_id": BOOT, "type": "lifecycle", "payload": {"event": "ws_rotation", **ev}},
            {"boot_id": BOOT, "type": "lifecycle", "payload": {
                "event": "ws_handoff", "conn": "conn0-book", "close_ms": rot_close, "audit_end": "all_proven",
                "handoff": {"complete": True, "reason": "caught_up"}, "classes": {"proven": 70}, "unresolved": []}}]
    with gzip.open(os.path.join(lc, f"lifecycle-20261008T00Z-{BOOT[:8]}-0001.jsonl.gz"), "wt") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in recs))
    wj(os.path.join(ds, "incidents", "state.json"), {"incidents": [
        {"id": "inc-1-6fd4edbc-2", "key": "failclosed:writer_stalled", "severity": "CRITICAL", "active": True,
         "ack": {"by": "x", "ref": "y"}, "count": 1, "first_ms": 1, "last_ms": 1},
        {"id": "inc-2-b1b7edb6-1", "key": "previous_run_stopped_failed", "severity": "WARNING", "active": True,
         "ack": None, "count": 1, "first_ms": 2, "last_ms": 2}]})
    os.makedirs(os.path.join(ds, "incidents", "external"))
    os.makedirs(os.path.join(ds, "seals"))
    seal_log = os.path.join(ops, "logs", "daily_seal_backup.log")
    os.makedirs(os.path.dirname(seal_log))
    log = []
    for day in ("2026-10-05", "2026-10-07"):
        wj(os.path.join(ds, "days", f"{day}.json"), {"day": day})
        rp = os.path.join(ds, "seals", f"{day}.report.json")
        wj(rp, {"PASS": True})
        sp = os.path.join(ds, "seals", f"{day}.json")
        wj(sp, {"result": "PASS", "report_sha256": sha(rp)})
        wj(os.path.join(bk, "p2-forward-continuous-v1", day, "BACKUP.json"), {"day": day, "seal_sha256": sha(sp)})
        wt(os.path.join(bk, "p2-forward-continuous-v1", day, "SHA256SUMS"), "x  y\n")
        log.append(json.dumps({"restore_test": "PASS", "day": day, "totals": {"unexplained": 0}}))
    wt(seal_log, "\n".join(['{"seal": "exists", "day": "2026-10-05"}'] + log) + "\n")
    wj(os.path.join(ds, "days", "2026-10-06.json"), {"day": "2026-10-06"})
    fr = os.path.join(ds, "seals", "2026-10-06.FAILED-1.report.json")
    wj(fr, {"PASS": False})
    doc = os.path.join(d, "DISPOSITION.md")
    wt(doc, "2026-10-06 FAILED disposition\n")
    cfg = os.path.join(ops, "configs", "continuous-v1.json")
    wj(cfg, {"mode": "continuous"})
    compose = os.path.join(ops, "compose.yml")
    open(compose, "w").write('services:\n  collector:\n    restart: "no"\n    cpus: 0.5\n    mem_limit: 384m\n'
                             '    memswap_limit: 384m\n    pids_limit: 64\n')
    cbk = os.path.join(ops, "compose.pre-g3.yml")
    wt(cbk, open(compose).read())
    os.chmod(cbk, 0o444)
    tar = os.path.join(d, "rollback.tar")
    wt(tar, b"image-tar", "wb")
    wt(tar + ".sha256", f"{sha(tar)}  {tar}\n")
    scope_tree(cg, procs=FAKEPID)
    binding = os.path.join(ops, "monitor", "p2-forward-continuous-v1.binding.json")
    wj(binding, {"schema": "p2f-monitor-binding-v1", "cid": CID, "container_name": "tsb-p2-forward-collector"})
    sp = os.path.join(mon, "status.json")
    wj(sp, {"t_ms": NOW - 10_000, "severity": "WARNING", "severity_reasons": ["incident:previous_run_stopped_failed"],
            "limits": {"memory_max_raw": "402653184", "cpu_max_raw": "50000 100000"},
            "monitor": {"supervisor": "systemd-user", "unit": "tsb-p2f-monitor.service", "pid": 123,
                        "invocation_id": "inv1", "cid": CID, "code_sha256": "c0de",
                        "binding_check": {"scope_alive": True, "collector_pid": 7, "dataset_mount_ok": True}}})
    os.utime(sp, (NOW / 1000 - 10, NOW / 1000 - 10))
    wt(os.path.join(mon, "alerts.jsonl"), "")
    x = {"schema": G.EXPECT_SCHEMA, "container_name": "tsb-p2-forward-collector", "cid": CID, "image_tag": TAG,
         "image_id": IMG, "git_commit": "cd2935e", "min_collector_version": "1.5.0", "config_hash": HASH,
         "config_file": cfg, "config_file_sha256": sha(cfg), "dataset": ds, "dataset_id": "p2-forward-continuous-v1",
         "limits_before": {"cpu.max": "50000 100000", "memory.max": "402653184", "memory.swap.max": "0", "pids.max": "64"},
         "verify_data_inode": False, "hard_reason_classification": None, "min_observed_handoffs": 1,
         "day_dispositions": {"2026-10-06": {"status": "FAILED", "doc": doc, "doc_sha256": sha(doc),
                                             "pinned_files": {"seals/2026-10-06.FAILED-1.report.json": sha(fr)}}},
         "seal_log": seal_log, "backup_root": bk, "monitor_unit": "tsb-p2f-monitor.service", "monitor_out": mon,
         "binding_file": binding, "monitor_code_sha256": "c0de", "require_limit_aware_monitor": True,
         "verifier": "/nonexistent", "ops_dir": str(ROOT / "ops"), "op_minutes": 25, "rotation_margin_min": 30,
         "compose_file": compose, "compose_sha256_before": sha(compose),
         "compose_limits_before": {"cpus": "0.5", "mem_limit": "384m", "memswap_limit": "384m", "pids_limit": "64"},
         "rollback": {"previous_image_tag": OLD_TAG, "previous_image_id": OLD_IMG, "tar": tar, "tar_sha256": sha(tar),
                      "compose_backup": cbk},
         "min_mem_available_gib": 0, "cgroup_root": cg}
    fx = {"inspect": {"Id": CID, "Image": IMG, "RestartCount": 0, "Config": {"Image": TAG},
                      "State": {"Running": True, "StartedAt": "2026-10-07T13:28:07Z"},
                      "Mounts": [{"Destination": "/data", "Source": ds, "RW": True},
                                 {"Destination": "/config/collector.json", "Source": cfg, "RW": False}]},
          "images": {TAG: IMG, OLD_TAG: OLD_IMG},
          "unit": {"ActiveState": "active", "SubState": "running", "MainPID": "123", "InvocationID": "inv1"},
          "run_chain": {"PASS": True, "failures": {}, "_rc": 0,
                        "runs": [{"boot_id": "b1b7edb6" * 4, "state": "STOPPED"}, {"boot_id": BOOT, "state": None}]}}
    return x, fx


class Gate(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.x, self.fx = build(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def ev(self, now=NOW):
        return G.evaluate(FakeEnv(self.x, self.fx), self.x, now)

    def fails(self, check, now=NOW, contains=None):
        v = self.ev(now)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertIn(check, v["failed"], json.dumps(v["checks"], default=str)[:2000])
        if contains:
            probs = " | ".join(next(c for c in v["checks"] if c["check"] == check)["problems"])
            self.assertIn(contains, probs)
        return v

    def health(self, **kw):
        p = os.path.join(self.x["dataset"], "health", "collector_health.json")
        h = json.load(open(p))
        for k, v in kw.items():
            if isinstance(v, dict) and isinstance(h.get(k), dict):
                h[k].update(v)
            else:
                h[k] = v
        wj(p, h)

    def test_baseline_fixture_passes(self):
        v = self.ev()
        self.assertEqual(v["verdict"], "PASS", json.dumps([c for c in v["checks"] if c["result"] != "PASS"], default=str))
        self.assertEqual(len(v["checks"]), 10)

    # ---- identity
    def test_identity_wrong_container_id(self):
        self.fx["inspect"]["Id"] = "ef" * 32
        self.fails("identity", contains="cid")

    def test_identity_image_and_restart_and_version(self):
        self.fx["inspect"]["Image"] = OLD_IMG
        self.fails("identity", contains="image_id")
        self.fx["inspect"]["Image"] = IMG
        self.fx["inspect"]["RestartCount"] = 1
        self.fails("identity", contains="restart_count")

    def test_identity_old_collector_version(self):
        p = os.path.join(self.x["dataset"], "runs", f"run-{BOOT}.json")
        r = json.load(open(p))
        r["collector_version"] = "p2cr-collector-1.4.0"
        wj(p, r)
        self.fails("identity", contains="collector_version")
        self.assertIn("rotation", self.ev()["failed"])

    def test_identity_config_hash(self):
        self.health(config_hash="27" * 32)
        self.fails("identity", contains="config_hash")

    def test_identity_limits_already_changed(self):
        scope_tree(self.x["cgroup_root"], procs=FAKEPID, mem="805306368")
        self.fails("identity", contains="memory.max")

    def test_identity_dataset_mount(self):
        self.fx["inspect"]["Mounts"][0]["RW"] = False
        self.fails("identity", contains="/data")

    def test_identity_no_collector_process(self):
        scope_tree(self.x["cgroup_root"], procs="1")
        self.fails("identity", contains="no collector process")

    def test_docker_unavailable_fails_closed(self):
        self.fx["inspect_error"] = True
        self.fails("identity", contains="RuntimeError")

    # ---- health
    def test_health_degraded_unclassified(self):
        self.health(state="DEGRADED", reasons=["stale:x"])
        self.fails("health", contains="unclassified")

    def test_health_stale(self):
        self.health(ts_ms=NOW - 120_000)
        self.fails("health", contains="health_age_s")

    def test_health_classified_reason_passes_only_with_signed_list(self):
        self.health(state="DEGRADED", reasons=["incident:x"])
        cl = os.path.join(self.td.name, "class.json")
        wj(cl, {"schema": "p2f-g3-hard-reason-classification-v1", "signed_by": "owner", "signed_at": "2026-10-08",
                "entries": [{"reason": "incident:x", "evidence": "path"}]})
        self.x["hard_reason_classification"] = cl
        self.assertNotIn("health", self.ev()["failed"])
        wj(cl, {"schema": "p2f-g3-hard-reason-classification-v1", "entries": [{"reason": "incident:x", "evidence": "p"}]})
        self.fails("health", contains="unsigned")

    # ---- incidents
    def test_incident_active_unacked_degraded(self):
        p = os.path.join(self.x["dataset"], "incidents", "state.json")
        s = json.load(open(p))
        s["incidents"].append({"id": "inc-9-6fd4edbc-9", "key": "certification_failed", "severity": "DEGRADED",
                               "active": True, "ack": None, "count": 1, "first_ms": 9, "last_ms": 9})
        wj(p, s)
        self.fails("incidents", contains="active unacked DEGRADED")

    def test_incident_unacked_critical_fails_ab_gate(self):
        p = os.path.join(self.x["dataset"], "incidents", "state.json")
        s = json.load(open(p))
        s["incidents"][0]["ack"] = None
        wj(p, s)
        v = self.fails("incidents", contains="AB.gate")
        self.assertTrue(next(c for c in v["checks"] if c["check"] == "incidents")["ab_gate"])

    def test_incident_rotation_warning_in_current_run(self):
        p = os.path.join(self.x["dataset"], "incidents", "state.json")
        s = json.load(open(p))
        s["incidents"].append({"id": f"inc-9-{BOOT[:8]}-3", "key": "rotation_handoff_incomplete:conn0-book",
                               "severity": "WARNING", "active": True, "ack": None, "count": 1, "first_ms": 9, "last_ms": 9})
        wj(p, s)
        self.fails("incidents", contains="rotation/sequence incident")

    # ---- rotation
    def test_rotation_not_yet_observed(self):
        self.health(counters={"handoffs": 0}, rotation={"events": []})
        self.fails("rotation", contains="no observed 1.5.0 rotation")

    def test_rotation_unresolved_class(self):
        self.health(counters={"handoff_classes": {"proven": 60, "unresolved": 2}})
        self.fails("rotation", contains="unresolved")

    def test_rotation_seq_reset(self):
        self.health(counters={"seq_reset": 1, "seq_reset_causes": {"catchup_timeout": 1}})
        self.fails("rotation", contains="seq_reset=1")

    def test_rotation_incomplete_handoff_event(self):
        p = os.path.join(self.x["dataset"], "health", "collector_health.json")
        h = json.load(open(p))
        h["rotation"]["events"][0]["handoff"].update(complete=False, reason="timeout")
        wj(p, h)
        self.fails("rotation", contains="reason=timeout")

    def test_rotation_lifecycle_record_missing(self):
        lc = os.path.join(self.x["dataset"], "raw", "lifecycle", "2026-10-08")
        os.rename(os.path.join(lc, f"lifecycle-20261008T00Z-{BOOT[:8]}-0001.jsonl.gz"),
                  os.path.join(lc, f"lifecycle-20261008T00Z-{BOOT[:8]}-0001.jsonl.gz.partial"))
        self.fails("rotation", contains="ws_handoff records=0")

    def test_rotation_lifecycle_seq_reset_record(self):
        lc = os.path.join(self.x["dataset"], "raw", "lifecycle", "2026-10-08")
        with gzip.open(os.path.join(lc, f"lifecycle-20261008T01Z-{BOOT[:8]}-0002.jsonl.gz"), "wt") as fh:
            fh.write(json.dumps({"boot_id": BOOT, "payload": {"event": "seq_reset", "stream": "x"}}) + "\n")
        self.fails("rotation", contains="lifecycle seq_reset")

    # ---- day lifecycle
    def test_lifecycle_missing_restore_test(self):
        wt(self.x["seal_log"], '{"restore_test": "PASS", "day": "2026-10-05", "totals": {"unexplained": 0}}\n')
        self.fails("day_lifecycle", contains="2026-10-07: no restore-test PASS")

    def test_lifecycle_missing_seal(self):
        os.unlink(os.path.join(self.x["dataset"], "seals", "2026-10-07.json"))
        self.fails("day_lifecycle", contains="2026-10-07")

    def test_lifecycle_backup_mismatch(self):
        wj(os.path.join(self.x["backup_root"], "p2-forward-continuous-v1", "2026-10-05", "BACKUP.json"),
           {"day": "2026-10-05", "seal_sha256": "0" * 64})
        self.fails("day_lifecycle", contains="BACKUP.json")

    def test_lifecycle_disposition_doc_changed(self):
        wt(self.x["day_dispositions"]["2026-10-06"]["doc"], "edited\n", "a")
        self.fails("day_lifecycle", contains="disposition doc")

    def test_lifecycle_disposition_missing(self):
        self.x["day_dispositions"] = {}
        self.fails("day_lifecycle", contains="2026-10-06")

    def test_lifecycle_yesterday_not_closed(self):
        os.unlink(os.path.join(self.x["dataset"], "days", "2026-10-07.json"))
        self.fails("day_lifecycle", contains="not closed")

    # ---- monitor
    def test_monitor_stale(self):
        sp = os.path.join(self.x["monitor_out"], "status.json")
        os.utime(sp, (NOW / 1000 - 600, NOW / 1000 - 600))
        self.fails("monitor", contains="age_s")

    def test_monitor_bound_to_old_container(self):
        wj(self.x["binding_file"], {"cid": "ab" * 32})
        self.fails("monitor", contains="binding cid")

    def test_monitor_not_the_unit(self):
        self.fx["unit"]["MainPID"] = "999"
        self.fails("monitor", contains="MainPID")

    def test_monitor_not_limit_aware(self):
        sp = os.path.join(self.x["monitor_out"], "status.json")
        s = json.load(open(sp))
        del s["limits"]
        wj(sp, s)
        os.utime(sp, (NOW / 1000 - 10, NOW / 1000 - 10))
        self.fails("monitor", contains="not limit-aware")

    def test_monitor_degraded(self):
        sp = os.path.join(self.x["monitor_out"], "status.json")
        s = json.load(open(sp))
        s["severity"] = "DEGRADED"
        wj(sp, s)
        os.utime(sp, (NOW / 1000 - 10, NOW / 1000 - 10))
        self.fails("monitor", contains="severity=DEGRADED")

    # ---- run chain
    def test_run_chain_fail(self):
        self.fx["run_chain"] = dict(self.fx["run_chain"], PASS=False, failures={"RUN_CHAIN": 1}, _rc=1)
        self.fails("run_chain")

    def test_run_chain_last_run_is_not_the_running_boot(self):
        self.fx["run_chain"]["runs"] = self.fx["run_chain"]["runs"][:1]
        self.fails("run_chain", contains="not the running boot")

    # ---- windows
    def test_window_hourly_seal(self):
        self.fails("windows", now=ms("2026-10-08T03:15:00Z"), contains="hourly_seal_backup_03")

    def test_window_operation_would_cross_into_next_hourly_window(self):
        self.fails("windows", now=ms("2026-10-08T03:50:00Z"), contains="hourly_seal_backup_04")

    def test_window_rotation_margin(self):
        self.health(universe_epoch={"next_refresh_ms": ms("2026-10-08T03:45:00Z")})
        self.fails("windows", contains="universe_refresh_transition")
        self.health(universe_epoch={"next_refresh_ms": ms("2026-10-09T00:10:00Z")},
                    connection_age_s={"conn0-book": 82800 - 600, "conn1-depth": 12000})
        self.fails("windows", contains="proactive:conn0-book")

    def test_window_day_end_and_seal(self):
        self.fails("windows", now=ms("2026-10-08T23:40:00Z"), contains="day_end")
        self.fails("windows", now=ms("2026-10-08T01:30:00Z"), contains="seal_universe_01:10-01:45")

    def test_window_universe_refresh_degraded_is_uncertain(self):
        self.health(universe_epoch={"refresh_degraded": "retry"})
        self.fails("windows", contains="uncertain")

    # ---- rollback
    def test_rollback_tar_sha(self):
        wt(self.x["rollback"]["tar"], b"x", "ab")
        self.fails("rollback", contains="tar content")

    def test_rollback_compose_already_edited(self):
        c = self.x["compose_file"]
        wt(c, open(c).read().replace("cpus: 0.5", "cpus: 1.5"))
        self.fails("rollback", contains="compose.yml sha256")

    def test_rollback_compose_backup_missing_or_writable(self):
        bk = self.x["rollback"]["compose_backup"]
        os.chmod(bk, 0o644)
        self.fails("rollback", contains="writable")
        os.unlink(bk)
        self.fails("rollback", contains="compose backup")

    def test_rollback_previous_image_missing(self):
        del self.fx["images"][OLD_TAG]
        self.fails("rollback", contains="previous (1.4.0) image")

    def test_missing_health_file_fails_everything_dependent(self):
        os.unlink(os.path.join(self.x["dataset"], "health", "collector_health.json"))
        v = self.ev()
        self.assertEqual(v["verdict"], "FAIL")
        for c in ("identity", "health", "windows"):
            self.assertIn(c, v["failed"])

    def test_cli_refuses_output_inside_dataset_and_bad_expect(self):
        ep = os.path.join(self.td.name, "expect.json")
        wj(ep, self.x)
        self.assertEqual(G.main(["check", "--expect", ep, "--json", os.path.join(self.x["dataset"], "o.json")]), 2)
        wj(ep, dict(self.x, schema="other"))
        self.assertEqual(G.main(["check", "--expect", ep]), 2)


# ===================================================================== bounded waiter
class Waiter(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.x, self.fx = build(self.td.name)
        self.t = [NOW]
        self.log = os.path.join(self.td.name, "w.jsonl")

    def tearDown(self):
        self.td.cleanup()

    def clock(self):
        return self.t[0]

    def run_w(self, max_s=600, until="never", mutate=None):
        calls = []

        def sleep(s):
            self.t[0] += int(s * 1000)
            calls.append(s)
            if mutate and len(calls) == 1:
                mutate()
            for p in (os.path.join(self.x["dataset"], "health", "collector_health.json"),):
                h = json.load(open(p))
                h["ts_ms"] = self.t[0] - 1000
                wj(p, h)
            sp = os.path.join(self.x["monitor_out"], "status.json")
            s = json.load(open(sp))
            s["t_ms"] = self.t[0] - 1000
            wj(sp, s)
            os.utime(sp, (self.t[0] / 1000, self.t[0] / 1000))

        rc = G.watch(FakeEnv(self.x, self.fx), self.x, max_s, 30, until, self.log, sleep=sleep, clock=self.clock)
        with open(self.log) as fh:
            return rc, [json.loads(line) for line in fh]

    def test_timeout_is_a_failure_exit(self):
        rc, recs = self.run_w(max_s=120)
        self.assertEqual(rc, 4)
        self.assertEqual(recs[-1]["event"], "timeout")

    def test_new_incident_stops(self):
        def mutate():
            p = os.path.join(self.x["dataset"], "incidents", "state.json")
            s = json.load(open(p))
            s["incidents"].append({"id": f"inc-9-{BOOT[:8]}-4", "key": "seq_reset", "severity": "DEGRADED",
                                   "active": True, "ack": None, "count": 1})
            wj(p, s)
        rc, recs = self.run_w(mutate=mutate)
        self.assertEqual(rc, 3)
        self.assertIn("new incident ids", " ".join(recs[-1]["why"]))

    def test_monitor_alert_line_stops(self):
        def mutate():
            with open(os.path.join(self.x["monitor_out"], "alerts.jsonl"), "a") as fh:
                fh.write(json.dumps({"severity": "DEGRADED", "kind": "entry", "reasons": ["health:DEGRADED"]}) + "\n")
        rc, recs = self.run_w(mutate=mutate)
        self.assertEqual(rc, 3)
        self.assertIn("monitor alert DEGRADED", " ".join(recs[-1]["why"]))

    def test_health_degraded_stops(self):
        def mutate():
            p = os.path.join(self.x["dataset"], "health", "collector_health.json")
            h = json.load(open(p))
            h.update(state="DEGRADED", reasons=["stale:x"])
            wj(p, h)
        rc, recs = self.run_w(mutate=mutate)
        self.assertEqual(rc, 3)

    def test_new_failed_seal_or_external_incident_stops(self):
        def mutate():
            wj(os.path.join(self.x["dataset"], "incidents", "external", "seal-2026-10-07-1.json"), {"result": "FAIL"})
        rc, recs = self.run_w(mutate=mutate)
        self.assertEqual(rc, 3)
        self.assertIn("external incident", " ".join(recs[-1]["why"]))

    def test_until_pass_returns_zero_when_gate_passes(self):
        rc, recs = self.run_w(until="pass")
        self.assertEqual(rc, 0)
        self.assertEqual(recs[-1]["event"], "pass")

    def test_cli_requires_hard_deadline(self):
        ep = os.path.join(self.td.name, "expect.json")
        wj(ep, self.x)
        self.assertEqual(G.main(["watch", "--expect", ep]), 2)
        self.assertEqual(G.main(["watch", "--expect", ep, "--max-s", "999999"]), 2)


if __name__ == "__main__":
    unittest.main()
