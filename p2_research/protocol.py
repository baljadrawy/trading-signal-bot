"""P2-D0 alpha research protocol: frozen hypothesis / benchmark / protocol registries and the PLANNED-trial generator.

Spec: docs/p2/P2D_ALPHA_RESEARCH_PROTOCOL.md. Registries (frozen, content-hashed): ``p2_research/research/``.

This module is bookkeeping only. It
  * loads the frozen registries and verifies their SHA-256 against ``FROZEN_SHA256SUMS.json``;
  * expands each hypothesis' predeclared grid into deterministic PLANNED trial entries (no data, no outcome);
  * turns a planned entry into a Trial Ledger spec (validated by ``ledger.validate_spec``: W3 refused, crypto only)
    once P2-D1 supplies the code commit, dataset hash and periods.
It never reads market data or labels, never computes a metric, never ranks anything and never writes the ledger
(registration is ``ledger.create_trial`` at P2-D1 start, see the protocol document section 14).
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os

from . import instrument as IN
from . import ledger as LG
from . import registry as RG

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH_DIR = os.path.join(HERE, "research")
FROZEN_FILES = ("hypotheses_v1.json", "benchmarks_v1.json", "protocol_v1.json", "planned_trials_v1.json")
FROZEN_SUMS = "FROZEN_SHA256SUMS.json"
PLAN_RECORD = "tsb.p2d.planned_trials"


class ProtocolError(Exception):
    pass


def canon(o) -> str:
    return LG.canon(o)


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def dump_frozen(obj) -> str:
    """The one serialization used for every frozen registry file (sorted keys, indent 1, ASCII, trailing newline)."""
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=True) + "\n"


def load(name: str, research_dir: str = RESEARCH_DIR) -> dict:
    with open(os.path.join(research_dir, name), encoding="utf-8") as fh:
        return json.load(fh)


def verify_frozen(research_dir: str = RESEARCH_DIR) -> dict:
    """Recompute the SHA-256 of every frozen file and compare with FROZEN_SHA256SUMS.json; raise on any mismatch."""
    sums = load(FROZEN_SUMS, research_dir)["files"]
    if set(sums) != set(FROZEN_FILES):
        raise ProtocolError(f"frozen file set mismatch: {sorted(sums)}")
    got = {f: sha256_file(os.path.join(research_dir, f)) for f in FROZEN_FILES}
    bad = sorted(f for f in FROZEN_FILES if got[f] != sums[f])
    if bad:
        raise ProtocolError(f"frozen registry altered (hash mismatch): {bad}")
    return got


def feature_ids() -> set:
    return {f["id"] for f in RG.FEATURES}


def _entry_sha(e: dict) -> str:
    return hashlib.sha256(canon({k: v for k, v in e.items() if k != "plan_entry_sha256"}).encode()).hexdigest()


def planned_trials(hyp_registry: dict, round_no: int = 1) -> list:
    """Deterministic expansion of every hypothesis grid (cartesian product in ``grid_order``, values in declared order)
    into PLANNED trial entries. Pure function of the hypothesis registry: no data, no outcome, no ranking."""
    out = []
    for h in hyp_registry["hypotheses"]:
        order = h["grid_order"]
        if sorted(order) != sorted(h["grid"]):
            raise ProtocolError(f"{h['id']}: grid_order does not match grid keys")
        values = [h["grid"][k]["values"] for k in order]
        cells = list(itertools.product(*values))
        if len(cells) != h["trials"]:
            raise ProtocolError(f"{h['id']}: grid has {len(cells)} cells, declared trials = {h['trials']}")
        for i, cell in enumerate(cells, 1):
            e = {"record": PLAN_RECORD, "round": round_no, "plan_id": f"P2D-R{round_no}-{h['id']}-{i:03d}",
                 "hypothesis": h["id"], "ledger_hypothesis_id": h["ledger_hypothesis_id"],
                 "strategy_family": h["strategy_family"], "trial_kind": h["trial_kind"],
                 "params": dict(zip(order, cell)), "fixed_parameters": h["fixed_parameters"],
                 "features": h["features"], "labels": h["labels_used"], "control": h["comparison_control"],
                 "status": "PLANNED"}
            e["plan_entry_sha256"] = _entry_sha(e)
            out.append(e)
    return out


def plan_document(hyp_registry: dict, hyp_sha: str, round_no: int = 1) -> dict:
    trials = planned_trials(hyp_registry, round_no)
    per = {}
    for t in trials:
        per[t["hypothesis"]] = per.get(t["hypothesis"], 0) + 1
    return {"record": PLAN_RECORD, "record_version": 1, "round": round_no, "hypotheses_sha256": hyp_sha,
            "registered_in_ledger": False,
            "registration_rule": "registered with ledger.create_trial at P2-D1 start, before any outcome is computed",
            "trials_total": len(trials), "trials_per_hypothesis": dict(sorted(per.items())), "trials": trials}


def ledger_spec(entry: dict, protocol: dict, frozen: dict, *, code_commit: str, dataset: dict,
                train_period: dict, validation_period: dict, forward_untouched: dict | None = None) -> dict:
    """Trial Ledger spec for one PLANNED entry (validated, not written). The frozen plan entry hash and the registry
    hashes are bound into ``parameter_spec`` so a ledger trial can be traced to the immutable plan."""
    if entry.get("status") != "PLANNED" or entry.get("plan_entry_sha256") != _entry_sha(entry):
        raise ProtocolError("not an unaltered PLANNED entry")
    cost = protocol["gross_vs_executable"]["ledger_cost_assumptions"]
    spec = {
        "hypothesis_id": entry["ledger_hypothesis_id"], "code_commit": code_commit, "dataset": dataset,
        "feature_set_version": protocol["feature_set"]["version"], "label_set_version": protocol["label_set"]["version"],
        "universe_policy": protocol["universe_policy"]["id"], "market": dict(protocol["market"]),
        "strategy_family": entry["strategy_family"],
        "parameter_spec": {"plan_id": entry["plan_id"], "plan_entry_sha256": entry["plan_entry_sha256"],
                           "params": entry["params"], "fixed_parameters": entry["fixed_parameters"],
                           "hypotheses_sha256": frozen["hypotheses_v1.json"],
                           "protocol_sha256": frozen["protocol_v1.json"],
                           "benchmarks_sha256": frozen["benchmarks_v1.json"]},
        "transaction_cost_assumptions": cost,
        "execution_assumptions": protocol["execution_model"],
        "train_period": train_period, "validation_period": validation_period,
        "holdout": {"w3": LG.HOLDOUT_W3, "forward_untouched": forward_untouched},
        "metrics_requested": protocol["metrics_contract"]["ledger_metrics_requested"], "parent_trial": None,
    }
    IN.require_supported_market(spec["market"])
    return LG.validate_spec(spec)


def summary(research_dir: str = RESEARCH_DIR) -> dict:
    frozen = verify_frozen(research_dir)
    hyp, bench, plan = load("hypotheses_v1.json", research_dir), load("benchmarks_v1.json", research_dir), \
        load("planned_trials_v1.json", research_dir)
    return {"hypotheses": len(hyp["hypotheses"]), "planned_trials_total": plan["trials_total"],
            "planned_trials_per_hypothesis": plan["trials_per_hypothesis"],
            "benchmarks": [b["id"] for b in bench["benchmarks"]], "frozen_sha256": frozen}


def _write_plan_and_sums(research_dir: str = RESEARCH_DIR) -> None:
    """Freeze step (run once at P2-D0): write planned_trials_v1.json from the hypothesis registry and the hash file."""
    if os.path.exists(os.path.join(research_dir, FROZEN_SUMS)):
        raise ProtocolError("registries already frozen; a change needs a new version (v2) and a new research round")
    hyp_path = os.path.join(research_dir, "hypotheses_v1.json")
    plan =plan_document(load("hypotheses_v1.json", research_dir), sha256_file(hyp_path))
    with open(os.path.join(research_dir, "planned_trials_v1.json"), "w", encoding="ascii") as fh:
        fh.write(dump_frozen(plan))
    sums = {"record": "tsb.p2d.frozen_sha256", "record_version": 1,
            "files": {f: sha256_file(os.path.join(research_dir, f)) for f in FROZEN_FILES}}
    with open(os.path.join(research_dir, FROZEN_SUMS), "w", encoding="ascii") as fh:
        fh.write(dump_frozen(sums))


def main(argv=None) -> int:
    """``python -m p2_research.protocol summary`` -> counts + verified hashes (read-only);
    ``python -m p2_research.protocol plan`` -> the planned trials regenerated from the frozen registry (stdout)."""
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="python -m p2_research.protocol")
    ap.add_argument("command", choices=("summary", "plan", "freeze"))
    a = ap.parse_args(argv)
    if a.command == "freeze":
        _write_plan_and_sums()
        a.command = "summary"
    if a.command == "summary":
        sys.stdout.write(json.dumps(summary(), sort_keys=True, indent=1) + "\n")
    else:
        verify_frozen()
        hp = os.path.join(RESEARCH_DIR, "hypotheses_v1.json")
        sys.stdout.write(dump_frozen(plan_document(load("hypotheses_v1.json"), sha256_file(hp))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
