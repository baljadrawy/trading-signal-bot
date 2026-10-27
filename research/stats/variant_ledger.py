"""Append-only, hash-chained variant ledger (JSONL). Standard library only; research only.

One ``register`` event per variant, written BEFORE its result is read (roadmap §5.4), and at most one ``result``
event per variant. A registered variant without a result is an abandoned trial and still counts toward the family's
number of trials for the Deflated Sharpe Ratio.

Append-only enforcement:
* the API has no edit or delete; a variant id can be registered once and receive one result;
* every line carries ``seq``, ``prev`` (hash of the previous line) and ``hash`` (SHA-256 of its canonical JSON), and
  every read verifies the whole chain, so an in-place edit, deletion, insertion or reorder raises ``LedgerTamper``;
* tail truncation cannot be seen from the file alone: callers record ``head()`` (e.g. in a preregistration) and pass
  it back as ``verify(expected_head=...)``, which fails if the ledger no longer extends that head.

Evidence class: only ``SYNTHETIC`` is accepted without an ``authorization_ref``. Any other class (real data) is a
governed research action and must name its owner authorization / preregistration record.
Hashing pattern follows ops/research/mi_cpuguard/ledger.py (not imported: that ledger is a CPU budget).
"""
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
from math import isfinite
from statistics import variance

from research.stats.sharpe_deflation import deflated_sharpe_ratio, sharpe_ratio

GENESIS = "0" * 64
SYNTHETIC = "SYNTHETIC"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{7,64}$")
_EVENT_KEYS = {
    "register": {"variant_id", "family", "hypothesis_ref", "data_window_label", "metric", "code_sha",
                 "evidence_class", "authorization_ref", "dataset_hash", "config_hash", "cost_label"},
    "result": {"variant_id", "n", "mean", "sd", "skew", "kurtosis"},
}
_CHAIN_KEYS = {"seq", "prev", "event", "recorded_at", "hash"}


class LedgerError(Exception):
    pass


class LedgerTamper(LedgerError):
    """The file is not an unbroken chain written by this module (edited, deleted, reordered or torn)."""


class LedgerRefused(LedgerError):
    """A write the ledger rules do not allow (duplicate id, second result, unregistered id, ungoverned class)."""


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _digest(record) -> str:
    return hashlib.sha256(_canonical({k: v for k, v in record.items() if k != "hash"})).hexdigest()


def _minute(now) -> str:
    if not isinstance(now, dt.datetime) or now.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _ident(name, v):
    if not isinstance(v, str) or not _ID.match(v):
        raise ValueError(f"{name} must match {_ID.pattern}")
    return v


def _text(name, v, optional=False):
    if v is None and optional:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > 256:
        raise ValueError(f"{name} must be a non-empty string of at most 256 characters")
    return v


def _num(name, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v):
        raise ValueError(f"{name} must be a finite number")
    return float(v)


