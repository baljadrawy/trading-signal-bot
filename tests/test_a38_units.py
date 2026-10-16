"""A38 unit tests: delivery failure policy, economic labels, entry fill models, dead-letter watch.
Deterministic, no network, no database."""
import sys; sys.path.insert(0, '.')
import asyncio
import datetime as dt
import itertools
import random

import pytest

from shared import delivery_policy as dp
from shared import fees
from shared import outbox_watch
from shared.config import config
from shared.entry_execution import (
    decide_long_entry, resolve_entry_fill, order_kind_after, EntryDecision,
    LEGACY_FILL_MODEL, RESTING_LIMIT_FILL_MODEL)
from shared.risk_epoch import tail_loss_streak


# ---------------------------------------------------------------- delivery policy ----------------
def _exc(name, base=Exception, **attrs):
    cls = type(name, (base,), {})
    e = cls('x')
    for k, v in attrs.items():
        setattr(e, k, v)
    return e


def test_telegram_errors_are_classified_by_name_permanent_first():
    network = type('NetworkError', (Exception,), {})
    bad = type('BadRequest', (network,), {})('chat not found')       # PTB: BadRequest < NetworkError
    timed = type('TimedOut', (network,), {})('t')
    assert dp.classify_failure(bad) == (dp.PERMANENT, None)
    assert dp.classify_failure(_exc('Forbidden', network)) == (dp.PERMANENT, None)
    assert dp.classify_failure(timed) == (dp.TRANSIENT, None)
    assert dp.classify_failure(network('n')) == (dp.TRANSIENT, None)
    assert dp.classify_failure(_exc('RetryAfter', network, retry_after=7)) == (dp.RATE_LIMITED, 7.0)
    assert dp.classify_failure(
        _exc('RetryAfter', network, retry_after=dt.timedelta(seconds=3))) == (dp.RATE_LIMITED, 3.0)


def test_network_and_database_connectivity_are_transient_defects_are_permanent():
    assert dp.classify_failure(ConnectionError('db'))[0] == dp.TRANSIENT
    assert dp.classify_failure(asyncio.TimeoutError())[0] == dp.TRANSIENT
    assert dp.classify_failure(OSError('net'))[0] == dp.TRANSIENT
    for e in (ValueError('v'), KeyError('k'), RuntimeError('r'), AssertionError('a')):
        assert dp.classify_failure(e)[0] == dp.PERMANENT


def test_backoff_and_deadline_bound():
    assert [dp.backoff_seconds(n) for n in range(7)] == [60, 120, 240, 480, 600, 600, 600]
    assert dp.backoff_seconds(None) == 60
    assert dp.bounded_delay(600, 30) == 31            # never past the deadline (+1 s to cross it)
    assert dp.bounded_delay(60, 3600) == 60
    assert dp.bounded_delay(60, -5) == 1              # past the deadline: re-examine now
    assert dp.bounded_delay(0, None) == 1


# ---------------------------------------------------------------- economic label -----------------
def test_gross_positive_net_negative_is_an_economic_loss(monkeypatch):
    monkeypatch.setattr(config, 'TRADE_AMOUNT_USDT', 50.0)
    monkeypatch.setattr(config, 'FEE_ROUNDTRIP_PCT', 0.3)
    e = fees.economic_close(0.10)
    assert e == {'cost_usdt': 0.15, 'net_profit_usdt': -0.05, 'economic_result': 'LOSS',
                 'label_policy': 'net_after_modeled_cost_v1'}
    assert fees.economic_close(0.15)['economic_result'] == 'BREAKEVEN'
    assert fees.economic_close(0.15004)['economic_result'] == 'BREAKEVEN'   # stored gross is 4 dp
    assert fees.economic_close(0.1501)['economic_result'] == 'WIN'
    assert fees.economic_close(-0.2)['economic_result'] == 'LOSS'


