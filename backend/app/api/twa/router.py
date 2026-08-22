"""Telegram Mini-App API — all customer actions live here (bot is minimal)."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import Conflict, NotFound, RateLimited, ValidationError
from app.models import FaqItem, Invoice, ReferralLedger, Request
from app.services import accesses as accesses_svc
from app.services import catalog as catalog_svc
from app.services import ops_alerts, vpn_configs
from app.services import orders as orders_svc
from app.services import payouts as payouts_svc
from app.services import settings as settings_svc
from app.services import users as users_svc
from app.services.notifications import enqueue
from app.services.payments.invoice_links import (
    invoice_pay_uri,
    invoice_qr_code,
    invoice_qr_payload,
)
from app.services.provisioning.lifecycle import rotate_ip, swap_access

router = APIRouter(prefix="/api/twa", tags=["twa"])


# ── profile / catalog ───────────────────────────────────────────────────
@router.get("/me")
async def me(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    available = await session.scalar(
        select(func.coalesce(func.sum(ReferralLedger.amount_usd), 0)).where(
            ReferralLedger.referrer_user_id == user.id, ReferralLedger.status == "available"
        )
    )
    active = await session.scalar(
        select(func.count()).select_from(accesses_svc.Access).where(
            accesses_svc.Access.user_id == user.id,
            accesses_svc.Access.status.in_(("provisioning", "active", "expiring")),
        )
    )
    return {
        "tg_user_id": user.tg_user_id,
        "first_name": user.first_name,
        "active_accesses": int(active or 0),
        "referral": {"code": user.referral_code, "available_usd": float(available or 0)},
        "trial_available": await catalog_svc.trial_available(session, user),
        "tos_accepted": await users_svc.is_tos_accepted(session, user),
    }


@router.get("/catalog")
async def catalog(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    return await catalog_svc.get_catalog(session, user)


# ── orders / checkout ───────────────────────────────────────────────────
class CreateOrder(BaseModel):
    tariff_code: str
    location_id: int | None = None
    carrier: str | None = None
    # Which rail to be quoted in. Omitted → the first configured rail, which is only ever
    # right by accident once more than one is enabled.
    asset: str | None = None
    network: str | None = None
    # How many proxies. Trimmed server-side to what is actually free, so the app asking
    # for ten where seven are left gets an order for seven and is told the number back.
    quantity: int = 1


# The buyer picks a chain first and a coin second, so those two need separate labels.
_CHAIN_LABELS = {
    "tron": "Tron",
    "ethereum": "Ethereum",
    "bsc": "BNB Chain (BSC)",
    "solana": "Solana",
    "bitcoin": "Bitcoin",
    "litecoin": "Litecoin",
}

_NETWORK_LABELS = {
    "trc20": "TRC-20",
    "erc20": "ERC-20",
    "bep20": "BEP-20",
    "spl": "SPL",
}


@router.get("/payment-methods")
async def payment_methods(session: DbSession) -> dict[str, Any]:
    """Rails the buyer may pay on, in configured order.

    Without this the mini app had no way to offer a choice, so every order was quoted in
    whichever rail happened to be listed first.

    The refresh is why this takes a session. Console-saved rails live in app_settings and
    reach the config through refresh_rails(); the process-wide override starts empty on
    every boot. Reading the config without one meant this endpoint answered from
    ONCHAIN_METHODS alone — empty on this deployment — so after each restart the mini app
    told buyers payments were not configured until some *other* request happened to
    refresh the config. Measured right after a deploy: the rail was in the database and
    this endpoint returned nothing.
    """
    from app.services.payments.onchain.config import get_onchain_config
    from app.services.payments.onchain.rails_cache import refresh_rails_cached

    try:
        await refresh_rails_cached(session)
        cfg = get_onchain_config()
    except Exception:
        return {"methods": []}
    out = []
    for method in cfg.enabled_methods():
        spec = method.spec
        chain_label = _CHAIN_LABELS.get(spec.chain, spec.chain.capitalize())
        if spec.network == "native":
            coin_label = f"{spec.asset} — native coin"
        else:
            coin_label = f"{spec.asset} — {_NETWORK_LABELS.get(spec.network, spec.network.upper())}"
        out.append(
            {
                "asset": spec.asset,
                "network": spec.network,
                "chain": spec.chain,
                "chain_label": chain_label,
                "coin_label": coin_label,
                "label": f"{coin_label} ({chain_label})",
                "min_amount_usd": float(method.min_amount_usd),
            }
        )
    return {"methods": out}


@router.get("/links")
async def links(session: DbSession) -> dict[str, Any]:
    """Channel/Support links, operator-editable in the admin Settings screen.

    Deliberately no CurrentUser here (session only): get_current_user 403s a banned
    account (see AccountBanned in api/deps.py), and BannedScreen.tsx shows this exact
    Support link to exactly that user — the one who most needs a way to reach a human.
    Nothing sensitive is returned, just two public Telegram links.
    """
    return await settings_svc.app_links(session)


def _invoice_view(inv: Invoice | None, order_public_id: str | None = None) -> dict[str, Any] | None:
    if inv is None:
        return None
    # Only offer the hand-off when there is a scheme to hand off to. On Tron the builder
    # returns None and the button must stay hidden rather than open a page apologising.
    wallet_uri = invoice_pay_uri(inv)
    pay_open_url = (
        f"{settings.public_base_url}/pay/{order_public_id}"
        if wallet_uri and order_public_id
        else None
    )
    return {
        "provider": inv.provider,
        "status": inv.status,
        "amount_usd": float(inv.amount_usd),
        "crypto_currency": inv.crypto_currency,
        "crypto_network": inv.crypto_network,
        # STRING, not float: the watcher matches on the exact quoted amount, and assets
        # quoted to 8 decimals (BTC/ETH/LTC) lost their last digits through float +
        # toFixed(6) on the client — the buyer then paid an amount that never matched.
        "crypto_amount": str(inv.crypto_amount) if inv.crypto_amount is not None else None,
        "pay_address": inv.pay_address,
        "pay_uri": invoice_qr_payload(inv),
        # What the QR itself carries. Not the same as pay_uri: the deep link above opens a
        # wallet on this device and may be a contract call, while this has to survive being
        # photographed by an exchange app. See invoice_qr_code.
        "qr_payload": invoice_qr_code(inv),
        # An https URL that redirects into the wallet scheme. Inside Telegram the mini app
        # cannot navigate to `ethereum:` itself — it opens this through the client instead,
        # in a real browser, which is where the OS wallet chooser comes from.
        "pay_open_url": pay_open_url,
        "payment_url": inv.payment_url,
        "expires_at": inv.expires_at.isoformat(),
    }


@router.post("/orders")
async def create_order(body: CreateOrder, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    await orders_svc.guard_order_attempt(
        session, user_id=user.id, tariff_code=body.tariff_code,
        asset=body.asset, network=body.network,
    )
    order, invoice = await orders_svc.create_order(
        session, user=user, tariff_code=body.tariff_code,
        location_id=body.location_id, carrier=body.carrier,
        asset=body.asset, network=body.network, quantity=body.quantity,
    )
    return {
        # `quantity` is what was actually sold, which can be less than what was asked for
        # — the checkout screen shows it, so nobody discovers the trim by counting proxies.
        "order": {"public_id": str(order.public_id), "status": order.status,
                  "amount_usd": float(order.amount_usd), "quantity": int(order.quantity)},
        "invoice": _invoice_view(invoice, str(order.public_id)),
    }


_ACTIVE_ORDER_STATUSES = ("awaiting_payment", "paid", "provisioning")


@router.get("/orders")
async def list_active_orders(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    """Orders still in flight, newest first.

    Without this the mini app had no way back to an unpaid order: the payment details lived
    only in the tab's sessionStorage, so closing the mini app lost the address, the exact
    amount and any sense of what was happening to the money already sent.
    """
    orders = list(
        await session.scalars(
            select(orders_svc.Order)
            .where(
                orders_svc.Order.user_id == user.id,
                orders_svc.Order.status.in_(_ACTIVE_ORDER_STATUSES),
            )
            .order_by(orders_svc.Order.id.desc())
            .limit(20)
        )
    )
    if not orders:
        return {"orders": []}
    # Single query for all invoices — was one scalar per order (N+1, up to 21 queries).
    # Fetch the newest invoice per order_id (same behaviour as the old per-order scalar,
    # which returned the first match with no explicit ordering).
    order_ids = [o.id for o in orders]
    invoices_by_order: dict[int, Invoice] = {}
    invoice_rows = list(
        await session.scalars(
            select(Invoice)
            .where(Invoice.order_id.in_(order_ids))
            .order_by(Invoice.id.desc())
        )
    )
    for inv in invoice_rows:
        # Only keep the first (newest) invoice per order — same as the old scalar's
        # implicit "first row" behaviour, now deterministic.
        if inv.order_id not in invoices_by_order:
            invoices_by_order[inv.order_id] = inv
    out = []
    for order in orders:
        inv_order: Invoice | None = invoices_by_order.get(order.id)
        out.append(
            {
                "public_id": str(order.public_id),
                "status": order.status,
                "tariff_code": order.tariff_code,
                "amount_usd": float(order.amount_usd),
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "invoice": _invoice_view(inv_order, str(order.public_id)),
            }
        )
    return {"orders": out}


@router.get("/orders/{public_id}")
async def order_status(public_id: str, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    order = await orders_svc.get_by_public_id(session, public_id, user_id=user.id)
    inv = await session.scalar(select(Invoice).where(Invoice.order_id == order.id))
    access_pid = None
    if order.status == "completed":
        acc = await session.scalar(
            select(accesses_svc.Access.public_id).where(accesses_svc.Access.order_id == order.id)
        )
        access_pid = str(acc) if acc else None
    return {
        "status": order.status,
        "invoice_status": inv.status if inv else None,
        "access_public_id": access_pid,
        # What was actually sold. The checkout screen names it beside the amount, because
        # an invoice for $20 when the plan says $10 is otherwise unexplained — and it may
        # be fewer than was asked for, if the shelf was short when the order was placed.
        "quantity": int(order.quantity or 1),
        "tariff_code": order.tariff_code,
        # Payment details, so the checkout screen survives a reload or a reopened mini app
        # instead of depending on sessionStorage written at order-creation time.
        "invoice": _invoice_view(inv, str(order.public_id)),
    }


@router.post("/orders/{public_id}/cancel")
async def cancel_order(public_id: str, user: CurrentUser, session: DbSession) -> dict[str, str]:
    order = await orders_svc.get_by_public_id(session, public_id, user_id=user.id)
    await orders_svc.cancel_order(session, order=order)
    return {"status": order.status}


@router.post("/orders/{public_id}/_mock_pay")
async def mock_pay(public_id: str, user: CurrentUser, session: DbSession) -> dict[str, str]:
    """DEV ONLY: simulate a confirmed payment (MockPaymentProvider)."""
    if settings.is_prod or settings.feature_real_payments or settings.env != "local":
        raise NotFound("not found")
    order = await orders_svc.get_by_public_id(session, public_id, user_id=user.id)
    inv = await session.scalar(select(Invoice).where(Invoice.order_id == order.id))
    if inv is not None:
        inv.status = "paid"
    await orders_svc.mark_paid(session, order=order, source="mock")
    return {"status": order.status}


# ── accesses / My Access ────────────────────────────────────────────────
@router.get("/accesses")
async def list_accesses(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    return await accesses_svc.list_for_user(session, user.id)


@router.get("/accesses/{public_id}")
async def access_detail(public_id: str, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    return await accesses_svc.detail_for_user(session, public_id, user.id)


@router.post("/accesses/{public_id}/rotate-ip")
async def rotate(public_id: str, user: CurrentUser, session: DbSession) -> dict[str, str]:
    from app.core.ratelimit import cooldown

    access = await accesses_svc.get_owned(session, public_id, user.id)
    if access.status not in ("active", "expiring"):
        raise Conflict("access is not active")
    cd = int(await settings_svc.get(session, "rotation_cooldown_sec", 60))
    await cooldown(f"rotate:{access.id}", seconds=cd)
    await rotate_ip(session, access=access, actor="user")
    return {"status": "rotated"}


class AutoRotateBody(BaseModel):
    enabled: bool
    # Bounded here and by a CHECK constraint on the column: one minute is the floor
    # because that is the sweep's own cadence, a day the ceiling because past that "off"
    # is the honest setting. Ignored entirely when enabled is false.
    minutes: int | None = Field(default=None, ge=1, le=1440)


@router.put("/accesses/{public_id}/auto-rotate")
async def set_auto_rotate(
    public_id: str, body: AutoRotateBody, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    access = await accesses_svc.get_owned(session, public_id, user.id)
    if access.status not in ("active", "expiring"):
        raise Conflict("access is not active")
    if body.enabled and body.minutes is None:
        raise ValidationError("choose how often to rotate")
    access.auto_rotate_minutes = body.minutes if body.enabled else None
    return {"auto_rotate_minutes": access.auto_rotate_minutes}


class SwapBody(BaseModel):
    location_id: int | None = None
    carrier: str | None = None


@router.post("/accesses/{public_id}/swap")
async def swap(public_id: str, body: SwapBody, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    access = await accesses_svc.get_owned(session, public_id, user.id)
    if access.status not in ("active", "expiring"):
        raise Conflict("access is not active")
    # Was gated by the plan's max_user_swaps, which is 0 on every paid plan — so swap
    # existed for trial buyers and nobody else, and the field it read is not editable in
    # the admin anymore. One a day, on any live access, is the rule now.
    ready = accesses_svc.swap_available_at(access)
    if ready is not None:
        retry_after = max(1, int((ready - datetime.now(UTC)).total_seconds()))
        raise RateLimited("one swap per day", retry_after=retry_after)
    await swap_access(session, access=access, location_id=body.location_id, carrier=body.carrier)
    # Stamped here rather than inside swap_access: the same function reissues an access for
    # an admin, and an admin's repair should not spend the customer's swap for the day.
    access.last_swap_at = datetime.now(UTC)
    return {
        "status": "swapped",
        "swap_available_at": (access.last_swap_at + accesses_svc.SWAP_COOLDOWN).isoformat(),
    }


class ExtendBody(BaseModel):
    tariff_code: str


@router.post("/accesses/{public_id}/extend")
async def extend(public_id: str, body: ExtendBody, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    access = await accesses_svc.get_owned(session, public_id, user.id)
    order, invoice = await orders_svc.create_extension_order(
        session, user=user, access=access, tariff_code=body.tariff_code
    )
    return {
        "order": {"public_id": str(order.public_id), "status": order.status,
                  "amount_usd": float(order.amount_usd)},
        "invoice": _invoice_view(invoice, str(order.public_id)),
    }


class ConfigBody(BaseModel):
    type: str  # 'ovpn' | 'wg'


@router.post("/accesses/{public_id}/config", status_code=202)
async def request_config(
    public_id: str, body: ConfigBody, user: CurrentUser, session: DbSession
) -> dict[str, str]:
    """Ask for the VPN config file; the outbox builds and delivers it.

    Queued rather than done here on purpose. Issuing a config is two iproxy round-trips,
    and running them while the customer's tap waits turns a slow provider into a button
    that appears broken. In the outbox a failure is a retry.

    Until 2026-08-12 this endpoint queued a notification that said "your config is on the
    way" and nothing anywhere fetched a config — the buttons had never worked. What is
    validated here is the part that must not wait: that the access is the caller's, and
    that it is still live.
    """
    if body.type not in vpn_configs.KINDS:
        raise ValidationError("type must be 'ovpn' or 'wg'")
    access = await accesses_svc.get_owned(session, public_id, user.id)
    if body.type not in vpn_configs.available_kinds(access):
        raise ValidationError("this access is no longer active")
    await enqueue(
        session, user_id=user.id, template_code="config_delivered",
        payload={"access_public_id": str(access.public_id), "config_type": body.type},
    )
    return {"status": "sending"}


# ── referral (read; full engine in Stage 4) ─────────────────────────────
@router.get("/referral")
async def referral(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    from app.services import referral as referral_svc

    balances = await referral_svc.balances(session, user.id)
    signups = await session.scalar(
        select(func.count()).select_from(catalog_svc.User).where(
            catalog_svc.User.referrer_user_id == user.id
        )
    )
    return {
        "code": user.referral_code,
        # Arrivals through this person's link, counted whether or not the visitor could be
        # bound. Next to `signups` it answers the question the referrer actually has: is
        # nobody coming, or are they coming and not staying? Those need opposite fixes.
        "link_opens": int(user.referral_clicks or 0),
        "signups": int(signups or 0),
        "balances": balances,
        "min_payout_usd": float(await settings_svc.get(session, "referral_min_payout_usd", 0)),
        # The rate the app promises has to be the rate it pays. It is operator-editable
        # (20 → 23 on 2026-07-30), and the mini-app used to hard-code "20%" in its copy —
        # so the screen was quietly advertising a different deal than the ledger applied.
        "pct": float(await settings_svc.get(session, "referral_pct", 20)),
        # the only rails we pay out on — the client picks from these, never free-types a network
        "payout_rails": payouts_svc.rails_for_client(),
    }


class PayoutRequest(BaseModel):
    wallet_address: str
    network: str


@router.post("/referral/payout")
async def request_payout(
    body: PayoutRequest, user: CurrentUser, session: DbSession
) -> dict[str, Any]:
    from app.services import referral

    payout = await referral.request_payout(
        session, user=user, wallet_address=body.wallet_address, network=body.network
    )
    return {
        "payout_id": payout.id,
        "amount_usd": float(payout.amount_usd),
        "status": payout.status,
    }


# ── faq / requests / terms ──────────────────────────────────────────────
@router.get("/faq")
async def faq(user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(FaqItem).where(FaqItem.is_active).order_by(FaqItem.sort_order)
        )
    ).scalars().all()
    return [{"category": f.category, "question": f.question, "answer": f.answer} for f in rows]


class NewRequest(BaseModel):
    type: str
    subject: str = Field(max_length=200)
    body: str = Field(max_length=10000)


@router.get("/requests")
async def my_requests(user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Request).where(Request.user_id == user.id).order_by(Request.created_at.desc())
        )
    ).scalars().all()
    return [{"id": r.id, "type": r.type, "subject": r.subject, "status": r.status} for r in rows]


@router.post("/requests", status_code=201)
async def create_request(body: NewRequest, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    if body.type not in ("reseller", "support", "custom"):
        raise ValidationError("invalid request type")
    req = Request(user_id=user.id, type=body.type, subject=body.subject, body=body.body)
    session.add(req)
    await session.flush()
    # A reseller enquiry is a lead with nobody watching for it: it landed in the Requests
    # board and waited to be noticed. Wholesale buyers do not wait. Alert goes to every
    # operator chat; a failure here must not lose the request that is already stored.
    with contextlib.suppress(Exception):
        who = f"@{user.tg_username}" if user.tg_username else (user.first_name or f"#{user.id}")
        await ops_alerts.notify_ops(
            session,
            f"📨 New {body.type} request from {who} (tg {user.tg_user_id})\n"
            f"{body.subject}\n{body.body[:500]}",
        )
    return {"id": req.id, "status": req.status}


@router.get("/terms")
async def terms(user: CurrentUser, session: DbSession) -> dict[str, Any]:
    return await users_svc.get_terms(session)


class AcceptTerms(BaseModel):
    version: int
    answers: dict[str, Any] = {}


@router.post("/terms/accept")
async def accept_terms(body: AcceptTerms, user: CurrentUser, session: DbSession) -> dict[str, bool]:
    await users_svc.accept_terms(
        session, user, version=body.version, answers=body.answers, source="twa"
    )
    return {"accepted": True}
