"""Promo codes: what a code is worth, who may use it, and when it comes back.

The rules were the client's, decided 2026-09-08: a percentage off, a validity window, a
limit on how many times a code may be used, at most one use per buyer, and per code whether
extensions count. The commission a referrer earns is calculated on what was actually paid,
which is not a separate feature — it falls out of the discount being applied to the order
rather than to the invoice, and there is a test here that says so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.core.errors import ValidationError
from app.models import Order, PromoCode, PromoRedemption, Tariff, User
from app.services import promos, referral
from app.services import settings as settings_svc
from scripts.seed import seed_settings
from sqlalchemy import func, select


def _now() -> datetime:
    return datetime.now(UTC)


async def _user(session, tg: int) -> User:
    u = User(tg_user_id=tg, referral_code=f"PR{tg}")
    session.add(u)
    await session.flush()
    return u


async def _code(session, **kw) -> PromoCode:
    defaults = {"code": "SUMMER", "percent_off": 20, "applies_to": "any"}
    defaults.update(kw)
    promo = PromoCode(**defaults)
    session.add(promo)
    await session.flush()
    return promo


async def _order(session, user: User, *, amount: str = "100", extension: bool = False) -> Order:
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    if tariff is None:
        tariff = Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                        price_usd=Decimal("10.00"), is_active=True)
        session.add(tariff)
        await session.flush()
    o = Order(
        user_id=user.id, tariff_id=tariff.id, tariff_code="daily",
        amount_usd=Decimal(amount), status="awaiting_payment", is_extension=extension,
    )
    session.add(o)
    await session.flush()
    return o


# ── what a code is worth ──────────────────────────────────────────────────


async def test_the_discount_is_a_percentage_of_what_is_being_sold(session) -> None:
    user = await _user(session, 80001)
    await _code(session, percent_off=20)
    d = await promos.quote(session, code="SUMMER", user=user, subtotal_usd=Decimal("23.00"))
    assert d.amount_off_usd == Decimal("4.60")
    assert d.total_usd == Decimal("18.40")


async def test_case_and_stray_spaces_do_not_make_a_different_code(session) -> None:
    """A buyer pastes the code out of a chat message, and brings whitespace with them."""
    user = await _user(session, 80002)
    await _code(session, code="SUMMER")
    for typed in ("summer", "  SuMMer ", "SUMMER"):
        d = await promos.quote(session, code=typed, user=user, subtotal_usd=Decimal("10"))
        assert d.percent_off == 20


async def test_a_code_that_takes_the_whole_price_is_allowed(session) -> None:
    """An operator handing somebody a free month is a real thing to want, and the order
    path already understands a zero total — it is what the trial is."""
    user = await _user(session, 80003)
    await _code(session, percent_off=100)
    d = await promos.quote(session, code="SUMMER", user=user, subtotal_usd=Decimal("23.00"))
    assert d.amount_off_usd == Decimal("23.00")
    assert d.total_usd == Decimal("0.00")


async def test_an_unknown_code_says_so_rather_than_failing_obscurely(session) -> None:
    user = await _user(session, 80004)
    with pytest.raises(ValidationError, match="not found"):
        await promos.quote(session, code="NOPE", user=user, subtotal_usd=Decimal("10"))


# ── the window ────────────────────────────────────────────────────────────


async def test_a_code_outside_its_window_cannot_be_used(session) -> None:
    user = await _user(session, 80010)
    await _code(session, code="EARLY", starts_at=_now() + timedelta(days=1))
    with pytest.raises(ValidationError, match="not active yet"):
        await promos.quote(session, code="EARLY", user=user, subtotal_usd=Decimal("10"))

    await _code(session, code="OVER", expires_at=_now() - timedelta(minutes=1))
    with pytest.raises(ValidationError, match="expired"):
        await promos.quote(session, code="OVER", user=user, subtotal_usd=Decimal("10"))


async def test_a_code_with_no_window_simply_works(session) -> None:
    """"No expiry" is what an operator means by leaving both dates empty."""
    user = await _user(session, 80011)
    await _code(session, code="FOREVER", starts_at=None, expires_at=None)
    d = await promos.quote(session, code="FOREVER", user=user, subtotal_usd=Decimal("50"))
    assert d.total_usd == Decimal("40.00")


# ── the limits ────────────────────────────────────────────────────────────


async def test_one_use_per_buyer_however_many_uses_the_code_has_left(session) -> None:
    """The protection against a code being pasted into a group chat.

    A campaign code with fifty uses is still one use each — otherwise the first person to
    find it spends the whole campaign.
    """
    user = await _user(session, 80020)
    promo = await _code(session, code="CAMPAIGN", max_uses=50)
    order = await _order(session, user)
    await promos.redeem(session, code="CAMPAIGN", user=user, order=order, subtotal_usd=Decimal("10"))
    await session.flush()

    with pytest.raises(ValidationError, match="already used"):
        await promos.quote(session, code="CAMPAIGN", user=user, subtotal_usd=Decimal("10"))

    # …and somebody else still can.
    other = await _user(session, 80021)
    d = await promos.quote(session, code="CAMPAIGN", user=other, subtotal_usd=Decimal("10"))
    assert d.percent_off == promo.percent_off


async def test_a_code_runs_out_when_its_uses_are_spent(session) -> None:
    await _code(session, code="ONCE", max_uses=1)
    first = await _user(session, 80030)
    order = await _order(session, first)
    await promos.redeem(session, code="ONCE", user=first, order=order, subtotal_usd=Decimal("10"))
    await session.flush()

    second = await _user(session, 80031)
    with pytest.raises(ValidationError, match="run out"):
        await promos.quote(session, code="ONCE", user=second, subtotal_usd=Decimal("10"))


async def test_no_limit_means_no_limit(session) -> None:
    await _code(session, code="OPEN", max_uses=None)
    for i in range(4):
        buyer = await _user(session, 80040 + i)
        order = await _order(session, buyer)
        await promos.redeem(
            session, code="OPEN", user=buyer, order=order, subtotal_usd=Decimal("10")
        )
    await session.flush()
    assert await promos.usage_counts(
        session, [(await session.scalar(select(PromoCode.id).where(PromoCode.code == "OPEN")))]
    ) != {}


# ── purchases versus extensions ───────────────────────────────────────────


async def test_a_purchase_only_code_is_refused_on_an_extension(session) -> None:
    """The client asked for this per code rather than as one rule for everything."""
    user = await _user(session, 80050)
    await _code(session, code="NEWONLY", applies_to="purchase")
    extension = await _order(session, user, extension=True)

    with pytest.raises(ValidationError, match="new purchases only"):
        await promos.redeem(
            session, code="NEWONLY", user=user, order=extension, subtotal_usd=Decimal("10")
        )

    purchase = await _order(session, user)
    d = await promos.redeem(
        session, code="NEWONLY", user=user, order=purchase, subtotal_usd=Decimal("10")
    )
    assert d.total_usd == Decimal("8.00")


async def test_an_any_code_works_on_both(session) -> None:
    user = await _user(session, 80060)
    await _code(session, code="BOTH", applies_to="any")
    extension = await _order(session, user, extension=True)
    d = await promos.redeem(
        session, code="BOTH", user=user, order=extension, subtotal_usd=Decimal("30")
    )
    assert d.total_usd == Decimal("24.00")


# ── giving the use back ───────────────────────────────────────────────────


async def test_an_order_that_dies_unpaid_gives_the_code_back(session) -> None:
    """The failure this exists to prevent: a one-use code spent on an invoice nobody paid.

    The buyer opens the checkout, changes their mind, and the code they were handed is gone
    with nothing sold.
    """
    user = await _user(session, 80070)
    await _code(session, code="ONEUSE", max_uses=1)
    order = await _order(session, user)
    await promos.redeem(session, code="ONEUSE", user=user, order=order, subtotal_usd=Decimal("10"))
    await session.flush()

    released = await promos.release(session, order_id=order.id)
    await session.flush()
    assert released == 1

    # the same buyer, and the code's single use, are both available again
    again = await _order(session, user)
    d = await promos.redeem(
        session, code="ONEUSE", user=user, order=again, subtotal_usd=Decimal("10")
    )
    assert d.total_usd == Decimal("8.00")


async def test_releasing_leaves_the_order_saying_what_it_sold_for(session) -> None:
    """Only the claim on the code goes back. What was charged is history and stays."""
    user = await _user(session, 80080)
    promo = await _code(session, code="KEEP", percent_off=25)
    order = await _order(session, user, amount="40")
    d = await promos.redeem(session, code="KEEP", user=user, order=order, subtotal_usd=Decimal("40"))
    order.promo_code_id = promo.id
    order.discount_usd = d.amount_off_usd
    order.amount_usd = d.total_usd
    await session.flush()

    await promos.release(session, order_id=order.id)
    await session.flush()
    await session.refresh(order)

    assert order.promo_code_id == promo.id
    assert Decimal(str(order.discount_usd)) == Decimal("10.00")
    assert Decimal(str(order.amount_usd)) == Decimal("30.00")
    assert await session.scalar(
        select(func.count()).select_from(PromoRedemption).where(PromoRedemption.order_id == order.id)
    ) == 0


# ── a deleted code ────────────────────────────────────────────────────────


async def test_a_deleted_code_stops_working_but_its_orders_survive(session) -> None:
    user = await _user(session, 80090)
    promo = await _code(session, code="OLD")
    order = await _order(session, user)
    await promos.redeem(session, code="OLD", user=user, order=order, subtotal_usd=Decimal("10"))
    order.promo_code_id = promo.id
    await session.flush()

    promo.deleted_at = _now()
    await session.flush()

    other = await _user(session, 80091)
    with pytest.raises(ValidationError, match="not found"):
        await promos.quote(session, code="OLD", user=other, subtotal_usd=Decimal("10"))

    await session.refresh(order)
    assert order.promo_code_id == promo.id, "what was sold under it is not rewritten"


async def test_a_deleted_codes_name_can_be_used_again(session) -> None:
    """The unique index is over living codes only, so a spent campaign does not reserve its
    own name forever."""
    old = await _code(session, code="REUSE", percent_off=10)
    old.deleted_at = _now()
    await session.flush()

    fresh = await _code(session, code="REUSE", percent_off=50)
    await session.flush()

    user = await _user(session, 80100)
    d = await promos.quote(session, code="REUSE", user=user, subtotal_usd=Decimal("20"))
    assert d.percent_off == 50 and d.code.id == fresh.id


# ── the money it touches ──────────────────────────────────────────────────


async def test_the_referrer_earns_on_what_was_actually_paid(session) -> None:
    """The client's rule, and the reason the discount is applied to the order.

    Discounting the invoice alone would have quoted the buyer the right crypto amount and
    then paid commission on the full price — money nobody sent.
    """
    await seed_settings(session)
    await settings_svc.set_value(session, "referral_pct", 23)
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd=Decimal("23.00"), is_active=True))
    await session.flush()

    referrer = await _user(session, 80110)
    buyer = User(tg_user_id=80111, referral_code="PR80111", referrer_user_id=referrer.id)
    session.add(buyer)
    await session.flush()

    await _code(session, code="MINUS20", percent_off=20)
    order = await _order(session, buyer, amount="23.00")
    order.referrer_user_id = referrer.id
    order.status = "completed"
    order.paid_at = _now()
    d = await promos.redeem(
        session, code="MINUS20", user=buyer, order=order, subtotal_usd=Decimal("23.00")
    )
    order.amount_usd = d.total_usd  # what create_order does
    await session.flush()

    await referral.accrue(session, order=order)
    await session.flush()

    earned = await session.scalar(
        select(func.sum(referral.ReferralLedger.amount_usd)).where(
            referral.ReferralLedger.referrer_user_id == referrer.id
        )
    )
    # 23% of $18.40, not of $23.00 — which would have been $5.29.
    assert Decimal(str(earned)) == Decimal("4.23")


# ── which coin an extension is quoted in ──────────────────────────────────


async def test_an_extension_is_quoted_in_the_coin_the_buyer_picked(session, monkeypatch) -> None:
    """It was always bitcoin, whatever they had paid with the first time.

    `create_extension_order` has always accepted a rail; the sheet in the app never asked
    for one, so `asset`/`network` arrived as None and the provider fell back to the first
    configured rail — bitcoin on this account. Reported by the client 2026-09-09.
    """
    from app.models import Access, Connection
    from app.services import orders as orders_svc

    asked: list[tuple[str | None, str | None]] = []

    class _Provider:
        name = "stub"

        async def create_invoice(self, *, order_public_id, amount_usd, ttl_minutes, asset, network):
            asked.append((asset, network))
            from app.services.payments.base import InvoiceDTO

            return InvoiceDTO(
                provider_invoice_id=f"stub-{len(asked)}",
                payment_url=None,
                pay_address="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                crypto_currency=asset or "BTC",
                crypto_network=network or "native",
                crypto_amount=Decimal("1.0001"),
                expires_at_epoch=int(_now().timestamp()) + 3600,
                chain="tron",
                base_amount=Decimal("1"),
                amount_tolerance=Decimal("0"),
                locked_rate=Decimal("1"),
                reference_pubkey=None,
            )

    monkeypatch.setattr(orders_svc, "get_payment_provider", lambda: _Provider())

    async def _no_refresh(_s):
        return None

    monkeypatch.setattr(orders_svc, "refresh_rails_cached", _no_refresh)

    await seed_settings(session)
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd=Decimal("10.00"), is_active=True, auto_issue=True))
    user = await _user(session, 80200)
    conn = Connection(iproxy_connection_id="ext-coin", is_sellable=True, online_status="online")
    session.add(conn)
    await session.flush()
    order = await _order(session, user)
    order.status = "completed"
    access = Access(
        user_id=user.id, order_id=order.id, connection_id=conn.id, tariff_code="daily",
        status="active", expires_at=_now() + timedelta(days=1),
    )
    session.add(access)
    await session.flush()

    await orders_svc.create_extension_order(
        session, user=user, access=access, tariff_code="daily",
        asset="USDT", network="trc20",
    )
    assert asked == [("USDT", "trc20")], "the buyer's choice has to reach the provider"
