"""Referral engine — append-only ledger with holds, pro-rata reversal, payouts.

Model (INVARIANT #5):
- accrual entries: amount > 0, status hold → available (via release) → requested → paid.
- reversal entries: amount < 0 (refund clawback), released alongside their accrual.
- available balance := SUM(amount_usd) WHERE status = 'available'  (accruals + reversals net).
- a payout moves ALL 'available' entries (positive and negative) → 'requested' → 'paid';
  reject returns them to 'available'. A reversal that lands after payout becomes a negative
  'available' entry that is eaten by the referrer's future accruals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound, ValidationError
from app.models import Order, Payout, ReferralLedger, User
from app.services import ops_alerts
from app.services import payouts as payouts_svc
from app.services import settings as settings_svc
from app.services.notifications import enqueue


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _q(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


# ── binding (called from the bot /start) ────────────────────────────────
async def record_click(session: AsyncSession, *, code: str, visitor: User) -> None:
    """Somebody opened a referral link. Count it against whoever owns the code.

    Deliberately separate from binding and deliberately looser: a click counts even when
    the visitor cannot be bound — they already have a referrer, or they are simply coming
    back. Otherwise the number would only ever equal the number of sign-ups, and the whole
    question the card answers ("do people click and then not sign up?") could not be asked.

    Opening your own link is not a click. It costs nothing to check and it stops the one
    number a referrer can trivially inflate by hand.
    """
    referrer_id = await session.scalar(
        select(User.id).where(User.referral_code == code, User.id != visitor.id)
    )
    if referrer_id is None:
        return
    await session.execute(
        update(User)
        .where(User.id == referrer_id)
        .values(referral_clicks=User.referral_clicks + 1)
    )


async def try_bind(session: AsyncSession, *, referee: User, code: str) -> bool:
    if referee.referrer_user_id is not None:
        return False
    referrer = await session.scalar(select(User).where(User.referral_code == code))
    if referrer is None or referrer.id == referee.id:
        return False
    # no 2-cycle (A→B→A)
    if referrer.referrer_user_id == referee.id:
        return False
    referee.referrer_user_id = referrer.id
    referee.referral_bound_at = _utcnow()
    await enqueue(
        session, user_id=referrer.id, template_code="referral_joined",
        payload={"referee": referee.tg_username or str(referee.tg_user_id)},
    )
    return True


# ── accrual / release / reversal ────────────────────────────────────────
async def accrue(session: AsyncSession, *, order: Order) -> None:
    if not order.referrer_user_id or order.origin == "admin":
        return
    if float(order.amount_usd) <= 0:
        return
    pct = Decimal(str(await settings_svc.get(session, "referral_pct", 20)))
    hold_days = int(await settings_svc.get(session, "referral_hold_days", 14))
    amount = _q(Decimal(str(order.amount_usd)) * pct / Decimal(100))
    stmt = insert(ReferralLedger).values(
        referrer_user_id=order.referrer_user_id,
        referee_user_id=order.user_id,
        order_id=order.id,
        kind="accrual",
        base_amount_usd=order.amount_usd,
        pct=pct,
        amount_usd=amount,
        status="hold",
        hold_until=(order.paid_at or _utcnow()) + timedelta(days=hold_days),
    )
    stmt = stmt.on_conflict_do_nothing(  # one accrual per order (partial unique index)
        index_elements=["order_id"], index_where=text("kind = 'accrual'")
    )
    await session.execute(stmt)
    await enqueue(
        session, user_id=order.referrer_user_id, template_code="referral_accrued",
        payload={"amount_usd": float(amount)},
    )


async def release_holds(session: AsyncSession) -> int:
    """Move due 'hold' entries (accruals AND reversals) → 'available'."""
    result = await session.execute(
        update(ReferralLedger)
        .where(ReferralLedger.status == "hold", ReferralLedger.hold_until <= _utcnow())
        .values(status="available")
        .returning(ReferralLedger.id)
    )
    return len(result.all())


async def reverse(session: AsyncSession, *, order: Order, refund_amount_usd: Decimal) -> None:
    accrual = await session.scalar(
        select(ReferralLedger).where(
            ReferralLedger.order_id == order.id, ReferralLedger.kind == "accrual"
        )
    )
    if accrual is None:
        return
    order_amount = Decimal(str(order.amount_usd))
    if order_amount <= 0:
        return
    ratio = min(Decimal(1), max(Decimal(0), Decimal(str(refund_amount_usd)) / order_amount))
    reversal_amount = _q(Decimal(str(accrual.amount_usd)) * ratio)
    if reversal_amount <= 0:
        return

    if accrual.status == "hold" and ratio >= 1:
        accrual.status = "reversed"
        return
    # partial-on-hold rides with the accrual; otherwise it hits available immediately
    status = "hold" if accrual.status == "hold" else "available"
    session.add(
        ReferralLedger(
            referrer_user_id=accrual.referrer_user_id,
            referee_user_id=accrual.referee_user_id,
            order_id=order.id,
            kind="reversal",
            base_amount_usd=refund_amount_usd,
            pct=accrual.pct,
            amount_usd=-reversal_amount,
            status=status,
            hold_until=accrual.hold_until if status == "hold" else None,
            reversal_of_id=accrual.id,
        )
    )


# ── balances / payouts ──────────────────────────────────────────────────
async def _sum(session: AsyncSession, user_id: int, status: str) -> Decimal:
    val = await session.scalar(
        select(func.coalesce(func.sum(ReferralLedger.amount_usd), 0)).where(
            ReferralLedger.referrer_user_id == user_id, ReferralLedger.status == status
        )
    )
    return Decimal(str(val or 0))


async def balances(session: AsyncSession, user_id: int) -> dict[str, float]:
    return {
        s: float(await _sum(session, user_id, s))
        for s in ("hold", "available", "requested", "paid")
    }


async def request_payout(
    session: AsyncSession, *, user: User, wallet_address: str, network: str
) -> Payout:
    # Reject a wrong-network / malformed address BEFORE taking the lock — an irreversible
    # transfer to a mistyped address is the most expensive failure in this flow.
    canonical_network, canonical_address = payouts_svc.validate_target(network, wallet_address)
    # Serialize concurrent payout requests for this user → no phantom double-payout (TOCTOU).
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": user.id})
    available = await _sum(session, user.id, "available")
    if available <= 0:
        raise ValidationError("no funds available to withdraw")
    # Threshold is 0 by client decision, but stays configurable.
    min_payout = Decimal(str(await settings_svc.get(session, "referral_min_payout_usd", 0)))
    if min_payout > 0 and available < min_payout:
        raise ValidationError(f"minimum payout is ${min_payout}")
    payout = Payout(
        referrer_user_id=user.id,
        amount_usd=_q(available),
        wallet_address=canonical_address,
        network=canonical_network,
        status="requested",
    )
    session.add(payout)
    await session.flush()
    await session.execute(
        update(ReferralLedger)
        .where(ReferralLedger.referrer_user_id == user.id, ReferralLedger.status == "available")
        .values(status="requested", payout_id=payout.id)
    )
    # Both sides, because filing a request used to notify nobody. The partner saw their
    # balance go to zero with no acknowledgement anywhere, and the operator only learned of
    # the request by opening the admin console and looking — so a payout sat until somebody
    # happened to check. Reported by the client's partner on 2026-09-04.
    await enqueue(
        session, user_id=user.id, template_code="payout_requested",
        payload={
            "payout_id": payout.id,
            "amount_usd": float(payout.amount_usd),
            "network": canonical_network,
        },
    )
    who = f"@{user.tg_username}" if user.tg_username else f"id {user.tg_user_id}"
    await ops_alerts.notify_ops(
        session,
        f"Payout requested: ${_q(available)} to {canonical_network}\n"
        f"{canonical_address}\n"
        f"From: {who}",
    )
    return payout


async def _get_payout(session: AsyncSession, payout_id: int) -> Payout:
    payout = await session.get(Payout, payout_id)
    if payout is None:
        raise NotFound("payout not found")
    return payout


async def approve_payout(session: AsyncSession, payout_id: int, *, operator_id: int) -> Payout:
    payout = await _get_payout(session, payout_id)
    if payout.status != "requested":
        raise Conflict("payout not in requested state")
    payout.status = "approved"
    payout.operator_id = operator_id
    return payout


async def mark_payout_paid(
    session: AsyncSession, payout_id: int, *, tx_hash: str, operator_id: int | None
) -> Payout:
    """Close a payout as paid. ``operator_id`` is None when the on-chain watcher confirmed
    it automatically — we don't invent a human actor for a machine observation."""
    payout = await _get_payout(session, payout_id)
    if payout.status not in ("requested", "approved"):
        raise Conflict("payout not payable")
    # Defense-in-depth: never pay out more than the ledger rows actually backing this payout.
    backing = await session.scalar(
        select(func.coalesce(func.sum(ReferralLedger.amount_usd), 0)).where(
            ReferralLedger.payout_id == payout.id
        )
    )
    if _q(Decimal(str(backing))) != _q(Decimal(str(payout.amount_usd))):
        raise Conflict("payout amount does not match its backing ledger (possible duplicate)")
    payout.status = "paid"
    payout.tx_hash = tx_hash
    if operator_id is not None:  # keep the approving operator when auto-confirming
        payout.operator_id = operator_id
    payout.processed_at = _utcnow()
    await session.execute(
        update(ReferralLedger)
        .where(ReferralLedger.payout_id == payout.id)
        .values(status="paid")
    )
    await enqueue(
        session, user_id=payout.referrer_user_id, template_code="payout_paid",
        payload={"amount_usd": float(payout.amount_usd), "tx_hash": tx_hash},
    )
    return payout


