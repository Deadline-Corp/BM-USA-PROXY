"""What the Issue-access pickers are allowed to offer.

The city and carrier dropdowns used to list the whole pool, so an operator could pick a
city whose phones were all sold, offline or withheld — and learn that from a failed issue.
`available_locations` answers with the allocator's own definition of free, so anything
offered can actually be handed out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Access, Connection, Location, Order, Tariff, User
from app.services.provisioning.allocator import available_locations


async def _pool(session):
    tariff = Tariff(code="t-av", name="Av", kind="auto", duration_minutes=60, price_usd=1)
    reno = Location(city="Reno", state_code="NV")
    mesa = Location(city="Mesa", state_code="AZ")
    user = User(tg_user_id=940001, referral_code="AVAIL001")
    session.add_all([tariff, reno, mesa, user])
    await session.flush()
    return tariff, reno, mesa, user


def _conn(**kw) -> Connection:
    base = {"is_sellable": True, "online_status": "online", "external_access_count": 0}
    return Connection(**{**base, **kw})


async def test_only_cities_with_something_free_are_offered(session) -> None:
    tariff, reno, mesa, user = await _pool(session)
    # Reno: one free phone. Mesa: one phone, but offline — nothing to sell there.
    session.add_all(
        [
            _conn(iproxy_connection_id="av-1", location_id=reno.id, carrier="Verizon"),
            _conn(iproxy_connection_id="av-2", location_id=mesa.id, carrier="AT&T",
                  online_status="offline"),
        ]
    )
    await session.flush()

    cities = await available_locations(session)

    assert [c["city"] for c in cities] == ["Reno"]
    assert cities[0]["free"] == 1
    assert cities[0]["carriers"] == [{"carrier": "Verizon", "free": 1}]


async def test_a_sold_phone_stops_counting(session) -> None:
    tariff, reno, _mesa, user = await _pool(session)
    conn = _conn(iproxy_connection_id="av-3", location_id=reno.id, carrier="Verizon")
    session.add(conn)
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="t-av", amount_usd=1)
    session.add(order)
    await session.flush()
    session.add(
        Access(
            user_id=user.id,
            order_id=order.id,
            connection_id=conn.id,
            tariff_code="t-av",
            status="active",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await session.flush()

    assert await available_locations(session) == []


async def test_a_phone_held_inside_iproxy_stops_counting(session) -> None:
    """Occupied with no row of ours saying so — the mismatch sync_external_holds records."""
    _tariff, reno, _mesa, _user = await _pool(session)
    session.add(
        _conn(
            iproxy_connection_id="av-4",
            location_id=reno.id,
            carrier="Verizon",
            external_access_count=1,
        )
    )
    await session.flush()

    assert await available_locations(session) == []


async def test_carriers_are_listed_per_city_with_their_own_counts(session) -> None:
    _tariff, reno, mesa, _user = await _pool(session)
    session.add_all(
        [
            _conn(iproxy_connection_id="av-5", location_id=reno.id, carrier="Verizon"),
            _conn(iproxy_connection_id="av-6", location_id=reno.id, carrier="Verizon"),
            _conn(iproxy_connection_id="av-7", location_id=reno.id, carrier="T-Mobile"),
            _conn(iproxy_connection_id="av-8", location_id=mesa.id, carrier="AT&T"),
        ]
    )
    await session.flush()

    cities = {c["city"]: c for c in await available_locations(session)}

    assert cities["Reno"]["free"] == 3
    assert sorted(cities["Reno"]["carriers"], key=lambda c: c["carrier"]) == [
        {"carrier": "T-Mobile", "free": 1},
        {"carrier": "Verizon", "free": 2},
    ]
    assert cities["Mesa"]["carriers"] == [{"carrier": "AT&T", "free": 1}]


async def test_a_phone_without_a_carrier_counts_for_the_city_but_names_no_carrier(
    session,
) -> None:
    """It can still be handed out when no carrier is asked for, so the city stays offerable."""
    _tariff, reno, _mesa, _user = await _pool(session)
    session.add(_conn(iproxy_connection_id="av-9", location_id=reno.id, carrier=None))
    await session.flush()

    cities = await available_locations(session)

    assert cities[0]["free"] == 1
    assert cities[0]["carriers"] == []
