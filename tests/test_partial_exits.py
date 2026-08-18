import pytest

from shared.partial_exits import aggregate_close, fills_between, target_distribution


def test_standard_distribution_is_25_50_25():
    assert target_distribution(50, 5) == {1: .25, 2: .50, 3: .25}


def test_small_edge_orders_merge_into_t2():
    assert target_distribution(10, 5) == {1: 0, 2: 1.0, 3: 0}


def test_crossing_multiple_targets_accounts_each_tranche():
    fills = fills_between(previous_target=0, reached_target=2, entry=100,
                          targets={1: 102, 2: 104, 3: 106},
                          trade_amount=50, min_notional=5)
    assert [f.target for f in fills] == [1, 2]
    assert sum(f.fraction for f in fills) == .75
    assert sum(f.gross_usdt for f in fills) == pytest.approx(1.25)


def test_final_close_combines_realized_and_remaining_fraction():
    pct, usdt = aggregate_close(entry=100, final_exit=98, trade_amount=50,
                                realized_pct=.5, realized_usdt=.25,
                                remaining_fraction=.75)
    assert pct == pytest.approx(-1.0)
    assert usdt == pytest.approx(-.5)
