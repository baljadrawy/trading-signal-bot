"""A38 end to end on a REAL disposable PostgreSQL (P1R_TEST_DSN; never production).

signal_engine -> signal.ready -> telegram (bot stubbed, nothing sent) -> signal.delivered ->
trade_tracker. It covers outbox deferral and terminal semantics, genuine dead letters, duplicates
and replays, concurrent claims, crash and restart, the entry fill models, the economic label at
close, and Telegram failure semantics. Every scenario runs in a fresh database (Env of
test_p1r_cr2_e2e)."""
import sys; sys.path.insert(0, '.'); sys.path.insert(0, 'tests')
import asyncio
import datetime as dt
import importlib.util

import pytest

from shared.config import config
from shared.database import Database
from shared import outbox
from shared import outbox_watch
from shared import risk_epoch

e2e = pytest.importorskip('test_p1r_cr2_e2e')
pytestmark = e2e.pytestmark
Env = e2e.Env


def run(fn, monkeypatch, tmp_path, model='observed_price_v0'):
    async def go():
        monkeypatch.setattr(config, 'PAPER_ENTRY_FILL_MODEL', model)
        async with Env('after', 'off', monkeypatch, tmp_path / fn.__name__) as env:
            return await fn(env)
    return asyncio.run(go())


async def delivered_row(env, sid):
    return await env.pool.fetchrow(
        "SELECT * FROM outbox_events WHERE event_type='signal.delivered' AND aggregate_id=$1", sid)


async def passes(env, n):
    for _ in range(n):
        await env.due_now()
        await env.tracker_pass()


# ================================================================ outbox primitives ===============
def test_defer_is_not_an_attempt_and_is_owner_scoped(monkeypatch, tmp_path):
    async def go(env):
        sid = await env.save()
        [ev] = await outbox.claim('signal.ready', 'w1')
        assert ev['attempts'] == 1
        await outbox.defer(ev['id'], 'intruder', 60, 'x')                 # not the lease owner
        assert (await env.val("SELECT status FROM outbox_events WHERE id=$1", ev['id'])) == 'processing'
        await outbox.defer(ev['id'], 'w1', 60, 'window open')
        row = await env.pool.fetchrow("SELECT *, available_at > NOW() + interval '50 s' AS later "
                                      "FROM outbox_events WHERE id=$1", ev['id'])
        assert (row['status'], row['attempts'], row['deferrals'], row['later']) == ('pending', 0, 1, True)
        assert row['last_error'] == 'deferred: window open' and row['locked_by'] is None
        for _ in range(20):                                                # never approaches dead
            await env.due_now()
            [ev] = await outbox.claim('signal.ready', 'w1')
            await outbox.defer(ev['id'], 'w1', 1, 'again')
        row = await env.pool.fetchrow("SELECT status, attempts, deferrals FROM outbox_events "
                                      "WHERE id=$1", ev['id'])
        assert tuple(row) == ('pending', 0, 21)
        await env.due_now()
        [ev] = await outbox.claim('signal.ready', 'w1')
        await outbox.ack(ev['id'], 'w1', 'delivered')
        return await env.pool.fetchrow("SELECT status, outcome FROM outbox_events WHERE id=$1", ev['id'])
    assert tuple(run(go, monkeypatch, tmp_path)) == ('completed', 'delivered')


def test_fail_exhaustion_is_named_and_observable(monkeypatch, tmp_path):
    async def go(env):
        sid = await env.save()
        await env.sql("UPDATE outbox_events SET max_attempts=2")
        watch = outbox_watch.DeadLetterWatch('t', ['signal.ready'],
                                             clock=lambda: dt.datetime.now(dt.timezone.utc)
                                             - dt.timedelta(minutes=1))
        assert await watch.poll(force=True) == []
        for _ in range(2):
            await env.due_now()
            [ev] = await outbox.claim('signal.ready', 'w')
            await outbox.fail(ev['id'], 'w', ValueError('defect'), 1)
        row = await env.pool.fetchrow("SELECT status, outcome, last_error FROM outbox_events")
        new = await watch.poll(force=True)
        return tuple(row), [r['id'] for r in new], await watch.poll(force=True)
    row, new, again = run(go, monkeypatch, tmp_path)
    assert row == ('dead', 'retry_exhausted', 'ValueError: defect')
    assert len(new) == 1 and again == []


