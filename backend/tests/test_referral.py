"""Referral ledger: accrue → release → reverse (pro-rata) → payout, balance invariant."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.models import AdminUser, Order, ReferralLedger, Tariff, User
from app.services import referral
from app.services import settings as settings_svc
from scripts.seed import seed_settings
from sqlalchemy import select, update

# Valid TRC-20 address — payout requests validate the address against the network, so a
# placeholder like "w" is (correctly) rejected now.
WALLET_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
# These tests exercise ledger mechanics, not the commission rate — pin the rate explicitly
# so a business change (20% → 23%) can't break them.
TEST_PCT = 20


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


# The exact string the mini-app puts on the share button (ReferralScreen.tsx). Written out
# rather than referenced so that changing it there without changing the bot fails here.
MINIAPP_LINK = "https://t.me/BM_USA_Proxy_bot?start=ref_F11A1225"


def test_the_link_the_miniapp_hands_out_is_one_the_bot_understands() -> None:
    """Every referral shared before 2026-08-11 bound nobody, and nothing said so.

    The mini-app builds `?start=ref_<code>`; the handler read only `r_<code>`. A payload
    that does not match is not an error — /start just greeted the newcomer, skipped the
    binding, and the ledger stayed empty. Zero of six users had a referrer. Pin both
    spellings: links already sitting in people's chats have to keep working.
    """
    from app.bot.handlers.start import referral_code_from

    payload = MINIAPP_LINK.split("?start=", 1)[1]
    assert referral_code_from(payload) == "F11A1225"
    assert referral_code_from("r_F11A1225") == "F11A1225"

    # Post attribution is a different deep link and must not be read as a referral.
    assert referral_code_from("p_ABC12345") is None
    assert referral_code_from(None) is None
    assert referral_code_from("") is None
    assert referral_code_from("ref_") is None  # prefix with no code behind it


async def test_binding_by_deep_link_then_accruing_on_a_paid_order(session) -> None:
    """The path the customer actually walks: follow a link, buy, referrer gets a hold.

    The unit above pins the prefix; this pins that the prefix is all that was missing —
    bind through the same call /start makes, then let a paid order accrue.
    """
    from app.bot.handlers.start import referral_code_from

    await seed_settings(session)
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd=Decimal("10.00"), is_active=True))
    await session.flush()
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)

    referrer = await _mk(session, tg=1001, code="F11A1225")
    referee = await _mk(session, tg=1002, code="F5D2851D")

    code = referral_code_from(MINIAPP_LINK.split("?start=", 1)[1])
    assert code is not None
    assert await referral.try_bind(session, referee=referee, code=code) is True
    assert referee.referrer_user_id == referrer.id
    assert referee.referral_bound_at is not None

    order = await _paid_order(session, referee=referee, referrer=referrer, amount="10.00")
    await referral.accrue(session, order=order)
    await session.flush()

    row = await session.scalar(
        select(ReferralLedger).where(ReferralLedger.referee_user_id == referee.id)
    )
    assert row is not None, "a paid order from a bound referee must leave a ledger row"
    assert float(row.amount_usd) == 2.00  # 20% of $10
    assert row.status == "hold"


async def test_accrue_release_reverse_payout(session) -> None:
    await seed_settings(session)  # needs tariffs? no — settings + we create daily tariff below
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd="10"))
    await session.flush()
    await settings_svc.set_value(session, "referral_min_payout_usd", 1)
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)

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
        session, user=referrer, wallet_address=WALLET_TRC20, network="TRC20"
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
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)
    await session.flush()
    referrer = await _mk(session, 10, "REFA0001")
    referee = await _mk(session, 11, "REFA0002", referrer_id=referrer.id)
    o = await _paid_order(session, referee=referee, referrer=referrer, amount="10")
    await referral.accrue(session, order=o)
    await session.execute(update(ReferralLedger).values(hold_until=datetime.now(UTC)))
    await referral.release_holds(session)

    payout = await referral.request_payout(
        session, user=referrer, wallet_address=WALLET_TRC20, network="TRC20"
    )
    assert (await referral.balances(session, referrer.id))["available"] == 0.0
    await referral.reject_payout(session, payout.id, reason="bad wallet", operator_id=await _admin(session))
    assert (await referral.balances(session, referrer.id))["available"] == 2.0


async def test_hold_not_counted_until_released(session) -> None:
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd="10"))
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)
    await session.flush()
    referrer = await _mk(session, 20, "REFB0001")
    referee = await _mk(session, 21, "REFB0002", referrer_id=referrer.id)
    o = await _paid_order(session, referee=referee, referrer=referrer, amount="10")
    # hold_until is 14 days out → still on hold, available must be 0
    await referral.accrue(session, order=o)
    bal = await referral.balances(session, referrer.id)
    assert bal["available"] == 0.0
    assert bal["hold"] == 2.0
