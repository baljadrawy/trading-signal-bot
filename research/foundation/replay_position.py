"""Offline position replay reusing the production barrier and partial-fill functions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from shared.partial_exits import aggregate_close, fills_between
from shared.signal_stop import candle_invalidated
from shared.triple_barrier import TripleBarrierConfig, TripleBarrierState, step_barrier
from .costs import CostModel


@dataclass
class ReplayPosition:
    trade_id: str
    cfg: TripleBarrierConfig
    opened_ms: int
    stop_invalidation: float
    timeframe: str
    min_notional: float = 5.0
    state: TripleBarrierState = field(init=False)
    realized_pct: float = 0.0
    realized_usdt: float = 0.0
    sold_fraction: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.state = TripleBarrierState(peak=self.cfg.entry)
        self._event(self.opened_ms, "NONE", "OPEN", self.cfg.entry, "entry")

    def _event(self, timestamp: Any, previous: str, new: str, price: float, reason: str) -> None:
        self.events.append({"timestamp": timestamp, "previous_state": previous,
                            "new_state": new, "price": float(price), "reason": reason})

    def step(self, candle: dict[str, Any], *, hours: float,
             intrabar_policy: str = "CONSERVATIVE") -> dict[str, Any] | None:
        if intrabar_policy not in {"CONSERVATIVE", "AMBIGUOUS"}:
            raise ValueError("invalid intrabar policy")
        ts = candle["timestamp"]; high = float(candle["high"]); low = float(candle["low"])
        close = float(candle["close"]); prior_target = self.state.highest_target
        prior_stop = self.state.effective_stop(self.cfg)[0]
        touches_target = high >= self.cfg.target_1
        if low <= prior_stop and touches_target and intrabar_policy == "AMBIGUOUS":
            self._event(ts, self._name(prior_target), "AMBIGUOUS", close,
                        "intrabar_sequence_unknown")
            return self._finish(close, "intrabar_sequence_unknown", ts, ambiguous=True)
        close_ms = int(candle.get("close_time_ms", candle.get("timestamp_ms", 0)))
        if candle_invalidated(opened_ms=self.opened_ms, candle_close_ms=close_ms,
                              candle_close=close, invalidation_price=self.stop_invalidation,
                              highest_target=self.state.highest_target):
            self._event(ts, self._name(prior_target), "CLOSED", close, "signal_candle_invalidation")
            return self._finish(close, "signal_candle_invalidation", ts)
        result = step_barrier(self.cfg, self.state, high, low, close, hours_elapsed=hours)
        reached = self.state.highest_target
        if reached > prior_target:
            fills = fills_between(previous_target=prior_target, reached_target=reached,
                                  entry=self.cfg.entry,
                                  targets={1: self.cfg.target_1, 2: self.cfg.target_2, 3: self.cfg.target_3},
                                  trade_amount=self.cfg.trade_amount,
                                  min_notional=self.min_notional)
            for fill in fills:
                before = self._name(fill.target - 1)
                self.realized_pct += fill.gross_pct_contribution
                self.realized_usdt += fill.gross_usdt
                self.sold_fraction += fill.fraction
                self._event(ts, before, self._name(fill.target), fill.price, f"T{fill.target}_fill")
        if result is None: return None
        return self._finish(result.exit_price, result.exit_reason, ts)

    def _name(self, target: int) -> str:
        return "OPEN" if target == 0 else f"T{target}_FILLED"

    def _finish(self, price: float, reason: str, timestamp: Any, ambiguous: bool = False) -> dict[str, Any]:
        remaining = max(0.0, 1.0 - self.sold_fraction)
        gross_pct, gross_usdt = aggregate_close(entry=self.cfg.entry, final_exit=price,
                                                trade_amount=self.cfg.trade_amount,
                                                realized_pct=self.realized_pct,
                                                realized_usdt=self.realized_usdt,
                                                remaining_fraction=remaining)
        self._event(timestamp, self._name(self.state.highest_target), "CLOSED", price, reason)
        return {"trade_id": self.trade_id, "entry_price": self.cfg.entry,
                "exit_price": price, "gross_pct": gross_pct, "gross_usdt": gross_usdt,
                "remaining_fraction": remaining, "exit_reason": reason,
                "highest_target": self.state.highest_target,
                "duration_h": self.state.hours_open, "intrabar_ambiguous": ambiguous,
                "events": list(self.events)}


def apply_costs(result: dict[str, Any], notional: float, model: CostModel) -> dict[str, Any]:
    model.validate()
    cost = model.entry_cost(notional) + model.exit_cost(notional)
    result = dict(result); result["cost_usdt"] = cost
    result["net_usdt"] = result["gross_usdt"] - cost
    result["net_pct"] = result["gross_pct"] - model.baseline_roundtrip * 100
    result["cost_model"] = model.metadata()
    return result
