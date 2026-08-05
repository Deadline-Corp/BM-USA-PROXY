"""Matching a deposit to an invoice — the rules that keep money on the right order.

The shared-address design leans entirely on the amount to tell orders apart, so the
matcher is the last line of defence against crediting the wrong one. Both cases below are
regressions from a real production incident on 2026-08-05.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Invoice, Order, Tariff, User
from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.matcher import PaymentMatcher
from scripts.seed import seed_locations, seed_settings, seed_tariffs
from sqlalchemy import select

ADDR = "TWatchedAddr11111111111111111111111"


async def _invoice(session, *, amount: Decimal, status: str, tag: str) -> Invoice:
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    user = User(tg_user_id=abs(hash(tag)) % 9_000_000 + 1000, referral_code=tag.upper()[:12])
    session.add(user)
    await session.flush()
    order = Order(
        user_id=user.id, tariff_id=tariff.id, tariff_code="daily", duration_minutes=1440,
        amount_usd="10", status="awaiting_payment",
    )
    session.add(order)
    await session.flush()
    inv = Invoice(
        order_id=order.id, provider="onchain", provider_invoice_id=tag, status=status,
        amount_usd="10", crypto_currency="TRX", crypto_network="native",
        crypto_amount=amount, pay_address=ADDR, chain="tron",
        amount_tolerance=Decimal("0"), locked_rate=Decimal("1"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(inv)
    await session.flush()
    return inv


def _transfer(amount: Decimal) -> IncomingTransfer:
    return IncomingTransfer(
        chain="tron", asset="TRX", network="native", txid=f"0x{amount}",
        to_address=ADDR, amount=amount, from_address="Tsender",
        block_time=datetime.now(UTC), confirmations=30,
    )


async def _seed(session) -> None:
    await seed_settings(session)
    await seed_tariffs(session)
    await seed_locations(session)
    await session.flush()


async def test_payment_for_a_closed_invoice_is_not_spent_on_an_open_one(session) -> None:
    """The production failure, exactly.

    A buyer paid 30.618099 for an invoice that expired 17 seconds earlier. The next open
    invoice happened to quote 30.597123 — near enough that the fuzzy pass accepted the
    deposit as an "overpayment" and issued that other buyer's proxy. The rightful payer
    got nothing. An amount that exactly matches a closed invoice must be parked instead.
    """
    await _seed(session)
    await _invoice(session, amount=Decimal("30.618099"), status="expired", tag="closed-one")
    open_inv = await _invoice(session, amount=Decimal("30.597123"), status="pending", tag="open-one")

    result = await PaymentMatcher(session).match(_transfer(Decimal("30.618099")))

    assert result.invoice is None, "the deposit must not settle a different buyer's invoice"
    assert result.reason == "exact_match_on_closed_invoice"
    await session.refresh(open_inv)
    assert open_inv.status == "pending", "the open invoice must be left untouched"


async def test_a_large_overpayment_does_not_settle_a_small_invoice(session) -> None:
    """`paid >= expected - tol` used to accept an overpayment of any size.

    On a shared address that means a big deposit silently settles whichever small invoice
    is open at the time — the unique-amount design exists precisely to stop that.
    """
    await _seed(session)
    small = await _invoice(session, amount=Decimal("30.597123"), status="pending", tag="small-one")

    result = await PaymentMatcher(session).match(_transfer(Decimal("260.000000")))

    assert result.invoice is None
    await session.refresh(small)
    assert small.status == "pending"


async def test_a_modest_round_up_still_settles_the_invoice(session) -> None:
    """Buyers do round up — the cap must not send every tidy payment to manual review."""
    await _seed(session)
    inv = await _invoice(session, amount=Decimal("30.597123"), status="pending", tag="round-up")

    result = await PaymentMatcher(session).match(_transfer(Decimal("30.60")))

    assert result.invoice is not None and result.invoice.id == inv.id


async def test_the_exact_amount_still_wins(session) -> None:
    """The normal path must be untouched by the new guards."""
    await _seed(session)
    inv = await _invoice(session, amount=Decimal("30.597123"), status="pending", tag="exact-one")

    result = await PaymentMatcher(session).match(_transfer(Decimal("30.597123")))

    assert result.reason == "exact"
    assert result.invoice is not None and result.invoice.id == inv.id
