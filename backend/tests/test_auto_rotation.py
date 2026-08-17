"""Scheduled IP rotation: what the interval accepts, and what the sweep acts on.

The floor is one minute — the sweep's own cadence. Anything smaller would be accepted and
then behave exactly like one minute, which is a promise the system cannot keep.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models import Access, Connection, Location, Order, Tariff, User
from app.services.maintenance import sweep_auto_rotations
from sqlalchemy.exc import IntegrityError


async def _access(session, *, minutes: int | None, last_rotated_ago: timedelta | None):
    tariff = Tariff(code="t-rot", name="Rot", kind="auto", duration_minutes=1440, price_usd=10)
    loc = Location(city="Mesa", state_code="AZ")
    user = User(tg_user_id=930001, referral_code="ROT00001")
    session.add_all([tariff, loc, user])
    await session.flush()
    conn = Connection(
        iproxy_connection_id=f"rot-conn-{minutes}-{last_rotated_ago}",
        location_id=loc.id,
        is_sellable=True,
        online_status="online",
    )
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="t-rot", amount_usd=10)
    session.add_all([conn, order])
    await session.flush()
    now = datetime.now(UTC)
    access = Access(
        user_id=user.id,
        order_id=order.id,
        connection_id=conn.id,
        tariff_code="t-rot",
        status="active",
        starts_at=now - timedelta(hours=2),
        expires_at=now + timedelta(hours=10),
        auto_rotate_minutes=minutes,
        last_rotation_at=now - last_rotated_ago if last_rotated_ago else None,
    )
    session.add(access)
    await session.flush()
    return access


async def test_one_minute_is_allowed(session) -> None:
    access = await _access(session, minutes=1, last_rotated_ago=timedelta(hours=1))
    assert access.auto_rotate_minutes == 1


async def test_below_one_minute_is_refused_by_the_database(session) -> None:
    """The API bound is not the only guard — the column refuses it too."""
    with pytest.raises(IntegrityError):
        await _access(session, minutes=0, last_rotated_ago=None)


async def test_the_sweep_rotates_an_access_whose_interval_has_elapsed(session) -> None:
    access = await _access(session, minutes=1, last_rotated_ago=timedelta(minutes=3))
    before = access.rotations_count

    result = await sweep_auto_rotations(session)

    assert result["rotated"] == 1
    assert access.rotations_count == before + 1
    assert access.last_rotation_at is not None


async def test_the_sweep_leaves_an_access_that_is_not_due(session) -> None:
    """A minute's interval rotated thirty seconds ago is not due — the clock is the last
    rotation, whoever triggered it, so a manual rotation postpones the next automatic one."""
    access = await _access(session, minutes=30, last_rotated_ago=timedelta(seconds=30))
    before = access.rotations_count

    result = await sweep_auto_rotations(session)

    assert result["rotated"] == 0
    assert access.rotations_count == before


async def test_the_sweep_ignores_an_access_with_rotation_off(session) -> None:
    await _access(session, minutes=None, last_rotated_ago=timedelta(days=1))

    result = await sweep_auto_rotations(session)

    assert result["rotated"] == 0
