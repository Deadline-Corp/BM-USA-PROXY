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
    """Just enough of IproxyClient for sync_pool: both endpoints return the whole account.

    ``get_connection`` backs IproxyProvisioner.current_ip — the real exit-IP lookup —
    so it also has to exist here, returning whatever ``exit_ip`` the fixture carries.
    """

    def __init__(self, connections: list[dict[str, Any]], offline: set[str] | None = None) -> None:
        self._connections = connections
        self.offline = offline or set()
        self.list_calls = 0
        self.get_connection_calls = 0

    async def list_connections(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return self._connections

    async def connection_status(self) -> list[dict[str, Any]]:
        return [
            {
                "id": c["id"],
                "online_status": "offline" if c["id"] in self.offline else "online",
            }
            for c in self._connections
        ]

    async def get_connection(self, connection_id: str) -> dict[str, Any]:
        self.get_connection_calls += 1
        exit_ip = next(
            (c.get("_exit_ip") for c in self._connections if c["id"] == connection_id), None
        )
        return {"app_data": {"device_info": {"ip_public": {"ipv4": exit_ip}}}}


def _conn(cid: str, city: str, exit_ip: str | None = None) -> dict[str, Any]:
    return {
        "id": cid,
        "basic_info": {"name": f"phone-{cid}"},
        "app_data": {
            # iproxy's own claimed city — sync_pool must not use this for location any
            # more (it is not trustworthy; see geo tests below), but it is still part of
            # the real payload shape, so the stub keeps sending it.
            "ip_city": city,
            "device_info": {"network_operator_mobile": "Verizon "},
        },
        "_exit_ip": exit_ip,
    }


async def test_repeated_city_is_resolved_once_per_pass(session) -> None:
    """The second lookup of a (city, state) pair must not go back to the database.

    Two statements per connection is invisible on a three-phone test account and is ~4000
    round-trips per minute on a launch-sized pool — to resolve nine distinct cities.
    """
    cache: dict[tuple[str, str], int | None] = {}

    first = await _resolve_location(session, "Boston", "MA", cache)
    assert first is not None
    assert cache[("Boston", "MA")] == first

    # Poison the entry: it can only come back if the database path was skipped entirely.
    cache[("Boston", "MA")] = -1
    assert await _resolve_location(session, "Boston", "MA", cache) == -1

    # A different state for the same city name is a different location, not a cache hit.
    other = await _resolve_location(session, "Boston", "GA", cache)
    assert other is not None
    assert other != -1


async def test_resolve_location_without_a_cache_still_works(session) -> None:
    """The cache is an optimisation, not a requirement — callers may omit it."""
    assert await _resolve_location(session, "Boston", "MA") is not None
    assert await _resolve_location(session, None, None) is None
    assert await _resolve_location(session, "Boston", None) is None  # state is required too


def _fake_geoip(mapping: dict[str, tuple[str, str]]) -> Any:
    """A resolve_city_state stand-in — tests must never touch the real .mmdb file."""
    return lambda ip: mapping.get(ip) if ip else None


async def test_sync_pool_upserts_every_connection_and_reuses_one_location(
    session, monkeypatch
) -> None:
    """End-to-end over the stub: every phone lands, one shared exit IP makes one Location."""
    monkeypatch.setattr(
        "app.services.provisioning.sync.resolve_city_state",
        _fake_geoip({"1.1.1.1": ("Boston", "MA"), "2.2.2.2": ("Denver", "CO")}),
    )
    client = _StubIproxy([
        _conn("aaa", "Boston", exit_ip="1.1.1.1"),
        _conn("bbb", "Boston", exit_ip="1.1.1.1"),
        _conn("ccc", "Denver", exit_ip="2.2.2.2"),
    ])

    result = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    assert result["seen"] == 3
    assert result["written"] == 3  # first sighting: all three are inserts
    assert result["online"] == 3
    assert result["geo_lookups"] == 3  # one exit-IP lookup per phone, first sighting
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


async def test_geo_city_comes_from_the_real_exit_ip_not_iproxys_claimed_city(
    session, monkeypatch
) -> None:
    """iproxy's app_data.ip_city is not trusted for location any more — measured live,
    it names the wrong city for a phone's real exit IP (called a Milwaukee-area Verizon
    phone "Boston"). The GeoIP lookup on the actual exit IP must win instead.
    """
    monkeypatch.setattr(
        "app.services.provisioning.sync.resolve_city_state",
        _fake_geoip({"174.224.240.8": ("New Berlin", "WI")}),
    )
    # iproxy insists this phone is in Boston; its real modem IP is in Wisconsin.
    client = _StubIproxy([_conn("aaa", "Boston", exit_ip="174.224.240.8")])

    await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    row = (
        await session.execute(
            select(Connection.geo_city, Connection.geo_state, Connection.geo_ip, Connection.location_id)
            .where(Connection.iproxy_connection_id == "aaa")
        )
    ).one()
    assert (row.geo_city, row.geo_state, row.geo_ip) == ("New Berlin", "WI", "174.224.240.8")

    location = await session.get(Location, row.location_id)
    assert (location.city, location.state_code) == ("New Berlin", "WI")


async def test_city_outside_the_old_seventeen_city_map_is_no_longer_lost(
    session, monkeypatch
) -> None:
    """Saint Francis, WI had no entry in the old hand-rolled _CITY_STATE dict and its
    connection landed with location_id=NULL forever. That dict is gone; any city GeoIP
    resolves must produce a sellable, findable Location — not just the original 17.
    """
    monkeypatch.setattr(
        "app.services.provisioning.sync.resolve_city_state",
        _fake_geoip({"9.9.9.9": ("Saint Francis", "WI")}),
    )
    client = _StubIproxy([_conn("zzz", "Saint Francis", exit_ip="9.9.9.9")])

    result = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()

    assert result["written"] == 1
    location_id = await session.scalar(
        select(Connection.location_id).where(Connection.iproxy_connection_id == "zzz")
    )
    assert location_id is not None
    location = await session.get(Location, location_id)
    assert (location.city, location.state_code) == ("Saint Francis", "WI")


async def test_geo_lookup_budget_caps_a_single_pass(session, monkeypatch) -> None:
    """Every phone needing a lookup is one iproxy HTTP call — a launch-sized pool must not
    turn its first pass into ~2000 of them. The rest catch up on the next pass instead.
    """
    from app.services.provisioning.sync import _MAX_GEO_LOOKUPS_PER_PASS

    monkeypatch.setattr(
        "app.services.provisioning.sync.resolve_city_state",
        _fake_geoip({}),  # no matches needed — only call counts are asserted
    )
    extra = 5
    conns = [
        _conn(f"c{i}", "Nowhere", exit_ip=f"10.0.0.{i}")
        for i in range(_MAX_GEO_LOOKUPS_PER_PASS + extra)
    ]
    client = _StubIproxy(conns)

    first = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()
    assert first["geo_lookups"] == _MAX_GEO_LOOKUPS_PER_PASS
    assert client.get_connection_calls == _MAX_GEO_LOOKUPS_PER_PASS

    second = await sync_pool(session, client=client)  # type: ignore[arg-type]
    await session.flush()
    assert second["geo_lookups"] == extra  # the leftover phones catch up next pass


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
