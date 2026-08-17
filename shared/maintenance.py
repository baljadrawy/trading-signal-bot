"""Bounded retention for ephemeral pipeline records."""
from shared.database import Database


async def maintain_pipeline() -> dict:
    expired = await Database.execute(
        """UPDATE analysis_results
           SET processing_status='expired', decision_reason='stale_analysis', decision_at=NOW()
           WHERE signal_generated=false
             AND processing_status IN ('pending','evaluated')
             AND analyzed_at < NOW() - INTERVAL '2 hours'""")
    deleted = await Database.execute(
        "DELETE FROM scan_candidates WHERE scan_time < NOW() - INTERVAL '1 hour'")
    return {'analysis_expired': expired, 'scan_deleted': deleted}
