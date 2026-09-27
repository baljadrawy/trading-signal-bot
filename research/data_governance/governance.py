"""Append-only ledgers for validation and a one-way forward-holdout door."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LEVELS = {"KNOWN_RESEARCHED", "LIKELY_RESEARCHED", "UNKNOWN", "CLEAN_FORWARD_ONLY"}


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


@dataclass
class HoldoutLedger:
    path: Path

    def read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text())

    def initialize(self, *, freeze_timestamp: str) -> dict[str, Any]:
        if self.path.exists():
            return self.read()
        state = {"status": "SEALED", "freeze_timestamp": freeze_timestamp,
                 "opened_at": None, "opened_by": None, "reason": None,
                 "hypothesis_ids": [], "git_sha": None, "experiment_ids": [],
                 "holdout_look_count": 0}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        return state

    def assert_hidden(self) -> None:
        if self.read()["status"] != "OPENED":
            raise PermissionError("FORWARD_HOLDOUT_SEALED")

    def unlock(self, *, opened_by: str, reason: str, hypothesis_ids: list[str],
               git_sha: str, experiment_ids: list[str], opened_at: str | None = None) -> dict[str, Any]:
        state = self.read()
        if state["status"] == "OPENED":
            raise RuntimeError("FORWARD_HOLDOUT_ALREADY_OPENED_ONE_WAY_DOOR")
        if not reason.strip() or not hypothesis_ids or not experiment_ids:
            raise ValueError("reason, hypothesis_ids and experiment_ids are required")
        state.update(status="OPENED", opened_at=opened_at or datetime.now(timezone.utc).isoformat(),
                     opened_by=opened_by, reason=reason, hypothesis_ids=hypothesis_ids,
                     git_sha=git_sha, experiment_ids=experiment_ids,
                     holdout_look_count=state["holdout_look_count"] + 1)
        self.path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        return state


class TemporalGovernance:
    def __init__(self, root: Path):
        self.root = Path(root)

    def register_contamination(self, record: dict[str, Any]) -> None:
        if record.get("contamination_level") not in LEVELS:
            raise ValueError("invalid contamination level")
        append_jsonl(self.root / "contamination_registry.jsonl", record)

    def log_validation_use(self, *, hypothesis_id: str, experiment_id: str,
                           metrics_requested: list[str], result_artifact: str,
                           timestamp: str | None = None) -> None:
        append_jsonl(self.root / "validation_usage.jsonl", {
            "hypothesis_id": hypothesis_id, "experiment_id": experiment_id,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "metrics_requested": metrics_requested, "result_artifact": result_artifact,
        })

    def validation_look_count(self) -> int:
        path = self.root / "validation_usage.jsonl"
        return 0 if not path.exists() else sum(1 for line in path.read_text().splitlines() if line.strip())


def partition_for(timestamp: datetime, *, freeze: datetime,
                  discovery_end: datetime | None = None) -> str:
    if timestamp > freeze:
        return "FORWARD_HOLDOUT"
    if discovery_end is None or timestamp <= discovery_end:
        return "DISCOVERY"
    return "VALIDATION"
