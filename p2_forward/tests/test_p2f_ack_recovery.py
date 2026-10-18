"""Fail-closed recovery protocol (2026-10-06 deadlock fix): a CRITICAL fail-closed stop can be acknowledged while the
collector is STOPPED, through a hash-bound ack that the start gate validates, and the next run merges it through the
collector's normal IncidentLog.poll_acks path. Offline; real collector code on the fake exchange; the gate script runs
against a stub `docker` (no Docker, no network). Adversarial acks all fail closed.

Lifecycle: run A -> fail_closed("writer_stalled") (exit 6, CRITICAL, stop marker FAILED) -> gate refuses -> ack while
stopped -> gate passes only with P2F_ACK_PREVIOUS=<A> -> run B merges the ack, records downtime cause stopped_failed
-> run chain PASS -> run C fails closed again -> a NEW ack is required (old ack never reused)."""
import asyncio
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from p2_forward import app as A, config as C, incidents as I
from tests.test_p2cr_continuous import VC, UniverseShiftExchange, cont_cfg
from tests.test_verify_independent import ENV

ROOT = pathlib.Path(__file__).resolve().parents[1]
OPS = ROOT / "ops"
sys.path.insert(0, str(OPS))
import p2f_ack_binding as AB  # noqa: E402

IID = "sha256:" + "ab" * 32
STUB_DOCKER = r"""#!/bin/bash
# test stub: no Docker access. Records compose invocations; answers the gate's inspect / ps queries.
case "$1 $2" in
  "image inspect") echo "$STUB_IID" ;;
  "ps -q") echo "${STUB_RUNNING:-}" ;;
  "compose -p") echo "$*" >> "$STUB_LOG" ;;
  *) case "$*" in
       *"{{.Image}}"*) echo "$STUB_IID" ;;
       *"{{.Id}}"*) echo "stubcid" ;;
       *RestartPolicy*) echo "no" ;;
       *) echo "unexpected docker $*" >&2; exit 99 ;;
     esac ;;
esac
"""


def run_collector(d, seconds, fail_at=None):
    """One continuous run on the fake exchange; optionally the production fail_closed('writer_stalled') path."""
    cfg = cont_cfg(d, ws_rotation_s=82800, day_close_after_s=600, universe_refresh_at_s=600); C.validate(cfg)
    c = A.Collector(cfg)
    s = UniverseShiftExchange()
    c.session_factory = lambda: s

    async def main():
        loop = asyncio.get_running_loop()
        loop.call_later(seconds, c._signal_stop)
        if fail_at is not None:
            loop.call_later(fail_at, c.fail_closed, "writer_stalled", {"beat_age_ms": 61000, "injected": "test"})
        return await c.run()
    with mock.patch.dict(os.environ, ENV), contextlib.redirect_stderr(io.StringIO()):
        code = asyncio.run(main())
    return c, code


