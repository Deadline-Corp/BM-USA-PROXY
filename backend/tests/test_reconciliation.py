"""Daily payment reconciliation: catches missed / over-credited payments."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Invoice, Order, Tariff, User
from app.models.onchain import OnchainDepositLedger
from app.services.payments.reconciliation import reconcile_day
from scripts.seed import seed_locations, seed_settings, seed_tariffs
from sqlalchemy import select


async def _seed(session) -> None:
    await seed_settings(session)
    await seed_tariffs(session)
    await seed_locations(session)
    await session.flush()


async def _paid_invoice(session, *, inv_id: str, when: datetime, amount: str = "10") -> Order:
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    user = User(tg_user_id=abs(hash(inv_id)) % 9_000_000 + 5000, referral_code=inv_id.upper()[:12])
    session.add(user)
    await session.flush()
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="daily", duration_minutes=1440,
                  amount_usd=amount, status="completed", paid_at=when, completed_at=when)
    session.add(order)
    await session.flush()
    session.add(Invoice(order_id=order.id, provider="onchain", provider_invoice_id=inv_id,
                        status="paid", amount_usd=amount, paid_at=when,
                        expires_at=when + timedelta(hours=1)))
    await session.flush()
    return order


async def test_reconcile_clean_day(session) -> None:
    await _seed(session)
    today = datetime.now(UTC)
    order = await _paid_invoice(session, inv_id="rec-clean", when=today)
    # a matched 'paid' ledger row backing the invoice → no discrepancy
    inv = await session.scalar(select(Invoice).where(Invoice.order_id == order.id))
    session.add(OnchainDepositLedger(status="paid", chain="tron", asset="USDT", network="trc20",
                txid="0xok", to_address="T", amount=Decimal("10.0005"), amount_usd=Decimal("10"),
                confirmations=20, observed_at=today, invoice_id=inv.id))
    await session.flush()

    report = await reconcile_day(session, today.date())
    assert report["paid"]["count"] == 1
    assert report["paid"]["amount_usd"] == 10.0
    assert report["clean"] is True
    assert report["issue_count"] == 0


async def test_reconcile_flags_unmatched_deposit(session) -> None:
    await _seed(session)
    today = datetime.now(UTC)
    # money landed but matched no invoice → the "missed payment" case
    session.add(OnchainDepositLedger(status="unmatched", chain="tron", asset="USDT",
                network="trc20", txid="0xmiss", to_address="TWatch", amount=Decimal("5"),
                amount_usd=Decimal("5"), confirmations=20, observed_at=today))
    await session.flush()

    report = await reconcile_day(session, today.date())
    assert report["clean"] is False
    misses = report["discrepancies"]["unmatched_deposits"]
    assert len(misses) == 1 and misses[0]["txid"] == "0xmiss"
    assert report["deposits_by_status"].get("unmatched") == 1


async def test_reconcile_flags_paid_without_ledger(session) -> None:
    await _seed(session)
    today = datetime.now(UTC)
    # an on-chain invoice marked paid but with NO confirmed ledger row behind it
    await _paid_invoice(session, inv_id="rec-noledger", when=today)

    report = await reconcile_day(session, today.date())
    assert report["clean"] is False
    assert len(report["discrepancies"]["paid_without_ledger"]) == 1
