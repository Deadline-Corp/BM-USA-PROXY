"""Time-driven maintenance logic (called by worker cron jobs; unit-testable directly)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.models import Access, AccessEvent, Connection, Invoice, Order
from app.services.notifications import enqueue
from app.services.provisioning.registry import get_provisioner


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def sweep_access_expiries(session: AsyncSession) -> dict[str, int]:
    """Warn at 24h/1h, expire+revoke when due. Idempotent via warned_* + dedupe keys."""
    now = _utcnow()
    rows = (
        await session.execute(
            select(Access).where(Access.status.in_(("active", "expiring")))
        )
    ).scalars().all()
    warned = expired = 0
    for access in rows:
        if access.expires_at is None:
            continue
        if access.expires_at <= now:
            try:
                conn = await session.get(Connection, access.connection_id)
                if conn is not None and access.iproxy_access_id:
                    await get_provisioner().revoke(
                        iproxy_connection_id=conn.iproxy_connection_id,
                        iproxy_access_id=access.iproxy_access_id,
                    )
            except Exception as exc:  # noqa: BLE001 — best-effort revoke; log and continue
                log.warning("revoke.failed", access_id=access.id, error=str(exc))
            access.status = "expired"
            access.revoked_at = now
            session.add(AccessEvent(access_id=access.id, type="expired", actor="system"))
            await enqueue(
                session, user_id=access.user_id, template_code="access_expired",
                payload={"access_public_id": str(access.public_id)},
                dedupe_key=f"exp:{access.id}",
            )
            expired += 1
        elif access.expires_at <= now + timedelta(hours=1) and access.warned_1h_at is None:
            access.status = "expiring"
            access.warned_1h_at = now
            await enqueue(
                session, user_id=access.user_id, template_code="access_expiring_1h",
                payload={"access_public_id": str(access.public_id)},
                dedupe_key=f"exp1:{access.id}",
            )
            warned += 1
        elif access.expires_at <= now + timedelta(hours=24) and access.warned_24h_at is None:
            access.status = "expiring"
            access.warned_24h_at = now
            await enqueue(
                session, user_id=access.user_id, template_code="access_expiring_24h",
                payload={"access_public_id": str(access.public_id)},
                dedupe_key=f"exp24:{access.id}",
            )
            warned += 1
    return {"warned": warned, "expired": expired}


async def expire_invoices(session: AsyncSession) -> int:
    now = _utcnow()
    invoices = (
        await session.execute(
            select(Invoice).where(
                Invoice.status.in_(("created", "pending", "confirming")),
                Invoice.expires_at < now,
            )
        )
    ).scalars().all()
    for inv in invoices:
        inv.status = "expired"
        order = await session.get(Order, inv.order_id)
        if order is not None and order.status == "awaiting_payment":
            order.status = "expired"
    return len(invoices)
