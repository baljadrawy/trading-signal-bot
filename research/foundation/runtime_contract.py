"""Runtime-contract capture and macro-only research derivation.

This module is research-only.  It never mutates production configuration and
never serialises environment values outside an explicit non-secret allowlist.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .contract import canonical_json, compare_contracts, contract_hash, current_contract


MACRO_ABLATION = "MACRO_DISABLED_RESEARCH_ABLATION"
MACRO_BYPASS = "BYPASSED_BY_RESEARCH_ABLATION"
MACRO_DIFF_ALLOWLIST = frozenset({
    "macro.required", "macro.mode", "macro.admission_behavior",
})
SECRET_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "WEBHOOK", "PRIVATE_KEY")


def contract_id(kind: str, value: Mapping[str, Any]) -> str:
    return f"{kind.lower()}-{contract_hash(value)[:20]}"


def runtime_contract(*, analyzer: Mapping[str, Any], tracker: Mapping[str, Any],
                     runtime_logic_sources: Mapping[str, str]) -> dict[str, Any]:
    """Build the semantic contract from the owning production components."""
    value = current_contract()
    value["timeframes"] = list(analyzer["TIMEFRAMES"])
    value["universe"].update(
        min_quote_volume_24h=float(analyzer["MIN_VOLUME_USDT"]),
        min_abs_change_24h_pct=float(analyzer["MIN_PRICE_CHANGE_PERCENT"]),
    )
    value["entry"]["momentum"].update(
        breakout_n=int(analyzer["MOM_BREAKOUT_N"]),
        volume_n=int(analyzer["MOM_BREAKOUT_N"]),
        volume_multiplier=float(analyzer["MOM_VOL_MULT"]),
    )
    value["entry"]["reversion"].update(
        rsi_max=float(analyzer["REV_RSI"]),
        bollinger_position_max=float(analyzer["REV_BB_MAX_POSITION"]),
    )
    value["execution_filters"]["max_spread_pct"] = float(analyzer["MAX_SPREAD_PCT"])
    value["cost"].update(
        roundtrip_cost=float(tracker["FEE_ROUNDTRIP_PCT"]) / 100.0,
        stop_slippage=float(tracker["STOP_SLIPPAGE"]),
    )
    value["risk"].update(
        trade_amount_usdt=float(tracker["TRADE_AMOUNT_USDT"]),
        capital_usdt=float(tracker["RISK_CAPITAL_USDT"]),
        max_open_trades=min(int(tracker["MAX_OPEN_TRADES"]),
                            int(tracker["RISK_CANARY_MAX_OPEN_TRADES"])),
        max_gross_exposure_pct=float(tracker["MAX_GROSS_EXPOSURE_PERCENT"]),
        max_symbol_exposure_pct=float(tracker["MAX_SYMBOL_EXPOSURE_PERCENT"]),
        max_strategy_exposure_pct=float(tracker["MAX_STRATEGY_EXPOSURE_PERCENT"]),
        max_regime_exposure_pct=float(tracker["MAX_REGIME_EXPOSURE_PERCENT"]),
        max_daily_loss_pct=float(tracker["MAX_DAILY_LOSS_PERCENT"]),
        max_weekly_loss_pct=float(tracker["MAX_WEEKLY_LOSS_PERCENT"]),
        max_drawdown_pct=float(tracker["MAX_DRAWDOWN_PERCENT"]),
        loss_halt_count=int(tracker["STOP_ON_CONSECUTIVE_LOSSES"]),
    )
    # Hash the code that is actually loaded in the running component images.
    value["logic_sources"] = dict(sorted(runtime_logic_sources.items()))
    return value


def derive_macro_disabled(parent: Mapping[str, Any]) -> dict[str, Any]:
    child = deepcopy(parent)
    child["macro"] = deepcopy(child["macro"])
    child["macro"].update(required=False, mode=MACRO_ABLATION,
                          admission_behavior=MACRO_BYPASS)
    return child


def macro_only_diff(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    result = compare_contracts(parent, child)
    paths = {row["path"] for row in result["differences"]}
    unexpected = sorted(paths - MACRO_DIFF_ALLOWLIST)
    missing = sorted(MACRO_DIFF_ALLOWLIST - paths)
    return {
        "status": "PASS" if not unexpected and not missing else "FAIL — RESEARCH_CONTRACT_DRIFT",
        "allowed_paths": sorted(MACRO_DIFF_ALLOWLIST),
        "observed_paths": sorted(paths),
        "unexpected_paths": unexpected,
        "missing_paths": missing,
        "differences": result["differences"],
    }


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        upper = str(key).upper()
        if any(marker in upper for marker in SECRET_MARKERS):
            result[key] = {"present": bool(value), "source": "environment"}
        elif isinstance(value, Mapping):
            result[key] = redact_mapping(value)
        else:
            result[key] = value
    return result


def config_hash(values: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(redact_mapping(values)).encode()).hexdigest()


def snapshot_document(*, contract: Mapping[str, Any], status: str,
                      git_sha: str, git_dirty: bool, runtime_config: Mapping[str, Any],
                      provenance: Mapping[str, Any], captured_at: str | None = None,
                      parent_contract_id: str | None = None) -> dict[str, Any]:
    cid = contract_id(status, contract)
    return {
        "contract_id": cid,
        "contract_hash": contract_hash(contract),
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "git_dirty": bool(git_dirty),
        "runtime_config_hash": config_hash(runtime_config),
        "contract_schema_version": contract["schema_version"],
        "status": status,
        "parent_contract_id": parent_contract_id,
        "contract": contract,
        "provenance": redact_mapping(provenance),
    }


def write_new_read_only(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"immutable contract artifact exists: {path}")
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    path.chmod(0o444)

