"""MI budget-ledger reset protection: offline tests (temp dirs only; no systemd, no real campaign).

Covers genesis rules, deletion, rollback/replay/fork, code rollback, truncation, corrupted / missing checkpoints,
interrupted writes, concurrent opens, owner-approved recovery and audit-trail preservation.
"""
from __future__ import annotations

import contextlib
import glob
import importlib.util
import io
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from _helpers import ROOT

from research_exec import __main__ as CLI
from research_exec import config
from research_exec import mi_campaign as MIC
from mi_cpuguard import ledger as L


def cfg_for(tmp, **mi):
    c = config.load_config()
    c["state_dir"] = os.path.join(tmp, "state")
    c["mi"].update({"enabled": True, "anchor_dir": os.path.join(tmp, "anchor"), "cgroup_root": os.path.join(tmp, "cg")})
    c["mi"].update(mi)
    return c


def files_under(tmp):
    return sorted(p for p in glob.glob(os.path.join(tmp, "**", "*"), recursive=True) if os.path.isfile(p)
                  and not p.endswith(".lock"))


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.t = self.td.name
        self.cfg = cfg_for(self.t)
        self.p = MIC.paths(self.cfg)

    def tearDown(self):
        self.td.cleanup()

    def led(self, **kw):
        return MIC._ledger(self.cfg)

    def genesis(self):
        return MIC.init_ledger(self.cfg, approve_genesis=True, by="owner")

    def history(self, n=3):
        """genesis + n closed campaigns of 100 CPU-s each (charged 60)."""
        self.genesis()
        led = self.led()
        for i in range(n):
            led.reserve(f"c{i}", 100.0)
            led.charge(f"c{i}", 60.0, "cgroup_usage_usec")
        return led

    def code(self, fn, *a, **kw):
        try:
            fn(*a, **kw)
        except L.CheckpointError as e:
            return e.code
        except L.LedgerError as e:
            return str(e).split(":")[0].split(" ")[0]
        return "OK"


# ====================================================================== genesis
class Genesis(Base):
    def test_first_ever_genesis_only(self):
        with self.assertRaises(MIC.MIError):
            MIC.init_ledger(self.cfg, approve_genesis=False, by="x")
        g = self.genesis()
        self.assertEqual(g["genesis"]["event"], "genesis")
        self.assertTrue(os.path.exists(self.p["checkpoint"]) and os.path.exists(self.p["anchor"]))
        with self.assertRaises(L.LedgerError) as cm:
            self.genesis()
        self.assertIn("NOT_FIRST_GENESIS", str(cm.exception))

    def test_no_silent_initialization_anywhere(self):
        self.assertEqual(self.code(self.led().state), "NO_GENESIS")
        self.assertEqual(self.code(self.led().reserve, "x", 10.0), "NO_GENESIS")
        with self.assertRaises(L.LedgerMissing):
            MIC.open_campaign(self.cfg, "x", 10.0, run=lambda *a, **k: self.fail("must not start anything"))
        self.assertFalse(os.path.exists(self.p["ledger"]))

    def test_regenesis_refused_after_any_loss(self):
        self.history(1)
        os.remove(self.p["ledger"])                                       # ledger lost, checkpoints remain
        self.assertIn("NOT_FIRST_GENESIS", self.code(self.genesis))
        os.remove(self.p["checkpoint"])                                   # state dir checkpoint lost too
        self.assertIn("NOT_FIRST_GENESIS", self.code(self.genesis))       # the anchor still exists
        os.remove(self.p["anchor"])
        os.makedirs(os.path.join(self.p["campaigns"], "c0"), exist_ok=True)
        with self.assertRaises(MIC.MIError):
            self.genesis()                                                # campaign records prove prior use

    def test_anchor_must_be_independent_of_state_dir(self):
        bad = cfg_for(self.t, anchor_dir=os.path.join(self.t, "state", "mi"))
        with self.assertRaises(MIC.MIError):
            MIC.paths(bad)


