from datetime import datetime, timedelta

from research.strategy_performance_review import (
    entry_hypothesis_verdict, metrics, learned_blocked_keys, walk_forward,
)


def _row(i, gross, trade_type='momentum'):
    return {'id': i, 'exit_time': datetime(2026, 1, 1) + timedelta(days=i),
            'gross_return': gross, 'trade_type': trade_type,
            'macro_state': 'usdtd_flat', 'timeframe': '4h', 'symbol': 'BTCUSDT'}


def test_metrics_net_profit_factor_and_drawdown():
    result = metrics([1.0, -0.5, -0.5, 2.0])
    assert result['expectancy'] == 0.5
    assert result['profit_factor'] == 3.0
    assert result['max_drawdown'] == 1.0
    assert result['ci_low'] < result['expectancy'] < result['ci_high']


def test_entry_hypothesis_gate_requires_statistical_and_economic_edge():
    strong = metrics([1.0] * 60 + [-0.2] * 40)
    assert entry_hypothesis_verdict('reversion', strong) == 'GO'
    uncertain = metrics([2.0] * 50 + [-2.0] * 50)
    assert entry_hypothesis_verdict('momentum', uncertain) == 'NO-GO'


def test_training_blocks_only_sufficient_losing_cell():
    rows = [_row(i, -1.0) for i in range(10)] + [_row(20, 5.0, 'reversion')]
    blocked = learned_blocked_keys(rows, fee_pct=0.3, min_cell_n=10)
    assert ('momentum', 'usdtd_flat', '4h') in blocked
    assert ('reversion', 'usdtd_flat', '4h') not in blocked


def test_walk_forward_uses_prior_rows_and_returns_five_folds():
    rows = [_row(i, -1.0 if i < 30 else 1.0) for i in range(60)]
    folds = walk_forward(rows, fee_pct=0.3, min_cell_n=5, folds=5)
    assert len(folds) == 5
    assert all(fold['train_n'] < 60 for fold in folds)
    assert folds[0]['blocked_cells'] == 1
