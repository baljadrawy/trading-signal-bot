"""PostgreSQL transactional outbox with leases, retries, and dead-lettering."""
import json
import socket
import uuid
from typing import Any, Mapping, Optional

from shared.database import Database

DEFAULT_LEASE_SECONDS = 300


def worker_id(component: str) -> str:
    return f'{component}:{socket.gethostname()}:{uuid.uuid4().hex[:12]}'


async def enqueue(conn, event_type: str, aggregate_type: str, aggregate_id: int,
                  payload: Optional[Mapping[str, Any]] = None) -> Optional[int]:
    return await conn.fetchval(
        """INSERT INTO outbox_events(event_type,aggregate_type,aggregate_id,payload)
           VALUES($1,$2,$3,$4::jsonb)
           ON CONFLICT(event_type,aggregate_type,aggregate_id) DO NOTHING
           RETURNING id""",
        event_type, aggregate_type, aggregate_id,
        json.dumps(dict(payload or {}), default=str))


async def claim(event_type: str, owner: str, limit: int = 20,
                lease_seconds: int = DEFAULT_LEASE_SECONDS):
    return await Database.fetch(
        """WITH candidates AS (
               SELECT id FROM outbox_events
               WHERE event_type=$1
                 AND (status='pending' AND available_at<=NOW()
                      OR status='processing' AND locked_at < NOW()-make_interval(secs=>$4))
               ORDER BY id
               FOR UPDATE SKIP LOCKED
               LIMIT $3
           )
           UPDATE outbox_events e
           SET status='processing', locked_at=NOW(), locked_by=$2,
               attempts=e.attempts+1
           FROM candidates c WHERE e.id=c.id
           RETURNING e.*""",
        event_type, owner, limit, lease_seconds)


async def ack(event_id: int, owner: str, outcome: Optional[str] = None):
    """Complete a claimed event. `outcome` names the terminal state (A38), e.g. 'opened' or
    'terminal:STALE'; NULL when the caller has nothing more specific than 'completed'."""
    return await Database.execute(
        """UPDATE outbox_events SET status='completed',processed_at=NOW(),
                  locked_at=NULL,locked_by=NULL,last_error=NULL,outcome=$3
           WHERE id=$1 AND status='processing' AND locked_by=$2""",
        event_id, owner, (outcome or None) and str(outcome)[:64])


async def defer(event_id: int, owner: str, delay_seconds: float, reason: str):
    """Release a claimed event to be claimed again later WITHOUT consuming a retry attempt (A38).

    A deferral means "not yet": the event is waiting for a known future state (an admission
    window that is still open, a channel outage that is still transient). It is not a failure, so
    it must never move the event towards the dead-letter queue. The claim's attempt increment is
    returned and `deferrals` counts the wait instead. Callers bound every deferral by a deadline
    after which they ack a named terminal outcome or call fail(), so a deferral loop is finite.
    """
    return await Database.execute(
        """UPDATE outbox_events
           SET status='pending', attempts=GREATEST(attempts-1, 0), deferrals=deferrals+1,
               available_at=NOW()+make_interval(secs=>$3),
               locked_at=NULL, locked_by=NULL, last_error=$4
           WHERE id=$1 AND status='processing' AND locked_by=$2""",
        event_id, owner, max(1.0, float(delay_seconds)), f'deferred: {reason}'[:1000])


async def fail(event_id: int, owner: str, error: BaseException,
               retry_delay_seconds: int = 60):
    message = f'{type(error).__name__}: {str(error) or repr(error)}'[:1000]
    return await Database.execute(
        """UPDATE outbox_events
           SET status=CASE WHEN attempts>=max_attempts THEN 'dead' ELSE 'pending' END,
               available_at=CASE WHEN attempts>=max_attempts THEN available_at
                                 ELSE NOW()+make_interval(secs=>$4) END,
               locked_at=NULL,locked_by=NULL,last_error=$3,
               processed_at=CASE WHEN attempts>=max_attempts THEN NOW() ELSE NULL END,
               outcome=CASE WHEN attempts>=max_attempts THEN 'retry_exhausted' ELSE NULL END
           WHERE id=$1 AND status='processing' AND locked_by=$2""",
        event_id, owner, message, retry_delay_seconds)


async def dead_letters_since(event_types, after: tuple, limit: int = 50):
    """Dead letters of `event_types` that died after the (processed_at, id) watermark `after`,
    oldest first. Read-only; used to make new dead letters observable (A38)."""
    return await Database.fetch(
        """SELECT id, event_type, aggregate_type, aggregate_id, attempts, deferrals,
                  last_error, created_at, processed_at
           FROM outbox_events
           WHERE status='dead' AND event_type = ANY($1::text[])
             AND (processed_at, id) > ($2::timestamp, $3::bigint)
           ORDER BY processed_at, id
           LIMIT $4""",
        list(event_types), after[0], int(after[1]), limit)
