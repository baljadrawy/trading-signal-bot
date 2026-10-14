"""A41 tests for tsb-p1bg-backup.sh v2 + p1bg_evidence_snapshot.py.
Helper tests are pure and deterministic (exact interleavings via monkeypatch). Script tests need docker and run a
DISPOSABLE PostgreSQL container (A41_PG_CONTAINER, created by the caller); they never touch production."""
import hashlib, json, os, signal, subprocess, sys, tarfile, threading, time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p1bg_evidence_snapshot as S  # noqa: E402

SCRIPT = HERE / "tsb-p1bg-backup.sh"
PGC = os.getenv("A41_PG_CONTAINER")
V1 = os.getenv("A41_V1_SCRIPT")                    # the installed v1 script, for the root-cause replay


def tree(root: Path, big=0):
    for svc in ("analyzer", "trade_tracker"):
        d = root / svc
        d.mkdir(parents=True)
        (d / "events-2026-10-13.jsonl").write_bytes(b'{"a":1}\n{"a":2}\n')
        (d / "events-2026-10-14.jsonl").write_bytes(b'{"b":1}\n' * (big or 3) + b'{"partial"')
        (d / "_recorder_stats.json").write_text('{"seq": 1}')
    return root


# ================================================================ helper (deterministic) ========
def test_append_between_reads_is_a_consistent_prefix(tmp_path, monkeypatch):
    src = tree(tmp_path / "ev")
    real = S._read_exact
    calls = {"n": 0}

    def appending(path, n):
        data = real(path, n)
        calls["n"] += 1
        with open(path, "ab") as fh:                     # a live recorder appends between our two reads
            fh.write(b'"x"}\n{"c":9}\n')
        return data
    monkeypatch.setattr(S, "_read_exact", appending)
    m = S.snapshot(str(src), str(tmp_path / "st" / "evidence_v2"), str(tmp_path / "m.json"))
    f = {x["path"]: x for x in m["files"]}["analyzer/events-2026-10-14.jsonl"]
    staged = (tmp_path / "st/evidence_v2/analyzer/events-2026-10-14.jsonl").read_bytes()
    assert staged == b'{"b":1}\n' * 3 and staged.endswith(b"\n")          # only complete records
    assert f["tail_excluded_bytes"] == len(b'{"partial"')
    assert f["sha256"] == hashlib.sha256(staged).hexdigest()


@pytest.mark.parametrize("mutation", ["rewrite", "truncate"])
def test_non_append_mutation_fails_closed(tmp_path, monkeypatch, mutation):
    src = tree(tmp_path / "ev")
    real = S._read_exact
    state = {"first": True}

    def mutating(path, n):
        data = real(path, n)
        if state["first"] and path.endswith("analyzer/events-2026-10-13.jsonl"):
            state["first"] = False
            if mutation == "rewrite":
                Path(path).write_bytes(b'{"Z":1}\n{"a":2}\n')
            else:
                Path(path).write_bytes(b'{"a":1}\n')
        return data
    monkeypatch.setattr(S, "_read_exact", mutating)
    with pytest.raises(S.Integrity):
        S.snapshot(str(src), str(tmp_path / "st" / "evidence_v2"), str(tmp_path / "m.json"))


def test_vanishing_files_unknown_changes_and_symlinks(tmp_path, monkeypatch):
    src = tree(tmp_path / "ev")
    (src / "analyzer" / "_recorder_stats.json.tmp").write_text("{}")
    real_lstat = os.lstat

    def lstat(p, *a, **k):
        if p.endswith(".tmp"):
            raise FileNotFoundError(p)                   # transient file renamed away: skipped
        return real_lstat(p, *a, **k)
    monkeypatch.setattr(S.os, "lstat", lstat)
    m = S.snapshot(str(src), str(tmp_path / "a" / "evidence_v2"), str(tmp_path / "a.json"))
    assert m["skipped_transient"] == ["analyzer/_recorder_stats.json.tmp"]
    monkeypatch.undo()

    def gone(p, *a, **k):
        if p.endswith("trade_tracker/events-2026-10-13.jsonl"):
            raise FileNotFoundError(p)
        return real_lstat(p, *a, **k)
    monkeypatch.setattr(S.os, "lstat", gone)
    with pytest.raises(S.Integrity, match="vanished"):
        S.snapshot(str(src), str(tmp_path / "b" / "evidence_v2"), str(tmp_path / "b.json"))
    monkeypatch.undo()

    (src / "notes.txt").write_text("x")
    real_stat = os.stat

    def touched(p, *a, **k):
        st = real_stat(p, *a, **k)
        if str(p).endswith("notes.txt"):
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid, st.st_gid,
                                   st.st_size + 1, st.st_atime, st.st_mtime, st.st_ctime))
        return st
    monkeypatch.setattr(S.os, "stat", touched)
    with pytest.raises(S.Integrity, match="changed while being read"):
        S.snapshot(str(src), str(tmp_path / "c" / "evidence_v2"), str(tmp_path / "c.json"))
    monkeypatch.undo()
    (src / "notes.txt").unlink()
    (src / "link.jsonl").symlink_to(src / "analyzer" / "events-2026-10-13.jsonl")
    with pytest.raises(S.Integrity, match="not a regular file"):
        S.snapshot(str(src), str(tmp_path / "d" / "evidence_v2"), str(tmp_path / "d.json"))
    with pytest.raises(S.Integrity, match="source missing"):
        S.snapshot(str(tmp_path / "nope"), str(tmp_path / "e" / "evidence_v2"), str(tmp_path / "e.json"))


