"""B3 through the real Telegram service (production-parity layout only).

The module is imported as `main`, exactly as the image runs it; elsewhere this
file skips, like test_telegram_handlers.py. /resume and /pause run against a
disposable PostgreSQL so the real SQL writes the decision row that the real
get_pause_state then reads.
"""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

main = pytest.importorskip(
    'main', reason='production-parity env only (module lives at /app/main.py)')
pytest.importorskip('telegram.ext', reason='python-telegram-bot not installed')
if not hasattr(main, 'can_deliver_candidate'):
    pytest.skip('main.py is not the Telegram service', allow_module_level=True)

import shared.trading_state as trading_state                     # noqa: E402
from shared.config import config                                  # noqa: E402
from shared.trading_state import RISK_STATE_MISSING               # noqa: E402

DSN = os.getenv('RISK_TEST_DSN')
OWNER = '424242'


class HeartbeatDB:
    async def fetchrow(self, sql, *args):
        return {'metadata': {}}

    async def fetchval(self, sql, *args):
        raise AssertionError('capacity must not be consulted once state is missing')


@pytest.mark.asyncio
async def test_delivery_gate_refuses_when_state_is_missing(monkeypatch):
    class Missing:
        async def fetchrow(self, sql, *args):
            return None

    monkeypatch.setattr(trading_state, 'Database', Missing())
    monkeypatch.setattr(main, 'Database', HeartbeatDB())
    assert await main.can_deliver_candidate() == (False, RISK_STATE_MISSING)


@pytest.mark.asyncio
async def test_delivery_gate_refuses_when_database_is_down(monkeypatch):
    class Down:
        async def fetchrow(self, *a):
            raise ConnectionRefusedError('db down')

    monkeypatch.setattr(trading_state, 'Database', Down())
    monkeypatch.setattr(main, 'Database', HeartbeatDB())
    with pytest.raises(ConnectionRefusedError):
        await main.can_deliver_candidate()


# ---- the owner's explicit commands remain the only way out ----------------------

asyncpg = pytest.importorskip('asyncpg')


class Facade:
    def __init__(self, conn):
        self.conn = conn

    async def fetchrow(self, q, *a):
        return await self.conn.fetchrow(q, *a)

    async def execute(self, q, *a):
        return await self.conn.execute(q, *a)


class Msg:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def owner_update():
    return SimpleNamespace(effective_chat=SimpleNamespace(id=int(OWNER)),
                           effective_user=SimpleNamespace(username='owner', id=1),
                           message=Msg())


@pytest_asyncio.fixture
async def pg(monkeypatch):
    if not DSN:
        pytest.skip('RISK_TEST_DSN not set (disposable PostgreSQL required)')
    c = await asyncpg.connect(DSN)
    await c.execute("""CREATE TABLE IF NOT EXISTS risk_management (
        id SERIAL PRIMARY KEY, date DATE UNIQUE DEFAULT CURRENT_DATE,
        signals_sent INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0, consecutive_losses INTEGER DEFAULT 0,
        daily_pnl_percent DECIMAL(10,4) DEFAULT 0,
        is_trading_paused BOOLEAN DEFAULT false, pause_reason TEXT)""")
    await c.execute('TRUNCATE risk_management RESTART IDENTITY')
    facade = Facade(c)
    monkeypatch.setattr(trading_state, 'Database', facade)
    monkeypatch.setattr(main, 'Database', facade)
    monkeypatch.setattr(config, 'TELEGRAM_CHAT_ID', OWNER)
    monkeypatch.setattr(main, 'loss_streak_state', AsyncMock(
        return_value=SimpleNamespace(halt_active=False)))
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_resume_is_the_explicit_authorization_out_of_missing_state(pg):
    assert await trading_state.get_pause_state() == (True, RISK_STATE_MISSING)
    await main.cmd_resume(owner_update(), SimpleNamespace(args=[]))
    assert await trading_state.get_pause_state() == (False, None)


@pytest.mark.asyncio
async def test_pause_from_missing_state_records_a_real_manual_pause(pg):
    await main.cmd_pause(owner_update(), SimpleNamespace(args=[]))
    assert await trading_state.get_pause_state() == (True, 'manual_pause')
