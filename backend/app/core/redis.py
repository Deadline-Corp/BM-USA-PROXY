"""Shared async Redis client (FSM storage, locks, rate-limit, cache, ARQ broker)."""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import settings

redis_client: Redis = Redis.from_url(
    settings.redis_url,
    encoding="utf-8",
    decode_responses=True,
)


async def redis_ping() -> bool:
    try:
        return bool(await redis_client.ping())
    except Exception:
        return False