class VariantLedger:
    def __init__(self, path, *, clock=None):
        self.path = os.fspath(path)
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    # ---- reading and verification --------------------------------------------------------------------------
    def _parse(self, raw: bytes):
        if raw and not raw.endswith(b"\n"):
            raise LedgerTamper("torn or unterminated last line")
        records, prev = [], GENESIS
        for seq, line in enumerate(raw.splitlines()):
            try:
                rec = json.loads(line)
            except ValueError as exc:
                raise LedgerTamper(f"line {seq}: not JSON") from exc
            if not isinstance(rec, dict) or rec.get("event") not in _EVENT_KEYS:
                raise LedgerTamper(f"line {seq}: unknown event")
            if set(rec) != _CHAIN_KEYS | _EVENT_KEYS[rec["event"]]:
                raise LedgerTamper(f"line {seq}: unexpected fields")
            if rec["seq"] != seq or rec["prev"] != prev or rec["hash"] != _digest(rec):
                raise LedgerTamper(f"line {seq}: chain broken")
            if _canonical(rec) != line:
                raise LedgerTamper(f"line {seq}: not in canonical form")
            prev = rec["hash"]
            records.append(rec)
        self._check_rules(records)
        return records

    @staticmethod
    def _check_rules(records):
        registered, resulted = set(), set()
        for rec in records:
            vid = rec["variant_id"]
            if rec["event"] == "register":
                if vid in registered:
                    raise LedgerTamper(f"duplicate registration of {vid}")
                registered.add(vid)
            else:
                if vid not in registered or vid in resulted:
                    raise LedgerTamper(f"result for {vid} without a single prior registration")
                resulted.add(vid)

    def records(self) -> list:
        try:
            with open(self.path, "rb") as fh:
                return self._parse(fh.read())
        except FileNotFoundError:
            return []

    def head(self):
        """(next seq, hash of the last line) -- record it externally to detect later truncation or rollback."""
        recs = self.records()
        return (len(recs), recs[-1]["hash"] if recs else GENESIS)

    def verify(self, expected_head=None):
        """Verify the chain; with ``expected_head`` also require that the ledger still extends that head."""
        recs = self.records()
        if expected_head is not None:
            seq, digest = expected_head
            if seq > len(recs) or (seq > 0 and recs[seq - 1]["hash"] != digest) or (seq == 0 and digest != GENESIS):
                raise LedgerTamper("ledger does not extend the recorded head (truncated or rolled back)")
        return (len(recs), recs[-1]["hash"] if recs else GENESIS)

    # ---- writing ---------------------------------------------------------------------------------------------
    def _append(self, event, fields, check):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o644)
        with os.fdopen(fd, "r+b") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            recs = self._parse(fh.read())
            check(recs)
            rec = dict(fields, seq=len(recs), prev=recs[-1]["hash"] if recs else GENESIS, event=event,
                       recorded_at=_minute(self._clock()))
            rec["hash"] = _digest(rec)
            fh.write(_canonical(rec) + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
            return rec

    def register_variant(self, *, variant_id, family, hypothesis_ref, data_window_label, metric, code_sha,
                         evidence_class=SYNTHETIC, authorization_ref=None, dataset_hash=None, config_hash=None,
                         cost_label=None) -> dict:
        """Record that a variant is about to be evaluated. Call BEFORE its result is computed or read."""
        if not isinstance(code_sha, str) or not _SHA.match(code_sha):
            raise ValueError("code_sha must be 7-64 lowercase hex characters")
        _ident("evidence_class", evidence_class)
        if evidence_class != SYNTHETIC and _text("authorization_ref", authorization_ref, optional=True) is None:
            raise LedgerRefused("non-synthetic evidence needs an owner authorization / preregistration reference")
        fields = {
            "variant_id": _ident("variant_id", variant_id), "family": _ident("family", family),
            "hypothesis_ref": _text("hypothesis_ref", hypothesis_ref),
            "data_window_label": _text("data_window_label", data_window_label),
            "metric": _text("metric", metric), "code_sha": code_sha, "evidence_class": evidence_class,
            "authorization_ref": _text("authorization_ref", authorization_ref, optional=True),
            "dataset_hash": _text("dataset_hash", dataset_hash, optional=True),
            "config_hash": _text("config_hash", config_hash, optional=True),
            "cost_label": _text("cost_label", cost_label, optional=True),
        }

        def check(recs):
            if any(r["variant_id"] == variant_id for r in recs):
                raise LedgerRefused(f"{variant_id} already registered (the ledger is append-only)")
        return self._append("register", fields, check)

    def record_result(self, *, variant_id, n, mean, sd, skew, kurtosis) -> dict:
        """Attach the one result of a registered variant (per-observation moments; kurtosis non-excess)."""
        if isinstance(n, bool) or not isinstance(n, int) or n < 2:
            raise ValueError("n must be an int >= 2")
        fields = {"variant_id": _ident("variant_id", variant_id), "n": n, "mean": _num("mean", mean),
                  "sd": _num("sd", sd), "skew": _num("skew", skew), "kurtosis": _num("kurtosis", kurtosis)}
        if fields["sd"] <= 0:
            raise ValueError("sd must be > 0")

        def check(recs):
            if not any(r["event"] == "register" and r["variant_id"] == variant_id for r in recs):
                raise LedgerRefused(f"{variant_id} is not registered")
            if any(r["event"] == "result" and r["variant_id"] == variant_id for r in recs):
                raise LedgerRefused(f"{variant_id} already has a result (the ledger is append-only)")
        return self._append("result", fields, check)

    # ---- family views ----------------------------------------------------------------------------------------
    def variants(self, family=None) -> dict:
        """variant_id -> {"register": record, "result": record or None}, optionally for one family."""
        out = {}
        for rec in self.records():
            if rec["event"] == "register":
                if family is None or rec["family"] == family:
                    out[rec["variant_id"]] = {"register": rec, "result": None}
            elif rec["variant_id"] in out:
                out[rec["variant_id"]]["result"] = rec
        return out

    def family_counts(self) -> dict:
        """Running number of variants tried per family (registered, including abandoned ones)."""
        counts = {}
        for rec in self.records():
            if rec["event"] == "register":
                counts[rec["family"]] = counts.get(rec["family"], 0) + 1
        return counts

    def trials(self, family) -> int:
        return self.family_counts().get(family, 0)

    def trial_srs(self, family) -> list:
        return [sharpe_ratio(v["result"]["mean"], v["result"]["sd"])
                for v in self.variants(family).values() if v["result"] is not None]

    def trial_sr_variance(self, family) -> float:
        srs = self.trial_srs(family)
        if len(srs) < 2:
            raise LedgerRefused("need results for at least 2 variants to estimate the trial Sharpe variance")
        return variance(srs)

    def deflated_sharpe(self, variant_id, trial_sr_variance=None):
        """DSR of one variant with N = every variant registered in its family (abandoned ones included) and the
        variance of the family's evaluated Sharpe ratios (or a caller-supplied, preregistered variance)."""
        v = self.variants().get(variant_id)
        if v is None or v["result"] is None:
            raise LedgerRefused(f"{variant_id} has no recorded result")
        fam, res = v["register"]["family"], v["result"]
        var = self.trial_sr_variance(fam) if trial_sr_variance is None else trial_sr_variance
        return deflated_sharpe_ratio(sharpe_ratio(res["mean"], res["sd"]), res["n"], self.trials(fam), var,
                                     res["skew"], res["kurtosis"])
