"""Matching a deposit to an invoice — the rules that keep money on the right order.

The shared-address design leans entirely on the amount to tell orders apart, so the
matcher is the last line of defence against crediting the wrong one. Both cases below are
regressions from a real production incident on 2026-08-05.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Invoice, Order, Tariff, User
from app.models.onchain import OnchainDepositLedger
from app.services.payments.onchain.chain_client import IncomingTransfer
from app.services.payments.onchain.matcher import PaymentMatcher
from scripts.seed import seed_locations, seed_settings, seed_tariffs
from sqlalchemy import select

ADDR = "TWatchedAddr11111111111111111111111"


async def _invoice_for(session, *, amount: Decimal, status: str, tag: str) -> tuple[Order, Invoice]:
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
    return order, inv


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
    await _invoice_for(session, amount=Decimal("30.618099"), status="expired", tag="closed-one")
    _, open_inv = await _invoice_for(session, amount=Decimal("30.597123"), status="pending", tag="open-one")

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
    _, small = await _invoice_for(session, amount=Decimal("30.597123"), status="pending", tag="small-one")

    result = await PaymentMatcher(session).match(_transfer(Decimal("260.000000")))

    assert result.invoice is None
    await session.refresh(small)
    assert small.status == "pending"


async def test_a_modest_round_up_still_settles_the_invoice(session) -> None:
    """Buyers do round up — the cap must not send every tidy payment to manual review."""
    await _seed(session)
    _, inv = await _invoice_for(session, amount=Decimal("30.597123"), status="pending", tag="round-up")

    result = await PaymentMatcher(session).match(_transfer(Decimal("30.60")))

    assert result.invoice is not None and result.invoice.id == inv.id


async def test_the_exact_amount_still_wins(session) -> None:
    """The normal path must be untouched by the new guards."""
    await _seed(session)
    _, inv = await _invoice_for(session, amount=Decimal("30.597123"), status="pending", tag="exact-one")

    result = await PaymentMatcher(session).match(_transfer(Decimal("30.597123")))

    assert result.reason == "exact"
    assert result.invoice is not None and result.invoice.id == inv.id


async def test_a_late_payment_is_recorded_as_expired_rather_than_anonymous(session) -> None:
    """`expired_deposit` was declared and never written — a late payment looked anonymous.

    The amount is the exact quote of an invoice that timed out, so we know whose money it
    is. Saying "unmatched" hid the single fact that resolves it fastest.
    """
    import json as _json

    from app.services.payments.onchain import load_config
    from app.services.payments.onchain.ledger import LedgerWriter
    from app.services.payments.onchain.watcher import process_transfer

    await _seed(session)
    order, invoice = await _invoice_for(session, amount=Decimal("30.1234"), status="expired",
                                        tag="late-one")
    cfg = load_config(
        _json.dumps([{"asset": "TRX", "network": "native", "address": ADDR}]), "{}"
    )
    ledger = LedgerWriter(session)
    await process_transfer(
        session, _transfer(Decimal("30.1234")),
        config=cfg, ledger=ledger, matcher=PaymentMatcher(session),
    )

    rows = list(
        await session.scalars(
            select(OnchainDepositLedger).order_by(OnchainDepositLedger.id)
        )
    )
    assert [r.status for r in rows] == ["detected", "expired_deposit"]
    assert rows[-1].meta["invoice_id"] == invoice.id
    assert rows[-1].user_id == order.user_id, "the operator should see whose payment this is"


REF = "Ref1111111111111111111111111111111111111111"


def _sol_transfer(amount: Decimal, *, keys: tuple[str, ...]) -> IncomingTransfer:
    return IncomingTransfer(
        chain="solana", asset="SOL", network="native", txid=f"sig-{amount}",
        to_address=ADDR, amount=amount, from_address="SoLsender",
        block_time=datetime.now(UTC), confirmations=1, reference_candidates=keys,
    )


async def _sol_invoice(session, *, amount: Decimal, tag: str, reference: str | None):
    """An open Solana invoice on the shared address, optionally carrying a reference."""
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
        order_id=order.id, provider="onchain", provider_invoice_id=tag, status="pending",
        amount_usd="10", crypto_currency="SOL", crypto_network="native",
        crypto_amount=amount, pay_address=ADDR, chain="solana",
        amount_tolerance=Decimal("0"), locked_rate=Decimal("1"), reference_pubkey=reference,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(inv)
    await session.flush()
    return inv


async def test_a_reference_identifies_the_invoice_when_the_amount_cannot(session) -> None:
    """The point of the reference: it works where amount matching gives up.

    Two open invoices, and a deposit whose amount matches neither. On amount alone this is
    an unmatched deposit a human has to sort out. Carrying the reference, it lands on the
    right order with no ambiguity at all.
    """
    await _seed(session)
    await _sol_invoice(session, amount=Decimal("0.190000"), tag="sol-other", reference=None)
    mine = await _sol_invoice(session, amount=Decimal("0.184300"), tag="sol-mine", reference=REF)

    # amount deliberately matches neither invoice
    transfer = _sol_transfer(Decimal("0.177000"), keys=(ADDR, "TokenProgram", REF))
    result = await PaymentMatcher(session).match(transfer)

    assert result.reason == "reference"
    assert result.invoice is not None and result.invoice.id == mine.id


async def test_reference_matching_ignores_the_unrelated_keys_in_a_transaction(session) -> None:
    """Every account key is handed over, and all but ours must be inert."""
    await _seed(session)
    inv = await _sol_invoice(session, amount=Decimal("0.184300"), tag="sol-noise", reference=REF)

    transfer = _sol_transfer(
        Decimal("0.184300"),
        keys=(ADDR, "11111111111111111111111111111111", "SoLsender", "SysvarRent111"),
    )
    result = await PaymentMatcher(session).match(transfer)

    # no reference among the keys → falls through to the amount, which still works
    assert result.reason == "exact"
    assert result.invoice is not None and result.invoice.id == inv.id


async def test_one_transaction_naming_two_invoices_is_parked(session) -> None:
    """We cannot split a single transfer across two orders — guessing would rob one."""
    await _seed(session)
    other_ref = "Ref2222222222222222222222222222222222222222"
    await _sol_invoice(session, amount=Decimal("0.184300"), tag="sol-a", reference=REF)
    await _sol_invoice(session, amount=Decimal("0.190000"), tag="sol-b", reference=other_ref)

    result = await PaymentMatcher(session).match(
        _sol_transfer(Decimal("0.374300"), keys=(ADDR, REF, other_ref))
    )

    assert result.invoice is None
    assert result.reason == "ambiguous"
