#!/usr/bin/env python3
"""p1bg_evidence_snapshot.py: a consistent point-in-time copy of a LIVE evidence_v2 tree (A41).

Why: tar read the live tree directly, and the recorders keep appending, so GNU tar exited 1 ("file changed
as we read it") and every nightly set failed from 2026-10-10. Suppressing that exit code would archive torn
files. Instead this tool copies a stable state into a private staging directory, and only the immutable staging
copy is archived.

Per-file contract, from the recorder's write semantics (shared/evidence_v2.py):
  *.jsonl                 append-only (open "a"). The copy is the source prefix up to the last complete line
                          present at snapshot time. The source is then re-read and the same prefix must hash
                          identically, and the file must not have shrunk; otherwise it was rewritten or
                          truncated (not append-only), so fail.
  _recorder_stats.json    replaced atomically (os.replace). One open+read yields one coherent version.
  *.tmp                   transient write-then-rename files: skipped, and listed in the manifest.
  anything else           unknown: must be unchanged (inode, size, mtime_ns) across its read; otherwise fail.
Symlinks, special files and files vanishing mid-snapshot fail closed. Usage:
  snapshot <src_dir> <stage_dir> <manifest.json>   stage_dir must not exist
  verify   <archive.tar.gz> <manifest.json>        archive members == manifest (paths, sizes, sha256), exactly
Exit 0 = OK, 2 = integrity failure (stderr explains). Stdlib only."""
import hashlib, json, os, stat, sys, tarfile, time

VERSION = 2
APPEND, ATOMIC, STABLE = "append_prefix", "atomic_replace", "stable_whole"
CHUNK = 1 << 20


class Integrity(Exception):
    pass


def _kind(name: str) -> str | None:
    if name.endswith(".tmp"):
        return None
    if name.endswith(".jsonl"):
        return APPEND
    if name == "_recorder_stats.json":
        return ATOMIC
    return STABLE


def _read_exact(path: str, n: int) -> bytes:
    with open(path, "rb") as fh:
        data = fh.read(n)
    if len(data) != n:
        raise Integrity(f"{path}: shrank while reading ({len(data)} < {n} bytes)")
    return data


def snapshot(src: str, stage: str, manifest_path: str) -> dict:
    src = os.path.abspath(src)
    if not os.path.isdir(src):
        raise Integrity(f"evidence source missing: {src}")
    os.makedirs(stage, mode=0o700)                     # must not exist: never mix with an older copy
    files, skipped = [], []
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, src)
        os.makedirs(os.path.join(stage, rel_dir), mode=0o700, exist_ok=True)
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            rel = os.path.normpath(os.path.join(rel_dir, name))
            try:
                st0 = os.lstat(path)
            except FileNotFoundError:
                if name.endswith(".tmp"):
                    skipped.append(rel); continue
                raise Integrity(f"{rel}: vanished during snapshot")
            if not stat.S_ISREG(st0.st_mode):
                raise Integrity(f"{rel}: not a regular file (symlink or special)")
            kind = _kind(name)
            if kind is None:
                skipped.append(rel); continue
            try:
                if kind == APPEND:
                    data = _read_exact(path, st0.st_size)
                    cut = data.rfind(b"\n") + 1                  # complete records only
                    data, tail = data[:cut], st0.st_size - cut
                    again = _read_exact(path, cut)
                    if hashlib.sha256(again).digest() != hashlib.sha256(data).digest():
                        raise Integrity(f"{rel}: prefix changed (rewritten, not append-only)")
                    if os.stat(path).st_size < st0.st_size:
                        raise Integrity(f"{rel}: truncated during snapshot")
                else:
                    with open(path, "rb") as fh:
                        st_fd = os.fstat(fh.fileno())
                        data = fh.read()
                    tail = 0
                    if kind == STABLE:
                        st1 = os.stat(path)
                        if (st1.st_ino, st1.st_size, st1.st_mtime_ns) != (st0.st_ino, st0.st_size, st0.st_mtime_ns) \
                                or len(data) != st0.st_size:
                            raise Integrity(f"{rel}: changed while being read (not a known live file type)")
                    elif len(data) != st_fd.st_size:
                        raise Integrity(f"{rel}: torn read of an atomically replaced file")
            except FileNotFoundError:
                raise Integrity(f"{rel}: vanished during snapshot")
            out = os.path.join(stage, rel)
            fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush(); os.fsync(fh.fileno())
            os.chmod(out, stat.S_IMODE(st0.st_mode))
            os.utime(out, ns=(st0.st_atime_ns, st0.st_mtime_ns))
            files.append({"path": rel, "kind": kind, "source_size_at_snapshot": st0.st_size,
                          "captured_bytes": len(data), "tail_excluded_bytes": tail,
                          "sha256": hashlib.sha256(data).hexdigest(), "mode": oct(stat.S_IMODE(st0.st_mode)),
                          "uid": st0.st_uid, "gid": st0.st_gid, "mtime_ns": st0.st_mtime_ns})
    m = {"tool": "p1bg_evidence_snapshot", "version": VERSION, "source": src,
         "snapshot_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "files": files, "skipped_transient": skipped,
         "totals": {"files": len(files), "captured_bytes": sum(f["captured_bytes"] for f in files),
                    "tail_excluded_bytes": sum(f["tail_excluded_bytes"] for f in files)}}
    fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(m, fh, indent=1, sort_keys=True)
        fh.flush(); os.fsync(fh.fileno())
    return m


def verify(archive: str, manifest_path: str, root: str = "evidence_v2") -> dict:
    try:
        m = json.load(open(manifest_path))
        want = {f"{root}/{f['path']}": f for f in m["files"]}
        assert m.get("tool") == "p1bg_evidence_snapshot" and isinstance(m["files"], list)
        assert m["totals"]["files"] == len(m["files"])
    except Exception as e:
        raise Integrity(f"manifest unreadable or incomplete: {type(e).__name__}: {e}")
    seen = set()
    try:
        with tarfile.open(archive, "r:gz") as t:
            for mem in t:
                if mem.isdir():
                    continue
                if not mem.isfile():
                    raise Integrity(f"archive member {mem.name}: not a regular file")
                f = want.get(mem.name)
                if f is None:
                    raise Integrity(f"archive member {mem.name}: not in manifest")
                h = hashlib.sha256()
                fh = t.extractfile(mem)
                for chunk in iter(lambda: fh.read(CHUNK), b""):
                    h.update(chunk)
                if mem.size != f["captured_bytes"] or h.hexdigest() != f["sha256"]:
                    raise Integrity(f"archive member {mem.name}: size/sha256 differs from manifest")
                seen.add(mem.name)
    except (tarfile.TarError, EOFError, OSError) as e:
        raise Integrity(f"archive unreadable: {type(e).__name__}: {e}")
    missing = sorted(set(want) - seen)
    if missing:
        raise Integrity(f"archive lacks {len(missing)} manifest file(s), e.g. {missing[0]}")
    return {"files": len(seen), "bytes": m["totals"]["captured_bytes"]}


def main(argv):
    try:
        if argv[1:2] == ["snapshot"] and len(argv) == 5:
            r = snapshot(argv[2], argv[3], argv[4]); print(json.dumps(r["totals"]))
        elif argv[1:2] == ["verify"] and len(argv) == 4:
            print(json.dumps(verify(argv[2], argv[3])))
        else:
            print(__doc__, file=sys.stderr); return 64
    except Integrity as e:
        print(f"INTEGRITY: {e}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
