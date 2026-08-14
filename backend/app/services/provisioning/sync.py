"""iproxy pool sync — mirror the account's connections into our sellable pool.

Called from the worker cron (every minute) and the admin "Sync now" button; both go
through sync_pool(). Each iproxy connection is enriched with carrier, city and online
status so the allocator can pick it.

The pass writes only what moved. The pool is one row per phone and the client expects
~2000 at launch, so a pass that touched every row was ~2000 statements a minute to record
that nothing had happened. Now it is one read, one statement per phone that actually
changed, and two batched stamps for the quiet rest — three statements on a calm minute.

`location_id` is refreshed on EVERY pass, and that is the point of this module rather
than an incidental detail. It used to be written once, on a phone's first sighting, and
never again. But a phone's exit IP changes on every rotation and its city changes with
it, so that first answer went stale within hours and the row kept claiming a city the
phone had left. Measured on the client's live account: three phones all labelled Boston
while their addresses had long since resolved to Wisconsin. The label was not wrong when
it was written — it was just never rewritten.

Because it is derived, `location_id` can no longer be an operator's to keep: a manual
pick in /admin is overwritten by the next pass. carrier / is_sellable / tier remain
operator-owned and are still never touched after the first sighting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.models import Connection, Location
from app.services.provisioning.iproxy import IproxyClient

# iproxy reports the exit-IP city but not its state, so the state is filled in here for the
# cities we actually sell. This is a lookup table, NOT a filter — that distinction is the
# bug this file used to have. A city missing from it still gets a Location (with an empty
# state), because the previous version dropped such a city on the floor and left the phone
# with no location at all: "Saint Francis" and "Sun Prairie" both vanished that way, and
# nobody filtering by city could find those phones.
_CITY_STATE: dict[str, str] = {
    "seattle": "WA", "los angeles": "CA", "las vegas": "NV", "portland": "OR",
    "denver": "CO", "phoenix": "AZ", "dallas": "TX", "miami": "FL", "chicago": "IL",
    "boston": "MA", "new york": "NY", "san francisco": "CA", "atlanta": "GA",
    "houston": "TX", "austin": "TX", "washington": "DC", "philadelphia": "PA",
    "milwaukee": "WI", "madison": "WI", "saint francis": "WI", "sun prairie": "WI",
    "pleasant prairie": "WI", "new berlin": "WI", "kenosha": "WI",
}


def _normalize_carrier(raw: str | None) -> str | None:
    """iproxy 'network_operator_mobile' (e.g. 'Verizon ') → our carrier enum, or None."""
    if not raw:
        return None
    s = raw.strip().lower()
    if "verizon" in s:
        return "Verizon"
    if "t-mobile" in s or "tmobile" in s:
        return "T-Mobile"
    if "at&t" in s or "att" in s:
        return "AT&T"
    return None


def _online_status(raw: dict[str, Any]) -> str:
    val = raw.get("online_status") or raw.get("status")
    return val if val in ("online", "offline") else "unknown"


async def _resolve_location(
    session: AsyncSession,
    city: str | None,
    cache: dict[str, int | None] | None = None,
) -> int | None:
    """City name → location id, upserting the row the first time a city is seen.

    An unknown city is stored with an empty state rather than discarded — see _CITY_STATE.
    Empty string, not NULL: the table's unique index is (city, state_code), and in Postgres
    two NULLs never compare equal, so NULL states would let the same city be inserted over
    and over.

    ``cache`` memoises the answer for one sync pass. Without it this costs two statements
    per connection, and the pool is one row per phone: a launch-sized pool of ~2000 turns
    every pass into ~4000 round-trips to resolve a handful of distinct cities. The cache is
    per-pass on purpose — a long-lived one would go stale when an operator edits a city.
    """
    if not city:
        return None
    name = city.strip()
    if not name:
        return None
    if cache is not None and name in cache:
        return cache[name]
    state = _CITY_STATE.get(name.lower(), "")
    await session.execute(
        insert(Location)
        .values(city=name, state_code=state, is_active=True)
        .on_conflict_do_nothing(index_elements=["city", "state_code"])
    )
    loc_id = await session.scalar(
        select(Location.id).where(Location.city == name, Location.state_code == state)
    )
    resolved = int(loc_id) if loc_id is not None else None
    if cache is not None:
        cache[name] = resolved
    return resolved


async def sync_pool(session: AsyncSession, client: IproxyClient | None = None) -> dict[str, Any]:
    """Mirror the iproxy account into `connections`, writing only what changed.

    Returns ``{seen, written, online}`` — phones the account reported, rows actually
    written, and how many were up. ``written`` is the one worth watching: on a calm pass
    it is low, and a pass that keeps rewriting the same rows means something upstream is
    flapping.
    """
    client = client or IproxyClient()
    conns = await client.list_connections()
    statuses = {
        str(s.get("id") or s.get("connection_id") or ""): s
        for s in await client.connection_status()
    }
    now = datetime.now(UTC)
    # One read of what we already hold, so the loop can tell a changed phone from a phone
    # that simply reported the same thing again. Without it every pass wrote every row.
    # location_id is part of that comparison now that it is refreshed rather than frozen —
    # without it here, a phone whose city changed would look unchanged and never be written.
    current = {
        row.iproxy_connection_id: row
        for row in (
            await session.execute(
                select(
                    Connection.iproxy_connection_id,
                    Connection.name,
                    Connection.online_status,
                    Connection.location_id,
                )
            )
        ).all()
    }

    seen = written = online = 0
    # Rows where nothing moved still need their freshness stamps, but not a statement each:
    # they are collected here and stamped in one UPDATE per group at the end.
    stamp_online: list[str] = []
    stamp_offline: list[str] = []
    location_cache: dict[str, int | None] = {}

    for c in conns:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        seen += 1
        basic = c.get("basic_info") or {}
        app_data = c.get("app_data") or {}
        device = app_data.get("device_info") or {}
        name = basic.get("name") or c.get("name") or ""
        status = _online_status(statuses.get(cid, {}))
        if status == "online":
            online += 1

        known = current.get(cid)
        # Resolved for every phone on every pass, not just new ones — this is what keeps a
        # rotated phone's city current. It costs no HTTP call: the city rides along in the
        # list response we already have, and the per-pass cache collapses a whole pool down
        # to one pair of statements per distinct city.
        loc_id = await _resolve_location(session, app_data.get("ip_city"), location_cache)

        unchanged = (
            known is not None
            and known.name == name
            and known.online_status == status
            and known.location_id == loc_id
        )
        if unchanged:
            (stamp_online if status == "online" else stamp_offline).append(cid)
            continue

        values: dict[str, Any] = {
            "iproxy_connection_id": cid,
            "name": name,
            "carrier": _normalize_carrier(device.get("network_operator_mobile")),
            "location_id": loc_id,
            "is_sellable": True,  # auto-list on first sight; admin can toggle later
            "tier": "standard",
            "online_status": status,
            "synced_at": now,
        }
        if status == "online":
            values["last_online_at"] = now

        stmt = insert(Connection).values(**values)
        # Refresh what iproxy owns; preserve the operator's edits to carrier / is_sellable /
        # tier. location_id is in here because it is derived from the phone's current city —
        # leaving it out is exactly what let a stale city survive every later pass.
        set_: dict[str, Any] = {
            "name": stmt.excluded.name,
            "online_status": stmt.excluded.online_status,
            "synced_at": stmt.excluded.synced_at,
            "location_id": stmt.excluded.location_id,
        }
        if status == "online":
            set_["last_online_at"] = stmt.excluded.last_online_at
        stmt = stmt.on_conflict_do_update(index_elements=["iproxy_connection_id"], set_=set_)
        await session.execute(stmt)
        written += 1

    # Two statements for the whole quiet majority. `last_online_at` still moves for phones
    # that are up, so "when did we last see it alive" keeps its meaning for the ones that
    # later go dark.
    if stamp_offline:
        await session.execute(
            update(Connection)
            .where(Connection.iproxy_connection_id.in_(stamp_offline))
            .values(synced_at=now)
        )
    if stamp_online:
        await session.execute(
            update(Connection)
            .where(Connection.iproxy_connection_id.in_(stamp_online))
            .values(synced_at=now, last_online_at=now)
        )

    log.info("iproxy.sync", seen=seen, written=written, online=online)
    return {"seen": seen, "written": written, "online": online}
