from shared.learning_governance import exploration_selected, validate_cells


def _cell(**overrides):
    value = {'trade_type': 'momentum', 'macro_state': 'usdtd_flat',
             'timeframe': '4h', 'n': 12, 'wr': 50.0,
             'expectancy': 0.2, 'weight': 1.0}
    value.update(overrides)
    return value


def test_valid_learning_batch_passes():
    assert validate_cells([_cell()], trade_count=20, min_cell_n=10) == []


def test_nan_and_unknown_dimensions_are_rejected():
    errors = validate_cells(
        [_cell(trade_type='invented', expectancy=float('nan'))],
        trade_count=20, min_cell_n=10)
    assert any('invalid trade_type' in error for error in errors)
    assert any('invalid expectancy' in error for error in errors)


def test_small_cell_cannot_throttle():
    errors = validate_cells([_cell(n=3, weight=0.0)], trade_count=20, min_cell_n=10)
    assert any('undersized cell cannot be throttled' in error for error in errors)


def test_empty_batch_is_rejected():
    assert 'learning produced no cells' in validate_cells([], trade_count=10, min_cell_n=5)


def test_exploration_is_stable_and_bounded():
    key, bucket = 'BTC|momentum|flat|15m', '2026-08-17T12'
    assert exploration_selected(key, bucket, 0.0) is False
    assert exploration_selected(key, bucket, 1.0) is True
    assert exploration_selected(key, bucket, 0.1) == exploration_selected(key, bucket, 0.1)
