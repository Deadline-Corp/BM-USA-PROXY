"""Operator resolution of parked deposits.

Money that the watcher refuses to guess about has to have a way out, and that way out is
itself a money path: it hands over a paid product. These tests pin the parts that would
hurt — double-crediting, crediting a settled deposit, and losing the audit trail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.errors import Conflict
from app.models import Access, Invoice, Order, Tariff, User
from app.models.onchain import OnchainDepositLedger
from app.services.payments.onchain import manual_resolution
from scripts.seed import seed_dev_fixtures, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import func, select

ADDR = "TWatchedAddr11111111111111111111111"


async def _seed(session) -> None:
    await seed_settings(session)
    await seed_tariffs(session)
    await seed_locations(session)
    await session.flush()
    await seed_dev_fixtures(session)
    await session.flush()


async def _order_with_invoice(session, *, tag: str, amount: Decimal) -> tuple[Order, Invoice]:
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
    invoice = Invoice(
        order_id=order.id, provider="onchain", provider_invoice_id=tag, status="pending",
        amount_usd="10", crypto_currency="USDT", crypto_network="trc20",
        crypto_amount=amount, pay_address=ADDR, chain="tron",
        amount_tolerance=Decimal("0"), locked_rate=Decimal("1"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(invoice)
    await session.flush()
    return order, invoice


async def _parked_deposit(session, *, amount: Decimal, status: str = "unmatched") -> OnchainDepositLedger:
    row = OnchainDepositLedger(
        status=status, chain="tron", asset="USDT", network="trc20",
        txid=f"0xstuck{amount}", log_index=None, to_address=ADDR,
        amount=amount, amount_usd=Decimal("10"), confirmations=25,
        block_time=datetime.now(UTC), observed_at=datetime.now(UTC), meta={},
    )
    session.add(row)
    await session.flush()
    return row


async def _access_count(session, order_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Access).where(Access.order_id == order_id)
        )
        or 0
    )


async def test_attaching_a_parked_deposit_pays_the_order_and_issues_access(session) -> None:
    """The whole point: stuck money becomes a delivered product, through the normal path."""
    await _seed(session)
    order, invoice = await _order_with_invoice(session, tag="attach-1", amount=Decimal("10.000265"))
    deposit = await _parked_deposit(session, amount=Decimal("10.000265"))

    await manual_resolution.attach_to_order(
        session, deposit_id=deposit.id, order_public_id=str(order.public_id), operator_id=1
    )

    await session.refresh(invoice)
    await session.refresh(order)
    assert invoice.status == "paid"
    assert invoice.matched_txid == deposit.txid
    assert await _access_count(session, order.id) == 1


async def test_attaching_twice_does_not_credit_twice(session) -> None:
    """A double-click, or a retry after a timeout, must not hand out two proxies."""
    await _seed(session)
    order, _ = await _order_with_invoice(session, tag="attach-2", amount=Decimal("10.000266"))
    deposit = await _parked_deposit(session, amount=Decimal("10.000266"))

    await manual_resolution.attach_to_order(
        session, deposit_id=deposit.id, order_public_id=str(order.public_id), operator_id=1
    )
    with pytest.raises(Conflict):
        await manual_resolution.attach_to_order(
            session, deposit_id=deposit.id, order_public_id=str(order.public_id), operator_id=1
        )

    assert await _access_count(session, order.id) == 1


async def test_a_settled_deposit_cannot_be_re_resolved(session) -> None:
    await _seed(session)
    order, _ = await _order_with_invoice(session, tag="attach-3", amount=Decimal("10.000267"))
    deposit = await _parked_deposit(session, amount=Decimal("10.000267"), status="paid")

    with pytest.raises(Conflict):
        await manual_resolution.attach_to_order(
            session, deposit_id=deposit.id, order_public_id=str(order.public_id), operator_id=1
        )


async def test_write_off_appends_rather_than_edits(session) -> None:
    """The original observation and the decision to close it both have to survive."""
    await _seed(session)
    deposit = await _parked_deposit(session, amount=Decimal("7.5"))

    await manual_resolution.write_off(
        session, deposit_id=deposit.id, operator_id=7, reason="refunded by bank transfer"
    )

    rows = list(
        await session.scalars(
            select(OnchainDepositLedger)
            .where(OnchainDepositLedger.txid == deposit.txid)
            .order_by(OnchainDepositLedger.id)
        )
    )
    assert len(rows) == 2, "the closing row must be appended, not overwrite the original"
    assert rows[0].status == "unmatched"
    assert rows[1].status == "orphaned"
    assert rows[1].meta["resolution"] == "written_off"
    assert rows[1].meta["operator_id"] == 7
    assert rows[1].meta["reason"] == "refunded by bank transfer"
