"""Notification outbox — enqueue user-facing notifications (delivered by the worker)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationOutbox

# Template catalog (texts live in app_settings['notify_texts:<code>'], editable in admin).
#
# Every code here MUST have a default text in bot/notifier.py:DEFAULT_TEXTS, and a test
# holds the two lists together. A code in this set with no text renders as None, and the
# outbox marks the row `skipped` — the message is never sent and nothing says so. That is
# what happened to `payout_approved`. `invoice_expiring` was the same shape, minus the
# damage: never enqueued anywhere, no text, and an empty row on the admin Notifications
# screen. Removed rather than given a text nobody would ever send.
TEMPLATES = {
    "welcome",
    "access_issued",
    "accesses_issued",
    "provisioning_delayed",
    "access_expiring_soon",
    "access_expiring_10m",
    "trial_expiring_10m",
    "access_expired",
    "access_extended",
    "access_reissued",
    "refund_processed",
    "referral_joined",
    "referral_accrued",
    "referral_available",
    "payout_requested",
    "payout_approved",
    "payout_paid",
    "payout_rejected",
    "config_delivered",
    "operator_message",
    # Sent straight from the bot handler rather than through this outbox — it is listed
    # here so it appears on the Notifications screen and survives the settings whitelist.
    "bot_auto_reply",
}


async def enqueue(
    session: AsyncSession,
    *,
    user_id: int,
    template_code: str,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> None:
    stmt = insert(NotificationOutbox).values(
        user_id=user_id,
        template_code=template_code,
        payload=payload or {},
        dedupe_key=dedupe_key,
    )
    if dedupe_key is not None:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["dedupe_key"], index_where=text("dedupe_key IS NOT NULL")
        )
    await session.execute(stmt)


async def pending_batch(session: AsyncSession, limit: int = 25) -> list[NotificationOutbox]:
    rows = await session.execute(
        select(NotificationOutbox)
        .where(NotificationOutbox.status == "pending")
        .order_by(NotificationOutbox.scheduled_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(rows.scalars().all())
