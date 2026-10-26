"""Paper observe mode: one `risk.observed` outbox notice per economic-state transition.

Owner contract section 3: economic observations are "recorded, alerted on and analyzed".
enforce (default) must issue no new statement and no new event. No database: the
tracker's Database facade is a stateful fake that implements the outbox's
UNIQUE(event_type, aggregate_type, aggregate_id) / ON CONFLICT DO NOTHING contract.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from shared.config import config
from shared.economic_halt_policy import (
    OBSERVED_OUTBOX_AGGREGATE, OBSERVED_OUTBOX_EVENT, evaluate_with_policy,
    observation_transition, observed_codes,
)
from shared.risk_management import RiskLimits, RiskSnapshot
from shared.telegram_messages import UNKNOWN_ECONOMIC_CODE, risk_observed_message

try:
    import trade_tracker.main as tracker
except ImportError:                                    # pragma: no cover
    import importlib
    tracker = importlib.import_module('main')
    if not hasattr(tracker, 'assess_new_trade_risk'):
        pytest.skip('main.py is not the trade_tracker service', allow_module_level=True)

CLEAN_START = datetime(2026, 7, 20, tzinfo=timezone.utc)
LOSS, WIN = -2.0, 5.0


class OutboxDB:
    """Database facade + connection stand-in with a real-shaped outbox table."""

    def __init__(self, profits):
        self.profits = list(profits)
        self.outbox = []                  # dicts: id, event_type, aggregate_type, aggregate_id, payload
        self.sql = []
        self._next_id = 100
        self.today = []                   # trade_results exit_time offsets for "today" (none)

    def _nextval(self):
        self._next_id += 1
        return self._next_id

    async def fetchval(self, sql, *args):
        self.sql.append(sql)
        if 'INSERT INTO risk_management' in sql:
            return 11
        if 'nextval' in sql:
            return self._nextval()
        if 'INSERT INTO outbox_events' in sql:
            event_type, aggregate_type, aggregate_id, payload = args
            if any((r['event_type'], r['aggregate_type'], r['aggregate_id'])
                   == (event_type, aggregate_type, aggregate_id) for r in self.outbox):
                return None                                     # ON CONFLICT DO NOTHING
            row = dict(id=self._nextval(), event_type=event_type, aggregate_type=aggregate_type,
                       aggregate_id=aggregate_id, payload=payload)     # jsonb arrives as str
            self.outbox.append(row)
            return row['id']
        if 'MAX(epoch_started_at)' in sql:
            return None
        return 0

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        if 'trade_results' in sql:
            return [dict(profit_usdt=pnl, result='LOSS' if pnl < 0 else 'WIN',
                         exit_time=CLEAN_START + timedelta(hours=i))
                    for i, pnl in enumerate(self.profits)]
        return []

    async def fetchrow(self, sql, *args):
        self.sql.append(sql)
        if 'FROM outbox_events' in sql:
            rows = [r for r in self.outbox if (r['event_type'], r['aggregate_type']) == args]
            if not rows:
                return None
            last = max(rows, key=lambda r: r['aggregate_id'])
            return {'id': last['id'], 'payload': last['payload']}
        return None

    async def execute(self, sql, *args):
        self.sql.append(sql)
        return 'OK'

    def acquire(self):
        return _Ctx(self)

    def transaction(self):
        return _Ctx(self)

    def observed(self):
        return [dict(r, payload=json.loads(r['payload'])) for r in self.outbox
                if r['event_type'] == OBSERVED_OUTBOX_EVENT]

    def halted(self):
        return [r for r in self.outbox if r['event_type'] == 'risk.halted']


class _Ctx:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def wire(monkeypatch, mode, profits, db=None):
    db = db or OutboxDB(profits)
    monkeypatch.setattr(config, 'PAPER_ECONOMIC_HALT_MODE', mode)
    monkeypatch.setattr(config, 'PAPER_TRADING', True)
    monkeypatch.setattr(tracker, 'Database', db)
    monkeypatch.setattr('shared.risk_epoch.Database', db)
    monkeypatch.setattr(tracker, 'get_pause_state', AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(tracker, 'get_current_price', AsyncMock(return_value=100.0))
    return db


async def cycle(db, n=1, symbol='BTCUSDT'):
    for _ in range(n):
        await tracker.record_risk_decision(await tracker.assess_new_trade_risk(symbol))


# ---- pure helpers -------------------------------------------------------------------------

def test_transition_helper():
    assert observation_transition((), ()) is None
    assert observation_transition((), ('loss_streak_halt',)) == 'observed'
    assert observation_transition(('loss_streak_halt',), ('loss_streak_halt',)) is None
    assert observation_transition(('loss_streak_halt',),
                                  ('daily_loss_limit', 'loss_streak_halt')) == 'changed'
    assert observation_transition(('loss_streak_halt',), ()) == 'cleared'
    assert observation_transition(None, None) is None


def test_observed_codes_unknown_for_technical_halt():
    lim = RiskLimits(capital_usdt=500, trade_amount_usdt=50, max_open_trades=2)
    snap = RiskSnapshot(0, 0, 0, float('nan'), 500, 0, 0, 9)
    assert observed_codes(evaluate_with_policy(snap, lim, 'observe')) is None
    clean = RiskSnapshot(0, 0, 0, 0, 500, 0, 0, 0)
    assert observed_codes(evaluate_with_policy(clean, lim, 'observe')) == ()
    streak = RiskSnapshot(0, 0, 0, 0, 500, 0, 0, 7)
    assert observed_codes(evaluate_with_policy(streak, lim, 'observe')) == ('loss_streak_halt',)


# ---- tracker path ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transition_enqueues_exactly_one_event(monkeypatch):
    db = wire(monkeypatch, 'observe', [LOSS] * 7)
    await cycle(db)
    events = db.observed()
    assert len(events) == 1
    ev = events[0]
    assert (ev['aggregate_type'], ev['aggregate_id']) == (OBSERVED_OUTBOX_AGGREGATE, 0)
    assert ev['payload']['codes'] == ['loss_streak_halt']
    assert ev['payload']['transition'] == 'observed'
    assert ev['payload']['previous_codes'] == []
    assert ev['payload']['risk_policy_version'] == 'econ-observe-v1'
    # Codes only: no P&L, counts or drawdown values travel with the notice.
    assert set(ev['payload']) == {'codes', 'previous_codes', 'transition',
                                  'risk_management_id', 'risk_policy_version'}
    assert db.halted() == []


@pytest.mark.asyncio
async def test_repeated_identical_decisions_add_nothing(monkeypatch):
    db = wire(monkeypatch, 'observe', [LOSS] * 7)
    await cycle(db, 6)                                 # per admission / per cycle repeats
    await cycle(db, 3, symbol='__POST_CLOSE_RISK_REFRESH__')
    assert len(db.observed()) == 1


@pytest.mark.asyncio
async def test_restart_derives_state_from_persisted_outbox(monkeypatch):
    db = wire(monkeypatch, 'observe', [LOSS] * 7)
    await cycle(db)
    # "Restart": the alert path keeps no process memory; a new process sees only the
    # persisted outbox rows (stored jsonb arrives as text), so it does not re-alert.
    assert not [n for n in vars(tracker) if 'observ' in n.lower() and isinstance(
        getattr(tracker, n), (dict, set, list))], 'no in-memory observation cache'
    restarted = wire(monkeypatch, 'observe', [LOSS] * 7, db=db)
    await cycle(restarted, 2)
    assert len(db.observed()) == 1, 'no re-alert after restart'


@pytest.mark.asyncio
async def test_change_then_clear_each_one_event(monkeypatch):
    db = wire(monkeypatch, 'observe', [LOSS] * 7)
    await cycle(db, 2)
    # A deeper streak keeps the same code set: no new event.
    db.profits = [LOSS] * 9
    await cycle(db, 2)
    assert len(db.observed()) == 1
    # Drawdown joins the streak: one 'changed' event naming both codes.
    db.profits = [LOSS] * 4 + [-20.0] * 5
    await cycle(db, 3)
    events = db.observed()
    assert len(events) == 2
    changed = events[1]
    assert changed['payload']['transition'] == 'changed'
    assert changed['payload']['codes'] == ['max_drawdown_limit', 'loss_streak_halt']
    assert changed['payload']['previous_codes'] == ['loss_streak_halt']
    assert changed['aggregate_id'] == events[0]['id'], 'key = predecessor event id'
    # Clear: a win ends the streak and equity recovers -> one 'cleared' event.
    db.profits = [WIN] * 3
    await cycle(db, 4)
    events = db.observed()
    assert len(events) == 3
    assert events[2]['payload']['transition'] == 'cleared'
    assert events[2]['payload']['codes'] == []
    assert events[2]['aggregate_id'] == events[1]['id']
    # Re-entering the same code later is a new transition (new predecessor) -> one event.
    db.profits = [WIN] * 3 + [LOSS] * 7
    await cycle(db, 2)
    events = db.observed()
    assert len(events) == 4 and events[3]['payload']['transition'] == 'observed'


@pytest.mark.asyncio
async def test_clean_state_with_no_history_sends_nothing(monkeypatch):
    db = wire(monkeypatch, 'observe', [WIN, LOSS])
    await cycle(db, 3)
    assert db.observed() == []


@pytest.mark.asyncio
async def test_technical_halt_is_not_a_false_clear(monkeypatch):
    db = wire(monkeypatch, 'observe', [LOSS] * 7)
    await cycle(db)
    monkeypatch.setattr(tracker, 'get_current_price', AsyncMock(return_value=None))
    plain = db.fetch

    async def with_open_trade(sql, *args):
        if 'active_trades' in sql:
            return [{'symbol': 'ETHUSDT', 'entry_price': 100.0,
                     'trade_type': 'momentum', 'regime': 'flat'}]
        return await plain(sql, *args)
    db.fetch = with_open_trade
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    assert d.reason == 'invalid_risk_state'
    await tracker.record_risk_decision(d)
    assert len(db.observed()) == 1, 'unknown economic state is not reported as cleared'
    assert len(db.halted()) == 1, 'technical halt still uses risk.halted'


@pytest.mark.asyncio
async def test_concurrent_writers_with_same_predecessor_collapse(monkeypatch):
    db = wire(monkeypatch, 'observe', [LOSS] * 7)
    plain = db.fetchrow

    async def racing_fetchrow(sql, *args):
        row = await plain(sql, *args)
        await asyncio.sleep(0)            # both writers read the baseline before either inserts
        return row
    db.fetchrow = racing_fetchrow
    d = await tracker.assess_new_trade_risk('BTCUSDT')
    await asyncio.gather(tracker.record_risk_decision(d), tracker.record_risk_decision(d))
    assert len(db.observed()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('profits', [[LOSS] * 7, [LOSS] * 4 + [-20.0] * 5, [WIN] * 3, []])
async def test_enforce_issues_no_observation_statement_or_event(monkeypatch, profits):
    db = wire(monkeypatch, 'enforce', profits)
    await cycle(db, 3)
    assert db.observed() == []
    assert not any(OBSERVED_OUTBOX_EVENT in s or 'aggregate_id DESC' in s for s in db.sql)
    if profits == [LOSS] * 7:
        assert db.halted(), 'legacy risk.halted path unchanged (fake persists no pause row)'


# ---- message (shared helper; telegram/main.py consumes it) --------------------------------

@pytest.mark.parametrize('codes', [
    ['daily_loss_limit'], ['weekly_loss_limit'], ['max_drawdown_limit'], ['loss_streak_halt'],
    ['daily_loss_limit', 'weekly_loss_limit', 'max_drawdown_limit', 'loss_streak_halt'],
])
def test_observed_message_is_fixed_text_with_codes_only(codes):
    payload = {'codes': codes, 'previous_codes': [], 'transition': 'observed',
               'risk_management_id': 4711, 'risk_policy_version': 'econ-observe-v1',
               # Even if a producer ever added numbers, they must not reach the text.
               'daily_pnl_pct': -3.25, 'consecutive_losses': 9, 'drawdown_pct': 16.4}
    text = risk_observed_message(payload)
    assert not any(ch.isdigit() for ch in text)
    assert f"economic stop observed: {', '.join(codes)}" in text
    assert 'Paper observe mode, collection continues' in text
    assert 'رُصد توقف اقتصادي' in text
    assert 'USDT' not in text and '%' not in text


def test_cleared_and_unknown_messages():
    cleared = risk_observed_message({'codes': [], 'transition': 'cleared'})
    assert 'economic stop observation cleared' in cleared
    assert not any(ch.isdigit() for ch in cleared)
    odd = risk_observed_message({'codes': ['loss_streak_halt', 'pnl -42.0', 'x9']})
    assert f'loss_streak_halt, {UNKNOWN_ECONOMIC_CODE}' in odd
    assert not any(ch.isdigit() for ch in odd)
    assert risk_observed_message({}) == cleared


@pytest.mark.asyncio
async def test_telegram_delivers_observed_event(monkeypatch):
    from cr1_support import load_telegram_main
    tg = load_telegram_main()
    assert 'risk.observed' in tg.LIFECYCLE_EVENT_TYPES
    payload = {'codes': ['loss_streak_halt'], 'transition': 'observed'}
    event = {'id': 9, 'payload': json.dumps(payload), 'created_at': tg._utcnow()}

    async def claim(event_type, owner, limit=20):
        return [event] if event_type == 'risk.observed' else []
    ack = AsyncMock()
    monkeypatch.setattr(tg, 'claim', claim)
    monkeypatch.setattr(tg, 'ack', ack)
    monkeypatch.setattr(tg.config, 'TELEGRAM_CHAT_ID', '1')

    class Bot:
        sent = []

        async def send_message(self, chat_id, text, **kw):
            self.sent.append(text)
    bot = Bot()
    assert await tg.deliver_trade_lifecycle_events(bot, 'tg') == 1
    assert bot.sent == [risk_observed_message(payload)]
    ack.assert_awaited_once_with(9, 'tg', 'delivered')
