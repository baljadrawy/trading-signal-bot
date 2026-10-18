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


# ── A38: entry fill models ───────────────────────────────────────────────────────────────────
# decide_long_entry() above is unchanged: it is the entry policy (reject / market / limit_wait).
# A fill model turns that policy decision into a simulated fill. The model in force is
# config.PAPER_ENTRY_FILL_MODEL, and each trade records it in active_trades.entry_fill_model.
#
# observed_price_v0 (legacy, default): fill at the observed last price whenever the policy says
#   'market'. A resting limit order that was waiting above its limit therefore fills at the first
#   observed price at or below the limit, which may be well below it. That is price improvement a
#   resting limit order does not get. It also rejects an order once the observed price is below
#   the invalidation level, although the market traded through the limit first; this drops
#   adversely selected entries.
#
# resting_limit_v1: an order's kind is fixed by how it arrived, and the paper_entry_orders row
#   keeps it across restarts:
#   * marketable: arrived when the price was at or below the limit. It fills at the observed
#     price (a taker order). Price improvement relative to the plan is genuine here, but the
#     bid/ask spread is unknown (the price is the last trade); FEE_ROUNDTRIP_PCT's slippage
#     allowance is the only cover for it.
#   * resting: was waiting at its limit. It fills AT THE LIMIT, and only on a strict trade-through
#     (observed price < limit). On a touch (== limit), queue position is unknown, so the order
#     stays unfilled (conservative). A trade-through also fills when the observed price is already
#     below the invalidation level, as long as invalidation is below the limit: the market crossed
#     the limit first, and the trade's exit rules then decide. When invalidation is at or above the
#     limit, the order is cancelled before it could fill (the legacy reject).
#   Unchanged: full-size fills, no fill probability or latency model, and the risk and capacity
#   gates still run at fill time.
LEGACY_FILL_MODEL = 'observed_price_v0'
RESTING_LIMIT_FILL_MODEL = 'resting_limit_v1'
FILL_MODELS = (LEGACY_FILL_MODEL, RESTING_LIMIT_FILL_MODEL)


@dataclass(frozen=True)
class EntryFill:
    action: str             # fill | wait | reject
    price: float | None     # simulated fill price when action == 'fill'
    basis: str              # why: marketable_observed | resting_trade_through | resting_touch_unfilled | ...
    order_kind: str         # marketable | resting (the kind after this evaluation)


def order_kind_after(previous_kind: str | None, decision: EntryDecision) -> str:
    """An order rests once any evaluation found the price above its limit; that never reverts."""
    if previous_kind == 'resting' or decision.action == 'limit_wait':
        return 'resting'
    return 'marketable'


def resolve_entry_fill(*, model: str, decision: EntryDecision, previous_kind: str | None,
                       planned_entry: float, current_price: float, stop_loss: float,
                       invalidation_price: float | None = None) -> EntryFill:
    if model not in FILL_MODELS:
        raise ValueError(f'unknown entry fill model {model!r}')
    kind = order_kind_after(previous_kind, decision)
    if model == LEGACY_FILL_MODEL or kind == 'marketable':
        if decision.action == 'market':
            return EntryFill('fill', float(current_price), 'marketable_observed'
                             if kind == 'marketable' else 'legacy_observed', kind)
        if decision.action == 'limit_wait':
            return EntryFill('wait', None, 'limit_not_reached', kind)
        return EntryFill('reject', None, decision.reason, kind)
    # resting_limit_v1, resting order
    if decision.reason in ('invalid_price', 'unsupported_trade_type'):
        return EntryFill('reject', None, decision.reason, kind)
    limit = float(planned_entry)
    rejection_level = max(float(stop_loss), float(invalidation_price or stop_loss))
    if rejection_level >= limit:                   # invalidation before the limit: cancelled
        if decision.action == 'reject':
            return EntryFill('reject', None, 'cancelled_invalidated_before_limit', kind)
        return EntryFill('wait', None, 'limit_not_reached', kind)
    if current_price < limit:
        return EntryFill('fill', limit, 'resting_trade_through', kind)
    if current_price == limit:
        return EntryFill('wait', None, 'resting_touch_unfilled', kind)
    return EntryFill('wait', None, 'limit_not_reached', kind)