# ====================================================================== deletion, truncation, rollback, replay
class ResetAttacks(Base):
    def test_ledger_deletion_is_refused_never_reset(self):
        led = self.history(2)
        os.remove(self.p["ledger"])
        self.assertEqual(self.code(led.state), "LEDGER_MISSING")
        self.assertEqual(self.code(led.reserve, "new", 10.0), "LEDGER_MISSING")
        d = MIC.ledger_check(self.cfg)
        self.assertEqual(d["status"], "LEDGER_MISSING")
        self.assertEqual(d["best_checkpoint"]["committed_cpu_s"], 120.0)

    def test_state_dir_wipe_detected_by_external_anchor(self):
        self.history(2)
        shutil.rmtree(os.path.join(self.t, "state"))
        self.assertEqual(self.code(self.led().state), "LEDGER_MISSING")

    def test_truncation_and_rollback(self):
        led = self.history(2)
        with open(self.p["ledger"]) as fh:
            lines = fh.read().splitlines(True)
        with open(self.p["ledger"], "w") as fh:
            fh.writelines(lines[:-1])                                     # drop the last event
        self.assertEqual(self.code(led.state), "TRUNCATED_OR_ROLLED_BACK")
        with open(self.p["ledger"], "w") as fh:
            fh.write("")
        self.assertEqual(self.code(led.state), "LEDGER_CORRUPT")

    def test_old_copy_restored_is_detected(self):
        led = self.history(1)
        old_l, old_c = os.path.join(self.t, "old.jsonl"), os.path.join(self.t, "old.cp")
        shutil.copy(self.p["ledger"], old_l)
        shutil.copy(self.p["checkpoint"], old_c)
        led.reserve("later", 50.0)
        led.charge("later", 40.0, "cgroup_usage_usec")
        shutil.copy(old_l, self.p["ledger"])                              # roll the ledger back
        self.assertEqual(self.code(led.state), "TRUNCATED_OR_ROLLED_BACK")
        shutil.copy(old_c, self.p["checkpoint"])                          # ... and the state-dir checkpoint with it
        self.assertEqual(self.code(led.state), "TRUNCATED_OR_ROLLED_BACK")  # the external anchor still catches it

    def test_fork_and_foreign_ledger(self):
        led = self.history(1)
        evs, _ = L.parse_ledger_bytes(open(self.p["ledger"], "rb").read())
        forged, prev = [], L.GENESIS
        for e in evs:                                                     # same id, rewritten amounts, valid chain
            e = dict(e)
            if e["event"] == "charge":
                e["actual_cpu_s"] = 1.0
            e["prev"] = prev
            e["hash"] = L._ev_hash(e)
            prev = e["hash"]
            forged.append(e)
        with open(self.p["ledger"], "w") as fh:
            fh.write("".join(L._canon(e) + "\n" for e in forged))
        self.assertEqual(self.code(led.state), "FORK_OR_REPLAY")
        other = tempfile.mkdtemp(dir=self.t)
        c2 = cfg_for(other)
        MIC.init_ledger(c2, approve_genesis=True, by="x")
        shutil.copy(MIC.paths(c2)["ledger"], self.p["ledger"])           # foreign ledger replayed in
        self.assertEqual(self.code(led.state), "LEDGER_ID_MISMATCH")

    def test_code_rollback_refuses_new_ledger(self):
        src = subprocess.run(["git", "-C", ROOT, "show", "edc2b6d:ops/research/mi_cpuguard/ledger.py"],
                             capture_output=True, text=True)
        if src.returncode != 0:
            self.skipTest("edc2b6d not reachable")
        self.history(1)
        spec = importlib.util.spec_from_loader("mi_cpuguard._old_ledger", loader=None)
        old = importlib.util.module_from_spec(spec)
        old.__package__ = "mi_cpuguard"
        exec(compile(src.stdout, "old_ledger.py", "exec"), old.__dict__)
        o = old.BudgetLedger(self.p["ledger"])
        with self.assertRaises(old.LedgerTamper):
            o.state()                                                     # unknown event 'genesis'
        with self.assertRaises(old.LedgerTamper):
            o.reserve("rolled-back-code", 10.0)


