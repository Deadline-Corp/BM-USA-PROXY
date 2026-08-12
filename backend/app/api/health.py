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


# Jobs that must be beating for the system to be doing its work at all. Each refreshes
# `worker:alive:<job>` with a 180s expiry, so a missing key means "has not run in three
# minutes" — well past every one of these schedules.
#
# `daily_reconciliation` is deliberately absent: it runs once a night, so its heartbeat is
# expired for 23 hours out of 24 and requiring it would make this endpoint permanently red.
_REQUIRED_JOBS = (
    "watch_onchain_deposits",  # the only thing that sees money arrive
    "watch_payout_transfers",
    "send_outbox",             # nothing reaches a customer without it
    "expiry_sweeper",          # access outlives its purchase without it
    "sync_connections",        # the catalogue goes stale without it
)


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
        keys = [k async for k in redis_client.scan_iter("worker:alive:*")]
        beats = {k.split(":", 2)[-1] for k in keys}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}", "stale": list(_REQUIRED_JOBS)}
    stale = [job for job in _REQUIRED_JOBS if job not in beats]
    return {
        "ok": not stale,
        "stale": stale,
        "alive": sorted(beats),
    }
