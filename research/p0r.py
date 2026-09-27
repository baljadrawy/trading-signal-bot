"""Phase 2A-P0R: runtime capture, Parquet parity and technical dry-run only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

import pandas as pd

from research.data_governance.execution import EXECUTION_METADATA, conservative_spread_proxy
from research.data_governance.universe import PointInTimeUniverse, UniverseEvent, utc
from research.foundation.contract import compare_contracts, contract_hash, current_contract
from research.foundation.readers import ADAPTER_VERSION, NormalizedParquetReader
from research.foundation.replay import ReplayContext, evaluate_opportunity
from research.foundation.runtime_contract import (
    MACRO_ABLATION, MACRO_BYPASS, derive_macro_disabled, macro_only_diff,
    runtime_contract, snapshot_document, write_new_read_only,
)
from shared.config import config as host_config
from shared.risk_management import RiskLimits, RiskSnapshot, evaluate_new_trade
from shared.strategy_math import production_indicator_params
from shared.triple_barrier import expiry_policy_for_timeframe


REPO = Path(__file__).resolve().parents[1]
DATASET = Path("/home/tradmin/research-data/trading-signal-bot/snapshots/ds-09284abbc6453ff59acd")
EXPECTED_DATASET_ID = "ds-09284abbc6453ff59acd"
EXPECTED_MANIFEST_HASH = "a7c8eee1ecbd05eef3e28b1a40bd7199cc3fb9ac71ab3aac2c84ac0ca6a33b09"
KNOWLEDGE_CUTOFF = "2026-08-19T09:33:46Z"
HISTORICAL_END = "2026-05-31T23:59:59.999999Z"

ANALYZER_KEYS = ["TIMEFRAMES", "MIN_VOLUME_USDT", "MIN_PRICE_CHANGE_PERCENT",
                 "MOM_BREAKOUT_N", "MOM_VOL_MULT", "REV_RSI", "REV_BB_MAX_POSITION",
                 "MAX_SPREAD_PCT"]
TRACKER_KEYS = ["MAX_OPEN_TRADES", "RISK_CANARY_MAX_OPEN_TRADES", "RISK_CAPITAL_USDT",
                "MAX_DAILY_LOSS_PERCENT", "MAX_WEEKLY_LOSS_PERCENT", "MAX_DRAWDOWN_PERCENT",
                "MAX_GROSS_EXPOSURE_PERCENT", "MAX_SYMBOL_EXPOSURE_PERCENT",
                "MAX_STRATEGY_EXPOSURE_PERCENT", "MAX_REGIME_EXPOSURE_PERCENT",
                "STOP_ON_CONSECUTIVE_LOSSES", "FEE_ROUNDTRIP_PCT", "STOP_SLIPPAGE",
                "TRADE_AMOUNT_USDT"]
LOGIC_FILES = {
    "trading_analyzer": ["/app/simple_entry.py", "/app/technical_analyzer.py",
                         "/app/shared/regime.py", "/app/shared/signal_stop.py"],
    "trading_scanner": ["/app/scanner_logic.py"],
    "trading_signal_engine": ["/app/signal_logic.py"],
    "trading_tracker": ["/app/main.py", "/app/shared/triple_barrier.py",
                        "/app/shared/partial_exits.py", "/app/shared/risk_management.py",
                        "/app/shared/execution.py"],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _container_config(container: str, names: list[str]) -> dict[str, Any]:
    code = ("import json; from shared.config import config; "
            f"print(json.dumps({{k:getattr(config,k) for k in {names!r}}}))")
    output = subprocess.check_output(["docker", "exec", container, "python", "-c", code], text=True)
    return json.loads(output)


def _logic_hashes() -> dict[str, str]:
    result = {}
    for container, paths in LOGIC_FILES.items():
        for path in paths:
            output = subprocess.check_output(["docker", "exec", container, "sha256sum", path], text=True)
            result[f"{container}:{path}"] = output.split()[0]
    return result


def _container_metadata(container: str) -> dict[str, Any]:
    raw = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]
    labels = raw["Config"].get("Labels") or {}
    return {
        "container": container,
        "image": raw["Config"]["Image"],
        "image_id": raw["Image"],
        "command": raw["Config"].get("Cmd"),
        "started_at": raw["State"]["StartedAt"],
        "compose_service": labels.get("com.docker.compose.service"),
        "compose_config": labels.get("com.docker.compose.project.config_files"),
    }


def capture() -> dict[str, Any]:
    if sha256(DATASET / "manifest.json") != EXPECTED_MANIFEST_HASH:
        raise RuntimeError("STOP-1 — Dataset Drift")
    analyzer = _container_config("trading_analyzer", ANALYZER_KEYS)
    tracker = _container_config("trading_tracker", TRACKER_KEYS)
    logic = _logic_hashes()
    production = runtime_contract(analyzer=analyzer, tracker=tracker,
                                  runtime_logic_sources=logic)
    child = derive_macro_disabled(production)
    gate = macro_only_diff(production, child)
    if gate["status"] != "PASS":
        raise RuntimeError(gate["status"])
    git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    git_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True))
    captured_at = datetime.now(timezone.utc).isoformat()
    metadata = {name: _container_metadata(name) for name in LOGIC_FILES}
    provenance = {
        "runtime_mode": "active docker compose production services",
        "timeframes": {"source": "trading_analyzer:shared.config.Config.TIMEFRAMES"},
        "risk.max_open_trades": {
            "source": "trading_tracker:min(MAX_OPEN_TRADES,RISK_CANARY_MAX_OPEN_TRADES)"},
        "config_sources": metadata,
        "knowledge_freeze": KNOWLEDGE_CUTOFF,
        "disclosure": "CURRENT_RUNTIME_CONTRACT_REBASED_AFTER_KNOWLEDGE_FREEZE",
    }
    runtime_values = {"analyzer": analyzer, "tracker": tracker, "logic_sources": logic}
    prod = snapshot_document(contract=production, status="PRODUCTION_RUNTIME_CANONICAL",
        git_sha=git_sha, git_dirty=git_dirty, runtime_config=runtime_values,
        provenance=provenance, captured_at=captured_at)
    legacy_contract = current_contract()
    legacy = snapshot_document(contract=legacy_contract, status="LEGACY_RESEARCH_CONTRACT",
        git_sha=git_sha, git_dirty=git_dirty, runtime_config={}, provenance={
            "source": "research/governance/research_freeze.json",
            "freeze_timestamp": KNOWLEDGE_CUTOFF,
            "preserved_hash": contract_hash(legacy_contract),
        }, captured_at=captured_at)
    research = snapshot_document(contract=child, status="PHASE2A_MACRO_DISABLED_CONTRACT",
        git_sha=git_sha, git_dirty=git_dirty, runtime_config=runtime_values,
        provenance={**provenance, "research_mode": MACRO_ABLATION,
                    "macro_admission": MACRO_BYPASS}, captured_at=captured_at,
        parent_contract_id=prod["contract_id"])
    out = REPO / "research" / "governance" / "contracts"
    write_new_read_only(out / f"{legacy['contract_id']}.json", legacy)
    write_new_read_only(out / f"{prod['contract_id']}.json", prod)
    write_new_read_only(out / f"{research['contract_id']}.json", research)
    diff = {
        "legacy_vs_runtime": compare_contracts(legacy_contract, production),
        "production_vs_research": gate,
    }
    write_new_read_only(out / f"diff-{prod['contract_hash'][:12]}.json", diff)
    return {"legacy": legacy, "production": prod, "research": research, "diff": diff}


def _universe() -> PointInTimeUniverse:
    rows = json.loads((DATASET / "universe" / "universe_events.json").read_text())
    events = [UniverseEvent(symbol=r["symbol"], quote_asset=r["quote_asset"],
        event_type=r["event_type"], event_time=utc(r["event_time"]), source=r["source"],
        source_reference=r["source_reference"], confidence=r["confidence"],
        source_tier=r["source_tier"], evidence_timestamp=utc(r["evidence_timestamp"]),
        evidence_kind=r["evidence_kind"]) for r in rows]
    first = {e.symbol: e.event_time for e in events if e.event_type == "LISTED"}
    return PointInTimeUniverse(events, first)


def technical_dry_run(contract: dict[str, Any]) -> dict[str, Any]:
    reader = NormalizedParquetReader.open(DATASET)
    if reader.dataset_id != EXPECTED_DATASET_ID:
        raise RuntimeError("STOP-1 — Dataset Drift")
    universe = _universe(); outputs = []
    params = production_indicator_params(host_config)
    cutoff = pd.Timestamp("2024-06-01T00:00:00Z")
    for timeframe in ("15m", "1h", "4h", "1d"):
        frame = reader.read("BTCUSDT", timeframe, verify_hash=True)
        sample = frame[frame["close_time"] <= cutoff].tail(240).reset_index(drop=True)
        decision = pd.Timestamp(sample.iloc[-1]["close_time"])
        liquidity = reader.liquidity_asof("BTCUSDT", decision)
        spread = conservative_spread_proxy(liquidity)
        duration = {"15m": pd.Timedelta(minutes=15), "1h": pd.Timedelta(hours=1),
                    "4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1)}[timeframe]
        eligible = universe.strategy_eligible("BTCUSDT", decision.to_pydatetime(),
            timeframe=duration.to_pytimedelta(), warmup_candles=100)
        context = ReplayContext(reader.dataset_id, "p0r-technical-dry-run", "63da7d31",
            "sb-2026.08", "RESEARCH_CONTAMINATED", contract, params)
        market = {"quote_volume": liquidity["rolling_24h_quote_volume"],
            "change_24h_pct": liquidity["price_change_24h_pct"], "spread": spread,
            "spread_data_mode": "HISTORICAL_SPREAD_PROXY", "macro_pass": None,
            "macro_admission": MACRO_BYPASS}
        record, levels = evaluate_opportunity(raw_history=sample,
            decision_time=decision.isoformat(), symbol="BTCUSDT", timeframe=timeframe,
            market=market, context=context, universe_eligible=eligible)
        if record.strategy_state.get("macro_admission") != MACRO_BYPASS:
            raise RuntimeError("STOP-5 — Macro Misrepresentation")
        outputs.append({"timeframe": timeframe, "rows": len(sample),
            "opportunity_id": record.opportunity_id, "decision_time": record.decision_time,
            "decision": record.rejection_code, "macro_admission": MACRO_BYPASS,
            "levels": levels, "expiry_policy": expiry_policy_for_timeframe(timeframe),
            "liquidity_source_time": liquidity["liquidity_source_time"]})
    risk = contract["risk"]
    limits = RiskLimits(capital_usdt=risk["capital_usdt"], trade_amount_usdt=risk["trade_amount_usdt"],
        max_open_trades=risk["max_open_trades"], max_gross_exposure_pct=risk["max_gross_exposure_pct"],
        max_symbol_exposure_pct=risk["max_symbol_exposure_pct"],
        max_strategy_exposure_pct=risk["max_strategy_exposure_pct"],
        max_regime_exposure_pct=risk["max_regime_exposure_pct"],
        max_daily_loss_pct=risk["max_daily_loss_pct"], max_weekly_loss_pct=risk["max_weekly_loss_pct"],
        max_drawdown_pct=risk["max_drawdown_pct"], loss_halt_count=risk["loss_halt_count"])
    snapshot = RiskSnapshot(realized_total_usdt=0, daily_pnl_usdt=0, weekly_pnl_usdt=0,
        unrealized_pnl_usdt=0, peak_equity_usdt=risk["capital_usdt"],
        open_count=risk["max_open_trades"], symbol_open_count=0, consecutive_losses=0,
        strategy_open_count=0, regime_open_count=0)
    risk_decision = evaluate_new_trade(snapshot, limits)
    return {"performance_output_enabled": False, "adapter_version": ADAPTER_VERSION,
        "execution_fidelity": EXECUTION_METADATA["execution_fidelity"],
        "timeframes": outputs, "runtime_max_open_trades": risk["max_open_trades"],
        "capacity_rejection": {"allowed": risk_decision.allowed, "reason": risk_decision.reason}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("capture", "dry-run", "monitor"))
    parser.add_argument("--contract")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.command == "capture":
        result = capture()
        print(json.dumps({"production_contract": result["production"]["contract_id"],
                          "research_contract": result["research"]["contract_id"],
                          "macro_diff_gate": result["diff"]["production_vs_research"]["status"]}))
        return 0
    if not args.contract: raise SystemExit("--contract required")
    approved = json.loads(Path(args.contract).read_text())
    if args.command == "dry-run":
        first = technical_dry_run(approved["contract"])
        second = technical_dry_run(approved["contract"])
        result = {"deterministic": first == second, "performance_output_enabled": False,
                  "research_contract_hash": approved["contract_hash"], "result": first}
        if args.output:
            write_new_read_only(Path(args.output), result)
        print(json.dumps(result, indent=2))
        return 0 if first == second else 2
    analyzer = _container_config("trading_analyzer", ANALYZER_KEYS)
    tracker = _container_config("trading_tracker", TRACKER_KEYS)
    current = runtime_contract(analyzer=analyzer, tracker=tracker,
                               runtime_logic_sources=_logic_hashes())
    match = contract_hash(current) == approved["contract_hash"]
    print(json.dumps({"status": "MATCH" if match else "PRODUCTION_CHANGED_SINCE_RESEARCH_FREEZE",
                      "current_hash": contract_hash(current),
                      "approved_hash": approved["contract_hash"]}))
    return 0 if match else 3


if __name__ == "__main__":
    raise SystemExit(main())
