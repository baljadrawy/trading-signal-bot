"""Authoritative loss-streak state: one interpretation for admission and telemetry.

The hard loss-streak halt is a pure function of the *effective* streak, and the
effective streak is the tail run of net-losing closed trades since the effective
risk start. Two things can therefore end a halt, and only two:

1. a genuinely winning close lands at the tail (the pre-existing, unchanged
   autonomous path -- this is how the 2026-08-17 production halt cleared); or
2. an authorised operator acknowledges the halt, which records a recovery epoch
   whose boundary excludes the acknowledged losing tail from future counting.

Route 2 exists because route 1 is impossible when no position is open: admission
is refused, so nothing can close, so nothing can reset the streak.

Everything here is read from the same helpers that trade_tracker's admission path
uses, so a status display can never disagree with an admission decision.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from shared.config import config
from shared.database import Database


# Operational states an operator must be able to tell apart. The dangerous case
# this module exists to make visible is LOSS_STREAK_RECOVERY_REQUIRED: the
# scanner runs and signals are produced, but every admission is refused.
TRADING_ACTIVE = 'TRADING_ACTIVE'
TRADING_PAUSED = 'TRADING_PAUSED'
LOSS_STREAK_HALTED = 'LOSS_STREAK_HALTED'
LOSS_STREAK_RECOVERY_REQUIRED = 'LOSS_STREAK_RECOVERY_REQUIRED'


# Transaction-scoped advisory lock shared by the two paths that must never
# interleave: acknowledging a recovery (which asserts a flat book) and creating
# an open position (which makes the book non-flat). Stable, project-specific,
# and used by nothing else in this repository. Chosen once and never derived at
# runtime, so both paths provably request the same key.
RISK_ADMISSION_LOCK_KEY = 7205_1053


async def acquire_risk_admission_lock(conn) -> None:
    """Serialise recovery against open-position creation.

    Transaction-scoped: released automatically on COMMIT, ROLLBACK, or backend
    crash, so it needs no cleanup path and cannot leak a stuck lock. Callers
    must hold it only across the minimal state transition -- never across
    network, exchange, or formatting work.
    """
    await conn.execute('SELECT pg_advisory_xact_lock($1)', RISK_ADMISSION_LOCK_KEY)


def learning_clean_start() -> datetime:
    """The configured history floor, always tz-aware UTC."""
    value = datetime.fromisoformat(config.LEARNING_CLEAN_START.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def tail_loss_streak(net_results) -> int:
    """Length of the trailing run of net-losing closes.

    A net-zero close counts as a win and ends the run, matching the existing
    production semantics exactly (`net >= 0` breaks).
    """
    streak = 0
    for net in reversed(list(net_results)):
        if net >= 0:
            break
        streak += 1
    return streak


async def current_epoch_start(db=None) -> datetime | None:
    """Newest acknowledged recovery boundary, or None when none was ever declared.

    `db` accepts either the Database facade or a live connection, so the locked
    admission path and the unlocked telemetry path run the *same* query.
    """
    value = await (db or Database).fetchval(
        'SELECT MAX(epoch_started_at) FROM risk_recovery_events')
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


async def effective_risk_start(db=None) -> datetime:
    """Start boundary for every streak calculation.

    With no recovery on record this is exactly LEARNING_CLEAN_START, so the
    behaviour is identical to the pre-remediation system.
    """
    clean_start = learning_clean_start()
    epoch = await current_epoch_start(db)
    return max(clean_start, epoch) if epoch else clean_start


async def effective_consecutive_losses(db=None) -> int:
    """The authoritative streak. One implementation, every caller.

    Sharing this function between the admission path (holding the advisory lock,
    on its own connection) and the telemetry path is what makes parity
    structural rather than a convention someone has to remember.
    """
    start = await effective_risk_start(db)
    rows = await (db or Database).fetch("""
        SELECT profit_usdt
        FROM trade_results
        WHERE exit_time >= $1::timestamptz
        ORDER BY exit_time, id
    """, start)
    fee_usdt = config.TRADE_AMOUNT_USDT * config.FEE_ROUNDTRIP_PCT / 100.0
    return tail_loss_streak(float(r['profit_usdt']) - fee_usdt for r in rows)


async def loss_streak_halt_active(db=None) -> bool:
    """Whether the hard breaker currently refuses admission."""
    return await effective_consecutive_losses(db) >= config.STOP_ON_CONSECUTIVE_LOSSES


@dataclass(frozen=True)
class LossStreakState:
    effective_start: datetime
    consecutive_losses: int
    halt_threshold: int
    halt_active: bool
    manual_recovery_required: bool
    open_positions: int
    epoch_started_at: datetime | None


async def loss_streak_state() -> LossStreakState:
    """The single authoritative read of loss-streak state.

    `manual_recovery_required` is the important field: it distinguishes a halt
    that can still clear on its own (a position is open and may yet close green)
    from one that cannot (flat book -- no future close can occur at all).
    """
    start = await effective_risk_start()
    streak = await effective_consecutive_losses()
    open_positions = await Database.fetchval(
        "SELECT COUNT(*) FROM active_trades WHERE status='open'") or 0
    threshold = config.STOP_ON_CONSECUTIVE_LOSSES
    halt_active = streak >= threshold
    return LossStreakState(
        effective_start=start,
        consecutive_losses=streak,
        halt_threshold=threshold,
        halt_active=halt_active,
        # A halt with a flat book cannot clear autonomously: no admission means
        # no close, and no close means no winning tail.
        manual_recovery_required=halt_active and open_positions == 0,
        open_positions=int(open_positions),
        epoch_started_at=await current_epoch_start(),
    )


def operational_state(state: LossStreakState, is_paused: bool) -> str:
    """Classify what an operator is actually looking at.

    Risk halt outranks pause in the display because clearing the pause alone
    leaves admissions refused -- the exact confusion this classification exists
    to prevent.
    """
    if state.manual_recovery_required:
        return LOSS_STREAK_RECOVERY_REQUIRED
    if state.halt_active:
        return LOSS_STREAK_HALTED
    if is_paused:
        return TRADING_PAUSED
    return TRADING_ACTIVE


class RecoveryRejected(Exception):
    """Recovery preconditions not met; no state was changed."""


async def record_recovery(acknowledged_by: str, reason: str) -> dict:
    """Acknowledge an active loss-streak halt and open a new streak epoch.

    Refuses unless a halt is genuinely active and the book is flat. Never edits
    or deletes trade_results -- it only moves the boundary from which future
    streaks are counted, so the acknowledged incident stays fully auditable.
    """
    reason = (reason or '').strip()
    if not reason:
        raise RecoveryRejected('a reason is required: recovery is an acknowledgement, not a reset')
    acknowledged_by = (acknowledged_by or '').strip()
    if not acknowledged_by:
        raise RecoveryRejected('an authorised operator identity is required')

    async with Database.acquire() as conn:
        async with conn.transaction():
            # Everything the decision depends on is read AFTER the lock, on the
            # locked connection. A concurrent admission is either already
            # committed (and therefore visible to the read below) or blocked
            # until this transaction ends -- there is no interleaving in which a
            # position is created behind a flat-book assertion.
            await acquire_risk_admission_lock(conn)

            streak = await effective_consecutive_losses(conn)
            threshold = config.STOP_ON_CONSECUTIVE_LOSSES
            if streak < threshold:
                # Idempotency: a second call finds no halt and changes nothing.
                raise RecoveryRejected(
                    f'no active loss-streak halt to recover '
                    f'(consecutive_losses={streak} < {threshold})')
            open_now = await conn.fetchval(
                "SELECT COUNT(*) FROM active_trades WHERE status='open'") or 0
            if open_now:
                raise RecoveryRejected(
                    f'{open_now} position(s) still open; resolve them first — '
                    'an open position may still close green and clear the halt on its own')

            # NOW() so the boundary and trade_results.exit_time (also NOW())
            # come from one clock. An application-stamped boundary could drift
            # against the database and silently drop a real post-recovery loss.
            row = await conn.fetchrow("""
                INSERT INTO risk_recovery_events
                    (epoch_started_at, acknowledged_by, reason, halt_reason,
                     consecutive_losses_before, open_positions_at_recovery)
                VALUES (NOW(), $1, $2, 'loss_streak_halt', $3, 0)
                RETURNING id, epoch_started_at
            """, acknowledged_by, reason, streak)
    return {
        'id': row['id'],
        'epoch_started_at': row['epoch_started_at'],
        'acknowledged_by': acknowledged_by,
        'reason': reason,
        'consecutive_losses_before': streak,
    }
