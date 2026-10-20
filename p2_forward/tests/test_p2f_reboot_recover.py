"""CHG-03: gated Collector recovery after host reboot. Deterministic, offline: a fake host (no Docker, no systemd,
no network except one closed localhost port) and fixture datasets in temp dirs. Stdlib only."""
import configparser
import fcntl
import hashlib
import importlib.util
import json
import os
import pathlib
import secrets
import shutil
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
OPS = ROOT / "ops"
UNIT = OPS / "systemd" / "tsb-p2f-recover.service"
STOP_UNIT = OPS / "systemd" / "tsb-p2f-shutdown-stop.service"


def load(name, path):
    import sys
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sys.path.insert(0, str(path.parent))
    sp.loader.exec_module(m)
    return m


R = load("chg03_recover", OPS / "p2f_reboot_recover.py")
IMG = "sha256:" + "cd" * 32
H = 3_600_000
BOOT_START = 1_800_000_000_000            # current host boot start (ms)
PREV_END = BOOT_START - 15 * 60_000       # previous host boot's last journal entry
PAPER = ["trading_scanner", "trading_tracker", "postgres"]


def tree_hash(d, skip=()):
    h = hashlib.sha256()
    for root, dirs, files in sorted(os.walk(d)):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, d)
            if rel.split(os.sep)[0] in skip:
                continue
            h.update(rel.encode() + b"\0" + open(p, "rb").read())
    return h.hexdigest()


class Fixture:
    """A dataset + ops dir shaped like production: runs/, control/, incidents/, quarantine/, health/, configs."""

    def __init__(self, tmp, *, clean_stop=None, run_created=PREV_END - 5 * H, health_ts=PREV_END - 2_000,
                 critical=False):
        self.tmp = pathlib.Path(tmp)
        self.data = self.tmp / "dataset"
        self.ops = self.tmp / "ops"
        for d in ("runs", "control", "incidents/ack", "quarantine", "health", "seals", "days"):
            (self.data / d).mkdir(parents=True)
        (self.ops / "monitor" / "p2-forward-continuous-v1").mkdir(parents=True)
        (self.ops / "monitor" / "p2-forward-continuous-v1" / "status.json").write_text('{"severity":"STOPPED"}')
        (self.data / "dataset.json").write_text(json.dumps({"dataset_id": "p2-forward-continuous-v1"}))
        (self.data / "seals" / "2026-10-18.json").write_text('{"PASS": true}')
        self.prev = secrets.token_hex(16)                 # dynamic previous run id: never a fixed value
        self.write_run(self.prev, run_created, None)
        if clean_stop is not None:
            (self.data / "control" / f"stop-{self.prev[:8]}.json").write_text(json.dumps(
                {"boot_id": self.prev, "state": "STOPPED" if clean_stop else "FAILED",
                 "exit_code": 0 if clean_stop else 6, "reason": "signal" if clean_stop else "fail_closed"}))
        incs = [{"id": "inc-1-aaaa-1", "key": "observation_loss:tier0", "severity": "WARNING", "active": True,
                 "ack": None, "first_ms": 1, "last_ms": 1, "count": 1, "boot8": "aaaaaaaa"}]
        if critical:
            incs.append({"id": "inc-2-bbbb-1", "key": "failclosed:writer_stalled", "severity": "CRITICAL",
                         "active": True, "ack": None, "first_ms": 2, "last_ms": 2, "count": 1, "boot8": "bbbbbbbb"})
        (self.data / "incidents" / "state.json").write_text(json.dumps({"incidents": incs, "updated_ms": 3}))
        (self.data / "health" / "collector_health.json").write_text(json.dumps(
            {"boot_id": self.prev, "ts_ms": health_ts, "state": "HEALTHY", "write_errors": 0,
             "writer": {"alive": True, "beat_age_ms": 100}, "certifier": {"alive": True}}))
        self.config = self.ops / "continuous-v1.json"
        self.config.write_text(json.dumps({"dataset_id": "p2-forward-continuous-v1", "mode": "continuous"}))
        self.compose = self.ops / "compose.yml"
        self.compose.write_text('services:\n  collector:\n    restart: "no"\n')
        self.cfg = {"dataset_dir": str(self.data), "config_file": str(self.config),
                    "config_sha256": R.sha256_file(self.config), "compose_file": str(self.compose),
                    "compose_sha256": R.sha256_file(self.compose), "image_tag": "tsb-p2-forward:test",
                    "image_id": IMG, "container": "tsb-p2-forward-collector",
                    "state_dir": str(self.ops / "recovery"), "monitor_dir": str(self.ops / "monitor"),
                    "paper_containers": PAPER, "docker_wait_s": 30, "health_wait_s": 60}

    def write_run(self, boot, created, prev):
        (self.data / "runs" / f"run-{boot}.json").write_text(json.dumps(
            {"boot_id": boot, "created_ms": created,
             "previous_run": None if prev is None else {"boot_id": prev, "clean_stop": False}}))

    def config_for(self, **over):
        p = self.tmp / "recover.json"
        cfg = {**self.cfg, **over}
        p.write_text(json.dumps(cfg))
        return R.load_config(str(p))


