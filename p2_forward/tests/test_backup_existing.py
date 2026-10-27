"""Sealed-day backup: optional --verify-existing (OFF by default) on a synthetic dataset.

(a) flag off: an existing destination is reported exactly as before (FAIL destination_exists_immutable, exit 3,
no incident); (b) flag on: an intact, hash-identical existing copy is `OK (exists)` (exit 0), also after the source
legitimately grew (new run record, next-day manifest); (c) any difference still FAILs loudly (exit 1 + incident).
Nothing is ever overwritten or deleted."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

from p2_forward import cal

ROOT = pathlib.Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location("bk_mod", ROOT / "ops" / "p2f_backup.py")
B = importlib.util.module_from_spec(sp)
sp.loader.exec_module(B)

DAY, DS_ID = "2026-01-05", "test-ds"


def w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode())


def h(b):
    return hashlib.sha256(b).hexdigest()


def make_dataset(base):
    w(os.path.join(base, "dataset.json"), json.dumps({"dataset_id": DS_ID, "calendar": cal.params()}))
    w(os.path.join(base, "days", f"{DAY}.json"), json.dumps({"day": DAY, "closed": True}))
    man = []
    for t in ("book", "depth"):
        seg = f"raw/{t}/{DAY}/{t}-20260105T03Z-x.jsonl.gz"
        body = f"synthetic-{t}".encode()
        w(os.path.join(base, seg), body)
        w(os.path.join(base, seg + ".sha256"), f"{h(body)}  {os.path.basename(seg)}\n")
        w(os.path.join(base, seg[:-len(".jsonl.gz")] + ".idx"), "idx")
        man.append(json.dumps({"segment": seg, "sha256": h(body)}))
    w(os.path.join(base, "manifests", f"{DAY}.jsonl"), "\n".join(man) + "\n")
    w(os.path.join(base, "runs", "run-a.json"), "{}")
    rep = json.dumps({"PASS": True}).encode()
    w(os.path.join(base, "seals", f"{DAY}.report.json"), rep)
    w(os.path.join(base, "seals", f"{DAY}.json"),
      json.dumps({"result": "PASS", "report_sha256": h(rep), "dataset_id": DS_ID, "universe_files": []}))


def tree(root):
    out = {}
    for r, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(r, f)
            out[os.path.relpath(p, root)] = open(p, "rb").read()
    return out


def unlock(root):
    for r, ds, fs in os.walk(root):
        os.chmod(r, 0o755)
        for f in fs:
            os.chmod(os.path.join(r, f), 0o644)


def run_main(*args):
    o, e = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
        rc = B.main(list(args))
    return rc, o.getvalue(), e.getvalue()


def incidents(base):
    d = os.path.join(base, "incidents", "external")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


class ExistingDestination(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.base, self.dest = os.path.join(self.tmp, "ds"), os.path.join(self.tmp, "bk")
        make_dataset(self.base)
        rc, out, err = run_main("backup", self.base, DAY, "--dest", self.dest, "--floor-gb", "0")
        self.assertEqual(rc, 0, err)
        self.copy = os.path.join(self.dest, DS_ID, DAY)
        self.before = tree(self.copy)

    def tearDown(self):
        unlock(self.tmp)
        shutil.rmtree(self.tmp)

    def again(self, *flags):
        return run_main("backup", self.base, DAY, "--dest", self.dest, "--floor-gb", "0", *flags)

    def assert_untouched(self):
        self.assertEqual(tree(self.copy), self.before)                    # never overwritten, never deleted

    def test_flag_off_unchanged_behaviour(self):
        rc, out, err = self.again()
        self.assertEqual(rc, 3)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err), {"backup": "FAIL", "day": DAY,
                                           "reason": f"destination_exists_immutable:{self.copy}"})
        self.assertEqual(incidents(self.base), [])
        self.assert_untouched()

    def test_flag_on_identical_is_ok_exists(self):
        rc, out, err = self.again("--verify-existing")
        self.assertEqual((rc, err), (0, ""))
        res = json.loads(out)
        self.assertEqual((res["backup"], res["day"], res["dest"], res["verified"]), ("OK (exists)", DAY, self.copy, "sha256"))
        self.assertEqual(res["files"], len(self.before) - 2)              # SHA256SUMS and BACKUP.json not listed
        self.assertEqual(incidents(self.base), [])
        self.assert_untouched()

    def test_flag_on_source_growth_is_still_ok(self):
        w(os.path.join(self.base, "runs", "run-b.json"), "{}")            # a later run record
        w(os.path.join(self.base, "control", "stop-b.json"), "{}")
        w(os.path.join(self.base, "manifests", "2026-01-06.jsonl"), "{}\n")
        rc, out, _ = self.again("--verify-existing")
        self.assertEqual(rc, 0); self.assertEqual(json.loads(out)["backup"], "OK (exists)")
        self.assert_untouched()

    def check_fail(self, why):
        rc, out, err = self.again("--verify-existing")
        self.assertEqual(rc, 1, (out, err))
        r = json.loads(err)
        self.assertEqual(r["backup"], "FAIL")
        self.assertTrue(r["reason"].startswith(f"existing_destination_mismatch:{why}"), r["reason"])
        self.assertEqual(len(incidents(self.base)), 1)                    # loud: a visible incident
        return r

    def mutate_copy(self, rel, data):
        p = os.path.join(self.copy, rel)
        os.chmod(os.path.dirname(p), 0o755)
        if os.path.exists(p):
            os.chmod(p, 0o644)
        w(p, data)
        self.before = tree(self.copy)

    def test_copy_content_differs(self):
        self.mutate_copy(f"raw/book/{DAY}/book-20260105T03Z-x.jsonl.gz", b"tampered")
        self.check_fail("copy_digest_differs")
        self.assert_untouched()

    def test_copy_has_extra_or_missing_file(self):
        self.mutate_copy(f"raw/book/{DAY}/extra.json", b"x")
        self.check_fail("file_set_differs")

    def test_source_immutable_file_differs(self):
        p = os.path.join(self.base, "raw", "depth", DAY, "depth-20260105T03Z-x.idx")
        w(p, "changed")
        self.check_fail("source_digest_differs")
        self.assert_untouched()

    def test_source_has_new_day_file(self):
        w(os.path.join(self.base, "raw", "book", DAY, "book-20260105T04Z-y.idx"), "new")
        self.check_fail("source_set_differs")

    def test_seal_differs(self):
        p = os.path.join(self.base, "seals", f"{DAY}.json")
        s = json.load(open(p)); s["note"] = "resealed"
        w(p, json.dumps(s))
        self.check_fail("backup_record_differs")

    def test_unreadable_copy_metadata(self):
        p = os.path.join(self.copy, "SHA256SUMS")
        os.chmod(self.copy, 0o755); os.chmod(p, 0o644); os.rename(p, p + ".moved")
        self.before = tree(self.copy)
        self.check_fail("unreadable")
        self.assert_untouched()

    def test_not_sealed_unchanged_with_flag(self):
        rc, _, err = run_main("backup", self.base, "2026-01-04", "--dest", self.dest, "--floor-gb", "0",
                              "--verify-existing")
        self.assertEqual(rc, 3); self.assertIn("not_sealed", err)


if __name__ == "__main__":
    unittest.main()
