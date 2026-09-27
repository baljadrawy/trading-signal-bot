"""Explicit execution-cost metadata and cash accounting."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CostModel:
    entry_fee: float = 0.001
    exit_fee: float = 0.001
    spread_cost: float = 0.0005
    slippage: float = 0.0005
    stop_slippage: float = 0.001

    def validate(self) -> None:
        if any(not 0 <= x < 1 for x in asdict(self).values()):
            raise ValueError("cost rates must be in [0,1)")

    @property
    def baseline_roundtrip(self) -> float:
        return self.entry_fee + self.exit_fee + self.spread_cost + self.slippage

    def entry_cost(self, notional: float) -> float:
        return notional * (self.entry_fee + self.spread_cost / 2 + self.slippage / 2)

    def exit_cost(self, notional_fraction: float) -> float:
        return notional_fraction * (self.exit_fee + self.spread_cost / 2 + self.slippage / 2)

    def metadata(self) -> dict:
        return {**asdict(self), "baseline_roundtrip": self.baseline_roundtrip}
