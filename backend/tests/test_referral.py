"""Referral ledger: accrue → release → reverse (pro-rata) → payout, balance invariant."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.models import AdminUser, Order, ReferralLedger, Tariff, User
from app.services import referral
from app.services import settings as settings_svc
from scripts.seed import seed_settings
from sqlalchemy import select, update


async def _admin(session) -> int:
    a = AdminUser(email="op@test.local", password_hash="x", display_name="op", role="owner")
    session.add(a)
    await session.flush()
    return a.id


async def _mk(session, tg: int, code: str, referrer_id: int | None = None) -> User:
    u = User(tg_user_id=tg, referral_code=code, referrer_user_id=referrer_id)
    session.add(u)
    await session.flush()
    return u


async def _paid_order(session, *, referee: User, referrer: User, amount: str) -> Order:
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    o = Order(
        user_id=referee.id, tariff_id=tariff.id, tariff_code="daily",
        amount_usd=amount, status="completed", referrer_user_id=referrer.id,
        paid_at=datetime.now(UTC),
    )
    session.add(o)
    await session.flush()
    return o


async def test_accrue_release_reverse_payout(session) -> None:
    await seed_settings(session)  # needs tariffs? no — settings + we create daily tariff below
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd="10"))
    await session.flush()
    await settings_svc.set_value(session, "referral_min_payout_usd", 1)

    referrer = await _mk(session, 1, "REF00001")
    referee = await _mk(session, 2, "REF00002", referrer_id=referrer.id)

    # three $10 orders → 20% → $2 each accrual (hold)
    orders = [await _paid_order(session, referee=referee, referrer=referrer, amount="10")
              for _ in range(3)]
    for o in orders:
        await referral.accrue(session, order=o)
    assert (await referral.balances(session, referrer.id))["hold"] == 6.0

    # release holds (force due)
    await session.execute(update(ReferralLedger).values(hold_until=datetime.now(UTC)))
    await referral.release_holds(session)
    bal = await referral.balances(session, referrer.id)
    assert bal["hold"] == 0.0
    assert bal["available"] == 6.0

    # full refund of one order → -$2 reversal in available
    await referral.reverse(session, order=orders[0], refund_amount_usd=Decimal("10"))
    assert (await referral.balances(session, referrer.id))["available"] == 4.0

    # payout the net $4
    payout = await referral.request_payout(
        session, user=referrer, wallet_address="Twallet", network="TRC20"
    )
    assert float(payout.amount_usd) == 4.0
    assert (await referral.balances(session, referrer.id))["available"] == 0.0

    await referral.mark_payout_paid(session, payout.id, tx_hash="0xabc", operator_id=await _admin(session))
    bal = await referral.balances(session, referrer.id)
    assert bal["paid"] == 4.0
    assert bal["available"] == 0.0


async def test_reject_payout_returns_to_available(session) -> None:
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd="10"))
    await settings_svc.set_value(session, "referral_min_payout_usd", 1)
    await session.flush()
    referrer = await _mk(session, 10, "REFA0001")
    referee = await _mk(session, 11, "REFA0002", referrer_id=referrer.id)
    o = await _paid_order(session, referee=referee, referrer=referrer, amount="10")
    await referral.accrue(session, order=o)
    await session.execute(update(ReferralLedger).values(hold_until=datetime.now(UTC)))
    await referral.release_holds(session)

    payout = await referral.request_payout(
        session, user=referrer, wallet_address="w", network="TRC20"
    )
    assert (await referral.balances(session, referrer.id))["available"] == 0.0
    await referral.reject_payout(session, payout.id, reason="bad wallet", operator_id=await _admin(session))
    assert (await referral.balances(session, referrer.id))["available"] == 2.0


async def test_hold_not_counted_until_released(session) -> None:
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd="10"))
    await session.flush()
    referrer = await _mk(session, 20, "REFB0001")
    referee = await _mk(session, 21, "REFB0002", referrer_id=referrer.id)
    o = await _paid_order(session, referee=referee, referrer=referrer, amount="10")
    # hold_until is 14 days out → still on hold, available must be 0
    await referral.accrue(session, order=o)
    bal = await referral.balances(session, referrer.id)
    assert bal["available"] == 0.0
    assert bal["hold"] == 2.0
