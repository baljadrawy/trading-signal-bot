"""Paper/live-neutral entry-order policy for approved long candidates."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EntryDecision:
    action: str  # market | limit_wait | reject
    reason: str
    order_price: float | None


def decide_long_entry(*, trade_type: str, planned_entry: float,
                      current_price: float, stop_loss: float,
                      invalidation_price: float | None = None) -> EntryDecision:
    if min(planned_entry, current_price, stop_loss) <= 0:
        return EntryDecision('reject', 'invalid_price', None)
    invalidation = float(invalidation_price or stop_loss)
    rejection_level = max(float(stop_loss), invalidation)
    if current_price <= rejection_level:
        return EntryDecision('reject', 'signal_invalidated_before_fill', None)
    if trade_type not in ('momentum', 'reversion'):
        return EntryDecision('reject', 'unsupported_trade_type', None)
    if current_price <= planned_entry:
        reason = ('momentum_retest_better_price' if trade_type == 'momentum'
                  else 'reversion_better_price')
        return EntryDecision('market', reason, current_price)
    return EntryDecision('limit_wait', f'{trade_type}_do_not_chase', planned_entry)
