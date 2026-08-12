"""What "the worker is alive" means, in one place.

Both the API's ``/health/worker`` and the worker's own healthcheck answer the same
question, so they must answer it the same way — otherwise the operator's dashboard and
the platform's restart decision disagree about whether anything is wrong.
"""

from __future__ import annotations

from app.core.redis import redis_client

# Jobs that must be beating for the system to be doing its work at all. Each refreshes
# `worker:alive:<job>` with a 180s expiry, so a missing key means "has not run in three
# minutes" — well past every one of these schedules.
#
# `daily_reconciliation` is deliberately absent: it runs once a night, so its heartbeat is
# expired for 23 hours out of 24 and requiring it would make this permanently red.
REQUIRED_JOBS = (
    "watch_onchain_deposits",  # the only thing that sees money arrive
    "watch_payout_transfers",
    "send_outbox",             # nothing reaches a customer without it
    "expiry_sweeper",          # access outlives its purchase without it
    "sync_connections",        # the catalogue goes stale without it
)


async def alive_jobs() -> set[str]:
    """Job names whose heartbeat has not expired."""
    return {k.split(":", 2)[-1] async for k in redis_client.scan_iter("worker:alive:*")}


async def stale_jobs() -> list[str]:
    """Required jobs that are not beating. Empty means healthy."""
    beats = await alive_jobs()
    return [job for job in REQUIRED_JOBS if job not in beats]
