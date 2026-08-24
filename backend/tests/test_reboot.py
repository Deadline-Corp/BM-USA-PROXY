"""Rebooting the phone behind a proxy.

Not a heavier Rotate IP. Rotation redials the data connection and the port is back in
seconds; a reboot restarts the device, so the proxy is down for a minute or two — which is
why it carries its own, much longer cooldown and why nothing here claims the phone came
back. iproxy answers "command has been sent" without waiting for the device, and a phone
with Owner Mode off ignores it entirely.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.core.errors import Conflict
from app.models import Access, AccessEvent, Connection, Order, Tariff, User
from app.services.provisioning.lifecycle import reboot_device
from sqlalchemy import func, select


class _RecordingProvisioner:
    """Stands in for iproxy and remembers what it was asked to do."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.rebooted: list[str] = []
        self.rotated: list[str] = []
        self._fail = fail

    async def reboot(self, *, iproxy_connection_id: str) -> None:
        if self._fail is not None:
            raise self._fail
        self.rebooted.append(iproxy_connection_id)

    async def rotate_ip(self, *, iproxy_connection_id: str) -> None:
        self.rotated.append(iproxy_connection_id)


async def _live_access(session, *, tg: int, status: str = "active") -> Access:
    tariff = Tariff(
        code=f"rb-{tg}", name="Daily", kind="auto", auto_issue=True,
        duration_minutes=1440, price_usd="10", is_active=True,
    )
    user = User(tg_user_id=tg, referral_code=f"RB{tg}")
    conn = Connection(
        iproxy_connection_id=f"rb-conn-{tg}", is_sellable=True, online_status="online"
    )
    session.add_all([tariff, user, conn])
    await session.flush()
    order = Order(
        user_id=user.id, tariff_id=tariff.id, tariff_code=tariff.code,
        duration_minutes=1440, amount_usd=10, status="completed",
    )
    session.add(order)
    await session.flush()
    access = Access(
        user_id=user.id, order_id=order.id, connection_id=conn.id,
        tariff_code=tariff.code, status=status,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(access)
    await session.flush()
    return access


async def _reboot_events(session, access_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(AccessEvent)
            .where(AccessEvent.access_id == access_id, AccessEvent.type == "reboot")
        )
        or 0
    )


async def test_a_reboot_reaches_the_phone_behind_this_access(session, monkeypatch) -> None:
    """The command has to name the customer's own connection, not any other."""
    from app.services.provisioning import lifecycle

    prov = _RecordingProvisioner()
    monkeypatch.setattr(lifecycle, "get_provisioner", lambda: prov)
    access = await _live_access(session, tg=7710001)

    await reboot_device(session, access=access, actor="user")
    await session.flush()

    assert prov.rebooted == ["rb-conn-7710001"]
    assert prov.rotated == [], "a reboot is not a rotation"


async def test_the_reboot_is_written_to_the_access_timeline(session, monkeypatch) -> None:
    """`reboot` is a whitelisted event type only because a migration added it.

    Written without widening the check constraint it fails at the last moment: the command
    reaches iproxy and the transaction rolls back on the log line, so the phone restarts
    and the record of why does not exist.
    """
    from app.services.provisioning import lifecycle

    monkeypatch.setattr(lifecycle, "get_provisioner", lambda: _RecordingProvisioner())
    access = await _live_access(session, tg=7710002)

    await reboot_device(session, access=access, actor="admin:7")
    await session.flush()

    assert await _reboot_events(session, access.id) == 1
    event = await session.scalar(
        select(AccessEvent).where(
            AccessEvent.access_id == access.id, AccessEvent.type == "reboot"
        )
    )
    assert event is not None and event.actor == "admin:7"


@pytest.mark.parametrize("status", ["revoked", "expired", "failed", "provisioning"])
async def test_only_a_live_access_may_reboot_its_phone(session, monkeypatch, status) -> None:
    """Revoking an access frees its phone for somebody else.

    Rebooting through a dead one would take a different customer's proxy down for two
    minutes, which is the same reason rotation checks this.
    """
    from app.services.provisioning import lifecycle

    prov = _RecordingProvisioner()
    monkeypatch.setattr(lifecycle, "get_provisioner", lambda: prov)
    access = await _live_access(session, tg=7710010 + len(status), status=status)

    with pytest.raises(Conflict):
        await reboot_device(session, access=access, actor="user")

    assert prov.rebooted == [], "no command may reach a phone this access no longer holds"


async def test_a_provider_failure_leaves_no_record_of_a_reboot(session, monkeypatch) -> None:
    """The event says the command was accepted. If it was not, there is nothing to say."""
    from app.core.errors import ProvisioningError
    from app.services.provisioning import lifecycle

    monkeypatch.setattr(
        lifecycle,
        "get_provisioner",
        lambda: _RecordingProvisioner(fail=ProvisioningError("iproxy reboot failed: 502")),
    )
    access = await _live_access(session, tg=7710003)

    with pytest.raises(ProvisioningError):
        await reboot_device(session, access=access, actor="user")

    assert await _reboot_events(session, access.id) == 0


async def test_the_expiring_state_still_counts_as_live(session, monkeypatch) -> None:
    """An access in its last hour is still the customer's, and a wedged phone in that hour
    is exactly when they need this."""
    from app.services.provisioning import lifecycle

    prov = _RecordingProvisioner()
    monkeypatch.setattr(lifecycle, "get_provisioner", lambda: prov)
    access = await _live_access(session, tg=7710004, status="expiring")

    await reboot_device(session, access=access, actor="user")
    await session.flush()

    assert prov.rebooted == ["rb-conn-7710004"]


async def test_the_two_screens_share_one_cooldown(session, monkeypatch) -> None:
    """One phone, one restart window — whichever screen asked.

    The customer's button lives on an access and the console's on a connection, so it is
    natural to key their cooldowns on those two different ids. That would let a reboot
    from the mini app and a reboot from the console land seconds apart, and the second one
    arrives while the device is still booting. Both key on the phone instead.
    """
    from app.api.admin.domain import reboot_connection
    from app.api.twa.router import reboot as twa_reboot
    from app.core.errors import RateLimited
    from app.core.redis import redis_client
    from app.models import AdminUser
    from app.services.provisioning import lifecycle

    prov = _RecordingProvisioner()
    monkeypatch.setattr(lifecycle, "get_provisioner", lambda: prov)
    monkeypatch.setattr(
        "app.services.provisioning.registry.get_provisioner", lambda: prov, raising=False
    )
    access = await _live_access(session, tg=7710005)
    user = await session.get(User, access.user_id)
    admin = AdminUser(
        email="ops-reboot@example.test",
        password_hash="x",
        display_name="Ops",
        role="owner",
    )
    session.add(admin)
    await session.flush()
    await redis_client.delete(f"cd:reboot:conn:{access.connection_id}")

    assert user is not None
    await twa_reboot(access.public_id, user, session)

    # Same phone, other screen, immediately after.
    with pytest.raises(RateLimited):
        await reboot_connection(access.connection_id, admin, session)

    assert prov.rebooted == ["rb-conn-7710005"], "the second command must not have gone out"
    await redis_client.delete(f"cd:reboot:conn:{access.connection_id}")