def test_concurrent_claims_are_disjoint_and_leases_recover_after_crash(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        for i in range(12):
            await env.save(symbol=f'C{i:02d}USDT')
        a, b = await asyncio.gather(outbox.claim('signal.ready', 'wa', limit=8),
                                    outbox.claim('signal.ready', 'wb', limit=8))
        ids_a, ids_b = {e['id'] for e in a}, {e['id'] for e in b}
        # crash: worker A dies holding its lease; after the lease expires another worker takes over
        await env.sql("UPDATE outbox_events SET locked_at = NOW() - interval '10 minutes' "
                      "WHERE locked_by='wa'")
        c = await outbox.claim('signal.ready', 'wc', limit=20)
        return ids_a, ids_b, {e['id'] for e in c}, {e['attempts'] for e in c}
    ids_a, ids_b, ids_c, attempts = run(go, monkeypatch, tmp_path)
    assert not (ids_a & ids_b) and len(ids_a | ids_b) == 12
    assert ids_c == ids_a and attempts == {2}          # a crashed lease is a counted attempt


# ================================================================ tracker reconciliation ===========
def test_late_registration_never_dead_letters_and_opens_once(monkeypatch, tmp_path):
    """The 9 A37 cases: a limit order waits more than 8 re-checks, then fills inside the window."""
    async def go(env):
        await env.resume()
        sid = await env.save()
        env.prices['P1RUSDT'] = 100.5                                     # above limit: wait
        assert await env.telegram_pass() == 1
        await passes(env, 12)                                             # > the old 8-attempt budget
        waiting = await delivered_row(env, sid)
        env.prices['P1RUSDT'] = 99.8                                      # touches through the limit
        await passes(env, 3)
        done = await delivered_row(env, sid)
        trades = await env.val("SELECT count(*) FROM active_trades WHERE signal_id=$1", sid)
        opened = await env.val("SELECT count(*) FROM outbox_events WHERE event_type='trade.opened'")
        dead = await env.val("SELECT count(*) FROM outbox_events WHERE status='dead'")
        return waiting, done, trades, opened, dead
    waiting, done, trades, opened, dead = run(go, monkeypatch, tmp_path)
    assert (waiting['status'], waiting['attempts']) == ('pending', 0) and waiting['deferrals'] == 12
    assert (done['status'], done['outcome']) == ('completed', 'opened')
    assert trades == 1 and opened == 1 and dead == 0


def test_duplicate_and_replayed_delivery_creates_one_trade(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        sid = await env.save()
        assert await env.telegram_pass() == 1
        assert await env.enqueue('signal.delivered', sid) is None        # outbox uniqueness
        await passes(env, 2)
        await env.sql("UPDATE outbox_events SET status='pending', outcome=NULL "
                      "WHERE event_type='signal.delivered'")              # replay the event
        await passes(env, 3)
        return (await env.val("SELECT count(*) FROM active_trades"),
                await env.val("SELECT count(*) FROM outbox_events WHERE event_type='trade.opened'"),
                (await delivered_row(env, sid))['outcome'])
    assert run(go, monkeypatch, tmp_path) == (1, 1, 'opened')


def test_terminal_outcomes_are_named(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        stale = await env.save(symbol='STALEUSDT')
        rejected = await env.save(symbol='REJUSDT')
        env.prices.update({'STALEUSDT': 100.5, 'REJUSDT': 96.0})          # wait / below stop
        assert await env.telegram_pass() == 2
        await passes(env, 2)
        await env.sql("UPDATE signals SET signal_time = NOW() - interval '2 hours 1 minute' "
                      "WHERE id=$1", stale)
        await passes(env, 1)
        orders = {r['signal_id']: (r['status'], r['terminal_reason']) for r in await env.pool.fetch(
            "SELECT signal_id, status, terminal_reason FROM paper_entry_orders")}
        return ((await delivered_row(env, stale))['outcome'],
                (await delivered_row(env, rejected))['outcome'], orders[stale], orders[rejected])
    stale, rejected, o_stale, o_rej = run(go, monkeypatch, tmp_path)
    assert stale == 'terminal:STALE' and rejected == 'terminal:ENTRY_REJECTED'
    assert o_stale == ('working', None)                 # expiry is derived from the window
    assert o_rej == ('rejected', 'signal_invalidated_before_fill')


def test_genuine_failures_still_dead_letter_and_alert(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        missing = 987654
        await env.enqueue('signal.delivered', missing)                   # no such signal
        sid = await env.save(symbol='NOTIMEUSDT')
        await env.sql("UPDATE signals SET telegram_sent=true, signal_time=NULL WHERE id=$1", sid)
        await env.enqueue('signal.delivered', sid)                       # unresolvable window
        alerts = []

        async def alert(text):
            alerts.append(text)
        watch = outbox_watch.DeadLetterWatch(
            'trade_tracker', ['signal.delivered'], alert=alert,
            clock=lambda: dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1))
        await watch.poll(force=True)
        await passes(env, 8)
        rows = {r['aggregate_id']: (r['status'], r['outcome'], r['last_error']) for r in
                await env.pool.fetch("SELECT * FROM outbox_events WHERE event_type='signal.delivered'")}
        new = await watch.poll(force=True)
        return rows[missing], rows[sid], len(new), alerts
    missing, notime, n, alerts = run(go, monkeypatch, tmp_path)
    assert missing == ('dead', 'retry_exhausted', 'RuntimeError: signal_missing')
    assert notime == ('dead', 'retry_exhausted', 'RuntimeError: admission_state_unresolved_after_window')
    assert n == 2 and len(alerts) == 1


def test_outbox_semantics_do_not_change_admission(monkeypatch, tmp_path):
    """Admission is poll-based: the same price path admits the same trade whether the delivery
    event is deferred (A38) or has already died (pre-A38 state)."""
    async def go(env):
        await env.resume()
        a = await env.save(symbol='AAAUSDT')
        b = await env.save(symbol='BBBUSDT')
        env.prices.update({'AAAUSDT': 100.5, 'BBBUSDT': 100.5})
        assert await env.telegram_pass() == 2
        await passes(env, 2)
        await env.sql("UPDATE outbox_events SET status='dead' WHERE event_type='signal.delivered' "
                      "AND aggregate_id=$1", b)                          # pre-A38 dead letter
        env.prices.update({'AAAUSDT': 99.9, 'BBBUSDT': 99.9})
        await passes(env, 1)
        return [(r['symbol'], float(r['entry_price'])) for r in await env.pool.fetch(
            "SELECT symbol, entry_price FROM active_trades ORDER BY symbol")]
    assert run(go, monkeypatch, tmp_path) == [('AAAUSDT', 99.9), ('BBBUSDT', 99.9)]


# ================================================================ fill models end to end ===========
async def _resting_then_through(env, through_price):
    await env.resume()
    sid = await env.save()                                  # entry 100, stop 97
    env.prices['P1RUSDT'] = 100.5
    assert await env.telegram_pass() == 1
    await passes(env, 1)                                    # rests at its limit
    env.prices['P1RUSDT'] = through_price
    await passes(env, 1)
    trade = await env.pool.fetchrow("SELECT * FROM active_trades WHERE signal_id=$1", sid)
    order = await env.pool.fetchrow("SELECT * FROM paper_entry_orders WHERE signal_id=$1", sid)
    sent = await env.val("SELECT telegram_sent FROM signals WHERE id=$1", sid)
    return trade, order, sent


def test_resting_fill_at_limit_v1_vs_legacy_observed(monkeypatch, tmp_path):
    legacy = run(lambda env: _resting_then_through(env, 99.0), monkeypatch, tmp_path / 'l')
    v1 = run(lambda env: _resting_then_through(env, 99.0), monkeypatch, tmp_path / 'v',
             model='resting_limit_v1')
    lt, lo, _ = legacy
    vt, vo, _ = v1
    assert float(lt['entry_price']) == 99.0 and lt['entry_fill_model'] == 'observed_price_v0'
    assert lt['entry_order_type'] == 'market' and lo['fill_basis'] == 'legacy_observed'
    assert float(vt['entry_price']) == 100.0 and vt['entry_fill_model'] == 'resting_limit_v1'
    assert vt['entry_order_type'] == 'limit' and float(vt['stop_loss']) == 97.0   # bracket unscaled
    assert (vo['order_kind'], vo['status'], vo['fill_basis']) == ('resting', 'filled',
                                                                 'resting_trade_through')


def test_trade_through_below_stop_is_filled_by_v1_and_dropped_by_legacy(monkeypatch, tmp_path):
    lt, lo, l_sent = run(lambda env: _resting_then_through(env, 96.0), monkeypatch, tmp_path / 'l')
    vt, vo, v_sent = run(lambda env: _resting_then_through(env, 96.0), monkeypatch, tmp_path / 'v',
                         model='resting_limit_v1')
    assert lt is None and l_sent is False and lo['status'] == 'rejected'
    assert vt is not None and float(vt['entry_price']) == 100.0 and vo['status'] == 'filled'


def test_marketable_arrival_keeps_observed_price_under_v1(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        sid = await env.save()
        env.prices['P1RUSDT'] = 99.5
        assert await env.telegram_pass() == 1
        await passes(env, 1)
        return (await env.pool.fetchrow("SELECT entry_price, entry_order_type FROM active_trades")), \
            (await env.pool.fetchrow("SELECT order_kind, fill_basis FROM paper_entry_orders"))
    trade, order = run(go, monkeypatch, tmp_path, model='resting_limit_v1')
    assert float(trade['entry_price']) == 99.5 and trade['entry_order_type'] == 'market'
    assert tuple(order) == ('marketable', 'marketable_observed')


def test_resting_kind_survives_a_tracker_restart(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        sid = await env.save()
        env.prices['P1RUSDT'] = 100.5
        assert await env.telegram_pass() == 1
        await passes(env, 1)
        # restart: a fresh tracker module (no in-memory state), same database
        spec = importlib.util.spec_from_file_location('a38_tracker_restarted', 'trade_tracker/main.py')
        fresh = importlib.util.module_from_spec(spec)
        sys.path.insert(0, 'trade_tracker')
        try:
            spec.loader.exec_module(fresh)
        finally:
            sys.path.remove('trade_tracker')

        async def price(symbol):
            return 99.0

        async def notional(symbol):
            return 5.0
        monkeypatch.setattr(fresh, 'get_current_price', price)
        monkeypatch.setattr(fresh, 'get_min_notional', notional)
        env.tr = fresh
        await passes(env, 1)
        return await env.val("SELECT entry_price FROM active_trades WHERE signal_id=$1", sid)
    assert float(run(go, monkeypatch, tmp_path, model='resting_limit_v1')) == 100.0


# ================================================================ economic label at close ==========
def test_close_stores_economic_label_beside_legacy_gross(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        await env.sql("INSERT INTO risk_recovery_events (epoch_started_at, acknowledged_at, "
                      "acknowledged_by, reason, halt_reason, consecutive_losses_before, "
                      "open_positions_at_recovery) VALUES (NOW() - interval '1 hour', "
                      "NOW() - interval '1 hour', 't', 't', 'loss_streak_halt', 0, 0)")
        sid = await env.save()
        assert await env.telegram_pass() == 1
        await passes(env, 1)
        trade = dict(await env.pool.fetchrow("SELECT * FROM active_trades WHERE signal_id=$1", sid))
        await env.tr.close_trade_barrier(trade, 'WIN', 0.2, 0.10, 99.7, 'break_even', 1, False)
        row = await env.pool.fetchrow("SELECT * FROM trade_results WHERE signal_id=$1", sid)
        streak = await risk_epoch.effective_consecutive_losses()
        from shared.fees import economic_result_sql
        historical = await env.val(
            "INSERT INTO trade_results (signal_id, symbol, entry_price, exit_price, profit_percent, "
            "profit_usdt, result, exit_time) VALUES (NULL,'OLDUSDT',1,1,0.2,0.10,'WIN',NOW()) RETURNING id")
        derived = await env.val(f"SELECT {economic_result_sql('$1::numeric')} FROM trade_results "
                                "WHERE id=$2", 0.15, historical)
        return row, streak, derived
    row, streak, derived = run(go, monkeypatch, tmp_path)
    assert row['result'] == 'WIN'                                  # legacy gross label unchanged
    gross = float(row['profit_usdt'])                              # recomputed from the exit
    assert 0 < gross < 0.15                                        # gross-positive, net-negative
    assert (row['economic_result'], float(row['net_profit_usdt']), float(row['cost_usdt'])) == \
        ('LOSS', round(gross - 0.15, 6), 0.15)
    assert row['label_policy'] == 'net_after_modeled_cost_v1'
    assert streak == 1                                             # risk guard agrees: a loss
    assert derived == 'LOSS'                                       # history derived, not rewritten


# ================================================================ telegram =========================
class FakeBot:
    def __init__(self, errors=()):
        self.errors = list(errors)
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        if self.errors:
            err = self.errors.pop(0)
            if err is not None:
                raise err
        self.sent.append(text)


def _tg_error(name, **attrs):
    network = type('NetworkError', (Exception,), {})
    e = type(name, (network,), {})(name)
    for k, v in attrs.items():
        setattr(e, k, v)
    return e


async def _opened_trades(env, n):
    await env.resume()
    for i in range(n):
        await env.save(symbol=f'N{i}USDT')
    assert await env.telegram_pass() == n
    await passes(env, 1)
    assert await env.val("SELECT count(*) FROM active_trades") == n


def test_candidate_transient_failure_defers_then_expires_explicitly(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        sid = await env.save()
        tg, alerts = env.tg, []

        async def down(bot, signal):
            raise ConnectionError('db unavailable')

        async def alert(text, **kw):
            alerts.append(text)
        monkeypatch.setattr(tg, 'send_signal_direct', down)
        monkeypatch.setattr(tg, 'send_alert', alert)
        assert await env.telegram_pass() == 0
        deferred = await env.pool.fetchrow("SELECT status, attempts, deferrals FROM outbox_events "
                                           "WHERE event_type='signal.ready'")
        await env.sql("UPDATE signals SET signal_time = NOW() - interval '2 hours 1 minute'")
        await env.due_now()
        assert await env.telegram_pass() == 0
        final = await env.pool.fetchrow("SELECT status, outcome FROM outbox_events "
                                        "WHERE event_type='signal.ready'")
        return tuple(deferred), tuple(final), alerts
    deferred, final, alerts = run(go, monkeypatch, tmp_path)
    assert deferred == ('pending', 0, 1)
    assert final == ('completed', 'expired_undelivered') and len(alerts) == 1


def test_candidate_permanent_failure_uses_the_counted_budget(monkeypatch, tmp_path):
    async def go(env):
        await env.resume()
        await env.save()

        async def defect(bot, signal):
            raise ValueError('bug')
        monkeypatch.setattr(env.tg, 'send_signal_direct', defect)
        assert await env.telegram_pass() == 0
        return tuple(await env.pool.fetchrow("SELECT status, attempts, deferrals FROM outbox_events "
                                             "WHERE event_type='signal.ready'"))
    assert run(go, monkeypatch, tmp_path) == ('pending', 1, 0)


def test_notification_outage_defers_in_order_then_summarises_once(monkeypatch, tmp_path):
    async def go(env):
        await _opened_trades(env, 3)
        tg = env.tg
        for k in list(tg.NOTIFY_STATE):
            monkeypatch.setitem(tg.NOTIFY_STATE, k, 0 if isinstance(tg.NOTIFY_STATE[k], int) else None)
        bot = FakeBot([_tg_error('TimedOut')])
        assert await tg.deliver_trade_lifecycle_events(bot, 'tg') == 0      # circuit breaker
        after_outage = [tuple(r) for r in await env.pool.fetch(
            "SELECT status, attempts, deferrals FROM outbox_events WHERE event_type='trade.opened' "
            "ORDER BY id")]
        health = tg.delivery_health()
        await env.due_now()
        assert await tg.deliver_trade_lifecycle_events(bot, 'tg') == 3
        outcomes = [r['outcome'] for r in await env.pool.fetch(
            "SELECT outcome FROM outbox_events WHERE event_type='trade.opened' ORDER BY id")]
        await env.due_now()
        await tg.deliver_trade_lifecycle_events(bot, 'tg')
        return after_outage, health, bot.sent, outcomes
    after_outage, health, sent, outcomes = run(go, monkeypatch, tmp_path)
    assert after_outage == [('pending', 0, 1)] * 3              # none consumed an attempt
    assert health['notifications']['unavailable_since'] is not None
    summaries = [t for t in sent if 'تعذّر إرسال الإشعارات' in t]
    assert len(sent) == 4 and len(summaries) == 1               # 3 messages + one summary
    assert sent.index(summaries[0]) == 1                        # right after the first success
    assert outcomes == ['delivered'] * 3


def test_notification_rate_limit_ttl_and_permanent_errors(monkeypatch, tmp_path):
    async def go(env):
        await _opened_trades(env, 2)
        tg = env.tg
        bot = FakeBot([_tg_error('RetryAfter', retry_after=42)])
        await tg.deliver_trade_lifecycle_events(bot, 'tg')
        wait = await env.val("SELECT EXTRACT(EPOCH FROM available_at - NOW()) FROM outbox_events "
                             "WHERE event_type='trade.opened' ORDER BY id LIMIT 1")
        await env.sql("UPDATE outbox_events SET created_at = NOW() - interval '25 hours', "
                      "available_at = NOW() WHERE event_type='trade.opened' AND id = "
                      "(SELECT min(id) FROM outbox_events WHERE event_type='trade.opened')")
        bad = FakeBot([_tg_error('BadRequest')])
        await env.sql("UPDATE outbox_events SET available_at = NOW() WHERE status='pending'")
        await tg.deliver_trade_lifecycle_events(bad, 'tg')
        return float(wait), [tuple(r) for r in await env.pool.fetch(
            "SELECT status, outcome, attempts FROM outbox_events WHERE event_type='trade.opened' "
            "ORDER BY id")]
    wait, rows = run(go, monkeypatch, tmp_path)
    assert 40 <= wait <= 44                                     # server retry_after + 1
    assert rows[0] == ('completed', 'notification_expired', 1)  # older than the 24 h TTL
    assert rows[1] == ('pending', None, 1)                      # permanent: counted attempt


def test_notification_failure_never_blocks_trading(monkeypatch, tmp_path):
    async def go(env):
        await _opened_trades(env, 1)
        bot = FakeBot([_tg_error('TimedOut')] * 50)
        for _ in range(5):
            await env.due_now()
            await env.tg.deliver_trade_lifecycle_events(bot, 'tg')
        await env.save(symbol='NEXTUSDT')
        assert await env.telegram_pass() == 1
        await passes(env, 1)
        return await env.val("SELECT count(*) FROM active_trades")
    assert run(go, monkeypatch, tmp_path) == 2
