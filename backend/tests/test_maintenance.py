"""Access expiry sweeper + invoice expirer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import (
    Access,
    Connection,
    Invoice,
    Location,
    NotificationOutbox,
    Order,
    Tariff,
    User,
)
from app.services.maintenance import (
    advance_warning_lead,
    expire_invoices,
    humanise_lead,
    sweep_access_expiries,
)
from sqlalchemy import func, select


async def _access(session, *, hours: float, status: str = "active") -> Access:
    tariff = Tariff(code=f"t{hours}", name="T", kind="auto", duration_minutes=60, price_usd=0)
    loc = Location(city=f"C{hours}", state_code="WA")
    user = User(tg_user_id=int(hours * 1000) + 5000, referral_code=f"SW{int(hours*10):05d}")
    session.add_all([tariff, loc, user])
    await session.flush()
    conn = Connection(iproxy_connection_id=f"sw-{hours}", location_id=loc.id, is_sellable=True)
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code=tariff.code, amount_usd=0)
    session.add_all([conn, order])
    await session.flush()
    acc = Access(
        user_id=user.id, order_id=order.id, connection_id=conn.id, tariff_code=tariff.code,
        status=status, expires_at=datetime.now(UTC) + timedelta(hours=hours),
    )
    session.add(acc)
    await session.flush()
    return acc


async def _outbox(session, user_id: int, code: str) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(NotificationOutbox).where(
            NotificationOutbox.user_id == user_id, NotificationOutbox.template_code == code
        )
    ) or 0)


async def _outbox_payload(session, user_id: int, code: str) -> str | None:
    """The `left` the message will be rendered with — the number the customer reads."""
    row = await session.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.user_id == user_id, NotificationOutbox.template_code == code
        )
    )
    return None if row is None else row.payload.get("left")


async def test_sweeper_expires_due_access(session) -> None:
    acc = await _access(session, hours=-1)  # already past
    await sweep_access_expiries(session)
    assert acc.status == "expired"
    assert acc.revoked_at is not None
    assert await _outbox(session, acc.user_id, "access_expired") == 1


async def test_sweeper_warns_24h(session) -> None:
    acc = await _access(session, hours=12)
    await sweep_access_expiries(session)
    assert acc.status == "expiring"
    assert acc.warned_24h_at is not None
    assert await _outbox(session, acc.user_id, "access_expiring_soon") == 1


async def test_sweeper_is_idempotent_on_warnings(session) -> None:
    acc = await _access(session, hours=12)
    await sweep_access_expiries(session)
    await sweep_access_expiries(session)  # second pass: no duplicate warning
    assert await _outbox(session, acc.user_id, "access_expiring_soon") == 1


async def _access_span(
    session, *, started_h_ago: float, expires_in_h: float, idx: int, status: str = "active"
) -> Access:
    """Access with an explicit issue→expiry span so the duration-based warning gating
    (trial/daily/weekly) can be exercised. Total granted = started_h_ago + expires_in_h."""
    now = datetime.now(UTC)
    tariff = Tariff(code=f"sp{idx}", name="T", kind="auto", duration_minutes=60, price_usd=0)
    loc = Location(city=f"S{idx}", state_code="WA")
    user = User(tg_user_id=700000 + idx, referral_code=f"SP{idx:05d}")
    session.add_all([tariff, loc, user])
    await session.flush()
    conn = Connection(iproxy_connection_id=f"sp-{idx}", location_id=loc.id, is_sellable=True)
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code=tariff.code, amount_usd=0)
    session.add_all([conn, order])
    await session.flush()
    acc = Access(
        user_id=user.id, order_id=order.id, connection_id=conn.id, tariff_code=tariff.code,
        status=status,
        starts_at=now - timedelta(hours=started_h_ago),
        expires_at=now + timedelta(hours=expires_in_h),
    )
    session.add(acc)
    await session.flush()
    return acc


async def test_a_trial_is_warned_ten_minutes_out(session) -> None:
    """The whole reason the warning moved from an hour to ten minutes.

    A one-hour trial can never be given an hour's notice — the warning would fire the
    instant it was issued — so trials were excluded and the client's most numerous
    customers reached the end of their test with no word at all.
    """
    acc = await _access_span(session, started_h_ago=0.85, expires_in_h=0.1, idx=11)
    await sweep_access_expiries(session)
    assert acc.warned_1h_at is not None
    # A free plan is told it can buy one, not to "make a payment to extend".
    assert await _outbox(session, acc.user_id, "trial_expiring_10m") == 1
    assert await _outbox(session, acc.user_id, "access_expiring_10m") == 0
    assert await _outbox(session, acc.user_id, "access_expiring_soon") == 0


async def test_a_trial_is_left_alone_an_hour_out(session) -> None:
    """The old hour-wide window is gone: at issue time a trial hears nothing."""
    acc = await _access_span(session, started_h_ago=0, expires_in_h=1, idx=15)
    await sweep_access_expiries(session)
    assert acc.warned_1h_at is None
    assert await _outbox(session, acc.user_id, "trial_expiring_10m") == 0


async def test_a_paid_plan_gets_the_paid_wording(session) -> None:
    """Same moment, different sentence — a buyer renews, they do not "buy a plan"."""
    acc = await _access_span(session, started_h_ago=23.9, expires_in_h=0.1, idx=12)
    tariff = await session.scalar(select(Tariff).where(Tariff.code == acc.tariff_code))
    assert tariff is not None
    tariff.price_usd = 10
    await session.flush()

    await sweep_access_expiries(session)

    assert acc.warned_1h_at is not None
    assert await _outbox(session, acc.user_id, "access_expiring_10m") == 1
    assert await _outbox(session, acc.user_id, "trial_expiring_10m") == 0
    # Daily still never gets the 24h notice — it would land at issue time.
    assert await _outbox(session, acc.user_id, "access_expiring_soon") == 0


async def test_a_daily_hears_nothing_a_full_day_out(session) -> None:
    """At issue time a Daily buyer is not told their access is ending. Its lead is six
    hours, and a warning that fires as the thing is handed over is not a warning."""
    acc = await _access_span(session, started_h_ago=0, expires_in_h=24, idx=13)
    await sweep_access_expiries(session)
    assert acc.warned_24h_at is None
    assert acc.status == "active"
    assert await _outbox(session, acc.user_id, "access_expiring_soon") == 0


async def test_a_daily_is_warned_six_hours_out(session) -> None:
    """The client's report of 2026-09-10: on a Daily plan the only warning was the
    ten-minute one, because the advance warning was a flat 24 hours and a 24-hour plan
    could never qualify for it. A quarter of the plan can."""
    acc = await _access_span(session, started_h_ago=18, expires_in_h=6, idx=23)
    await sweep_access_expiries(session)
    assert acc.warned_24h_at is not None
    assert acc.status == "expiring"
    assert await _outbox(session, acc.user_id, "access_expiring_soon") == 1
    # And the message says six hours, not "24 hrs" — the sentence carries the real lead.
    assert await _outbox_payload(session, acc.user_id, "access_expiring_soon") == "6 hours"


async def test_a_daily_hears_nothing_seven_hours_out(session) -> None:
    """The other edge of the same window: one hour before it is due, nothing has been sent.
    Without this the six-hour test would pass just as well on a warning that fires at any
    distance at all."""
    acc = await _access_span(session, started_h_ago=17, expires_in_h=7, idx=24)
    await sweep_access_expiries(session)
    assert acc.warned_24h_at is None
    assert await _outbox(session, acc.user_id, "access_expiring_soon") == 0


async def test_weekly_still_gets_a_days_notice(session) -> None:
    """Unchanged by the change: a quarter of a week is 42 hours, and the cap brings it back
    to the 24 hours it has always been."""
    acc = await _access_span(session, started_h_ago=6 * 24, expires_in_h=24, idx=14)
    await sweep_access_expiries(session)
    assert acc.warned_24h_at is not None
    assert await _outbox(session, acc.user_id, "access_expiring_soon") == 1
    assert await _outbox_payload(session, acc.user_id, "access_expiring_soon") == "24 hours"


async def test_the_advance_warning_never_lands_after_the_last_call(session) -> None:
    """A Daily access reaches the end without ever qualifying for the advance warning, so
    the ten-minute call fires first and the advance branch is wide open on the next sweep.
    Telling somebody with six minutes left that they have six hours is worse than silence.
    """
    acc = await _access_span(session, started_h_ago=23.9, expires_in_h=0.1, idx=25)
    await sweep_access_expiries(session)
    assert acc.warned_1h_at is not None
    # A second pass, the way the cron actually runs.
    await sweep_access_expiries(session)
    assert acc.warned_24h_at is None
    assert await _outbox(session, acc.user_id, "access_expiring_soon") == 0


def test_the_lead_is_a_quarter_of_the_plan_capped_at_a_day() -> None:
    """The rule itself, on the four plans the client actually sells."""
    assert advance_warning_lead(60) is None  # trial: 15 min, too close to the last call
    assert advance_warning_lead(1440) == timedelta(hours=6)  # daily
    assert advance_warning_lead(10080) == timedelta(hours=24)  # weekly, capped from 42
    assert advance_warning_lead(43200) == timedelta(hours=24)  # monthly, capped from 180
    # An access with no start stamp: a day's notice, which is what every long plan gets.
    assert advance_warning_lead(None) == timedelta(hours=24)
    # Just either side of the suppression line (twice the ten-minute final warning).
    assert advance_warning_lead(80) is None
    assert advance_warning_lead(84) == timedelta(minutes=21)


def test_the_lead_is_worded_the_way_a_person_says_it() -> None:
    assert humanise_lead(timedelta(hours=24)) == "24 hours"
    assert humanise_lead(timedelta(hours=6)) == "6 hours"
    assert humanise_lead(timedelta(hours=1)) == "1 hour"
    assert humanise_lead(timedelta(minutes=45)) == "45 min"


async def test_invoice_expirer(session) -> None:
    tariff = Tariff(code="tx", name="T", kind="auto", duration_minutes=60, price_usd="10")
    user = User(tg_user_id=99123, referral_code="INVEXP01")
    session.add_all([tariff, user])
    await session.flush()
    order = Order(user_id=user.id, tariff_id=tariff.id, tariff_code="tx", amount_usd="10",
                  status="awaiting_payment")
    session.add(order)
    await session.flush()
    inv = Invoice(order_id=order.id, provider="mock", provider_invoice_id="exp-1",
                  status="pending", amount_usd="10",
                  expires_at=datetime.now(UTC) - timedelta(minutes=1))
    session.add(inv)
    await session.flush()

    assert await expire_invoices(session) == 1
    assert inv.status == "expired"
    assert order.status == "expired"