async def reject_payout(
    session: AsyncSession, payout_id: int, *, reason: str, operator_id: int
) -> Payout:
    payout = await _get_payout(session, payout_id)
    if payout.status not in ("requested", "approved"):
        raise Conflict("payout not rejectable")
    payout.status = "rejected"
    payout.reject_reason = reason
    payout.operator_id = operator_id
    payout.processed_at = _utcnow()
    await session.execute(
        update(ReferralLedger)
        .where(ReferralLedger.payout_id == payout.id)
        .values(status="available", payout_id=None)
    )
    await enqueue(
        session, user_id=payout.referrer_user_id, template_code="payout_rejected",
        payload={"reason": reason},
    )
    return payout


def mask_handle(username: str | None, tg_user_id: int | None) -> str:
    """How a referrer is shown their own referrals.

    The last three characters of the handle and nothing else — enough for the partner to
    tell one person they brought from another, and to recognise somebody they know, without
    handing them a list of this business's customers to approach directly. Somebody with no
    username is shown the tail of their Telegram id for the same reason: the row still has
    to be distinguishable from the row above it.
    """
    handle = (username or "").strip().lstrip("@")
    if handle:
        return f"…{handle[-3:]}" if len(handle) > 3 else f"@{handle}"
    tail = str(tg_user_id or "")[-3:]
    return f"id …{tail}" if tail else "—"


