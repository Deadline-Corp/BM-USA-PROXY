"""Liveness/readiness endpoints for the platform healthcheck + uptime monitor."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import SessionFactory
from app.core.redis import redis_ping
from app.workers.heartbeat import REQUIRED_JOBS, alive_jobs

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
    """Whether the worker is doing its job — not merely whether it once existed.

    This used to answer ok as long as *any* heartbeat was present, which is the answer you
    least want: `send_outbox` beating every ten seconds would keep the endpoint green while
    the deposit watcher had been dead for a day. Now a named set has to be beating, and the
    ones that are not are listed, so the answer says which part stopped.

    Point an uptime monitor at this, not at /health — /health is the API, and the API is
    fine when the worker is not.
    """
    try:
        beats = await alive_jobs()
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}", "stale": list(REQUIRED_JOBS)}
    stale = [job for job in REQUIRED_JOBS if job not in beats]
    return {"ok": not stale, "stale": stale, "alive": sorted(beats)}
