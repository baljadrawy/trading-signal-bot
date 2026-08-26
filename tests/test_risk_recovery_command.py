"""Production-path tests for the real admission path.

RISK-1A found that no test imported `trade_tracker.main.assess_new_trade_risk`,
so the real admission integration was evidenced only by code reading. These
tests import and drive the actual module.

The `/recover_risk` and `/resume` Telegram handlers are NOT covered here and
cannot be: the repository's own `telegram/` package directory shadows the
`python-telegram-bot` distribution, so `telegram.main` is importable only inside
its container (where the file is deployed as `/app/main.py`). Covering them
would require renaming the package or reshaping sys.path for test convenience --
architectural drift this pass is not authorised to make. The handler bodies
delegate every decision to `shared.risk_epoch`, which is covered directly by
tests/test_risk_epoch.py.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

# The deployed image flattens `trade_tracker/` into /app, so the module is
# importable as `main` there and as `trade_tracker.main` from the repo root.
# Resolving both lets this test run against the built release image too.
try:
    import trade_tracker.main as tracker
except ImportError:                                    # pragma: no cover
    import importlib
    tracker = importlib.import_module('main')
    if not hasattr(tracker, 'assess_new_trade_risk'):
        pytest.skip('main.py is not the trade_tracker service',
                    allow_module_level=True)

CLEAN_START = datetime(2026, 7, 20, tzinfo=timezone.utc)
FEE = 50.0 * 0.3 / 100.0
LOSS = -1.0 - FEE          # comfortably net-negative after the round-trip fee
WIN = 5.0


class RecoveryDB:
    """Stands in for the shared Database facade, recording every mutation."""

    DB_NOW = CLEAN_START + timedelta(days=30)

    def __init__(self, profits, open_positions=0, epoch=None):
        self.profits = list(profits)
        self.open_positions = open_positions
        self.epoch = epoch
        self.recovery_events = []
        self.locks_taken = []

    async def fetchval(self, sql, *args):
        if 'MAX(epoch_started_at)' in sql:
            return self.epoch
        if 'active_trades' in sql:
            return self.open_positions
        return 0

    async def fetch(self, sql, *args):
        if 'trade_results' in sql:
            start = args[0]
            return [{'profit_usdt': p, 'result': 'LOSS' if p < 0 else 'WIN',
                     'exit_time': ts}
                    for ts, p in self._stamped() if ts >= start]
        return []          # e.g. the open-positions query

    async def fetchrow(self, sql, *args):
        if 'INSERT INTO risk_recovery_events' in sql:
            assert 'NOW()' in sql, 'epoch must be database-generated'
            self.recovery_events.append(args)
            return {'id': len(self.recovery_events), 'epoch_started_at': self.DB_NOW}
        return None

    async def execute(self, sql, *args):
        if 'pg_advisory_xact_lock' in sql:
            self.locks_taken.append(args[0])
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


def wire_admission(db, monkeypatch):
    # Patch the resolved module object, not a dotted path, so this works under
    # both the repo layout and the flattened image layout.
    monkeypatch.setattr(tracker, 'Database', db)
    monkeypatch.setattr('shared.risk_epoch.Database', db)
    monkeypatch.setattr(tracker, 'get_pause_state',
                        AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(tracker, 'get_current_price',
                        AsyncMock(return_value=100.0))


@pytest.mark.asyncio
async def test_real_admission_path_reflects_the_recovery_epoch(monkeypatch):
    """`assess_new_trade_risk` must honour the epoch, then re-halt on 7 new losses."""
    db = RecoveryDB([LOSS] * 7)
    wire_admission(db, monkeypatch)

    halted = await tracker.assess_new_trade_risk('BTCUSDT')
    assert not halted.allowed and halted.reason == 'loss_streak_halt'

    # An acknowledged epoch moves the boundary past the losing tail.
    db.epoch = RecoveryDB.DB_NOW
    recovered = await tracker.assess_new_trade_risk('BTCUSDT')
    assert recovered.allowed, 'admission must reflect the new epoch'
    assert recovered.consecutive_losses == 0

    # Seven NEW post-epoch losses must re-halt the very same production path.
    db.profits = [LOSS] * 7
    db._stamped = lambda: [(RecoveryDB.DB_NOW + timedelta(hours=i + 1), p)
                           for i, p in enumerate(db.profits)]
    rehalted = await tracker.assess_new_trade_risk('BTCUSDT')
    assert not rehalted.allowed and rehalted.reason == 'loss_streak_halt', \
        'recovery must not permanently disable the breaker'


@pytest.mark.asyncio
async def test_natural_recovery_still_works_on_the_real_admission_path(monkeypatch):
    """A winning close clears the halt with no operator action at all."""
    db = RecoveryDB([LOSS] * 7 + [WIN])
    wire_admission(db, monkeypatch)

    decision = await tracker.assess_new_trade_risk('BTCUSDT')
    assert decision.allowed
    assert decision.consecutive_losses == 0
    assert db.recovery_events == [], 'natural recovery needs no recovery event'


@pytest.mark.asyncio
async def test_admission_path_and_telemetry_agree_on_the_real_module(monkeypatch):
    """Parity across the epoch lifecycle, both sides via production code."""
    from shared.risk_epoch import loss_streak_state

    for profits, epoch in (([LOSS] * 7, None),
                           ([LOSS] * 7, RecoveryDB.DB_NOW),
                           ([LOSS] * 6, None),
                           ([LOSS] * 7 + [WIN], None)):
        db = RecoveryDB(list(profits), epoch=epoch)
        wire_admission(db, monkeypatch)
        decision = await tracker.assess_new_trade_risk('BTCUSDT')
        state = await loss_streak_state()
        assert decision.consecutive_losses == state.consecutive_losses, (
            f'admission/telemetry disagree for profits={len(profits)} epoch={epoch}')
        assert (decision.reason == 'loss_streak_halt') == state.halt_active
