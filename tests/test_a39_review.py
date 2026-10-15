"""A39 independent review of A38: failure modes the A38 tests did not cover (disposable PostgreSQL, P1R_TEST_DSN).
No real Telegram messages (stubbed bots/alerts); never production."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import asyncio
import datetime as dt
import os
from pathlib import Path

import pytest

from shared import outbox, outbox_watch
from shared.config import config

e2e = pytest.importorskip('test_p1r_cr2_e2e')
pytestmark = e2e.pytestmark
asyncpg = e2e.asyncpg
Env, DSN, AFTER = e2e.Env, e2e.DSN, e2e.AFTER
from test_a38_lifecycle_db import run, passes, delivered_row, FakeBot, _tg_error, _opened_trades  # noqa: E402

MIGRATION = AFTER / 'database' / 'migrations' / '010_a38_execution_integrity.sql'


# ================================================================ migration =======================
def test_migration_times_out_on_a_held_lock_and_rolls_back_completely():
    async def go():
        db = 'a39_mig_lock'
        admin = await asyncpg.connect(DSN)
        await admin.execute(f'DROP DATABASE IF EXISTS {db} WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE {db}')
        await admin.close()
        dsn = DSN.rsplit('/', 1)[0] + '/' + db
        setup = await asyncpg.connect(dsn)
        for path in [p for p in e2e.SCHEMA if p.name != MIGRATION.name]:     # schema version 9
            await setup.execute(Path(path).read_text(encoding='utf-8'))
        holder = await asyncpg.connect(dsn)
        tx = holder.transaction()
        await tx.start()
        await holder.fetch("SELECT * FROM outbox_events LIMIT 1")         # a running reader holds a lock
        body = MIGRATION.read_text(encoding='utf-8')
        t0 = asyncio.get_running_loop().time()
        err = None
        try:
            async with setup.transaction():                               # exactly how migrate.py applies it
                await setup.execute(body)
        except Exception as exc:
            err = exc
        took = asyncio.get_running_loop().time() - t0
        cols = await setup.fetchval("SELECT count(*) FROM information_schema.columns WHERE "
                                    "table_name='trade_results' AND column_name='economic_result'")
        orders = await setup.fetchval("SELECT to_regclass('paper_entry_orders') IS NOT NULL")
        await tx.rollback()
        await holder.close()
        async with setup.transaction():                                   # lock gone: applies
            await setup.execute(body)
        ok = await setup.fetchval("SELECT to_regclass('paper_entry_orders') IS NOT NULL")
        await setup.close()
        admin = await asyncpg.connect(DSN)
        await admin.execute(f'DROP DATABASE IF EXISTS {db} WITH (FORCE)')
        await admin.close()
        return err, took, cols, orders, ok
    err, took, cols, orders, ok = asyncio.run(go())
    assert type(err).__name__ == 'LockNotAvailableError' and 4 <= took < 15
    assert cols == 0 and orders is False                                  # nothing partial survived
    assert ok is True


# ================================================================ outbox idempotency ===============
def test_stale_owner_and_duplicate_acks_are_no_ops(monkeypatch, tmp_path):
    async def go(env):
        await env.save()
        [ev] = await outbox.claim('signal.ready', 'w1')
        await env.sql("UPDATE outbox_events SET locked_at = NOW() - interval '10 minutes'")
        [ev2] = await outbox.claim('signal.ready', 'w2')                  # w1 crashed; w2 took over
        stale = await outbox.ack(ev['id'], 'w1', 'delivered')
        stale_defer = await outbox.defer(ev['id'], 'w1', 60, 'x')
        first = await outbox.ack(ev2['id'], 'w2', 'delivered')
        again = await outbox.ack(ev2['id'], 'w2', 'other')
        row = await env.pool.fetchrow("SELECT status, outcome, attempts, deferrals FROM outbox_events")
        return stale, stale_defer, first, again, tuple(row)
    stale, stale_defer, first, again, row = run(go, monkeypatch, tmp_path)
    assert (stale, stale_defer, first, again) == ('UPDATE 0', 'UPDATE 0', 'UPDATE 1', 'UPDATE 0')
    assert row == ('completed', 'delivered', 2, 0)


def test_concurrent_tracker_passes_open_one_trade(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        sid = await env.save()
        assert await env.telegram_pass() == 1
        await asyncio.gather(env.tracker_pass(), env.tracker_pass(), env.tracker_pass())
        await passes(env, 1)
        return (await env.val("SELECT count(*) FROM active_trades"),
                await env.val("SELECT count(*) FROM outbox_events WHERE event_type='trade.opened'"),
                (await delivered_row(env, sid))['outcome'])
    assert run(go, monkeypatch, tmp_path) == (1, 1, 'opened')


def test_admission_window_boundary(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        sid = await env.save()
        env.prices['P1RUSDT'] = 100.5
        assert await env.telegram_pass() == 1
        await env.sql("UPDATE signals SET signal_time = NOW() - interval '1 hour 59 minutes 30 seconds'")
        await passes(env, 1)
        wait = await env.val("SELECT EXTRACT(EPOCH FROM available_at - NOW()) FROM outbox_events "
                             "WHERE event_type='signal.delivered'")
        await env.sql("UPDATE signals SET signal_time = NOW() - interval '2 hours 1 second'")
        await passes(env, 1)
        return float(wait), (await delivered_row(env, sid))['outcome']
    wait, outcome = run(go, monkeypatch, tmp_path)
    assert 0 < wait <= 32                       # never scheduled past the window end (+1 s)
    assert outcome == 'terminal:STALE'


# ================================================================ telegram ========================
def test_future_signal_time_cannot_defer_forever(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        await env.save()
        await env.sql("UPDATE signals SET signal_time = NOW() + interval '3 days'")
        await env.sql("UPDATE outbox_events SET created_at = NOW() - interval '3 hours'")

        async def down(bot, signal):
            raise ConnectionError('db unavailable')
        monkeypatch.setattr(env.tg, 'send_signal_direct', down)
        assert await env.telegram_pass() == 0
        return tuple(await env.pool.fetchrow("SELECT status, attempts, deferrals FROM outbox_events "
                                             "WHERE event_type='signal.ready'"))
    assert run(go, monkeypatch, tmp_path) == ('pending', 1, 0)        # counted, not deferred


def test_deferred_notifications_survive_a_restart(monkeypatch, tmp_path):
    async def go(env):
        await _opened_trades(env, 2)
        tg = env.tg
        await tg.deliver_trade_lifecycle_events(FakeBot([_tg_error('TimedOut')]), 'tg-old')
        for k in list(tg.NOTIFY_STATE):                     # restart: in-memory outage state is lost
            monkeypatch.setitem(tg.NOTIFY_STATE, k, 0 if isinstance(tg.NOTIFY_STATE[k], int) else None)
        await env.due_now()
        bot = FakeBot()
        assert await tg.deliver_trade_lifecycle_events(bot, 'tg-new') == 2
        return bot.sent, [r['outcome'] for r in await env.pool.fetch(
            "SELECT outcome FROM outbox_events WHERE event_type='trade.opened' ORDER BY id")]
    sent, outcomes = run(go, monkeypatch, tmp_path)
    assert outcomes == ['delivered', 'delivered']           # durable state: nothing lost
    assert len(sent) == 2                                   # residual: no outage summary after a restart


def test_long_outage_expires_notifications_explicitly(monkeypatch, tmp_path):
    async def go(env):
        await _opened_trades(env, 2)
        tg = env.tg
        bot = FakeBot([_tg_error('TimedOut')] * 100)
        await tg.deliver_trade_lifecycle_events(bot, 'tg')
        await env.sql("UPDATE outbox_events SET created_at = NOW() - interval '25 hours', available_at = NOW() "
                      "WHERE event_type='trade.opened'")
        await tg.deliver_trade_lifecycle_events(bot, 'tg')
        return [tuple(r) for r in await env.pool.fetch(
            "SELECT status, outcome, attempts FROM outbox_events WHERE event_type='trade.opened' ORDER BY id")]
    rows = run(go, monkeypatch, tmp_path)
    assert rows == [('completed', 'notification_expired', 1)] * 2


# ================================================================ dead-letter watch resume ========
def test_dead_letter_died_before_a_crash_is_alerted_after_restart(monkeypatch):
    boot = dt.datetime(2026, 10, 14, 12, 0)
    rows = [{'id': i, 'event_type': 'signal.delivered', 'aggregate_type': 'signal', 'aggregate_id': i,
             'attempts': 8, 'deferrals': 0, 'last_error': 'e', 'created_at': t, 'processed_at': t}
            for i, t in ((1, boot - dt.timedelta(hours=30)), (2, boot - dt.timedelta(minutes=10)),
                         (3, boot - dt.timedelta(minutes=2)))]

    async def since(types, after, limit=50):
        return [r for r in rows if (r['processed_at'], r['id']) > after][:limit]
    monkeypatch.setattr(outbox_watch, 'dead_letters_since', since)
    alerts = []

    async def alert(text):
        alerts.append(text)

    async def prev():                    # the previous run had alerted letter 2 before it crashed
        return rows[1]['processed_at'], 2
    w = outbox_watch.DeadLetterWatch('t', ['signal.delivered'], alert=alert, resume_from=prev,
                                     clock=lambda: boot.replace(tzinfo=dt.timezone.utc))
    got = asyncio.run(w.poll(force=True))
    assert [r['id'] for r in got] == [3] and len(alerts) == 1 and w.snapshot()['resumed_from_previous_run']

    async def ancient():                 # a watermark older than 24 h is ignored (no history re-alert)
        return rows[0]['processed_at'] - dt.timedelta(hours=1), 0
    w2 = outbox_watch.DeadLetterWatch('t', ['x'], resume_from=ancient,
                                      clock=lambda: boot.replace(tzinfo=dt.timezone.utc))
    assert asyncio.run(w2.poll(force=True)) == [] and w2.snapshot()['resumed_from_previous_run'] is False


# ================================================================ partial deployment ==============
_BEFORE = pytest.mark.skipif(not e2e.BEFORE, reason='P1_BEFORE_TREE (pre-A38 tree) not set')


def _mixed(monkeypatch, tmp_path, tg_arm, tr_arm):
    """Migrated (v10) schema, one service on pre-A38 code and the other on A38: the deployment window."""
    async def go():
        monkeypatch.setattr(config, 'PAPER_ENTRY_FILL_MODEL', 'observed_price_v0')
        async with Env('after', 'off', monkeypatch, tmp_path / f'mix_{tg_arm}_{tr_arm}') as env:
            env.tg = e2e.modules(tg_arm)[1]
            env.tr = e2e.modules(tr_arm)[2]

            async def price(symbol):
                return env.prices.get(symbol, 99.5)

            async def notional(symbol):
                return 5.0
            monkeypatch.setattr(env.tr, 'get_current_price', price)
            monkeypatch.setattr(env.tr, 'get_min_notional', notional)
            if hasattr(env.tg, 'DELIVERY_PACING_SECONDS'):
                monkeypatch.setattr(env.tg, 'DELIVERY_PACING_SECONDS', 0)
            await env.resume()
            a = await env.save(symbol='MIXAUSDT')                      # fills immediately
            b = await env.save(symbol='MIXBUSDT')
            env.prices['MIXBUSDT'] = 100.5                              # waits
            assert await env.telegram_pass() == 2
            await passes(env, 3)
            env.prices['MIXBUSDT'] = 99.9
            await passes(env, 2)
            rows = {r['aggregate_id']: (r['status'], r['outcome']) for r in await env.pool.fetch(
                "SELECT aggregate_id, status, outcome FROM outbox_events WHERE event_type='signal.delivered'")}
            trades = await env.val("SELECT count(*) FROM active_trades")
            dead = await env.val("SELECT count(*) FROM outbox_events WHERE status='dead'")
            return rows[a], rows[b], trades, dead
    return asyncio.run(go())


@_BEFORE
def test_new_tracker_with_old_telegram(monkeypatch, tmp_path):
    a, b, trades, dead = _mixed(monkeypatch, tmp_path, 'before', 'after')
    assert trades == 2 and dead == 0
    assert a == ('completed', 'opened') and b == ('completed', 'opened')


@_BEFORE
def test_old_tracker_with_new_telegram(monkeypatch, tmp_path):
    a, b, trades, dead = _mixed(monkeypatch, tmp_path, 'after', 'before')
    assert trades == 2 and dead == 0                    # pre-A38 tracker: same trades, legacy outbox semantics
    assert a == ('completed', None) and b[0] == 'completed'
