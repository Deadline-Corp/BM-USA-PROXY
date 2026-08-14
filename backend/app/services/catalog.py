"""Catalog: tariffs, locations, carriers, and city×carrier availability."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Connection, Location, Order, Tariff, User

CARRIERS = ["AT&T", "T-Mobile", "Verizon"]


async def trial_available(session: AsyncSession, user: User) -> bool:
    used = await session.scalar(
        select(Order.id).where(
            Order.user_id == user.id,
            Order.tariff_code == "trial",
            Order.status.in_(("paid", "provisioning", "completed")),
        )
    )
    return used is None


async def _availability(session: AsyncSession) -> dict[tuple[int | None, str | None], int]:
    rows = await session.execute(
        text(
            """
            SELECT c.location_id, c.carrier, count(*) AS free
            FROM connections c
            WHERE c.is_sellable AND c.online_status = 'online'
              AND NOT EXISTS (
                SELECT 1 FROM accesses a
                WHERE a.connection_id = c.id
                  AND a.status IN ('provisioning','active','expiring'))
            GROUP BY c.location_id, c.carrier
            """
        )
    )
    return {(r[0], r[1]): int(r[2]) for r in rows}


async def _stocked_location_ids(session: AsyncSession) -> set[int]:
    """Locations that actually have a phone on them.

    A city is offered to a buyer only if it holds stock. Cities are created automatically
    from whatever city a phone reports, and a phone's city changes every time its IP
    rotates — so the table accumulates places nothing is left in. Listing those is not a
    harmless extra: every one of them is a city a buyer can pick and be told "sold out",
    and on the live account nine of twelve listed cities held nothing at all.

    Deliberately "has a sellable phone", not "has a free phone": a city where everything is
    currently rented is still a city we sell, and making it blink out of the list whenever
    the last phone is taken would be worse than showing it with nothing available.
    """
    rows = await session.execute(
        select(Connection.location_id)
        .where(Connection.is_sellable, Connection.location_id.is_not(None))
        .distinct()
    )
    return {int(r[0]) for r in rows}


async def get_catalog(session: AsyncSession, user: User) -> dict[str, Any]:
    tariffs = (
        (await session.execute(
            select(Tariff).where(Tariff.is_active).order_by(Tariff.sort_order)
        )).scalars().all()
    )
    stocked = await _stocked_location_ids(session)
    locations = [
        loc
        for loc in (await session.execute(
            select(Location).where(Location.is_active).order_by(Location.sort_order)
        )).scalars().all()
        if loc.id in stocked
    ]
    avail = await _availability(session)

    def city_free(loc_id: int) -> dict[str, int]:
        per = {c: avail.get((loc_id, c), 0) for c in CARRIERS}
        per["any"] = sum(per.values())
        return per

    total_free = sum(avail.values())
    return {
        "tariffs": [
            {
                "code": t.code,
                "name": t.name,
                "description": t.description,
                "kind": t.kind,
                "auto_issue": t.auto_issue,
                "duration_minutes": t.duration_minutes,
                "price_usd": float(t.price_usd),
                "max_user_swaps": t.max_user_swaps,
            }
            for t in tariffs
        ],
        "carriers": CARRIERS,
        "locations": [
            {
                "id": loc.id,
                "city": loc.city,
                "state_code": loc.state_code,
                "free": city_free(loc.id),
            }
            for loc in locations
        ],
        # "Any city" counts every free phone, including ones whose city is unknown and ones
        # in a city not listed above — picking no city is exactly the buyer saying they do
        # not care where it is. Summing the listed cities instead would under-report the
        # option that is always available.
        "any_city_free": {
            **{
                carrier: sum(n for (_lid, c), n in avail.items() if c == carrier)
                for carrier in CARRIERS
            },
            "any": total_free,
        },
        "trial_available": await trial_available(session, user),
    }