def test_economic_loss_is_exactly_the_risk_control_loss(monkeypatch):
    """Economic LOSS (net < 0) == a loss that extends tail_loss_streak; BREAKEVEN never does."""
    monkeypatch.setattr(config, 'TRADE_AMOUNT_USDT', 50.0)
    monkeypatch.setattr(config, 'FEE_ROUNDTRIP_PCT', 0.3)
    rng = random.Random(3838)
    grosses = [round(rng.uniform(-1, 1), 4) for _ in range(4000)] + [0.15, 0.1499, 0.1501, 0.0]
    cost = fees.fee_usdt()
    for g in grosses:
        risk_loss = tail_loss_streak([round(g, 4) - cost]) == 1   # how the risk guard counts it
        assert (fees.economic_close(g)['economic_result'] == 'LOSS') == risk_loss, g


def test_legacy_gross_label_is_not_redefined():
    """`result` keeps WIN when gross > 0 (strategy cooldown + history rely on it)."""
    src = open('trade_tracker/main.py', encoding='utf-8').read()
    assert "'WIN' if profit_usdt > 0 else 'LOSS', reason," in src
    assert "econ = economic_close(profit_usdt)" in src


# ---------------------------------------------------------------- fill models --------------------
def _decision(planned, price, stop, inv=None, tt='reversion'):
    return decide_long_entry(trade_type=tt, planned_entry=planned, current_price=price,
                             stop_loss=stop, invalidation_price=inv)


def _fill(model, kind, planned, price, stop, inv=None, tt='reversion'):
    d = _decision(planned, price, stop, inv, tt)
    return resolve_entry_fill(model=model, decision=d, previous_kind=kind, planned_entry=planned,
                              current_price=price, stop_loss=stop, invalidation_price=inv)


def test_legacy_model_is_exactly_the_pre_a38_behaviour():
    """Exhaustive grid: legacy fill == the old code path (market -> fill at the observed price,
    limit_wait -> wait, reject -> reject), whatever the order history."""
    prices = [0, 96, 97, 97.5, 98, 99.5, 100, 100.5, 103]
    for planned, price, stop, inv, tt, kind in itertools.product(
            [100.0], prices, [97.0], [None, 98.0, 100.0, 101.0], ['momentum', 'reversion', 'x'],
            [None, 'marketable', 'resting']):
        d = _decision(planned, price, stop, inv, tt)
        f = resolve_entry_fill(model=LEGACY_FILL_MODEL, decision=d, previous_kind=kind,
                               planned_entry=planned, current_price=price, stop_loss=stop,
                               invalidation_price=inv)
        expected = {'market': 'fill', 'limit_wait': 'wait', 'reject': 'reject'}[d.action]
        assert f.action == expected
        if f.action == 'fill':
            assert f.price == price


def test_marketable_arrival_keeps_genuine_price_improvement():
    f = _fill(RESTING_LIMIT_FILL_MODEL, None, 100.0, 99.5, 97.0)
    assert (f.action, f.price, f.basis, f.order_kind) == ('fill', 99.5, 'marketable_observed',
                                                          'marketable')


def test_resting_order_fills_at_its_limit_on_trade_through_only():
    f = _fill(RESTING_LIMIT_FILL_MODEL, 'resting', 100.0, 99.0, 97.0)
    assert (f.action, f.price, f.basis) == ('fill', 100.0, 'resting_trade_through')
    touch = _fill(RESTING_LIMIT_FILL_MODEL, 'resting', 100.0, 100.0, 97.0)
    assert (touch.action, touch.basis) == ('wait', 'resting_touch_unfilled')   # queue unknown
    above = _fill(RESTING_LIMIT_FILL_MODEL, 'resting', 100.0, 100.5, 97.0)
    assert above.action == 'wait'


def test_trade_through_below_invalidation_is_filled_not_dropped():
    """Adverse selection: the market crossed the limit before reaching invalidation, so a real
    resting order filled. Legacy rejects it (dropping the worst entries); v1 fills at the limit."""
    legacy = _fill(LEGACY_FILL_MODEL, 'resting', 100.0, 96.0, 97.0, inv=98.0)
    v1 = _fill(RESTING_LIMIT_FILL_MODEL, 'resting', 100.0, 96.0, 97.0, inv=98.0)
    assert legacy.action == 'reject'
    assert (v1.action, v1.price, v1.basis) == ('fill', 100.0, 'resting_trade_through')


