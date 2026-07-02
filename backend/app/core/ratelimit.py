"""Redis-backed rate limiting and cooldowns (fixed-window)."""

from __future__ import annotations

from app.core.errors import RateLimited
from app.core.redis import redis_client


async def enforce(key: str, *, limit: int, window_sec: int) -> None:
    """Allow `limit` hits per `window_sec`. Raises RateLimited when exceeded."""
    full = f"rl:{key}"
    count = await redis_client.incr(full)
    if count == 1:
        await redis_client.expire(full, window_sec)
    if count > limit:
        ttl = await redis_client.ttl(full)
        raise RateLimited(f"too many requests for {key}", retry_after=max(ttl, 1))


async def cooldown(key: str, *, seconds: int) -> None:
    """One action per `seconds`. Raises RateLimited (with retry_after) if still cooling."""
    full = f"cd:{key}"
    if not await redis_client.set(full, "1", nx=True, ex=seconds):
        ttl = await redis_client.ttl(full)
        raise RateLimited(f"cooldown active for {key}", retry_after=max(ttl, 1))
