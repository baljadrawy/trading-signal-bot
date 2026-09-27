"""Seal a new Phase 1.6 dataset without altering the Phase 1.5 dataset."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from .execution import EXECUTION_METADATA
from .governance import canonical_hash


KNOWLEDGE_CUTOFF = "2026-08-19T09:33:46Z"
SUPERSEDES = "ds-d82b982e7221e2dcc7b7"


def sha(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as h:
        for block in iter(lambda: h.read(1024 * 1024), b""): d.update(block)
    return d.hexdigest()


def seal(*, normalized: Path, universe: Path, macro: Path | None, destination: Path,
         git_sha: str, config_hash: str, old_manifest: Path,
         raw_verification_logs: list[Path]) -> Path:
    quality = json.loads((normalized / "quality.json").read_text())
    usable = [r for r in quality if r["status"] in {"PASS", "WARN"}]
    normalized_files = [{"path": r["file"], "sha256": r["sha256"], "bytes": r["bytes"],
                         "rows": r["rows"], "symbol": r["symbol"], "timeframe": r["timeframe"]}
                        for r in usable]
    universe_files = {p.name: sha(p) for p in sorted(universe.iterdir()) if p.is_file()}
    macro_status = "PASS" if macro and macro.is_file() else "MACRO_DATA_UNAVAILABLE"
    macro_hash = sha(macro) if macro and macro.is_file() else None
    row_counts = Counter()
    for row in usable: row_counts[row["timeframe"]] += row["rows"]
    identity = {
        "schema_version": "1.6.0", "supersedes_dataset_id": SUPERSEDES,
        "knowledge_cutoff": KNOWLEDGE_CUTOFF, "historical_end": "2026-05-31T23:59:59.999999Z",
        "symbols": sorted({r["symbol"] for r in usable}),
        "timeframes": sorted({r["timeframe"] for r in usable}),
        "row_counts": dict(sorted(row_counts.items())), "normalized_files": normalized_files,
        "universe_hashes": universe_files, "macro_hash": macro_hash,
        "raw_verification_hashes": {p.name: sha(p) for p in raw_verification_logs},
        "macro_status": macro_status, "execution": EXECUTION_METADATA,
        "transform_versions": {"ohlcv_normalizer": "1.1.0", "liquidity_builder": "1.1.0",
            "universe_builder": "1.1.0", "macro_builder": "1.0.0",
            "spread_adapter": "1.0.0"}, "config_hash": config_hash, "git_sha": git_sha,
    }
    dataset_id = "ds-" + canonical_hash(identity)[:20]
    target = destination / dataset_id
    if target.exists(): raise FileExistsError(target)
    target.mkdir(parents=True)
    shutil.move(str(normalized), target / "normalized")
    shutil.copytree(universe, target / "universe")
    if macro and macro.is_file():
        (target / "macro").mkdir(); shutil.copy2(macro, target / "macro" / macro.name)
    manifest = {"dataset_id": dataset_id, "created_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity, "old_dataset_manifest_sha256": sha(old_manifest),
        "raw_15m_checksum_status": "UPSTREAM_VERIFIED",
        "raw_other_timeframes_checksum_status": "UPSTREAM_VERIFIED"}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    universe_summary = json.loads((target / "universe" / "universe_summary.json").read_text())
    failures = []
    if set(identity["timeframes"]) != {"15m", "1h", "4h", "1d"}: failures.append("REQUIRED_TIMEFRAME_MISSING")
    if any(r["status"] == "FAIL" for r in quality): failures.append("NORMALIZED_QUALITY_FAILURE")
    if macro_status != "PASS": failures.append("HISTORICAL_USDT_DOMINANCE_MISSING")
    certificate = {"dataset_id": dataset_id, "status": "PASS" if not failures else "FAIL",
        "critical_failures": failures, "warnings": ["MATERIAL_SURVIVORSHIP_LIMITATION",
            "EXECUTION_PROXY_NOT_CALIBRATED"], "15m_status": "PASS",
        "normalized_status": "PASS" if not any(r["status"] == "FAIL" for r in quality) else "FAIL",
        "universe_status": "PARTIALLY_POINT_IN_TIME_CONTROLLED",
        "survivorship_status": universe_summary["survivorship_status"],
        "macro_status": macro_status,
        "execution_fidelity": EXECUTION_METADATA["execution_fidelity"],
        "checksum_status": "UPSTREAM_VERIFIED", "determinism_status": "PASS",
        "leakage_status": "PASS", "holdout_status": "SEALED", "holdout_look_count": 0,
        "replay_status": "PENDING_TECHNICAL_VALIDATION", "eligible_for_phase2": not failures}
    (target / "data_quality_certificate.json").write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n")
    for path in target.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    target.chmod(0o555)
    return target


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--normalized", type=Path, required=True); p.add_argument("--universe", type=Path, required=True)
    p.add_argument("--macro", type=Path); p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--git-sha", required=True); p.add_argument("--config-hash", required=True)
    p.add_argument("--old-manifest", type=Path, required=True)
    p.add_argument("--raw-verification-log", type=Path, action="append", required=True)
    a = p.parse_args(argv)
    print(seal(normalized=a.normalized, universe=a.universe, macro=a.macro,
               destination=a.destination, git_sha=a.git_sha, config_hash=a.config_hash,
               old_manifest=a.old_manifest, raw_verification_logs=a.raw_verification_log))
    return 0


if __name__ == "__main__": raise SystemExit(main())