def test_invalidation_at_or_above_limit_cancels_before_fill():
    f = _fill(RESTING_LIMIT_FILL_MODEL, 'resting', 100.0, 99.0, 97.0, inv=101.0)
    assert (f.action, f.basis) == ('reject', 'cancelled_invalidated_before_limit')
    w = _fill(RESTING_LIMIT_FILL_MODEL, 'resting', 100.0, 102.0, 97.0, inv=101.0)
    assert w.action == 'wait'


def test_invalid_prices_and_types_still_reject_and_unknown_model_raises():
    assert _fill(RESTING_LIMIT_FILL_MODEL, 'resting', 100.0, 0, 97.0).action == 'reject'
    assert _fill(RESTING_LIMIT_FILL_MODEL, 'resting', 100.0, 99.0, 97.0, tt='swing').action == 'reject'
    with pytest.raises(ValueError):
        _fill('optimistic_v9', None, 100.0, 99.0, 97.0)


def test_order_kind_is_monotone():
    wait = EntryDecision('limit_wait', 'x', 100.0)
    market = EntryDecision('market', 'x', 99.0)
    assert order_kind_after(None, market) == 'marketable'
    assert order_kind_after(None, wait) == 'resting'
    assert order_kind_after('marketable', wait) == 'resting'
    assert order_kind_after('resting', market) == 'resting'


# ---------------------------------------------------------------- dead-letter watch --------------
def _rows(*specs):
    return [{'id': i, 'event_type': et, 'aggregate_type': 'signal', 'aggregate_id': i * 10,
             'attempts': 8, 'deferrals': 0, 'last_error': f'err{i}', 'created_at': t,
             'processed_at': t} for i, et, t in specs]


def test_dead_letter_watch_alerts_new_letters_once_and_never_history(monkeypatch):
    boot = dt.datetime(2026, 10, 14, 12, 0)
    store = _rows((1, 'signal.delivered', boot - dt.timedelta(hours=1)))       # history
    calls, alerts = [], []

    async def since(types, after, limit=50):
        calls.append(after)
        return [r for r in store if (r['processed_at'], r['id']) > after][:limit]
    monkeypatch.setattr(outbox_watch, 'dead_letters_since', since)
    now = [boot.replace(tzinfo=dt.timezone.utc)]

    async def alert(text):
        alerts.append(text)
    w = outbox_watch.DeadLetterWatch('t', ['signal.delivered'], alert=alert, clock=lambda: now[0])
    assert asyncio.run(w.poll()) == [] and alerts == []
    assert w.snapshot()['before_boot_24h'] == 1
    store += _rows((2, 'signal.delivered', boot + dt.timedelta(minutes=5)),
                   (3, 'signal.delivered', boot + dt.timedelta(minutes=6)))
    assert asyncio.run(w.poll()) == []                      # rate-limited by interval
    now[0] += dt.timedelta(seconds=61)
    assert [r['id'] for r in asyncio.run(w.poll())] == [2, 3]
    assert len(alerts) == 1 and '2 dead letter(s)' in alerts[0]
    now[0] += dt.timedelta(seconds=61)
    assert asyncio.run(w.poll()) == [] and len(alerts) == 1  # no re-alert
    assert w.snapshot()['new_since_boot'] == 2 and w.snapshot()['last']['id'] == 3


def test_dead_letter_watch_never_raises(monkeypatch):
    async def boom(*a, **k):
        raise ConnectionError('db down')
    monkeypatch.setattr(outbox_watch, 'dead_letters_since', boom)

    async def bad_alert(text):
        raise RuntimeError('telegram down')
    w = outbox_watch.DeadLetterWatch('t', ['x'], alert=bad_alert)
    assert asyncio.run(w.poll(force=True)) == [] and w.errors == 1
