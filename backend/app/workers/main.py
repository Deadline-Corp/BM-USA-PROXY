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
    # A tick that cannot finish must be abandoned, not left holding a slot. arq's default
    # is 300s — twenty deposit-watcher ticks — so one wedged pass would sit on a worker
    # slot for five minutes while the schedule kept firing behind it. 90s is generous
    # against the measured tick (3.8s across five chains) and short enough that a stuck
    # RPC costs one pass, not twenty. Every job here is idempotent, so an abandoned pass
    # is retried by the next one rather than needing recovery.
    job_timeout = 90
    max_jobs = 20
    cron_jobs = [
        cron(jobs.send_outbox, second={0, 10, 20, 30, 40, 50}, run_at_startup=True),
        cron(jobs.expiry_sweeper, second=0),
        # Buyer-scheduled IP rotation. Every minute because the shortest interval an
        # access can ask for is five, and a pass that finds nothing is one indexed read.
        cron(jobs.auto_rotate_sweeper, second=25),
        cron(jobs.invoice_expirer, second=30),
        cron(jobs.reconcile_invoices, minute=_FIVE_MIN, second=15),
        cron(jobs.watch_onchain_deposits, second={0, 15, 30, 45}, run_at_startup=True),
        # payout confirmation — a sent payout should flip to 'paid' within ~a minute
        cron(jobs.watch_payout_transfers, second={10, 40}, run_at_startup=True),
        # Every minute, not hourly. The hold is a business setting an operator can set to
        # zero, and "no hold" has to mean the money is withdrawable now — not at the top of
        # the next hour. One indexed UPDATE over rows whose hold has expired; at a 14-day
        # hold the extra passes find nothing and cost nothing.
        cron(jobs.release_referral_holds, second=45),
        cron(jobs.daily_reconciliation, hour={0}, minute={20}, run_at_startup=False),
        # Every minute: the pool is what the catalogue sells from, so a phone going offline
        # or a newly added one should not stay invisible for five. Costs two iproxy calls
        # per pass whatever the pool size — both endpoints return the whole account.
        cron(jobs.sync_connections, second=45),
        # One request per phone, so it walks the pool in batches rather than sweeping it
        # every minute like sync_connections does. Five minutes is fast enough for a hold
        # created by hand in the iproxy console — nobody does that twice a minute.
        cron(jobs.sync_external_holds, minute=_FIVE_MIN, second=50),
        # Low-stock alert. Fires every minute and decides for itself whether it is due —
        # the cadence is `pool_check_interval_minutes` in the console, and a schedule fixed
        # here would mean a redeploy every time somebody wanted to change it.
        cron(jobs.pool_watermark, second=55),
        # Handles drift silently: Telegram does not announce a rename, and the data it
        # attaches to a visit is cached by the client. Hourly, oldest check first, so the
        # cost per pass is fixed whatever the size of the client list.
        cron(jobs.refresh_client_handles, minute={7}),
        cron(jobs.publish_scheduled_posts, second=5),
        cron(jobs.process_broadcasts, second={5, 20, 35, 50}),
    ]
