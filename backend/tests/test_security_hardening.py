"""Regression tests for the security-audit fixes (P1/P2/P3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.bot.notifier import render
from app.core.config import Settings
from app.core.errors import Conflict
from app.models import Access, AdminUser, Invoice, Order, Payout, Tariff, User
from app.services import referral
from app.services import settings as settings_svc
from app.services.payments.base import PaymentEventDTO
from app.services.payments.processing import ingest_webhook, process_payment_event
from pydantic import ValidationError as PydanticValidationError
from scripts.seed import seed_dev_fixtures, seed_locations, seed_settings, seed_tariffs
from sqlalchemy import func, select


# ── P1: prod refuses default/missing secrets (pure, no DB) ──────────────
def test_prod_refuses_default_jwt_secret() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(
            env="prod",
            admin_jwt_secret="change-me-in-prod-please-32bytes-min",
            bot_webhook_secret="real-secret",
            credentials_key="k",
        )


def test_prod_refuses_missing_credentials_key() -> None:
    with pytest.raises(PydanticValidationError):
        Settings(
            env="prod",
            admin_jwt_secret="a-proper-real-secret",
            bot_webhook_secret="real-secret",
            credentials_key=None,
        )


def test_prod_accepts_real_secrets() -> None:
    s = Settings(
        env="prod",
        admin_jwt_secret="a-proper-real-secret",
        bot_webhook_secret="real-secret",
        credentials_key="k",
    )
    assert s.is_prod


# ── P2: 'paid' is forward-only + amount-checked ─────────────────────────
async def _seed(session) -> None:
    await seed_settings(session)
    await seed_tariffs(session)
    await seed_locations(session)
    await session.flush()
    await seed_dev_fixtures(session)
    await session.flush()


async def _order_invoice(session, inv_id: str, *, status: str = "pending", amount: str = "10"):
    tariff = await session.scalar(select(Tariff).where(Tariff.code == "daily"))
    u = User(tg_user_id=abs(hash(inv_id)) % 9_000_000 + 2000,
             referral_code=inv_id.replace("-", "").upper()[:12])
    session.add(u)
    await session.flush()
    o = Order(user_id=u.id, tariff_id=tariff.id, tariff_code="daily", duration_minutes=1440,
              amount_usd=amount, status="awaiting_payment")
    session.add(o)
    await session.flush()
    inv = Invoice(order_id=o.id, provider="mock", provider_invoice_id=inv_id, status=status,
                  amount_usd=amount, expires_at=datetime.now(UTC) + timedelta(hours=1))
    session.add(inv)
    await session.flush()
    return o, inv


async def _access_count(session, order_id: int) -> int:
    return int(await session.scalar(
        select(func.count()).select_from(Access).where(Access.order_id == order_id)
    ) or 0)


async def test_paid_does_not_override_terminal(session) -> None:
    await _seed(session)
    o, inv = await _order_invoice(session, "sec-term-1", status="failed")
    dto = PaymentEventDTO(provider_invoice_id="sec-term-1", status="paid", provider_event_id="t1")
    eid = await ingest_webhook(session, provider="mock", raw_body=b"{}", signature_valid=True, dto=dto)
    assert await process_payment_event(session, eid) == "stale"  # paid can't resurrect 'failed'
    assert inv.status == "failed"
    assert await _access_count(session, o.id) == 0


async def test_paid_amount_short_goes_manual_review(session) -> None:
    await _seed(session)
    o, inv = await _order_invoice(session, "sec-amt-1", amount="50")
    dto = PaymentEventDTO(provider_invoice_id="sec-amt-1", status="paid",
                          provider_event_id="a1", paid_amount_usd=Decimal("10"))
    eid = await ingest_webhook(session, provider="mock", raw_body=b"{}", signature_valid=True, dto=dto)
    assert "manual_review" in await process_payment_event(session, eid)
    assert inv.status == "manual_review"
    assert await _access_count(session, o.id) == 0  # not provisioned for a short payment


# ── P2: payout backing check blocks a phantom payout ────────────────────
async def test_mark_payout_paid_rejects_backing_mismatch(session) -> None:
    admin = AdminUser(email="op2@test.local", password_hash="x", display_name="op", role="owner")
    u = User(tg_user_id=773001, referral_code="BACK0001")
    session.add_all([admin, u])
    await session.flush()
    # phantom payout: has an amount but NO ledger rows backing it
    p = Payout(referrer_user_id=u.id, amount_usd="100", wallet_address="w", network="TRC20",
               status="requested")
    session.add(p)
    await session.flush()
    with pytest.raises(Conflict):
        await referral.mark_payout_paid(session, p.id, tx_hash="0xabc", operator_id=admin.id)


# ── P3: notifier substitution is not str.format (no attribute traversal) ─
async def test_notifier_blocks_format_injection(session) -> None:
    await settings_svc.set_value(session, "notify_texts:operator_message", "{msg.__class__} {msg}")
    out = await render(session, "operator_message", {"msg": "hi"})
    assert out == "{msg.__class__} hi"  # .__class__ left literal, {msg} substituted
