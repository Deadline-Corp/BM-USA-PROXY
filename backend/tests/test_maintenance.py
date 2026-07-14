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


async def _access_span(
    session, *, started_h_ago: float, expires_in_h: float, idx: int, status: str = "active"
) -> Access:
    """Access with an explicit issue→expiry span so the duration-based warning gating
    (trial/daily/weekly) can be exercised. Total granted = started_h_ago + expires_in_h."""
    now = datetime.now(UTC)
    tariff = Tariff(code=f"sp{idx}", name="T", kind="auto", duration_minutes=60, price_usd=0)
    loc = Location(city=f"S{idx}", state_code="WA")
    user = User(tg_user_id=700000 + idx, referral_code=f"SP{idx:05d}")
    session.add_all([tariff, loc, user])
    await session.flush()
    conn = Connection(iproxy_connection_id=f"sp-{idx}", location_id=loc.id, is_sellable=True)
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code=tariff.code, amount_usd=0)
    session.add_all([conn, order])
    await session.flush()
    acc = Access(
        user_id=user.id, order_id=order.id, connection_id=conn.id, tariff_code=tariff.code,
        status=status,
        starts_at=now - timedelta(hours=started_h_ago),
        expires_at=now + timedelta(hours=expires_in_h),
    )
    session.add(acc)
    await session.flush()
    return acc


async def test_trial_gets_no_expiry_warnings(session) -> None:
    # Total granted = 1h (trial): no warnings even though it's within the 1h window.
    acc = await _access_span(session, started_h_ago=0.5, expires_in_h=0.5, idx=11)
    await sweep_access_expiries(session)
    assert acc.warned_1h_at is None
    assert acc.warned_24h_at is None
    assert await _outbox(session, acc.user_id, "access_expiring_1h") == 0
    assert await _outbox(session, acc.user_id, "access_expiring_24h") == 0


async def test_daily_gets_only_1h_warning(session) -> None:
    # Total granted = 24h (daily), 1h from expiry: only the 1h warning, never the 24h one.
    acc = await _access_span(session, started_h_ago=23, expires_in_h=1, idx=12)
    await sweep_access_expiries(session)
    assert acc.warned_1h_at is not None
    assert acc.warned_24h_at is None
    assert await _outbox(session, acc.user_id, "access_expiring_1h") == 1
    assert await _outbox(session, acc.user_id, "access_expiring_24h") == 0


async def test_daily_no_24h_warning_a_day_out(session) -> None:
    # Total granted = 24h, a full day from expiry: the 24h warning is suppressed.
    acc = await _access_span(session, started_h_ago=0, expires_in_h=24, idx=13)
    await sweep_access_expiries(session)
    assert acc.warned_24h_at is None
    assert acc.status == "active"
    assert await _outbox(session, acc.user_id, "access_expiring_24h") == 0


async def test_weekly_gets_24h_warning(session) -> None:
    # Total granted = 7d (weekly), 24h from expiry: gets the 24h warning.
    acc = await _access_span(session, started_h_ago=6 * 24, expires_in_h=24, idx=14)
    await sweep_access_expiries(session)
    assert acc.warned_24h_at is not None
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
