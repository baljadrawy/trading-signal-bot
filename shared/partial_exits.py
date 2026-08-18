"""Pure partial-exit planning and accounting helpers."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TargetFill:
    target: int
    fraction: float
    price: float
    gross_pct_contribution: float
    gross_usdt: float


def target_distribution(trade_amount: float, min_notional: float) -> dict[int, float]:
    """Return 25/50/25, merging sub-minimum edge tranches into T2."""
    if trade_amount <= 0 or min_notional < 0:
        raise ValueError('trade amount must be positive and min notional non-negative')
    fractions = {1: 0.25, 2: 0.50, 3: 0.25}
    for target in (1, 3):
        if fractions[target] * trade_amount + 1e-12 < min_notional:
            fractions[2] += fractions[target]
            fractions[target] = 0.0
    return fractions


def fills_between(*, previous_target: int, reached_target: int, entry: float,
                  targets: dict[int, float], trade_amount: float,
                  min_notional: float) -> list[TargetFill]:
    if not 0 <= previous_target <= reached_target <= 3:
        raise ValueError('invalid target transition')
    distribution = target_distribution(trade_amount, min_notional)
    fills = []
    for target in range(previous_target + 1, reached_target + 1):
        fraction = distribution[target]
        if fraction <= 0:
            continue
        price = float(targets[target])
        gross_pct = (price / entry - 1) * 100
        fills.append(TargetFill(
            target=target, fraction=fraction, price=price,
            gross_pct_contribution=gross_pct * fraction,
            gross_usdt=gross_pct / 100 * trade_amount * fraction,
        ))
    return fills


def aggregate_close(*, entry: float, final_exit: float, trade_amount: float,
                    realized_pct: float, realized_usdt: float,
                    remaining_fraction: float) -> tuple[float, float]:
    """Combine prior target tranches and the terminal fill into gross P&L."""
    terminal_pct = (final_exit / entry - 1) * 100
    return (
        realized_pct + terminal_pct * remaining_fraction,
        realized_usdt + terminal_pct / 100 * trade_amount * remaining_fraction,
    )
