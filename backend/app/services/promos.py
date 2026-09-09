"""Promo codes: checking one, spending it, and giving it back.

Three calls, and the order they happen in is the whole design.

`quote` answers "what would this code do for me" and writes nothing — the checkout screen
asks it while the buyer is still typing. `redeem` is what actually consumes a use, and it
runs inside the order's own transaction so that a code and an order come into existence
together or not at all. `release` hands the use back when the order dies unpaid.

Without `release`, a one-use code burns on an invoice nobody paid: the buyer changes their
mind, and the code they were given is gone with nothing sold. That is the failure this
module exists to avoid, and it is why the count is rows in `promo_redemptions` rather than
a number on the code — a counter has to be decremented by whoever remembers to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.models import Order, PromoCode, PromoRedemption, User


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _money(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalise(code: str | None) -> str:
    """What a typed code becomes before anything looks it up.

    Upper-cased and trimmed, so "  summer " and "SUMMER" are the same code — a buyer
    pasting from a chat message brings whitespace with them more often than not.
    """
    return (code or "").strip().upper()


@dataclass(frozen=True, slots=True)
class Discount:
    code: PromoCode
    percent_off: int
    amount_off_usd: Decimal
    total_usd: Decimal


async def _live_code(session: AsyncSession, code: str) -> PromoCode:
    row = await session.scalar(
        select(PromoCode).where(PromoCode.code == code, PromoCode.deleted_at.is_(None))
    )
    if row is None:
        raise ValidationError("promo code not found")
    return row


async def _uses(session: AsyncSession, code_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(PromoRedemption)
            .where(PromoRedemption.promo_code_id == code_id)
        )
        or 0
    )


async def quote(
    session: AsyncSession,
    *,
    code: str,
    user: User,
    subtotal_usd: Decimal,
    is_extension: bool = False,
) -> Discount:
    """What this code is worth on this order, or why it cannot be used.

    Writes nothing. Every rejection is a `ValidationError` whose message is meant to be
    shown to the buyer as-is — "this code has already been used" is something they can act
    on, an opaque failure is a message to support.
    """
    normalised = normalise(code)
    if not normalised:
        raise ValidationError("enter a promo code")
    promo = await _live_code(session, normalised)

    now = _utcnow()
    if promo.starts_at is not None and promo.starts_at > now:
        raise ValidationError("this promo code is not active yet")
    if promo.expires_at is not None and promo.expires_at <= now:
        raise ValidationError("this promo code has expired")
    if is_extension and promo.applies_to == "purchase":
        raise ValidationError("this promo code applies to new purchases only")

    already = await session.scalar(
        select(PromoRedemption.id).where(
            PromoRedemption.promo_code_id == promo.id, PromoRedemption.user_id == user.id
        )
    )
    if already is not None:
        raise ValidationError("you have already used this promo code")

    if promo.max_uses is not None and await _uses(session, promo.id) >= promo.max_uses:
        raise ValidationError("this promo code has run out")

    amount_off = _money(subtotal_usd * Decimal(promo.percent_off) / Decimal(100))
    # Never below zero, and never more than the order is worth. A 100% code is allowed —
    # an operator may want to hand somebody a free month — and it lands on a zero total,
    # which the order path already understands as "nothing to pay".
    amount_off = min(amount_off, _money(subtotal_usd))
    return Discount(
        code=promo,
        percent_off=promo.percent_off,
        amount_off_usd=amount_off,
        total_usd=_money(subtotal_usd - amount_off),
    )


async def redeem(
    session: AsyncSession,
    *,
    code: str,
    user: User,
    order: Order,
    subtotal_usd: Decimal,
) -> Discount:
    """Spend a use against this order. Call inside the order's transaction.

    The limit is re-checked under a lock on the code, not just in `quote`. Two buyers can
    pass the same check at the same moment on the last remaining use of a code, and the
    count is what the operator promised — an advisory lock keyed on the code makes the two
    attempts queue rather than both succeed.
    """
    normalised = normalise(code)
    promo = await _live_code(session, normalised)
    # Namespaced away from the user-id locks `create_order` already takes, so the two
    # cannot collide on the same integer and deadlock.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :k)"), {"ns": 0x50524D4F % 2**31, "k": promo.id}
    )

    discount = await quote(
        session,
        code=normalised,
        user=user,
        subtotal_usd=subtotal_usd,
        is_extension=bool(order.is_extension),
    )
    session.add(
        PromoRedemption(
            promo_code_id=promo.id,
            user_id=user.id,
            order_id=order.id,
            percent_off=discount.percent_off,
            discount_usd=discount.amount_off_usd,
        )
    )
    await session.flush()
    return discount


async def release(session: AsyncSession, *, order_id: int) -> int:
    """Give the use back. Called when an order is cancelled or expires.

    The order keeps its own `promo_code_id` and `discount_usd`, so the history of what was
    sold at what price survives this — only the claim on the code goes.
    """
    result = await session.execute(
        delete(PromoRedemption)
        .where(PromoRedemption.order_id == order_id)
        .returning(PromoRedemption.id)
    )
    return len(result.all())


async def usage_counts(session: AsyncSession, code_ids: list[int]) -> dict[int, int]:
    """How many times each code has been used, in one query rather than N."""
    if not code_ids:
        return {}
    rows = (
        await session.execute(
            select(PromoRedemption.promo_code_id, func.count())
            .where(PromoRedemption.promo_code_id.in_(code_ids))
            .group_by(PromoRedemption.promo_code_id)
        )
    ).all()
    return {int(code_id): int(n) for code_id, n in rows}
