"""Loss-streak halt recovery contract (Phase RISK-1).

Covers the deadlock that made the hard halt absorbing: once the streak reached
the threshold with a flat book, admission was refused, so nothing could close,
so the streak could never reset. Recovery is now an explicit, authorised,
audited acknowledgement that opens a new streak epoch without touching history.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from shared.risk_management import RiskLimits, RiskSnapshot, evaluate_new_trade
from shared.risk_epoch import (
    LOSS_STREAK_HALTED, LOSS_STREAK_RECOVERY_REQUIRED, TRADING_ACTIVE,
    TRADING_PAUSED, LossStreakState, RecoveryRejected, learning_clean_start,
    loss_streak_state, operational_state, record_recovery, tail_loss_streak,
)

CLEAN_START = datetime(2026, 7, 20, tzinfo=timezone.utc)
LOSS = -1.0
WIN = 2.0


def limits(**changes):
    values = dict(capital_usdt=500, trade_amount_usdt=50, max_open_trades=2)
    values.update(changes)
    return RiskLimits(**values)


def snapshot(consecutive_losses, open_count=0, **changes):
    values = dict(
        realized_total_usdt=0, daily_pnl_usdt=0, weekly_pnl_usdt=0,
        unrealized_pnl_usdt=0, peak_equity_usdt=500, open_count=open_count,
        symbol_open_count=0, consecutive_losses=consecutive_losses,
    )
    values.update(changes)
    return RiskSnapshot(**values)


class FakeDB:
    """Minimal stand-in for the shared Database facade.

    `profits` are gross; the module under test subtracts the round-trip fee, so
    tests state gross values the way trade_results does.
    """

    # Timestamp the fake database hands out for NOW(), standing in for the
    # server clock now that the epoch is database-generated.
    DB_NOW = CLEAN_START + timedelta(days=30)

    def __init__(self, profits, open_positions=0, epoch=None):
        self.profits = list(profits)
        self.open_positions = open_positions
        self.epoch = epoch
        self.inserted = []
        self.locks_taken = []

    async def execute(self, sql, *args):
        if 'pg_advisory_xact_lock' in sql:
            self.locks_taken.append(args[0])
            return 'SELECT 1'
        raise AssertionError(f'unexpected execute: {sql}')

    async def fetchval(self, sql, *args):
        if 'MAX(epoch_started_at)' in sql:
            return self.epoch
        if 'active_trades' in sql:
            return self.open_positions
        raise AssertionError(f'unexpected fetchval: {sql}')

    async def fetchrow(self, sql, *args):
        assert 'INSERT INTO risk_recovery_events' in sql
        assert 'NOW()' in sql, 'the epoch must be database-generated, not passed in'
        self.inserted.append(args)
        return {'id': len(self.inserted), 'epoch_started_at': self.DB_NOW}

    async def fetch(self, sql, *args):
        assert 'trade_results' in sql
        start = args[0]
        # Only closes at or after the effective boundary count.
        return [{'profit_usdt': p} for ts, p in self._stamped() if ts >= start]

    def _stamped(self):
        # Evenly spaced synthetic exit times inside the clean-start window.
        return [(CLEAN_START + timedelta(hours=i), p)
                for i, p in enumerate(self.profits)]

    def acquire(self):
        return _FakeAcquire(self)

    def transaction(self):
        # The acquired connection is this same fake, so it must offer the
        # transaction context manager too.
        return _FakeAcquire(self)


class _FakeAcquire:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *exc):
        return False


def patched(db):
    return patch('shared.risk_epoch.Database', db)


# ---------------------------------------------------------------- pure helper

def test_tail_streak_counts_only_the_trailing_run():
    assert tail_loss_streak([LOSS, WIN, LOSS, LOSS]) == 2
    assert tail_loss_streak([LOSS] * 7) == 7
    assert tail_loss_streak([]) == 0


def test_break_even_close_counts_as_a_win():
    # Production uses `net >= 0`, so an exact scratch ends the run.
    assert tail_loss_streak([LOSS, LOSS, 0.0]) == 0


# ------------------------------------------------- Case 1: below the hard halt

@pytest.mark.asyncio
async def test_case1_six_losses_throttles_but_does_not_halt():
    db = FakeDB([LOSS] * 6)
    with patched(db):
        state = await loss_streak_state()
    assert state.consecutive_losses == 6
    assert not state.halt_active
    assert not state.manual_recovery_required

    decision = evaluate_new_trade(snapshot(6), limits())
    assert decision.allowed, 'six losses must still admit under the existing soft throttle'
    assert decision.size_multiplier == 0.1


def test_case1_soft_thresholds_are_unchanged():
    assert evaluate_new_trade(snapshot(3), limits()).size_multiplier == 0.5
    assert evaluate_new_trade(snapshot(5), limits()).size_multiplier == 0.1
    assert evaluate_new_trade(snapshot(3), limits()).allowed
    assert evaluate_new_trade(snapshot(5), limits()).allowed


# ------------------------------------------------ Case 2: reaching seven losses

@pytest.mark.asyncio
async def test_case2_seventh_loss_halts_and_requires_recovery():
    db = FakeDB([LOSS] * 7)
    with patched(db):
        state = await loss_streak_state()
    assert state.consecutive_losses == 7
    assert state.halt_active
    assert state.manual_recovery_required

    decision = evaluate_new_trade(snapshot(7), limits())
    assert not decision.allowed
    assert decision.reason == 'loss_streak_halt'


# ------------------------- Case 3: seven losses while a position is still open

@pytest.mark.asyncio
async def test_case3_open_position_halt_is_not_manual_recovery_required():
    """The autonomous path is deliberately preserved.

    With a position still open the halt can clear on its own when that position
    closes green -- exactly how the real 2026-08-17 halt cleared. Recovery is
    therefore NOT offered here, which keeps one coherent contract: the halt is a
    function of the effective streak, and only a flat book makes the streak
    unable to move on its own.
    """
    db = FakeDB([LOSS] * 7, open_positions=1)
    with patched(db):
        state = await loss_streak_state()
    assert state.halt_active
    assert not state.manual_recovery_required, 'an open position can still clear this halt'


@pytest.mark.asyncio
async def test_case3_winning_close_clears_halt_without_any_operator_action():
    db = FakeDB([LOSS] * 7 + [WIN])
    with patched(db):
        state = await loss_streak_state()
    assert state.consecutive_losses == 0
    assert not state.halt_active
    assert evaluate_new_trade(snapshot(0), limits()).allowed


# -------------------------------- Case 4: the blocker — seven losses, flat book

@pytest.mark.asyncio
async def test_case4_zero_open_seven_losses_is_the_deadlock_state():
    db = FakeDB([LOSS] * 7, open_positions=0)
    with patched(db):
        state = await loss_streak_state()
    assert state.halt_active
    assert state.manual_recovery_required
    assert state.open_positions == 0
    assert not evaluate_new_trade(snapshot(7), limits()).allowed


# ------------------------------------------- Case 5: /resume must not recover

def test_case5_clearing_the_pause_alone_leaves_admission_refused():
    # manually_paused=False models the state right after /resume.
    decision = evaluate_new_trade(snapshot(7), limits())
    assert not decision.allowed
    assert decision.reason == 'loss_streak_halt'


@pytest.mark.asyncio
async def test_case5_operational_state_ranks_risk_halt_above_pause():
    db = FakeDB([LOSS] * 7)
    with patched(db):
        state = await loss_streak_state()
    # Even with the pause cleared, the surface must not read as healthy.
    assert operational_state(state, is_paused=False) == LOSS_STREAK_RECOVERY_REQUIRED
    assert operational_state(state, is_paused=True) == LOSS_STREAK_RECOVERY_REQUIRED


@pytest.mark.asyncio
async def test_operational_state_classification_is_exhaustive():
    healthy = FakeDB([WIN])
    with patched(healthy):
        state = await loss_streak_state()
    assert operational_state(state, is_paused=False) == TRADING_ACTIVE
    assert operational_state(state, is_paused=True) == TRADING_PAUSED

    open_halt = FakeDB([LOSS] * 7, open_positions=1)
    with patched(open_halt):
        state = await loss_streak_state()
    assert operational_state(state, is_paused=False) == LOSS_STREAK_HALTED


# --------------------------------------------- Case 6: restart must not clear

@pytest.mark.asyncio
async def test_case6_state_reconstructs_identically_in_a_fresh_process():
    # Two independent reads model two process lifetimes over the same history.
    first = FakeDB([LOSS] * 7)
    second = FakeDB([LOSS] * 7)
    with patched(first):
        a = await loss_streak_state()
    with patched(second):
        b = await loss_streak_state()
    assert a.consecutive_losses == b.consecutive_losses == 7
    assert a.halt_active and b.halt_active
    assert a.manual_recovery_required and b.manual_recovery_required


# -------------------------------------------- Case 7: authorised manual recovery

@pytest.mark.asyncio
async def test_case7_authorised_recovery_opens_a_new_epoch():
    db = FakeDB([LOSS] * 7)
    before = list(db.profits)
    with patched(db):
        event = await record_recovery(acknowledged_by='operator-1',
                                      reason='reviewed the streak, no execution defect')
        assert event['consecutive_losses_before'] == 7
        # The epoch boundary now excludes the acknowledged losing tail.
        db.epoch = event['epoch_started_at']
        after = await loss_streak_state()

    assert after.consecutive_losses == 0
    assert not after.halt_active
    assert not after.manual_recovery_required
    assert db.profits == before, 'recovery must not touch trade history'
    # Admission is handed back to the remaining risk gates, not force-allowed.
    assert evaluate_new_trade(snapshot(0), limits()).allowed


@pytest.mark.asyncio
async def test_case7_recovery_does_not_bypass_other_risk_gates():
    db = FakeDB([LOSS] * 7)
    with patched(db):
        event = await record_recovery(acknowledged_by='operator-1', reason='ack')
        db.epoch = event['epoch_started_at']
        state = await loss_streak_state()
    assert not state.halt_active
    # Capacity still applies: a cleared streak is not a free pass.
    blocked = evaluate_new_trade(snapshot(0, open_count=2), limits())
    assert not blocked.allowed


@pytest.mark.asyncio
async def test_case7_recovery_requires_a_reason():
    db = FakeDB([LOSS] * 7)
    with patched(db):
        with pytest.raises(RecoveryRejected, match='reason'):
            await record_recovery(acknowledged_by='operator-1', reason='   ')
    assert db.inserted == [], 'a rejected recovery must not persist anything'


# ------------------------------------------------ Case 8: unauthorised recovery

@pytest.mark.asyncio
async def test_case8_recovery_without_an_operator_identity_is_refused():
    db = FakeDB([LOSS] * 7)
    with patched(db):
        with pytest.raises(RecoveryRejected, match='operator'):
            await record_recovery(acknowledged_by='', reason='ack')
    assert db.inserted == [], 'no state mutation on a denied attempt'


# ------------------------------------- Case 9: recovery with open positions

@pytest.mark.asyncio
async def test_case9_recovery_refused_while_positions_remain_open():
    db = FakeDB([LOSS] * 7, open_positions=1)
    with patched(db):
        with pytest.raises(RecoveryRejected, match='open'):
            await record_recovery(acknowledged_by='operator-1', reason='ack')
    assert db.inserted == []


# --------------------------------------------------- Case 10: idempotency

@pytest.mark.asyncio
async def test_case10_second_recovery_is_refused_not_duplicated():
    db = FakeDB([LOSS] * 7)
    with patched(db):
        event = await record_recovery(acknowledged_by='operator-1', reason='ack')
        db.epoch = event['epoch_started_at']
        # The halt is gone, so there is nothing left to acknowledge.
        with pytest.raises(RecoveryRejected, match='no active loss-streak halt'):
            await record_recovery(acknowledged_by='operator-1', reason='ack again')
    assert len(db.inserted) == 1, 'exactly one epoch may be opened per incident'


# ---------------------------------------------- Case 11: historical integrity

@pytest.mark.asyncio
async def test_case11_recovery_never_rewrites_history():
    profits = [LOSS] * 7
    db = FakeDB(profits)
    stamped_before = db._stamped()
    with patched(db):
        await record_recovery(acknowledged_by='operator-1', reason='ack')
    assert db.profits == profits
    assert db._stamped() == stamped_before
    assert len(db.profits) == 7, 'no rows deleted'


# ------------------------------------------ Case 12: restart after recovery

@pytest.mark.asyncio
async def test_case12_new_epoch_survives_a_fresh_process():
    db = FakeDB([LOSS] * 7)
    with patched(db):
        event = await record_recovery(acknowledged_by='operator-1', reason='ack')
    # A fresh process re-reads the same persisted epoch from the database.
    revived = FakeDB([LOSS] * 7, epoch=event['epoch_started_at'])
    with patched(revived):
        state = await loss_streak_state()
    assert state.consecutive_losses == 0
    assert not state.halt_active, 'the acknowledged streak must not reactivate on restart'
    assert state.epoch_started_at == event['epoch_started_at']


# --------------------------------------- Case 13: protection is not disabled

@pytest.mark.asyncio
async def test_case13_seven_new_losses_after_recovery_halt_again():
    db = FakeDB([LOSS] * 7)
    with patched(db):
        event = await record_recovery(acknowledged_by='operator-1', reason='ack')
    epoch = event['epoch_started_at']
    # Seven fresh losses, all stamped after the boundary.
    post = FakeDB([LOSS] * 7, epoch=epoch)
    post._stamped = lambda: [(epoch + timedelta(hours=i + 1), p)
                             for i, p in enumerate(post.profits)]
    with patched(post):
        state = await loss_streak_state()
    assert state.consecutive_losses == 7
    assert state.halt_active, 'recovery must not permanently disable the breaker'
    assert state.manual_recovery_required


# ------------------------------------------------- Case 14: telemetry parity

@pytest.mark.asyncio
async def test_case14_displayed_streak_equals_the_admission_streak():
    """The status surface and evaluate_new_trade must read one interpretation."""
    db = FakeDB([LOSS] * 7)
    with patched(db):
        state = await loss_streak_state()
    decision = evaluate_new_trade(snapshot(state.consecutive_losses), limits())
    assert decision.consecutive_losses == state.consecutive_losses
    assert (decision.reason == 'loss_streak_halt') == state.halt_active


@pytest.mark.asyncio
async def test_case14_effective_start_moves_with_the_epoch():
    db = FakeDB([LOSS] * 7)
    with patched(db):
        base = await loss_streak_state()
        assert base.effective_start == learning_clean_start()
        event = await record_recovery(acknowledged_by='operator-1', reason='ack')
        db.epoch = event['epoch_started_at']
        after = await loss_streak_state()
    assert after.effective_start == event['epoch_started_at']
    assert after.effective_start > base.effective_start


# --------------------------------------- Case 15: operational-health honesty

@pytest.mark.asyncio
async def test_case15_running_scanner_with_active_halt_is_not_reported_healthy():
    db = FakeDB([LOSS] * 7)
    with patched(db):
        state = await loss_streak_state()
    # Scanner running (not paused) yet admissions refused: must not read healthy.
    assert operational_state(state, is_paused=False) != TRADING_ACTIVE
    assert state.halt_active


# --------------------------------------------------- migration fail-safety

@pytest.mark.asyncio
async def test_no_epoch_on_record_reproduces_pre_migration_behaviour():
    """An empty risk_recovery_events table must change nothing."""
    db = FakeDB([LOSS] * 7, epoch=None)
    with patched(db):
        state = await loss_streak_state()
    assert state.effective_start == learning_clean_start()
    assert state.halt_active, 'migrating must never silently clear an active halt'
    assert state.epoch_started_at is None


# ------------------------------------- GATE-B: the shared serialization lock

@pytest.mark.asyncio
async def test_recovery_takes_the_shared_advisory_lock_before_reading_state():
    """RISK-1A proved an unlocked re-read was racy; the lock must be taken."""
    from shared.risk_epoch import RISK_ADMISSION_LOCK_KEY
    db = FakeDB([LOSS] * 7)
    with patched(db):
        await record_recovery(acknowledged_by='operator-1', reason='ack')
    assert db.locks_taken == [RISK_ADMISSION_LOCK_KEY], \
        'recovery must serialise on the same key the admission path uses'


@pytest.mark.asyncio
async def test_rejected_recovery_still_serialised_and_wrote_nothing():
    from shared.risk_epoch import RISK_ADMISSION_LOCK_KEY
    db = FakeDB([LOSS] * 7, open_positions=1)
    with patched(db):
        with pytest.raises(RecoveryRejected):
            await record_recovery(acknowledged_by='operator-1', reason='ack')
    assert db.locks_taken == [RISK_ADMISSION_LOCK_KEY]
    assert db.inserted == []


@pytest.mark.asyncio
async def test_epoch_timestamp_is_not_supplied_by_the_application():
    """The INSERT must use NOW(); FakeDB.fetchrow asserts it, this pins intent."""
    import inspect
    from shared import risk_epoch
    source = inspect.getsource(risk_epoch.record_recovery)
    assert 'VALUES (NOW()' in source
    assert 'datetime.now' not in source, \
        'application wall-clock must not define the recovery boundary'
