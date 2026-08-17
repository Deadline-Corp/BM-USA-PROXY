"""Atomic pool allocation — INVARIANT #2 (one phone, one sale).

FOR UPDATE ... SKIP LOCKED picks a free, online, sellable connection matching the
requested city/carrier; the partial unique index on accesses is the backstop.

"Free" also means nobody is holding it outside our tables: a proxy-access created straight
in the iproxy console occupies the phone without any row here to say so, and selling that
phone hands two customers the same device. See sync.sync_external_holds.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_ALLOC_SQL = text(
    """
    SELECT c.id, c.iproxy_connection_id
    FROM connections c
    WHERE c.is_sellable AND c.online_status = 'online'
      AND c.external_access_count = 0
      AND (CAST(:location_id AS bigint) IS NULL OR c.location_id = CAST(:location_id AS bigint))
      AND (CAST(:carrier AS text) IS NULL OR c.carrier = CAST(:carrier AS text))
      AND (CAST(:exclude_id AS bigint) IS NULL OR c.id <> CAST(:exclude_id AS bigint))
      AND NOT EXISTS (
        SELECT 1 FROM accesses a
        WHERE a.connection_id = c.id
          AND a.status IN ('provisioning','active','expiring')
      )
    ORDER BY (c.tier = 'stable') DESC, c.last_online_at DESC NULLS LAST
    FOR UPDATE OF c SKIP LOCKED
    LIMIT 1
    """
)


async def allocate(
    session: AsyncSession,
    *,
    location_id: int | None = None,
    carrier: str | None = None,
    exclude_id: int | None = None,
) -> tuple[int, str] | None:
    """Return (connection_id, iproxy_connection_id) locked for this txn, or None."""
    row = (
        await session.execute(
            _ALLOC_SQL,
            {
                "location_id": location_id,
                "carrier": carrier,
                "exclude_id": exclude_id,
            },
        )
    ).first()
    return (row[0], row[1]) if row else None


_AVAILABILITY_SQL = text(
    """
    SELECT l.id, l.city, l.state_code, c.carrier, count(*) AS free
    FROM connections c
    JOIN locations l ON l.id = c.location_id
    WHERE c.is_sellable AND c.online_status = 'online'
      AND c.external_access_count = 0
      AND NOT EXISTS (
        SELECT 1 FROM accesses a
        WHERE a.connection_id = c.id
          AND a.status IN ('provisioning','active','expiring')
      )
    GROUP BY l.id, l.city, l.state_code, c.carrier
    ORDER BY l.city
    """
)


async def available_locations(session: AsyncSession) -> list[dict[str, Any]]:
    """Cities that can be sold from right now, each with the carriers it can be sold on.

    Deliberately the allocator's own definition of free — same WHERE clause as `allocate`
    — so a picker built from this cannot offer a combination the allocator would then
    refuse. Anything with nothing free is absent rather than listed as zero: a choice that
    only leads to "no free connection" is not a choice.

    A connection with no carrier recorded still counts toward the city (it can be handed
    out when no carrier is asked for) but names no carrier of its own.
    """
    rows = (await session.execute(_AVAILABILITY_SQL)).all()
    by_location: dict[int, dict[str, Any]] = {}
    for loc_id, city, state, carrier, free in rows:
        entry = by_location.setdefault(
            int(loc_id),
            {"id": str(loc_id), "city": city, "state_code": state, "free": 0, "carriers": []},
        )
        entry["free"] += int(free)
        if carrier:
            entry["carriers"].append({"carrier": carrier, "free": int(free)})
    return list(by_location.values())


async def count_available(
    session: AsyncSession, *, location_id: int | None = None, carrier: str | None = None
) -> int:
    row = await session.execute(
        text(
            """
            SELECT count(*) FROM connections c
            WHERE c.is_sellable AND c.online_status = 'online'
              AND c.external_access_count = 0
              AND (CAST(:location_id AS bigint) IS NULL OR c.location_id = CAST(:location_id AS bigint))
              AND (CAST(:carrier AS text) IS NULL OR c.carrier = CAST(:carrier AS text))
              AND NOT EXISTS (
                SELECT 1 FROM accesses a
                WHERE a.connection_id = c.id
                  AND a.status IN ('provisioning','active','expiring'))
            """
        ),
        {"location_id": location_id, "carrier": carrier},
    )
    return int(row.scalar_one())
