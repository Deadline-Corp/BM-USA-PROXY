"""ARQ worker entrypoint — cron schedule for the automation layer (02_Backend §6).

Payment webhooks process inline in the API; these crons are the safety-nets and the
time-driven work: access expiry, invoice expiry, reconciliation, referral release,
notification delivery, and iproxy inventory sync.
"""

from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import configure_logging, log
from app.workers.tasks import jobs


async def startup(ctx: dict) -> None:
    configure_logging()
    await ctx["redis"].set("worker:alive:startup", "1", ex=180)
    log.info("worker.startup")


async def shutdown(ctx: dict) -> None:
    log.info("worker.shutdown")


_FIVE_MIN = set(range(0, 60, 5))


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = startup
    on_shutdown = shutdown
    functions: list = []  # webhook processing is inline; all work below is cron-driven
    cron_jobs = [
        cron(jobs.send_outbox, second={0, 10, 20, 30, 40, 50}, run_at_startup=True),
        cron(jobs.expiry_sweeper, second=0),
        cron(jobs.invoice_expirer, second=30),
        cron(jobs.reconcile_invoices, minute=_FIVE_MIN, second=15),
        cron(jobs.release_referral_holds, minute=0, second=45),
        cron(jobs.sync_connections, minute=_FIVE_MIN, second=45),
        cron(jobs.publish_scheduled_posts, second=5),
        cron(jobs.process_broadcasts, second={5, 20, 35, 50}),
    ]
