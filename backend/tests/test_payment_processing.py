"""Payment idempotency (Invariant #1): 1 paid event = 1 activation, no double-issue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Access, Invoice, Order, Tariff, User
from app.services.payments.base import PaymentEventDTO
from app.services.payments.processing import ingest_webhook, process_payment_event
from scripts.seed import seed_dev_fixtures, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import func, select


async def _order_with_invoice(session, *, inv_id: str, amount: str = "10") -> tuple[Order, Invoice]:
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    user = User(tg_user_id=abs(hash(inv_id)) % 9_000_000 + 1000,
                referral_code=inv_id.replace("-", "").upper()[:12])
    session.add(user)
    await session.flush()
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="daily",
                  duration_minutes=1440, amount_usd=amount, status="awaiting_payment")
    session.add(order)
    await session.flush()
    invoice = Invoice(order_id=order.id, provider="mock", provider_invoice_id=inv_id,
                      status="pending", amount_usd=amount,
                      expires_at=datetime.now(UTC) + timedelta(hours=1))
    session.add(invoice)
    await session.flush()
    return order, invoice


async def _seed(session) -> None:
    await seed_settings(session)
    await seed_tariffs(session)
    await seed_locations(session)
    await session.flush()
    await seed_dev_fixtures(session)
    await session.flush()


async def _access_count(session, order_id: int) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(Access).where(Access.order_id == order_id)
    ) or 0)


async def test_paid_event_provisions_exactly_once(session) -> None:
    await _seed(session)
    order, _ = await _order_with_invoice(session, inv_id="inv-pay-1")
    dto = PaymentEventDTO(provider_invoice_id="inv-pay-1", status="paid", provider_event_id="e1")

    eid = await ingest_webhook(session, provider="mock", raw_body=b"{}", signature_valid=True, dto=dto)
    assert eid is not None
    assert await process_payment_event(session, eid) == "applied"
    await session.refresh(order)
    assert order.status == "completed"
    assert await _access_count(session, order.id) == 1

    # replay the SAME event → deduped at ingest (no new row)
    dup = await ingest_webhook(
        session, provider="mock", raw_body=b"{}", signature_valid=True, dto=dto
    )
    assert dup is None
    # reprocess same event id → no-op
    assert await process_payment_event(session, eid) == "already_processed"
    assert await _access_count(session, order.id) == 1


async def test_second_distinct_paid_event_does_not_double_issue(session) -> None:
    await _seed(session)
    order, _ = await _order_with_invoice(session, inv_id="inv-pay-2")
    dto1 = PaymentEventDTO(provider_invoice_id="inv-pay-2", status="paid", provider_event_id="a1")
    dto2 = PaymentEventDTO(provider_invoice_id="inv-pay-2", status="paid", provider_event_id="a2")
    e1 = await ingest_webhook(session, provider="mock", raw_body=b"{}", signature_valid=True, dto=dto1)
    await process_payment_event(session, e1)
    e2 = await ingest_webhook(session, provider="mock", raw_body=b"{}", signature_valid=True, dto=dto2)
    await process_payment_event(session, e2)  # invoice already paid → mark_paid no-op
    assert await _access_count(session, order.id) == 1


async def test_underpaid_goes_to_manual_review(session) -> None:
    await _seed(session)
    order, invoice = await _order_with_invoice(session, inv_id="inv-pay-3")
    dto = PaymentEventDTO(provider_invoice_id="inv-pay-3", status="underpaid", provider_event_id="u1")
    eid = await ingest_webhook(session, provider="mock", raw_body=b"{}", signature_valid=True, dto=dto)
    result = await process_payment_event(session, eid)
    assert "manual_review" in result
    assert invoice.status == "manual_review"
    assert await _access_count(session, order.id) == 0


async def test_stale_event_ignored(session) -> None:
    await _seed(session)
    order, invoice = await _order_with_invoice(session, inv_id="inv-pay-4")
    paid = PaymentEventDTO(provider_invoice_id="inv-pay-4", status="paid", provider_event_id="p1")
    e1 = await ingest_webhook(session, provider="mock", raw_body=b"{}", signature_valid=True, dto=paid)
    await process_payment_event(session, e1)
    # a late 'pending' after 'paid' must not regress
    late = PaymentEventDTO(provider_invoice_id="inv-pay-4", status="pending", provider_event_id="p2")
    e2 = await ingest_webhook(session, provider="mock", raw_body=b"{}", signature_valid=True, dto=late)
    assert await process_payment_event(session, e2) == "stale"
    assert invoice.status == "paid"
