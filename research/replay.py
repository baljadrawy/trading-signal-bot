"""CLI for immutable offline datasets and exact-contract research replay."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from research.foundation.contract import current_contract, contract_hash
from research.foundation.dataset import create_snapshot, load_snapshot, verify_snapshot
from research.foundation.experiment import ExperimentWriter
from research.foundation.runner import run_experiment
from shared.config import config as live_config


REPO = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline-only research replay")
    sub = parser.add_subparsers(dest="command", required=True)
    contract = sub.add_parser("contract")
    create = sub.add_parser("create-dataset")
    create.add_argument("--spec", required=True); create.add_argument("--destination", default="research/datasets")
    verify = sub.add_parser("verify-dataset"); verify.add_argument("--dataset", required=True)
    replay = sub.add_parser("run"); replay.add_argument("--dataset", required=True)
    replay.add_argument("--config", required=True); replay.add_argument("--output", default="research/runs")
    args = parser.parse_args(argv)
    if args.command == "contract":
        value = current_contract(live_config)
        print(json.dumps({"hash": contract_hash(value), "contract": value}, indent=2)); return
    if args.command == "create-dataset":
        spec = json.loads(Path(args.spec).read_text())
        snap = create_snapshot(sources=[Path(x) for x in spec.pop("sources")],
                               destination=Path(args.destination), **spec)
        print(snap.dataset_id); return
    snap = load_snapshot(Path(args.dataset))
    if args.command == "verify-dataset": print(json.dumps(verify_snapshot(snap), indent=2)); return
    cfg = json.loads(Path(args.config).read_text())
    params = cfg["indicator_params"]
    live_contract = current_contract(live_config)
    writer = ExperimentWriter(runs_root=Path(args.output), dataset=snap, config=cfg,
                              contract=live_contract, repo=REPO,
                              seed=int(cfg.get("random_seed", 0)))
    print(json.dumps(run_experiment(dataset=snap, writer=writer,
                                    indicator_params=params, config=cfg), indent=2))


if __name__ == "__main__": main()
