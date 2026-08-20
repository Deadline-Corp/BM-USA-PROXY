"""Atomic pool allocation — INVARIANT #2 (one phone, one sale).

FOR UPDATE ... SKIP LOCKED picks a free, online, sellable connection matching the
requested city/carrier; the partial unique index on accesses is the backstop.

"Free" also means nobody is holding it outside our tables: a proxy-access created straight
in the iproxy console occupies the phone without any row here to say so, and selling that
phone hands two customers the same device. See sync.sync_external_holds.

It also means nobody is holding it *for* an unpaid invoice. A quote is a promise about
specific stock, and between raising the invoice and the deposit confirming there is a
window — minutes on a good day — in which the phones behind that promise could be sold to
somebody else. `reserve` takes them off the shelf for the life of the invoice.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# A reservation an order made for itself is not an obstacle to that same order: the whole
# point of holding stock is to hand it over when the money lands. Everyone else sees the
# phone as taken. A lapsed hold is nobody's — see `reserve` on why the clock exists.
#
# Keyed on the owner, not the clock. Deleting an order nulls `reserved_order_id` through
# the FK and leaves the timestamp behind; reading the timestamp alone would keep the phone
# out of the pool on behalf of an order that no longer exists.
_UNRESERVED = """
        (c.reserved_order_id IS NULL OR c.reserved_until < now())
"""
_MINE_OR_UNRESERVED = """
        (c.reserved_order_id IS NULL
         OR c.reserved_until < now()
         OR c.reserved_order_id = CAST(:for_order_id AS bigint))
"""

_ALLOC_SQL = text(
    f"""
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
      AND {_MINE_OR_UNRESERVED}
    -- Take back what this order already holds before touching the open pool: the buyer
    -- paid for these, and spending a free phone here while their own sits reserved would
    -- shrink the shelf for no one's benefit.
    ORDER BY coalesce(c.reserved_order_id = CAST(:for_order_id AS bigint), false) DESC,
             (c.tier = 'stable') DESC, c.last_online_at DESC NULLS LAST
    FOR UPDATE OF c SKIP LOCKED
    LIMIT 1
    """  # noqa: S608
)


async def allocate(
    session: AsyncSession,
    *,
    location_id: int | None = None,
    carrier: str | None = None,
    exclude_id: int | None = None,
    for_order_id: int | None = None,
) -> tuple[int, str] | None:
    """Return (connection_id, iproxy_connection_id) locked for this txn, or None.

    ``for_order_id`` unlocks that order's own reservations and prefers them. Callers with
    no order behind them — an operator issuing by hand — pass nothing and see reserved
    phones as taken, which is the entire purpose of a reservation.
    """
    row = (
        await session.execute(
            _ALLOC_SQL,
            {
                "location_id": location_id,
                "carrier": carrier,
                "exclude_id": exclude_id,
                "for_order_id": for_order_id,
            },
        )
    ).first()
    if row is None:
        return None
    # The hold has served its purpose the moment a live access takes the phone. Clearing it
    # here rather than in the caller keeps the two from drifting: every allocation path
    # goes through this function, and a stale hold on a rented phone would make the pool
    # screen lie about why it is unavailable.
    await session.execute(
        text(
            "UPDATE connections SET reserved_order_id = NULL, reserved_until = NULL "
            "WHERE id = :id"
        ),
        {"id": row[0]},
    )
    return (row[0], row[1])


# What "free" means, in one place: online, not held by the iproxy console, not already
# rented, and not reserved for somebody's open invoice. Kept as a fragment so the city
# list, the unplaced count and the availability count cannot drift apart, and so all of
# them keep matching `allocate`'s own WHERE clause.
_FREE_PREDICATE = f"""
        c.online_status = 'online'
        AND c.external_access_count = 0
        AND NOT EXISTS (
          SELECT 1 FROM accesses a
          WHERE a.connection_id = c.id
            AND a.status IN ('provisioning','active','expiring')
        )
        AND {_UNRESERVED}
