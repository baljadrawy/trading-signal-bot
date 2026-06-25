import sys; sys.path.insert(0, '.')
from research.continuous_learner import compute_cells

def _t(tt, ms, tf, pct):
    return {'trade_type': tt, 'macro_state': ms, 'timeframe': tf,
            'profit_percent': pct, 'is_win': pct > 0}

def test_winning_cell_weight_1():
    trades = [_t('momentum','usdtd_falling','4h', p) for p in [2,3,-1,2,1,2,3,-1,2,2,3,1]]  # n=12 pos exp
    cells = compute_cells(trades, min_cell_n=10, throttle_expectancy=0)
    c = [c for c in cells if c['trade_type']=='momentum'][0]
    assert c['n'] == 12 and c['expectancy'] > 0 and c['weight'] == 1.0

def test_losing_cell_throttled():
    trades = [_t('reversion','usdtd_rising','1d', p) for p in [-2,-3,1,-2,-1,-2,-3,1,-2,-2,-1]]  # n=11 neg exp
    cells = compute_cells(trades, min_cell_n=10, throttle_expectancy=0)
    c = [c for c in cells if c['trade_type']=='reversion'][0]
    assert c['expectancy'] < 0 and c['weight'] == 0.0

def test_small_cell_neutral():
    trades = [_t('momentum','usdtd_flat','15m', p) for p in [-5,-5,-5]]  # n=3 < min
    cells = compute_cells(trades, min_cell_n=10, throttle_expectancy=0)
    c = [c for c in cells if c['trade_type']=='momentum'][0]
    assert c['n'] == 3 and c['weight'] == 1.0   # محايد رغم الخسارة (عيّنة صغيرة)
