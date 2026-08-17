"""Order lifecycle: create (with ToS gate, trial limit, availability), mark paid, status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    Conflict,
    NotFound,
    PaymentsUnconfigured,
    ProvisioningError,
    TermsNotAccepted,
    ValidationError,
)
from app.models import Access, AccessEvent, Connection, Invoice, Order, Tariff, User
from app.services import referral
from app.services import settings as settings_svc
from app.services.catalog import trial_available
from app.services.notifications import enqueue
from app.services.payments.base import InvoiceDTO
from app.services.payments.onchain.config import get_onchain_config
from app.services.payments.onchain.rails import refresh_rails
from app.services.payments.registry import get_payment_provider
from app.services.provisioning.allocator import count_available
from app.services.provisioning.lifecycle import extend_access, provision_access, swap_access
from app.services.ratelimit_helpers import order_guard
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


async def _ensure_unique_crypto_amount(session: AsyncSession, provider_name: str, dto: InvoiceDTO) -> None:
    """Nudge the on-chain expected amount until it's unique among OPEN invoices on this rail.

    With one shared receiving address per rail, the amount is the routing key — two open
    invoices sharing it are ambiguous and strand a payment. The hash-derived delta makes
    collisions rare; this closes them deterministically (the DB partial-unique index is the
    hard backstop). Only touches on-chain invoices.
    """
    if provider_name != "onchain" or dto.crypto_amount is None:
        return
    from app.services.payments.onchain.amounts import _quantum
    from app.services.payments.onchain.assets import find_spec

    spec = find_spec(dto.crypto_currency or "", dto.crypto_network or "")
    step = _quantum(spec.quote_decimals) if spec else Decimal("0.000001")
    for _ in range(1000):
        clash = await session.scalar(
            select(Invoice.id)
            .where(
                Invoice.provider == "onchain",
                Invoice.crypto_currency == dto.crypto_currency,
                Invoice.crypto_network == dto.crypto_network,
                Invoice.pay_address == dto.pay_address,
                Invoice.crypto_amount == dto.crypto_amount,
                Invoice.status.in_(("pending", "confirming")),
            )
            .limit(1)
        )
        if clash is None:
            return
        dto.crypto_amount += step


async def guard_order_attempt(session: AsyncSession, *, user_id: int, tariff_code: str) -> None:
    """Apply the order rate limit — unless this specific attempt is certain to fail anyway.

    A paid-tariff purchase against a store with zero on-chain rails configured always ends
    in ``PaymentsUnconfigured``, no matter how the buyer behaves. Checking that here, before
    ``order_guard``, means those guaranteed failures stop reaching the payment provider only
    *after* spending one of the buyer's 10/hour order attempts — which is how a business
    owner's own test clicks used to burn the whole budget and hide the real error behind a
    429 ``rate_limited`` (see PaymentsUnconfigured for the actual problem). Free tariffs
    (trial) never touch the payment provider, so they are never blocked here — only a paid
    tariff with no configured rail short-circuits before it can spend a slot.

    Gated on the on-chain provider actually being the active one: "no on-chain rail" only
    predicts a failure when ``create_order`` below is going to ask the on-chain provider for
    an invoice. Under ``PAYMENT_PROVIDER=mock`` (every non-prod default) or any future
    non-on-chain provider, an empty on-chain rail list means nothing — checking it anyway
    would block purchases a real attempt could satisfy just fine.
    """
    if get_payment_provider().name == "onchain":
        await refresh_rails(session)
        if get_onchain_config().default_method() is None:
            price = await session.scalar(
                select(Tariff.price_usd).where(Tariff.code == tariff_code, Tariff.is_active)
            )
            if price is not None and float(price) > 0:
                raise PaymentsUnconfigured(
                    "Payments are not set up yet: an administrator must add at least one "
                    "receiving wallet address in the admin console (Wallets), after which "
                    "purchases will work."
                )
    await order_guard(user_id)


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
        if tariff.code == "trial":
            if not await trial_available(session, user):
                raise ValidationError("trial already used")
        else:
            # generic per-user cap for any tariff carrying max_per_user (promos etc.);
            # previously ONLY the trial code was enforced, so any other capped tariff
            # could be bought without limit.
            used = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Order)
                    .where(
                        Order.user_id == user.id,
                        Order.tariff_id == tariff.id,
                        Order.status.in_(("paid", "provisioning", "completed")),
                    )
                )
                or 0
            )
            if used >= tariff.max_per_user:
                raise ValidationError("purchase limit reached for this tariff")

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

    # Pick up whatever rail list the console last saved before quoting an address —
    # otherwise this process keeps handing out the address an operator already replaced.
    await refresh_rails(session)
    provider = get_payment_provider()
    ttl = int(await settings_svc.get(session, "invoice_ttl_minutes", 60))
    dto = await provider.create_invoice(
        order_public_id=str(order.public_id),
        amount_usd=Decimal(str(order.amount_usd)),
        ttl_minutes=ttl,
        asset=asset,
        network=network,
    )
    await _ensure_unique_crypto_amount(session, provider.name, dto)
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
    # Deliberately silent. "Payment received — issuing your proxy now" was a message about
    # an intermediate step the buyer is already watching on the checkout screen, and it
    # landed seconds before `access_issued` said the same thing with something actionable
    # attached. Two pings for one purchase is one too many.
    await referral.accrue(session, order=order)  # no-op if no referrer / admin origin
    if order.is_extension and order.extends_access_id:
        access = await session.get(Access, order.extends_access_id)
        if access is None:
            order.status = "manual_review"
        elif access.status in ("active", "expiring"):
            await extend_access(session, access=access, minutes=order.duration_minutes or 0)
            order.status = "completed"
            order.completed_at = _utcnow()
        else:
            # The access died between "Extend" and the payment landing — an invoice lives
            # an hour, and create_extension_order only checked the access was alive when
            # it was created. Extending now would flip a dead access back to 'active'
            # while the expiry sweeper has already deleted its proxy-accesses on iproxy:
            # the customer has paid, the app says active, and nothing connects.
            #
            # So re-issue instead of extend. Same city and carrier, fresh credentials, and
            # the duration they just paid for. The connection may well be the same phone
            # if nobody took it in the meantime.
            conn = await session.get(Connection, access.connection_id)
            try:
                await swap_access(
                    session,
                    access=access,
                    location_id=conn.location_id if conn else None,
                    carrier=conn.carrier if conn else None,
                    duration_minutes=order.duration_minutes,
                )
            except Conflict:
                # Nothing free in that city/carrier right now. The money is recorded and
                # an operator picks it up rather than the buyer being told "paid" over an
                # access that does not work.
                order.status = "manual_review"
            else:
                order.status = "completed"
                order.completed_at = _utcnow()
                # Different credentials than the ones they had — say so, because the app
                # will quietly show new ones and the old pair stops working.
                await enqueue(
                    session,
                    user_id=access.user_id,
                    template_code="access_reissued",
                    payload={"access_public_id": str(access.public_id)},
                )
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
    # Only a live access can be extended. Extending an already-expired one would, on
    # payment, resurrect it to 'active' — and if its connection was re-sold in the
    # meantime that violates the one-live-access-per-connection unique index and poisons
    # the payment tick. Reject at the source.
    if access.status not in ("active", "expiring"):
        raise Conflict("this access can no longer be extended; buy a new one")

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

    # Pick up whatever rail list the console last saved before quoting an address —
    # otherwise this process keeps handing out the address an operator already replaced.
    await refresh_rails(session)
    provider = get_payment_provider()
    ttl = int(await settings_svc.get(session, "invoice_ttl_minutes", 60))
    dto = await provider.create_invoice(
        order_public_id=str(order.public_id),
        amount_usd=Decimal(str(order.amount_usd)),
        ttl_minutes=ttl,
        asset=asset,
        network=network,
    )
    await _ensure_unique_crypto_amount(session, provider.name, dto)
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
