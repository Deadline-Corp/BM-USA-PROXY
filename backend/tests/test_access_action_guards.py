"""What may be done to an access depends on the state it is in.

The admin console offered Revoke, Extend and Rotate on every row regardless of status.
None of the three was a harmless no-op on a revoked access, and only the buyer-facing
app had ever checked — so the guards belong in the service, where both callers meet.
"""

from __future__ import annotations

import pytest
from app.core.errors import Conflict
from app.models import Access, Connection, Location, Order, Tariff, User
from app.services.provisioning.lifecycle import extend_access, revoke_access, rotate_ip
from sqlalchemy import select


async def _access(session, *, status: str) -> Access:
    tariff = Tariff(code="t-guard", name="Guard", kind="auto", duration_minutes=60, price_usd=0)
    loc = Location(city="Austin", state_code="TX")
    user = User(tg_user_id=910001, referral_code="GUARD001")
    session.add_all([tariff, loc, user])
    await session.flush()
    conn = Connection(iproxy_connection_id="guard-conn-1", location_id=loc.id, is_sellable=True)
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="t-guard", amount_usd=0)
    session.add_all([conn, order])
    await session.flush()
    access = Access(
        user_id=user.id, order_id=order.id, connection_id=conn.id,
        tariff_code="t-guard", status=status,
    )
    session.add(access)
    await session.flush()
    return access


async def test_revoking_twice_does_not_forge_a_second_event(session) -> None:
    """The event log is how anyone reconstructs what was done to a customer.

    A second revoke used to succeed and append another `revoked` event describing a
    transition that never occurred.
    """
    from app.models import AccessEvent

    access = await _access(session, status="active")
    await revoke_access(session, access=access, reason="first", actor="admin:1")
    await session.flush()

    with pytest.raises(Conflict):
        await revoke_access(session, access=access, reason="again", actor="admin:1")

    events = list(
        await session.scalars(
            select(AccessEvent).where(
                AccessEvent.access_id == access.id, AccessEvent.type == "revoked"
            )
        )
    )
    assert len(events) == 1, "a refused revoke must not leave a trace in the log"


async def test_a_revoked_access_cannot_be_extended(session) -> None:
    """Extending never revived it — it only moved the expiry and notified the customer."""
    access = await _access(session, status="revoked")
    with pytest.raises(Conflict):
        await extend_access(session, access=access, minutes=60)


async def test_an_expired_access_can_still_be_extended(session) -> None:
    """The guard must not catch the one dead state extend is designed to resurrect."""
    access = await _access(session, status="expired")
    await extend_access(session, access=access, minutes=60)
    assert access.status == "active"


async def test_rotating_through_a_dead_access_is_refused(session) -> None:
    """Revocation frees the connection, so it may already belong to another customer.

    Rotating through the dead access would reach that customer's live proxy and change
    their IP under them.
    """
    for status in ("revoked", "expired", "provisioning"):
        access = await _access(session, status=status)
        with pytest.raises(Conflict):
            await rotate_ip(session, access=access, actor="admin:1")
        await session.rollback()
