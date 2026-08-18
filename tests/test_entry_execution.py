from shared.entry_execution import decide_long_entry


def test_better_price_uses_market_only_above_invalidation():
    d = decide_long_entry(trade_type='momentum', planned_entry=100,
                          current_price=99, stop_loss=95,
                          invalidation_price=97)
    assert d.action == 'market'


def test_price_at_or_above_entry_waits_on_limit():
    d = decide_long_entry(trade_type='reversion', planned_entry=100,
                          current_price=101, stop_loss=95)
    assert d.action == 'limit_wait'
    assert d.order_price == 100


def test_candidate_below_invalidation_is_rejected():
    d = decide_long_entry(trade_type='momentum', planned_entry=100,
                          current_price=96, stop_loss=95,
                          invalidation_price=97)
    assert d.action == 'reject'
