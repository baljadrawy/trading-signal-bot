from unittest.mock import AsyncMock, patch

import pytest

from shared.trading_state import (
    RISK_STATE_INCONSISTENT, RISK_STATE_MISSING, get_pause_state)


def decision(paused, reason, date_invalid=False):
    return {'is_trading_paused': paused, 'pause_reason': reason,
            'date_invalid': date_invalid}


async def state_for(row):
    with patch('shared.trading_state.Database.fetchrow',
               new=AsyncMock(return_value=row)):
        return await get_pause_state()


@pytest.mark.asyncio
async def test_pause_survives_daily_rollover():
    assert await state_for(decision(True, 'risk:loss_streak_halt')) == \
        (True, 'risk:loss_streak_halt')


@pytest.mark.asyncio
async def test_explicit_resume_clears_prior_pause():
    assert await state_for(decision(False, 'manual_resume')) == (False, None)


@pytest.mark.asyncio
async def test_manual_pause_is_preserved():
    assert await state_for(decision(True, 'manual_pause')) == (True, 'manual_pause')


@pytest.mark.asyncio
async def test_paused_row_without_reason_keeps_generic_reason():
    assert await state_for(decision(True, None)) == (True, 'trading_paused')


# ---- B3: absent or malformed state must never grant permission ----------------

@pytest.mark.asyncio
async def test_missing_decision_row_denies_trading():
    assert await state_for(None) == (True, RISK_STATE_MISSING)


@pytest.mark.asyncio
async def test_null_paused_flag_is_inconsistent_not_permission():
    # Before B3 `not None` read as "not paused" and granted trading.
    assert await state_for(decision(None, 'manual_resume')) == \
        (True, RISK_STATE_INCONSISTENT)


@pytest.mark.asyncio
async def test_paused_row_claiming_manual_resume_is_inconsistent():
    assert await state_for(decision(True, 'manual_resume')) == \
        (True, RISK_STATE_INCONSISTENT)


@pytest.mark.asyncio
async def test_undated_or_future_dated_resume_is_inconsistent():
    assert await state_for(decision(False, 'manual_resume', date_invalid=True)) == \
        (True, RISK_STATE_INCONSISTENT)


@pytest.mark.asyncio
async def test_unpaused_row_without_explicit_resume_is_inconsistent():
    assert await state_for(decision(False, None)) == (True, RISK_STATE_INCONSISTENT)


@pytest.mark.asyncio
async def test_fail_closed_reasons_are_distinct_from_existing_halts():
    existing = {'manual_pause', 'manual_resume', 'trading_paused'}
    for reason in (RISK_STATE_MISSING, RISK_STATE_INCONSISTENT):
        assert reason not in existing and not reason.startswith('risk:')


@pytest.mark.asyncio
async def test_query_failure_propagates_instead_of_granting_trading():
    with patch('shared.trading_state.Database.fetchrow',
               new=AsyncMock(side_effect=RuntimeError('query failed'))):
        with pytest.raises(RuntimeError):
            await get_pause_state()


@pytest.mark.asyncio
async def test_connection_failure_propagates_instead_of_granting_trading():
    with patch('shared.trading_state.Database.fetchrow',
               new=AsyncMock(side_effect=ConnectionRefusedError('db down'))):
        with pytest.raises(ConnectionRefusedError):
            await get_pause_state()
