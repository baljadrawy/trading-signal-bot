import asyncio
import pytest

from shared import schema


def test_require_schema_accepts_current(monkeypatch):
    async def fetchval(_query):
        return schema.REQUIRED_SCHEMA_VERSION
    monkeypatch.setattr(schema.Database, 'fetchval', fetchval)
    asyncio.run(schema.require_schema('test'))


def test_require_schema_rejects_old(monkeypatch):
    async def fetchval(_query):
        return schema.REQUIRED_SCHEMA_VERSION - 1
    monkeypatch.setattr(schema.Database, 'fetchval', fetchval)
    with pytest.raises(RuntimeError, match='older than required'):
        asyncio.run(schema.require_schema('test'))