"""  # noqa: S608 — the only interpolation is _UNRESERVED, a constant defined above

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

_COUNT_SQL = text(
    f"""
    SELECT count(*) FROM connections c
    WHERE c.is_sellable
      AND (CAST(:location_id AS bigint) IS NULL OR c.location_id = CAST(:location_id AS bigint))
      AND (CAST(:carrier AS text) IS NULL OR c.carrier = CAST(:carrier AS text))
      AND {_FREE_PREDICATE}
    """  # noqa: S608
)

# Pick the phones, lock them, stamp them — one statement, so two buyers checking out in the
# same instant cannot be handed the same phone. SKIP LOCKED means the second one takes the
# next phones down the list instead of waiting behind the first.
_RESERVE_SQL = text(
    f"""
    WITH picked AS (
        SELECT c.id
        FROM connections c
        WHERE c.is_sellable
          AND (CAST(:location_id AS bigint) IS NULL
               OR c.location_id = CAST(:location_id AS bigint))
          AND (CAST(:carrier AS text) IS NULL OR c.carrier = CAST(:carrier AS text))
          AND {_FREE_PREDICATE}
        ORDER BY (c.tier = 'stable') DESC, c.last_online_at DESC NULLS LAST
        FOR UPDATE SKIP LOCKED
        LIMIT :want
    )
    UPDATE connections SET reserved_order_id = :order_id, reserved_until = :until
    WHERE id IN (SELECT id FROM picked)
    RETURNING id
    """  # noqa: S608
)


async def available_locations(
    session: AsyncSession, *, include_sold_out: bool = False
) -> list[dict[str, Any]]:
    """Cities that can be sold from, each with its carriers and how many are free now.

    Two callers want two different lists, which is why the flag is explicit rather than a
    default anybody can drift:

    * The **buyer's catalogue** passes ``include_sold_out=True``. A city whose phones are
      all rented is still a city we sell; the app lists it greyed out and unselectable, so
      the shop does not appear to shrink every time somebody else buys — with three
      stocked cities, losing one to a sale halves the visible coverage.
    * The **operator's Issue-access picker** takes the default. It has no greyed-out
      state, so a city offered there is one the allocator has to be able to serve;
      anything else is learned from a failed issue.

    Either way ``free`` is the allocator's own definition — the same predicate `allocate`
    uses — so a non-zero count cannot turn into "no free connection" at checkout, and a
    city that has never held a sellable phone is absent from both lists.

    A connection with no carrier recorded still counts toward the city (it can be handed
    out when no carrier is asked for) but names no carrier of its own. A connection with no
    *city* is in neither list — see `unplaced_free_counts`.
    """
    rows = (await session.execute(_AVAILABILITY_SQL)).all()
    by_location: dict[int, dict[str, Any]] = {}
    for loc_id, city, state, carrier, free, _stocked in rows:
        entry = by_location.setdefault(
            int(loc_id),
            {"id": str(loc_id), "city": city, "state_code": state, "free": 0, "carriers": []},
        )
        entry["free"] += int(free)
        if carrier and (int(free) > 0 or include_sold_out):
            entry["carriers"].append({"carrier": carrier, "free": int(free)})
    cities = list(by_location.values())
    if include_sold_out:
        return cities
    return [c for c in cities if c["free"] > 0]


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
        _COUNT_SQL, {"location_id": location_id, "carrier": carrier}
    )
    return int(row.scalar_one())


async def reserve(
    session: AsyncSession,
    *,
    order_id: int,
    until: datetime,
    want: int,
    location_id: int | None = None,
    carrier: str | None = None,
) -> int:
    """Hold up to ``want`` matching phones for this order. Returns how many were taken.

    Fewer than asked is a normal answer, not a failure: somebody wanting ten where seven
    are free is a customer who wants ten, and the caller sells them the seven. Zero means
    sold out.

    ``until`` is the deadline the hold dies on by itself. It exists because every explicit
    release — invoice expiry, cancellation, the order completing — is code that can be
    skipped by a crash or a branch nobody thought about, and a hold that outlives its
    order removes a phone from the shelf with no way to notice. The clock turns the worst
    case from lost inventory into a phone that idles until the invoice would have expired.
    """
    if want < 1:
        return 0
    rows = (
        await session.execute(
            _RESERVE_SQL,
            {
                "order_id": order_id,
                "until": until,
                "want": want,
                "location_id": location_id,
                "carrier": carrier,
            },
        )
    ).all()
    return len(rows)


async def release_reservations(session: AsyncSession, *, order_id: int) -> int:
    """Put back everything this order was holding. Returns how many phones were freed."""
    rows = (
        await session.execute(
            text(
                "UPDATE connections SET reserved_order_id = NULL, reserved_until = NULL "
                "WHERE reserved_order_id = :order_id RETURNING id"
            ),
            {"order_id": order_id},
        )
    ).all()
    return len(rows)


async def release_stale_reservations(session: AsyncSession) -> int:
    """Clear holds whose deadline has passed.

    Nothing depends on this for correctness — every query that asks what is free already
    ignores a lapsed hold. It runs so the pool screen does not show an operator a phone
    marked "reserved" by an order that died last week, which reads as a system that has
    lost track of its own stock.

    Also clears the deadline left behind when an order is deleted: the FK nulls the owner
    and cannot touch the timestamp, so the row keeps a date nobody is waiting for.
    """
    rows = (
        await session.execute(
            text(
                "UPDATE connections SET reserved_order_id = NULL, reserved_until = NULL "
                "WHERE reserved_until IS NOT NULL "
                "  AND (reserved_order_id IS NULL OR reserved_until < now()) "
                "RETURNING id"
            )
        )
    ).all()
    return len(rows)
