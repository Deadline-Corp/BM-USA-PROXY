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


# What "free" means, in one place: online, not held by the iproxy console, and not already
# rented. Kept as a fragment so the city list and the unplaced count cannot drift apart,
# and so both keep matching `allocate`'s own WHERE clause.
_FREE_PREDICATE = """
        c.online_status = 'online'
        AND c.external_access_count = 0
        AND NOT EXISTS (
          SELECT 1 FROM accesses a
          WHERE a.connection_id = c.id
            AND a.status IN ('provisioning','active','expiring')
        )
"""

# Rows are every sellable phone in an ACTIVE city, counted twice: how many exist there at
# all, and how many are free this second. Two counts rather than one because "sold out" and
# "not somewhere we sell" are different answers — a city whose phones are all rented is
# still a city we sell, and dropping it the moment the last phone goes would make the menu
# flicker with demand. A city switched off in the console is gone regardless of stock.
_AVAILABILITY_SQL = text(
    # The S608 suppression below is safe: the only interpolation is _FREE_PREDICATE, a
    # constant defined directly above. No caller, request or column value reaches here.
    f"""
    SELECT l.id, l.city, l.state_code, c.carrier,
           count(*) FILTER (WHERE {_FREE_PREDICATE}) AS free,
           count(*) AS stocked
    FROM connections c
    JOIN locations l ON l.id = c.location_id
    WHERE c.is_sellable AND l.is_active
    GROUP BY l.id, l.city, l.state_code, c.carrier
    ORDER BY l.city
    """  # noqa: S608
)

# Phones we can sell but cannot place. A phone's city comes from the state written into its
# name plus the operator's state→city mapping; a name that parses to nothing leaves the
# phone with no location. It still sells — it just cannot be found by filtering for a city,
# so it belongs to "Any city" and to nothing else. Counting only the listed cities hid it
# from the one option that is always on the screen.
_UNPLACED_SQL = text(
    f"""
    SELECT c.carrier, count(*) AS free
    FROM connections c
    WHERE c.is_sellable AND c.location_id IS NULL
      AND {_FREE_PREDICATE}
    GROUP BY c.carrier
    """  # noqa: S608
)


async def available_locations(session: AsyncSession) -> list[dict[str, Any]]:
    """Cities we sell from, each with the carriers it holds and how many are free now.

    A city appears when it is switched on in the console AND holds at least one sellable
    phone — whether or not that phone is free this second, which is why ``free`` can be 0.
    Sold out and not-stocked are different answers and the picker shows them differently:
    dropping a city the moment its last phone was taken made the menu flicker with demand,
    while a city that has never held a phone must never be offered at all.

    ``free`` is the allocator's own definition — the same predicate `allocate` uses — so a
    non-zero count here cannot become "no free connection" at checkout.

    A connection with no carrier recorded still counts toward the city (it can be handed
    out when no carrier is asked for) but names no carrier of its own. A connection with no
    *city* is not here at all — see `unplaced_free_counts`.
    """
    rows = (await session.execute(_AVAILABILITY_SQL)).all()
    by_location: dict[int, dict[str, Any]] = {}
    for loc_id, city, state, carrier, free, _stocked in rows:
        entry = by_location.setdefault(
            int(loc_id),
            {"id": str(loc_id), "city": city, "state_code": state, "free": 0, "carriers": []},
        )
        entry["free"] += int(free)
        if carrier:
            entry["carriers"].append({"carrier": carrier, "free": int(free)})
    return list(by_location.values())


async def unplaced_free_counts(session: AsyncSession) -> dict[str, int]:
    """Free phones that belong to no city, by carrier, plus an ``any`` total.

    These are sellable and allocatable — they simply cannot be offered under a city name,
    so they belong to the "Any city" option alone. Returned separately from
    `available_locations` rather than folded into it, because there is no city to name them
    under and inventing one would put a place on the menu that does not exist.
    """
    rows = (await session.execute(_UNPLACED_SQL)).all()
    counts: dict[str, int] = {}
    total = 0
    for carrier, free in rows:
        total += int(free)
        if carrier:
            counts[carrier] = counts.get(carrier, 0) + int(free)
    counts["any"] = total
    return counts


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
