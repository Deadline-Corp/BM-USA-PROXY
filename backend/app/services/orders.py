"""Order lifecycle: create (with ToS gate, trial limit, availability), mark paid, status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    Conflict,
    NotFound,
    ProvisioningError,
    TermsNotAccepted,
    ValidationError,
)
from app.models import Access, AccessEvent, Invoice, Order, Tariff, User
from app.services import referral
from app.services import settings as settings_svc
from app.services.catalog import trial_available
from app.services.notifications import enqueue
from app.services.payments.base import InvoiceDTO
from app.services.payments.registry import get_payment_provider
from app.services.provisioning.allocator import count_available
from app.services.provisioning.lifecycle import extend_access, provision_access
from app.services.users import is_tos_accepted


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _build_invoice(*, order: Order, provider_name: str, dto: InvoiceDTO, ttl: int) -> Invoice:
    """Construct the Invoice row from a provider DTO (incl. on-chain fields, when present)."""
    return Invoice(
        order_id=order.id,
        provider=provider_name,
        provider_invoice_id=dto.provider_invoice_id,
        status="pending",
        amount_usd=order.amount_usd,
        crypto_currency=dto.crypto_currency,
        crypto_network=dto.crypto_network,
        crypto_amount=dto.crypto_amount,
        pay_address=dto.pay_address,
        payment_url=dto.payment_url,
        expires_at=_utcnow() + timedelta(minutes=ttl),
        chain=dto.chain,
        base_amount=dto.base_amount,
        amount_tolerance=dto.amount_tolerance,
        locked_rate=dto.locked_rate,
        rate_locked_at=_utcnow() if dto.locked_rate is not None else None,
        reference_pubkey=dto.reference_pubkey,
    )


async def create_order(
    session: AsyncSession,
    *,
    user: User,
    tariff_code: str,
    location_id: int | None = None,
    carrier: str | None = None,
    asset: str | None = None,
    network: str | None = None,
) -> tuple[Order, Invoice | None]:
    if not await is_tos_accepted(session, user):
        raise TermsNotAccepted("accept the Terms of Use first")

    tariff = await session.scalar(
        select(Tariff).where(Tariff.code == tariff_code, Tariff.is_active)
    )
    if tariff is None or tariff.kind != "auto" or not tariff.auto_issue:
        raise Conflict("tariff is not available for self-service purchase")

    # trial / per-user limit — advisory lock to serialize concurrent attempts
    if tariff.max_per_user is not None:
        await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": user.id})
        if tariff.code == "trial" and not await trial_available(session, user):
            raise ValidationError("trial already used")

    if await count_available(session, location_id=location_id, carrier=carrier) == 0:
        raise Conflict("sold out for the requested city/carrier")

    order = Order(
        user_id=user.id,
        tariff_id=tariff.id,
        tariff_code=tariff.code,
        duration_minutes=tariff.duration_minutes,
        amount_usd=tariff.price_usd,
        location_id=location_id,
        carrier=carrier,
        referrer_user_id=user.referrer_user_id,
        source_post_id=user.source_post_id,
        status="awaiting_payment",
    )
    session.add(order)
    await session.flush()

    if float(tariff.price_usd) == 0:  # trial: no invoice, issue immediately
        order.status = "paid"
        order.paid_at = _utcnow()
        await _provision_or_review(session, order)
        return order, None

    provider = get_payment_provider()
    ttl = int(await settings_svc.get(session, "invoice_ttl_minutes", 60))
    dto = await provider.create_invoice(
        order_public_id=str(order.public_id),
        amount_usd=Decimal(str(order.amount_usd)),
        ttl_minutes=ttl,
        asset=asset,
        network=network,
    )
    invoice = _build_invoice(order=order, provider_name=provider.name, dto=dto, ttl=ttl)
    session.add(invoice)
    await session.flush()
    return order, invoice


async def mark_paid(session: AsyncSession, *, order: Order, source: str) -> None:
    """Idempotent: awaiting_payment → paid → provision (or extend). Re-entry is a no-op."""
    if order.status != "awaiting_payment":
        return
    order.status = "paid"
    order.paid_at = _utcnow()
    await enqueue(
        session,
        user_id=order.user_id,
        template_code="payment_received",
        payload={"order_public_id": str(order.public_id)},
    )
    await referral.accrue(session, order=order)  # no-op if no referrer / admin origin
    if order.is_extension and order.extends_access_id:
        access = await session.get(Access, order.extends_access_id)
        if access is not None:
            await extend_access(session, access=access, minutes=order.duration_minutes or 0)
            order.status = "completed"
            order.completed_at = _utcnow()
        else:
            order.status = "manual_review"
        return
    await _provision_or_review(session, order)


async def create_extension_order(
    session: AsyncSession,
    *,
    user: User,
    access: Access,
    tariff_code: str,
    asset: str | None = None,
    network: str | None = None,
) -> tuple[Order, Invoice | None]:
    tariff = await session.scalar(
        select(Tariff).where(Tariff.code == tariff_code, Tariff.is_active)
    )
    if tariff is None or float(tariff.price_usd) == 0 or tariff.duration_minutes is None:
        raise Conflict("tariff not valid for extension")

    order = Order(
        user_id=user.id,
        tariff_id=tariff.id,
        tariff_code=tariff.code,
        duration_minutes=tariff.duration_minutes,
        amount_usd=tariff.price_usd,
        is_extension=True,
        extends_access_id=access.id,
        status="awaiting_payment",
    )
    session.add(order)
    await session.flush()

    provider = get_payment_provider()
    ttl = int(await settings_svc.get(session, "invoice_ttl_minutes", 60))
    dto = await provider.create_invoice(
        order_public_id=str(order.public_id),
        amount_usd=Decimal(str(order.amount_usd)),
        ttl_minutes=ttl,
        asset=asset,
        network=network,
    )
    invoice = _build_invoice(order=order, provider_name=provider.name, dto=dto, ttl=ttl)
    session.add(invoice)
    await session.flush()
    return order, invoice


async def _provision_or_review(session: AsyncSession, order: Order) -> None:
    try:
        order.status = "provisioning"
        await provision_access(session, order=order)
    except ProvisioningError:
        # Release the connection held by the half-created access: mark it failed
        # and record an event so the invariant (one live access per connection) frees up.
        access = await session.scalar(
            select(Access).where(
                Access.order_id == order.id, Access.status == "provisioning"
            )
        )
        if access is not None:
            access.status = "failed"
            session.add(
                AccessEvent(access_id=access.id, type="provision_failed", actor="system")
            )
        order.status = "manual_review"
        await enqueue(
            session,
            user_id=order.user_id,
            template_code="provisioning_delayed",
            payload={"order_public_id": str(order.public_id)},
        )


async def get_by_public_id(session: AsyncSession, public_id: str, *, user_id: int | None = None) -> Order:
    stmt = select(Order).where(Order.public_id == public_id)
    if user_id is not None:
        stmt = stmt.where(Order.user_id == user_id)
    order = await session.scalar(stmt)
    if order is None:
        raise NotFound("order not found")
    return order
