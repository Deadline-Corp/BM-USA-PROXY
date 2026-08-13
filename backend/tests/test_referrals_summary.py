"""The five numbers above the referrals screen have to be the five numbers on the screen.

They were not. The endpoint returned the ledger grouped by status — `{"paid": 1.84}` —
and the console asked for `total_referrers`, `total_clicks`, `total_attached`,
`total_paid_usd`, `pending_payouts`. Nothing matched, so every card read zero, including
"Paid out" on a day money had actually been paid out. A dashboard that is confidently wrong
is worse than one that is missing: nobody goes looking behind a number that looks fine.

So each card is checked against data built here on purpose, and each is checked to *move* —
a query that returns a constant zero would pass a test that only asserts "zero".
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.main import app
from app.models import Order, Payout, ReferralLedger, Tariff, User
from app.services import referral
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_admin, seed_settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


def _user(n: int, **over) -> User:
    row = {
        "tg_user_id": 900_000 + n,
        "tg_username": f"user{n}",
        "referral_code": f"code{n}",
    }
    row.update(over)
    return User(**row)


@pytest_asyncio.fixture
async def ctx(engine):
    await redis_client.flushdb()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_admin(s)
        await s.commit()

    async def _db():
        async with maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[deps.db_session] = _db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        pwd = settings.seed_admin_password
        assert pwd is not None
        r = await c.post(
            "/api/admin/auth/login",
            json={"email": settings.seed_admin_email, "password": pwd.get_secret_value()},
        )
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c, maker
    app.dependency_overrides.clear()


async def _summary(client) -> dict:
    r = await client.get("/api/admin/referrals/summary")
    assert r.status_code == 200, r.text
    return r.json()


async def test_an_empty_programme_reads_zero(ctx) -> None:
    boss, _ = ctx
    assert await _summary(boss) == {
        "total_referrers": 0,
        "total_clicks": 0,
        "total_attached": 0,
        "total_paid_usd": 0.0,
        "pending_payouts": 0,
    }


async def test_every_card_reflects_its_own_data(ctx) -> None:
    """One arrangement, five numbers, each different — so a card cannot be quietly reading
    somebody else's query and still look right."""
    boss, maker = ctx
    async with maker() as s:
        alice, bob, carol = _user(1), _user(2), _user(3)
        s.add_all([alice, bob, carol])
        await s.flush()
        # Two people brought in by one referrer, a third by another: 2 referrers, 3 attached.
        dave, erin, frank = (
            _user(4, referrer_user_id=alice.id),
            _user(5, referrer_user_id=alice.id),
            _user(6, referrer_user_id=bob.id),
        )
        s.add_all([dave, erin, frank])
        alice.referral_clicks = 7
        bob.referral_clicks = 3
        await s.flush()
        # Commissions hang off real orders — referral_ledger.order_id is NOT NULL.
        tariff = Tariff(code="daily-refsum", name="Daily", kind="auto",
                        duration_minutes=1440, price_usd="10")
        s.add(tariff)
        await s.flush()

        def _accrual(referrer, referee, amount, status):
            order = Order(user_id=referee.id, tariff_id=tariff.id, tariff_code=tariff.code,
                          amount_usd=amount, status="completed",
                          referrer_user_id=referrer.id, paid_at=datetime.now(UTC))
            s.add(order)
            return order, referrer, referee, amount, status

        planned = [
            _accrual(alice, dave, 5, "paid"),
            _accrual(bob, frank, 2.5, "paid"),
            # Not paid — must not land in "Paid out".
            _accrual(alice, erin, 99, "available"),
        ]
        await s.flush()
        s.add_all([
            ReferralLedger(referrer_user_id=referrer.id, referee_user_id=referee.id,
                           order_id=order.id, kind="accrual", base_amount_usd=amount,
                           pct=23, amount_usd=amount, status=status)
            for order, referrer, referee, amount, status in planned
        ])
        s.add_all([
            Payout(referrer_user_id=alice.id, amount_usd=5, wallet_address="w1",
                   network="trc20", status="requested"),
            Payout(referrer_user_id=bob.id, amount_usd=2.5, wallet_address="w2",
                   network="trc20", status="approved"),
            # Already settled — the queue does not show it, so neither does the card.
            Payout(referrer_user_id=carol.id, amount_usd=1, wallet_address="w3",
                   network="trc20", status="paid"),
        ])
        await s.commit()

    assert await _summary(boss) == {
        "total_referrers": 2,
        "total_clicks": 10,
        "total_attached": 3,
        "total_paid_usd": 7.5,
        "pending_payouts": 2,
    }


async def test_a_click_lands_on_the_link_owner(ctx) -> None:
    boss, maker = ctx
    async with maker() as s:
        owner, visitor = _user(1), _user(2)
        s.add_all([owner, visitor])
        await s.commit()
        await referral.record_click(s, code="code1", visitor=visitor)
        await s.commit()
        assert await s.scalar(select(User.referral_clicks).where(User.id == owner.id)) == 1
        assert await s.scalar(select(User.referral_clicks).where(User.id == visitor.id)) == 0
    assert (await _summary(boss))["total_clicks"] == 1


async def test_opening_your_own_link_is_not_a_click(ctx) -> None:
    """The one number a referrer could otherwise inflate from their own phone."""
    boss, maker = ctx
    async with maker() as s:
        owner = _user(1)
        s.add(owner)
        await s.commit()
        await referral.record_click(s, code="code1", visitor=owner)
        await s.commit()
    assert (await _summary(boss))["total_clicks"] == 0


async def test_a_click_counts_even_when_the_visitor_cannot_be_bound(ctx) -> None:
    """This is the whole point of the card: clicks that do not convert are the ones worth
    knowing about. Counting only successful bindings would just restate `total_attached`."""
    boss, maker = ctx
    async with maker() as s:
        owner, other, visitor = _user(1), _user(2), _user(3)
        s.add_all([owner, other])
        await s.flush()
        visitor.referrer_user_id = other.id  # already belongs to somebody else
        s.add(visitor)
        await s.commit()

        bound = await referral.try_bind(s, referee=visitor, code="code1")
        await referral.record_click(s, code="code1", visitor=visitor)
        await s.commit()
        assert bound is False

    summary = await _summary(boss)
    assert summary["total_clicks"] == 1
    assert summary["total_attached"] == 1  # unchanged — the click did not become a sign-up


async def test_the_referrer_sees_their_own_opens_not_everyones(ctx, engine) -> None:
    """The mini-app tile is per person; the admin card is the whole business. Reading the
    wrong one would tell a referrer with 2 opens that they had 9."""
    _boss, maker = ctx
    async with maker() as s:
        me, someone_else = _user(1), _user(2)
        me.referral_clicks = 2
        someone_else.referral_clicks = 7
        s.add_all([me, someone_else])
        await s.commit()
        my_identity = {
            "tg_user_id": me.tg_user_id, "tg_username": me.tg_username,
            "first_name": None, "last_name": None, "lang": "en", "start_param": None,
        }

    app.dependency_overrides[deps.twa_identity] = lambda: dict(my_identity)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/api/twa/referral")
            assert r.status_code == 200, r.text
            assert r.json()["link_opens"] == 2
    finally:
        app.dependency_overrides.pop(deps.twa_identity, None)


async def test_an_unknown_code_counts_for_nobody(ctx) -> None:
    boss, maker = ctx
    async with maker() as s:
        s.add(_user(1))
        await s.commit()
        await referral.record_click(s, code="no-such-code", visitor=_user(2))
        await s.commit()
    assert (await _summary(boss))["total_clicks"] == 0
