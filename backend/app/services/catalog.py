"""Catalog: tariffs, locations, carriers, and city×carrier availability."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Location, Order, Tariff, User

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


async def get_catalog(session: AsyncSession, user: User) -> dict[str, Any]:
    tariffs = (
        (await session.execute(
            select(Tariff).where(Tariff.is_active).order_by(Tariff.sort_order)
        )).scalars().all()
    )
    locations = (
        (await session.execute(
            select(Location).where(Location.is_active).order_by(Location.sort_order)
        )).scalars().all()
    )
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
        "any_city_free": {
            **{c: sum(avail.get((loc.id, c), 0) for loc in locations) for c in CARRIERS},
            "any": total_free,
        },
        "trial_available": await trial_available(session, user),
    }
