"""Offline replay pipeline. No network, database, messaging or wall-clock dependencies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import pandas as pd

from analyzer.simple_entry import detect_trade_setup
from shared.regime import classify_regime
from shared.strategy_math import calculate_production_indicators, calculate_signal_levels
from shared.triple_barrier import TripleBarrierConfig, expiry_policy_for_timeframe
from .contract import contract_hash
from .opportunity import (OpportunityRecord, RejectionCode,
                          deterministic_opportunity_id)
from .quality import enforce_completed, validate_candles


@dataclass(frozen=True)
class ReplayContext:
    dataset_id: str
    experiment_id: str
    git_sha: str
    strategy_version: str
    partition: str
    contract: dict[str, Any]
    indicator_params: dict[str, Any]


def _feature_snapshot(df: pd.DataFrame, regime: dict[str, Any], execution: dict[str, Any]) -> dict:
    last = df.iloc[-1]
    keys = ("open", "high", "low", "close", "volume", "ema20", "ema50", "ema200",
            "rsi", "bb_lower", "bb_upper", "bb_width", "atr", "adx", "volume_ratio",
            "macd_hist", "stoch_k", "stoch_d", "obv", "obv_ema")
    features = {key: _finite(last.get(key)) for key in keys}
    features.update({"ema20_slope": regime.get("ema20_slope_5_pct"),
                     "atr_percentile": regime.get("atr_percentile_100"),
                     "prior_high": execution.get("breakout_level"),
                     "breakout_level": execution.get("breakout_level"),
                     "volume_baseline": execution.get("volume_baseline"),
                     "bollinger_position": execution.get("bb_position"),
                     "structural_low": float(df.tail(20)["low"].min())})
    return features


def _finite(value: Any) -> float | None:
    try:
        value = float(value)
        return value if value == value and abs(value) != float("inf") else None
    except (TypeError, ValueError):
        return None


def evaluate_opportunity(*, raw_history: pd.DataFrame, decision_time: str,
                         symbol: str, timeframe: str, market: dict[str, Any],
                         context: ReplayContext, universe_eligible: bool,
                         risk_allowed: bool = True, risk_reason: str = "within_limits") -> tuple[OpportunityRecord, dict | None]:
    quality = validate_candles(raw_history, timeframe)
    base = dict(dataset_id=context.dataset_id, experiment_id=context.experiment_id,
                git_sha=context.git_sha, strategy_version=context.strategy_version,
                strategy_contract_hash=contract_hash(context.contract), decision_time=decision_time,
                signal_time=decision_time, entry_eligible_time=decision_time,
                symbol=symbol, timeframe=timeframe, research_partition=context.partition)
    oid = deterministic_opportunity_id(context.dataset_id, symbol, timeframe,
                                       decision_time, context.strategy_version)
    if quality["status"] == "FAIL":
        return OpportunityRecord(opportunity_id=oid, **base, market_context=market,
            liquidity=_liquidity(market), features={}, strategy_state={}, accepted=False,
            rejection_code=RejectionCode.NOT_ELIGIBLE_INSUFFICIENT_HISTORY.value
            if "insufficient_history" in quality["failures"] else RejectionCode.REJECT_DATA_QUALITY.value,
            rejection_detail=quality), None
    history = enforce_completed(raw_history, decision_time)
    if len(history) < 200:
        return OpportunityRecord(opportunity_id=oid, **base, market_context=market,
            liquidity=_liquidity(market), features={}, strategy_state={}, accepted=False,
            rejection_code=RejectionCode.NOT_ELIGIBLE_INSUFFICIENT_HISTORY.value,
            rejection_detail={"rows": len(history)}), None
    df = calculate_production_indicators(history, context.indicator_params)
    regime = dict(classify_regime(df))
    trade_type, reason, execution = detect_trade_setup(
        df, breakout_n=context.contract["entry"]["momentum"]["breakout_n"],
        vol_mult=context.contract["entry"]["momentum"]["volume_multiplier"],
        rev_rsi=context.contract["entry"]["reversion"]["rsi_max"],
        bb_max_position=context.contract["entry"]["reversion"]["bollinger_position_max"],
        market_condition=regime["condition"])
    momentum_pass = detect_trade_setup(df, market_condition="bullish")[0] == "momentum"
    reversion_pass = detect_trade_setup(df, market_condition="sideways")[0] == "reversion"
    features = _feature_snapshot(df, regime, execution)
    state = {"trade_type_candidate": trade_type, "entry_reason": reason,
             "momentum_pass": momentum_pass, "reversion_pass": reversion_pass,
             "macro_pass": market.get("macro_pass"), "universe_pass": universe_eligible,
             "macro_admission": market.get("macro_admission"),
             "risk_admission_pass": risk_allowed, "risk_reason": risk_reason}
    code, detail = _decision_code(context.contract, market, universe_eligible,
                                  trade_type, regime["condition"], risk_allowed, risk_reason)
    levels = calculate_signal_levels(df, timeframe, trade_type,
                                     breakout_n=context.contract["entry"]["momentum"]["breakout_n"])
    if code == RejectionCode.ACCEPTED and not levels["stop_valid"]:
        code, detail = RejectionCode.REJECT_STOP_DISTANCE, {"reason": levels["stop_reject_reason"]}
    accepted = code == RejectionCode.ACCEPTED
    record = OpportunityRecord(opportunity_id=oid, **base,
        market_context={**market, "market_regime": regime["condition"],
                        "atr_percentile": regime["atr_percentile_100"]},
        liquidity=_liquidity(market), features=features, strategy_state=state,
        accepted=accepted, rejection_code=code.value, rejection_detail=detail)
    return record, levels if accepted else None


def _liquidity(market: dict[str, Any]) -> dict[str, Any]:
    return {"quote_volume": market.get("quote_volume"), "spread": market.get("spread"),
            "change_24h_pct": market.get("change_24h_pct"),
            "spread_data_mode": market.get("spread_data_mode", "NO_SPREAD_DATA")}


def _decision_code(contract: dict, market: dict, universe: bool, trade_type: str | None,
                   regime: str, risk_allowed: bool, risk_reason: str):
    if not universe: return RejectionCode.REJECT_UNIVERSE, {}
    volume = market.get("quote_volume")
    if volume is None or float(volume) < contract["universe"]["min_quote_volume_24h"]:
        return RejectionCode.REJECT_VOLUME, {"observed": volume}
    change = market.get("change_24h_pct")
    if change is None or abs(float(change)) < contract["universe"]["min_abs_change_24h_pct"]:
        return RejectionCode.REJECT_PRICE_MOVEMENT, {"observed": change}
    macro_bypass = market.get("macro_admission") == "BYPASSED_BY_RESEARCH_ABLATION"
    if not macro_bypass and market.get("macro_pass") is None:
        return RejectionCode.REJECT_MACRO_DATA_UNAVAILABLE, {}
    if not macro_bypass and not market["macro_pass"]: return RejectionCode.REJECT_MACRO, {}
    mode, spread = market.get("spread_data_mode", "NO_SPREAD_DATA"), market.get("spread")
    if mode == "NO_SPREAD_DATA" or spread is None:
        return RejectionCode.REJECT_SPREAD_DATA_UNAVAILABLE, {"mode": mode}
    if float(spread) > contract["execution_filters"]["max_spread_pct"]:
        return RejectionCode.REJECT_SPREAD, {"observed": spread}
    if regime not in {"bullish", "sideways"}: return RejectionCode.REJECT_REGIME, {"regime": regime}
    if not trade_type: return RejectionCode.REJECT_ENTRY, {}
    if not risk_allowed:
        mapping = {"daily_loss_limit": RejectionCode.REJECT_DAILY_RISK,
                   "weekly_loss_limit": RejectionCode.REJECT_WEEKLY_RISK,
                   "max_drawdown_limit": RejectionCode.REJECT_DRAWDOWN,
                   "max_open_trades": RejectionCode.REJECT_MAX_TRADES}
        return mapping.get(risk_reason, RejectionCode.REJECT_PORTFOLIO_CAP), {"reason": risk_reason}
    return RejectionCode.ACCEPTED, {}


def config_from_levels(symbol: str, timeframe: str, levels: dict[str, Any],
                       contract: dict[str, Any]) -> TripleBarrierConfig:
    expiry, t1_expiry, no_t1 = expiry_policy_for_timeframe(timeframe)
    return TripleBarrierConfig(symbol=symbol, entry=levels["entry"], target_1=levels["t1"],
        target_2=levels["t2"], target_3=levels["t3"], stop_loss=levels["stop"],
        trade_amount=contract["risk"]["trade_amount_usdt"], expiry_h=expiry,
        t1_expiry_h=t1_expiry, no_t1_expiry_h=no_t1,
        trail_stop_pct=contract["position"]["trail_stop_pct"],
        stop_slippage=contract["cost"]["stop_slippage"],
        roundtrip_cost=contract["cost"]["roundtrip_cost"])
