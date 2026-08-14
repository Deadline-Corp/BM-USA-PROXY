"""iproxy pool sync — mirror the account's connections into our sellable pool.

Called from the worker cron (every minute) and the admin "Sync now" button; both go
through sync_pool(). Each iproxy connection is enriched with carrier, exit-city
location, and online status so the allocator can pick it. carrier / location_id /
is_sellable / tier are set when a connection is first seen; later syncs refresh only
volatile fields (name, online status), so an operator's manual edits in /admin survive.

The pass writes only what moved. The pool is one row per phone and the client expects
~2000 at launch, so a pass that touched every row was ~2000 statements a minute to record
that nothing had happened. Now it is one read, one statement per phone that actually
changed, and two batched stamps for the quiet rest — three statements on a calm minute.

Geo data (`geo_city` / `geo_state` / `geo_ip`) is kept separate from `location_id` on
purpose. `location_id` is what a connection is *sold as* — an operator's edit, once set,
that this pass has never overwritten. `geo_*` is the honest, automatic half: what a
local GeoIP database says about the phone's *actual* exit IP right now. The two are
allowed to disagree, because iproxy's own `app_data.ip_city` field is not trustworthy —
measured live against the client's account, iproxy named a Milwaukee-area Verizon phone
"Boston" — so it is no longer used to pick a location at all, not even on first sight.

Resolving geo means one rate-limited iproxy HTTP call per phone (IproxyProvisioner.
current_ip → get_connection), so it is budgeted rather than done for the whole pool every
pass: see _MAX_GEO_LOOKUPS_PER_PASS and _GEO_TTL below.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.models import Connection, Location
from app.services.provisioning.geoip import resolve_city_state
from app.services.provisioning.iproxy import IproxyClient, IproxyProvisioner

# How many connections get a real exit-IP lookup (one rate-limited iproxy HTTP call each)
# in a single pass. Every phone needs this at least once, and the whole existing pool has
# never had one the first time this runs — uncapped, that first pass would fire ~2000
# sequential calls inside one DB transaction. Capped, a launch-sized pool backfills over a
# handful of the once-a-minute cron passes instead of turning one of them into a
# multi-minute outlier that holds the transaction open the whole time.
_MAX_GEO_LOOKUPS_PER_PASS = 100
# Re-check a resolved phone's exit IP occasionally — a carrier can reassign it — without
# paying the lookup cost every pass. A miss (lookup failed, or the database had no match)
# is stamped the same as a hit, so a permanently unresolvable phone does not retry forever
# and starve the rest of the pool's budget.
_GEO_TTL = timedelta(days=7)


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
    state: str | None,
    cache: dict[tuple[str, str], int | None] | None = None,
) -> int | None:
    """(city, state) → location id, upserting the row the first time this pair is seen.

    ``cache`` memoises the answer for one sync pass. Without it this costs two statements
    per connection, and the pool is one row per phone: a launch-sized pool of ~2000 turns
    every pass into ~4000 round-trips to resolve nine distinct cities. The cache is
    per-pass on purpose — a long-lived one would go stale when an operator edits a city.
    """
    if not city or not state:
        return None
    key = (city, state)
    if cache is not None and key in cache:
        return cache[key]
    await session.execute(
        insert(Location)
        .values(city=city, state_code=state, is_active=True)
        .on_conflict_do_nothing(index_elements=["city", "state_code"])
    )
    loc_id = await session.scalar(
        select(Location.id).where(Location.city == city, Location.state_code == state)
    )
    resolved = int(loc_id) if loc_id is not None else None
    if cache is not None:
        cache[key] = resolved
    return resolved


async def sync_pool(session: AsyncSession, client: IproxyClient | None = None) -> dict[str, Any]:
    """Mirror the iproxy account into `connections`, writing only what changed.

    Returns ``{seen, written, online, geo_lookups}`` — phones the account reported, rows
    actually written, how many were up, and how many paid for a real exit-IP lookup this
    pass. ``written`` is the one worth watching day to day: on a calm pass it is low, and
    a pass that keeps rewriting the same rows means something upstream is flapping.
    ``geo_lookups`` will sit near _MAX_GEO_LOOKUPS_PER_PASS while the pool backfills after
    this shipped, then drop to whatever a week's worth of TTL refresh + new phones needs.
    """
    client = client or IproxyClient()
    provisioner = IproxyProvisioner(client)
    conns = await client.list_connections()
    statuses = {
        str(s.get("id") or s.get("connection_id") or ""): s
        for s in await client.connection_status()
    }
    now = datetime.now(UTC)
    # One read of what we already hold, so the loop can tell a changed phone from a phone
    # that simply reported the same thing again. Without it every pass wrote every row.
    # geo_* rides along too — not to preserve an operator's edit (there is none to
    # preserve, this is never operator-set) but so a row we are NOT re-resolving this pass
    # can still supply its already-stored geo_* values back into the upsert unchanged.
    current = {
        row.iproxy_connection_id: row
        for row in (
            await session.execute(
                select(
                    Connection.iproxy_connection_id,
                    Connection.name,
                    Connection.online_status,
                    Connection.geo_city,
                    Connection.geo_state,
                    Connection.geo_ip,
                    Connection.geo_resolved_at,
                )
            )
        ).all()
    }

    seen = written = online = 0
    # Rows where nothing moved still need their freshness stamps, but not a statement each:
    # they are collected here and stamped in one UPDATE per group at the end.
    stamp_online: list[str] = []
    stamp_offline: list[str] = []
    location_cache: dict[tuple[str, str], int | None] = {}
    geo_lookups = 0

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

        # A real exit-IP lookup is one rate-limited iproxy HTTP call, so it is budgeted: a
        # brand new phone always gets one, an already-known one only if it has never had
        # one or _GEO_TTL has passed — and even then only up to _MAX_GEO_LOOKUPS_PER_PASS.
        due_for_geo = (
            known is None
            or known.geo_resolved_at is None
            or now - known.geo_resolved_at > _GEO_TTL
        )
        geo_city = known.geo_city if known is not None else None
        geo_state = known.geo_state if known is not None else None
        geo_ip = known.geo_ip if known is not None else None
        geo_resolved_at = known.geo_resolved_at if known is not None else None
        if due_for_geo and geo_lookups < _MAX_GEO_LOOKUPS_PER_PASS:
            geo_lookups += 1
            geo_ip = await provisioner.current_ip(iproxy_connection_id=cid)
            resolved = resolve_city_state(geo_ip)
            geo_city, geo_state = resolved if resolved is not None else (None, None)
            geo_resolved_at = now

        unchanged = (
            known is not None
            and known.name == name
            and known.online_status == status
            and geo_resolved_at == known.geo_resolved_at
        )
        if unchanged:
            (stamp_online if status == "online" else stamp_offline).append(cid)
            continue

        # Only a first sighting needs a sold-as location: location_id is deliberately
        # absent from the conflict update below, so resolving it for a row we already
        # hold would be work thrown away. It comes from our own geo lookup above, never
        # from iproxy's own app_data.ip_city — that field is what this change stops
        # trusting, so it is not read anywhere in this function any more.
        loc_id = (
            await _resolve_location(session, geo_city, geo_state, location_cache)
            if known is None
            else None
        )
        values: dict[str, Any] = {
            "iproxy_connection_id": cid,
            "name": name,
            "carrier": _normalize_carrier(device.get("network_operator_mobile")),
            "location_id": loc_id,
            "is_sellable": True,  # auto-list on first sight; admin can toggle later
            "tier": "standard",
            "online_status": status,
            "synced_at": now,
            "geo_city": geo_city,
            "geo_state": geo_state,
            "geo_ip": geo_ip,
            "geo_resolved_at": geo_resolved_at,
        }
        if status == "online":
            values["last_online_at"] = now

        stmt = insert(Connection).values(**values)
        # Refresh volatile / auto-managed fields on conflict — preserve operator edits to
        # carrier / location_id / is_sellable / tier. geo_* is never operator-set, so it
        # refreshes here exactly like name / online_status / synced_at.
        set_: dict[str, Any] = {
            "name": stmt.excluded.name,
            "online_status": stmt.excluded.online_status,
            "synced_at": stmt.excluded.synced_at,
            "geo_city": stmt.excluded.geo_city,
            "geo_state": stmt.excluded.geo_state,
            "geo_ip": stmt.excluded.geo_ip,
            "geo_resolved_at": stmt.excluded.geo_resolved_at,
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

    log.info("iproxy.sync", seen=seen, written=written, online=online, geo_lookups=geo_lookups)
    return {"seen": seen, "written": written, "online": online, "geo_lookups": geo_lookups}