def jload(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def state(d):
    return jload(os.path.join(d, "incidents", "state.json"))["incidents"]


def events(d):
    with open(os.path.join(d, "incidents", "events.jsonl"), encoding="utf-8") as fh:
        return [json.loads(l) for l in fh]


class Ops:
    """The deployed operator scripts, run as subprocesses (ack tool and the full gate script with a stub docker)."""

    def __init__(self, tmp):
        self.bin = os.path.join(tmp, "bin"); os.makedirs(self.bin, exist_ok=True)
        p = os.path.join(self.bin, "docker")
        with open(p, "w") as fh:
            fh.write(STUB_DOCKER)
        os.chmod(p, 0o755)
        py = os.path.join(self.bin, "python3")
        if not os.path.exists(py):
            os.symlink(sys.executable, py)
        self.log = os.path.join(tmp, "compose_calls.log")
        self.cfg = os.path.join(tmp, "cfg.json")
        with open(self.cfg, "w") as fh:
            json.dump({"enabled": True, "mode": "continuous", "max_runtime_s": 0, "data_dir": "/data",
                       "dataset_id": "test-ds"}, fh)

    def env(self, **kw):
        return {"PATH": self.bin + ":/usr/bin:/bin", "STUB_IID": IID, "STUB_LOG": self.log, "HOME": "/tmp",
                "PYTHONDONTWRITEBYTECODE": "1", **kw}

    def ack(self, d, iid, by="operator", ref="evidence/dir", reason="reviewed: test", **kw):
        r = subprocess.run(["bash", str(OPS / "p2f_incident_ack.sh"), d, iid, by, ref, reason],
                           capture_output=True, text=True, env=self.env(**kw))
        return r.returncode, r.stdout + r.stderr

    def up(self, d, **kw):
        n0 = len(read(self.log).splitlines()) if os.path.exists(self.log) else 0
        r = subprocess.run(["bash", str(OPS / "p2f_continuous_up.sh"), "tsb-p2-forward:test", IID, d, self.cfg,
                            str(ROOT / "compose.yml")], capture_output=True, text=True, env=self.env(**kw))
        n1 = len(read(self.log).splitlines()) if os.path.exists(self.log) else 0
        return r.returncode, r.stdout + r.stderr, n1 > n0


class FailClosedAckRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); t = cls.tmp.name
        cls.base = os.path.join(t, "data")
        cls.ops = Ops(t)
        cls.a, cls.code_a = run_collector(cls.base, 40, fail_at=8)
        cls.boot_a = cls.a.boot_id
        cls.inc_a = [i for i in state(cls.base) if i["key"] == "failclosed:writer_stalled"][0]
        cls.stopped = cls.copy_of(cls.base, "stopped")                 # pristine post-fail-closed copy (no ack)
        cls.gate_no_ack = cls.ops.up(cls.base, P2F_ACK_PREVIOUS=cls.boot_a[:8])
        cls.ack_rc, cls.ack_out = cls.ops.ack(cls.base, cls.inc_a["id"], ref="collector-failclosed-recovery/evidence",
                                              reason="host stall reviewed; evidence preserved")
        cls.gate_no_prev = cls.ops.up(cls.base)
        cls.gate_wrong_prev = cls.ops.up(cls.base, P2F_ACK_PREVIOUS="deadbeef")
        cls.gate_ok = cls.ops.up(cls.base, P2F_ACK_PREVIOUS=cls.boot_a[:8])
        cls.ev_before_b = len(events(cls.base))
        cls.b, cls.code_b = run_collector(cls.base, 10)                  # the restart (gate passed)
        cls.state_after_b = state(cls.base)
        cls.ev_b = events(cls.base)[cls.ev_before_b:]
        cls.gate_after_clean_b = cls.ops.up(cls.base)                    # clean stop: no P2F_ACK_PREVIOUS needed
        cls.c, cls.code_c = run_collector(cls.base, 40, fail_at=8)     # a second CRITICAL in a later run

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def copy_of(cls, src, name):
        dst = os.path.join(cls.tmp.name, "copies", name)
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("raw", "manifests", "days", "seals", "health"))
        for root, dirs, _ in os.walk(dst):                               # copies must be writable to tamper with
            for x in dirs:
                os.chmod(os.path.join(root, x), 0o755)
        return dst

    def fresh(self, name):
        return self.copy_of(self.stopped, name)

    def put(self, d, iid, obj, raw=None):
        p = AB.ack_path(d, iid)
        with open(p, "w") as fh:
            fh.write(raw if raw is not None else json.dumps(obj))
        return p

    def bound(self, d, inc, **over):
        a = AB.build(d, inc, "op", "ref", "reason", inc["last_ms"] + 1)
        a.update(over)
        return a

    def rehash(self, a):
        body = {k: v for k, v in a.items() if k != "binding_sha256"}
        return {**body, "binding_sha256": AB.sha(body)}

    # ---- the stop ----
    def test_run_a_failed_closed_with_critical(self):
        self.assertEqual(self.code_a, A.EXIT_FAILCLOSED)
        mk = jload(os.path.join(self.base, "control", f"stop-{self.boot_a[:8]}.json"))
        self.assertEqual(mk["state"], "FAILED")
        self.assertEqual((self.inc_a["severity"], self.inc_a["boot8"]), ("CRITICAL", self.boot_a[:8]))

    # ---- the gate ----
    def test_gate_refuses_without_ack_and_never_starts(self):
        rc, out, started = self.gate_no_ack
        self.assertEqual(rc, 2, out); self.assertFalse(started)
        self.assertIn("no_ack", out); self.assertIn(self.inc_a["id"], out)

    def test_ack_while_stopped_is_bound_and_read_only(self):
        self.assertEqual(self.ack_rc, 0, self.ack_out)
        p = AB.ack_path(self.base, self.inc_a["id"])
        self.assertEqual(os.stat(p).st_mode & 0o777, 0o444)
        a = jload(p)
        self.assertEqual((a["incident"]["id"], a["incident"]["first_ms"], a["lineage"]["boot_id"]),
                         (self.inc_a["id"], self.inc_a["first_ms"], self.boot_a))
        self.assertEqual(AB.validate(self.stopped, self.inc_a, a["ts_ms"]), ["no_ack"])  # the copy has none

    def test_gate_requires_lineage_ack_after_failclosed(self):
        for rc, out, started in (self.gate_no_prev, self.gate_wrong_prev):
            self.assertEqual(rc, 2, out); self.assertFalse(started)
            self.assertIn(f"P2F_ACK_PREVIOUS={self.boot_a[:8]}", out)

    def test_gate_passes_with_valid_ack_and_lineage(self):
        rc, out, started = self.gate_ok
        self.assertEqual(rc, 0, out); self.assertTrue(started)
        self.assertIn("incident gate: no blocking CRITICAL incident", out)
        self.assertIn("NOT a clean stop", out); self.assertIn("UP OK", out)

    def test_second_start_while_running_refuses(self):
        rc, out, started = self.ops.up(self.base, P2F_ACK_PREVIOUS=self.boot_a[:8], STUB_RUNNING="abc123")
        self.assertEqual(rc, 2); self.assertFalse(started); self.assertIn("collector already running", out)

    # ---- the restart ----
    def test_restart_merged_ack_through_collector_path(self):
        self.assertEqual(self.code_b, 0)
        inc = [i for i in self.state_after_b if i["id"] == self.inc_a["id"]][0]
        self.assertEqual((inc["ack"]["by"], inc["ack"]["ref"]), ("operator", "collector-failclosed-recovery/evidence"))
        self.assertGreater(inc["ack"]["ack_ms"], self.inc_a["first_ms"])
        self.assertEqual({k: inc[k] for k in AB.INC_FIELDS}, {k: self.inc_a[k] for k in AB.INC_FIELDS})  # preserved
        self.assertIn(("ack", self.inc_a["id"]), [(e["event"], e["id"]) for e in self.ev_b])

    def test_restart_does_not_reraise_old_incident(self):
        opened = [e["key"] for e in self.ev_b if e["event"] == "open"]
        self.assertNotIn("failclosed:writer_stalled", opened)
        self.assertIn("previous_run_stopped_failed", opened)
        w = [i for i in self.state_after_b if i["key"] == "previous_run_stopped_failed"][0]
        self.assertEqual(w["severity"], "WARNING")
        crit = [i for i in self.state_after_b if i["active"] and i["ack"] is None and i["severity"] == "CRITICAL"]
        self.assertEqual(crit, [])

    def test_downtime_record_and_run_chain(self):
        d = jload(os.path.join(self.base, "runs", f"downtime-{self.b.boot_id}.json"))
        mk = jload(os.path.join(self.base, "control", f"stop-{self.boot_a[:8]}.json"))
        self.assertEqual(d["cause"], "stopped_failed")
        self.assertEqual((d["previous_run"]["boot_id"], d["previous_run"]["clean_stop"], d["previous_run"]["state"]),
                         (self.boot_a, True, "FAILED"))
        self.assertEqual(d["from_ms"], mk["stop_requested_ms"])
        self.assertIsNotNone(d["until_ms"]); self.assertGreater(d["until_ms"], d["from_ms"])
        rp = VC.VI.Report(); ch = VC.run_chain(self.base, rp)
        self.assertFalse(rp.failures, rp.failures)
        self.assertEqual([r["boot_id"] for r in ch][:2], [self.boot_a, self.b.boot_id])

    def test_clean_stop_then_gate_passes_without_previous_ack(self):
        rc, out, started = self.gate_after_clean_b
        self.assertEqual(rc, 0, out); self.assertTrue(started); self.assertIn("STOPPED cleanly", out)

    # ---- a later CRITICAL needs a NEW ack ----
    def test_new_critical_requires_new_ack_old_ack_never_reused(self):
        self.assertEqual(self.code_c, A.EXIT_FAILCLOSED)
        new = [i for i in state(self.base) if i["key"] == "failclosed:writer_stalled" and i["ack"] is None]
        self.assertEqual(len(new), 1); new = new[0]
        self.assertNotEqual(new["id"], self.inc_a["id"]); self.assertEqual(new["boot8"], self.c.boot_id[:8])
        rc, out, started = self.ops.up(self.base, P2F_ACK_PREVIOUS=self.c.boot_id[:8])
        self.assertEqual(rc, 2); self.assertFalse(started); self.assertIn(new["id"], out)
        d = self.copy_of(self.base, "reuse")                              # replay A's ack under C's incident id
        old = jload(AB.ack_path(d, self.inc_a["id"]))
        self.put(d, new["id"], old)
        probs = AB.validate(d, new)
        for p in ("wrong_incident_id", "incident_record_changed_since_ack", "run_lineage_mismatch"):
            self.assertIn(p, probs)
        rc, out, started = self.ops.up(d, P2F_ACK_PREVIOUS=self.c.boot_id[:8])
        self.assertEqual(rc, 2); self.assertFalse(started)
        rc, out = self.ops.ack(self.base, new["id"])                        # a fresh ack for the new incident works
        self.assertEqual(rc, 0, out)
        rc, out, started = self.ops.up(self.base, P2F_ACK_PREVIOUS=self.c.boot_id[:8])
        self.assertEqual(rc, 0, out); self.assertTrue(started)

    # ---- adversarial acks (scratch copies of the stopped state) ----
    def test_adversarial_acks_fail_closed(self):
        inc = self.inc_a
        cases = {
            "legacy_unbound": ({"by": "op", "ref": "r", "ts_ms": inc["last_ms"] + 1}, None, "ack_unbound_or_wrong_version"),
            "malformed_json": (None, "{not json", "ack_malformed"),
            "not_object": (None, "[1, 2]", "ack_not_object"),
            "empty_object": ({}, None, "ack_unbound_or_wrong_version"),
            "tampered_no_rehash": ("TAMPER_BY", None, "binding_hash_mismatch"),
            "tampered_severity_rehash": ("SEV", None, "incident_severity_mismatch"),
            "stale_opened": ("STALE_FIRST", None, "incident_first_ms_mismatch"),
            "stale_boot": ("STALE_BOOT", None, "incident_boot8_mismatch"),
            "ack_before_incident": ("EARLY", None, "ack_not_after_incident"),
            "ack_in_future": ("FUTURE", None, "ack_in_future"),
            "incident_sha_forged": ("INCSHA", None, "incident_record_changed_since_ack"),
            "wrong_dataset": ("DSID", None, "dataset_id_mismatch"),
            "missing_reason": ("NOREASON", None, "reason_missing"),
            "wrong_lineage": ("LINEAGE", None, "run_lineage_mismatch"),
        }
        for name, (obj, raw, want) in cases.items():
            with self.subTest(name):
                d = self.fresh(name)
                if obj == "TAMPER_BY":
                    obj = self.bound(d, inc); obj["by"] = "someone-else"
                elif obj == "SEV":
                    obj = self.rehash(self.bound(d, inc, incident={**self.bound(d, inc)["incident"], "severity": "WARNING"}))
                elif obj == "STALE_FIRST":
                    obj = self.rehash(self.bound(d, inc, incident={**self.bound(d, inc)["incident"], "first_ms": inc["first_ms"] - 1000}))
                elif obj == "STALE_BOOT":
                    obj = self.rehash(self.bound(d, inc, incident={**self.bound(d, inc)["incident"], "boot8": "00000000"}))
                elif obj == "EARLY":
                    obj = self.rehash(self.bound(d, inc, ts_ms=inc["first_ms"] - 1))
                elif obj == "FUTURE":
                    obj = self.rehash(self.bound(d, inc, ts_ms=AB.now_ms() + 3_600_000))
                elif obj == "INCSHA":
                    obj = self.rehash(self.bound(d, inc, incident_sha256="0" * 64))
                elif obj == "DSID":
                    obj = self.rehash(self.bound(d, inc, dataset_id="other-ds"))
                elif obj == "NOREASON":
                    obj = self.rehash(self.bound(d, inc, reason=" "))
                elif obj == "LINEAGE":
                    obj = self.rehash(self.bound(d, inc, lineage={"boot_id": "f" * 32, "run_record_sha256": "0" * 64}))
                self.put(d, inc["id"], obj, raw)
                probs = AB.validate(d, inc)
                self.assertTrue(any(p.startswith(want) for p in probs), (name, probs))
                rc, out, started = self.ops.up(d, P2F_ACK_PREVIOUS=self.boot_a[:8])
                self.assertEqual(rc, 2, (name, out)); self.assertFalse(started, name)

    def test_symlinked_ack_refused(self):
        d = self.fresh("symlink")
        good = self.fresh("symlink-src")
        self.assertEqual(self.ops.ack(good, self.inc_a["id"])[0], 0)
        os.symlink(AB.ack_path(good, self.inc_a["id"]), AB.ack_path(d, self.inc_a["id"]))
        self.assertEqual(AB.validate(d, self.inc_a), ["ack_is_symlink"])
        self.assertEqual(self.ops.up(d, P2F_ACK_PREVIOUS=self.boot_a[:8])[0], 2)

    def test_ack_for_other_incident_under_this_id_refused(self):
        d = self.fresh("wrong-incident")
        log = I.IncidentLog(d, self.boot_a)                            # a second CRITICAL (same boot) in the copy
        other = log.raise_("failclosed:test_second", "CRITICAL", {"t": 1}); log.flush()
        inc = [i for i in state(d) if i["id"] == self.inc_a["id"]][0]
        other = [i for i in state(d) if i["id"] == other["id"]][0]
        self.put(d, inc["id"], AB.build(d, other, "op", "ref", "reason", other["last_ms"] + 1))
        self.assertIn("wrong_incident_id", AB.validate(d, inc))
        rc, out, started = self.ops.up(d, P2F_ACK_PREVIOUS=self.boot_a[:8])
        self.assertEqual(rc, 2); self.assertFalse(started)

    def test_multiple_criticals_only_one_acked_refuses_the_other(self):
        d = self.fresh("multi")
        log = I.IncidentLog(d, self.boot_a)
        other = log.raise_("failclosed:test_second", "CRITICAL", {"t": 1}); log.flush()
        self.assertEqual(self.ops.ack(d, self.inc_a["id"])[0], 0)
        b = AB.gate(d)
        self.assertEqual(list(b), [other["id"]]); self.assertEqual(b[other["id"]], ["no_ack"])
        rc, out, started = self.ops.up(d, P2F_ACK_PREVIOUS=self.boot_a[:8])
        self.assertEqual(rc, 2); self.assertFalse(started); self.assertIn(other["id"], out)
        self.assertNotIn(self.inc_a["id"], out.split("unacknowledged CRITICAL incidents:")[1])
        self.assertEqual(self.ops.ack(d, other["id"])[0], 0)
        self.assertEqual(self.ops.up(d, P2F_ACK_PREVIOUS=self.boot_a[:8])[0], 0)

    def test_incident_changed_after_ack_refused(self):
        d = self.fresh("changed-after")
        self.assertEqual(self.ops.ack(d, self.inc_a["id"])[0], 0)
        st = jload(os.path.join(d, "incidents", "state.json"))
        for i in st["incidents"]:
            if i["id"] == self.inc_a["id"]:
                i["count"] += 1                                          # e.g. a later occurrence the operator never saw
        with open(os.path.join(d, "incidents", "state.json"), "w") as fh:
            json.dump(st, fh)
        inc = [i for i in st["incidents"] if i["id"] == self.inc_a["id"]][0]
        probs = AB.validate(d, inc)
        self.assertIn("incident_record_changed_since_ack", probs); self.assertIn("incident_count_mismatch", probs)

    def test_ack_tool_refusals(self):
        d = self.fresh("tool")
        iid = self.inc_a["id"]
        self.assertEqual(self.ops.ack(d, "inc-0-00000000-1")[0], 2)                  # unknown incident
        self.assertEqual(self.ops.ack(d, iid, reason="")[0], 2)                       # reason required
        self.assertEqual(self.ops.ack(d, iid, ref=" ")[0], 2)                         # reference required
        self.assertEqual(self.ops.ack(d, iid, by="x" * 81)[0], 2)                     # never truncated by the merge
        self.assertFalse(os.path.lexists(AB.ack_path(d, iid)))                         # refusals write nothing
        self.assertFalse([f for f in os.listdir(os.path.join(d, "incidents", "ack")) if f.endswith(".tmp")])
        self.assertEqual(self.ops.ack(d, iid)[0], 0)
        before = read(AB.ack_path(d, iid))
        rc, out = self.ops.ack(d, iid, by="second")                                   # never overwritten
        self.assertEqual(rc, 2); self.assertIn("already exists", out)
        self.assertEqual(read(AB.ack_path(d, iid)), before)
        r = subprocess.run(["bash", str(OPS / "p2f_incident_ack.sh"), d, iid, "op", "ref"], capture_output=True,
                           text=True, env=self.ops.env())                              # old 4-argument form refused
        self.assertEqual(r.returncode, 64)

    def test_collector_merge_reads_bound_ack_unchanged(self):
        d = self.fresh("merge")
        self.assertEqual(self.ops.ack(d, self.inc_a["id"])[0], 0)
        log = I.IncidentLog(d, "c" * 32)
        self.assertEqual(log.poll_acks(), 1)
        self.assertEqual(log.items[self.inc_a["id"]]["ack"]["by"], "operator")
        self.assertEqual(log.active(), [])


if __name__ == "__main__":
    unittest.main()
