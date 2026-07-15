import sys; sys.path.insert(0, '.')
from shared.candle import (
    candle_seconds, is_within_candle, candle_interval_case_sql, CANDLE_SECONDS,
)


def test_candle_seconds_known():
    assert candle_seconds('15m') == 900
    assert candle_seconds('4h') == 14400
    assert candle_seconds('1d') == 86400


def test_candle_seconds_unknown_defaults_daily():
    assert candle_seconds('7d') == 86400


def test_is_within_candle_true_when_recent():
    # opened 100s ago on 15m (900s window) → still same candle period
    assert is_within_candle(1000.0, 900.0, '15m') is True


def test_is_within_candle_false_after_window():
    # opened 1000s ago on 15m (900s window) → past the candle period
    assert is_within_candle(2000.0, 1000.0, '15m') is False


def test_interval_case_sql_contains_all_seconds():
    sql = candle_interval_case_sql('s.timeframe')
    for tf, secs in CANDLE_SECONDS.items():
        assert f"WHEN '{tf}' THEN INTERVAL '{secs} seconds'" in sql
    assert sql.strip().startswith('CASE s.timeframe')
    assert sql.strip().endswith('END')
