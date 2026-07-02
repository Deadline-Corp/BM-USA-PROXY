"""Notification outbox — enqueue user-facing notifications (delivered by the worker)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationOutbox

# Template catalog (texts live in app_settings['notify_texts:<code>'], editable in admin).
TEMPLATES = {
    "welcome",
    "payment_received",
    "access_issued",
    "provisioning_delayed",
    "invoice_expiring",
    "access_expiring_24h",
    "access_expiring_1h",
    "access_expired",
    "access_extended",
    "access_reissued",
    "refund_processed",
    "referral_joined",
    "referral_accrued",
    "referral_available",
    "payout_approved",
    "payout_paid",
    "payout_rejected",
    "config_delivered",
    "operator_message",
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
