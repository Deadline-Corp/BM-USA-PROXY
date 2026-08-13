"""An order has a number an operator can read, and the number has to work everywhere.

Showing `#412` in a table and accepting only `6c7476ed-…` in the box beside it is the
failure this guards against: the console would be teaching a value it then refuses. So the
number is checked in the three places it appears — the list, the search, the attach box —
and the id is checked to still work, because the customer's payment link is built from it
and the candidate list still hands it over.

The id stays a UUID on purpose. `/pay/{public_id}` is opened from an external browser with
no session to check; a sequential number there would let anyone walk every order.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from app.api import deps
from app.core.config import settings
from app.core.redis import redis_client
from app.main import app
from app.models import Invoice, OnchainDepositLedger, Order, Tariff, User
from httpx import ASGITransport, AsyncClient
from scripts.seed import seed_admin, seed_settings
from sqlalchemy.ext.asyncio import async_sessionmaker


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


async def _make_orders(maker, count: int = 3) -> list[tuple[int, str]]:
    """`count` paid-pending orders. Returns (number, public_id) for each."""
    async with maker() as s:
        buyer = User(tg_user_id=880_001, tg_username="numbuyer", referral_code="numcode")
        tariff = Tariff(code="daily-num", name="Daily", kind="auto",
                        duration_minutes=1440, price_usd="10")
        s.add_all([buyer, tariff])
        await s.flush()
        made = []
        for i in range(count):
            order = Order(user_id=buyer.id, tariff_id=tariff.id, tariff_code=tariff.code,
                          amount_usd=10 + i, status="awaiting_payment",
                          created_at=datetime.now(UTC))
            s.add(order)
            await s.flush()
            made.append((order.id, str(order.public_id)))
        await s.commit()
        return made


async def test_the_list_carries_a_number_beside_the_id(ctx) -> None:
    boss, maker = ctx
    made = await _make_orders(maker)
    rows = (await boss.get("/api/admin/orders")).json()["items"]
    by_id = {r["id"]: r for r in rows}
    for number, public_id in made:
        assert by_id[public_id]["number"] == number
        # The id is still there: actions take it, and the buyer's pay link is built from it.
        assert by_id[public_id]["id"] == public_id


async def test_attach_accepts_the_number_the_console_shows(ctx) -> None:
    """The box under the candidate list. An operator who has just read `#412` off the table
    types `#412`, and it has to mean that order."""
    boss, maker = ctx
    made = await _make_orders(maker, count=1)
    number, _public_id = made[0]
    async with maker() as s:
        order = await s.get(Order, number)
        invoice = Invoice(order_id=order.id, provider="onchain", status="pending",
                          amount_usd=order.amount_usd, crypto_amount=10,
                          provider_invoice_id=f"inv-{number}",
                          expires_at=datetime.now(UTC) + timedelta(hours=1))
        s.add(invoice)
        await s.flush()
        deposit = OnchainDepositLedger(
            chain="tron", asset="USDT", network="mainnet", txid=f"0xtest{number}",
            log_index=0, from_address="Tfrom", to_address="Tto", amount=10,
            status="unmatched", confirmations=30, block_number=1,
            observed_at=datetime.now(UTC),
        )
        s.add(deposit)
        await s.flush()
        deposit_id = deposit.id
        await s.commit()

    r = await boss.post(
        f"/api/admin/payments/ledger/{deposit_id}/attach", json={"order_public_id": f"#{number}"}
    )
    # Either it attached, or it failed for a reason that is not "no such order" — what is
    # being pinned here is that the number resolved to a real order at all.
    assert r.status_code != 404, r.text


async def test_a_number_that_belongs_to_nobody_is_a_clean_404(ctx) -> None:
    boss, maker = ctx
    await _make_orders(maker, count=1)
    async with maker() as s:
        deposit = OnchainDepositLedger(
            chain="tron", asset="USDT", network="mainnet", txid="0xnosuch",
            log_index=0, from_address="Tfrom", to_address="Tto", amount=10,
            status="unmatched", confirmations=30, block_number=1,
            observed_at=datetime.now(UTC),
        )
        s.add(deposit)
        await s.flush()
        deposit_id = deposit.id
        await s.commit()

    r = await boss.post(
        f"/api/admin/payments/ledger/{deposit_id}/attach", json={"order_public_id": "#999999"}
    )
    assert r.status_code == 404, r.text
    # …and so is a value that is neither a number nor an id, rather than a 500.
    r = await boss.post(
        f"/api/admin/payments/ledger/{deposit_id}/attach", json={"order_public_id": "not-an-id"}
    )
    assert r.status_code == 404, r.text


async def test_searching_a_number_finds_that_order_only(ctx) -> None:
    """Whole-number matching, not substring: with orders 1..12 in the table, searching 1
    must not return 1, 10, 11 and 12."""
    boss, maker = ctx
    made = await _make_orders(maker, count=12)
    async with maker() as s:
        # Accesses are what the packages screen lists, so give each order one.
        from app.models import Access, Connection, Location

        loc = Location(city="Boston", state_code="MA")
        s.add(loc)
        await s.flush()
        for number, _pub in made:
            conn = Connection(iproxy_connection_id=f"c{number}", name=f"phone-{number}",
                              location_id=loc.id, carrier="Verizon")
            s.add(conn)
            await s.flush()
            s.add(Access(user_id=(await s.get(Order, number)).user_id, order_id=number,
                         connection_id=conn.id, tariff_code="daily-num", status="active",
                         expires_at=datetime.now(UTC)))
        await s.commit()

    first_number = made[0][0]
    # "#N" — the form the console prints and CopyInline hands over — means that order and
    # nothing else, even though every row here shares a buyer whose telegram id contains
    # the same digits.
    rows = (await boss.get(f"/api/admin/accesses?q=%23{first_number}")).json()["items"]
    assert [r["order_number"] for r in rows] == [first_number], rows

    # Bare digits stay broad on purpose — a telegram id typed from memory still works —
    # but the exact order is in there rather than lost.
    rows = (await boss.get(f"/api/admin/accesses?q={first_number}")).json()["items"]
    assert first_number in [r["order_number"] for r in rows]
