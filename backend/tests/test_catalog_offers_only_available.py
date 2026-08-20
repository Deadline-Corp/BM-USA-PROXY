"""The catalogue may only offer what the allocator would actually hand out.

A buyer picked Los Angeles, pressed Buy, and was told the location had just sold out —
because the catalogue counted "free" with its own query, which did not know about phones
held inside the iproxy console, and listed any city holding a sellable phone at all.
Measured on production 2026-08-19: the catalogue offered Los Angeles while the allocator
had nothing free there.

Both now read `allocator.available_locations`, so the two cannot disagree.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Access, Connection, Location, Order, Tariff, User
from app.services.catalog import get_catalog


async def _user(session) -> User:
    user = User(tg_user_id=1230001, referral_code="CATA0001")
    session.add(user)
    await session.flush()
    return user


async def _city(session, city: str, state: str) -> Location:
    loc = Location(city=city, state_code=state)
    session.add(loc)
    await session.flush()
    return loc


def _phone(cid: str, loc: Location, carrier: str, **kw) -> Connection:
    base = {
        "iproxy_connection_id": cid,
        "name": cid,
        "location_id": loc.id,
        "carrier": carrier,
        "is_sellable": True,
        "online_status": "online",
    }
    return Connection(**{**base, **kw})


async def test_a_city_with_nothing_free_cannot_be_picked(session) -> None:
    """The city is listed, and its count says nothing is free — the picker greys it out.

    This used to assert the city vanished. It stopped being right when the shop shrank to
    three stocked cities: hiding one the moment its last phone went made the coverage look
    like it had shrunk, and the menu moved under the buyer as other people bought. What
    the original incident actually required is that the buyer cannot *choose* a city the
    allocator would refuse, and a zero count is what the app disables the option on.
    """
    user = await _user(session)
    la = await _city(session, "Los Angeles", "CA")
    vegas = await _city(session, "Las Vegas", "NV")
    # Los Angeles has a phone, but it is held inside iproxy — sellable, online, unusable.
    session.add_all(
        [
            _phone("la-1", la, "T-Mobile", external_access_count=1),
            _phone("lv-1", vegas, "Verizon"),
        ]
    )
    await session.flush()

    catalog = await get_catalog(session, user)

    by_city = {loc["city"]: loc for loc in catalog["locations"]}
    assert by_city["Los Angeles"]["free"]["any"] == 0, "held by iproxy is not free"
    assert by_city["Las Vegas"]["free"]["any"] == 1
    assert catalog["any_city_free"]["any"] == 1, "and it must not inflate the total"


async def test_a_sold_phone_leaves_its_city_visible_but_unpickable(session) -> None:
    user = await _user(session)
    vegas = await _city(session, "Las Vegas", "NV")
    phone = _phone("lv-2", vegas, "Verizon")
    session.add(phone)
    tariff = Tariff(code="t-cat", name="Cat", kind="auto", duration_minutes=60, price_usd=1)
    session.add(tariff)
    await session.flush()
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="t-cat", amount_usd=1)
    session.add(order)
    await session.flush()
    session.add(
        Access(
            user_id=user.id,
            order_id=order.id,
            connection_id=phone.id,
            tariff_code="t-cat",
            status="active",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await session.flush()

    catalog = await get_catalog(session, user)

    assert [loc["city"] for loc in catalog["locations"]] == ["Las Vegas"]
    assert catalog["locations"][0]["free"]["any"] == 0
    assert catalog["any_city_free"]["any"] == 0
    # The carrier list is still free-only: unlike a city, the carrier dropdown has no
    # sold-out state, so a carrier listed there is a choice that has to work.
    assert catalog["carriers"] == [], "no phone free means no carrier to choose either"


async def test_only_carriers_with_something_free_are_listed(session) -> None:
    """The list used to be the three US networks, hardcoded, free phones or not."""
    user = await _user(session)
    vegas = await _city(session, "Las Vegas", "NV")
    session.add_all(
        [
            _phone("lv-3", vegas, "Verizon"),
            _phone("lv-4", vegas, "AT&T", online_status="offline"),
        ]
    )
    await session.flush()

    catalog = await get_catalog(session, user)

    assert catalog["carriers"] == ["Verizon"]
    assert catalog["locations"][0]["free"] == {"Verizon": 1, "any": 1}


async def test_a_phone_with_no_carrier_still_counts_for_the_city(session) -> None:
    """It can be handed out when the buyer does not ask for a carrier."""
    user = await _user(session)
    vegas = await _city(session, "Las Vegas", "NV")
    session.add(_phone("lv-5", vegas, None))
    await session.flush()

    catalog = await get_catalog(session, user)

    assert catalog["locations"][0]["free"]["any"] == 1
    assert catalog["carriers"] == []
