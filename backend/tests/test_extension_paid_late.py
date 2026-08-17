"""A paid extension that lands after the access has already expired.

An invoice lives an hour, and create_extension_order only checks the access is alive when
the *order* is created. So a customer can press Extend with twenty minutes left, pay forty
minutes later, and the payment arrives against an access the expiry sweeper has already
retired — including deleting its proxy-accesses on iproxy.

Extending at that point flipped the access back to 'active' over credentials that no longer
exist anywhere: the app says active, the money is taken, and nothing connects. It must be
re-issued instead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Access, Connection, Location, Order, Tariff, User


def _mark_paid():
    """Imported lazily — app.services.orders ↔ payments.processing is circular at
    module scope, and this file would otherwise be the import that trips it."""
    from app.services.orders import mark_paid

    return mark_paid


async def _setup(session, *, access_status: str, spare_phone: bool = True):
    tariff = Tariff(
        code="t-late", name="Late", kind="auto", duration_minutes=1440, price_usd=10
    )
    loc = Location(city="Reno", state_code="NV")
    user = User(tg_user_id=920001, referral_code="LATE0001")
    session.add_all([tariff, loc, user])
    await session.flush()

    conn = Connection(
        iproxy_connection_id="late-conn-1",
        location_id=loc.id,
        carrier="Verizon",
        is_sellable=True,
        online_status="online",
    )
    session.add(conn)
    if spare_phone:
        # A second phone in the same city, so re-issue has somewhere to go even when the
        # original is taken. Without one, "no free connection" is the honest answer.
        session.add(
            Connection(
                iproxy_connection_id="late-conn-2",
                location_id=loc.id,
                carrier="Verizon",
                is_sellable=True,
                online_status="online",
            )
        )
    first_order = Order(
        user_id=user.id, tariff_id=tariff.id, tariff_code="t-late", amount_usd=10
    )
    session.add(first_order)
    await session.flush()

    now = datetime.now(UTC)
    access = Access(
        user_id=user.id,
        order_id=first_order.id,
        connection_id=conn.id,
        tariff_code="t-late",
        status=access_status,
        iproxy_access_id="acc-http-1",
        starts_at=now - timedelta(days=1),
        expires_at=now - timedelta(minutes=5) if access_status == "expired" else now
        + timedelta(hours=5),
    )
    session.add(access)
    await session.flush()

    extension = Order(
        user_id=user.id,
        tariff_id=tariff.id,
        tariff_code="t-late",
        amount_usd=10,
        duration_minutes=1440,
        is_extension=True,
        extends_access_id=access.id,
        status="awaiting_payment",
    )
    session.add(extension)
    await session.flush()
    return access, extension


async def test_a_live_access_is_simply_extended(session) -> None:
    """The ordinary path stays what it was: same phone, same credentials, later expiry."""
    access, extension = await _setup(session, access_status="active")
    before_conn, before_expiry = access.connection_id, access.expires_at

    await _mark_paid()(session, order=extension, source="test")
    await session.flush()

    assert extension.status == "completed"
    assert access.status == "active"
    assert access.connection_id == before_conn, "extending must not move the customer"
    assert access.expires_at > before_expiry


async def test_paying_after_expiry_reissues_rather_than_resurrecting(session) -> None:
    """The whole point: dead credentials must not be sold back to the customer."""
    access, extension = await _setup(session, access_status="expired")

    await _mark_paid()(session, order=extension, source="test")
    await session.flush()

    assert extension.status == "completed"
    assert access.status == "active"
    # Re-issued, so a fresh provisioner call happened and the old dead id is gone.
    assert access.iproxy_access_id != "acc-http-1"
    assert access.credentials_enc is not None
    # And they got the time they paid for, not the old plan's leftovers.
    remaining = access.expires_at - datetime.now(UTC)
    assert timedelta(hours=23) < remaining <= timedelta(hours=24)


async def test_nothing_free_parks_the_order_for_an_operator(session) -> None:
    """Better a human looks at it than the buyer being told 'paid' over a dead access."""
    access, extension = await _setup(session, access_status="expired", spare_phone=False)
    # Occupy the only phone with somebody else's live access.
    other = User(tg_user_id=920002, referral_code="LATE0002")
    session.add(other)
    await session.flush()
    session.add(
        Access(
            user_id=other.id,
            order_id=extension.id,
            connection_id=access.connection_id,
            tariff_code="t-late",
            status="active",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await session.flush()

    await _mark_paid()(session, order=extension, source="test")
    await session.flush()

    assert extension.status == "manual_review"
    assert access.status == "expired", "a failed re-issue must not claim the access is live"
