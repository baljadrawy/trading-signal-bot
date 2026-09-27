"""Content-addressed immutable research dataset snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Iterable


SCHEMA_VERSION = "1.0.0"
COMPLETENESS = {"FULL_POINT_IN_TIME", "PARTIAL_POINT_IN_TIME", "CURRENT_SURVIVORS_ONLY"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


@dataclass(frozen=True)
class DatasetSnapshot:
    root: Path
    manifest: dict[str, Any]

    @property
    def dataset_id(self) -> str:
        return str(self.manifest["dataset_id"])


def create_snapshot(*, sources: Iterable[Path], destination: Path, source_name: str,
                    start_time: str, end_time: str, symbols: list[str],
                    timeframes: list[str], row_counts: dict[str, int], git_sha: str,
                    universe: list[dict[str, Any]], universe_completeness: str,
                    source_metadata: dict[str, Any] | None = None,
                    created_at: str | None = None) -> DatasetSnapshot:
    if universe_completeness not in COMPLETENESS:
        raise ValueError("invalid universe_completeness")
    files = [Path(p).resolve() for p in sources]
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    if len({p.name for p in files}) != len(files):
        raise ValueError("dataset source basenames must be unique")
    descriptors = [{"name": p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size}
                   for p in sorted(files)]
    identity = {"schema_version": SCHEMA_VERSION, "source": source_name,
                "start_time": start_time, "end_time": end_time,
                "symbols": sorted(symbols), "timeframes": sorted(timeframes),
                "row_counts": row_counts, "files": descriptors,
                "universe": universe, "universe_completeness": universe_completeness,
                "source_metadata": source_metadata or {}, "git_sha": git_sha}
    dataset_id = "ds-" + hashlib.sha256(_json(identity)).hexdigest()[:20]
    root = destination.resolve() / dataset_id
    if root.exists():
        existing = load_snapshot(root)
        verify_snapshot(existing)
        if existing.manifest["identity"] != identity:
            raise FileExistsError(f"immutable dataset collision: {root}")
        return existing
    root.mkdir(parents=True, exist_ok=False)
    data_dir = root / "files"
    data_dir.mkdir()
    for path in files:
        shutil.copyfile(path, data_dir / path.name)
    manifest = {"dataset_id": dataset_id,
                "created_at": created_at or datetime.now(timezone.utc).isoformat(),
                "git_sha": git_sha, "identity": identity}
    (root / "manifest.json").write_bytes(_json(manifest) + b"\n")
    for path in [root, data_dir]:
        path.chmod(0o555)
    for path in data_dir.iterdir():
        path.chmod(0o444)
    (root / "manifest.json").chmod(0o444)
    return DatasetSnapshot(root, manifest)


def load_snapshot(root: Path) -> DatasetSnapshot:
    root = Path(root).resolve()
    return DatasetSnapshot(root, json.loads((root / "manifest.json").read_text()))


def verify_snapshot(snapshot: DatasetSnapshot) -> dict[str, Any]:
    errors = []
    identity = snapshot.manifest.get("identity", {})
    expected_id = "ds-" + hashlib.sha256(_json(identity)).hexdigest()[:20]
    if snapshot.dataset_id != expected_id:
        errors.append("dataset_id_mismatch")
    for item in identity.get("files", []):
        path = snapshot.root / "files" / item["name"]
        if not path.is_file():
            errors.append(f"missing:{item['name']}")
        elif sha256_file(path) != item["sha256"]:
            errors.append(f"checksum:{item['name']}")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}


def universe_at(universe: list[dict[str, Any]], timestamp: str) -> list[str]:
    t = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    result = []
    for row in universe:
        start = datetime.fromisoformat(row["eligible_from"].replace("Z", "+00:00"))
        end_raw = row.get("eligible_until")
        end = datetime.fromisoformat(end_raw.replace("Z", "+00:00")) if end_raw else None
        if start <= t and (end is None or t < end) and row.get("status", "TRADING") == "TRADING":
            result.append(row["symbol"])
    return sorted(result)
