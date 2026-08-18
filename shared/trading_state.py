"""Persistent trading pause state layered on the existing daily risk table."""
from shared.database import Database


async def get_pause_state() -> tuple[bool, str | None]:
    """Return the latest explicit pause/resume decision, surviving UTC day rollover."""
    row = await Database.fetchrow("""
        SELECT is_trading_paused, pause_reason
        FROM risk_management
        WHERE is_trading_paused=true OR pause_reason='manual_resume'
        ORDER BY date DESC, id DESC
        LIMIT 1
    """)
    if not row or not row['is_trading_paused']:
        return False, None
    return True, row['pause_reason'] or 'trading_paused'