# ====================================================================== checkpoints
class Checkpoints(Base):
    def test_corrupted_or_missing_checkpoint_refuses(self):
        led = self.history(1)
        for target in (self.p["checkpoint"], self.p["anchor"]):
            good = open(target).read()
            with open(target, "w") as fh:
                fh.write("{not json")
            self.assertEqual(self.code(led.state), "CHECKPOINT_CORRUPT")
            cp = json.loads(good)
            cp["committed_cpu_s"] = 0.0                                   # edited without the self hash
            with open(target, "w") as fh:
                json.dump(cp, fh)
            self.assertEqual(self.code(led.state), "CHECKPOINT_CORRUPT")
            cp = json.loads(good)
            cp.pop("self_sha256")
            cp["head"] = "f" * 64                                         # forged head, self hash recomputed
            import hashlib
            cp["self_sha256"] = hashlib.sha256(L._canon(cp).encode()).hexdigest()
            with open(target, "w") as fh:
                json.dump(cp, fh)
            self.assertEqual(self.code(led.state), "FORK_OR_REPLAY")
            with open(target, "w") as fh:
                fh.write(good)
            self.assertEqual(self.code(led.state), "OK")
        os.remove(self.p["anchor"])
        self.assertEqual(self.code(led.state), "CHECKPOINT_MISSING")

    def test_rebuild_checkpoints_needs_approval_and_preserves(self):
        led = self.history(1)
        os.remove(self.p["anchor"])
        with self.assertRaises(L.ApprovalRequired):
            MIC.ledger_recover(self.cfg, "rebuild-checkpoints", approve="wrong", by="owner")
        tok = MIC.ledger_check(self.cfg)["approval_challenges"]["rebuild-checkpoints"]
        ev = MIC.ledger_recover(self.cfg, "rebuild-checkpoints", approve=tok, by="owner")
        self.assertEqual(ev["event"], "checkpoint_rebuilt")
        st = self.led().state()
        self.assertEqual(st["charged_cpu_s"], 60.0)
        self.assertTrue(glob.glob(self.p["checkpoint"] + ".corrupt-*.bak"))   # the surviving one was preserved

    def test_rebuild_refused_when_survivor_contradicts_ledger(self):
        led = self.history(2)
        with open(self.p["ledger"]) as fh:
            lines = fh.read().splitlines(True)
        with open(self.p["ledger"], "w") as fh:
            fh.writelines(lines[:-2])                                     # rolled back
        os.remove(self.p["anchor"])
        tok = MIC.ledger_check(self.cfg)["approval_challenges"]["rebuild-checkpoints"]
        with self.assertRaises(L.LedgerError):
            MIC.ledger_recover(self.cfg, "rebuild-checkpoints", approve=tok, by="owner")


