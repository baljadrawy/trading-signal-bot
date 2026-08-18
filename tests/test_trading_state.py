from unittest.mock import AsyncMock, patch

import pytest

from shared.trading_state import get_pause_state


@pytest.mark.asyncio
async def test_pause_survives_daily_rollover():
    with patch(
        'shared.trading_state.Database.fetchrow',
        new=AsyncMock(return_value={
            'is_trading_paused': True,
            'pause_reason': 'risk:loss_streak_halt',
        }),
    ):
        assert await get_pause_state() == (True, 'risk:loss_streak_halt')


@pytest.mark.asyncio
async def test_explicit_resume_clears_prior_pause():
    with patch(
        'shared.trading_state.Database.fetchrow',
        new=AsyncMock(return_value={
            'is_trading_paused': False,
            'pause_reason': 'manual_resume',
        }),
    ):
        assert await get_pause_state() == (False, None)
