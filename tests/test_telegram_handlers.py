"""Production-path validation of the real Telegram command handlers.

RISK-1B left `PRODUCTION_PATH_RECOVERY_TESTS = PARTIAL` because the repository's
own `telegram/` directory shadows the `python-telegram-bot` distribution when
tests run from the repo root. Production does not have that problem: the image
does `COPY telegram/ ./`, so the module lands at `/app/main.py` with no
`/app/telegram/` directory, and `telegram` resolves to site-packages.

These tests therefore import the module the way production does -- as `main` --
and run inside a container built from the real Telegram image. Outside that
environment they skip.

Transport objects (Update/Context) are fakes, as allowed. The handler,
`@restricted`, argument parsing, and `record_recovery` are all the real
production code.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

main = pytest.importorskip(
    'main', reason='production-parity env only (module lives at /app/main.py)')
pytest.importorskip('telegram.ext', reason='python-telegram-bot not installed')

if not hasattr(main, 'cmd_recover_risk'):          # a different main.py
    pytest.skip('main.py is not the Telegram service', allow_module_level=True)

from shared.config import config                    # noqa: E402
from shared.risk_epoch import RISK_ADMISSION_LOCK_KEY  # noqa: E402

OWNER = '424242'
INTRUDER = '999999'
CLEAN_START = datetime(2026, 7, 20, tzinfo=timezone.utc)
FEE = 50.0 * 0.3 / 100.0
LOSS = -1.0 - FEE
WIN = 5.0


class Msg:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def update_from(chat_id):
    msg = Msg()
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_user=SimpleNamespace(id=chat_id, username='op'),
        message=msg,
    ), msg


def ctx(*args):
    return SimpleNamespace(args=list(args))


class FakeDB:
    DB_NOW = CLEAN_START + timedelta(days=30)

    def __init__(self, profits, open_positions=0, epoch=None, paused=False):
        self.profits = list(profits)
        self.open_positions = open_positions
        self.epoch = epoch
        self.paused = paused
        self.recovery_events = []
        self.locks_taken = []
        self.writes = []

    async def fetchval(self, sql, *args):
        if 'MAX(epoch_started_at)' in sql:
            return self.epoch
        if 'active_trades' in sql:
            return self.open_positions
        return 0

    async def fetch(self, sql, *args):
        if 'trade_results' in sql:
            start = args[0]
            return [{'profit_usdt': p} for ts, p in self._stamped() if ts >= start]
        return []

    async def fetchrow(self, sql, *args):
        if 'INSERT INTO risk_recovery_events' in sql:
            assert 'NOW()' in sql
            self.recovery_events.append(args)
            return {'id': len(self.recovery_events), 'epoch_started_at': self.DB_NOW}
        return None

    async def execute(self, sql, *args):
        if 'pg_advisory_xact_lock' in sql:
            self.locks_taken.append(args[0])
        else:
            self.writes.append(' '.join(sql.split())[:80])
        return 'OK'

    def _stamped(self):
        return [(CLEAN_START + timedelta(hours=i), p) for i, p in enumerate(self.profits)]

    def acquire(self):
        return _Acquire(self)

    def transaction(self):
        return _Acquire(self)


class _Acquire:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def wire(db, monkeypatch):
    monkeypatch.setattr(main, 'Database', db)
    monkeypatch.setattr('shared.risk_epoch.Database', db)
    monkeypatch.setattr(config, 'TELEGRAM_CHAT_ID', OWNER)
    monkeypatch.setattr(
        main, 'get_pause_state',
        AsyncMock(return_value=(db.paused,
                                'risk:loss_streak_halt' if db.paused else None)))


# ---------------------------------------------- /recover_risk, real handler

@pytest.mark.asyncio
async def test_case1_authorized_valid_recovery(monkeypatch):
    db = FakeDB([LOSS] * 7)
    wire(db, monkeypatch)
    update, msg = update_from(OWNER)

    await main.cmd_recover_risk(update, ctx('reviewed', 'nine', 'trades'))

    assert len(db.recovery_events) == 1, 'exactly one recovery event'
    actor, reason, streak = db.recovery_events[0]
    assert actor == OWNER, 'the acknowledging principal is persisted'
    assert reason == 'reviewed nine trades', 'arguments joined verbatim'
    assert streak == 7
    assert db.locks_taken == [RISK_ADMISSION_LOCK_KEY], 'serialised via the shared lock'
    assert 'تم رفع قاطع سلسلة الخسائر' in msg.replies[-1]


@pytest.mark.asyncio
async def test_case2_unauthorized_chat_cannot_recover(monkeypatch):
    """Exercises the real @restricted decorator."""
    db = FakeDB([LOSS] * 7)
    wire(db, monkeypatch)
    update, msg = update_from(INTRUDER)

    await main.cmd_recover_risk(update, ctx('let', 'me', 'in'))

    assert db.recovery_events == [], 'no recovery event'
    assert db.locks_taken == [], 'no database work at all'
    assert msg.replies == [], 'intruder gets no reply (existence not disclosed)'


@pytest.mark.asyncio
async def test_case2b_unset_chat_id_fails_closed(monkeypatch):
    db = FakeDB([LOSS] * 7)
    wire(db, monkeypatch)
    monkeypatch.setattr(config, 'TELEGRAM_CHAT_ID', '')
    update, msg = update_from(OWNER)

    await main.cmd_recover_risk(update, ctx('ack'))

    assert db.recovery_events == [] and msg.replies == []


@pytest.mark.asyncio
async def test_case3_missing_reason_rejected(monkeypatch):
    db = FakeDB([LOSS] * 7)
    wire(db, monkeypatch)
    update, msg = update_from(OWNER)

    await main.cmd_recover_risk(update, ctx())

    assert db.recovery_events == []
    assert 'يحتاج سبباً صريحاً' in msg.replies[-1]


@pytest.mark.asyncio
async def test_case3b_whitespace_only_reason_rejected(monkeypatch):
    db = FakeDB([LOSS] * 7)
    wire(db, monkeypatch)
    update, msg = update_from(OWNER)

    await main.cmd_recover_risk(update, ctx('   ', '  '))

    assert db.recovery_events == []


@pytest.mark.asyncio
async def test_case4_open_positions_block_recovery(monkeypatch):
    db = FakeDB([LOSS] * 7, open_positions=2)
    wire(db, monkeypatch)
    update, msg = update_from(OWNER)

    await main.cmd_recover_risk(update, ctx('ack'))

    assert db.recovery_events == []
    assert 'تعذّر رفع القاطع' in msg.replies[-1]


@pytest.mark.asyncio
async def test_case5_no_active_halt_creates_no_epoch(monkeypatch):
    db = FakeDB([LOSS] * 3)
    wire(db, monkeypatch)
    update, msg = update_from(OWNER)

    await main.cmd_recover_risk(update, ctx('ack'))

    assert db.recovery_events == [], 'no meaningless epoch'
    assert 'تعذّر رفع القاطع' in msg.replies[-1]


@pytest.mark.asyncio
async def test_case6_double_submit_creates_exactly_one_epoch(monkeypatch):
    db = FakeDB([LOSS] * 7)
    wire(db, monkeypatch)
    update, msg = update_from(OWNER)

    await main.cmd_recover_risk(update, ctx('ack'))
    db.epoch = FakeDB.DB_NOW                    # the first recovery now applies
    await main.cmd_recover_risk(update, ctx('ack', 'again'))

    assert len(db.recovery_events) == 1
    assert 'تعذّر رفع القاطع' in msg.replies[-1]


# --------------------------------------------------- /resume, real handler

@pytest.mark.asyncio
async def test_resume_does_not_recover_and_warns(monkeypatch):
    db = FakeDB([LOSS] * 7, paused=True)
    wire(db, monkeypatch)
    update, msg = update_from(OWNER)

    await main.cmd_resume(update, ctx())

    assert db.recovery_events == [], '/resume must never create a recovery epoch'
    assert db.epoch is None, 'the epoch must be untouched'
    assert not any('trade_results' in w for w in db.writes), 'history untouched'
    reply = msg.replies[-1]
    assert 'تم رفع الإيقاف الإداري' in reply
    assert 'ما زال نشطاً' in reply, 'must not imply the system can trade'
    assert '/recover_risk' in reply, 'must name the required next step'


@pytest.mark.asyncio
async def test_resume_reports_normally_when_no_halt(monkeypatch):
    db = FakeDB([WIN], paused=True)
    wire(db, monkeypatch)
    update, msg = update_from(OWNER)

    await main.cmd_resume(update, ctx())

    assert 'تم استئناف البحث' in msg.replies[-1]


# --------------------------------------------------- /status, real handler

@pytest.mark.asyncio
@pytest.mark.parametrize('profits,halted,needs_recovery', [
    ([LOSS] * 7, True, True),
    ([LOSS] * 6, False, False),
    ([LOSS], False, False),
    ([LOSS] * 7 + [WIN], False, False),
])
async def test_status_reports_the_effective_streak(monkeypatch, profits, halted,
                                                   needs_recovery):
    from shared.risk_epoch import loss_streak_state
    db = FakeDB(list(profits))
    wire(db, monkeypatch)
    update, msg = update_from(OWNER)

    await main.cmd_status(update, ctx())
    reply = msg.replies[-1]
    state = await loss_streak_state()

    assert state.halt_active is halted
    if halted:
        assert 'قاطع سلسلة الخسائر' in reply
        assert f'{state.consecutive_losses}/{state.halt_threshold}' in reply, \
            'the displayed streak must be the effective one'
        assert 'يبحث ويراقب' not in reply, 'a halted system must not read as healthy'
        if needs_recovery:
            assert '/recover_risk' in reply
    else:
        assert 'قاطع سلسلة الخسائر' not in reply


@pytest.mark.asyncio
async def test_status_after_recovery_shows_healthy(monkeypatch):
    db = FakeDB([LOSS] * 7, epoch=FakeDB.DB_NOW)   # acknowledged epoch in effect
    wire(db, monkeypatch)
    update, msg = update_from(OWNER)

    await main.cmd_status(update, ctx())

    assert 'يبحث ويراقب' in msg.replies[-1]


# ------------------------------------------------------ handler registration

def test_handlers_are_registered_to_the_intended_functions():
    """Structural check against the real module: a correct but unregistered
    handler would be unreachable in production."""
    import inspect
    source = inspect.getsource(main)
    for command, func in (('recover_risk', 'cmd_recover_risk'),
                          ('resume', 'cmd_resume'),
                          ('status', 'cmd_status'),
                          ('pause', 'cmd_pause')):
        assert f'CommandHandler("{command}",' in source, f'/{command} not registered'
        line = next(l for l in source.splitlines()
                    if f'CommandHandler("{command}",' in l)
        assert func in line, f'/{command} registered to the wrong handler: {line.strip()}'
    assert source.count('CommandHandler("recover_risk"') == 1, 'duplicate registration'


def test_recover_risk_is_authorization_wrapped():
    """The handler must be behind @restricted, not merely defined."""
    assert main.cmd_recover_risk.__wrapped__ is not None, \
        'cmd_recover_risk is not wrapped by @restricted'
    assert main.cmd_resume.__wrapped__ is not None
    assert main.cmd_status.__wrapped__ is not None
