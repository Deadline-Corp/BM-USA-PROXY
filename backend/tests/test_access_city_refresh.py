"""A rotated phone's city must not wait on the next sync_pool pass to catch up.

sync_pool already re-resolves every connection's city on every pass (test_pool_sync.py),
but that pass runs at most once a minute. Two call sites can afford to be right sooner
because they already pay for a provider round-trip for another reason entirely: rotating
an IP (the provider call that changes it in the first place) and viewing an access's
detail (already fetching current_ip). Both reuse sync.py's own _resolve_location — this
file checks they actually call it, that the row in the database moves, and that a hiccup
talking to iproxy along the way never breaks the primary action.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models import Access, Connection, Location, Order, Tariff, User
from app.services.provisioning.iproxy import IproxyProvisioner


class _StubIproxyClient:
    """Just enough of IproxyClient for current_exit_ip: one connection, one GET.

    ``city``/``ip`` are writable so a test can simulate the phone having rotated onto a
    new exit IP between calls — the same app_data.ip_city + app_data.device_info.
    ip_public.ipv4 shape IproxyProvisioner.current_exit_ip parses off the real API.
    """

    def __init__(self, *, ip: str | None, city: str | None) -> None:
        self.ip = ip
        self.city = city
        self.get_connection_calls = 0
        self.rotated = False

    async def change_ip(self, connection_id: str) -> None:
        self.rotated = True

    async def get_connection(self, connection_id: str) -> dict[str, Any]:
        self.get_connection_calls += 1
        return {
            "app_data": {
                "ip_city": self.city,
                "device_info": {"ip_public": {"ipv4": self.ip}},
            }
        }


class _UnreachableIproxyClient:
    """change_ip (the rotation itself) succeeds; get_connection blows up unexpectedly.

    A plain RuntimeError, not an IproxyError — this is what reaches rotate_ip's own
    outer guard, as opposed to the IproxyError case current_exit_ip already swallows
    internally (see IproxyProvisioner.current_exit_ip).
    """

    async def change_ip(self, connection_id: str) -> None:
        return None

    async def get_connection(self, connection_id: str) -> dict[str, Any]:
        raise RuntimeError("simulated iproxy outage")


async def _access(
    session, *, city: str = "Boston", state: str = "MA", status: str = "active"
) -> tuple[Access, Connection]:
    tariff = Tariff(code="t-cityref", name="CityRefresh", kind="auto",
                     duration_minutes=60, price_usd=0)
    loc = Location(city=city, state_code=state)
    user = User(tg_user_id=930001, referral_code="CITYREF1")
    session.add_all([tariff, loc, user])
    await session.flush()
    conn = Connection(iproxy_connection_id="cityref-conn-1", location_id=loc.id, is_sellable=True)
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="t-cityref", amount_usd=0)
    session.add_all([conn, order])
    await session.flush()
    access = Access(
        user_id=user.id, order_id=order.id, connection_id=conn.id,
        tariff_code="t-cityref", status=status,
    )
    session.add(access)
    await session.flush()
    return access, conn


async def test_rotate_ip_refreshes_the_city_when_iproxy_reports_a_new_one(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug this pair of files was extended for: location_id used to sit stale until
    the next cron pass, up to a minute after the buyer had already rotated away from it.
    """
    from app.services.provisioning.lifecycle import rotate_ip

    access, conn = await _access(session, city="Boston", state="MA")

    stub = _StubIproxyClient(ip="174.224.240.8", city="Milwaukee")
    monkeypatch.setattr(
        "app.services.provisioning.lifecycle.get_provisioner",
        lambda: IproxyProvisioner(client=stub),  # type: ignore[arg-type]
    )

    await rotate_ip(session, access=access, actor="user")
    await session.flush()

    assert stub.rotated is True
    assert stub.get_connection_calls == 1
    assert conn.location_id is not None
    new_loc = await session.get(Location, conn.location_id)
    assert (new_loc.city, new_loc.state_code) == ("Milwaukee", "WI")


async def test_rotate_ip_survives_iproxy_being_unreachable_for_the_city_refresh(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rotation itself must succeed even when the follow-up city read blows up."""
    from app.services.provisioning.lifecycle import rotate_ip

    access, conn = await _access(session, city="Boston", state="MA")
    original_location_id = conn.location_id

    monkeypatch.setattr(
        "app.services.provisioning.lifecycle.get_provisioner",
        lambda: IproxyProvisioner(client=_UnreachableIproxyClient()),  # type: ignore[arg-type]
    )

    await rotate_ip(session, access=access, actor="user")  # must not raise
    await session.flush()

    assert access.rotations_count == 1  # the rotation itself was still recorded
    assert conn.location_id == original_location_id  # best-effort refresh silently skipped


async def test_viewing_access_detail_refreshes_the_city_when_iproxy_reports_a_new_one(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Viewing the access already pays for a current_ip round-trip; the city rides along."""
    from app.services import accesses as accesses_svc

    access, conn = await _access(session, city="Boston", state="MA")

    stub = _StubIproxyClient(ip="174.224.240.8", city="Milwaukee")
    monkeypatch.setattr(
        "app.services.accesses.get_provisioner",
        lambda: IproxyProvisioner(client=stub),  # type: ignore[arg-type]
    )

    detail = await accesses_svc.detail_for_user(session, str(access.public_id), access.user_id)
    await session.flush()

    assert detail["current_ip"] == "174.224.240.8"
    assert detail["city"] == "Milwaukee"  # the response itself reflects the change
    assert detail["state_code"] == "WI"
    assert stub.get_connection_calls == 1  # one request served both current_ip and the city
    new_loc = await session.get(Location, conn.location_id)
    assert new_loc.city == "Milwaukee"  # and it is persisted, not just echoed in the response


async def test_access_detail_survives_iproxy_being_unreachable(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matches _exit_ip's documented contract: a provider hiccup must not 500 the view."""
    from app.services import accesses as accesses_svc

    access, conn = await _access(session, city="Boston", state="MA")
    original_location_id = conn.location_id

    monkeypatch.setattr(
        "app.services.accesses.get_provisioner",
        lambda: IproxyProvisioner(client=_UnreachableIproxyClient()),  # type: ignore[arg-type]
    )

    detail = await accesses_svc.detail_for_user(session, str(access.public_id), access.user_id)

    assert detail["current_ip"] is None
    assert conn.location_id == original_location_id
    assert detail["city"] == "Boston"  # summary still reflects the untouched location


async def test_a_non_live_access_does_not_touch_the_provider_or_the_city(
    session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """revoked/expired accesses skip the provider entirely — same gate current_ip had."""
    from app.services import accesses as accesses_svc

    access, conn = await _access(session, city="Boston", state="MA", status="revoked")
    original_location_id = conn.location_id

    stub = _StubIproxyClient(ip="174.224.240.8", city="Milwaukee")
    monkeypatch.setattr(
        "app.services.accesses.get_provisioner",
        lambda: IproxyProvisioner(client=stub),  # type: ignore[arg-type]
    )

    detail = await accesses_svc.detail_for_user(session, str(access.public_id), access.user_id)

    assert detail["current_ip"] is None
    assert stub.get_connection_calls == 0
    assert conn.location_id == original_location_id
