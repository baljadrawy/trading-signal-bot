"""Research Trial Ledger (P2-C delta B): append-only, hash-chained JSONL record of every research trial.

Spec: docs/p2/P2C_TRIAL_LEDGER.md; JSON schema: p2_research/schemas/trial_ledger_v1.schema.json.

Rules enforced here (no update / delete API exists):
  * ``create_trial(spec)`` validates and freezes a trial spec and appends a ``trial_created`` event. The trial ID is
    derived from the canonical spec SHA-256 plus a creation sequence (the number of earlier trials with the same
    spec), so the same history + spec always yields the same ID and a re-run of an identical spec gets a new ID.
  * ``record_result(trial_id, result)`` appends ONE ``trial_result`` event (accepted / rejected / inconclusive).
    A second result for a trial is refused: a failure can never be overwritten by a later success. A re-test is a
    new trial with ``parent_trial`` set, which keeps every attempt countable (Deflated Sharpe / PBO need N trials).
  * Every event carries ``seq``, ``prev_hash`` and ``event_hash`` (SHA-256 of the canonical event without
    ``event_hash``); ``verify()`` recomputes the chain, the trial IDs and the rules and reports tampering.
    Truncation of the newest events is detectable only against an externally recorded ``head()``.
  * Periods overlapping the sealed holdout W3 = [2026-08-19T09:33:46Z, 2026-10-04T15:26:43.497803Z) are refused,
    and every spec must state ``holdout.w3 = "sealed_forbidden"``.
  * Market must be an authorized market (crypto Binance spot only, see ``instrument.SUPPORTED_MARKETS``).

This module records research bookkeeping only: it computes no metric and runs no optimization.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import re

from . import instrument as IN

LEDGER_RECORD = "tsb.p2c.trial_ledger"
LEDGER_VERSION = 1
DEFAULT_LEDGER_DIR = "/home/tradmin/research-data/trading-signal-bot/p2c/ledger"
FORBIDDEN_ROOT = "/home/tradmin/research-data/trading-signal-bot/p2"         # the collector's raw-data tree
LEDGER_FILE = "trials.jsonl"
GENESIS = "0" * 64

W3_START = dt.datetime(2026, 8, 19, 9, 33, 46, tzinfo=dt.timezone.utc)
W3_END = dt.datetime(2026, 10, 4, 15, 26, 43, 497803, tzinfo=dt.timezone.utc)   # recovery epoch E (exclusive)

STATUSES = ("accepted", "rejected", "inconclusive")
HOLDOUT_W3 = "sealed_forbidden"
SPEC_FIELDS = {          # field -> type (validated); all required, ``parent_trial`` may be null
    "hypothesis_id": str, "code_commit": str, "dataset": dict, "feature_set_version": str,
    "label_set_version": str, "universe_policy": str, "market": dict, "strategy_family": str,
    "parameter_spec": dict, "transaction_cost_assumptions": dict, "execution_assumptions": dict,
    "train_period": dict, "validation_period": dict, "holdout": dict, "metrics_requested": list,
    "parent_trial": (str, type(None)),
}
RESULT_FIELDS = {"status": str, "rejection_reason": (str, type(None)), "metrics": dict, "evidence": dict,
                 "notes": (str, type(None))}
_HYP = re.compile(r"^H-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_TRIAL = re.compile(r"^TR-[0-9a-f]{24}$")


class LedgerError(Exception):
    pass


class SpecError(LedgerError):
    pass


class W3SealedError(SpecError):
    pass


class ResultConflict(LedgerError):
    pass


class LedgerTamper(LedgerError):
    pass


def canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _ts(s, what) -> dt.datetime:
    if not isinstance(s, str) or not s.endswith("Z"):
        raise SpecError(f"{what}: ISO-8601 UTC timestamp ending in Z required")
    try:
        t = dt.datetime.fromisoformat(s[:-1] + "+00:00")
    except ValueError:
        raise SpecError(f"{what}: invalid timestamp {s!r}") from None
    return t


def _period(p, what) -> tuple:
    if not isinstance(p, dict) or set(p) != {"start", "end"}:
        raise SpecError(f"{what}: {{start, end}} required")
    a, b = _ts(p["start"], f"{what}.start"), _ts(p["end"], f"{what}.end")
    if not a < b:
        raise SpecError(f"{what}: start must be before end")
    if a < W3_END and b > W3_START:                    # half-open [a, b) overlaps [W3_START, W3_END)
        raise W3SealedError(f"{what} [{p['start']}, {p['end']}) overlaps the sealed holdout W3 "
                            f"[{W3_START.isoformat()}, {W3_END.isoformat()}); refused")
    return a, b


def validate_spec(spec: dict) -> dict:
    """Return a normalized copy of a trial spec or raise SpecError / W3SealedError."""
    if not isinstance(spec, dict):
        raise SpecError("spec must be an object")
    missing, extra = set(SPEC_FIELDS) - set(spec), set(spec) - set(SPEC_FIELDS)
    if missing or extra:
        raise SpecError(f"spec fields: missing={sorted(missing)} unexpected={sorted(extra)}")
    for k, t in SPEC_FIELDS.items():
        if not isinstance(spec[k], t) or (t is str and not spec[k]):
            raise SpecError(f"{k}: wrong type or empty")
    if not _HYP.match(spec["hypothesis_id"]):
        raise SpecError("hypothesis_id must look like H-<name> (strategy research starts from a documented hypothesis)")
    if not _COMMIT.match(spec["code_commit"]):
        raise SpecError("code_commit must be a hex git SHA")
    ds = spec["dataset"]
    if not isinstance(ds.get("dataset_id"), str) or not re.match(r"^[0-9a-f]{64}$", str(ds.get("dataset_hash"))):
        raise SpecError("dataset: {dataset_id, dataset_hash (sha256 hex)} required")
    try:
        IN.require_supported_market(spec["market"])
    except IN.UnsupportedMarket as e:
        raise SpecError(str(e)) from None
    if spec["holdout"].get("w3") != HOLDOUT_W3:
        raise W3SealedError("holdout.w3 must be 'sealed_forbidden' (W3 is never used for any trial)")
    tr = _period(spec["train_period"], "train_period")
    va = _period(spec["validation_period"], "validation_period")
    if va[0] < tr[1]:
        raise SpecError("validation_period must start at or after the end of train_period")
    for k, v in spec["holdout"].items():
        if k != "w3" and v is not None:
            _period(v, f"holdout.{k}")
    if not spec["metrics_requested"] or not all(isinstance(x, str) and x for x in spec["metrics_requested"]):
        raise SpecError("metrics_requested: non-empty list of metric names")
    if spec["parent_trial"] is not None and not _TRIAL.match(spec["parent_trial"]):
        raise SpecError("parent_trial must be a trial id or null")
    return json.loads(canon(spec))


def _validate_result(result: dict) -> dict:
    if not isinstance(result, dict) or set(result) != set(RESULT_FIELDS):
        raise LedgerError(f"result fields must be exactly {sorted(RESULT_FIELDS)}")
    for k, t in RESULT_FIELDS.items():
        if not isinstance(result[k], t):
            raise LedgerError(f"result.{k}: wrong type")
    if result["status"] not in STATUSES:
        raise LedgerError(f"result.status must be one of {STATUSES}")
    if result["status"] == "rejected" and not (result["rejection_reason"] or "").strip():
        raise LedgerError("a rejected trial needs a rejection_reason")
    return json.loads(canon(result))


def trial_id_for(spec_sha: str, creation_seq: int) -> str:
    return "TR-" + _sha(f"{spec_sha}|{creation_seq}")[:24]


def _event_hash(ev: dict) -> str:
    return _sha(canon({k: v for k, v in ev.items() if k != "event_hash"}))


class Ledger:
    def __init__(self, ledger_dir: str = DEFAULT_LEDGER_DIR):
        real = os.path.realpath(ledger_dir)
        fr = os.path.realpath(FORBIDDEN_ROOT)
        if real == fr or real.startswith(fr.rstrip("/") + "/"):
            raise LedgerError(f"ledger may not live inside the collector raw-data tree: {ledger_dir}")
        self.dir = ledger_dir
        self.path = os.path.join(ledger_dir, LEDGER_FILE)

    # ---------------- read ----------------
    def events(self) -> list:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [json.loads(x) for x in fh if x.strip()]

    def head(self) -> dict:
        ev = self.events()
        return {"seq": ev[-1]["seq"] if ev else -1, "event_hash": ev[-1]["event_hash"] if ev else GENESIS}

    def trials(self) -> dict:
        out = {}
        for e in self.events():
            if e["event"] == "trial_created":
                out[e["trial_id"]] = {"spec": e["payload"]["spec"], "created_at": e["at"], "result": None}
            elif e["event"] == "trial_result" and e["trial_id"] in out:
                out[e["trial_id"]]["result"] = e["payload"]
        return out

    def trial_counts(self) -> dict:
        """Per hypothesis: number of trials (all attempts, including failed and pending) and results by status."""
        out = {}
        for tid, t in self.trials().items():
            h = out.setdefault(t["spec"]["hypothesis_id"], {"trials": 0, "pending": 0, **{s: 0 for s in STATUSES}})
            h["trials"] += 1
            h[t["result"]["status"] if t["result"] else "pending"] += 1
        return dict(sorted(out.items()))

    # ---------------- append (the only write path) ----------------
    def _append(self, build) -> dict:
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, ".lock"), "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            rep = self.verify()
            if not rep["ok"]:
                raise LedgerTamper(f"ledger failed verification, refusing to append: {rep['errors'][:3]}")
            ev = build(self.events())
            ev["seq"], ev["prev_hash"] = rep["head"]["seq"] + 1, rep["head"]["event_hash"]
            ev["ledger"], ev["ledger_version"] = LEDGER_RECORD, LEDGER_VERSION
            ev["event_hash"] = _event_hash(ev)
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, (canon(ev) + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            return ev

    def create_trial(self, spec: dict, *, now: str | None = None) -> str:
        norm = validate_spec(spec)
        spec_sha = _sha(canon(norm))
        at = now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        def build(events):
            if norm["parent_trial"] is not None and not any(
                    e["event"] == "trial_created" and e["trial_id"] == norm["parent_trial"] for e in events):
                raise SpecError(f"parent_trial {norm['parent_trial']} not in ledger")
            n = sum(1 for e in events if e["event"] == "trial_created" and e["payload"]["spec_sha256"] == spec_sha)
            return {"event": "trial_created", "trial_id": trial_id_for(spec_sha, n), "at": at,
                    "payload": {"spec": norm, "spec_sha256": spec_sha, "creation_seq": n}}
        return self._append(build)["trial_id"]

    def record_result(self, trial_id: str, result: dict, *, now: str | None = None) -> dict:
        res = _validate_result(result)
        at = now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        def build(events):
            if not any(e["event"] == "trial_created" and e["trial_id"] == trial_id for e in events):
                raise LedgerError(f"unknown trial {trial_id}")
            prev = [e for e in events if e["event"] == "trial_result" and e["trial_id"] == trial_id]
            if prev:
                raise ResultConflict(f"trial {trial_id} already has result {prev[0]['payload']['status']!r}; results are "
                                     "immutable - register a new trial with parent_trial for a re-test")
            return {"event": "trial_result", "trial_id": trial_id, "at": at, "payload": res}
        return self._append(build)

    # ---------------- verification ----------------
    def verify(self, expected_head: dict | None = None) -> dict:
        errors, created, results, spec_seen = [], {}, set(), {}
        prev, seq = GENESIS, -1
        lines = []
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                lines = [x for x in fh.read().split("\n") if x.strip()]
        for i, line in enumerate(lines):
            try:
                ev = json.loads(line)
            except ValueError:
                errors.append(f"line {i}: not JSON")
                break
            if canon(ev) != line:
                errors.append(f"line {i}: not canonical")
            if ev.get("ledger") != LEDGER_RECORD or ev.get("ledger_version") != LEDGER_VERSION:
                errors.append(f"line {i}: wrong ledger record/version")
            if ev.get("seq") != i:
                errors.append(f"line {i}: seq {ev.get('seq')} != {i}")
            if ev.get("prev_hash") != prev:
                errors.append(f"line {i}: hash-chain break (prev_hash)")
            if ev.get("event_hash") != _event_hash(ev):
                errors.append(f"line {i}: event_hash mismatch (content altered)")
            prev, seq = ev.get("event_hash"), i
            kind, tid, p = ev.get("event"), ev.get("trial_id"), ev.get("payload") or {}
            if kind == "trial_created":
                try:
                    norm = validate_spec(p.get("spec"))
                except LedgerError as e:
                    errors.append(f"line {i}: invalid spec ({e})")
                    continue
                ss = _sha(canon(norm))
                n = spec_seen.get(ss, 0)
                if p.get("spec_sha256") != ss or p.get("creation_seq") != n or tid != trial_id_for(ss, n):
                    errors.append(f"line {i}: trial id / spec hash mismatch")
                if tid in created:
                    errors.append(f"line {i}: duplicate trial id")
                if norm["parent_trial"] is not None and norm["parent_trial"] not in created:
                    errors.append(f"line {i}: parent_trial not earlier in ledger")
                spec_seen[ss] = n + 1
                created[tid] = i
            elif kind == "trial_result":
                if tid not in created:
                    errors.append(f"line {i}: result for unknown trial")
                if tid in results:
                    errors.append(f"line {i}: second result for {tid} (overwrite attempt)")
                try:
                    _validate_result(p)
                except LedgerError as e:
                    errors.append(f"line {i}: invalid result ({e})")
                results.add(tid)
            else:
                errors.append(f"line {i}: unknown event {kind!r}")
        head = {"seq": seq, "event_hash": prev}
        if expected_head is not None and (seq < expected_head["seq"] or (
                seq == expected_head["seq"] and prev != expected_head["event_hash"])):
            errors.append(f"head {head} does not match/extend the recorded head {expected_head} (truncation)")
        return {"ok": not errors, "errors": errors, "events": len(lines), "trials": len(created),
                "results": len(results), "head": head}


def create_trial(spec: dict, ledger_dir: str = DEFAULT_LEDGER_DIR, **kw) -> str:
    return Ledger(ledger_dir).create_trial(spec, **kw)


def record_result(trial_id: str, result: dict, ledger_dir: str = DEFAULT_LEDGER_DIR, **kw) -> dict:
    return Ledger(ledger_dir).record_result(trial_id, result, **kw)


def verify(ledger_dir: str = DEFAULT_LEDGER_DIR, expected_head: dict | None = None) -> dict:
    return Ledger(ledger_dir).verify(expected_head)
