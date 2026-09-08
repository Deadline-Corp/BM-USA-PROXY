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


# ── a phone the account no longer lists ───────────────────────────────────
#
# Both reported by the client on 2026-09-08: two connections shown as "Held in iproxy"
# that nobody was holding.


async def test_a_phone_deleted_in_iproxy_stops_being_sold(session) -> None:
    """It kept its last row forever — sellable, online, and frozen at whatever hold count
    it happened to carry. `tm1399_NY` sat that way from 2026-09-03 until the client asked
    why a phone they had removed was still shown as busy."""
    stub = _StubIproxy([_conn("keep", "Miami"), _conn("gone", "Chicago")])
    await sync_pool(session, stub)
    await session.flush()

    row = await session.scalar(select(Connection).where(Connection.iproxy_connection_id == "gone"))
    assert row is not None and row.online_status == "online"
    row.external_access_count = 2  # what the last successful hold check had left behind
    row.is_sellable = True
    await session.flush()

    # the client deletes it in the console
    stub.connections = [_conn("keep", "Miami")]
    report = await sync_pool(session, stub)
    await session.flush()
    await session.refresh(row)

    assert report["gone"] == 1
    assert row.online_status == "offline", "the allocator only takes phones that are online"
    assert row.external_access_count == 0, "there is no phone left for anyone to be holding"
    assert row.health_note and "iproxy" in row.health_note.lower()
    # Not deleted, and the operator's own flag is left alone — accesses and ledger rows
    # point at this row, and `is_sellable` is theirs to set.
    assert row.is_sellable is True

    kept = await session.scalar(select(Connection).where(Connection.iproxy_connection_id == "keep"))
    assert kept is not None and kept.online_status == "online"


async def test_an_empty_listing_cannot_take_the_whole_pool_offline(session) -> None:
    """One bad answer from the API must not be able to close the shop.

    A phone that has genuinely gone is still missing on the next pass a minute later, so
    there is nothing to lose by declining to act on nothing.
    """
    stub = _StubIproxy([_conn("a", "Miami"), _conn("b", "Chicago")])
    await sync_pool(session, stub)
    await session.flush()

    stub.connections = []
    report = await sync_pool(session, stub)
    await session.flush()

    assert report["gone"] == 0
    still_online = await session.scalar(
        select(func.count()).select_from(Connection).where(Connection.online_status == "online")
    )
    assert still_online == 2


# ── a proxy iproxy created for itself is not a hold ───────────────────────


def test_iproxys_own_automatic_proxy_is_not_somebody_holding_the_phone() -> None:
    """`tm1406_NY` carried one of these and could not be sold.

    Matched on the label because the payload gives nothing else to go on — no owner, no
    origin, and an id no different in shape from ours. Ours are stamped "bm-usa-proxy";
    the client's own are free text, like the "test1" on `att263_WA_S`, which is a real
    hold and has to keep counting.
    """
    from app.services.provisioning.sync import _made_by_iproxy_itself

    assert _made_by_iproxy_itself({"description": "this proxy was created automatically"})
    assert _made_by_iproxy_itself({"description": "This Proxy Was Created Automatically"})
    assert not _made_by_iproxy_itself({"description": "bm-usa-proxy"})
    assert not _made_by_iproxy_itself({"description": "test1"})
    assert not _made_by_iproxy_itself({"description": None})
    assert not _made_by_iproxy_itself({})


class _HoldsStub:
    """Enough of IproxyClient for `sync_external_holds` — one phone, whatever accesses."""

    def __init__(self, accesses: list[dict[str, Any]]) -> None:
        self.accesses = accesses

    async def list_proxy_access(self, _connection_id: str) -> list[dict[str, Any]]:
        return self.accesses


async def test_only_a_real_outsider_marks_the_phone_held(session) -> None:
    """The count is what makes a phone unsellable, so what goes into it is the whole point.

    Three kinds of access turn up on a live phone, and only one of them means somebody
    else is using it.
    """
    from app.services.provisioning.sync import sync_external_holds

    await sync_pool(session, _StubIproxy([_conn("p1", "Miami")]))
    await session.flush()
    conn = await session.scalar(select(Connection).where(Connection.iproxy_connection_id == "p1"))
    assert conn is not None

    async def holds(accesses: list[dict[str, Any]]) -> int:
        await sync_external_holds(session, _HoldsStub(accesses))  # type: ignore[arg-type]
        await session.flush()
        await session.refresh(conn)
        return conn.external_access_count

    # iproxy's own, on a phone nobody has bought — this is what `tm1406_NY` carried.
    assert await holds([{"id": "auto1", "description": "this proxy was created automatically"}]) == 0
    # The client made one by hand in the console. `att263_WA_S` has exactly this.
    assert await holds([{"id": "byhand", "description": "test1"}]) == 1
    # Both at once: still one outsider, not two.
    assert (
        await holds(
            [
                {"id": "auto1", "description": "this proxy was created automatically"},
                {"id": "byhand", "description": "test1"},
            ]
        )
        == 1
    )
    assert await holds([]) == 0
