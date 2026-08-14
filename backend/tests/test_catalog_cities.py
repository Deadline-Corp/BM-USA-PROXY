"""Which cities the buyer is offered.

Cities are created automatically from whatever city a phone reports, and a phone's city
changes every time its IP rotates — so the table accumulates places that no longer hold
anything. On the live account that reached nine listed cities with zero phones between
them: every one of those was a city a buyer could pick and be told "sold out". The
catalogue must offer only cities that actually have stock.
"""

from __future__ import annotations

from app.models import Connection, Location, User
from app.services.catalog import get_catalog


async def _user(session) -> User:
    user = User(
        tg_user_id=987654321,
        tg_username="cat_tester",
        status="active",
        referral_code="CATTEST1",
    )
    session.add(user)
    await session.flush()
    return user


async def _city(session, city: str, state: str, *, active: bool = True) -> Location:
    location = Location(city=city, state_code=state, is_active=active)
    session.add(location)
    await session.flush()
    return location


async def test_a_city_with_no_phones_is_not_offered(session) -> None:
    """The nine empty cities that shipped as seed data must not reach the buyer."""
    user = await _user(session)
    stocked = await _city(session, "Milwaukee", "WI")
    await _city(session, "Seattle", "WA")  # seeded, never had a phone

    session.add(
        Connection(
            iproxy_connection_id="cat-1",
            location_id=stocked.id,
            is_sellable=True,
            online_status="online",
            carrier="Verizon",
        )
    )
    await session.flush()

    catalog = await get_catalog(session, user)
    offered = {c["city"] for c in catalog["locations"]}

    assert "Milwaukee" in offered
    assert "Seattle" not in offered


async def test_a_city_whose_phones_are_all_rented_is_still_offered(session) -> None:
    """Sold out is not the same as not stocked.

    A city where every phone is currently rented is still a city we sell. Dropping it from
    the list the moment the last phone is taken would make the menu flicker with demand.
    """
    user = await _user(session)
    busy = await _city(session, "Madison", "WI")
    session.add(
        Connection(
            iproxy_connection_id="cat-2",
            location_id=busy.id,
            is_sellable=True,
            online_status="offline",  # not free right now
            carrier="Verizon",
        )
    )
    await session.flush()

    catalog = await get_catalog(session, user)
    row = next(c for c in catalog["locations"] if c["city"] == "Madison")
    assert row["free"]["any"] == 0  # honest about having nothing available


async def test_a_deactivated_city_stays_hidden_even_with_phones_on_it(session) -> None:
    """Switching a city off in the console outranks it having stock."""
    user = await _user(session)
    hidden = await _city(session, "Boston", "MA", active=False)
    session.add(
        Connection(
            iproxy_connection_id="cat-3",
            location_id=hidden.id,
            is_sellable=True,
            online_status="online",
            carrier="Verizon",
        )
    )
    await session.flush()

    catalog = await get_catalog(session, user)
    assert "Boston" not in {c["city"] for c in catalog["locations"]}


async def test_any_city_counts_phones_with_no_city_at_all(session) -> None:
    """Picking no city means "anywhere", so it must include phones we cannot place.

    A phone whose city iproxy did not report still sells — it just cannot be found by
    filtering for a city. Counting only the listed cities would hide it from the one
    option that is always on the screen.
    """
    user = await _user(session)
    session.add(
        Connection(
            iproxy_connection_id="cat-4",
            location_id=None,  # iproxy reported no city for this one
            is_sellable=True,
            online_status="online",
            carrier="Verizon",
        )
    )
    await session.flush()

    catalog = await get_catalog(session, user)
    assert catalog["locations"] == []  # nothing to filter by
    assert catalog["any_city_free"]["any"] == 1  # but it is still for sale
    assert catalog["any_city_free"]["Verizon"] == 1