class FakeHost:
    """Records every action. ``run_up`` behaves like p2f_continuous_up.sh's previous-run gate and then plays the
    collector: a new run record (with lineage), a downtime record and a health file."""

    def __init__(self, fx, *, orderly=True, docker_ready_after_s=0, running=False, image=IMG, up_rc=0,
                 exits_after_start=False, bind_rc=0, disk=500.0, mem=20_000.0, paper_changes=False,
                 healthy=True):
        self.fx, self.orderly, self.ready_at = fx, orderly, BOOT_START + 60_000 + docker_ready_after_s * 1000
        self.t = BOOT_START + 60_000
        self.running, self.image, self.up_rc = running, image, up_rc
        self.exits_after_start, self.bind_rc, self.disk, self.mem = exits_after_start, bind_rc, disk, mem
        self.paper_changes, self.healthy = paper_changes, healthy
        self.calls, self.alerts, self.up_env = [], [], None
        self.boot_id = secrets.token_hex(16)
        self.paper = [f"/{n} id{n} img started 0 running" for n in PAPER]
        self.new_run = None

    def now_ms(self):
        return self.t

    def sleep(self, s):
        self.t += int(s * 1000)

    def docker_ready(self):
        self.calls.append("docker_ready")
        return self.t >= self.ready_at

    def container_state(self, name):
        self.calls.append(("inspect", name))
        if name != self.fx.cfg["container"]:
            raise AssertionError("only the collector may be inspected through container_state")
        return {"running": self.running, "status": "running" if self.running else "exited", "exit_code": 255,
                "id": "c" * 64, "image": IMG, "restart_policy": "no"}

    def image_id(self, tag):
        return self.image

    def paper_snapshot(self, names):
        self.calls.append(("paper_snapshot", tuple(names)))
        snap = list(self.paper)
        if self.paper_changes and self.new_run:
            snap[0] = snap[0].replace("started 0", "started 1")
        return snap

    def disk_free_gb(self, path):
        return self.disk

    def mem_available_mb(self):
        return self.mem

    def host_boots(self):
        return {"current": {"boot_id": self.boot_id, "start_ms": BOOT_START},
                "previous": {"boot_id": "p" * 32, "end_ms": PREV_END, "orderly": self.orderly}}

    def docker_inspect_json(self, name):
        return '[{"State": {"ExitCode": 255}}]'

    def docker_logs(self, name):
        return ""

    def run_up(self, env_extra, timeout):
        self.calls.append(("run_up", dict(env_extra)))
        self.up_env = dict(env_extra)
        if self.up_rc:
            return self.up_rc, "REFUSED: test"
        latest = R.latest_run_record(self.fx.cfg["dataset_dir"])
        clean = (pathlib.Path(self.fx.cfg["dataset_dir"]) / "control" / f"stop-{latest['boot_id'][:8]}.json")
        if not clean.exists() and env_extra.get("P2F_ACK_PREVIOUS") != latest["boot_id"][:8]:
            return 2, "REFUSED: previous run did not stop cleanly"
        self.new_run = secrets.token_hex(16)
        self.fx.write_run(self.new_run, self.t, latest["boot_id"])
        (self.fx.data / "runs" / f"downtime-{self.new_run}.json").write_text(json.dumps({"until_ms": self.t}))
        (self.fx.data / "health" / "collector_health.json").write_text(json.dumps(
            {"boot_id": self.new_run, "ts_ms": self.t, "state": "DEGRADED", "reasons": ["x"],
             "write_errors": 0 if self.healthy else 3,
             "writer": {"alive": True, "beat_age_ms": 50}, "certifier": {"alive": True}}))
        self.running = not self.exits_after_start
        return 0, "UP OK test"

    def run_bind(self, reason, timeout):
        self.calls.append(("run_bind", reason))
        return self.bind_rc, "bound" if self.bind_rc == 0 else "mismatch"

    def send_alert(self, text):
        self.alerts.append(text)
        return True, None


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="chg03-")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def fx(self, **kw):
        return Fixture(self._tmp, **kw)

    def ups(self, host):
        return [c for c in host.calls if isinstance(c, tuple) and c[0] == "run_up"]


