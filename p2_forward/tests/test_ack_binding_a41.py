"""A41: incident-acknowledgement verification after merge. Uses COPIES of the real dataset's incident metadata
(state.json, ack/, dataset.json, runs/), when present, plus synthetic records. The real dataset is never written."""
import copy, importlib.util, json, os, shutil, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ackb", os.path.join(HERE, "..", "ops", "p2f_ack_binding.py"))
B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
REAL = "/home/tradmin/research-data/trading-signal-bot/p2/forward-continuous-v1"
HIST = ["inc-1791285725357-6fd4edbc-2", "inc-1791331810668-b1b7edb6-2", "inc-1791335970908-b1b7edb6-3",
        "inc-1791993336315-2cfb872f-5", "inc-1791993338326-2cfb872f-6"]


def copy_meta(dst):
    os.makedirs(os.path.join(dst, "incidents"))
    shutil.copy(os.path.join(REAL, "incidents", "state.json"), os.path.join(dst, "incidents", "state.json"))
    shutil.copytree(os.path.join(REAL, "incidents", "ack"), os.path.join(dst, "incidents", "ack"))
    shutil.copy(os.path.join(REAL, "dataset.json"), dst)
    os.makedirs(os.path.join(dst, "runs"))
    for f in os.listdir(os.path.join(REAL, "runs")):
        if f.startswith("run-"):
            shutil.copy(os.path.join(REAL, "runs", f), os.path.join(dst, "runs", f))


def incidents(d):
    return {i["id"]: i for i in B.load_state(d)["incidents"]}


@unittest.skipUnless(os.path.isdir(os.path.join(REAL, "incidents", "ack")), "real dataset metadata not present")
class HistoricalCompatibility(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); copy_meta(self.d); self.inc = incidents(self.d)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_all_historical_merged_acks_validate(self):
        for iid in HIST:
            self.assertEqual(B.validate(self.d, self.inc[iid]), [], iid)

    def _tampered(self, iid, mutate):
        inc = copy.deepcopy(self.inc[iid]); mutate(inc)
        return B.validate(self.d, inc)

    def test_any_protected_field_change_is_detected(self):
        iid = HIST[3]
        for name, mut in {
            "severity": lambda i: i.update(severity="WARNING"),
            "count": lambda i: i.update(count=i["count"] + 1),
            "key": lambda i: i.update(key="conn_recovery_failed:other"),
            "last_detail": lambda i: i.update(last_detail={"forged": True}),
            "first_detail": lambda i: i["first_detail"].update(outage_ms=1),
            "active": lambda i: i.update(active=False),
            "latched": lambda i: i.update(latched=False),
            "resolved_ms": lambda i: i.update(resolved_ms=1),
        }.items():
            self.assertIn("incident_record_changed_since_ack", self._tampered(iid, mut), name)

    def test_merged_ack_tampering_is_detected(self):
        iid = HIST[4]
        self.assertIn("merged_ack_differs_from_file", self._tampered(iid, lambda i: i["ack"].update(by="mallory")))
        self.assertIn("merged_ack_malformed", self._tampered(iid, lambda i: i["ack"].update(extra=1)))
        self.assertIn("merged_ack_malformed", self._tampered(iid, lambda i: i.update(ack="yes")))
        self.assertIn("merged_before_ack_written", self._tampered(iid, lambda i: i["ack"].update(ack_ms=1)))

    def test_ack_file_forgery_and_run_record_changes_are_detected(self):
        iid = HIST[3]
        p = B.ack_path(self.d, iid); os.chmod(p, 0o600)
        a = json.load(open(p)); a["reason"] = "forged reason"; json.dump(a, open(p, "w"))
        self.assertIn("binding_hash_mismatch", B.validate(self.d, self.inc[iid]))
        a["binding_sha256"] = B.sha({k: v for k, v in a.items() if k != "binding_sha256"})
        a["incident_sha256"] = "0" * 64; a["binding_sha256"] = B.sha({k: v for k, v in a.items()
                                                                       if k != "binding_sha256"})
        json.dump(a, open(p, "w"))
        self.assertIn("incident_record_changed_since_ack", B.validate(self.d, self.inc[iid]))
        boot = json.load(open(B.ack_path(self.d, HIST[4])))["lineage"]["boot_id"]
        rp = os.path.join(self.d, "runs", f"run-{boot}.json")
        os.chmod(rp, 0o600)                                    # the COPY only
        with open(rp, "a") as fh:
            fh.write(" ")
        self.assertIn("bound_run_record_changed", B.validate(self.d, self.inc[HIST[4]]))
        os.unlink(rp)
        self.assertIn("bound_run_record_missing", B.validate(self.d, self.inc[HIST[4]]))

    def test_malformed_files_fail_closed(self):
        iid = HIST[0]; p = B.ack_path(self.d, iid); os.chmod(p, 0o600)
        open(p, "w").write("{not json")
        self.assertTrue(B.validate(self.d, self.inc[iid])[0].startswith("ack_malformed"))
        os.unlink(p); os.symlink(B.ack_path(self.d, HIST[1]), p)
        self.assertEqual(B.validate(self.d, self.inc[iid]), ["ack_is_symlink"])


class PendingModeUnchanged(unittest.TestCase):
    """The start gate's pending-ack path keeps its exact pre-A41 semantics (strict latest lineage)."""
    def test_pending_ack_written_then_merged(self):
        d = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(d, "incidents", "ack")); os.makedirs(os.path.join(d, "runs"))
            json.dump({"dataset_id": "t"}, open(os.path.join(d, "dataset.json"), "w"))
            json.dump({"created_ms": 1, "boot_id": "aaaa1111"}, open(os.path.join(d, "runs", "run-aaaa1111.json"), "w"))
            inc = {"id": "inc-5-aaaa1111-1", "key": "conn_recovery_failed:c", "severity": "CRITICAL", "latched": True,
                   "first_ms": 5, "last_ms": 5, "count": 1, "active": True, "resolved_ms": None, "ack": None,
                   "boot8": "aaaa1111", "first_detail": {}, "last_detail": {}}
            json.dump({"incidents": [inc]}, open(os.path.join(d, "incidents", "state.json"), "w"))
            self.assertEqual(B.validate(d, inc), ["no_ack"])
            B.write_ack(d, inc["id"], "owner", "ref", "reason")
            self.assertEqual(B.validate(d, inc), [])                    # pending: valid
            self.assertEqual(B.gate(d), {})
            json.dump({"created_ms": 2, "boot_id": "bbbb2222"}, open(os.path.join(d, "runs", "run-bbbb2222.json"), "w"))
            self.assertEqual(B.validate(d, inc), ["run_lineage_mismatch"])   # pending + newer run: still strict
            a = json.load(open(B.ack_path(d, inc["id"])))
            merged = {**inc, "ack": {"by": a["by"][:80], "ref": a["ref"][:200], "ack_ms": a["ts_ms"] + 5}}
            self.assertEqual(B.validate(d, merged), [])                 # merged: bound run still exists unchanged
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
