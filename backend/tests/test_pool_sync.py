"""Pool sync — the job that keeps `connections` matching what iproxy actually has.

It runs every minute, and the pool is one row per phone, so the cost of a single pass is
multiplied by both the cadence and the size of the client's farm (~2000 at launch). These
tests pin two things that matter more than they look: that a phone's city keeps up with
its rotating IP, and that a pass where nothing happened stays cheap.
"""

from __future__ import annotations

from typing import Any

from app.models import Connection, Location
from app.services.provisioning.sync import _resolve_location, sync_pool
from sqlalchemy import func, select


class _StubIproxy:
    """Just enough of IproxyClient for sync_pool: both endpoints return the whole account.

    ``connections`` is writable so a test can make a phone report a different city on the
    next pass — which is what a rotated IP looks like from here.
    """

    def __init__(self, connections: list[dict[str, Any]], offline: set[str] | None = None) -> None:
        self.connections = connections
        self.offline = offline or set()
        self.list_calls = 0

    async def list_connections(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return self.connections

    async def connection_status(self) -> list[dict[str, Any]]:
        return [
            {
                "id": c["id"],
                "online_status": "offline" if c["id"] in self.offline else "online",
            }
            for c in self.connections
        ]


def _conn(cid: str, city: str | None) -> dict[str, Any]:
    return {
        "id": cid,
        "basic_info": {"name": f"phone-{cid}"},
        "app_data": {
            "ip_city": city,
            "device_info": {"network_operator_mobile": "Verizon "},
        },
    }


async def _city_of(session, cid: str) -> tuple[str, str] | None:
    """The (city, state) a connection is currently listed under."""
    location_id = await session.scalar(
        select(Connection.location_id).where(Connection.iproxy_connection_id == cid)
    )
    if location_id is None:
        return None
    location = await session.get(Location, location_id)
    return (location.city, location.state_code)


async def test_repeated_city_is_resolved_once_per_pass(session) -> None:
    """The second lookup of a city must not go back to the database.

    Two statements per connection is invisible on a three-phone test account and is ~4000
    round-trips per minute on a launch-sized pool — to resolve a handful of cities.
    """
    cache: dict[str, int | None] = {}

    first = await _resolve_location(session, "Boston", cache)
    assert first is not None
    assert cache["Boston"] == first

    # Poison the entry: it can only come back if the database path was skipped entirely.
    cache["Boston"] = -1
    assert await _resolve_location(session, "Boston", cache) == -1


async def test_resolve_location_without_a_cache_still_works(session) -> None:
    """The cache is an optimisation, not a requirement — callers may omit it."""
    assert await _resolve_location(session, "Boston") is not None
    assert await _resolve_location(session, None) is None
    assert await _resolve_location(session, "   ") is None


async def test_sync_pool_upserts_every_connection_and_reuses_one_location(session) -> None:
    """End-to-end over the stub: every phone lands, one shared city makes one Location."""
    client = _StubIproxy([
        _conn("aaa", "Boston"),
        _conn("bbb", "Boston"),
        _conn("ccc", "Denver"),
    ])

    result = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    assert result["seen"] == 3
    assert result["written"] == 3  # first sighting: all three are inserts
    assert result["online"] == 3
    assert client.list_calls == 1  # one call for the whole pool, not one per phone

    stored = set((await session.scalars(select(Connection.iproxy_connection_id))).all())
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


async def test_a_rotated_phone_follows_its_new_city(session) -> None:
    """The bug this module was rewritten for.

    location_id used to be written once, on first sighting, and never again. A phone's exit
    IP changes on every rotation and its city changes with it, so the row kept advertising
    a city the phone had left — measured live, three phones all still labelled Boston long
    after their addresses had moved to Wisconsin. A later pass must follow the change.
    """
    client = _StubIproxy([_conn("aaa", "Boston")])
    await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()
    assert await _city_of(session, "aaa") == ("Boston", "MA")

    # The phone rotated its IP; iproxy now reports it from somewhere else entirely.
    client.connections = [_conn("aaa", "Milwaukee")]
    result = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    assert result["written"] == 1, "a changed city has to be written, not treated as quiet"
    assert await _city_of(session, "aaa") == ("Milwaukee", "WI")


async def test_city_outside_the_state_map_is_kept_not_dropped(session) -> None:
    """An unmapped city used to become location_id=NULL and the phone vanished from every
    city filter. Saint Francis and Sun Prairie both went that way on the live account.
    The state is what is unknown, not the city, so the city is kept and the state left blank.
    """
    client = _StubIproxy([_conn("zzz", "Nowheresville")])

    result = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    assert result["written"] == 1
    assert await _city_of(session, "zzz") == ("Nowheresville", "")


async def test_a_phone_reporting_no_city_is_still_synced(session) -> None:
    """No city is a normal answer from iproxy, not a reason to skip the phone entirely."""
    client = _StubIproxy([_conn("nocity", None)])

    result = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    assert result["seen"] == 1
    assert await _city_of(session, "nocity") is None
    status = await session.scalar(
        select(Connection.online_status).where(Connection.iproxy_connection_id == "nocity")
    )
    assert status == "online"


async def test_quiet_pass_writes_nothing_yet_still_stamps_freshness(session) -> None:
    """The point of the whole exercise: a minute where nothing happened costs no row writes.

    Freshness must survive that. `synced_at` is how an operator and the ops checks tell
    "the pool is being watched" from "the sync died", so it has to keep moving even when
    every phone reports exactly what it reported a minute ago.
    """
    client = _StubIproxy([_conn("aaa", "Boston"), _conn("bbb", "Denver")])
    await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()
    before = dict(
        (await session.execute(
            select(Connection.iproxy_connection_id, Connection.synced_at)
        )).all()  # type: ignore[arg-type]
    )

    again = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    assert again["seen"] == 2
    assert again["written"] == 0  # nothing moved, so nothing was written row by row
    after = dict(
        (await session.execute(
            select(Connection.iproxy_connection_id, Connection.synced_at)
        )).all()  # type: ignore[arg-type]
    )
    for cid, stamp in before.items():
        assert after[cid] > stamp, f"{cid} stopped looking synced"


async def test_only_the_phone_that_changed_is_written(session) -> None:
    """One phone drops offline; the others must not be rewritten to say so."""
    conns = [_conn("aaa", "Boston"), _conn("bbb", "Boston"), _conn("ccc", "Denver")]
    client = _StubIproxy(conns)
    await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    client.offline = {"bbb"}
    result = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    assert result["written"] == 1
    assert result["online"] == 2
    status = await session.scalar(
        select(Connection.online_status).where(Connection.iproxy_connection_id == "bbb")
    )
    assert status == "offline"


async def test_pool_summary_buckets_cover_every_connection(session) -> None:
    """Free + used + unavailable must always equal the whole pool.

    They did not. `offline` counted only `online_status='offline'`, so a phone reporting
    'unknown' — iproxy's answer when it has not heard from a device — was in no bucket, and
    neither was an online phone an operator had withheld from sale. On the live pool that
    was two of three connections counted nowhere, while their own cards on the same screen
    read "Offline", and the capacity bar drew a third of a track for it.
    """
    from app.api.admin.domain import pool_summary

    session.add_all([
        Connection(iproxy_connection_id="sum-online", online_status="online", is_sellable=True),
        Connection(iproxy_connection_id="sum-unknown", online_status="unknown", is_sellable=True),
        Connection(iproxy_connection_id="sum-offline", online_status="offline", is_sellable=True),
        # online, but an operator took it off the market — sellable capacity it is not
        Connection(iproxy_connection_id="sum-withheld", online_status="online", is_sellable=False),
    ])
    await session.flush()

    s = await pool_summary(admin=None, session=session)  # type: ignore[arg-type]

    assert s["slots_total"] == 4
    assert s["slots_free"] == 1          # only the online, sellable, idle one
    assert s["slots_used"] == 0          # nothing has an access on it
    assert s["slots_unavailable"] == 3   # unknown + offline + withheld
    assert s["slots_free"] + s["slots_used"] + s["slots_unavailable"] == s["slots_total"]

    # and the per-city rows carry the same three, so the dashboard map cannot disagree
    for row in s["cities"]:
        assert (
            row["nodes_free"] + row["nodes_busy"] + row["nodes_unavailable"]
            == row["slots_total"]
        )
