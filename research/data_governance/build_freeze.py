"""Build a content-addressed audit index over immutable external raw market data.

This command never contacts an API and never writes to production state. It treats
the supplied raw tree as input and emits manifests/certificates to an output root.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import zipfile

from research.data_governance.governance import canonical_hash
from research.foundation.contract import contract_hash, current_contract
from research.foundation.dataset import sha256_file


NAME = re.compile(r"^(?P<symbol>[A-Z0-9]+)-(?P<tf>15m|1h|4h|1d)-(?P<month>\d{4}-\d{2})\.zip$")


def _write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"immutable artifact exists: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def inventory(raw_root: Path) -> tuple[list[dict], list[dict]]:
    files, exclusions = [], []
    for path in sorted(raw_root.rglob("*.zip")):
        match = NAME.match(path.name)
        if not match:
            exclusions.append({"symbol": None, "period": None, "reason_code": "EXCLUDE_BAD_TIMESTAMPS",
                               "details": f"unrecognized archive name: {path.relative_to(raw_root)}"})
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                info = [x for x in archive.infolist() if x.filename.endswith(".csv")]
                if len(info) != 1 or archive.testzip() is not None:
                    raise ValueError("invalid ZIP member layout or CRC")
                rows = max(0, info[0].file_size // 40)  # estimate only; never reported as exact rows
        except Exception as exc:
            exclusions.append({"symbol": match["symbol"], "period": match["month"],
                               "reason_code": "EXCLUDE_CORRUPT_DATA", "details": str(exc)})
            continue
        files.append({"relative_path": str(path.relative_to(raw_root)), "symbol": match["symbol"],
                      "timeframe": match["tf"], "month": match["month"], "bytes": path.stat().st_size,
                      "sha256": sha256_file(path), "upstream_checksum_verified": False,
                      "estimated_rows_not_canonical": rows})
    return files, exclusions


def build(*, raw_root: Path, output_root: Path, freeze_timestamp: str,
          git_sha: str, git_dirty: bool) -> dict:
    files, exclusions = inventory(raw_root)
    contract = current_contract()
    config = {
        "raw_root": str(raw_root.resolve()), "source": "Binance Public Data monthly spot klines",
        "source_url": "https://data.binance.vision/data/spot/monthly/klines",
        "requested_timeframes": ["15m", "4h", "1d"], "warmup_candles": 100,
        "spread_mode": "SPREAD_UNAVAILABLE", "macro_mode": "MACRO_DATA_UNAVAILABLE",
        "partition_policy_version": "1.0.0", "holdout_policy_version": "1.0.0",
    }
    symbols = sorted({f["symbol"] for f in files})
    tfs = sorted({f["timeframe"] for f in files})
    months = sorted({f["month"] for f in files})
    counts = Counter(f["timeframe"] for f in files)
    file_index_hash = canonical_hash(files)
    identity = {
        "schema_version": "1.5.0", "source": config["source"], "start": months[0] if months else None,
        "end": months[-1] if months else None, "symbols": symbols, "timeframes": tfs,
        "archive_counts": dict(counts), "raw_file_index_sha256": file_index_hash,
        "transform_versions": {"ohlcv_normalizer": "1.0.0", "universe_builder": "1.0.0",
            "macro_builder": "1.0.0", "spread_adapter": "1.0.0", "liquidity_builder": "1.0.0"},
        "universe_completeness": "PARTIAL_POINT_IN_TIME",
        "delisted_assets_included": "SOME_OBSERVED_ARCHIVES_PRESENT_NOT_AUTHORITATIVELY_ENUMERATED",
        "listing_history_coverage": "UNVERIFIED_FIRST_LAST_CANDLE_ONLY",
        "execution_fidelity": "TIER_4_NO_SPREAD", "macro_status": "MACRO_DATA_UNAVAILABLE",
    }
    dataset_id = "ds-" + canonical_hash(identity)[:20]
    run = output_root / dataset_id
    manifest = {"dataset_id": dataset_id, "created_at": freeze_timestamp, "git_sha": git_sha,
                "git_dirty": git_dirty, "identity": identity, "config_hash": canonical_hash(config),
                "strategy_contract_hash": contract_hash(contract), "raw_storage": str(raw_root.resolve()),
                "raw_storage_mode": "EXTERNAL_CONTENT_ADDRESSED_INDEX", "files_index": "raw_files.json"}
    _write_new(run / "raw_files.json", files)
    _write_new(run / "dataset_exclusions.json", exclusions)
    _write_new(run / "manifest.json", manifest)
    required_tfs = {"15m", "4h", "1d"}
    critical = []
    if not required_tfs.issubset(tfs): critical.append("MISSING_REQUIRED_TIMEFRAME_15M")
    if "BTCUSDT" not in symbols: critical.append("BTC_REFERENCE_MISSING")
    critical += ["AUTHORITATIVE_POINT_IN_TIME_UNIVERSE_MISSING", "HISTORICAL_USDT_DOMINANCE_MISSING"]
    warnings = ["UPSTREAM_CHECKSUMS_NOT_RETAINED", "HISTORICAL_SPREAD_UNAVAILABLE",
                "RAW_SYMBOL_LIST_PROVENANCE_UNKNOWN", "NORMALIZED_RESEARCH_LAYER_NOT_BUILT"]
    certificate = {
        "dataset_id": dataset_id, "status": "FAIL" if critical else "WARN",
        "critical_failures": critical, "warnings": warnings,
        "coverage": {"symbols": len(symbols), "archive_counts": dict(counts),
                     "first_month": months[0] if months else None, "last_month": months[-1] if months else None},
        "survivorship_status": "NOT_SURVIVORSHIP_SAFE", "execution_fidelity": "TIER_4_NO_SPREAD",
        "macro_status": "MACRO_DATA_UNAVAILABLE", "determinism_status": "CONTENT_INDEX_DETERMINISTIC",
        "partition_status": "FROZEN_GOVERNANCE_ONLY", "eligible_for_phase2": False,
    }
    _write_new(run / "data_quality_certificate.json", certificate)
    _write_new(run / "quality_report.json", {"status": certificate["status"],
        "archive_crc_failures": sum(e["reason_code"] == "EXCLUDE_CORRUPT_DATA" for e in exclusions),
        "note": "Row-level normalized candle quality is not certified because the required 15m layer is absent."})
    return {"manifest": manifest, "certificate": certificate, "run": str(run), "config": config}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--raw-root", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--freeze-timestamp", required=True)
    p.add_argument("--git-sha", required=True)
    p.add_argument("--git-dirty", action="store_true")
    a = p.parse_args(argv)
    print(json.dumps(build(raw_root=a.raw_root, output_root=a.output_root,
                           freeze_timestamp=a.freeze_timestamp, git_sha=a.git_sha,
                           git_dirty=a.git_dirty), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
