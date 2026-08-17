"""The revoke reason has to come back out again.

The revoke dialog has required a reason since launch. It was written to `revoke_reason`
and to the event log, and then read by nothing: no endpoint returned either, so the only
way to learn why a customer had been cut off was to ask whoever pressed the button. An
operator was filling in a field that went nowhere.
"""

from __future__ import annotations

from app.models import Access, AdminUser, Connection, Location, Order, Tariff, User
from app.services.provisioning.lifecycle import revoke_access


async def _revoked_access(session, *, actor: str):
    tariff = Tariff(code="t-rev", name="Rev", kind="auto", duration_minutes=60, price_usd=1)
    loc = Location(city="Tempe", state_code="AZ")
    user = User(tg_user_id=950001, referral_code="REVN0001")
    session.add_all([tariff, loc, user])
    await session.flush()
    conn = Connection(iproxy_connection_id="rev-conn-1", location_id=loc.id, is_sellable=True)
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="t-rev", amount_usd=1)
    session.add_all([conn, order])
    await session.flush()
    access = Access(
        user_id=user.id,
        order_id=order.id,
        connection_id=conn.id,
        tariff_code="t-rev",
        status="active",
    )
    session.add(access)
    await session.flush()
    await revoke_access(session, access=access, reason="abuse: port scanning", actor=actor)
    await session.flush()
    return access


async def test_the_reason_is_stored_where_it_can_be_read(session) -> None:
    access = await _revoked_access(session, actor="admin:1")

    assert access.status == "revoked"
    assert access.revoke_reason == "abuse: port scanning"
    assert access.revoked_at is not None


async def test_the_view_hands_back_the_reason_and_who_gave_it(session) -> None:
    """What the packages table renders under the status badge."""
    from app.api.admin.domain import _access_view, _revoked_by_map

    admin = AdminUser(
        email="ops@bmusproxy.local",
        display_name="Ops Lead",
        password_hash="x",
        role="operator",
    )
    session.add(admin)
    await session.flush()
    access = await _revoked_access(session, actor=f"admin:{admin.id}")

    revoked_by = await _revoked_by_map(session, [access.id])
    view = _access_view(
        access, user_display="@someone", city="Tempe", carrier="Verizon",
        revoked_by=revoked_by.get(access.id),
    )

    assert view["revoke_reason"] == "abuse: port scanning"
    assert view["revoked_at"] is not None
    assert view["revoked_by"] == "Ops Lead", "an operator's name, not 'admin:3'"


async def test_an_expiry_names_the_system_rather_than_a_person(session) -> None:
    """`revoked_at` is stamped on expiry too, so the actor is what tells them apart."""
    from app.api.admin.domain import _revoked_by_map

    access = await _revoked_access(session, actor="system")

    assert (await _revoked_by_map(session, [access.id])).get(access.id) == "system"
