"""Process-wide resources: the database engine and the Redis client.

Held in a small container rather than module globals so that tests can build an
isolated instance, and so that shutdown is explicit. Nothing here knows about the
domain; it exists to be injected.
"""

from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backstop_api.settings import Settings


@dataclass(slots=True)
class Resources:
    engine: AsyncEngine
    redis: Redis

    @classmethod
    def create(cls, settings: Settings) -> Resources:
        engine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,
            echo=False,
        )
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return cls(engine=engine, redis=redis)

    async def aclose(self) -> None:
        await self.engine.dispose()
        await self.redis.aclose()

    async def check_database(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001 - a readiness probe reports, it does not raise
            return False
        return True

    async def check_redis(self) -> bool:
        try:
            return bool(await self.redis.ping())
        except Exception:  # noqa: BLE001 - same rationale as above
            return False
