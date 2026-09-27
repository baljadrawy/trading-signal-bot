"""Outcome-blind conservative execution proxy for controlled research."""
from __future__ import annotations

from typing import Mapping, Any


FORBIDDEN = {"pnl", "profit", "profit_factor", "future_return", "label", "accepted",
             "rejected", "strategy_result", "win_rate", "expectancy"}


def conservative_spread_proxy(features: Mapping[str, Any]) -> float:
    """Return spread percent from current microstructure only; never strategy outcomes.

    This is a deliberately conservative schedule, not a calibrated estimator.
    """
    bad = FORBIDDEN.intersection(str(k).lower() for k in features)
    if bad:
        raise ValueError(f"outcome fields forbidden in spread proxy: {sorted(bad)}")
    quote_volume = float(features["rolling_24h_quote_volume"])
    volatility = float(features.get("realized_volatility_pct", 0.0))
    trades = float(features.get("rolling_24h_trade_count", 0.0))
    if quote_volume >= 100_000_000 and trades >= 10_000:
        base = 0.05
    elif quote_volume >= 25_000_000:
        base = 0.10
    elif quote_volume >= 10_000_000:
        base = 0.20
    else:
        base = 0.40
    return min(0.75, base + max(0.0, volatility - 3.0) * 0.01)


EXECUTION_METADATA = {
    "execution_fidelity": "TIER_3_DOCUMENTED_CONSERVATIVE_PROXY",
    "calibrated": False,
    "outcome_blind": True,
    "mandatory_phase2_control": "cost_and_slippage_stress",
    "inputs": ["rolling_24h_quote_volume", "realized_volatility_pct",
               "rolling_24h_trade_count"],
    "units": "spread_pct",
}
