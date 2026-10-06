"""P2-F0 frozen contracts: load, verify, bind to P2-D0 / P2-X, register candidates, choose the applicable version.

Frozen set (``contracts/``): ``f0_protocol_v1.json`` (tests, parameters, verdict taxonomy), ``f0_evidence_schema_v1.json``
(input contract), ``f0_forward_v1.json`` (forward-survival rules), ``f0_calibration_plan_v1.json`` (synthetic
validation design) and ``FROZEN_SHA256SUMS.json``. ``contract_set_sha256`` = SHA-256 of the sums file; every verdict
and every registration carries it.

Versioning (anti-retroactivity): a changed rule is a NEW file version with a new sums file; old files are never
edited. ``applicable_version`` picks, for a candidate, the latest version frozen strictly before the first
``trial_result`` of its round in the Trial Ledger; a newer version can only add a second verdict and the more
conservative one governs (``governing_verdict``).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os

from .. import ledger as LG
from .. import protocol as D0

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT_DIR = os.path.join(HERE, "contracts")
FILES = ("f0_protocol_v1.json", "f0_evidence_schema_v1.json", "f0_forward_v1.json", "f0_calibration_plan_v1.json")
SUMS = "FROZEN_SHA256SUMS.json"
REPO = os.path.dirname(os.path.dirname(HERE))
REG_RECORD = "tsb.p2f.candidate_registration"
IN_SAMPLE_ORDER = ("INVALID_EVIDENCE", "INSUFFICIENT_EVIDENCE", "REJECTED", "FRAGILE", "FORWARD_CONFIRMATION_REQUIRED",
                   "PROVISIONAL")


class ContractError(Exception):
    pass


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def dump_frozen(obj) -> str:
    return D0.dump_frozen(obj)


def load(name: str, directory: str = CONTRACT_DIR) -> dict:
    with open(os.path.join(directory, name), encoding="utf-8") as fh:
        return json.load(fh)


def verify(directory: str = CONTRACT_DIR) -> str:
    """Recompute every frozen F0 file hash against the sums file; return contract_set_sha256 or raise."""
    sums = load(SUMS, directory)
    if sums.get("record") != "tsb.p2f.frozen_sha256" or set(sums.get("files", {})) != set(FILES):
        raise ContractError("F0 frozen file set mismatch")
    bad = [f for f in FILES if sha256_file(os.path.join(directory, f)) != sums["files"][f]]
    if bad:
        raise ContractError(f"F0 contract altered (hash mismatch): {bad}")
    return sha256_file(os.path.join(directory, SUMS))


def verify_dependencies(proto: dict, repo: str = REPO) -> dict:
    """The P2-D0 and P2-X frozen sum files must still have the hashes P2-F0 was frozen against."""
    out = {}
    for k in ("p2d0", "p2x_v1", "p2x_v2"):
        d = proto["dependencies"][k]
        got = sha256_file(os.path.join(repo, d["sums_file"]))
        if got != d["sha256"]:
            raise ContractError(f"dependency {k} changed: {got} != {d['sha256']}")
        out[k] = got
    D0.verify_frozen()
    return out


class ContractSetF0:
    def __init__(self, directory: str = CONTRACT_DIR, verify_hashes: bool = True):
        self.directory = directory
        self.sha256 = verify(directory) if verify_hashes else None
        self.protocol = load("f0_protocol_v1.json", directory)
        self.schema = load("f0_evidence_schema_v1.json", directory)
        self.forward = load("f0_forward_v1.json", directory)
        self.calibration = load("f0_calibration_plan_v1.json", directory)
        self.dependencies = verify_dependencies(self.protocol) if verify_hashes else {}
        self.plan = D0.load("planned_trials_v1.json")

    def battery(self, reps_profile: dict | None = None):
        from .battery import Battery
        if self.sha256 is None:
            raise ContractError("an unverified contract set cannot evaluate")
        return Battery(self.protocol, self.sha256, self.plan, reps_profile=reps_profile)


def default() -> ContractSetF0:
    return ContractSetF0()


# ---------------------------------------------------------------- registration
def registration(cs: ContractSetF0, *, trial_id: str, plan_id: str, considered_trials: list, code_commit: str,
                 ledger_anchor: dict, selection_rule: str, now: str | None = None,
                 forward_registration: dict | None = None) -> dict:
    """Bind a candidate to this frozen F version, the frozen P2-D0 plan entry, the P2-X v2 contracts and a ledger
    anchor. ``considered_trials`` must list EVERY trial of the round (the candidate was selected from them), so
    the selection is countable. Pure: writes nothing."""
    pe = next((t for t in cs.plan["trials"] if t["plan_id"] == plan_id), None)
    if pe is None:
        raise ContractError(f"plan_id {plan_id} not in the frozen P2-D0 plan")
    if trial_id not in considered_trials:
        raise ContractError("the candidate must be one of the considered trials")
    if not isinstance(ledger_anchor, dict) or {"seq", "event_hash"} - set(ledger_anchor):
        raise ContractError("ledger_anchor {seq, event_hash} required")
    if not selection_rule or not isinstance(selection_rule, str):
        raise ContractError("a predeclared selection rule (text) is required")
    rec = {"record": REG_RECORD, "record_version": 1, "trial_id": trial_id, "plan_id": plan_id,
           "plan_entry_sha256": pe["plan_entry_sha256"], "hypothesis": pe["hypothesis"],
           "f0_contract_set_sha256": cs.sha256, "p2d0_sums_sha256": cs.protocol["dependencies"]["p2d0"]["sha256"],
           "p2x_v2_sums_sha256": cs.protocol["dependencies"]["p2x_v2"]["sha256"], "code_commit": code_commit,
           "considered_trials": sorted(considered_trials), "selection_rule": selection_rule,
           "ledger_anchor": {"seq": ledger_anchor["seq"], "event_hash": ledger_anchor["event_hash"]},
           "forward_registration": forward_registration,
           "registered_at": now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    rec["registration_sha256"] = hashlib.sha256(LG.canon(rec).encode()).hexdigest()
    return rec


def check_registration_against_ledger(reg: dict, ledger_dir: str) -> dict:
    """Read-only: the ledger verifies against the registration anchor, every considered trial exists, and every
    trial of the candidate's hypothesis in the ledger is among the considered ones (no hidden siblings)."""
    L = LG.Ledger(ledger_dir)
    rep = L.verify({"seq": reg["ledger_anchor"]["seq"], "event_hash": reg["ledger_anchor"]["event_hash"]}) \
        if reg["ledger_anchor"]["seq"] >= 0 else L.verify()
    errs = list(rep["errors"])
    trials = L.trials()
    for t in reg["considered_trials"]:
        if t not in trials:
            errs.append(f"considered trial {t} not in ledger")
    hyp_ids = {tid for tid, t in trials.items() if t["spec"]["parameter_spec"].get("plan_id", "").startswith(
        f"P2D-R1-{reg['hypothesis']}-")}
    hidden = sorted(hyp_ids - set(reg["considered_trials"]))
    if hidden:
        errs.append(f"trials of {reg['hypothesis']} missing from considered_trials: {hidden}")
    counts = L.trial_counts()
    total = sum(v["trials"] for k, v in counts.items() if k != "H-P2D-BENCH-v1")
    return {"ok": not errs, "errors": errs, "total_trials_excluding_benchmarks": total, "counts": counts}


