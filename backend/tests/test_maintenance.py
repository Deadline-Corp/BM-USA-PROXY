"""Access expiry sweeper + invoice expirer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import (
    Access,
    Connection,
    Invoice,
    Location,
    NotificationOutbox,
    Order,
    Tariff,
    User,
)
from app.services.maintenance import expire_invoices, sweep_access_expiries
from sqlalchemy import func, select


async def _access(session, *, hours: float, status: str = "active") -> Access:
    tariff = Tariff(code=f"t{hours}", name="T", kind="auto", duration_minutes=60, price_usd=0)
    loc = Location(city=f"C{hours}", state_code="WA")
    user = User(tg_user_id=int(hours * 1000) + 5000, referral_code=f"SW{int(hours*10):05d}")
    session.add_all([tariff, loc, user])
    await session.flush()
    conn = Connection(iproxy_connection_id=f"sw-{hours}", location_id=loc.id, is_sellable=True)
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code=tariff.code, amount_usd=0)
    session.add_all([conn, order])
    await session.flush()
    acc = Access(
        user_id=user.id, order_id=order.id, connection_id=conn.id, tariff_code=tariff.code,
        status=status, expires_at=datetime.now(UTC) + timedelta(hours=hours),
    )
    session.add(acc)
    await session.flush()
    return acc


async def _outbox(session, user_id: int, code: str) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(NotificationOutbox).where(
            NotificationOutbox.user_id == user_id, NotificationOutbox.template_code == code
        )
    ) or 0)


async def test_sweeper_expires_due_access(session) -> None:
    acc = await _access(session, hours=-1)  # already past
    await sweep_access_expiries(session)
    assert acc.status == "expired"
    assert acc.revoked_at is not None
    assert await _outbox(session, acc.user_id, "access_expired") == 1


async def test_sweeper_warns_24h(session) -> None:
    acc = await _access(session, hours=12)
    await sweep_access_expiries(session)
    assert acc.status == "expiring"
    assert acc.warned_24h_at is not None
    assert await _outbox(session, acc.user_id, "access_expiring_24h") == 1


async def test_sweeper_is_idempotent_on_warnings(session) -> None:
    acc = await _access(session, hours=12)
    await sweep_access_expiries(session)
    await sweep_access_expiries(session)  # second pass: no duplicate warning
    assert await _outbox(session, acc.user_id, "access_expiring_24h") == 1


async def test_invoice_expirer(session) -> None:
    tariff = Tariff(code="tx", name="T", kind="auto", duration_minutes=60, price_usd="10")
    user = User(tg_user_id=99123, referral_code="INVEXP01")
    session.add_all([tariff, user])
    await session.flush()
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="tx", amount_usd="10",
                  status="awaiting_payment")
    session.add(order)
    await session.flush()
    inv = Invoice(order_id=order.id, provider="mock", provider_invoice_id="exp-1",
                  status="pending", amount_usd="10",
                  expires_at=datetime.now(UTC) - timedelta(minutes=1))
    session.add(inv)
    await session.flush()

    assert await expire_invoices(session) == 1
    assert inv.status == "expired"
    assert order.status == "expired"
