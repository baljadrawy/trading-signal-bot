from datetime import datetime

import pytest

from research.portfolio_review import (
    grouped_metrics, longest_underwater, max_drawdown, portfolio_metrics, remove_top_symbols,
    stress_remove_best, symbol_concentration,
)


def test_drawdown_and_underwater_metrics():
    equity = [100, 110, 105, 100, 115]
    assert max_drawdown(equity) == pytest.approx((110 - 100) / 110)
    assert longest_underwater(equity) == 2


def test_portfolio_metrics_uses_prior_equity_for_daily_returns():
    result = portfolio_metrics([10, -5, 5], 100)
    assert result['ending_equity'] == 110
    assert result['total_return_pct'] == pytest.approx(10)
    assert result['max_drawdown_pct'] == pytest.approx(5 / 110 * 100)
    assert result['worst_day_pct'] == pytest.approx(-5 / 110 * 100)


def test_concentration_and_removal_stress():
    rows = [
        {'symbol': 'A', 'net_pct': 5.0}, {'symbol': 'A', 'net_pct': 2.0},
        {'symbol': 'B', 'net_pct': -1.0}, {'symbol': 'C', 'net_pct': 1.0},
    ]
    result = symbol_concentration(rows)
    assert result['ordered'][0] == ('A', 7.0)
    assert result['top1_positive_share_pct'] == pytest.approx(87.5)
    assert remove_top_symbols(rows, 1)['expectancy'] == 0.0
    assert stress_remove_best([5, 2, -1], counts=(1,))[1]['expectancy'] == 0.5
    assert grouped_metrics(rows, 'symbol')[0][0] == 'A'
