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


async def ack(event_id: int, owner: str):
    return await Database.execute(
        """UPDATE outbox_events SET status='completed',processed_at=NOW(),
                  locked_at=NULL,locked_by=NULL,last_error=NULL
           WHERE id=$1 AND status='processing' AND locked_by=$2""",
        event_id, owner)


async def fail(event_id: int, owner: str, error: BaseException,
               retry_delay_seconds: int = 60):
    message = f'{type(error).__name__}: {str(error) or repr(error)}'[:1000]
    return await Database.execute(
        """UPDATE outbox_events
           SET status=CASE WHEN attempts>=max_attempts THEN 'dead' ELSE 'pending' END,
               available_at=CASE WHEN attempts>=max_attempts THEN available_at
                                 ELSE NOW()+make_interval(secs=>$4) END,
               locked_at=NULL,locked_by=NULL,last_error=$3,
               processed_at=CASE WHEN attempts>=max_attempts THEN NOW() ELSE NULL END
           WHERE id=$1 AND status='processing' AND locked_by=$2""",
        event_id, owner, message, retry_delay_seconds)
