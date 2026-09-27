"""Canonical, serialisable fingerprint of the production trading contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.triple_barrier import TIMEFRAME_EXPIRY_HOURS


CONTRACT_SCHEMA_VERSION = "1.0.0"


def current_contract(runtime_config: Any | None = None) -> dict[str, Any]:
    """Return values wired by the current production path, without reading env state."""
    contract = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "direction": "long_only",
        "timeframes": ["15m", "4h", "1d"],
        "universe": {
            "quote_asset": "USDT", "status": "TRADING",
            "excluded_symbols": ["BUSDUSDT", "TUSDUSDT", "USDCUSDT"],
            "min_quote_volume_24h": 10_000_000.0,
            "min_abs_change_24h_pct": 1.0,
            "strong_bearish_min_abs_change_pct": 5.0,
        },
        "entry": {
            "momentum": {"regime": "bullish", "breakout_n": 20, "volume_n": 20,
                         "volume_multiplier": 1.2, "ema_fast": 20, "ema_slow": 50},
            "reversion": {"regime": "sideways", "rsi_n": 14, "rsi_max": 35.0,
                          "bollinger_n": 20, "bollinger_std": 2.0,
                          "bollinger_position_max": 0.20,
                          "requires_bullish_candle": True,
                          "requires_close_above_previous": True},
        },
        "regime": {"adx_n": 14, "adx_trend": 25.0, "adx_range": 20.0,
                   "ema_n": 20, "slope_bars": 5, "atr_n": 14,
                   "vol_lookback": 100, "high_vol_percentile": 0.75},
        "execution_filters": {"max_spread_pct": 0.15,
                              "orderbook_required": True,
                              "historical_spread_modes": ["HISTORICAL_ORDERBOOK",
                                                          "HISTORICAL_SPREAD_PROXY",
                                                          "NO_SPREAD_DATA"]},
        "stop": {"atr_buffer": 0.25, "minimum_atr_distance": 1.0,
                 "max_risk_pct": {"15m": 2.0, "4h": 5.0, "1d": 3.0}},
        "targets": {"r_multiples": {"1": 1.0, "2": 1.8, "3": 2.2},
                    "fractions": {"1": 0.25, "2": 0.50, "3": 0.25},
                    "t1_resistance_cap_factor": 0.99, "min_notional_usdt": 5.0},
        "position": {"trail_stop_pct": 2.5,
                     "expiry_hours": {k: list(v) for k, v in TIMEFRAME_EXPIRY_HOURS.items()},
                     "candle_invalidation_before_t1": True,
                     "intrabar_default": "CONSERVATIVE"},
        "cost": {"roundtrip_cost": 0.003, "stop_slippage": 0.001,
                 "baseline_components": {"entry_fee": 0.001,
                                         "exit_fee": 0.001,
                                         "spread_cost": 0.0005,
                                         "slippage": 0.0005}},
        "risk": {"trade_amount_usdt": 50.0, "capital_usdt": 500.0,
                 "max_open_trades": 2, "max_gross_exposure_pct": 80.0,
                 "max_symbol_exposure_pct": 10.0,
                 "max_strategy_exposure_pct": 40.0,
                 "max_regime_exposure_pct": 50.0,
                 "max_daily_loss_pct": 3.0, "max_weekly_loss_pct": 10.0,
                 "max_drawdown_pct": 15.0, "loss_halt_count": 7},
        "macro": {"required": True, "missing_policy": "MACRO_DATA_UNAVAILABLE"},
    }
    root = Path(__file__).resolve().parents[2]
    sources = ("analyzer/simple_entry.py", "shared/regime.py", "shared/signal_stop.py",
               "shared/triple_barrier.py", "shared/partial_exits.py",
               "shared/risk_management.py", "shared/strategy_math.py",
               "scanner/scanner_logic.py", "signal_engine/signal_logic.py")
    contract["logic_sources"] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources
    }
    if runtime_config is not None:
        contract["timeframes"] = list(runtime_config.TIMEFRAMES)
        contract["universe"].update(
            min_quote_volume_24h=float(runtime_config.MIN_VOLUME_USDT),
            min_abs_change_24h_pct=float(runtime_config.MIN_PRICE_CHANGE_PERCENT))
        contract["entry"]["momentum"].update(
            breakout_n=int(runtime_config.MOM_BREAKOUT_N),
            volume_n=int(runtime_config.MOM_BREAKOUT_N),
            volume_multiplier=float(runtime_config.MOM_VOL_MULT))
        contract["entry"]["reversion"].update(
            rsi_max=float(runtime_config.REV_RSI),
            bollinger_position_max=float(runtime_config.REV_BB_MAX_POSITION))
        contract["execution_filters"]["max_spread_pct"] = float(runtime_config.MAX_SPREAD_PCT)
        contract["cost"].update(roundtrip_cost=float(runtime_config.FEE_ROUNDTRIP_PCT) / 100,
                                stop_slippage=float(runtime_config.STOP_SLIPPAGE))
        contract["risk"].update(trade_amount_usdt=float(runtime_config.TRADE_AMOUNT_USDT),
                                capital_usdt=float(runtime_config.RISK_CAPITAL_USDT),
                                max_open_trades=min(int(runtime_config.MAX_OPEN_TRADES),
                                    int(runtime_config.RISK_CANARY_MAX_OPEN_TRADES)),
                                max_gross_exposure_pct=float(runtime_config.MAX_GROSS_EXPOSURE_PERCENT),
                                max_symbol_exposure_pct=float(runtime_config.MAX_SYMBOL_EXPOSURE_PERCENT),
                                max_strategy_exposure_pct=float(runtime_config.MAX_STRATEGY_EXPOSURE_PERCENT),
                                max_regime_exposure_pct=float(runtime_config.MAX_REGIME_EXPOSURE_PERCENT),
                                max_daily_loss_pct=float(runtime_config.MAX_DAILY_LOSS_PERCENT),
                                max_weekly_loss_pct=float(runtime_config.MAX_WEEKLY_LOSS_PERCENT),
                                max_drawdown_pct=float(runtime_config.MAX_DRAWDOWN_PERCENT),
                                loss_halt_count=int(runtime_config.STOP_ON_CONSECUTIVE_LOSSES))
    return contract


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def contract_hash(contract: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(contract).encode()).hexdigest()


def compare_contracts(live: Mapping[str, Any], research: Mapping[str, Any]) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []

    def walk(a: Any, b: Any, path: str) -> None:
        if isinstance(a, Mapping) and isinstance(b, Mapping):
            for key in sorted(set(a) | set(b)):
                child = f"{path}.{key}" if path else str(key)
                if key not in a:
                    differences.append({"path": child, "live": None, "research": b[key]})
                elif key not in b:
                    differences.append({"path": child, "live": a[key], "research": None})
                else:
                    walk(a[key], b[key], child)
        elif a != b:
            differences.append({"path": path, "live": a, "research": b})

    walk(live, research, "")
    return {"match": not differences,
            "status": "MATCH" if not differences else "RESEARCH CONTRACT DOES NOT MATCH LIVE CONTRACT",
            "live_hash": contract_hash(live), "research_hash": contract_hash(research),
            "differences": differences}