# ====================================================================== interrupted writes
class InterruptedWrites(Base):
    def test_torn_tail_refused_then_owner_repair(self):
        led = self.history(1)
        torn = '{"seq": 3, "event": "reser'
        with open(self.p["ledger"], "a") as fh:
            fh.write(torn)                                                # crash mid-line
        self.assertEqual(self.code(led.state), "TORN_TAIL")
        self.assertEqual(self.code(led.reserve, "x", 1.0), "TORN_TAIL")
        tok = MIC.ledger_check(self.cfg)["approval_challenges"]["torn-tail"]
        ev = MIC.ledger_recover(self.cfg, "torn-tail", approve=tok, by="owner")
        self.assertEqual((ev["event"], ev["removed_bytes"]), ("torn_tail_repaired", len(torn.encode())))
        self.assertTrue(glob.glob(self.p["ledger"] + ".torn-*.bak"))
        self.assertEqual(self.led().state()["charged_cpu_s"], 60.0)

    def test_crash_between_ledger_append_and_checkpoint_rolls_forward(self):
        led = self.history(1)
        evs = led._events()
        ev = {"event": "reserve", "campaign": "half", "amount_cpu_s": 10.0, "seq": len(evs),
              "prev": evs[-1]["hash"], "at": "x"}
        ev["hash"] = L._ev_hash(ev)
        with open(self.p["ledger"], "a") as fh:                           # appended, checkpoints NOT updated
            fh.write(L._canon(ev) + "\n")
        st = led.state()
        self.assertEqual(st["verify"]["lag"], 1)                          # read-only: reported, not written
        led.charge("half", 5.0, "cgroup_usage_usec")                      # next mutation rolls forward first
        self.assertTrue(led.last_verify["rolled_forward"])
        self.assertEqual(self.led().state()["verify"]["lag"], 0)
        # two writes without checkpoint updates is not an interrupted write: refuse
        for i in range(2):
            evs = led._events()
            e = {"event": "reserve", "campaign": f"z{i}", "amount_cpu_s": 1.0, "seq": len(evs), "prev": evs[-1]["hash"],
                 "at": "x"}
            e["hash"] = L._ev_hash(e)
            with open(self.p["ledger"], "a") as fh:
                fh.write(L._canon(e) + "\n")
        self.assertEqual(self.code(led.state), "CHECKPOINT_STALE")

    def test_crash_between_the_two_checkpoint_writes(self):
        led = self.history(1)
        old_anchor = open(self.p["anchor"]).read()
        led.reserve("n", 10.0)
        with open(self.p["anchor"], "w") as fh:                           # anchor still at the previous head
            fh.write(old_anchor)
        self.assertEqual(self.code(led.state), "OK")
        led.charge("n", 1.0, "cgroup_usage_usec")
        self.assertEqual(json.load(open(self.p["anchor"]))["seq"], led.state()["seq"])

    def test_failed_atomic_checkpoint_write_leaves_previous_intact(self):
        led = self.history(1)
        with mock.patch.object(L.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                led.reserve("w", 10.0)                                    # ledger appended, checkpoints unchanged
        self.assertEqual(self.led().state()["verify"]["lag"], 1)          # recoverable: exactly one ahead
        self.led().charge("w", 2.0, "cgroup_usage_usec")
        self.assertEqual(self.led().state()["verify"]["lag"], 0)
        self.assertEqual(glob.glob(os.path.join(self.t, "**", "*.tmp-*"), recursive=True), [])


# ====================================================================== concurrency
def _single_open_worker(cfgjson, q):
    c = json.loads(cfgjson)
    try:
        MIC._ledger(c).reserve(f"w{os.getpid()}", 100.0)
        q.put("ok")
    except L.BudgetExceeded:
        q.put("refused")


class Concurrency(Base):
    def test_concurrent_reservations_single_open(self):
        self.genesis()
        ctx = mp.get_context("fork")
        q = ctx.Queue()
        ps = [ctx.Process(target=_single_open_worker, args=(json.dumps(self.cfg), q)) for _ in range(8)]
        for x in ps:
            x.start()
        for x in ps:
            x.join(60)
        res = sorted(q.get(timeout=5) for _ in ps)
        self.assertEqual(res.count("ok"), 1)
        st = self.led().state()
        self.assertEqual((len(st["open_reservations"]), st["events"]), (1, 2))

    def test_concurrent_open_lock(self):
        self.genesis()
        with MIC._open_lock(self.cfg):
            pid = os.fork()
            if pid == 0:
                try:
                    MIC.open_campaign(self.cfg, "b", 10.0, run=lambda *a, **k: os._exit(9))
                except MIC.MIError as e:
                    os._exit(0 if "in progress" in str(e) else 8)
                os._exit(7)
            _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)