async def payout_history(session: AsyncSession, user_id: int, *, limit: int = 20) -> list[dict]:
    """This partner's payout requests, newest first.

    The cabinet showed a balance and nothing else, so a request that had been filed was
    indistinguishable from money that had vanished — which is exactly how the client's
    partner read it.
    """
    rows = (
        await session.execute(
            select(Payout)
            .where(Payout.referrer_user_id == user_id)
            .order_by(Payout.requested_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": p.id,
            "amount_usd": float(p.amount_usd),
            "network": p.network,
            "status": p.status,
            "tx_hash": p.tx_hash,
            "reject_reason": p.reject_reason,
            "requested_at": p.requested_at.isoformat(),
            "processed_at": p.processed_at.isoformat() if p.processed_at else None,
        }
        for p in rows
    ]


async def referral_breakdown(session: AsyncSession, user_id: int, *, limit: int = 50) -> list[dict]:
    """Who this partner brought and what each of them has earned them.

    Everyone they referred, including the ones who have not bought yet — "signed up and
    never paid" and "has not signed up" are different problems and the partner is the one
    who can act on the difference.
    """
    earned = (
        select(
            ReferralLedger.referee_user_id.label("uid"),
            func.coalesce(func.sum(ReferralLedger.amount_usd), 0).label("earned"),
        )
        .where(
            ReferralLedger.referrer_user_id == user_id,
            ReferralLedger.kind == "accrual",
        )
        .group_by(ReferralLedger.referee_user_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(User.id, User.tg_username, User.tg_user_id, User.created_at, earned.c.earned)
            .outerjoin(earned, earned.c.uid == User.id)
            .where(User.referrer_user_id == user_id)
            .order_by(func.coalesce(earned.c.earned, 0).desc(), User.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "handle": mask_handle(username, tg_user_id),
            "earned_usd": float(earned_usd or 0),
            "joined_at": created_at.isoformat() if created_at else None,
        }
        for _id, username, tg_user_id, created_at, earned_usd in rows
    ]
