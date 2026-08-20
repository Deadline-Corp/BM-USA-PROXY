"""Stock is held for the life of an unpaid invoice.

A quote is a promise about specific phones. Between raising the invoice and the deposit
confirming there is a window — minutes, on a chain having a slow day — and the pool used
to stay open the whole time. Two buyers could be quoted the same phone, both pay, and the
second one's order landed in manual review with a shortfall nobody caused.

The phones now come off the shelf at checkout and go back when the invoice dies. What has
to hold: the buyer who paid gets exactly the phones they were promised, nobody else can
take them in the meantime, and a hold can never outlive its order — because a hold that
does is inventory that disappears with nothing to point at.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.errors import Conflict
from app.models import Access, Connection, Invoice, Location, Order, Tariff, User
from app.services import orders as orders_svc
from app.services.maintenance import expire_invoices
from app.services.provisioning import allocator
from app.services.users import accept_terms
from scripts.seed import seed_settings
from sqlalchemy import func, select


async def _buyer(session, *, tg: int) -> User:
    user = User(tg_user_id=tg, referral_code=f"RES{tg}")
    session.add(user)
    await session.flush()
    await seed_settings(session)
    await session.flush()
    await accept_terms(session, user, version=1, answers={}, source="twa")
    return user


async def _plan(session, *, price: str = "10", code: str = "r-daily") -> Tariff:
    tariff = Tariff(
        code=code, name="Daily", kind="auto", auto_issue=True,
        duration_minutes=1440, price_usd=price, is_active=True,
    )
    session.add(tariff)
    await session.flush()
    return tariff


async def _phones(session, count: int, *, city: str) -> Location:
    loc = Location(city=city, state_code="NV", is_active=True)
    session.add(loc)
    await session.flush()
    for i in range(count):
        session.add(
            Connection(
                iproxy_connection_id=f"res-{city}-{i}",
                name=f"{city} #{i}",
                location_id=loc.id,
                carrier="Verizon",
                is_sellable=True,
                online_status="online",
            )
        )
    await session.flush()
    return loc


async def _held_by(session, order_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Connection)
            .where(Connection.reserved_order_id == order_id)
        )
        or 0
    )


async def test_checkout_takes_the_phones_off_the_shelf(session) -> None:
    """Three of five quoted means two left for everybody else — immediately, not on payment."""
    user = await _buyer(session, tg=5560001)
    await _plan(session)
    loc = await _phones(session, 5, city="Reno")

    assert await allocator.count_available(session, location_id=loc.id) == 5

    order, invoice = await orders_svc.create_order(
        session, user=user, tariff_code="r-daily", location_id=loc.id, quantity=3
    )
    assert invoice is not None

    assert await _held_by(session, order.id) == 3
    assert await allocator.count_available(session, location_id=loc.id) == 2


async def test_a_second_buyer_cannot_take_what_is_already_quoted(session) -> None:
    """The whole point. Both buyers used to be quoted the same phones and both could pay."""
    first = await _buyer(session, tg=5560002)
    second = await _buyer(session, tg=5560003)
    await _plan(session)
    loc = await _phones(session, 5, city="Mesa")

    await orders_svc.create_order(
        session, user=first, tariff_code="r-daily", location_id=loc.id, quantity=3
    )
    # The second buyer asks for all five and is honestly sold the two that are left.
    later, _ = await orders_svc.create_order(
        session, user=second, tariff_code="r-daily", location_id=loc.id, quantity=5
    )

    assert later.quantity == 2
    assert float(later.amount_usd) == 20.0
    assert await allocator.count_available(session, location_id=loc.id) == 0


async def test_the_shelf_being_entirely_held_reads_as_sold_out(session) -> None:
    """Not "an error occurred" — the phones exist, they are just spoken for."""
    first = await _buyer(session, tg=5560004)
    second = await _buyer(session, tg=5560005)
    await _plan(session)
    loc = await _phones(session, 2, city="Yuma")

    await orders_svc.create_order(
        session, user=first, tariff_code="r-daily", location_id=loc.id, quantity=2
    )
    try:
        await orders_svc.create_order(
            session, user=second, tariff_code="r-daily", location_id=loc.id, quantity=1
        )
    except Conflict:
        pass
    else:
        raise AssertionError("a fully reserved city must report sold out")


async def test_paying_gets_back_exactly_what_was_held(session) -> None:
    """The buyer is issued their own reserved phones, not whatever is free at the time.

    Without this the order would queue behind its own hold and be told the pool is empty —
    the reservation would have made the failure it was built to prevent.
    """
    user = await _buyer(session, tg=5560006)
    await _plan(session)
    loc = await _phones(session, 3, city="Tempe")

    order, _ = await orders_svc.create_order(
        session, user=user, tariff_code="r-daily", location_id=loc.id, quantity=3
    )
    assert await allocator.count_available(session, location_id=loc.id) == 0

    await orders_svc.mark_paid(session, order=order, source="test")

    assert order.status == "completed"
    issued = int(
        await session.scalar(
            select(func.count()).select_from(Access).where(Access.order_id == order.id)
        )
        or 0
    )
    assert issued == 3
    # Consumed, not still held: the phones are rented now, and a live access is the reason
    # they are unavailable. A leftover hold on a rented phone makes the pool screen lie.
    assert await _held_by(session, order.id) == 0


async def test_an_expired_invoice_puts_the_phones_back(session) -> None:
    """An abandoned checkout must not cost the shop its stock."""
    user = await _buyer(session, tg=5560007)
    await _plan(session)
    loc = await _phones(session, 4, city="Bend")

    order, invoice = await orders_svc.create_order(
        session, user=user, tariff_code="r-daily", location_id=loc.id, quantity=4
    )
    assert invoice is not None
    assert await allocator.count_available(session, location_id=loc.id) == 0

    invoice.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.flush()
    assert await expire_invoices(session) == 1

    assert order.status == "expired"
    assert await _held_by(session, order.id) == 0
    assert await allocator.count_available(session, location_id=loc.id) == 4


async def test_a_hold_that_outlived_its_deadline_blocks_nobody(session) -> None:
    """The clock is what makes this safe to run unattended.

    Every explicit release is code that can be skipped — a crashed worker, a branch nobody
    thought of. Without a deadline on the hold itself, one missed release is a phone gone
    from the pool with nothing to point at. So a lapsed hold has to be invisible to every
    query that asks what is free, before any sweeper gets round to tidying it.
    """
    user = await _buyer(session, tg=5560008)
    await _plan(session)
    loc = await _phones(session, 2, city="Ely")

    order, _ = await orders_svc.create_order(
        session, user=user, tariff_code="r-daily", location_id=loc.id, quantity=2
    )
    assert await allocator.count_available(session, location_id=loc.id) == 0

    # Wind the deadline back without touching anything else — this is the state a missed
    # release leaves behind.
    await session.execute(
        Connection.__table__.update()
        .where(Connection.reserved_order_id == order.id)
        .values(reserved_until=datetime.now(UTC) - timedelta(hours=2))
    )
    await session.flush()

    assert await allocator.count_available(session, location_id=loc.id) == 2
    assert await allocator.allocate(session, location_id=loc.id) is not None

    # And the sweeper tidies the rows so the pool screen stops naming a dead order.
    freed = await allocator.release_stale_reservations(session)
    assert freed >= 1


async def test_an_operator_issuing_by_hand_does_not_take_reserved_stock(session) -> None:
    """No order behind the request means no claim on somebody else's held phone."""
    user = await _buyer(session, tg=5560009)
    await _plan(session)
    loc = await _phones(session, 1, city="Elko")

    order, _ = await orders_svc.create_order(
        session, user=user, tariff_code="r-daily", location_id=loc.id, quantity=1
    )

    assert await allocator.allocate(session, location_id=loc.id) is None
    # …while the order that holds it still gets it.
    assert await allocator.allocate(session, location_id=loc.id, for_order_id=order.id) is not None


