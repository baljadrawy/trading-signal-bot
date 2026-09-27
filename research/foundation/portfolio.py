"""Deterministic mark-to-market ledger for replay output."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def mark_to_market(initial_cash: float, trades: Iterable[dict[str, Any]],
                   prices: dict[str, dict[str, float]]) -> tuple[list[dict], dict]:
    events = sorted({ts for series in prices.values() for ts in series})
    trades = list(trades); curve = []; peak = initial_cash; max_dd = 0.0
    for ts in events:
        realized = sum(float(t.get("net_usdt", 0)) for t in trades if str(t["exit_time"]) <= ts)
        open_trades = [t for t in trades if str(t["entry_time"]) <= ts < str(t["exit_time"])]
        unrealized = 0.0; gross = 0.0; by_symbol = defaultdict(float)
        by_strategy = defaultdict(float); by_regime = defaultdict(float)
        for trade in open_trades:
            price = prices.get(trade["symbol"], {}).get(ts)
            if price is None: continue
            notional = float(trade["notional"]); gross += notional; by_symbol[trade["symbol"]] += notional
            by_strategy[str(trade.get("trade_type") or "unknown")] += notional
            by_regime[str(trade.get("market_regime") or "unknown")] += notional
            unrealized += (float(price) / float(trade["entry_price"]) - 1) * notional
        cash = initial_cash + realized
        equity = cash + unrealized; peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak else 0.0; max_dd = max(max_dd, dd)
        curve.append({"timestamp": ts, "cash": cash, "open_position_value": gross + unrealized,
                      "equity": equity, "gross_exposure": gross,
                      "gross_exposure_pct": gross / equity * 100 if equity else 0.0,
                      "drawdown_pct": dd, "symbol_exposure": dict(by_symbol),
                      "strategy_exposure": dict(by_strategy), "regime_exposure": dict(by_regime)})
    avg = sum(x["gross_exposure_pct"] for x in curve) / len(curve) if curve else 0.0
    return curve, {"max_drawdown_pct": max_dd, "average_gross_exposure_pct": avg,
                   "max_gross_exposure_pct": max((x["gross_exposure_pct"] for x in curve), default=0.0),
                   "time_in_market_pct": (sum(bool(x["gross_exposure"]) for x in curve) / len(curve) * 100
                                          if curve else 0.0)}


def risk_fields(entry: float, stop: float, notional: float, capital: float) -> dict[str, float]:
    distance = (entry - stop) / entry
    at_risk = notional * distance
    return {"notional": notional, "stop_distance_pct": distance * 100,
            "capital_at_risk_usdt": at_risk,
            "capital_at_risk_pct": at_risk / capital * 100}
