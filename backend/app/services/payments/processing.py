"""Webhook intake + idempotent payment-event processing (Invariant #1).

Split so the HTTP layer only records the raw event; the worker applies it. 1 paid
event = 1 activation, guarded by UNIQUE(provider, provider_invoice_id) + the
payment_events dedupe index + the forward-only invoice state machine.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.models import Invoice, Order, PaymentEvent
from app.services.orders import mark_paid
from app.services.payments.base import PaymentEventDTO

# forward-only ordering of invoice statuses (higher = later; never regress)
_RANK = {
    "created": 0,
    "pending": 1,
    "confirming": 2,
    "underpaid": 3,
    "overpaid": 3,
    "paid": 4,
    "failed": 5,
    "expired": 5,
    "manual_review": 6,
}


async def ingest_webhook(
    session: AsyncSession, *, provider: str, raw_body: bytes, signature_valid: bool, dto: PaymentEventDTO
) -> int | None:
    """Record the raw event (deduped). Returns the event id to process, or None if dup."""
    stmt = insert(PaymentEvent).values(
        provider=provider,
        provider_event_id=dto.provider_event_id,
        provider_invoice_id=dto.provider_invoice_id,
        payload={
            "status": dto.status,
            "raw_len": len(raw_body),
            "paid_amount_usd": str(dto.paid_amount_usd) if dto.paid_amount_usd is not None else None,
        },
        signature_valid=signature_valid,
    )
    if dto.provider_event_id is not None:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["provider", "provider_event_id"],
            index_where=text("provider_event_id IS NOT NULL"),
        )
    result = await session.execute(stmt.returning(PaymentEvent.id))
    row = result.first()
    return int(row[0]) if row else None


async def process_payment_event(session: AsyncSession, event_id: int) -> str:
    """Apply one recorded event to its invoice/order. Idempotent + forward-only."""
    event = await session.get(PaymentEvent, event_id)
    if event is None:
        return "missing_event"
    if event.processed_at is not None:
        return "already_processed"

    invoice = await session.scalar(
        select(Invoice)
        .where(
            Invoice.provider == event.provider,
            Invoice.provider_invoice_id == event.provider_invoice_id,
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    if invoice is None:
        event.processed_at = now
        event.processing_result = "ignored:no_invoice"
        log.warning("payment.no_invoice", provider=event.provider, inv=event.provider_invoice_id)
        return "no_invoice"

    new_status = str((event.payload or {}).get("status", "")) or "pending"
    # Forward-only for EVERY status (incl. 'paid'): a 'paid' event must never override
    # a terminal (failed/expired) or manual_review invoice — the operator resolves those.
    if _RANK.get(new_status, -1) <= _RANK.get(invoice.status, -1):
        event.processed_at = now
        event.processing_result = f"ignored:stale({new_status}<= {invoice.status})"
        return "stale"

    result = "applied"
    if new_status == "paid":
        # Amount check: if the provider reports the paid amount and it's short of the
        # invoice, route to manual review instead of provisioning for free.
        paid_raw = (event.payload or {}).get("paid_amount_usd")
        if paid_raw is not None and Decimal(str(paid_raw)) < Decimal(str(invoice.amount_usd)):
            invoice.status = "manual_review"
            result = "manual_review:amount_short"
        else:
            invoice.status = "paid"
            invoice.paid_at = now
            order = await session.get(Order, invoice.order_id)
            if order is not None:
                await mark_paid(session, order=order, source=f"webhook:{event.provider}")
    elif new_status in ("underpaid", "overpaid"):
        invoice.status = "manual_review"
        result = f"manual_review:{new_status}"
    elif new_status in ("expired", "failed"):
        invoice.status = new_status
        order = await session.get(Order, invoice.order_id)
        if order is not None and order.status == "awaiting_payment":
            order.status = "expired" if new_status == "expired" else "cancelled"
    else:
        invoice.status = new_status

    event.processed_at = now
    event.processing_result = result
    return result
