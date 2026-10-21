"""Deterministic parallel map with per-unit seeds, canonical merge and checkpoint/resume.

Contract
  * A plan is an ordered list of Units (unique key, explicit seed, JSON params). The plan order
    is the canonical order; the merged output lists results in that order, whatever the worker
    count or completion order.
  * fn(unit) must be a top-level (picklable) pure function of the unit: use unit.rng() or
    unit.seed, never global random state, time or PID. It returns JSON-serialisable data
    (no NaN/Inf).
  * Results are serialised canonically; result_sha256 is the SHA-256 of the merged bytes, so
    identical inputs give byte-identical output at 1, 2, 4 ... workers.
  * Checkpoint dir (optional): plan.json binds the dir to one plan_sha256 (a different plan is
    refused). Each finished unit is written atomically by the PARENT as units/<key>.json plus
    units/<key>.sha256. On resume a unit is reused only if both files exist, the digest matches
    and key/seed/plan agree; anything else (partial temp files, truncated or tampered output) is
    moved to quarantine/ with a reason and recomputed (strict=True raises instead).
  * Worker death (e.g. OOM kill) raises BrokenProcessPool instead of hanging: we use
    concurrent.futures with the "spawn" start method, never multiprocessing.Pool.

Usage
    from research_exec.detpool import make_units, run_units
    units = make_units([f"rep-{i:04d}" for i in range(500)], base_seed=20261006,
                       params={"study": "F1"})
    res = run_units(my_rep, units, workers=None, checkpoint_dir="out/ckpt")
    # workers=None -> $RESEARCH_WORKERS (set by the runner) or 1
    open("out/merged.json", "wb").write(res.merged_bytes)
"""
from __future__ import annotations

import concurrent.futures as cf
import dataclasses
import hashlib
import json
import multiprocessing as mp
import os
import random
import re
import time

from .record import atomic_write_bytes, canonical_dumps, sha256_bytes, utc_now

KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
FORMAT = "detpool/v1"


class PlanMismatch(RuntimeError):
    pass


class CorruptUnit(RuntimeError):
    pass


def derive_seed(base_seed: int, key: str) -> int:
    """Stable 63-bit seed from (base_seed, key). Independent of Python's hash randomisation."""
    d = hashlib.sha256(f"{int(base_seed)}:{key}".encode()).digest()
    return int.from_bytes(d[:8], "big") & ((1 << 63) - 1)


@dataclasses.dataclass(frozen=True)
class Unit:
    key: str
    seed: int
    params: dict = dataclasses.field(default_factory=dict)

    def rng(self) -> random.Random:
        return random.Random(self.seed)

    def as_json(self) -> dict:
        return {"key": self.key, "seed": self.seed, "params": self.params}


def make_units(keys, base_seed: int, params: dict | None = None, per_key_params=None) -> list[Unit]:
    out = []
    for k in keys:
        p = dict(params or {})
        if per_key_params:
            p.update(per_key_params(k))
        out.append(Unit(k, derive_seed(base_seed, k), p))
    return out


def plan_sha256(units: list[Unit], fn_id: str, meta: dict | None) -> str:
    return sha256_bytes(canonical_dumps({"format": FORMAT, "fn": fn_id, "meta": meta or {},
                                         "units": [u.as_json() for u in units]}))


@dataclasses.dataclass
class RunResult:
    plan_sha256: str
    results: list            # canonical (plan) order
    merged_bytes: bytes
    result_sha256: str
    reused: int
    computed: int
    rejected: list           # [{"file", "reason"}]
    workers: int
    completion_order: list   # keys in the order they finished (diagnostic only)


def _call(fn, unit: Unit):
    res = fn(unit)
    return canonical_dumps(res)   # validate serialisability inside the worker


class _Store:
    def __init__(self, root: str, psha: str, units: list[Unit], fn_id: str, meta, strict: bool):
        self.root, self.psha, self.strict = root, psha, strict
        self.udir = os.path.join(root, "units")
        self.qdir = os.path.join(root, "quarantine")
        os.makedirs(self.udir, exist_ok=True)
        plan_path = os.path.join(root, "plan.json")
        if os.path.exists(plan_path):
            with open(plan_path, "rb") as fh:
                existing = json.loads(fh.read() or b"{}")
            if existing.get("plan_sha256") != psha:
                raise PlanMismatch(f"checkpoint dir {root} belongs to plan {existing.get('plan_sha256')}, "
                                   f"not {psha}; use a fresh dir")
        else:
            atomic_write_bytes(plan_path, canonical_dumps(
                {"format": FORMAT, "plan_sha256": psha, "fn": fn_id, "meta": meta or {},
                 "n_units": len(units), "created_at": utc_now()}))
        self.rejected = []

    def _quarantine(self, path: str, reason: str):
        os.makedirs(self.qdir, exist_ok=True)
        dst = os.path.join(self.qdir, f"{os.path.basename(path)}.{int(time.time() * 1e6)}")
        os.replace(path, dst)
        self.rejected.append({"file": os.path.basename(path), "reason": reason,
                              "quarantined_as": os.path.basename(dst)})

    def sweep_partials(self):
        for name in sorted(os.listdir(self.udir)):
            if ".tmp-" in name:
                self._quarantine(os.path.join(self.udir, name), "partial_temp_file")

    def load(self, u: Unit):
        jp, sp = os.path.join(self.udir, f"{u.key}.json"), os.path.join(self.udir, f"{u.key}.sha256")
        if not os.path.exists(jp) and not os.path.exists(sp):
            return None
        reason = None
        try:
            with open(jp, "rb") as fh:
                data = fh.read()
            with open(sp, "r") as fh:
                want = fh.read().strip()
            if sha256_bytes(data) != want:
                reason = "sha256_mismatch"
            else:
                doc = json.loads(data)
                if (doc.get("key"), doc.get("seed"), doc.get("plan_sha256")) != (u.key, u.seed, self.psha):
                    reason = "identity_mismatch"
                elif "result" not in doc:
                    reason = "no_result"
                else:
                    return doc["result"]
        except FileNotFoundError:
            reason = "missing_pair_file"
        except (ValueError, UnicodeDecodeError):
            reason = "unparseable"
        if self.strict:
            raise CorruptUnit(f"unit {u.key}: {reason}")
        for p in (jp, sp):
            if os.path.exists(p):
                self._quarantine(p, reason)
        return None

    def save(self, u: Unit, result_bytes: bytes):
        doc = (b'{"key":' + canonical_dumps(u.key) + b',"plan_sha256":' + canonical_dumps(self.psha) +
               b',"result":' + result_bytes + b',"seed":' + canonical_dumps(u.seed) + b"}")
        # write payload first, digest second: a unit is valid only when both exist and agree
        atomic_write_bytes(os.path.join(self.udir, f"{u.key}.json"), doc)
        atomic_write_bytes(os.path.join(self.udir, f"{u.key}.sha256"), (sha256_bytes(doc) + "\n").encode())


