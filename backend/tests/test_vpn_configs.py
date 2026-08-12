"""VPN configs: issued once per protocol, and never outliving the access they belong to.

Both rules cost real money if they are only conventions. iproxy caps configs at 20 per
connection, so a customer tapping the button in a loop could exhaust a phone and block
every other buyer on it; and a VPN access has no expiry of its own, so one left behind is
a tunnel the customer keeps for free after the month they paid for has ended.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.errors import ValidationError
from app.models import Access, AccessVpnConfig, Connection, Location, Order, Tariff, User
from app.services import vpn_configs
from app.services.provisioning.lifecycle import revoke_access
from sqlalchemy import func, select


async def _make_access(session, *, status: str = "active") -> Access:
    # unique per call: (city, state_code) is a unique pair, and one test builds two
    loc = Location(city=f"Dallas-{uuid.uuid4().hex[:6]}", state_code="TX")
    session.add(loc)
    await session.flush()
    conn = Connection(
        iproxy_connection_id=f"c-{uuid.uuid4().hex[:8]}", name="phone", location_id=loc.id,
        carrier="Verizon", is_sellable=True, online_status="online",
    )
    user = User(
        tg_user_id=int(uuid.uuid4().int % 10**9), tg_username="buyer",
        referral_code=uuid.uuid4().hex[:8].upper(),
    )
    tariff = Tariff(
        code=f"t{uuid.uuid4().hex[:6]}", name="Daily", kind="auto",
        duration_minutes=1440, price_usd=10, auto_issue=True,
    )
    session.add_all([conn, user, tariff])
    await session.flush()
    order = Order(
        user_id=user.id, tariff_id=tariff.id, tariff_code=tariff.code,
        duration_minutes=1440, amount_usd=10, status="paid",
    )
    session.add(order)
    await session.flush()
    access = Access(
        user_id=user.id, order_id=order.id, connection_id=conn.id,
        tariff_code=tariff.code, status=status, iproxy_access_id="acc-1",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(access)
    await session.flush()
    return access


async def test_second_request_returns_the_same_config(session) -> None:
    """One per protocol per access — asking twice must not create a second."""
    access = await _make_access(session)

    first = await vpn_configs.ensure_config(session, access, "wg")
    second = await vpn_configs.ensure_config(session, access, "wg")
    assert first and second

    rows = await session.scalar(
        select(func.count()).select_from(AccessVpnConfig).where(
            AccessVpnConfig.access_id == access.id
        )
    )
    assert rows == 1

    # …and the two protocols are counted apart, so asking for OpenVPN still works.
    await vpn_configs.ensure_config(session, access, "ovpn")
    rows = await session.scalar(
        select(func.count()).select_from(AccessVpnConfig).where(
            AccessVpnConfig.access_id == access.id
        )
    )
    assert rows == 2


async def test_revoking_the_access_removes_its_configs(session) -> None:
    """The leak this module exists to prevent: a tunnel outliving the purchase."""
    access = await _make_access(session)
    await vpn_configs.ensure_config(session, access, "wg")
    await vpn_configs.ensure_config(session, access, "ovpn")

    await revoke_access(session, access=access, reason="test")
    await session.flush()

    left = await session.scalar(
        select(func.count()).select_from(AccessVpnConfig).where(
            AccessVpnConfig.access_id == access.id
        )
    )
    assert left == 0, "a revoked access must not leave a working VPN config behind"


async def test_a_dead_access_gets_no_config(session) -> None:
    """Issuing against a revoked access would recreate the leak from the front door."""
    access = await _make_access(session, status="revoked")
    assert vpn_configs.available_kinds(access) == []
    # ValidationError specifically: the caller turns it into a 4xx the customer can read,
    # and asserting on bare Exception would pass just as happily on a crash.
    with pytest.raises(ValidationError):
        await vpn_configs.ensure_config(session, access, "wg")


async def test_available_kinds_follows_the_access_state(session) -> None:
    """The mini-app renders buttons from this; it used to be hardcoded to both."""
    access = await _make_access(session)
    assert vpn_configs.available_kinds(access) == ["ovpn", "wg"]
    for dead in ("expired", "revoked", "failed", "provisioning"):
        access.status = dead
        assert vpn_configs.available_kinds(access) == [], dead


async def test_filenames_are_distinct_per_access_and_protocol(session) -> None:
    """Two proxies, two files — "config.conf" twice is how the wrong one gets imported."""
    a = await _make_access(session)
    b = await _make_access(session)
    names = {
        vpn_configs.filename_for(a, "wg"), vpn_configs.filename_for(a, "ovpn"),
        vpn_configs.filename_for(b, "wg"), vpn_configs.filename_for(b, "ovpn"),
    }
    assert len(names) == 4
    assert all(n.startswith("bmusa-") for n in names)
    assert vpn_configs.filename_for(a, "wg").endswith(".conf")   # WireGuard imports .conf
    assert vpn_configs.filename_for(a, "ovpn").endswith(".ovpn")
