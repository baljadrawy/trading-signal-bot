"""Explicit governance commands. None contact live services."""
from __future__ import annotations

import argparse
from pathlib import Path

from .governance import HoldoutLedger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    unlock = sub.add_parser("unlock-holdout")
    unlock.add_argument("--ledger", type=Path, default=Path("research/governance/holdout_status.json"))
    unlock.add_argument("--opened-by", required=True)
    unlock.add_argument("--reason", required=True)
    unlock.add_argument("--hypothesis-id", action="append", required=True)
    unlock.add_argument("--experiment-id", action="append", required=True)
    unlock.add_argument("--git-sha", required=True)
    args = parser.parse_args(argv)
    HoldoutLedger(args.ledger).unlock(opened_by=args.opened_by, reason=args.reason,
        hypothesis_ids=args.hypothesis_id, git_sha=args.git_sha, experiment_ids=args.experiment_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
