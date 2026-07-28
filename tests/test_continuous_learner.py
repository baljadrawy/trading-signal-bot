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


def test_fee_blind_gate_throttles_gross_positive_net_negative():
    """العطب: خلية إجماليها موجب (+0.3%) لكنها خاسرة صافياً بعد رسوم 0.6% يجب أن تُخنق.
    مع fee_roundtrip=0.6 يصبح الصافي -0.3% → weight=0 وتُخزَّن expectancy صافية سالبة.
    على الكود القديم (بلا رسوم) كانت هذه الخلية تُبقى weight=1 و expectancy=+0.3."""
    trades = [_t('reversion','usdtd_falling','4h', p) for p in [0.3]*12]  # n=12 gross exp=+0.3
    cells = compute_cells(trades, min_cell_n=10, throttle_expectancy=0, fee_roundtrip=0.6)
    c = [c for c in cells if c['trade_type']=='reversion'][0]
    assert c['n'] == 12
    assert abs(c['expectancy'] - (0.3 - 0.6)) < 1e-9   # net = -0.3, مخزَّنة صافية
    assert c['weight'] == 0.0                          # مخنوقة لأن الصافي سالب


def test_fee_net_positive_cell_kept():
    """خلية إجماليها +1.0% تتجاوز رسوم 0.3% → صافٍ +0.7% تبقى مفعّلة."""
    trades = [_t('momentum','usdtd_rising','1d', p) for p in [1.0]*11]  # gross +1.0
    cells = compute_cells(trades, min_cell_n=10, throttle_expectancy=0, fee_roundtrip=0.3)
    c = [c for c in cells if c['trade_type']=='momentum'][0]
    assert abs(c['expectancy'] - 0.7) < 1e-9 and c['weight'] == 1.0


def test_default_fee_zero_backward_compatible():
    """بلا تمرير fee_roundtrip يبقى السلوك كما كان (صافٍ=إجمالي) — توافق خلفي."""
    trades = [_t('momentum','usdtd_falling','4h', p) for p in [2,3,-1,2,1,2,3,-1,2,2,3,1]]
    cells = compute_cells(trades, min_cell_n=10, throttle_expectancy=0)
    c = [c for c in cells if c['trade_type']=='momentum'][0]
    assert c['expectancy'] > 0 and c['weight'] == 1.0
