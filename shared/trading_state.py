"""Persistent trading pause state layered on the existing daily risk table.

Fail-closed contract: new trading is permitted only by an explicit, well-formed
decision row whose latest value is the owner's `manual_resume`. Absent or
malformed state never reads as permission — a wiped table or a restored backup
without decision rows halts entry until the owner sends /resume.

Database errors are deliberately NOT caught here: every caller already runs
inside a loop that treats an exception as a failed cycle (no candidate, no
delivery, no admission) and reports it through its health heartbeat. Turning
an outage into an ordinary pause would hide it from that telemetry.
"""
from shared.database import Database

# Distinct from 'manual_pause' and the 'risk:<reason>' halts written by the
# tracker, so /status and logs show that the state itself is the problem.
RISK_STATE_MISSING = 'risk_state_missing'
RISK_STATE_INCONSISTENT = 'risk_state_inconsistent'


async def get_pause_state() -> tuple[bool, str | None]:
    """Return the latest explicit pause/resume decision, surviving UTC day rollover."""
    # NULLS FIRST (the DESC default, stated explicitly): a decision row with no
    # date would otherwise outrank every dated decision, so it must be the row
    # we inspect — and reject.
    row = await Database.fetchrow("""
        SELECT is_trading_paused, pause_reason,
               (date IS NULL OR date > CURRENT_DATE) AS date_invalid
        FROM risk_management
        WHERE is_trading_paused=true OR pause_reason='manual_resume'
        ORDER BY date DESC NULLS FIRST, id DESC
        LIMIT 1
    """)
    if not row:
        return True, RISK_STATE_MISSING
    paused = row['is_trading_paused']
    # A future-dated row would permanently outrank today's pause, so it cannot
    # be trusted to carry a resume either.
    if row['date_invalid'] or paused is None:
        return True, RISK_STATE_INCONSISTENT
    if paused:
        if row['pause_reason'] == 'manual_resume':
            return True, RISK_STATE_INCONSISTENT
        return True, row['pause_reason'] or 'trading_paused'
    if row['pause_reason'] == 'manual_resume':
        return False, None
    return True, RISK_STATE_INCONSISTENT
