"""Runtime guard against starting application code on an old database schema."""
from shared.database import Database

REQUIRED_SCHEMA_VERSION = 8


async def require_schema(service_name: str) -> None:
    try:
        version = await Database.fetchval('SELECT MAX(version) FROM schema_migrations')
    except Exception as exc:
        raise RuntimeError(
            f'{service_name}: schema migrations are missing; run database/migrate.py') from exc
    if int(version or 0) < REQUIRED_SCHEMA_VERSION:
        raise RuntimeError(
            f'{service_name}: database schema {version or 0} is older than required '
            f'{REQUIRED_SCHEMA_VERSION}; run database/migrate.py')
