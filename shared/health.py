"""Best-effort service heartbeats and strict container health checks."""
import asyncio
import json
import logging
import os
import sys
from typing import Any, Mapping, Optional

from shared.database import Database

logger = logging.getLogger(__name__)


def _metadata(value: Optional[Mapping[str, Any]]) -> str:
    return json.dumps(dict(value or {}), default=str, ensure_ascii=False)


async def mark_started(service_name: str, metadata: Optional[Mapping[str, Any]] = None):
    """Register a process start. Monitoring failures never interrupt business work."""
    try:
        await Database.execute(
            """INSERT INTO service_heartbeats
                   (service_name, last_started_at, consecutive_errors, metadata, updated_at)
               VALUES ($1, NOW(), 0, $2::jsonb, NOW())
               ON CONFLICT (service_name) DO UPDATE
               SET last_started_at=NOW(), metadata=$2::jsonb, updated_at=NOW()""",
            service_name, _metadata(metadata))
    except Exception as exc:
        logger.warning("heartbeat start failed for %s: %s", service_name, exc)


async def mark_success(service_name: str, metadata: Optional[Mapping[str, Any]] = None):
    try:
        await Database.execute(
            """INSERT INTO service_heartbeats
                   (service_name, last_started_at, last_success_at, consecutive_errors, last_error, metadata, updated_at)
               VALUES ($1, NOW(), NOW(), 0, NULL, $2::jsonb, NOW())
               ON CONFLICT (service_name) DO UPDATE
               SET last_success_at=NOW(), consecutive_errors=0, last_error=NULL,
                   metadata=$2::jsonb, updated_at=NOW()""",
            service_name, _metadata(metadata))
    except Exception as exc:
        logger.warning("heartbeat success update failed for %s: %s", service_name, exc)


async def mark_failure(service_name: str, error: BaseException,
                       metadata: Optional[Mapping[str, Any]] = None):
    try:
        await Database.execute(
            """INSERT INTO service_heartbeats
                   (service_name, last_started_at, last_error_at, consecutive_errors, last_error, metadata, updated_at)
               VALUES ($1, NOW(), NOW(), 1, $2, $3::jsonb, NOW())
               ON CONFLICT (service_name) DO UPDATE
               SET last_error_at=NOW(), consecutive_errors=service_heartbeats.consecutive_errors+1,
                   last_error=$2, metadata=$3::jsonb, updated_at=NOW()""",
            service_name, f"{type(error).__name__}: {error}"[:1000], _metadata(metadata))
    except Exception as exc:
        logger.warning("heartbeat failure update failed for %s: %s", service_name, exc)


async def check(service_name: str, max_age_seconds: int) -> tuple[bool, str]:
    await Database.connect()
    try:
        row = await Database.fetchrow(
            """SELECT last_success_at, consecutive_errors,
                      EXTRACT(EPOCH FROM (NOW() - last_success_at)) AS age_seconds
               FROM service_heartbeats WHERE service_name=$1""", service_name)
        if not row or row['last_success_at'] is None:
            return False, f"no successful heartbeat for {service_name}"
        age = float(row['age_seconds'])
        if row['consecutive_errors'] > 0:
            return False, f"{service_name} has {row['consecutive_errors']} consecutive errors"
        if age > max_age_seconds:
            return False, f"stale heartbeat for {service_name}: {age:.0f}s"
        return True, f"ok: age={age:.0f}s errors={row['consecutive_errors']}"
    finally:
        await Database.disconnect()


def main() -> int:
    service_name = os.environ.get('SERVICE_NAME', '').strip()
    max_age = int(os.environ.get('HEALTH_MAX_AGE_SECONDS', '600'))
    if not service_name:
        print("SERVICE_NAME is required", file=sys.stderr)
        return 2
    try:
        healthy, message = asyncio.run(check(service_name, max_age))
    except Exception as exc:
        print(f"health check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0 if healthy else 1


if __name__ == '__main__':
    raise SystemExit(main())
