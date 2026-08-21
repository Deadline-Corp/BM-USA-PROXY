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


# ── the screen has to wait for the moment the sweep acts on ──────────────
async def test_the_app_is_told_when_the_next_change_is_due(session) -> None:
    """Auto-rotation changed the address on the server and told the screen nothing.

    A customer watching this page kept seeing the address they already had until they
    reloaded by hand — which is how a working feature reached us as a bug report. The app
    now waits for this timestamp, so it has to be there and it has to be right.
    """
    from app.services.accesses import next_rotation_at

    access = await _access(session, minutes=30, last_rotated_ago=timedelta(minutes=10))

    due = next_rotation_at(access)

    assert due is not None
    assert access.last_rotation_at is not None
    assert due == access.last_rotation_at + timedelta(minutes=30)


async def test_a_never_rotated_access_counts_from_when_it_was_issued(session) -> None:
    """Otherwise the first automatic change is due the instant the proxy is handed over,
    and the screen would ask for a new address before one exists."""
    from app.services.accesses import next_rotation_at

    access = await _access(session, minutes=15, last_rotated_ago=None)

    due = next_rotation_at(access)

    assert due is not None
    assert access.starts_at is not None
    assert due == access.starts_at + timedelta(minutes=15)


async def test_rotation_off_means_the_screen_is_told_to_wait_for_nothing(session) -> None:
    """A null here is what stops the app polling an access that never changes by itself."""
    from app.services.accesses import next_rotation_at

    access = await _access(session, minutes=None, last_rotated_ago=None)

    assert next_rotation_at(access) is None


async def test_while_the_app_is_still_waiting_the_sweep_does_nothing(session) -> None:
    """One rule, two readers. Two copies would drift into a screen that refreshes just
    before the change lands and shows the address the customer already had — the original
    bug wearing a different hat.
    """
    from app.services.accesses import next_rotation_at

    access = await _access(session, minutes=30, last_rotated_ago=timedelta(minutes=5))
    due = next_rotation_at(access)

    assert due is not None and due > datetime.now(UTC)  # the app is still waiting…
    assert (await sweep_auto_rotations(session))["rotated"] == 0  # …and the sweep agrees


async def test_when_the_app_expects_a_change_the_sweep_makes_one(session) -> None:
    """The other half of the same agreement: the moment the screen refreshes for is the
    moment an address actually changes, so the refresh has something new to show."""
    from app.services.accesses import next_rotation_at

    access = await _access(session, minutes=30, last_rotated_ago=timedelta(minutes=31))
    due = next_rotation_at(access)

    assert due is not None and due <= datetime.now(UTC)  # the app expects a change…
    assert (await sweep_auto_rotations(session))["rotated"] == 1  # …and gets one


async def test_the_access_payload_carries_the_due_time(session) -> None:
    """It has to survive the trip to the app, not just exist in the service."""
    from app.services.accesses import detail_for_user

    access = await _access(session, minutes=20, last_rotated_ago=timedelta(minutes=1))
    await session.commit()

    payload = await detail_for_user(session, str(access.public_id), access.user_id)

    assert payload["auto_rotate_minutes"] == 20
    assert payload["next_rotation_at"] is not None
    assert datetime.fromisoformat(payload["next_rotation_at"]) == (
        access.last_rotation_at + timedelta(minutes=20)
    )
