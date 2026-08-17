import sys; sys.path.insert(0, '.')
import pytest
from shared.triple_barrier import modeled_stop_exit


def test_stop_fill_at_stop_with_slippage():
    # entry 100, stop 97 (-3%), 0.1% slippage → fill 96.903, ≈ -3.097%
    fill, pct = modeled_stop_exit(100.0, 97.0, 0.001)
    assert abs(fill - 96.903) < 1e-6
    assert abs(pct - (-3.097)) < 1e-3


def test_stop_fill_zero_slippage_is_stop():
    fill, pct = modeled_stop_exit(100.0, 97.0, 0.0)
    assert fill == 97.0
    assert abs(pct - (-3.0)) < 1e-9


def test_stop_fill_bounds_overshoot():
    # The real ALLO case: entry .4731, stop .458907 (-3%). Recorded loss was -23.8%
    # (overshoot). Modeled fill must be bounded near the -3% stop, not -23.8%.
    fill, pct = modeled_stop_exit(0.4731, 0.458907, 0.001)
    assert -3.5 < pct < -2.9


def test_stop_fill_preserves_profit_when_stop_above_entry():
    # trailing stop locked in above entry → still a WIN
    fill, pct = modeled_stop_exit(100.0, 105.0, 0.001)
    assert fill > 100.0 and pct > 0


@pytest.mark.parametrize("entry, stop, slippage", [
    (0, 97, 0.001), (100, 0, 0.001), (100, 97, -0.1), (100, 97, 1.0),
])
def test_stop_fill_rejects_invalid_inputs(entry, stop, slippage):
    with pytest.raises(ValueError):
        modeled_stop_exit(entry, stop, slippage)
