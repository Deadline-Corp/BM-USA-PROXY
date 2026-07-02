"""INVARIANT #2: a connection can hold at most one live access (dedicated pool).

Enforced by the partial unique index `uq_connection_active_access`. This is the
single most important data guarantee in the system — one phone is never sold twice.
"""

from __future__ import annotations

import pytest
from app.models import Access, Connection, Location, Order, Tariff, User
from sqlalchemy.exc import IntegrityError


async def _chain(session) -> tuple[int, int, int]:
    """Create the FK prerequisites; return (user_id, order_id, connection_id)."""
    tariff = Tariff(code="t-alloc", name="Alloc", kind="auto", duration_minutes=60, price_usd=0)
    loc = Location(city="Seattle", state_code="WA")
    user = User(tg_user_id=900001, referral_code="ALLOC001")
    session.add_all([tariff, loc, user])
    await session.flush()
    conn = Connection(iproxy_connection_id="alloc-conn-1", location_id=loc.id, is_sellable=True)
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="t-alloc", amount_usd=0)
    session.add_all([conn, order])
    await session.flush()
    return user.id, order.id, conn.id


async def test_two_active_accesses_on_one_connection_rejected(session) -> None:
    user_id, order_id, conn_id = await _chain(session)
    session.add(
        Access(user_id=user_id, order_id=order_id, connection_id=conn_id,
               tariff_code="t-alloc", status="active")
    )
    await session.flush()

    session.add(
        Access(user_id=user_id, order_id=order_id, connection_id=conn_id,
               tariff_code="t-alloc", status="provisioning")
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_revoked_access_frees_the_connection(session) -> None:
    """A revoked/expired access must NOT occupy the slot (partial index excludes them)."""
    user_id, order_id, conn_id = await _chain(session)
    session.add(
        Access(user_id=user_id, order_id=order_id, connection_id=conn_id,
               tariff_code="t-alloc", status="revoked")
    )
    await session.flush()

    # A fresh active access on the same connection is allowed once the old one is revoked.
    session.add(
        Access(user_id=user_id, order_id=order_id, connection_id=conn_id,
               tariff_code="t-alloc", status="active")
    )
    await session.flush()  # must not raise
