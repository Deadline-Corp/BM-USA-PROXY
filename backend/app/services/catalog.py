"""Catalog: tariffs, locations, carriers, and city×carrier availability."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, Tariff, User
from app.services.provisioning import allocator


async def trial_available(session: AsyncSession, user: User) -> bool:
    used = await session.scalar(
        select(Order.id).where(
            Order.user_id == user.id,
            Order.tariff_code == "trial",
            Order.status.in_(("paid", "provisioning", "completed")),
        )
    )
    return used is None


async def get_catalog(session: AsyncSession, user: User) -> dict[str, Any]:
    """What a buyer may choose from — and nothing else.

    Cities, carriers and their counts all come from `allocator.available_locations`, which
    is the same query the allocator itself runs. That matters more than it sounds: this
    screen used to count "free" with its own SQL, which did not know about phones held
    inside the iproxy console, and listed a city if it merely held a sellable phone. So a
    buyer could pick Los Angeles, press Buy, and be told the location just sold out —
    measured on production, the catalogue offered Los Angeles while the allocator had
    nothing free there at all.

    A city or a carrier with nothing free is absent rather than shown as zero. Offering a
    choice whose only outcome is an error is not offering a choice.
    """
    tariffs = (
        (await session.execute(
            select(Tariff).where(Tariff.is_active).order_by(Tariff.sort_order)
        )).scalars().all()
    )
    # Sold-out cities included on purpose — the picker greys them out rather than hiding
    # them, so the coverage on offer does not shrink every time somebody else buys.
    available = await allocator.available_locations(session, include_sold_out=True)
    # Sellable phones with no city of their own. They can only ever be handed out under
    # "Any city", so they are counted there and nowhere else — leaving them out understated
    # what was actually on the shelf.
    unplaced = await allocator.unplaced_free_counts(session)

    # Only carriers somebody can actually be given, across the cities that have stock. The
    # list used to be the three US networks, hardcoded, whether or not a single phone on
    # one was free.
    # Carriers are filtered to those with something free, cities are not. The difference
    # is what the picker can do with them: a sold-out city is shown greyed out and cannot
    # be chosen, while the carrier dropdown has no such state — listing a carrier with
    # nothing free there is a choice whose only outcome is "no free connection".
    carriers_present = sorted(
        {c["carrier"] for loc in available for c in loc["carriers"] if int(c["free"]) > 0}
        | {carrier for carrier in unplaced if carrier != "any"}
    )

    def per_carrier(loc: dict[str, Any]) -> dict[str, int]:
        counts = {c["carrier"]: int(c["free"]) for c in loc["carriers"]}
        # `any` is the city's own total, not the sum of the named carriers: a phone with no
        # carrier recorded can still be handed out when the buyer does not ask for one.
        return {**{c: counts.get(c, 0) for c in carriers_present}, "any": int(loc["free"])}

    total_free = sum(int(loc["free"]) for loc in available)
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
        "carriers": carriers_present,
        "locations": [
            {
                "id": int(loc["id"]),
                "city": loc["city"],
                "state_code": loc["state_code"],
                "free": per_carrier(loc),
            }
            for loc in sorted(available, key=lambda x: x["city"])
        ],
        # "Any city" is every free phone, including ones whose carrier is unknown — picking
        # no city is the buyer saying they do not care where it is.
        "any_city_free": {
            **{
                carrier: sum(
                    int(c["free"])
                    for loc in available
                    for c in loc["carriers"]
                    if c["carrier"] == carrier
                )
                + unplaced.get(carrier, 0)
                for carrier in carriers_present
            },
            "any": total_free + unplaced["any"],
        },
        "trial_available": await trial_available(session, user),
    }
