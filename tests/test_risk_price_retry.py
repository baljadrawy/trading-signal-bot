"""Technical-halt prevention option: bounded retry of the risk-evaluation price fetch.

The 2026-10-21 halt: one REST price fetch timed out inside assess_new_trade_risk ->
NaN -> invalid_risk_state -> sticky pause. RISK_PRICE_FETCH_RETRIES (default 0 = the
exact current behaviour) adds fresh attempts for that fetch only; persistent failure still
fails closed. No database, no network: Database and get_current_price are faked.
"""
import inspect
import os
from unittest.mock import AsyncMock

import pytest

from shared.config import Config, config

try:
    import trade_tracker.main as tracker
except ImportError:                                    # pragma: no cover
    import importlib
    tracker = importlib.import_module('main')
    if not hasattr(tracker, 'assess_new_trade_risk'):
        pytest.skip('main.py is not the trade_tracker service', allow_module_level=True)

OPEN = [{'symbol': 'ETHUSDT', 'entry_price': 100.0, 'trade_type': 'momentum', 'regime': 'flat'}]


class _DB:
    def __init__(self):
        self.writes = []

    async def fetch(self, sql, *args):
        return list(OPEN) if 'active_trades' in sql else []

    async def fetchval(self, sql, *args):
        if 'INSERT INTO risk_management' in sql:
            self.writes.append(args)
            return 11
        return None

    async def fetchrow(self, sql, *args):
        return None

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


def wire(monkeypatch, retries, prices, mode='enforce'):
    """prices: successive get_current_price results (None = failed fetch)."""
    db = _DB()
    if retries is not None:
        monkeypatch.setattr(config, 'RISK_PRICE_FETCH_RETRIES', retries)
    monkeypatch.setattr(config, 'PAPER_TRADING', True)
    monkeypatch.setattr(config, 'PAPER_ECONOMIC_HALT_MODE', mode)
    monkeypatch.setattr(config, 'RISK_CANARY_MAX_OPEN_TRADES', 2)     # runtime value
    monkeypatch.setattr(tracker, 'Database', db)
    monkeypatch.setattr('shared.risk_epoch.Database', db)
    monkeypatch.setattr(tracker, 'get_pause_state', AsyncMock(return_value=(False, None)))
    fetch = AsyncMock(side_effect=list(prices))
    monkeypatch.setattr(tracker, 'get_current_price', fetch)
    sleep = AsyncMock()
    monkeypatch.setattr(tracker.asyncio, 'sleep', sleep)
    return db, fetch, sleep


@pytest.mark.skipif('RISK_PRICE_FETCH_RETRIES' in os.environ, reason='env overrides default')
def test_default_is_off():
    assert Config.RISK_PRICE_FETCH_RETRIES == 0 and config.RISK_PRICE_FETCH_RETRIES == 0
    assert Config.RISK_PRICE_FETCH_BACKOFF_SECONDS == 0.5


@pytest.mark.asyncio
@pytest.mark.parametrize('prices,allowed', [([101.0], True), ([None], False)])
async def test_default_is_exactly_one_attempt(monkeypatch, prices, allowed):
    _db, fetch, sleep = wire(monkeypatch, None, prices)
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert fetch.await_count == 1 and sleep.await_count == 0
    assert d.allowed is allowed
    if not allowed:
        assert d.reason == 'invalid_risk_state'


@pytest.mark.asyncio
@pytest.mark.parametrize('prices', [[None, 101.0], [None, None, 101.0]])
async def test_retries_recover_from_transient_failures(monkeypatch, prices):
    _db, fetch, sleep = wire(monkeypatch, 2, prices)
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert d.allowed and d.reason == 'within_limits'
    assert fetch.await_count == len(prices)
    assert [c.args[0] for c in sleep.await_args_list] == [0.5, 1.0][:len(prices) - 1]


@pytest.mark.asyncio
async def test_success_first_time_does_not_retry(monkeypatch):
    _db, fetch, sleep = wire(monkeypatch, 2, [101.0])
    assert (await tracker.assess_new_trade_risk('BTCUSDT')).allowed
    assert fetch.await_count == 1 and sleep.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['enforce', 'observe'])
async def test_persistent_failure_still_fails_closed(monkeypatch, mode):
    db, fetch, _sleep = wire(monkeypatch, 2, [None, None, None], mode=mode)
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert fetch.await_count == 3
    assert not d.allowed and d.reason == 'invalid_risk_state'
    await tracker.record_risk_decision(d)
    assert db.writes[0][2:] == (True, 'risk:invalid_risk_state')      # pause persisted


@pytest.mark.asyncio
@pytest.mark.parametrize('retries,attempts', [(99, 4), (-1, 1), ('junk', 1)])
async def test_retries_are_bounded(monkeypatch, retries, attempts):
    _db, fetch, _sleep = wire(monkeypatch, retries, [None] * 10)
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert fetch.await_count == attempts and d.reason == 'invalid_risk_state'


def test_retry_applies_to_the_risk_evaluation_fetch_only():
    src = inspect.getsource(tracker)
    assert src.count('await _risk_price(') == 1
    assert 'await _risk_price(' in inspect.getsource(tracker.assess_new_trade_risk)
    assert 'get_current_price' not in inspect.getsource(tracker.assess_new_trade_risk)
    # Other price consumers (tracking, fills, blacklist closes) keep the single fetch.
    for fn in (tracker.track_open_trades, tracker.close_blacklisted_trades):
        assert '_risk_price' not in inspect.getsource(fn)
