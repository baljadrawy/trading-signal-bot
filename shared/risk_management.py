"""Pure portfolio risk policy used before admitting a new trade."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RiskLimits:
    capital_usdt: float
    trade_amount_usdt: float
    max_open_trades: int
    max_gross_exposure_pct: float = 80.0
    max_symbol_exposure_pct: float = 10.0
    max_daily_loss_pct: float = 3.0
    weekly_reduce_pct: float = 5.0
    weekly_minimum_pct: float = 7.0
    max_weekly_loss_pct: float = 10.0
    drawdown_caution_pct: float = 5.0
    drawdown_warning_pct: float = 10.0
    max_drawdown_pct: float = 15.0
    loss_reduce_count: int = 3
    loss_minimum_count: int = 5
    loss_halt_count: int = 7


@dataclass(frozen=True)
class RiskSnapshot:
    realized_total_usdt: float
    daily_pnl_usdt: float
    weekly_pnl_usdt: float
    unrealized_pnl_usdt: float
    peak_equity_usdt: float
    open_count: int
    symbol_open_count: int
    consecutive_losses: int
    manually_paused: bool = False
    manual_pause_reason: str | None = None


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    size_multiplier: float
    max_positions: int
    daily_pnl_pct: float
    weekly_pnl_pct: float
    drawdown_pct: float
    gross_exposure_pct_after: float
    symbol_exposure_pct_after: float
    consecutive_losses: int


def _pct(value: float, capital: float) -> float:
    return value / capital * 100.0


def evaluate_new_trade(snapshot: RiskSnapshot, limits: RiskLimits) -> RiskDecision:
    """Return a fail-closed admission decision for one equal-sized new trade."""
    numeric = (
        limits.capital_usdt, limits.trade_amount_usdt,
        snapshot.realized_total_usdt, snapshot.daily_pnl_usdt,
        snapshot.weekly_pnl_usdt, snapshot.unrealized_pnl_usdt,
        snapshot.peak_equity_usdt,
    )
    if (not all(math.isfinite(x) for x in numeric)
            or limits.capital_usdt <= 0 or limits.trade_amount_usdt <= 0
            or limits.max_open_trades <= 0 or snapshot.open_count < 0
            or snapshot.symbol_open_count < 0 or snapshot.consecutive_losses < 0):
        return RiskDecision(False, 'invalid_risk_state', 0.0, 0, 0, 0, 0, 0, 0,
                            max(0, snapshot.consecutive_losses))

    current_equity = (limits.capital_usdt + snapshot.realized_total_usdt
                      + snapshot.unrealized_pnl_usdt)
    peak = max(limits.capital_usdt, snapshot.peak_equity_usdt)
    drawdown = max(0.0, _pct(peak - current_equity, peak))
    daily = _pct(snapshot.daily_pnl_usdt + snapshot.unrealized_pnl_usdt,
                 limits.capital_usdt)
    weekly = _pct(snapshot.weekly_pnl_usdt + snapshot.unrealized_pnl_usdt,
                  limits.capital_usdt)
    gross_after = _pct((snapshot.open_count + 1) * limits.trade_amount_usdt,
                       limits.capital_usdt)
    symbol_after = _pct((snapshot.symbol_open_count + 1) * limits.trade_amount_usdt,
                        limits.capital_usdt)

    multiplier = 1.0
    reasons = []
    if drawdown >= limits.drawdown_warning_pct:
        multiplier = min(multiplier, 0.25)
        reasons.append('drawdown_warning')
    elif drawdown >= limits.drawdown_caution_pct:
        multiplier = min(multiplier, 0.5)
        reasons.append('drawdown_caution')
    if weekly <= -limits.weekly_minimum_pct:
        multiplier = min(multiplier, 0.1)
        reasons.append('weekly_minimum')
    elif weekly <= -limits.weekly_reduce_pct:
        multiplier = min(multiplier, 0.5)
        reasons.append('weekly_reduce')
    if snapshot.consecutive_losses >= limits.loss_minimum_count:
        multiplier = min(multiplier, 0.1)
        reasons.append('loss_streak_minimum')
    elif snapshot.consecutive_losses >= limits.loss_reduce_count:
        multiplier = min(multiplier, 0.5)
        reasons.append('loss_streak_reduce')

    max_by_exposure = math.floor(
        limits.capital_usdt * limits.max_gross_exposure_pct / 100
        / limits.trade_amount_usdt + 1e-12)
    base_max = min(limits.max_open_trades, max_by_exposure)
    effective_max = max(1, math.floor(base_max * multiplier))

    hard_stop = None
    if snapshot.manually_paused:
        hard_stop = snapshot.manual_pause_reason or 'manual_pause'
    elif daily <= -limits.max_daily_loss_pct:
        hard_stop = 'daily_loss_limit'
    elif weekly <= -limits.max_weekly_loss_pct:
        hard_stop = 'weekly_loss_limit'
    elif drawdown >= limits.max_drawdown_pct:
        hard_stop = 'max_drawdown_limit'
    elif snapshot.consecutive_losses >= limits.loss_halt_count:
        hard_stop = 'loss_streak_halt'
    elif gross_after > limits.max_gross_exposure_pct + 1e-9:
        hard_stop = 'gross_exposure_limit'
    elif symbol_after > limits.max_symbol_exposure_pct + 1e-9:
        hard_stop = 'symbol_concentration_limit'
    elif snapshot.open_count >= effective_max:
        hard_stop = reasons[0] if reasons else 'max_open_trades'

    return RiskDecision(
        hard_stop is None, hard_stop or (reasons[0] if reasons else 'within_limits'),
        multiplier, effective_max, daily, weekly, drawdown, gross_after, symbol_after,
        snapshot.consecutive_losses)
