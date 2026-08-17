import pandas as pd
import pytest

from shared.ohlcv import closed_klines, prepare_ohlcv


def _row(open_ms, close_ms, o=100, h=102, low=99, close=101, volume=10):
    return [open_ms, o, h, low, close, volume, close_ms, 1000, 5, 4, 400, 0]


def test_closed_klines_uses_exchange_close_time_not_last_row_position():
    rows = [_row(0, 899_999), _row(900_000, 1_799_999)]
    assert closed_klines(rows, now_ms=2_000_000) == rows
    assert closed_klines(rows, now_ms=1_000_000) == rows[:1]


def test_prepare_ohlcv_is_utc_numeric_and_ordered():
    rows = [_row(900_000, 1_799_999), _row(0, 899_999)]
    df = prepare_ohlcv(rows, "15m", now_ms=2_000_000)
    assert str(df.index.tz) == "UTC"
    assert df.index.is_monotonic_increasing
    assert pd.api.types.is_numeric_dtype(df["close"])


@pytest.mark.parametrize("rows, message", [
    ([_row(0, 899_999), _row(1_800_000, 2_699_999)], "missing or irregular"),
    ([_row(0, 899_999), _row(0, 899_999)], "duplicate"),
    ([_row(0, 899_999, h=98)], "high is below"),
])
def test_prepare_ohlcv_rejects_unsafe_market_data(rows, message):
    with pytest.raises(ValueError, match=message):
        prepare_ohlcv(rows, "15m", now_ms=3_000_000)
