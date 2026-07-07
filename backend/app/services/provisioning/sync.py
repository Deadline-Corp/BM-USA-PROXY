"""iproxy pool sync — mirror the account's connections into our sellable pool.

Called from the worker cron (~every 5 min) and the admin "Sync now" button; both go
through sync_pool(). Each iproxy connection is enriched with carrier, exit-city
location, and online status so the allocator can pick it. carrier / location_id /
is_sellable / tier are set when a connection is first seen; later syncs refresh only
volatile fields (name, online status), so an operator's manual edits in /admin survive.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.models import Connection, Location
from app.services.provisioning.iproxy import IproxyClient

# iproxy reports the exit-IP city but not the state. Map the cities we sell so a
# connection lands on a selectable Location. Unmapped city → location left NULL (the
# connection is still sellable and allocatable when the buyer doesn't filter by city).
_CITY_STATE: dict[str, str] = {
    "seattle": "WA", "los angeles": "CA", "las vegas": "NV", "portland": "OR",
    "denver": "CO", "phoenix": "AZ", "dallas": "TX", "miami": "FL", "chicago": "IL",
    "boston": "MA", "new york": "NY", "san francisco": "CA", "atlanta": "GA",
    "houston": "TX", "austin": "TX", "washington": "DC", "philadelphia": "PA",
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


async def _resolve_location(session: AsyncSession, city: str | None) -> int | None:
    if not city:
        return None
    name = city.strip()
    state = _CITY_STATE.get(name.lower())
    if not state:
        return None
    await session.execute(
        insert(Location)
        .values(city=name, state_code=state, is_active=True)
        .on_conflict_do_nothing(index_elements=["city", "state_code"])
    )
    loc_id = await session.scalar(
        select(Location.id).where(Location.city == name, Location.state_code == state)
    )
    return int(loc_id) if loc_id is not None else None


async def sync_pool(session: AsyncSession, client: IproxyClient | None = None) -> dict[str, Any]:
    """Upsert every iproxy connection into `connections`. Returns {upserted, online}."""
    client = client or IproxyClient()
    conns = await client.list_connections()
    statuses = {
        str(s.get("id") or s.get("connection_id") or ""): s
        for s in await client.connection_status()
    }
    now = datetime.now(UTC)
    upserted = online = 0
    for c in conns:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        basic = c.get("basic_info") or {}
        app_data = c.get("app_data") or {}
        device = app_data.get("device_info") or {}
        name = basic.get("name") or c.get("name") or ""
        carrier = _normalize_carrier(device.get("network_operator_mobile"))
        loc_id = await _resolve_location(session, app_data.get("ip_city"))
        status = _online_status(statuses.get(cid, {}))
        if status == "online":
            online += 1

        values: dict[str, Any] = {
            "iproxy_connection_id": cid,
            "name": name,
            "carrier": carrier,
            "location_id": loc_id,
            "is_sellable": True,  # auto-list on first sight; admin can toggle later
            "tier": "standard",
            "online_status": status,
            "synced_at": now,
        }
        if status == "online":
            values["last_online_at"] = now

        stmt = insert(Connection).values(**values)
        # Refresh only volatile fields on conflict — preserve operator edits to
        # carrier / location_id / is_sellable / tier.
        set_: dict[str, Any] = {
            "name": stmt.excluded.name,
            "online_status": stmt.excluded.online_status,
            "synced_at": stmt.excluded.synced_at,
        }
        if status == "online":
            set_["last_online_at"] = stmt.excluded.last_online_at
        stmt = stmt.on_conflict_do_update(index_elements=["iproxy_connection_id"], set_=set_)
        await session.execute(stmt)
        upserted += 1

    log.info("iproxy.sync", upserted=upserted, online=online)
    return {"upserted": upserted, "online": online}
