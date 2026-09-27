"""Immutable experiment manifests and deterministic artifact writer."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

from .contract import canonical_json, contract_hash
from .dataset import DatasetSnapshot, verify_snapshot


def _json_default(value: Any):
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def git_state(repo: Path) -> tuple[str, bool, str]:
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True)
    return sha, bool(status), status


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(config).encode()).hexdigest()


def experiment_id(dataset_id: str, config: dict[str, Any], sha: str, seed: int) -> str:
    identity = {"dataset_id": dataset_id, "config_hash": config_hash(config),
                "git_sha": sha, "random_seed": seed}
    return "exp-" + hashlib.sha256(canonical_json(identity).encode()).hexdigest()[:20]


class ExperimentWriter:
    def __init__(self, *, runs_root: Path, dataset: DatasetSnapshot, config: dict[str, Any],
                 contract: dict[str, Any], repo: Path, seed: int = 0,
                 research_mode: str = "OFFLINE_REPLAY", created_at: str | None = None,
                 git_sha_override: str | None = None,
                 git_dirty_override: bool | None = None,
                 git_status_override: str = ""):
        quality = verify_snapshot(dataset)
        if quality["status"] != "PASS": raise ValueError(f"dataset verification failed: {quality}")
        if git_sha_override is None:
            sha, dirty, status = git_state(repo)
        else:
            sha = git_sha_override
            dirty = bool(git_dirty_override)
            status = git_status_override
        eid = experiment_id(dataset.dataset_id, config, sha, seed)
        self.root = Path(runs_root).resolve() / eid
        self.root.mkdir(parents=True, exist_ok=False)
        self.dataset = dataset; self.config = config; self.contract = contract
        self.manifest = {"experiment_id": eid,
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
            "git_sha": sha, "git_dirty": dirty,
            "git_status_snapshot": status.splitlines(), "dataset_id": dataset.dataset_id,
            "strategy_contract_version": contract["schema_version"],
            "strategy_contract_hash": contract_hash(contract), "config_hash": config_hash(config),
            "random_seed": seed, "research_mode": research_mode,
            "reproducible": not dirty, "status": "RUNNING",
            "execution_assumptions": config.get("execution_assumptions", {}),
            "warnings": (["dirty_worktree_result_not_reproducible"] if dirty else [])}
        self.manifest["reproducibility_eligible"] = not dirty
        self.manifest["reproducible"] = False
        self.write_json("manifest.json", self.manifest)
        self.write_json("config.json", config)
        self.write_json("dataset_manifest.json", dataset.manifest)
        self.write_json("strategy_contract.json", contract)

    def write_json(self, name: str, value: Any) -> None:
        path = self.root / name
        if path.exists(): raise FileExistsError(f"immutable artifact exists: {path}")
        path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                                   allow_nan=False, default=_json_default) + "\n")

    def write_jsonl(self, name: str, rows: Iterable[dict[str, Any]]) -> int:
        path = self.root / name
        if path.exists(): raise FileExistsError(f"immutable artifact exists: {path}")
        count = 0
        with path.open("x") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False, allow_nan=False,
                                        default=_json_default) + "\n")
                count += 1
        return count

    def finish(self, *, counts: dict[str, int], warnings: list[str], parity: dict,
               quality: dict, metrics: dict) -> None:
        self.write_json("metrics.json", metrics)
        self.write_json("quality_report.json", quality)
        self.write_json("parity_report.json", parity)
        manifest_path = self.root / "manifest.json"
        self.manifest.update({"status": "COMPLETE", "finished_at": datetime.now(timezone.utc).isoformat(),
                              "row_counts": counts,
                              "warnings": self.manifest["warnings"] + warnings,
                              "parity_failures": parity.get("failure", 0),
                              "data_quality_failures": quality.get("failure", 0)})
        manifest_path.write_text(json.dumps(self.manifest, sort_keys=True, indent=2,
                                            ensure_ascii=False) + "\n")
        for path in self.root.iterdir(): path.chmod(0o444)
        self.root.chmod(0o555)


def verify_reproducible_outputs(first: Path, second: Path,
                                names=("opportunities.jsonl", "trades.jsonl",
                                       "trade_events.jsonl", "metrics.json")) -> dict:
    differences = []
    for name in names:
        a, b = first / name, second / name
        if not a.exists() or not b.exists() or a.read_bytes() != b.read_bytes():
            differences.append(name)
    return {"deterministic": not differences, "differences": differences}
