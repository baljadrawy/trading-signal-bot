"""B3 through the real callers: scanner emission, tracker admission, and the
existing-position path. Only the database facade is faked; get_pause_state,
BinanceScanner.scan, assess_new_trade_risk and record_risk_decision are the
production functions.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

import shared.trading_state as trading_state
from shared.trading_state import RISK_STATE_INCONSISTENT, RISK_STATE_MISSING

try:
    import trade_tracker.main as tracker
except ImportError:                                    # pragma: no cover
    import importlib
    tracker = importlib.import_module('main')
    if not hasattr(tracker, 'assess_new_trade_risk'):
        pytest.skip('main.py is not the trade_tracker service',
                    allow_module_level=True)

try:
    from scanner.scanner_logic import BinanceScanner
except ImportError:                                    # pragma: no cover
    from scanner_logic import BinanceScanner

CLEAN_START = datetime(2026, 7, 20, tzinfo=timezone.utc)
WIN = 5.0


class PauseRows:
    """What the risk_management decision query returns."""

    def __init__(self, row):
        self.row = row

    async def fetchrow(self, sql, *args):
        assert 'risk_management' in sql
        return self.row


MISSING = PauseRows(None)
INCONSISTENT = PauseRows({'is_trading_paused': None, 'pause_reason': 'manual_resume',
                          'date_invalid': False})
AUTHORIZED = PauseRows({'is_trading_paused': False, 'pause_reason': 'manual_resume',
                        'date_invalid': False})


class TrackerDB:
    """Tracker-side facade: winning history, no epoch, no open positions."""

    def __init__(self):
        self.writes = []

    async def fetchval(self, sql, *args):
        if 'INSERT INTO risk_management' in sql:
            self.writes.append(('risk_management', args))
            return 1
        return None if 'MAX(epoch_started_at)' in sql else 0

    async def fetch(self, sql, *args):
        if 'trade_results' in sql:
            return [{'profit_usdt': WIN, 'result': 'WIN',
                     'exit_time': CLEAN_START + timedelta(hours=i)} for i in range(3)]
        return []

    async def fetchrow(self, sql, *args):
        return None                    # no prior pause row for record_risk_decision

    async def execute(self, sql, *args):
        self.writes.append(('execute', sql))
        return 'OK'

    def acquire(self):
        return _Ctx(self)

    def transaction(self):
        return _Ctx(self)


class _Ctx:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def wire_tracker(monkeypatch, pause_rows):
    db = TrackerDB()
    monkeypatch.setattr(tracker, 'Database', db)
    monkeypatch.setattr('shared.risk_epoch.Database', db)
    monkeypatch.setattr(trading_state, 'Database', pause_rows)
    monkeypatch.setattr(tracker, 'get_current_price', AsyncMock(return_value=100.0))
    return db


# ---- scanner: no candidate emission ---------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize('rows,reason', [(MISSING, RISK_STATE_MISSING),
                                         (INCONSISTENT, RISK_STATE_INCONSISTENT)])
async def test_scanner_emits_nothing_when_state_is_not_explicit(monkeypatch, rows, reason):
    monkeypatch.setattr(trading_state, 'Database', rows)
    client = AsyncMock()
    scanner = BinanceScanner(client)
    scanner._update_btc_trend = AsyncMock()
    scanner._save_candidates = AsyncMock()

    assert await scanner.scan() == []
    assert await scanner._get_pause_reason() == reason
    scanner._update_btc_trend.assert_not_awaited()
    scanner._save_candidates.assert_not_awaited()
    assert not client.mock_calls, 'no market data should even be requested'


@pytest.mark.asyncio
async def test_scanner_startup_with_database_down_emits_nothing(monkeypatch):
    class Down:
        async def fetchrow(self, *a):
            raise ConnectionRefusedError('db down')

    monkeypatch.setattr(trading_state, 'Database', Down())
    scanner = BinanceScanner(AsyncMock())
    scanner._save_candidates = AsyncMock()
    with pytest.raises(ConnectionRefusedError):
        await scanner.scan()
    scanner._save_candidates.assert_not_awaited()


# ---- tracker: no new trade --------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize('rows,reason', [(MISSING, RISK_STATE_MISSING),
                                         (INCONSISTENT, RISK_STATE_INCONSISTENT)])
async def test_tracker_admission_denied_when_state_is_not_explicit(monkeypatch, rows, reason):
    wire_tracker(monkeypatch, rows)
    decision = await tracker.assess_new_trade_risk('BTCUSDT')
    assert not decision.allowed
    assert decision.reason == reason


@pytest.mark.asyncio
async def test_tracker_admission_unchanged_for_explicit_authorization(monkeypatch):
    wire_tracker(monkeypatch, AUTHORIZED)
    decision = await tracker.assess_new_trade_risk('BTCUSDT')
    assert decision.allowed, decision.reason


@pytest.mark.asyncio
async def test_recording_a_fail_closed_decision_never_writes_an_authorization(monkeypatch):
    db = wire_tracker(monkeypatch, MISSING)
    decision = await tracker.assess_new_trade_risk('BTCUSDT')
    await tracker.record_risk_decision(decision)

    rows = [args for kind, args in db.writes if kind == 'risk_management']
    assert rows, 'the decision is still recorded for telemetry'
    for args in rows:
        _daily, _streak, paused, reason = args
        assert paused is False and reason is None, \
            'must not persist manual_resume or any row the pause query would select'
    assert not any('outbox_events' in str(w) for w in db.writes), \
        'a state fault is not a risk.halted transition'


@pytest.mark.asyncio
async def test_tracker_database_failure_denies_by_exception(monkeypatch):
    class Down:
        async def fetchrow(self, *a):
            raise ConnectionRefusedError('db down')

    wire_tracker(monkeypatch, Down())
    with pytest.raises(ConnectionRefusedError):
        await tracker.assess_new_trade_risk('BTCUSDT')


# ---- existing positions keep their own contract ------------------------------------

@pytest.mark.asyncio
async def test_open_positions_are_still_managed_while_state_is_missing(monkeypatch):
    trade = {'id': 1, 'symbol': 'BTCUSDT', 'entry_price': 100.0, 'status': 'open',
             'highest_target_hit': 0, 'stop_invalidation': None, 'timeframe': '4h'}

    class OpenTrades:
        async def fetch(self, sql, *args):
            return [trade] if 'active_trades' in sql else []

    monkeypatch.setattr(tracker, 'Database', OpenTrades())
    monkeypatch.setattr(trading_state, 'Database', MISSING)
    monkeypatch.setattr(tracker, 'get_current_price', AsyncMock(return_value=101.0))
    gate = AsyncMock(side_effect=AssertionError('open positions must not consult pause state'))
    monkeypatch.setattr(tracker, 'get_pause_state', gate)
    manage = AsyncMock()
    monkeypatch.setattr(tracker, 'evaluate_trade_safely', manage)

    await tracker.track_open_trades()

    manage.assert_awaited_once()
    assert manage.await_args.args[0]['id'] == 1
    gate.assert_not_awaited()
