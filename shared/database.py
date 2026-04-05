"""
إدارة الاتصال بقاعدة البيانات PostgreSQL
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional
import asyncpg
from shared.config import config

logger = logging.getLogger(__name__)

class Database:
    _pool: Optional[asyncpg.Pool] = None

    @classmethod
    async def connect(cls):
        """إنشاء Connection Pool"""
        if cls._pool is None:
            cls._pool = await asyncpg.create_pool(
                dsn=config.postgres_dsn,
                min_size=2,
                max_size=10,
                command_timeout=60,
                server_settings={
                    'application_name': 'trading_bot'
                }
            )
            logger.info("✅ اتصال PostgreSQL ناجح")

    @classmethod
    async def disconnect(cls):
        """إغلاق Connection Pool"""
        if cls._pool:
            await cls._pool.close()
            cls._pool = None

    @classmethod
    @asynccontextmanager
    async def acquire(cls):
        """الحصول على connection من الـ Pool"""
        if cls._pool is None:
            await cls.connect()
        async with cls._pool.acquire() as conn:
            yield conn

    @classmethod
    async def fetch(cls, query: str, *args):
        """تنفيذ استعلام وإرجاع نتائج"""
        async with cls.acquire() as conn:
            return await conn.fetch(query, *args)

    @classmethod
    async def fetchrow(cls, query: str, *args):
        """تنفيذ استعلام وإرجاع صف واحد"""
        async with cls.acquire() as conn:
            return await conn.fetchrow(query, *args)

    @classmethod
    async def fetchval(cls, query: str, *args):
        """تنفيذ استعلام وإرجاع قيمة واحدة"""
        async with cls.acquire() as conn:
            return await conn.fetchval(query, *args)

    @classmethod
    async def execute(cls, query: str, *args):
        """تنفيذ استعلام بدون إرجاع نتائج"""
        async with cls.acquire() as conn:
            return await conn.execute(query, *args)

    @classmethod
    async def executemany(cls, query: str, args_list):
        """تنفيذ استعلام متعدد"""
        async with cls.acquire() as conn:
            return await conn.executemany(query, args_list)
