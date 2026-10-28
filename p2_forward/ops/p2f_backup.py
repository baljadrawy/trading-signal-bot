#!/usr/bin/env python3
"""Sealed-day backup of the continuous forward dataset (P2-CR Package D; F29 corrected). HOST-SIDE, stdlib only.

  p2f_backup.py backup <dataset_dir> <YYYY-MM-DD> [--dest DIR] [--floor-gb 60]
  p2f_backup.py restore-test <dataset_dir> <YYYY-MM-DD> [--dest DIR] [--allow-test-calendar]

Owner decision D1 (2026-10-04): ON-HOST SEALED-DAY BACKUP for the initial continuous period. This is NOT disaster
recovery: the copy is on the same disk/host as the source (host loss is an accepted residual risk).

backup — only a day with a PASS seal (seals/D.json + its report): copies
  raw/*/D/* (.jsonl.gz + .sha256 + .idx), the next day's first-hour spillover segments (+ sidecars),
  manifests/D.jsonl + a snapshot of manifests/D+1.jsonl, days/D.json, seals/D.json + report, dataset.json,
  all run / downtime records, stop markers, the universe artifacts (and their raw REST inputs) of the day's epochs.
  Free-space precheck (destination must keep >= floor GB free after the copy, with 2x margin). SHA-256 verified at
  source (against the manifest / sidecars) and destination; SHA256SUMS; read-only; atomic rename into place.
  An existing destination is never overwritten (immutable). Never deletes source or destination data.
restore-test — re-verifies SHA256SUMS and runs the independent day verifier on the backup copy itself.
Failures exit non-zero and write incidents/external/backup-D-<ms>.json in the source dataset (visible).

--verify-existing (optional, OFF by default; without it an existing destination is reported exactly as before:
  FAIL destination_exists_immutable, exit 3, no incident). With it, an existing destination is verified read-only:
  every file listed in its SHA256SUMS hashes to the listed digest, it holds no unlisted file, BACKUP.json names this
  day / dataset and the current seal's SHA-256, and every day-scoped immutable source file (dataset.json, days/D,
  seals/D + report, manifests/D, raw/**, universe/**) is listed with the source's current digest, with the same set.
  Snapshot members (manifests/D+1, runs/, control/, docs/) are checked inside the copy only, because the source
  legitimately grows after the backup. Identical: prints {"backup": "OK (exists)", ...} and exits 0. Any difference:
  FAIL existing_destination_mismatch (exit 1 + incident). Nothing is ever overwritten or deleted. This reads (hashes)
  the whole day twice (source and copy) on every invocation.
"""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (os.path.join(HERE, "..", "verifier"), os.path.join(HERE, "verifier")):
    if os.path.exists(os.path.join(cand, "verify_continuous.py")):
        sys.path.insert(0, os.path.abspath(cand)); break
import verify_continuous as VC                                    # noqa: E402

DEFAULT_DEST = "/home/tradmin/backups/tsb-p2-forward"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class BackupError(Exception):
    pass


def incident(base, day, reason, detail=None):
    d = os.path.join(base, "incidents", "external"); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"backup-{day}-{int(time.time() * 1000)}.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"job": "sealed_day_backup", "day": day, "result": "FAIL", "severity": "DEGRADED",
                   "reason": reason, "detail": detail}, fh, sort_keys=True, default=str)
    os.chmod(p, 0o444)


