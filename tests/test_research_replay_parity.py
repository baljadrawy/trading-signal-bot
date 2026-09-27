import pandas as pd
import numpy as np
import pytest

from analyzer.simple_entry import detect_trade_setup
from research.foundation.contract import current_contract
from research.foundation.replay import config_from_levels
from research.foundation.replay import ReplayContext, evaluate_opportunity
from shared.strategy_math import calculate_signal_levels
from shared.triple_barrier import expiry_policy_for_timeframe


def _frame():
    n=21
    return pd.DataFrame({"open":[99.9]*20+[104], "high":[102]*20+[106],
        "low":[99]*20+[103], "close":[100]*20+[105], "volume":[100]*20+[200],
        "ema20":[99]*n, "ema50":[98]*n, "rsi":[50]*n,
        "bb_lower":[90]*n, "bb_upper":[110]*n, "atr":[2]*n})


def test_golden_momentum_and_level_parity():
    df = _frame()
    trade_type, _, _ = detect_trade_setup(df, market_condition="bullish")
    assert trade_type == "momentum"
    levels = calculate_signal_levels(df, "4h", trade_type)
    assert levels == {"entry":105.0, "stop":101.5, "stop_policy":"momentum_breakout",
        "stop_invalidation":101.5, "stop_risk_pct":3.3333, "stop_valid":True,
        "stop_reject_reason":None, "t1":108.5, "t2":111.3, "t3":112.7}


def test_current_expiry_contract_matches_production_function():
    contract = current_contract()
    for tf in ("15m","4h","1d"):
        assert tuple(contract["position"]["expiry_hours"][tf]) == expiry_policy_for_timeframe(tf)


def test_config_from_levels_preserves_contract():
    levels = {"entry":100,"stop":97,"t1":103,"t2":105.4,"t3":106.6}
    cfg = config_from_levels("XUSDT", "1d", levels, current_contract())
    assert (cfg.expiry_h, cfg.t1_expiry_h, cfg.no_t1_expiry_h) == (240,120,72)
    assert cfg.roundtrip_cost == .003 and cfg.stop_slippage == .001


def test_golden_accepted_opportunity_uses_production_entry_and_regime():
    n = 220; ts = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    close = np.linspace(100, 120, n); close[-1] = 122
    frame = pd.DataFrame({"timestamp":ts, "close_time":ts + pd.Timedelta(hours=4),
        "open":close-.1, "high":close+.2, "low":close-.2, "close":close,
        "volume":[100.]*(n-1)+[300.]})
    params = {"rsi_period":14,"macd_fast":12,"macd_slow":26,"macd_signal":9,
        "ema_short":20,"ema_medium":50,"ema_long":200,"bb_period":20,"bb_std":2.,
        "atr_period":14,"stoch_rsi_window":14,"stoch_k":3,"stoch_d":3}
    contract = current_contract()
    context = ReplayContext("ds", "exp", "sha", "v", "DISCOVERY", contract, params)
    record, levels = evaluate_opportunity(raw_history=frame,
        decision_time=frame.close_time.iloc[-1].isoformat(), symbol="XUSDT", timeframe="4h",
        market={"quote_volume":20_000_000,"change_24h_pct":2,"macro_pass":True,
                "spread":.1,"spread_data_mode":"HISTORICAL_SPREAD_PROXY"},
        context=context, universe_eligible=True)
    assert record.accepted and record.rejection_code == "ACCEPTED"
    assert record.market_context["market_regime"] == "bullish"
    assert record.strategy_state["trade_type_candidate"] == "momentum"
    assert levels["stop_valid"]