def run_units(fn, units: list[Unit], *, workers: int | None = None, checkpoint_dir: str | None = None,
              meta: dict | None = None, strict: bool = False, fn_id: str | None = None,
              _test_shuffle_seed: int | None = None, progress=None) -> RunResult:
    keys = [u.key for u in units]
    if len(set(keys)) != len(keys):
        raise ValueError("unit keys must be unique")
    bad = [k for k in keys if not KEY_RE.match(k)]
    if bad:
        raise ValueError(f"invalid unit keys (allowed [A-Za-z0-9._-], max 128): {bad[:3]}")
    if workers is None:
        workers = int(os.environ.get("RESEARCH_WORKERS", "1") or 1)
    workers = max(1, int(workers))
    fn_id = fn_id or f"{fn.__module__}.{getattr(fn, '__qualname__', fn.__name__)}"
    psha = plan_sha256(units, fn_id, meta)
    store = _Store(checkpoint_dir, psha, units, fn_id, meta, strict) if checkpoint_dir else None
    results: dict[str, bytes] = {}
    reused = 0
    if store:
        store.sweep_partials()
        for u in units:
            r = store.load(u)
            if r is not None:
                results[u.key] = canonical_dumps(r)
                reused += 1
    todo = [u for u in units if u.key not in results]
    if _test_shuffle_seed is not None:
        random.Random(_test_shuffle_seed).shuffle(todo)
    order = []

    def _done(u, rb):
        results[u.key] = rb
        order.append(u.key)
        if store:
            store.save(u, rb)
        if progress:
            progress(len(results), len(units))

    if workers == 1 or len(todo) <= 1:
        for u in todo:
            _done(u, _call(fn, u))
    else:
        ctx = mp.get_context("spawn")
        with cf.ProcessPoolExecutor(max_workers=min(workers, len(todo)), mp_context=ctx) as ex:
            futs = {ex.submit(_call, fn, u): u for u in todo}
            try:
                for f in cf.as_completed(futs):
                    _done(futs[f], f.result())
            except BaseException:
                for f in futs:
                    f.cancel()
                raise

    merged = (b'{"format":' + canonical_dumps(FORMAT) + b',"plan_sha256":' + canonical_dumps(psha) +
              b',"units":[' + b",".join(b'{"key":' + canonical_dumps(k) + b',"result":' + results[k] + b"}"
                                         for k in keys) + b"]}")
    rsha = sha256_bytes(merged)
    if store:
        atomic_write_bytes(os.path.join(checkpoint_dir, "manifest.json"), canonical_dumps({
            "format": FORMAT, "plan_sha256": psha, "result_sha256": rsha, "n_units": len(units),
            "units": {k: sha256_bytes(results[k]) for k in keys},
            "reused": reused, "computed": len(todo), "rejected": store.rejected,
            "workers": workers, "completed_at": utc_now()}))
    return RunResult(psha, [json.loads(results[k]) for k in keys], merged, rsha, reused, len(todo),
                     store.rejected if store else [], workers, order)


def verify_checkpoint(checkpoint_dir: str) -> dict:
    """Audit a completed checkpoint dir against its manifest (read-only)."""
    with open(os.path.join(checkpoint_dir, "manifest.json"), "rb") as fh:
        man = json.loads(fh.read())
    problems = []
    for k, want in man["units"].items():
        jp = os.path.join(checkpoint_dir, "units", f"{k}.json")
        try:
            with open(jp, "rb") as fh:
                doc = json.loads(fh.read())
            if sha256_bytes(canonical_dumps(doc["result"])) != want:
                problems.append({"key": k, "problem": "result_digest_mismatch"})
        except (FileNotFoundError, ValueError, KeyError) as exc:
            problems.append({"key": k, "problem": type(exc).__name__})
    return {"ok": not problems, "problems": problems, "result_sha256": man["result_sha256"]}
