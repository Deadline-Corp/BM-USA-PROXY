"""The city a phone is sold as comes from the state in its name, when there is one.

The client sells by state and names phones accordingly. The exit IP's own city is real but
unsellable — Rolling Meadows, Sun Prairie, Saint Francis are where carrier pools happen to
sit, and nobody shops for those. So a mapped state wins, and `ip_city` is the fallback for
phones whose name says nothing.

This is a deliberate divergence from the physical location, agreed with the client.
"""

from __future__ import annotations

from typing import Any

from app.models import Connection, Location, StateCity
from app.services.provisioning.sync import sync_pool
from sqlalchemy import select


class _StubIproxy:
    def __init__(self, connections: list[dict[str, Any]]) -> None:
        self.connections = connections

    async def list_connections(self) -> list[dict[str, Any]]:
        return self.connections

    async def connection_status(self) -> list[dict[str, Any]]:
        return [{"id": c["id"], "online_status": "online", "ipv4": "174.1.2.3"} for c in self.connections]


def _conn(cid: str, name: str, ip_city: str) -> dict[str, Any]:
    return {
        "id": cid,
        "basic_info": {"name": name},
        "app_data": {"ip_city": ip_city, "device_info": {}},
    }


async def _city_of(session, cid: str) -> tuple[str | None, str | None]:
    row = (
        await session.execute(
            select(Location.city, Location.state_code)
            .join(Connection, Connection.location_id == Location.id)
            .where(Connection.iproxy_connection_id == cid)
        )
    ).first()
    return (row[0], row[1]) if row else (None, None)


async def test_a_mapped_state_in_the_name_decides_the_city(session) -> None:
    session.add(StateCity(state_code="NV", city="Las Vegas"))
    await session.flush()

    await sync_pool(session, _StubIproxy([_conn("c1", "att113_NV", "Rolling Meadows")]))  # type: ignore[arg-type]
    await session.flush()

    assert await _city_of(session, "c1") == ("Las Vegas", "NV")


async def test_a_phone_with_no_state_in_its_name_keeps_its_exit_ip_city(session) -> None:
    session.add(StateCity(state_code="NV", city="Las Vegas"))
    await session.flush()

    await sync_pool(session, _StubIproxy([_conn("c2", "test_bot_1", "Sun Prairie")]))  # type: ignore[arg-type]
    await session.flush()

    city, _state = await _city_of(session, "c2")
    assert city == "Sun Prairie"


async def test_an_unmapped_state_falls_back_rather_than_inventing_a_city(session) -> None:
    """Nothing is mapped for MI yet, so the phone keeps a real city until somebody adds it."""
    await sync_pool(session, _StubIproxy([_conn("c3", "att900_MI", "Ann Arbor")]))  # type: ignore[arg-type]
    await session.flush()

    city, _state = await _city_of(session, "c3")
    assert city == "Ann Arbor"


async def test_repointing_a_state_moves_every_phone_named_for_it(session) -> None:
    """The client changes their mind about which city NV is sold as."""
    session.add(StateCity(state_code="NV", city="Las Vegas"))
    await session.flush()
    client = _StubIproxy([_conn("c4", "att113_NV", "Rolling Meadows")])
    await sync_pool(session, client)  # type: ignore[arg-type]
    await session.flush()
    assert await _city_of(session, "c4") == ("Las Vegas", "NV")

    mapping = await session.get(StateCity, "NV")
    assert mapping is not None
    mapping.city = "Reno"
    await session.flush()

    await sync_pool(session, client)  # type: ignore[arg-type]
    await session.flush()

    assert await _city_of(session, "c4") == ("Reno", "NV")


async def test_the_state_from_the_name_wins_over_the_city_state_table(session) -> None:
    """Las Vegas is in the built-in city→state table too; the client's row is what counts."""
    session.add(StateCity(state_code="AZ", city="Phoenix"))
    await session.flush()

    await sync_pool(session, _StubIproxy([_conn("c5", "verizon_AZ_1", "Chicago")]))  # type: ignore[arg-type]
    await session.flush()

    assert await _city_of(session, "c5") == ("Phoenix", "AZ")
