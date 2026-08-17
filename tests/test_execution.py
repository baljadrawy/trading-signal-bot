import pytest

from shared.execution import rebase_long_bracket


def test_rebase_bracket_uses_fill_and_preserves_percentage_distances():
    result = rebase_long_bracket(100, 105, 102, 104, 106, 97)
    assert result == {
        "entry_price": 105.0, "target_1": 107.1, "target_2": 109.2,
        "target_3": 111.3, "stop_loss": 101.85,
    }
    assert result["target_1"] / result["entry_price"] == pytest.approx(1.02)
    assert result["stop_loss"] / result["entry_price"] == pytest.approx(0.97)


def test_rebase_bracket_rejects_invalid_prices_or_ordering():
    with pytest.raises(ValueError):
        rebase_long_bracket(0, 105, 102, 104, 106, 97)
    with pytest.raises(ValueError):
        rebase_long_bracket(100, 105, 99, 104, 106, 97)
