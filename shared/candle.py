"""Candle-period helpers — single source of truth for timeframe→seconds.
Used by the duplicate guard (trade_tracker), the validation oracle, and tests,
so the SQL cooldown and the Python re-analysis can never drift apart.
"""

CANDLE_SECONDS = {
    '15m': 900,
    '4h': 14400,
    '1d': 86400,
}
DEFAULT_CANDLE_SECONDS = 86400  # unknown timeframe → treat as daily (most conservative)


def candle_seconds(timeframe: str) -> int:
    """Seconds in one candle for the given timeframe."""
    return CANDLE_SECONDS.get(timeframe, DEFAULT_CANDLE_SECONDS)


def is_within_candle(now_ts: float, opened_ts: float, timeframe: str) -> bool:
    """True if opened_ts falls within the last candle period relative to now_ts
    (a rolling cooldown). Used to collapse re-fired identical setups to one position."""
    return (now_ts - opened_ts) < candle_seconds(timeframe)


def candle_interval_case_sql(column: str) -> str:
    """Postgres CASE expression mapping `column` (a timeframe) to an INTERVAL,
    generated from CANDLE_SECONDS so SQL and Python never drift."""
    whens = "\n".join(
        f"            WHEN '{tf}' THEN INTERVAL '{secs} seconds'"
        for tf, secs in CANDLE_SECONDS.items()
    )
    return (
        "CASE " + column + "\n" + whens + "\n"
        f"            ELSE INTERVAL '{DEFAULT_CANDLE_SECONDS} seconds'\n"
        "        END"
    )