async def test_settling_a_stuck_order_releases_whatever_it_still_held(session) -> None:
    """An order reaches manual_review because issuing went wrong, which is exactly the
    case where a hold is most likely to be left behind."""
    user = await _buyer(session, tg=5560010)
    await _plan(session)
    loc = await _phones(session, 3, city="Winnemucca")

    order, _ = await orders_svc.create_order(
        session, user=user, tariff_code="r-daily", location_id=loc.id, quantity=3
    )
    assert await _held_by(session, order.id) == 3

    freed = await allocator.release_reservations(session, order_id=order.id)

    assert freed == 3
    assert await _held_by(session, order.id) == 0
    assert await allocator.count_available(session, location_id=loc.id) == 3


async def test_a_free_plan_still_issues_without_stranding_its_hold(session) -> None:
    """The trial takes the same path — reserve, then immediately spend it.

    It raises no invoice, so nothing ever expires to trigger a release; if the hold were
    not consumed by the issue itself the phone would sit out until its deadline.
    """
    user = await _buyer(session, tg=5560011)
    await _plan(session, price="0", code="r-trial")
    loc = await _phones(session, 2, city="Fallon")

    order, invoice = await orders_svc.create_order(
        session, user=user, tariff_code="r-trial", location_id=loc.id, quantity=1
    )

    assert invoice is None
    assert order.status == "completed"
    assert await _held_by(session, order.id) == 0
    # One phone rented, one still on the shelf.
    assert await allocator.count_available(session, location_id=loc.id) == 1


