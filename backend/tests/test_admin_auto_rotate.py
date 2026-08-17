"""Support setting the buyer's rotation schedule from the client's dossier.

It lives there rather than on the packages table: a column of "Off" on every row answered
a question that screen is not for, while "make mine rotate every 30 minutes" arrives as a
message from one particular client, next to whose access this belongs.
"""

from __future__ import annotations

import pytest
from app.api.admin.domain import AutoRotateAdminBody, admin_set_auto_rotate
from app.core.errors import Conflict, ValidationError
from app.models import Access, AdminUser, Connection, Location, Order, Tariff, User


async def _access(session, *, status: str = "active") -> tuple[Access, AdminUser]:
    tariff = Tariff(code="t-ar", name="AR", kind="auto", duration_minutes=60, price_usd=1)
    loc = Location(city="Provo", state_code="UT")
    user = User(tg_user_id=980001, referral_code="ADAR0001")
    admin = AdminUser(
        email="ops-ar@bmusproxy.local", display_name="Ops", password_hash="x", role="operator"
    )
    session.add_all([tariff, loc, user, admin])
    await session.flush()
    conn = Connection(iproxy_connection_id="ar-conn-1", location_id=loc.id, is_sellable=True)
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="t-ar", amount_usd=1)
    session.add_all([conn, order])
    await session.flush()
    access = Access(
        user_id=user.id,
        order_id=order.id,
        connection_id=conn.id,
        tariff_code="t-ar",
        status=status,
    )
    session.add(access)
    await session.flush()
    return access, admin


async def test_an_operator_can_set_the_interval(session) -> None:
    access, admin = await _access(session)

    view = await admin_set_auto_rotate(
        str(access.public_id), AutoRotateAdminBody(enabled=True, minutes=30), admin, session
    )

    assert access.auto_rotate_minutes == 30
    assert view["status"] == "active"


async def test_turning_it_off_clears_the_interval(session) -> None:
    access, admin = await _access(session)
    access.auto_rotate_minutes = 45
    await session.flush()

    await admin_set_auto_rotate(
        str(access.public_id), AutoRotateAdminBody(enabled=False), admin, session
    )

    assert access.auto_rotate_minutes is None


async def test_enabling_without_an_interval_is_refused(session) -> None:
    """"On, but how often?" is not a state the sweep can act on."""
    access, admin = await _access(session)

    with pytest.raises(ValidationError):
        await admin_set_auto_rotate(
            str(access.public_id), AutoRotateAdminBody(enabled=True), admin, session
        )


async def test_a_dead_access_cannot_be_scheduled(session) -> None:
    """Nothing runs on a revoked access, so a schedule on it is a promise to nobody."""
    access, admin = await _access(session, status="revoked")

    with pytest.raises(Conflict):
        await admin_set_auto_rotate(
            str(access.public_id), AutoRotateAdminBody(enabled=True, minutes=10), admin, session
        )
