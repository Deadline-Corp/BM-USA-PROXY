"""Referral ledger: accrue → release → reverse (pro-rata) → payout, balance invariant."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.models import AdminUser, Order, ReferralLedger, Tariff, User
from app.services import referral
from app.services import settings as settings_svc
from scripts.seed import seed_settings
from sqlalchemy import select, update

# Valid TRC-20 address — payout requests validate the address against the network, so a
# placeholder like "w" is (correctly) rejected now.
WALLET_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
# These tests exercise ledger mechanics, not the commission rate — pin the rate explicitly
# so a business change (20% → 23%) can't break them.
TEST_PCT = 20


async def _admin(session) -> int:
    a = AdminUser(email="op@test.local", password_hash="x", display_name="op", role="owner")
    session.add(a)
    await session.flush()
    return a.id


async def _mk(session, tg: int, code: str, referrer_id: int | None = None) -> User:
    u = User(tg_user_id=tg, referral_code=code, referrer_user_id=referrer_id)
    session.add(u)
    await session.flush()
    return u


async def _paid_order(session, *, referee: User, referrer: User, amount: str) -> Order:
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    o = Order(
        user_id=referee.id, tariff_id=tariff.id, tariff_code="daily",
        amount_usd=amount, status="completed", referrer_user_id=referrer.id,
        paid_at=datetime.now(UTC),
    )
    session.add(o)
    await session.flush()
    return o


# The exact string the mini-app puts on the share button (ReferralScreen.tsx). Written out
# rather than referenced so that changing it there without changing the bot fails here.
MINIAPP_LINK = "https://t.me/BM_USA_Proxy_bot?start=ref_F11A1225"


def test_the_link_the_miniapp_hands_out_is_one_the_bot_understands() -> None:
    """Every referral shared before 2026-08-11 bound nobody, and nothing said so.

    The mini-app builds `?start=ref_<code>`; the handler read only `r_<code>`. A payload
    that does not match is not an error — /start just greeted the newcomer, skipped the
    binding, and the ledger stayed empty. Zero of six users had a referrer. Pin both
    spellings: links already sitting in people's chats have to keep working.
    """
    from app.bot.handlers.start import referral_code_from

    payload = MINIAPP_LINK.split("?start=", 1)[1]
    assert referral_code_from(payload) == "F11A1225"
    assert referral_code_from("r_F11A1225") == "F11A1225"

    # Post attribution is a different deep link and must not be read as a referral.
    assert referral_code_from("p_ABC12345") is None
    assert referral_code_from(None) is None
    assert referral_code_from("") is None
    assert referral_code_from("ref_") is None  # prefix with no code behind it


async def test_binding_by_deep_link_then_accruing_on_a_paid_order(session) -> None:
    """The path the customer actually walks: follow a link, buy, referrer gets a hold.

    The unit above pins the prefix; this pins that the prefix is all that was missing —
    bind through the same call /start makes, then let a paid order accrue.
    """
    from app.bot.handlers.start import referral_code_from

    await seed_settings(session)
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd=Decimal("10.00"), is_active=True))
    await session.flush()
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)

    referrer = await _mk(session, tg=1001, code="F11A1225")
    referee = await _mk(session, tg=1002, code="F5D2851D")

    code = referral_code_from(MINIAPP_LINK.split("?start=", 1)[1])
    assert code is not None
    assert await referral.try_bind(session, referee=referee, code=code) is True
    assert referee.referrer_user_id == referrer.id
    assert referee.referral_bound_at is not None

    order = await _paid_order(session, referee=referee, referrer=referrer, amount="10.00")
    await referral.accrue(session, order=order)
    await session.flush()

    row = await session.scalar(
        select(ReferralLedger).where(ReferralLedger.referee_user_id == referee.id)
    )
    assert row is not None, "a paid order from a bound referee must leave a ledger row"
    assert float(row.amount_usd) == 2.00  # 20% of $10
    assert row.status == "hold"


async def test_accrue_release_reverse_payout(session) -> None:
    await seed_settings(session)  # needs tariffs? no — settings + we create daily tariff below
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd="10"))
    await session.flush()
    await settings_svc.set_value(session, "referral_min_payout_usd", 1)
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)

    referrer = await _mk(session, 1, "REF00001")
    referee = await _mk(session, 2, "REF00002", referrer_id=referrer.id)

    # three $10 orders → 20% → $2 each accrual (hold)
    orders = [await _paid_order(session, referee=referee, referrer=referrer, amount="10")
              for _ in range(3)]
    for o in orders:
        await referral.accrue(session, order=o)
    assert (await referral.balances(session, referrer.id))["hold"] == 6.0

    # release holds (force due)
    await session.execute(update(ReferralLedger).values(hold_until=datetime.now(UTC)))
    await referral.release_holds(session)
    bal = await referral.balances(session, referrer.id)
    assert bal["hold"] == 0.0
    assert bal["available"] == 6.0

    # full refund of one order → -$2 reversal in available
    await referral.reverse(session, order=orders[0], refund_amount_usd=Decimal("10"))
    assert (await referral.balances(session, referrer.id))["available"] == 4.0

    # payout the net $4
    payout = await referral.request_payout(
        session, user=referrer, wallet_address=WALLET_TRC20, network="TRC20"
    )
    assert float(payout.amount_usd) == 4.0
    assert (await referral.balances(session, referrer.id))["available"] == 0.0

    await referral.mark_payout_paid(session, payout.id, tx_hash="0xabc", operator_id=await _admin(session))
    bal = await referral.balances(session, referrer.id)
    assert bal["paid"] == 4.0
    assert bal["available"] == 0.0


async def test_reject_payout_returns_to_available(session) -> None:
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd="10"))
    await settings_svc.set_value(session, "referral_min_payout_usd", 1)
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)
    await session.flush()
    referrer = await _mk(session, 10, "REFA0001")
    referee = await _mk(session, 11, "REFA0002", referrer_id=referrer.id)
    o = await _paid_order(session, referee=referee, referrer=referrer, amount="10")
    await referral.accrue(session, order=o)
    await session.execute(update(ReferralLedger).values(hold_until=datetime.now(UTC)))
    await referral.release_holds(session)

    payout = await referral.request_payout(
        session, user=referrer, wallet_address=WALLET_TRC20, network="TRC20"
    )
    assert (await referral.balances(session, referrer.id))["available"] == 0.0
    await referral.reject_payout(session, payout.id, reason="bad wallet", operator_id=await _admin(session))
    assert (await referral.balances(session, referrer.id))["available"] == 2.0


async def test_hold_not_counted_until_released(session) -> None:
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd="10"))
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)
    await session.flush()
    referrer = await _mk(session, 20, "REFB0001")
    referee = await _mk(session, 21, "REFB0002", referrer_id=referrer.id)
    o = await _paid_order(session, referee=referee, referrer=referrer, amount="10")
    # hold_until is 14 days out → still on hold, available must be 0
    await referral.accrue(session, order=o)
    bal = await referral.balances(session, referrer.id)
    assert bal["available"] == 0.0
    assert bal["hold"] == 2.0


# ── what the partner is told, and shown ───────────────────────────────────
#
# All four reported by the client's partner on 2026-09-04, from one payout: no message when
# the request was filed, no message to the operator either, no history to reconcile a
# balance that had just gone to zero, and finally "Your payout of $ was sent."


async def test_filing_a_request_tells_the_partner_and_the_operator(session, monkeypatch) -> None:
    from app.services import ops_alerts

    alerts: list[str] = []

    async def fake_notify(_s, text: str) -> int:
        alerts.append(text)
        return 1

    monkeypatch.setattr(ops_alerts, "notify_ops", fake_notify)
    monkeypatch.setattr(referral.ops_alerts, "notify_ops", fake_notify)

    await seed_settings(session)
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd=Decimal("10.00"), is_active=True))
    await session.flush()
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)
    referrer = await _mk(session, 91001, "PARTNER1")
    referee = await _mk(session, 91002, "BROUGHT1", referrer_id=referrer.id)
    order = await _paid_order(session, referee=referee, referrer=referrer, amount="100")
    await referral.accrue(session, order=order)
    await session.execute(
        update(ReferralLedger)
        .where(ReferralLedger.referrer_user_id == referrer.id)
        .values(status="available")
    )
    await session.flush()

    payout = await referral.request_payout(
        session, user=referrer, wallet_address=WALLET_TRC20, network="trc20"
    )
    await session.flush()

    from app.models import NotificationOutbox as Notification

    codes = (
        await session.execute(
            select(Notification.template_code, Notification.payload).where(
                Notification.user_id == referrer.id
            )
        )
    ).all()
    filed = [p for code, p in codes if code == "payout_requested"]
    assert filed, "the partner has to hear that the request was filed"
    assert float(filed[0]["amount_usd"]) == float(payout.amount_usd)

    assert alerts, "the operator learned of payouts only by opening the console"
    assert "Payout requested" in alerts[0] and str(_q_amount(payout)) in alerts[0]


def _q_amount(payout) -> Decimal:
    return Decimal(str(payout.amount_usd)).quantize(Decimal("0.01"))


async def test_the_paid_message_carries_the_amount_from_either_route(session) -> None:
    """It read "Your payout of $ was sent" because the admin console closed payouts with
    its own copy of this logic and never put the amount in the payload."""
    from app.bot.notifier import render
    from app.models import NotificationOutbox as Notification

    await seed_settings(session)
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd=Decimal("10.00"), is_active=True))
    await session.flush()
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)
    operator = await _admin(session)
    referrer = await _mk(session, 91011, "PARTNER2")
    referee = await _mk(session, 91012, "BROUGHT2", referrer_id=referrer.id)
    order = await _paid_order(session, referee=referee, referrer=referrer, amount="50")
    await referral.accrue(session, order=order)
    await session.execute(
        update(ReferralLedger)
        .where(ReferralLedger.referrer_user_id == referrer.id)
        .values(status="available")
    )
    await session.flush()
    payout = await referral.request_payout(
        session, user=referrer, wallet_address=WALLET_TRC20, network="trc20"
    )
    await session.flush()
    await referral.mark_payout_paid(
        session, payout.id, tx_hash="0xabc", operator_id=operator
    )
    await session.flush()

    paid = (
        await session.execute(
            select(Notification.payload).where(
                Notification.user_id == referrer.id,
                Notification.template_code == "payout_paid",
            )
        )
    ).scalars().all()
    assert paid, "no paid notification at all"
    text = await render(session, "payout_paid", paid[0])
    assert text is not None, "a template with an unfilled slot must not be delivered"
    assert "$ was" not in text
    assert str(float(payout.amount_usd)) in text


async def test_a_template_with_nothing_behind_a_slot_is_refused(session) -> None:
    """The empty-string substitution is what turned a missing field into a sentence about
    money that reads as though it went nowhere."""
    from app.bot.notifier import render

    await seed_settings(session)
    assert await render(session, "payout_paid", {"tx_hash": "0xabc"}) is None
    assert await render(session, "payout_paid", {"amount_usd": 10.58, "tx_hash": "0xabc"})


async def test_a_partner_sees_their_own_history_and_who_they_brought(session) -> None:
    await seed_settings(session)
    session.add(Tariff(code="daily", name="Daily", kind="auto", duration_minutes=1440,
                       price_usd=Decimal("10.00"), is_active=True))
    await session.flush()
    await settings_svc.set_value(session, "referral_pct", TEST_PCT)
    referrer = await _mk(session, 91021, "PARTNER3")
    named = User(
        tg_user_id=91022, referral_code="BROUGHT3", referrer_user_id=referrer.id,
        tg_username="coodvin",
    )
    session.add(named)
    await session.flush()
    order = await _paid_order(session, referee=named, referrer=referrer, amount="46")
    await referral.accrue(session, order=order)
    await session.execute(
        update(ReferralLedger)
        .where(ReferralLedger.referrer_user_id == referrer.id)
        .values(status="available")
    )
    await session.flush()
    payout = await referral.request_payout(
        session, user=referrer, wallet_address=WALLET_TRC20, network="trc20"
    )
    await session.flush()

    history = await referral.payout_history(session, referrer.id)
    assert [h["id"] for h in history] == [payout.id]
    assert history[0]["status"] == "requested"
    assert history[0]["network"] == "trc20"

    brought = await referral.referral_breakdown(session, referrer.id)
    assert len(brought) == 1
    # The tail only: a partner can tell their referrals apart without being handed the
    # handle of somebody else's customer.
    assert brought[0]["handle"] == "…vin"
    assert "coodvin" not in brought[0]["handle"]
    assert brought[0]["earned_usd"] == float(payout.amount_usd)


def test_a_referral_with_no_username_is_still_distinguishable() -> None:
    assert referral.mask_handle(None, 6428523975) == "id …975"
    assert referral.mask_handle("@coodvin", None) == "…vin"
    assert referral.mask_handle("ab", None) == "@ab"
    assert referral.mask_handle(None, None) == "—"


def test_only_one_place_closes_a_payout_as_paid() -> None:
    """The bug was a second copy, not a wrong line.

    The admin console closed payouts with its own transcription of `mark_payout_paid`, and
    the copy had drifted: no amount in the notification payload, and none of the check that
    a payout matches the ledger rows backing it. Nothing was wrong with either version in
    isolation, which is why it survived review and reached a partner.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    senders = [
        f"{path.relative_to(root)}:{n}"
        for path in root.rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if 'template_code="payout_paid"' in line
    ]
    assert senders == ["services/referral.py:257"] or len(senders) == 1, (
        f"payout_paid is enqueued from {len(senders)} places: {senders}. "
        "Route every caller through referral.mark_payout_paid instead."
    )
