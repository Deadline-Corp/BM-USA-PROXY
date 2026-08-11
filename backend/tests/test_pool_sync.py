"""Pool sync — the job that keeps `connections` matching what iproxy actually has.

It runs every minute, and the pool is one row per phone, so the cost of a single pass is
multiplied by both the cadence and the size of the client's farm (~2000 at launch). These
tests pin the part that scales badly if it regresses: resolving a city to a location id.
"""

from __future__ import annotations

from typing import Any

from app.models import Connection, Location
from app.services.provisioning.sync import _resolve_location, sync_pool
from sqlalchemy import func, select


class _StubIproxy:
    """Just enough of IproxyClient for sync_pool: both endpoints return the whole account."""

    def __init__(self, connections: list[dict[str, Any]]) -> None:
        self._connections = connections
        self.list_calls = 0

    async def list_connections(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return self._connections

    async def connection_status(self) -> list[dict[str, Any]]:
        return [{"id": c["id"], "online_status": "online"} for c in self._connections]


def _conn(cid: str, city: str) -> dict[str, Any]:
    return {
        "id": cid,
        "basic_info": {"name": f"phone-{cid}"},
        "app_data": {
            "ip_city": city,
            "device_info": {"network_operator_mobile": "Verizon "},
        },
    }


async def test_repeated_city_is_resolved_once_per_pass(session) -> None:
    """The second lookup of a city must not go back to the database.

    Two statements per connection is invisible on a three-phone test account and is ~4000
    round-trips per minute on a launch-sized pool — to resolve nine distinct cities.
    """
    cache: dict[str, int | None] = {}

    first = await _resolve_location(session, "Boston", cache)
    assert first is not None
    assert cache["Boston"] == first

    # Poison the entry: it can only come back if the database path was skipped entirely.
    cache["Boston"] = -1
    assert await _resolve_location(session, "Boston", cache) == -1

    # Unmapped cities are remembered too — a pool full of them would otherwise pay the
    # lookup every time and get None every time.
    assert await _resolve_location(session, "Atlantis", cache) is None
    assert cache["Atlantis"] is None


async def test_resolve_location_without_a_cache_still_works(session) -> None:
    """The cache is an optimisation, not a requirement — callers may omit it."""
    assert await _resolve_location(session, "Boston") is not None
    assert await _resolve_location(session, None) is None


async def test_sync_pool_upserts_every_connection_and_reuses_one_location(session) -> None:
    """End-to-end over the stub: every phone lands, one shared city makes one Location."""
    client = _StubIproxy([_conn("aaa", "Boston"), _conn("bbb", "Boston"), _conn("ccc", "Denver")])

    result = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    assert result["upserted"] == 3
    assert result["online"] == 3
    assert client.list_calls == 1  # one call for the whole pool, not one per phone

    stored = set(
        (await session.scalars(select(Connection.iproxy_connection_id))).all()
    )
    assert {"aaa", "bbb", "ccc"} <= stored

    boston = await session.scalar(
        select(func.count()).select_from(Location).where(Location.city == "Boston")
    )
    assert boston == 1

    # Carrier normalisation is what the allocator filters on — the API sends "Verizon ".
    carrier = await session.scalar(
        select(Connection.carrier).where(Connection.iproxy_connection_id == "aaa")
    )
    assert carrier == "Verizon"
