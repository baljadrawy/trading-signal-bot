"""A49: economic read labels must not turn nonfinite historical P&L into BREAKEVEN."""
import pytest

from shared.fees import economic_result_sql


@pytest.mark.parametrize("gross,cost,expected", [
    ("1.00", "0.10", "WIN"),
    ("-1.00", "0.10", "LOSS"),
    ("0.10", "0.10", "BREAKEVEN"),
    ("NaN", "0.10", None),
    ("Infinity", "0.10", None),
    ("-Infinity", "0.10", None),
    (None, "0.10", None),
])
@pytest.mark.asyncio
async def test_economic_sql_nonfinite_postgres(gross, cost, expected):
    asyncpg = pytest.importorskip("asyncpg")
    import os
    dsn = os.getenv("RISK_TEST_DSN")
    if not dsn:
        pytest.skip("RISK_TEST_DSN is required for PostgreSQL semantics")
    conn = await asyncpg.connect(dsn)
    try:
        sql = economic_result_sql("$2::numeric")
        result = await conn.fetchval(
            f"SELECT {sql} FROM (SELECT $1::numeric AS profit_usdt, "
            f"NULL::text AS economic_result) AS trade_results", gross, cost)
        assert result == expected
    finally:
        await conn.close()


def test_economic_sql_retains_existing_label():
    sql = economic_result_sql("$1::numeric")
    assert "COALESCE(economic_result" in sql
    assert "'BREAKEVEN'" in sql
    assert "NaN" in sql
