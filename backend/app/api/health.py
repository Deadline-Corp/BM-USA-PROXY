"""Liveness/readiness endpoints for the platform healthcheck + uptime monitor."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import SessionFactory
from app.core.redis import redis_client, redis_ping

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    db_ok = True
    try:
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    redis_ok = await redis_ping()
    ok = db_ok and redis_ok
    return {"ok": ok, "db": db_ok, "redis": redis_ok}


@router.get("/health/worker")
async def health_worker() -> dict[str, object]:
    """Report worker heartbeats. Each cron job refreshes ``worker:alive:<job>``."""
    try:
        keys = [k async for k in redis_client.scan_iter("worker:alive:*")]
        beats = {k.split(":", 2)[-1]: await redis_client.get(k) for k in keys}
    except Exception:
        return {"ok": False, "heartbeats": {}}
    return {"ok": bool(beats), "heartbeats": beats}
