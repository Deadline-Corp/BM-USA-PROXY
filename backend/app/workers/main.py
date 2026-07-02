"""ARQ worker entrypoint.

Stage 1 stands up the worker process with a heartbeat cron so `/health/worker` is
meaningful. The real job registry (provisioning, expiry sweeper, reconciliation,
posting, broadcasts, outbox) lands in Stages 3–4 per 02_Backend §6.
"""

from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import configure_logging, log


async def heartbeat(ctx: dict) -> None:
    """Refresh a liveness key so /health/worker can confirm the worker is running."""
    redis = ctx["redis"]
    await redis.set("worker:alive:heartbeat", "1", expire=180)


async def startup(ctx: dict) -> None:
    configure_logging()
    await ctx["redis"].set("worker:alive:startup", "1", expire=180)
    log.info("worker.startup")


async def shutdown(ctx: dict) -> None:
    log.info("worker.shutdown")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = startup
    on_shutdown = shutdown
    functions: list = []  # populated in Stage 3/4
    cron_jobs = [cron(heartbeat, second={0, 20, 40})]
