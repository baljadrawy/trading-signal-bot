from datetime import datetime, timedelta, timezone

from research.walk_forward_review import purged_walk_forward, select_regime


def _row(i, gross=1.0, duration_h=12, condition='volatile', trade_type='momentum'):
    signal = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)
    return {
        'id': i, 'signal_time': signal, 'exit_time': signal + timedelta(hours=duration_h),
        'gross_return': gross, 'trade_type': trade_type, 'macro_state': 'usdtd_flat',
        'timeframe': '4h', 'market_condition': condition,
    }


def test_purge_removes_labels_overlapping_embargo_boundary():
    rows = [_row(i) for i in range(60)]
    rows[23]['exit_time'] = rows[24]['signal_time'] - timedelta(hours=1)
    folds = purged_walk_forward(rows, 0.3, folds=3, embargo_hours=24, min_cell_n=5)
    assert len(folds) == 3
    assert folds[0]['purged_n'] >= 1
    cutoff = folds[0]['baseline_rows'][0]['signal_time'] - timedelta(hours=24)
    assert all(row['exit_time'] < cutoff for row in rows[:24] if row in rows[:folds[0]['train_n']])


def test_regime_selection_uses_confident_training_evidence_only():
    strong = [_row(i, gross=1.0, condition='volatile') for i in range(30)]
    weak = [_row(i + 30, gross=(-1) ** i, condition='sideways') for i in range(30)]
    assert select_regime(strong + weak, fee_pct=0.3, minimum_n=30) == 'volatile'
    assert select_regime(weak, fee_pct=0.3, minimum_n=30) is None


def test_walk_forward_never_uses_future_rows_for_training():
    rows = [_row(i, gross=-1 if i < 30 else 5) for i in range(60)]
    folds = purged_walk_forward(rows, 0.3, folds=3, embargo_hours=24, min_cell_n=5)
    for fold in folds:
        test_start = fold['baseline_rows'][0]['signal_time']
        assert fold['train_n'] < sum(row['signal_time'] < test_start for row in rows)
