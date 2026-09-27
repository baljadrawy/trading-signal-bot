"""Performance-suppressed technical validation of a sealed Phase 1.6 snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import pandas as pd

from research.data_governance.execution import conservative_spread_proxy
from research.foundation.contract import current_contract
from research.foundation.replay import ReplayContext, evaluate_opportunity


def sha(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as h:
        for block in iter(lambda: h.read(1024 * 1024), b""): d.update(block)
    return d.hexdigest()


def validate(snapshot: Path, *, holdout: Path, replay_config: Path) -> dict:
    manifest = json.loads((snapshot / "manifest.json").read_text())
    identity = manifest["identity"]
    failures, warnings = [], []
    checksum_failures = []
    for item in identity["normalized_files"]:
        path = snapshot / "normalized" / item["path"]
        if not path.is_file() or sha(path) != item["sha256"]:
            checksum_failures.append(item["path"])
    if checksum_failures: failures.append("NORMALIZED_CHECKSUM_FAILURE")
    if identity["knowledge_cutoff"] != "2026-08-19T09:33:46Z": failures.append("KNOWLEDGE_CUTOFF_DRIFT")
    if identity["historical_end"] > identity["knowledge_cutoff"]: failures.append("FORWARD_DATA_IN_SNAPSHOT")
    state = json.loads(holdout.read_text())
    if state["status"] != "SEALED" or state["holdout_look_count"] != 0:
        failures.append("HOLDOUT_GOVERNANCE_FAILURE")
    writable = [str(p.relative_to(snapshot)) for p in snapshot.rglob("*") if os.access(p, os.W_OK)]
    # os.access is root-sensitive; mode bits are the immutable contract.
    bad_modes = [str(p.relative_to(snapshot)) for p in snapshot.rglob("*") if p.stat().st_mode & 0o222]
    if bad_modes: failures.append("SNAPSHOT_MODE_WRITABLE")
    btc = pd.read_parquet(snapshot / "normalized" / "4h" / "BTCUSDT.parquet")
    liq = pd.read_parquet(snapshot / "normalized" / "15m" / "BTCUSDT.parquet",
                          columns=["close_time", "rolling_24h_quote_volume",
                                   "price_change_24h_pct", "rolling_24h_trade_count",
                                   "realized_volatility_pct"])
    decision = btc.iloc[-1].close_time
    available = liq[liq.close_time <= decision].dropna().iloc[-1]
    spread = conservative_spread_proxy(available.to_dict())
    history = btc.tail(250).rename(columns={"open_time": "timestamp"}).reset_index(drop=True)
    config = json.loads(replay_config.read_text())
    context = ReplayContext(identity["dataset_id"] if "dataset_id" in identity else manifest["dataset_id"],
        "TECHNICAL-CERTIFICATION", identity["git_sha"], "sb-2026.08", "DISCOVERY",
        current_contract(), config["indicator_params"])
    record, _ = evaluate_opportunity(raw_history=history, decision_time=pd.Timestamp(decision).isoformat(),
        symbol="BTCUSDT", timeframe="4h", market={"quote_volume": available.rolling_24h_quote_volume,
        "change_24h_pct": available.price_change_24h_pct, "spread": spread,
        "spread_data_mode": "HISTORICAL_SPREAD_PROXY", "macro_pass": None},
        context=context, universe_eligible=True)
    if not record.opportunity_id: failures.append("OPPORTUNITY_RECORD_NOT_GENERATED")
    macro_status = identity["macro_status"]
    replay_status = "BLOCKED_MACRO_DATA_UNAVAILABLE" if macro_status != "PASS" else "PASS"
    if replay_status != "PASS": warnings.append(replay_status)
    return {"dataset_id": manifest["dataset_id"], "status": "FAIL" if failures else "PASS",
        "failures": failures, "warnings": warnings, "normalized_files_verified": len(identity["normalized_files"]),
        "checksum_failures": checksum_failures, "snapshot_mode_status": "PASS" if not bad_modes else "FAIL",
        "holdout_status": state["status"], "holdout_look_count": state["holdout_look_count"],
        "knowledge_cutoff": identity["knowledge_cutoff"], "opportunity_record_generated": bool(record.opportunity_id),
        "opportunity_decision": record.rejection_code, "performance_metrics_suppressed": True,
        "live_dependencies_used": False, "replay_status": replay_status,
        "macro_status": macro_status, "root_os_access_writable_count_ignored": len(writable)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(); p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--holdout", type=Path, required=True); p.add_argument("--replay-config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True); a = p.parse_args(argv)
    if a.output.exists(): raise FileExistsError(a.output)
    report = validate(a.snapshot, holdout=a.holdout, replay_config=a.replay_config)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True)); return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__": raise SystemExit(main())
