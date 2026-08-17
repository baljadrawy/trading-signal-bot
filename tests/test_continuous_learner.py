import sys; sys.path.insert(0, '.')
from datetime import datetime, timedelta
from research.continuous_learner import compute_cells, select_stale_throttles

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


def test_noisy_negative_mean_fails_open_when_ci_crosses_zero():
    trades = [_t('momentum','usdtd_flat','4h', p)
              for p in [-5, 4, -4, 5, -3, 3, -2, 2, -1, 0] * 2]
    c = compute_cells(trades, min_cell_n=10, throttle_expectancy=0, fee_roundtrip=0.3)[0]
    assert c['expectancy'] < 0
    assert c['ci_high'] > 0
    assert c['weight'] == 1.0


# ── تقادم الخلايا المخنوقة (إعادة الفحص الدوري) ──
NOW = datetime(2026, 8, 10, 12, 0, 0)

def _g(tt, ms, tf, weight, age_days):
    return {'trade_type': tt, 'macro_state': ms, 'timeframe': tf,
            'weight': weight, 'updated_at': NOW - timedelta(days=age_days)}

def test_stale_throttle_selected_for_expiry():
    """خلية مخنوقة (weight=0) أقدم من عتبة التقادم → تُنتقى للحذف فتُعاد إحماءً."""
    rows = [_g('momentum','usdtd_flat','15m', 0.0, 37)]
    out = select_stale_throttles(rows, now=NOW, stale_days=14)
    assert out == [('momentum','usdtd_flat','15m')]

def test_fresh_throttle_not_expired():
    """خليّة مخنوقة لكنها حديثة (يُعاد تقييمها يومياً) → لا تُحذف."""
    rows = [_g('reversion','usdtd_rising','4h', 0.0, 1)]
    assert select_stale_throttles(rows, now=NOW, stale_days=14) == []

def test_stale_allow_not_expired():
    """خليّة مسموحة (weight=1) قديمة → لا تُحذف (لا تحجب إشارات أصلاً)."""
    rows = [_g('momentum','usdtd_flat','1d', 1.0, 60)]
    assert select_stale_throttles(rows, now=NOW, stale_days=14) == []

def test_boundary_exactly_at_cutoff_not_expired():
    """عند العتبة تماماً (age = stale_days) لا تُحذف — الحذف للأقدم فقط (< صارمة)."""
    rows = [_g('reversion','usdtd_falling','15m', 0.0, 14)]
    assert select_stale_throttles(rows, now=NOW, stale_days=14) == []

def test_mixed_only_stale_throttles_selected():
    rows = [
        _g('momentum','usdtd_flat','15m', 0.0, 37),      # stale throttle → expire
        _g('reversion','usdtd_rising','4h', 0.0, 1),      # fresh throttle → keep
        _g('momentum','usdtd_flat','1d', 1.0, 60),        # stale allow → keep
        _g('reversion','usdtd_rising','15m', 0.0, 25),    # stale throttle → expire
    ]
    out = set(select_stale_throttles(rows, now=NOW, stale_days=14))
    assert out == {('momentum','usdtd_flat','15m'), ('reversion','usdtd_rising','15m')}

def test_null_weight_not_expired():
    """صفّ weight=NULL (لا يحجب في SQL: NULL<=0 ليست صحيحة) → لا يُنتقى للحذف."""
    rows = [{'trade_type':'momentum','macro_state':'usdtd_flat','timeframe':'4h',
             'weight': None, 'updated_at': NOW - timedelta(days=99)}]
    assert select_stale_throttles(rows, now=NOW, stale_days=14) == []