def _archive(tmp_path, src, extra=None, drop=None, alter=None):
    m = S.snapshot(str(src), str(tmp_path / "st" / "evidence_v2"), str(tmp_path / "m.json"))
    stage = tmp_path / "st" / "evidence_v2"
    if extra:
        (stage / extra).write_text("rogue")
    if drop:
        (stage / drop).unlink()
    if alter:
        (stage / alter).write_bytes((stage / alter).read_bytes() + b"x")
    with tarfile.open(tmp_path / "e.tar.gz", "w:gz") as t:
        t.add(stage, arcname="evidence_v2")
    return m


@pytest.mark.parametrize("damage", [None, "extra", "drop", "alter", "manifest", "corrupt"])
def test_verify_is_exact(tmp_path, damage):
    src = tree(tmp_path / "ev")
    _archive(tmp_path, src, extra="rogue.jsonl" if damage == "extra" else None,
             drop="analyzer/_recorder_stats.json" if damage == "drop" else None,
             alter="trade_tracker/events-2026-10-13.jsonl" if damage == "alter" else None)
    if damage == "manifest":
        m = json.load(open(tmp_path / "m.json")); m["totals"]["files"] += 1
        json.dump(m, open(tmp_path / "m.json", "w"))
    if damage == "corrupt":
        b = (tmp_path / "e.tar.gz").read_bytes(); (tmp_path / "e.tar.gz").write_bytes(b[: len(b) // 2])
    if damage is None:
        assert S.verify(str(tmp_path / "e.tar.gz"), str(tmp_path / "m.json"))["files"] == 6
    else:
        with pytest.raises(S.Integrity):
            S.verify(str(tmp_path / "e.tar.gz"), str(tmp_path / "m.json"))


# ================================================================ script (disposable PostgreSQL) =
_PG = pytest.mark.skipif(not PGC, reason="A41_PG_CONTAINER (disposable PostgreSQL) not set")


def run(dest, src, *args, script=SCRIPT, env=None, prefix=(), timeout=300):
    e = {**os.environ, "P1BG_DEST": str(dest), "P1BG_EVIDENCE_SRC": str(src), "P1BG_DB": "a41",
         "P1BG_PG_CONTAINER": PGC or "", "P1BG_PG_USER": "postgres", "P1BG_KEEP": "7", **(env or {})}
    return subprocess.run([*prefix, "bash", str(script), *args], env=e, capture_output=True, text=True,
                          timeout=timeout)


def sets(dest):
    p = Path(dest) / "sets"
    return sorted(x.name for x in p.iterdir()) if p.exists() else []


class Writer(threading.Thread):
    """A live recorder: appends records continuously and atomically replaces its stats file."""
    def __init__(self, root):
        super().__init__(daemon=True); self.root, self.stop = root, threading.Event(); self.n = 0

    def run(self):
        f = self.root / "analyzer" / "events-2026-10-14.jsonl"
        st = self.root / "analyzer" / "_recorder_stats.json"
        while not self.stop.is_set():
            with open(f, "a") as fh:
                fh.write(json.dumps({"seq": self.n, "pad": "x" * 200}) + "\n")
            tmp = str(st) + ".tmp"
            Path(tmp).write_text(json.dumps({"seq": self.n})); os.replace(tmp, st)
            self.n += 1


@_PG
def test_live_writer_v2_succeeds_and_v1_reproduces_the_failure(tmp_path):
    src = tree(tmp_path / "evidence_v2", big=60000)            # ~0.5 MB per day file
    w = Writer(src); w.start()
    try:
        r2 = run(tmp_path / "d2", src)
        r1 = run(tmp_path / "d1", src, script=V1) if V1 else None
    finally:
        w.stop.set(); w.join()
    assert r2.returncode == 0, r2.stdout + r2.stderr
    [s] = sets(tmp_path / "d2")
    d = tmp_path / "d2" / "sets" / s
    assert not (d / "stage").exists()
    man = json.load(open(d / "MANIFEST.json"))
    assert man["implementation_version"] == 2 and man["evidence_files"] == 6
    assert run(tmp_path / "d2", src, "verify", str(d)).returncode == 0
    assert w.n > 0
    if r1 is not None:                                         # root cause, same load, installed v1
        assert r1.returncode != 0 and "evidence archive failed" in r1.stdout
        assert sets(tmp_path / "d1") == []


@_PG
@pytest.mark.parametrize("case", ["missing_source", "dump_fails", "dump_garbage", "disk_full"])
def test_failures_never_publish(tmp_path, case):
    src = tree(tmp_path / "evidence_v2", big=20000)
    env, prefix = {}, ()
    if case == "missing_source":
        src = tmp_path / "absent"
    if case == "dump_fails":
        env["P1BG_DUMP_CMD"] = "exit 3"
    if case == "dump_garbage":
        env["P1BG_DUMP_CMD"] = "echo not-a-dump"
    if case == "disk_full":                                    # RLIMIT_FSIZE: any file > 64 KiB fails
        prefix = ("prlimit", "--fsize=65536", "--")
    r = run(tmp_path / "d", src, env=env, prefix=prefix)
    assert r.returncode != 0
    assert sets(tmp_path / "d") == []
    inc = [x for x in (tmp_path / "d").iterdir() if x.name.startswith(".incomplete-")]
    assert len(inc) == 1                                       # evidence of the failed attempt is kept
    if case != "disk_full":
        assert (inc[0] / "FAILED").exists()


@_PG
def test_interrupted_run_then_repeat_succeeds_and_lock_excludes(tmp_path):
    src = tree(tmp_path / "evidence_v2")
    p = subprocess.Popen(["bash", str(SCRIPT)], env={**os.environ, "P1BG_DEST": str(tmp_path / "d"),
                         "P1BG_EVIDENCE_SRC": str(src), "P1BG_DB": "a41", "P1BG_PG_CONTAINER": PGC,
                         "P1BG_PG_USER": "postgres", "P1BG_DUMP_CMD": "sleep 30"},
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    while not list((tmp_path / "d").glob(".incomplete-*")) and time.time() < deadline:
        time.sleep(0.1)
    locked = run(tmp_path / "d", src)                          # concurrent run while the first holds the lock
    os.killpg(p.pid, signal.SIGKILL); p.wait()
    assert locked.returncode == 75 and sets(tmp_path / "d") == []
    time.sleep(1.1)                                            # distinct set timestamp
    ok = run(tmp_path / "d", src)
    assert ok.returncode == 0 and len(sets(tmp_path / "d")) == 1


@_PG
def test_tampered_published_set_fails_verify(tmp_path):
    src = tree(tmp_path / "evidence_v2")
    assert run(tmp_path / "d", src).returncode == 0
    d = tmp_path / "d" / "sets" / sets(tmp_path / "d")[0]
    os.chmod(d / "evidence_v2.manifest.json", 0o600)
    m = json.load(open(d / "evidence_v2.manifest.json")); m["files"][0]["sha256"] = "0" * 64
    json.dump(m, open(d / "evidence_v2.manifest.json", "w"))
    assert run(tmp_path / "d", src, "verify", str(d)).returncode != 0          # SHA256SUMS mismatch
    (d / "SHA256SUMS").write_text(subprocess.run(
        ["sha256sum", "a41.dump", "a41.toc", "evidence_v2.tar.gz", "evidence_v2.list",
         "evidence_v2.manifest.json", "MANIFEST.json"], cwd=d, capture_output=True, text=True).stdout)
    assert run(tmp_path / "d", src, "verify", str(d)).returncode != 0          # manifest vs archive mismatch


@_PG
def test_retention_keeps_newest_own_sets_and_never_foreign_or_on_failure(tmp_path):
    src = tree(tmp_path / "evidence_v2")
    dest = tmp_path / "d"
    for ts in ("20261001T000000Z", "20261002T000000Z"):
        d = dest / "sets" / ts; d.mkdir(parents=True)
        (d / "MANIFEST.json").write_text('{"implementation": "tsb-p1bg-backup", "implementation_version": 1}')
    (dest / "sets" / "20261003T000000Z").mkdir()                # foreign: no manifest
    env = {"P1BG_KEEP": "2"}
    assert run(dest, tmp_path / "absent", env=env).returncode != 0
    assert len(sets(dest)) == 3                                 # failed run: retention untouched
    assert run(dest, src, env=env).returncode == 0
    time.sleep(1.1)
    assert run(dest, src, env=env).returncode == 0
    left = sets(dest)
    assert "20261003T000000Z" in left and "20261001T000000Z" not in left and "20261002T000000Z" not in left
    assert len([x for x in left if x >= "20261014"]) == 2