async def test_the_catalogue_stops_offering_what_is_held(session) -> None:
    """The buyer's city list counts the same way the allocator does, or the app offers a
    city that cannot be served and the failure is learned at checkout."""
    user = await _buyer(session, tg=5560012)
    await _plan(session)
    loc = await _phones(session, 2, city="Sparks")

    before = {c["city"]: c["free"] for c in await allocator.available_locations(session)}
    assert before["Sparks"] == 2

    await orders_svc.create_order(
        session, user=user, tariff_code="r-daily", location_id=loc.id, quantity=2
    )

    after = {c["city"]: c["free"] for c in await allocator.available_locations(session)}
    assert "Sparks" not in after  # nothing free, so not offered to a new buyer
    sold_out = {
        c["city"]: c["free"]
        for c in await allocator.available_locations(session, include_sold_out=True)
    }
    assert sold_out["Sparks"] == 0  # still a city we sell, just greyed out


async def test_a_reservation_never_survives_its_order(session) -> None:
    """Deleting an order must free its phones, never take them with it — and never fail.

    The foreign key nulls the owner but cannot clear the deadline in the same statement,
    so a both-or-neither constraint here would turn deleting an order into an integrity
    error, and reading the deadline alone would hold the phone for an order that no longer
    exists. Both were real: the first version of this had them.
    """
    user = await _buyer(session, tg=5560013)
    await _plan(session)
    loc = await _phones(session, 2, city="Carson")

    order, _ = await orders_svc.create_order(
        session, user=user, tariff_code="r-daily", location_id=loc.id, quantity=2
    )
    order_id = order.id
    assert await _held_by(session, order_id) == 2

    await session.execute(Invoice.__table__.delete().where(Invoice.order_id == order_id))
    await session.execute(Order.__table__.delete().where(Order.id == order_id))
    await session.flush()

    still_held = int(
        await session.scalar(
            select(func.count())
            .select_from(Connection)
            .where(Connection.reserved_order_id.is_not(None))
        )
        or 0
    )
    assert still_held == 0
    assert await allocator.count_available(session, location_id=loc.id) == 2
