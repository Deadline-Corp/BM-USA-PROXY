"""Buying several proxies in one order.

Customers were asking for ten and being sold one at a time — ten invoices, ten transfers
and ten sets of network fees for what is one purchase. An order now carries a quantity,
and the two things that can go wrong with that are both about stock: there may be less on
the shelf than was asked for when the order is placed, and less again by the time the
money actually arrives, minutes later on a chain. Neither may take the sale away.
"""

from __future__ import annotations

from app.core.errors import ValidationError
from app.models import Access, Connection, Location, NotificationOutbox, Order, Tariff, User
from app.services import orders as orders_svc
from app.services.users import accept_terms
from scripts.seed import seed_settings
from sqlalchemy import func, select


async def _buyer(session, *, tg: int = 5550001) -> User:
    user = User(tg_user_id=tg, referral_code=f"QTY{tg}")
    session.add(user)
    await session.flush()
    await seed_settings(session)
    await session.flush()
    await accept_terms(session, user, version=1, answers={}, source="twa")
    return user


async def _plan(session, *, price: str = "10", code: str = "q-daily") -> Tariff:
    tariff = Tariff(
        code=code, name="Daily", kind="auto", auto_issue=True,
        duration_minutes=1440, price_usd=price, is_active=True,
    )
    session.add(tariff)
    await session.flush()
    return tariff


async def _phones(session, count: int, *, city: str = "Reno") -> Location:
    loc = Location(city=city, state_code="NV", is_active=True)
    session.add(loc)
    await session.flush()
    for i in range(count):
        session.add(
            Connection(
                iproxy_connection_id=f"q-{city}-{i}",
                name=f"{city} #{i}",
                location_id=loc.id,
                carrier="Verizon",
                is_sellable=True,
                online_status="online",
            )
        )
    await session.flush()
    return loc


async def _accesses(session, order_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Access).where(Access.order_id == order_id)
        )
        or 0
    )


async def _notifications(session, user_id: int, code: str) -> list[dict]:
    rows = await session.scalars(
        select(NotificationOutbox).where(
            NotificationOutbox.user_id == user_id, NotificationOutbox.template_code == code
        )
    )
    return [r.payload for r in rows]


async def test_the_whole_order_is_one_invoice_at_the_multiplied_price(session) -> None:
    """Three proxies is one deposit for three, not three deposits — that is the point."""
    user = await _buyer(session)
    await _plan(session)
    loc = await _phones(session, 5)

    order, _invoice = await orders_svc.create_order(
        session, user=user, tariff_code="q-daily", location_id=loc.id, quantity=3
    )

    assert order.quantity == 3
    assert float(order.amount_usd) == 30.0


async def test_asking_for_more_than_is_left_sells_what_is_left(session) -> None:
    """Ten wanted, seven on the shelf: the sale is seven, not an error.

    The app warns and asks the buyer to confirm before this is called; trimming here is
    what makes that confirmation honest, and the remaining three are a second purchase.
    """
    user = await _buyer(session, tg=5550002)
    await _plan(session)
    loc = await _phones(session, 7, city="Mesa")

    order, _invoice = await orders_svc.create_order(
        session, user=user, tariff_code="q-daily", location_id=loc.id, quantity=10
    )

    assert order.quantity == 7
    assert float(order.amount_usd) == 70.0


async def test_a_plan_limited_per_customer_cannot_be_bought_in_bulk(session) -> None:
    """Otherwise 'one free trial each' is bypassed by asking for five."""
    user = await _buyer(session, tg=5550003)
    tariff = await _plan(session, price="0", code="q-trial")
    tariff.max_per_user = 1
    await session.flush()
    loc = await _phones(session, 5, city="Tempe")

    try:
        await orders_svc.create_order(
            session, user=user, tariff_code="q-trial", location_id=loc.id, quantity=5
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("a per-customer cap must not be multipliable")


async def test_a_nonsense_quantity_is_refused(session) -> None:
    """A typo in a number box should not be able to quote somebody five figures."""
    user = await _buyer(session, tg=5550004)
    await _plan(session)
    loc = await _phones(session, 3, city="Yuma")

    for bad in (0, -1, orders_svc.MAX_QUANTITY + 1):
        try:
            await orders_svc.create_order(
                session, user=user, tariff_code="q-daily", location_id=loc.id, quantity=bad
            )
        except ValidationError:
            continue
        raise AssertionError(f"quantity {bad} should have been refused")


async def test_paying_for_three_issues_three_and_says_so_once(session) -> None:
    """Three proxies, three accesses, and ONE message — not three identical ones."""
    user = await _buyer(session, tg=5550005)
    await _plan(session, price="0", code="q-free")  # price 0 provisions immediately
    loc = await _phones(session, 4, city="Bend")

    order, _ = await orders_svc.create_order(
        session, user=user, tariff_code="q-free", location_id=loc.id, quantity=3
    )
    await session.flush()

    assert order.status == "completed"
    assert await _accesses(session, order.id) == 3
    batch = await _notifications(session, user.id, "accesses_issued")
    assert len(batch) == 1
    assert batch[0]["count"] == 3
    assert await _notifications(session, user.id, "access_issued") == []


async def test_a_shortfall_at_issue_time_still_hands_over_what_it_can(session) -> None:
    """Stock is checked when the order is placed; the money lands minutes later.

    Somebody else can buy in between. Failing the whole order would leave a buyer who paid
    for three with nothing while a human is found — they get the two that exist now, and
    the order waits on an operator for the difference rather than being quietly completed.
    """
    user = await _buyer(session, tg=5550006)
    await _plan(session, price="0", code="q-short")
    loc = await _phones(session, 3, city="Ogden")

    order, _ = await orders_svc.create_order(
        session, user=user, tariff_code="q-short", location_id=loc.id, quantity=3
    )
    await session.flush()
    assert await _accesses(session, order.id) == 3

    # Now the same again with the shelf one short of the order: three wanted, two left.
    user2 = await _buyer(session, tg=5550007)
    loc2 = await _phones(session, 2, city="Provo")
    order2, _ = await orders_svc.create_order(
        session, user=user2, tariff_code="q-short", location_id=loc2.id, quantity=2
    )
    await session.flush()
    # Force the shortfall: the order says three, the pool only ever had two.
    order2.quantity = 3
    await session.flush()
    order2.status = "paid"
    await orders_svc._provision_or_review(session, order2)
    await session.flush()

    assert await _accesses(session, order2.id) == 2, "what could be issued was issued"
    assert order2.status == "manual_review", "and the difference is a human's decision"
    delayed = await _notifications(session, user2.id, "provisioning_delayed")
    assert len(delayed) >= 1
