"""Refunds — the money going back out, which had no test at all.

Two changes landed here in the final-audit review and both are the kind that only fail
in front of a customer: a multi-proxy order revoked one access out of fifty, and a partial
refund wrote a status the database refuses. Neither was covered, so neither was caught.

What has to hold: everything the customer was refunded for stops working, nothing they
still paid for does, and the order says which of the two happened.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.main import app
from app.models import Access, Connection, Order, Refund, Tariff, User
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_admin, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

_ACTIVE = ("provisioning", "active", "expiring")


@pytest_asyncio.fixture
async def client(engine):
    await redis_client.flushdb()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        await seed_settings(s)
        await seed_tariffs(s)
        await seed_locations(s)
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
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        yield c
    app.dependency_overrides.clear()


async def _paid_order(engine, *, quantity: int, amount: str, tg: int) -> tuple[str, int]:
    """A paid order with `quantity` live accesses. Returns (public_id, order_id)."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        tariff = await s.scalar(select(Tariff).where(Tariff.code == "daily"))
        assert tariff is not None
        user = User(tg_user_id=tg, referral_code=f"RF{tg}")
        s.add(user)
        await s.flush()
        order = Order(
            user_id=user.id,
            tariff_id=tariff.id,
            tariff_code="daily",
            duration_minutes=1440,
            quantity=quantity,
            amount_usd=Decimal(amount),
            status="completed",
            paid_at=datetime.now(UTC),
        )
        s.add(order)
        await s.flush()
        for i in range(quantity):
            conn = Connection(
                iproxy_connection_id=f"rf-{tg}-{i}",
                is_sellable=True,
                online_status="online",
            )
            s.add(conn)
            await s.flush()
            s.add(
                Access(
                    user_id=user.id,
                    order_id=order.id,
                    connection_id=conn.id,
                    tariff_code="daily",
                    status="active",
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
        await s.commit()
        return str(order.public_id), order.id


async def _live_accesses(engine, order_id: int) -> int:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        return int(
            await s.scalar(
                select(func.count())
                .select_from(Access)
                .where(Access.order_id == order_id, Access.status.in_(_ACTIVE))
            )
            or 0
        )


async def _order_status(engine, order_id: int) -> str:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        order = await s.get(Order, order_id)
        assert order is not None
        return order.status


async def test_a_full_refund_revokes_every_proxy_on_the_order(engine, client) -> None:
    """One order can carry fifty proxies, and the revoke looked up exactly one.

    The customer got their money back and kept forty-nine working proxies. The scalar
    query was correct when an order meant one access and quietly wrong from the day
    quantity arrived.
    """
    public_id, order_id = await _paid_order(engine, quantity=5, amount="50.00", tg=6610001)
    assert await _live_accesses(engine, order_id) == 5

    r = await client.post(
        f"/api/admin/orders/{public_id}/refund",
        json={"amount_usd": 50.0, "reason": "customer asked"},
    )

    assert r.status_code == 200, r.text
    assert await _live_accesses(engine, order_id) == 0
    assert await _order_status(engine, order_id) == "refunded"


async def test_a_partial_refund_is_not_recorded_as_a_full_one(engine, client) -> None:
    """`partially_refunded` is a real status the database has to accept.

    The review added it without widening the check constraint, and no test asked. Measured
    against the schema, the write fails with `violates check constraint
    ck_orders_status_valid` — so the operator presses Refund, sees an error, and the money
    does not move.
    """
    public_id, order_id = await _paid_order(engine, quantity=3, amount="30.00", tg=6610002)

    r = await client.post(
        f"/api/admin/orders/{public_id}/refund",
        json={"amount_usd": 10.0, "reason": "one of three was faulty"},
    )

    assert r.status_code == 200, r.text
    assert await _order_status(engine, order_id) == "partially_refunded"


async def test_refunds_may_not_add_up_past_the_order(engine, client) -> None:
    """Two partial refunds are fine; a third that exceeds the total is not."""
    public_id, order_id = await _paid_order(engine, quantity=2, amount="20.00", tg=6610003)

    first = await client.post(
        f"/api/admin/orders/{public_id}/refund", json={"amount_usd": 8.0, "reason": "a"}
    )
    assert first.status_code == 200, first.text

    over = await client.post(
        f"/api/admin/orders/{public_id}/refund", json={"amount_usd": 15.0, "reason": "b"}
    )
    assert over.status_code >= 400, "8 + 15 is more than the order was worth"

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        total = await s.scalar(
            select(func.coalesce(func.sum(Refund.amount_usd), 0)).where(
                Refund.order_id == order_id
            )
        )
    assert Decimal(str(total)) == Decimal("8.00")


async def test_the_last_partial_refund_completes_the_order(engine, client) -> None:
    """Paying the rest back has to close it as fully refunded, not leave it partial."""
    public_id, order_id = await _paid_order(engine, quantity=2, amount="20.00", tg=6610004)

    await client.post(
        f"/api/admin/orders/{public_id}/refund", json={"amount_usd": 5.0, "reason": "a"}
    )
    assert await _order_status(engine, order_id) == "partially_refunded"

    rest = await client.post(
        f"/api/admin/orders/{public_id}/refund", json={"amount_usd": 15.0, "reason": "b"}
    )

    assert rest.status_code == 200, rest.text
    assert await _order_status(engine, order_id) == "refunded"
    assert await _live_accesses(engine, order_id) == 0


async def test_an_unpaid_order_cannot_be_refunded(engine, client) -> None:
    """There is nothing to send back, and pretending otherwise writes a Refund row."""
    public_id, order_id = await _paid_order(engine, quantity=1, amount="10.00", tg=6610005)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        order = await s.get(Order, order_id)
        assert order is not None
        order.paid_at = None
        await s.commit()

    r = await client.post(
        f"/api/admin/orders/{public_id}/refund", json={"amount_usd": 10.0, "reason": "x"}
    )

    assert r.status_code >= 400