def first_result_seq(ledger_dir: str, trial_ids) -> int | None:
    ids = set(trial_ids)
    seqs = [e["seq"] for e in LG.Ledger(ledger_dir).events() if e["event"] == "trial_result" and e["trial_id"] in ids]
    return min(seqs) if seqs else None


def applicable_version(versions: list, first_result: int | None) -> dict:
    """``versions``: [{version, contract_set_sha256, frozen_at_ledger_seq}]. Return the latest version frozen
    strictly before the first trial_result of the round (any version if no result exists yet)."""
    ok = [v for v in versions if first_result is None or v["frozen_at_ledger_seq"] < first_result]
    if not ok:
        raise ContractError("no F version was frozen before the round's first result: the round cannot be judged "
                            "by P2-F (a rule written after seeing outcomes is never applied first)")
    return max(ok, key=lambda v: (v["frozen_at_ledger_seq"], v["version"]))


def governing_verdict(verdicts: list) -> str:
    """The more conservative of several in-sample verdicts (retroactive versions can only downgrade)."""
    if not verdicts or any(v not in IN_SAMPLE_ORDER for v in verdicts):
        raise ContractError("unknown verdict")
    return min(verdicts, key=IN_SAMPLE_ORDER.index)


def freeze(directory: str = CONTRACT_DIR) -> str:
    """One-time freeze: canonicalize the four files and write the sums. Refused when a sums file exists."""
    if os.path.exists(os.path.join(directory, SUMS)):
        raise ContractError("F0 contracts already frozen; a change needs a new version")
    for f in FILES:
        p = os.path.join(directory, f)
        obj = load(f, directory)
        with open(p, "w", encoding="ascii") as fh:
            fh.write(dump_frozen(obj))
    sums = {"record": "tsb.p2f.frozen_sha256", "record_version": 1,
            "files": {f: sha256_file(os.path.join(directory, f)) for f in FILES}}
    with open(os.path.join(directory, SUMS), "w", encoding="ascii") as fh:
        fh.write(dump_frozen(sums))
    return sha256_file(os.path.join(directory, SUMS))