# ====================================================================== carry-forward (destructive recovery)
class CarryForward(Base):
    def test_corrupt_ledger_carry_forward_preserves_consumption(self):
        self.history(3)                                                   # 3 x 60 = 180 charged
        with open(self.p["ledger"], "r+") as fh:
            data = fh.read()
            fh.seek(0)
            fh.write(data.replace('"actual_cpu_s":60.0', '"actual_cpu_s":6.00', 1))
        self.assertEqual(MIC.ledger_check(self.cfg)["status"], "LEDGER_CORRUPT")
        before = files_under(self.t)
        with self.assertRaises(L.ApprovalRequired):
            MIC.ledger_recover(self.cfg, "carry-forward", approve="", by="owner")
        tok = MIC.ledger_check(self.cfg)["approval_challenges"]["carry-forward"]
        ev = MIC.ledger_recover(self.cfg, "carry-forward", approve=tok, by="owner",
                                declared_consumed_cpu_s=50.0)             # lower declaration never wins
        self.assertEqual(ev["consumed_cpu_s"], 180.0)
        st = self.led().state()
        self.assertEqual((st["epoch"], st["charged_cpu_s"], st["remaining_cpu_s"]), (1, 180.0, 28_800 - 180.0))
        with self.assertRaises(L.BudgetExceeded):
            self.led().reserve("c1", 10.0)                                # old ids stay used across epochs
        after = files_under(self.t)
        self.assertTrue(set(before) - {self.p["ledger"]} <= set(after))   # nothing deleted (ledger moved aside)
        self.assertTrue(glob.glob(self.p["ledger"] + ".superseded-*.bak"))

    def test_total_loss_requires_declared_consumption(self):
        self.history(1)
        for f in (self.p["ledger"], self.p["checkpoint"], self.p["anchor"]):
            os.remove(f)
        tok = MIC.ledger_check(self.cfg)["approval_challenges"]["carry-forward"]
        with self.assertRaises(L.LedgerError):
            MIC.ledger_recover(self.cfg, "carry-forward", approve=tok, by="owner")
        ev = MIC.ledger_recover(self.cfg, "carry-forward", approve=tok, by="owner", declared_consumed_cpu_s=28_800.0)
        self.assertEqual(ev["consumed_cpu_s"], 28_800.0)
        self.assertEqual(self.led().state()["remaining_cpu_s"], 0.0)       # fail-closed default: budget exhausted

    def test_restore_backup_only_if_not_older(self):
        led = self.history(1)
        bak_old = os.path.join(self.t, "old.jsonl")
        shutil.copy(self.p["ledger"], bak_old)
        led.reserve("x", 10.0)
        led.charge("x", 9.0, "cgroup_usage_usec")
        bak_new = os.path.join(self.t, "new.jsonl")
        shutil.copy(self.p["ledger"], bak_new)
        os.remove(self.p["ledger"])
        tok = MIC.ledger_check(self.cfg)["approval_challenges"]["restore-backup"]
        with self.assertRaises(L.LedgerError):
            MIC.ledger_recover(self.cfg, "restore-backup", approve=tok, by="owner", backup=bak_old)
        ev = MIC.ledger_recover(self.cfg, "restore-backup", approve=tok, by="owner", backup=bak_new)
        self.assertEqual(ev["event"], "restored_from_backup")
        self.assertEqual(self.led().state()["charged_cpu_s"], 69.0)

    def test_token_is_bound_to_the_exact_state(self):
        self.history(1)
        os.remove(self.p["anchor"])
        tok = MIC.ledger_check(self.cfg)["approval_challenges"]["rebuild-checkpoints"]
        with open(self.p["ledger"], "a") as fh:
            fh.write("x")                                                 # state changed after the check
        with self.assertRaises(L.ApprovalRequired):
            MIC.ledger_recover(self.cfg, "rebuild-checkpoints", approve=tok, by="owner")


# ====================================================================== CLI + opt-in
class CLIAndOptIn(Base):
    def run_cli(self, *argv):
        cf = os.path.join(self.t, "mi.json")
        with open(cf, "w") as fh:
            json.dump({"state_dir": self.cfg["state_dir"], "mi": {k: self.cfg["mi"][k] for k in
                                                                  ("enabled", "anchor_dir", "cgroup_root")}}, fh)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = CLI.main(["mi", *argv, "--config", cf])
        return rc, out.getvalue(), err.getvalue()

    def test_cli_genesis_check_and_refusals(self):
        rc, _, err = self.run_cli("open", "--campaign", "a", "--reservation-cpu-s", "10")
        self.assertEqual(rc, 2)
        self.assertIn("NO_GENESIS", err)
        self.assertEqual(self.run_cli("init")[0], 2)                      # no --approve-genesis
        self.assertEqual(self.run_cli("init", "--approve-genesis")[0], 0)
        rc, out, _ = self.run_cli("ledger-check")
        self.assertEqual((rc, json.loads(out)["status"]), (0, "OK"))
        self.assertEqual(self.run_cli("init", "--approve-genesis")[0], 2)  # never twice

    def test_disabled_by_default(self):
        c = config.load_config()
        self.assertFalse(c["mi"]["enabled"])
        with self.assertRaises(MIC.MIError):
            MIC.init_ledger(c, approve_genesis=True, by="x")


if __name__ == "__main__":
    unittest.main()
