"""Integrity-checked Phase 1S checkpoint store: self-hashed shards + a hash-chained append-only journal.

Write protocol per shard: write <path>.tmp, flush, fsync, rename onto <path>, fsync the directory, then append a
`shard_commit` journal line carrying the shard's file SHA-256. Crash windows:
  * before the rename      -> a stale .tmp remains: it is discarded (journal `tmp_discarded`) and the shard, whose reps
                              were never recorded, is computed again (deterministic: identical results, no new trial);
  * after the rename, before the journal line -> an orphan shard: adopted after full validation (`shard_adopted`),
                              never recomputed;
  * a journal-committed shard missing or changed on disk -> MISSING_SHARD / SHARD_CHANGED: fail closed (evidence
                              loss is never silently repaired; `--allow-recompute-missing` journals each recompute).
Nothing here touches the MI trial ledger or the CPU budget ledger.
"""
from __future__ import annotations

import hashlib
import json
import os

from ..derive import canon


class StoreError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}")
        self.code = code


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def results_sha(results) -> str:
    return sha_bytes(canon(results).encode())


def _fsync_dir(d: str) -> None:
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: str, data: bytes) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_dir(d)


# ============================================================================ shards
def shard_doc(key: str, plan_sha: str, unit: dict, results: dict, cpu: dict) -> bytes:
    body = {"record": "tsb.mi.phase1s_shard", "v": 1, "key": key, "plan_sha256": plan_sha, "unit": unit,
            "results": results, "results_sha256": results_sha(results), "cpu": cpu}
    body["self_sha256"] = sha_bytes(canon(body).encode())
    return canon(body).encode()


def read_shard(path: str, key: str, plan_sha: str, unit: dict, expected_seeds: list) -> dict:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        doc = json.loads(raw)
    except Exception as e:
        raise StoreError("SHARD_UNREADABLE", f"{path}: {e}")
    if not isinstance(doc, dict) or doc.get("record") != "tsb.mi.phase1s_shard" or doc.get("v") != 1:
        raise StoreError("SHARD_WRONG_RECORD", path)
    claimed = doc.pop("self_sha256", None)
    if claimed != sha_bytes(canon(doc).encode()):
        raise StoreError("SHARD_SELF_HASH", path)
    if doc.get("key") != key or doc.get("plan_sha256") != plan_sha or doc.get("unit") != unit:
        raise StoreError("SHARD_PLAN_MISMATCH", path)
    res = doc.get("results") or {}
    if doc.get("results_sha256") != results_sha(res):
        raise StoreError("SHARD_RESULTS_HASH", path)
    reps = res.get("reps")
    if not isinstance(reps, list) or [r[0] for r in reps] != list(range(unit["r0"], unit["r1"])):
        raise StoreError("SHARD_REP_SET", f"{path}: reps are not exactly {unit['r0']}..{unit['r1'] - 1}")
    if [r[1] for r in reps] != expected_seeds:
        raise StoreError("SHARD_SEEDS", path)
    doc["self_sha256"] = claimed
    doc["_file_sha256"] = sha_bytes(raw)
    return doc


# ============================================================================ journal
class Journal:
    """Append-only, hash-chained JSON-lines journal (out/journal.jsonl)."""

    GENESIS = "0" * 64

    def __init__(self, path: str):
        self.path = path
        self.head = self.GENESIS
        self.seq = 0
        self.events = []
        if os.path.exists(path):
            self._load()

    def _load(self):
        with open(self.path, "rb") as fh:
            lines = fh.read().split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()
        for i, ln in enumerate(lines):
            try:
                ev = json.loads(ln)
            except Exception:
                if i == len(lines) - 1:
                    raise StoreError("JOURNAL_TORN_TAIL", f"line {i + 1} unparseable (torn write)")
                raise StoreError("JOURNAL_CORRUPT", f"line {i + 1}")
            h = ev.pop("h", None)
            if ev.get("seq") != self.seq + 1 or ev.get("prev") != self.head:
                raise StoreError("JOURNAL_CHAIN", f"line {i + 1}")
            if h != sha_bytes((self.head + canon(ev)).encode()):
                raise StoreError("JOURNAL_HASH", f"line {i + 1}")
            self.seq, self.head = ev["seq"], h
            self.events.append(ev)

    def append(self, ev: str, **fields) -> dict:
        body = {"seq": self.seq + 1, "prev": self.head, "ev": ev, **fields}
        h = sha_bytes((self.head + canon(body)).encode())
        line = canon({**body, "h": h}).encode() + b"\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        self.seq, self.head = body["seq"], h
        self.events.append(body)
        return body

    def committed(self) -> dict:
        """key -> file sha of the latest commit/adoption of each shard."""
        out = {}
        for e in self.events:
            if e["ev"] in ("shard_commit", "shard_adopted"):
                out[e["key"]] = e["file_sha256"]
            elif e["ev"] == "shard_void":
                out.pop(e["key"], None)
        return out

    def campaigns(self) -> set:
        return {e.get("campaign") for e in self.events if e["ev"] in ("shard_commit", "shard_adopted")}