class TestRecovery(Base):
    def test_clean_reboot_recovers_without_ack_and_records_everything(self):
        fx = self.fx(clean_stop=True)
        cfg, host = fx.config_for(), None
        host = FakeHost(fx)
        rep = R.run(cfg, host)
        self.assertEqual((rep["outcome"], rep["classification"]), (R.RECOVERED, R.CLEAN_STOP), rep)
        self.assertEqual(host.up_env, {})                                  # no ack needed for a clean stop
        self.assertEqual(rep["previous_run"], fx.prev)
        self.assertEqual(rep["new_run"], host.new_run)
        led = R.read_ledger(cfg)
        self.assertEqual([r["kind"] for r in led], ["ATTEMPT", "OUTCOME"])
        self.assertTrue(R.verify_ledger_chain(cfg))
        self.assertTrue(os.path.isfile(rep["report_file"]))
        self.assertTrue(rep["downtime_record"] and rep["evidence_files"] >= 3)
        self.assertEqual(rep["paper_before"], rep["paper_after"])
        self.assertEqual(len(host.alerts), 1)
        self.assertIn("RECOVERED", host.alerts[0])

    def test_orderly_reboot_unclean_stop_needs_operator_ack_by_default(self):
        fx = self.fx()                                                     # no stop marker
        host = FakeHost(fx, orderly=True)
        rep = R.run(fx.config_for(), host)
        self.assertEqual((rep["outcome"], rep["reason"]), (R.MANUAL, "unclean_stop_needs_operator_ack"))
        self.assertEqual(rep["classification"], R.ORDERLY_REBOOT_UNCLEAN)
        self.assertEqual(self.ups(host), [])
        self.assertIn("Manual action needed", host.alerts[0])

    def test_orderly_reboot_with_owner_policy_derives_ack_dynamically(self):
        fx = self.fx()
        host = FakeHost(fx, orderly=True)
        rep = R.run(fx.config_for(policy={"auto_ack_previous_on_orderly_reboot": True}), host)
        self.assertEqual(rep["outcome"], R.RECOVERED, rep)
        self.assertEqual(host.up_env, {"P2F_ACK_PREVIOUS": fx.prev[:8]})   # from the dataset, not a constant
        self.assertTrue(R.read_ledger(fx.config_for())[0]["auto_ack"])

    def test_power_loss_or_unverified_shutdown_is_never_automatic(self):
        fx = self.fx()
        host = FakeHost(fx, orderly=False)
        rep = R.run(fx.config_for(policy={"auto_ack_previous_on_orderly_reboot": True}), host)
        self.assertEqual((rep["outcome"], rep["classification"]), (R.MANUAL, R.POWER_LOSS_OR_UNVERIFIED))
        self.assertEqual(self.ups(host), [])

    def test_collector_crash_on_the_same_boot_is_never_automatic(self):
        fx = self.fx(run_created=BOOT_START + 1000, health_ts=BOOT_START + 5000)
        rep = R.run(fx.config_for(policy={"auto_ack_previous_on_orderly_reboot": True}), FakeHost(fx))
        self.assertEqual((rep["outcome"], rep["classification"]), (R.MANUAL, R.CRASH_SAME_BOOT))

    def test_collector_that_died_long_before_the_shutdown_is_not_a_reboot_case(self):
        fx = self.fx(health_ts=PREV_END - 6 * H)
        rep = R.run(fx.config_for(policy={"auto_ack_previous_on_orderly_reboot": True}), FakeHost(fx))
        self.assertEqual(rep["classification"], R.DIED_BEFORE_SHUTDOWN)
        self.assertEqual(rep["outcome"], R.MANUAL)

    def test_fail_closed_stop_marker_is_never_automatic(self):
        fx = self.fx(clean_stop=False)
        host = FakeHost(fx)
        rep = R.run(fx.config_for(policy={"auto_ack_previous_on_orderly_reboot": True}), host)
        self.assertEqual((rep["outcome"], rep["classification"]), (R.MANUAL, R.FAILED_STOP))
        self.assertEqual(self.ups(host), [])

    def test_collector_already_running_is_a_noop(self):
        fx = self.fx(clean_stop=True)
        host = FakeHost(fx, running=True)
        rep = R.run(fx.config_for(), host)
        self.assertEqual(rep["outcome"], R.NOOP_RUNNING)
        self.assertEqual(self.ups(host), [])
        self.assertEqual(R.read_ledger(fx.config_for()), [])
        self.assertEqual(host.alerts, [])

    def test_blocking_critical_incident_is_never_bypassed_or_acknowledged(self):
        fx = self.fx(clean_stop=True, critical=True)
        before = tree_hash(fx.data / "incidents")
        host = FakeHost(fx)
        rep = R.run(fx.config_for(policy={"auto_ack_previous_on_orderly_reboot": True}), host)
        self.assertEqual((rep["outcome"], rep["reason"]), (R.MANUAL, "blocking_critical_incident"))
        self.assertEqual(rep["detail"], ["inc-2-bbbb-1"])
        self.assertEqual(self.ups(host), [])
        self.assertEqual(tree_hash(fx.data / "incidents"), before)        # no ack written, nothing changed

    def test_image_digest_mismatch_refuses(self):
        fx = self.fx(clean_stop=True)
        host = FakeHost(fx, image="sha256:" + "ee" * 32)
        rep = R.run(fx.config_for(), host)
        self.assertEqual((rep["outcome"], rep["reason"]), (R.MANUAL, "image_id_mismatch"))
        self.assertEqual(self.ups(host), [])

    def test_configuration_and_compose_drift_refuse(self):
        for mutate, reason in ((lambda f: f.config.write_text('{"dataset_id": "other"}'), "config_drift"),
                               (lambda f: f.compose.write_text('restart: "always"\n'), "compose_drift"),
                               (lambda f: f.config.unlink(), "config_missing")):
            with self.subTest(reason=reason):
                shutil.rmtree(self._tmp)
                os.makedirs(self._tmp)
                fx = self.fx(clean_stop=True)
                cfg = fx.config_for()
                mutate(fx)
                host = FakeHost(fx)
                rep = R.run(cfg, host)
                self.assertEqual((rep["outcome"], rep["reason"]), (R.MANUAL, reason))
                self.assertEqual(self.ups(host), [])

    def test_compose_whose_restart_policy_is_not_no_refuses_even_if_reviewed(self):
        fx = self.fx(clean_stop=True)
        fx.compose.write_text('services:\n  collector:\n    restart: on-failure\n')
        rep = R.run(fx.config_for(compose_sha256=R.sha256_file(fx.compose)), FakeHost(fx))
        self.assertEqual(rep["reason"], "compose_restart_policy_not_no")

    def test_missing_evidence_or_dataset_refuses(self):
        fx = self.fx(clean_stop=True)
        shutil.rmtree(fx.data / "quarantine")
        rep = R.run(fx.config_for(), FakeHost(fx))
        self.assertEqual((rep["outcome"], rep["reason"]), (R.MANUAL, "evidence_source_missing"))
        fx2 = Fixture(tempfile.mkdtemp(dir=self._tmp), clean_stop=True)
        (fx2.data / "dataset.json").unlink()
        self.assertEqual(R.run(fx2.config_for(), FakeHost(fx2))["reason"], "dataset_unavailable")

    def test_insufficient_disk_or_memory_refuses(self):
        fx = self.fx(clean_stop=True)
        self.assertEqual(R.run(fx.config_for(), FakeHost(fx, disk=99.0))["reason"], "insufficient_disk")
        fx2 = Fixture(tempfile.mkdtemp(dir=self._tmp), clean_stop=True)
        self.assertEqual(R.run(fx2.config_for(), FakeHost(fx2, mem=500.0))["reason"], "insufficient_memory")

    def test_concurrent_attempt_is_locked_out(self):
        fx = self.fx(clean_stop=True)
        cfg = fx.config_for()
        os.makedirs(cfg["state_dir"], exist_ok=True)
        with open(os.path.join(cfg["state_dir"], ".recover.lock"), "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            host = FakeHost(fx)
            rep = R.run(cfg, host)
        self.assertEqual(rep["outcome"], R.LOCKED)
        self.assertEqual(self.ups(host), [])
        self.assertEqual(R.read_ledger(cfg), [])

    def test_docker_not_ready_waits_bounded_then_refuses(self):
        fx = self.fx(clean_stop=True)
        host = FakeHost(fx, docker_ready_after_s=10_000)
        rep = R.run(fx.config_for(docker_wait_s=30), host)
        self.assertEqual((rep["outcome"], rep["reason"]), (R.MANUAL, "docker_not_ready"))
        self.assertLessEqual(host.calls.count("docker_ready"), 8)
        fx2 = Fixture(tempfile.mkdtemp(dir=self._tmp), clean_stop=True)
        self.assertEqual(R.run(fx2.config_for(docker_wait_s=30), FakeHost(fx2, docker_ready_after_s=12))
                         ["outcome"], R.RECOVERED)

    def test_monitor_rebind_failure_is_reported_as_failed(self):
        fx = self.fx(clean_stop=True)
        host = FakeHost(fx, bind_rc=3)
        rep = R.run(fx.config_for(), host)
        self.assertEqual((rep["outcome"], rep["reason"]), (R.FAILED, "monitor_rebind_failed"))
        self.assertIn("Manual action needed", host.alerts[0])

    def test_startup_failure_and_exit_after_start_are_failed(self):
        fx = self.fx(clean_stop=True)
        self.assertEqual(R.run(fx.config_for(), FakeHost(fx, up_rc=2))["reason"], "gated_start_refused_or_failed")
        fx2 = Fixture(tempfile.mkdtemp(dir=self._tmp), clean_stop=True)
        self.assertEqual(R.run(fx2.config_for(), FakeHost(fx2, exits_after_start=True))["reason"],
                         "collector_exited_after_start")
        fx3 = Fixture(tempfile.mkdtemp(dir=self._tmp), clean_stop=True)
        self.assertEqual(R.run(fx3.config_for(), FakeHost(fx3, healthy=False))["reason"], "health_not_verified")

    def test_one_attempt_per_host_boot_and_failure_circuit(self):
        fx = self.fx(clean_stop=True)
        cfg = fx.config_for()
        h1 = FakeHost(fx, up_rc=2)
        self.assertEqual(R.run(cfg, h1)["outcome"], R.FAILED)
        again = FakeHost(fx)
        again.boot_id = h1.boot_id                                           # same host boot
        self.assertEqual(R.run(cfg, again)["reason"], "already_attempted_this_host_boot")
        self.assertEqual(self.ups(again), [])
        self.assertEqual(R.run(cfg, FakeHost(fx, up_rc=2))["outcome"], R.FAILED)   # next boot, fails again
        blocked = FakeHost(fx)
        rep = R.run(cfg, blocked)
        self.assertEqual((rep["outcome"], rep["reason"]), (R.MANUAL, "failure_circuit_open"))
        self.assertEqual(self.ups(blocked), [])
        R.append_ledger(cfg, {"kind": "RESET", "at_ms": 1, "by": "owner", "reason": "reviewed"})
        self.assertEqual(R.run(cfg, FakeHost(fx))["outcome"], R.RECOVERED)
        self.assertTrue(R.verify_ledger_chain(cfg))

    def test_previous_run_is_never_recovered_twice(self):
        fx = self.fx(clean_stop=True)
        cfg = fx.config_for()
        h = FakeHost(fx)
        self.assertEqual(R.run(cfg, h)["outcome"], R.RECOVERED)
        # tamper: make the old run look newest again
        (fx.data / "runs" / f"run-{h.new_run}.json").unlink()
        rep = R.run(cfg, FakeHost(fx))
        self.assertIn(rep["reason"], ("previous_run_already_recovered_once", "not_auto_eligible:UNKNOWN"))
        self.assertEqual(rep["outcome"], R.MANUAL)

    def test_tampered_ledger_refuses(self):
        fx = self.fx(clean_stop=True)
        cfg = fx.config_for()
        R.append_ledger(cfg, {"kind": "OUTCOME", "outcome": R.FAILED})
        R.append_ledger(cfg, {"kind": "OUTCOME", "outcome": R.FAILED})
        p = R.ledger_path(cfg)
        lines = open(p).read().splitlines(keepends=True)
        open(p, "w").write(lines[1])                                         # drop the first record
        self.assertEqual(R.run(cfg, FakeHost(fx))["reason"], "ledger_chain_broken")

    def test_paper_change_during_recovery_is_failed_and_paper_is_only_inspected(self):
        fx = self.fx(clean_stop=True)
        host = FakeHost(fx, paper_changes=True)
        rep = R.run(fx.config_for(), host)
        self.assertEqual((rep["outcome"], rep["reason"]), (R.FAILED, "paper_containers_changed"))
        paper_calls = [c for c in host.calls if isinstance(c, tuple) and any(n in str(c) for n in PAPER)]
        self.assertTrue(all(c[0] == "paper_snapshot" for c in paper_calls))

    def test_dataset_history_is_never_modified(self):
        fx = self.fx(clean_stop=True)
        keep = ("seals", "days", "control", "incidents", "quarantine", "dataset.json")
        before = {k: tree_hash(fx.data / k) if (fx.data / k).is_dir() else R.sha256_file(fx.data / k) for k in keep}
        R.run(fx.config_for(), FakeHost(fx))
        after = {k: tree_hash(fx.data / k) if (fx.data / k).is_dir() else R.sha256_file(fx.data / k) for k in keep}
        self.assertEqual(before, after)

    def test_evidence_copy_matches_sources(self):
        fx = self.fx(clean_stop=True)
        rep = R.run(fx.config_for(), FakeHost(fx))
        ev = pathlib.Path(rep["report_dir"]) / "evidence"
        for ln in (ev / "SHA256SUMS").read_text().splitlines():
            h, rel = ln.split("  ", 1)
            self.assertEqual(R.sha256_file(ev / rel), h)
        self.assertTrue((ev / "monitor").is_dir() and (ev / "collector_inspect.json").is_file())

    def test_status_is_read_only(self):
        fx = self.fx()
        cfg = fx.config_for()
        before = tree_hash(self._tmp)
        out = R.status(cfg, FakeHost(fx))
        self.assertEqual(out["classification"], R.ORDERLY_REBOOT_UNCLEAN)
        self.assertEqual(tree_hash(self._tmp), before)


class TestContract(Base):
    def test_config_requires_explicit_paths_and_boolean_policy(self):
        fx = self.fx()
        p = pathlib.Path(self._tmp) / "bad.json"
        p.write_text(json.dumps({**fx.cfg, "image_id": ""}))
        with self.assertRaises(R.Stop):
            R.load_config(str(p))
        p.write_text(json.dumps({**fx.cfg, "policy": {"auto_ack_previous_on_orderly_reboot": "yes"}}))
        with self.assertRaises(R.Stop):
            R.load_config(str(p))
        self.assertFalse(fx.config_for()["policy"]["auto_ack_previous_on_orderly_reboot"])   # default off

    def test_recover_unit_is_a_oneshot_without_restart(self):
        c = configparser.ConfigParser(interpolation=None, strict=False)
        c.read(UNIT)
        s = c["Service"]
        self.assertEqual(s["Type"], "oneshot")
        self.assertNotIn("Restart", s)
        self.assertIn("p2f_reboot_recover.py run --config", s["ExecStart"])
        self.assertEqual(c["Install"]["WantedBy"], "default.target")

    def test_shutdown_stop_unit_orders_before_docker_stops(self):
        c = configparser.ConfigParser(interpolation=None, strict=False)
        c.read(STOP_UNIT)
        self.assertEqual(c["Unit"]["After"], "docker.service")
        self.assertIn("p2f_continuous_stop.sh", c["Service"]["ExecStop"])
        self.assertGreaterEqual(int(c["Service"]["TimeoutStopSec"]), 460)   # > compose stop_grace_period 450 s

    def test_start_only_through_the_gated_script_and_no_ack_or_restart_policy_code(self):
        src = (OPS / "p2f_reboot_recover.py").read_text()
        self.assertIn("p2f_continuous_up.sh", src)
        for forbidden in ('"start"', '"restart"', '"run", "-d"', "--restart-policy", "update --restart",
                          "write_ack", "p2f_incident_ack", "docker\", \"compose", "unlock-holdout",
                          "trading_signals", "psql"):
            self.assertNotIn(forbidden, src, forbidden)

    def test_alert_failure_never_leaks_the_token(self):
        fx = self.fx()
        tok = "123456:" + secrets.token_urlsafe(24)
        env = pathlib.Path(self._tmp) / "env"
        env.write_text(f"TELEGRAM_BOT_TOKEN={tok}\nTELEGRAM_CHAT_ID=42\n")
        cfg = fx.config_for(alert={"enabled": True, "env_file": str(env), "api_base": "http://127.0.0.1:9"})
        ok, err = R.RealHost(cfg).send_alert("x")
        self.assertFalse(ok)
        self.assertNotIn(tok, str(err))
        host = FakeHost(fx)
        host.send_alert = R.RealHost(cfg).send_alert
        rep = R.run(cfg, host)
        blob = open(rep["report_file"]).read() + open(os.path.join(cfg["state_dir"], "alert_errors.log")).read()
        blob += open(R.ledger_path(cfg)).read()
        self.assertNotIn(tok, blob)


if __name__ == "__main__":
    unittest.main()