def file_set(base, day, seal_report):
    """Relative paths to copy (all must exist)."""
    ds = json.load(open(os.path.join(base, "dataset.json"), encoding="utf-8"))
    cal = VC.Calendar(ds["calendar"])
    nxt = cal.day_key(cal.day_end(day))
    n_spill = min(24, max(1, -(-60_000 // cal.hour_ms)))
    hours = {cal.hour_key(cal.day_end(day) + i * cal.hour_ms) for i in range(n_spill)}
    out = ["dataset.json", f"days/{day}.json", f"seals/{day}.json", f"seals/{day}.report.json", f"manifests/{day}.jsonl"]
    if os.path.exists(os.path.join(base, "manifests", f"{nxt}.jsonl")):
        out.append(f"manifests/{nxt}.jsonl")
    raw = os.path.join(base, "raw")
    for t in sorted(os.listdir(raw)):
        for d_, spill in ((day, False), (nxt, True)):
            dd = os.path.join(raw, t, d_)
            if not os.path.isdir(dd):
                continue
            for f in sorted(os.listdir(dd)):
                if spill and not any(f"-{h}Z-" in f for h in hours):
                    continue
                if f.endswith((".partial", ".pending", ".certifying", ".tmp")):
                    raise BackupError(f"uncertified_file:{t}/{d_}/{f}")
                out.append(f"raw/{t}/{d_}/{f}")
    for sub in ("runs", "control"):
        p = os.path.join(base, sub)
        out += [f"{sub}/{f}" for f in sorted(os.listdir(p)) if f.endswith(".json")] if os.path.isdir(p) else []
    ud = os.path.join(base, "universe")
    by_id = {}
    for f in sorted(os.listdir(ud)) if os.path.isdir(ud) else []:
        if f.endswith(".json"):
            with open(os.path.join(ud, f), encoding="utf-8") as fh:
                by_id[json.load(fh).get("universe_id")] = f"universe/{f}"
    todo = list(seal_report.get("universe_files") or [])
    for uf in list(todo):                                      # + the prior artifact each universe's hysteresis used
        doc = json.load(open(os.path.join(base, uf), encoding="utf-8"))
        if doc.get("prior_universe_id"):
            if doc["prior_universe_id"] not in by_id:
                raise BackupError(f"prior_universe_missing:{doc['prior_universe_id']}")
            todo.append(by_id[doc["prior_universe_id"]])
    for uf in sorted(set(todo)):
        out.append(uf)
        doc = json.load(open(os.path.join(base, uf), encoding="utf-8"))
        for k, src in (doc.get("source") or {}).items():
            if src.get("raw_file"):
                out.append(src["raw_file"])
    p = os.path.join(base, "docs")
    out += [f"docs/{f}" for f in sorted(os.listdir(p))] if os.path.isdir(p) else []
    return sorted(set(out))


def _immutable(rel, day):
    """Day-scoped source files that never change after the seal (compared with the source by --verify-existing)."""
    return rel in ("dataset.json", f"days/{day}.json", f"seals/{day}.json", f"seals/{day}.report.json",
                   f"manifests/{day}.jsonl") or rel.startswith(("raw/", "universe/"))


def verify_existing(base, day, seal, seal_p, out):
    """Read-only check that the existing immutable backup `out` is this sealed day, intact and hash-identical to
    the source's immutable files. Raises BackupError(existing_destination_mismatch:...) on any difference."""
    def bad(why):
        return BackupError(f"existing_destination_mismatch:{why}:{out}")

    def digest(path, rel, side):
        try:
            return sha(path)
        except OSError as e:                                    # unreadable file: a loud mismatch, never a traceback
            raise bad(f"{side}_unreadable:{type(e).__name__}:{rel}") from None
    try:
        with open(os.path.join(out, "SHA256SUMS"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        with open(os.path.join(out, "BACKUP.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError) as e:
        raise bad(f"unreadable:{type(e).__name__}") from None
    listed = {}
    for line in lines:
        d0, sep, r = line.partition("  ")
        if not sep or len(d0) != 64 or not r or r in listed:
            raise bad("sha256sums_malformed")
        listed[r] = d0
    if meta.get("day") != day or meta.get("dataset_id") != seal.get("dataset_id") or \
            meta.get("seal_sha256") != sha(seal_p) or meta.get("files") != len(listed):
        raise bad("backup_record_differs")
    present = set()
    for root, dirs, files in os.walk(out):
        for f in files:
            present.add(os.path.relpath(os.path.join(root, f), out))
    extra = sorted(present - set(listed) - {"SHA256SUMS", "BACKUP.json"})
    missing = sorted(set(listed) - present)
    if extra or missing:
        raise bad(f"file_set_differs:extra={extra[:3]},missing={missing[:3]}")
    for r, d0 in sorted(listed.items()):
        if digest(os.path.join(out, r), r, "copy") != d0:
            raise bad(f"copy_digest_differs:{r}")
    try:
        cur = {r for r in file_set(base, day, seal) if _immutable(r, day)}
    except (OSError, ValueError) as e:
        raise bad(f"source_unreadable:{type(e).__name__}") from None
    lst = {r for r in listed if _immutable(r, day)}
    if cur != lst:
        raise bad(f"source_set_differs:only_source={sorted(cur - lst)[:3]},only_copy={sorted(lst - cur)[:3]}")
    for r in sorted(cur):
        if digest(os.path.join(base, r), r, "source") != listed[r]:
            raise bad(f"source_digest_differs:{r}")
    return {"backup": "OK (exists)", "day": day, "dest": out, "files": len(listed), "verified": "sha256"}


def backup(base, day, dest_root, floor_gb, verify_existing_dest=False):
    seal_p = os.path.join(base, "seals", f"{day}.json")
    if not os.path.exists(seal_p):
        raise BackupError("not_sealed")                       # active / partial / failed days are never backed up
    seal = json.load(open(seal_p, encoding="utf-8"))
    if seal.get("result") != "PASS" or sha(os.path.join(base, "seals", f"{day}.report.json")) != seal.get("report_sha256"):
        raise BackupError("seal_not_pass_or_report_mismatch")
    ds_id = seal["dataset_id"]
    out = os.path.join(dest_root, ds_id, day)
    if os.path.exists(out):
        if verify_existing_dest:                                # optional: identical existing copy = OK (exists)
            return verify_existing(base, day, seal, seal_p, out)
        raise BackupError(f"destination_exists_immutable:{out}")
    rels = file_set(base, day, seal)
    need = sum(os.path.getsize(os.path.join(base, r)) for r in rels)
    os.makedirs(os.path.join(dest_root, ds_id), exist_ok=True)
    free = shutil.disk_usage(dest_root).free
    if free - 2 * need < floor_gb * 1e9:
        raise BackupError(f"free_space_precheck:free={free / 1e9:.1f}GB need2x={2 * need / 1e9:.3f}GB floor={floor_gb}GB")
    man = {}
    for m in [r for r in rels if r.startswith("manifests/")]:
        for line in open(os.path.join(base, m), encoding="utf-8"):
            e = json.loads(line); man[e["segment"]] = e
    tmp = os.path.join(dest_root, ds_id, f".incomplete-{day}-{int(time.time())}")
    os.makedirs(tmp)
    sums = []
    for r in rels:
        src = os.path.join(base, r)
        d0 = sha(src)
        if r.endswith(".jsonl.gz"):
            with open(src + ".sha256", encoding="utf-8") as fh:
                side = fh.read().split()[0]
            if d0 != side or (man.get(r) or {}).get("sha256") != d0:
                raise BackupError(f"source_checksum_mismatch:{r}")
        dst = os.path.join(tmp, r)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if sha(dst) != d0:
            raise BackupError(f"copy_checksum_mismatch:{r}")
        sums.append(f"{d0}  {r}\n")
    with open(os.path.join(tmp, "SHA256SUMS"), "w", encoding="utf-8") as fh:
        fh.write("".join(sums)); fh.flush(); os.fsync(fh.fileno())
    with open(os.path.join(tmp, "BACKUP.json"), "w", encoding="utf-8") as fh:
        json.dump({"record": "tsb.p2.forward.sealed_day_backup", "day": day, "dataset_id": ds_id, "files": len(rels),
                   "bytes": need, "seal_sha256": sha(seal_p), "created_ms": int(time.time() * 1000),
                   "scope": "ON-HOST (owner D1, 2026-10-04): not disaster recovery"}, fh, sort_keys=True, indent=1)
    for root, dirs, files in os.walk(tmp):
        for f in files:
            os.chmod(os.path.join(root, f), 0o444)
    os.sync()
    os.rename(tmp, out)
    for root, dirs, files in os.walk(out, topdown=False):
        for x in dirs:
            os.chmod(os.path.join(root, x), 0o555)
    os.chmod(out, 0o555)
    return {"backup": "OK", "day": day, "dest": out, "files": len(rels), "bytes": need}


def restore_test(base, day, dest_root, allow_test_calendar):
    seal = json.load(open(os.path.join(base, "seals", f"{day}.json"), encoding="utf-8"))
    out = os.path.join(dest_root, seal["dataset_id"], day)
    bad = []
    for line in open(os.path.join(out, "SHA256SUMS"), encoding="utf-8"):
        d0, r = line.rstrip("\n").split("  ", 1)
        if sha(os.path.join(out, r)) != d0:
            bad.append(r)
    if bad:
        raise BackupError(f"restore_checksum_mismatch:{bad[:5]}")
    rep = VC.verify_day(out, day, allow_test_calendar)
    if not rep["PASS"]:
        raise BackupError(f"restore_day_verification_failed:{dict(list(rep['failures'].items())[:10])}")
    return {"restore_test": "PASS", "day": day, "dest": out, "files": rep["info"].get("files"),
            "totals": rep["info"].get("totals")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["backup", "restore-test"])
    ap.add_argument("base"); ap.add_argument("day")
    ap.add_argument("--dest", default=DEFAULT_DEST); ap.add_argument("--floor-gb", type=float, default=60.0)
    ap.add_argument("--allow-test-calendar", action="store_true")
    ap.add_argument("--verify-existing", action="store_true",
                    help="optional (OFF by default): an existing hash-identical destination is OK (exists), exit 0")
    a = ap.parse_args(argv)
    os.makedirs(a.dest, exist_ok=True)
    lock = open(os.path.join(a.dest, ".lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"backup": "busy"})); return 75
    try:
        res = backup(a.base, a.day, a.dest, a.floor_gb, a.verify_existing) if a.mode == "backup" else \
            restore_test(a.base, a.day, a.dest, a.allow_test_calendar)
    except BackupError as e:
        if not str(e).startswith(("not_sealed", "destination_exists")):
            incident(a.base, a.day, str(e)[:300])
        print(json.dumps({a.mode: "FAIL", "day": a.day, "reason": str(e)[:500]}), file=sys.stderr)
        return 1 if not str(e).startswith(("not_sealed", "destination_exists")) else 3
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
