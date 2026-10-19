"""Conservative transaction-cost model (s4-mech-v1).

Baseline: Binance Spot taker fee 0.10 % per side (0.20 % round trip), no BNB discount. Spread and
slippage are separate, explicitly declared components; they are never folded into the fee. The
tracker's flat 0.30 % round-trip accounting is a separate reporting convention, never a substitute.

Costs are charged on traded notional: cost = turnover × (fee + half_spread + slippage), where
turnover is the sum of absolute weight changes (a full entry plus a full exit = 2.0).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

BASELINE_FEE_PER_SIDE = 0.001            # 0.10 %
TRACKER_FLAT_ROUNDTRIP = 0.003           # 0.30 %: reporting convention only


class CostModelError(ValueError):
    """Invalid or artificially discounted cost assumption."""


def _rate(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CostModelError(f"{name} must be a number")
    v = float(value)
    if not math.isfinite(v) or v < 0:
        raise CostModelError(f"{name} must be finite and >= 0")
    return v


@dataclass(frozen=True)
class CostModel:
    """Per-side cost rates as fractions of traded notional."""
    fee_per_side: float = BASELINE_FEE_PER_SIDE
    half_spread: float = 0.0
    slippage: float = 0.0
    label: str = "baseline_fee_only"

    def __post_init__(self):
        fee = _rate(self.fee_per_side, "fee_per_side")
        _rate(self.half_spread, "half_spread")
        _rate(self.slippage, "slippage")
        if fee < BASELINE_FEE_PER_SIDE:
            raise CostModelError(
                f"fee_per_side {fee} is below the 0.10 % baseline; discounted fees are not modelled")

    @property
    def per_side(self) -> float:
        return self.fee_per_side + self.half_spread + self.slippage

    @property
    def round_trip(self) -> float:
        return 2.0 * self.per_side

    def cost(self, turnover: float) -> float:
        """Cost as a fraction of portfolio value for a given turnover."""
        return _rate(turnover, "turnover") * self.per_side


def tracker_flat_cost(round_trips: float) -> float:
    """The tracker's flat 0.30 %-per-round-trip label, for side-by-side reporting only."""
    return _rate(round_trips, "round_trips") * TRACKER_FLAT_ROUNDTRIP


BASELINE = CostModel()
