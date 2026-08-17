"""Every phone lands in exactly one bucket, and the four add up to the pool.

The screen shows four numbers side by side. If they overlap or leave a gap, the operator
is reading a fiction — which is what happened when phones held inside iproxy were folded
into "unavailable": stock that needs somebody to open the iproxy console looked identical
to a phone that is simply switched off.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.api.admin.domain import pool_summary
from app.models import Access, Connection, Location, Order, Tariff, User


async def _pool(session):
    loc = Location(city="Reno", state_code="NV")
    tariff = Tariff(code="t-sum", name="Sum", kind="auto", duration_minutes=60, price_usd=1)
    user = User(tg_user_id=970001, referral_code="SUMM0001")
    session.add_all([loc, tariff, user])
    await session.flush()

    def conn(cid: str, **kw) -> Connection:
        base = {
            "iproxy_connection_id": cid,
            "name": cid,
            "location_id": loc.id,
            "carrier": "Verizon",
            "is_sellable": True,
            "online_status": "online",
        }
        return Connection(**{**base, **kw})

    sold = conn("sum-sold")
    held = conn("sum-held", external_access_count=2)
    sold_and_held = conn("sum-both", external_access_count=1)
    free = conn("sum-free")
    offline = conn("sum-offline", online_status="offline")
    withheld = conn("sum-withheld", is_sellable=False)
    session.add_all([sold, held, sold_and_held, free, offline, withheld])
    await session.flush()

    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="t-sum", amount_usd=1)
    session.add(order)
    await session.flush()
    for c in (sold, sold_and_held):
        session.add(
            Access(
                user_id=user.id,
                order_id=order.id,
                connection_id=c.id,
                tariff_code="t-sum",
                status="active",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    await session.flush()


async def test_the_four_buckets_cover_the_pool_exactly(session) -> None:
    await _pool(session)

    summary = await pool_summary(admin=None, session=session)  # type: ignore[arg-type]

    assert summary["slots_total"] == 6
    assert summary["slots_used"] == 2  # sold, and sold-while-also-held
    assert summary["slots_held"] == 1  # held only
    assert summary["slots_free"] == 1
    assert summary["slots_unavailable"] == 2  # offline + withheld from sale
    assert (
        summary["slots_used"]
        + summary["slots_held"]
        + summary["slots_free"]
        + summary["slots_unavailable"]
        == summary["slots_total"]
    )


async def test_a_phone_we_sold_is_busy_even_if_iproxy_also_lists_an_access(session) -> None:
    """That access is ours being reported back, not a stranger holding the device."""
    await _pool(session)

    summary = await pool_summary(admin=None, session=session)  # type: ignore[arg-type]

    # sum-both carries external_access_count=1 AND a live access of ours; it must be
    # counted once, as busy.
    assert summary["slots_used"] == 2
    assert summary["slots_held"] == 1


async def test_a_held_phone_is_not_offered_as_free(session) -> None:
    await _pool(session)

    summary = await pool_summary(admin=None, session=session)  # type: ignore[arg-type]

    assert summary["slots_free"] == 1, "only the untouched, online, sellable phone"
