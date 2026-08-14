"""Time-driven maintenance logic (called by worker cron jobs; unit-testable directly)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.models import Access, AccessEvent, Connection, Invoice, Order
from app.services.notifications import enqueue
from app.services.provisioning.lifecycle import rotate_ip
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
                    # All three resources, not just the http one: an expiry that left the
                    # socks5 access or the changeip link behind would hand the customer a
                    # proxy that outlives the period they paid for.
                    await get_provisioner().revoke(
                        iproxy_connection_id=conn.iproxy_connection_id,
                        iproxy_access_id=access.iproxy_access_id,
                        socks5_access_id=access.iproxy_socks5_access_id,
                        action_link_id=access.iproxy_action_link_id,
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
        elif (
            _allow_1h_warning(access)
            and access.expires_at <= now + timedelta(hours=1)
            and access.warned_1h_at is None
        ):
            access.status = "expiring"
            access.warned_1h_at = now
            await enqueue(
                session, user_id=access.user_id, template_code="access_expiring_1h",
                payload={"access_public_id": str(access.public_id)},
                dedupe_key=f"exp1:{access.id}",
            )
            warned += 1
        elif (
            _allow_24h_warning(access)
            and access.expires_at <= now + timedelta(hours=24)
            and access.warned_24h_at is None
        ):
            access.status = "expiring"
            access.warned_24h_at = now
            await enqueue(
                session, user_id=access.user_id, template_code="access_expiring_24h",
                payload={"access_public_id": str(access.public_id)},
                dedupe_key=f"exp24:{access.id}",
            )
            warned += 1
    return {"warned": warned, "expired": expired}


async def sweep_auto_rotations(session: AsyncSession) -> dict[str, int]:
    """Rotate the IP of every live access whose auto-rotation interval has elapsed.

    Auto-rotation is ours, not iproxy's. iproxy has per-connection `ip_change_enabled` /
    `ip_change_interval_minutes` settings, but the Console API exposes no way to write
    them (PATCH/PUT on the connection and its settings both refuse), and they would be the
    wrong home anyway: they belong to the *phone*, so they would keep rotating after the
    access is revoked and follow the connection to the next buyer. Here the schedule
    belongs to the access that paid for it and dies with it.

    `last_rotation_at` is the clock, and lifecycle.rotate_ip stamps it however the rotation
    was triggered — so a buyer who rotates by hand resets their own interval instead of
    getting a second rotation moments later.
    """
    now = _utcnow()
    rows = (
        await session.execute(
            select(Access).where(
                Access.status.in_(("active", "expiring")),
                Access.auto_rotate_minutes.is_not(None),
            )
        )
    ).scalars().all()
    rotated = failed = 0
    for access in rows:
        interval = access.auto_rotate_minutes
        if not interval:
            continue
        # Never rotated yet: start the clock from when the access began, so the first
        # automatic rotation lands one full interval after issue rather than immediately.
        since = access.last_rotation_at or access.starts_at
        if since is not None and since + timedelta(minutes=interval) > now:
            continue
        try:
            await rotate_ip(session, access=access, actor="auto")
            rotated += 1
        except Exception as exc:  # noqa: BLE001 — one bad phone must not stop the sweep
            # Stamped anyway so a connection that keeps failing is retried once per
            # interval instead of on every pass, a minute apart, forever.
            access.last_rotation_at = now
            failed += 1
            log.warning("auto_rotate.failed", access_id=access.id, error=str(exc))
    return {"rotated": rotated, "failed": failed}


def _granted_minutes(access: Access) -> float | None:
    """Total granted lifetime (issue → expiry) in minutes, or None if it can't be
    determined. starts_at + expires_at are stamped together at issue, so this is exact."""
    if access.starts_at is None or access.expires_at is None:
        return None
    return (access.expires_at - access.starts_at).total_seconds() / 60.0


def _allow_1h_warning(access: Access) -> bool:
    """Skip the 1h warning for trial-length access (≤1h total) — a 1h proxy would
    otherwise get warned the instant it's issued."""
    total = _granted_minutes(access)
    return total is None or total > 60


def _allow_24h_warning(access: Access) -> bool:
    """Only send the 24h warning when the access lasts longer than a day (weekly+).
    Daily (≤24h) and trial access get no 24h warning."""
    total = _granted_minutes(access)
    return total is None or total > 24 * 60


async def expire_invoices(session: AsyncSession) -> int:
    now = _utcnow()
    invoices = (
        await session.execute(
            select(Invoice).where(
                Invoice.status.in_(("created", "pending", "confirming")),
                Invoice.expires_at < now,
                # never expire an invoice whose on-chain deposit is already in flight —
                # the watcher's finalize pass only sees 'confirming' invoices, so
                # expiring one mid-confirmation strands the customer's funds.
                Invoice.matched_txid.is_(None),
            )
        )
    ).scalars().all()
    for inv in invoices:
        inv.status = "expired"
        order = await session.get(Order, inv.order_id)
        if order is not None and order.status == "awaiting_payment":
            order.status = "expired"
    return len(invoices)
