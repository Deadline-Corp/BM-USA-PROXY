"""Access lifecycle saga: provision, revoke, rotate, swap (trial), extend, reissue.

Stage 2 runs the mock provisioner synchronously (instant). Stage 3 moves the external
call to a worker job with retries/compensation and swaps in the real iproxy provisioner.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, ProvisioningError
from app.core.security import encrypt_credentials
from app.models import Access, AccessEvent, Connection, Order
from app.services.notifications import enqueue
from app.services.provisioning.allocator import allocate
from app.services.provisioning.registry import get_provisioner


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def provision_access(session: AsyncSession, *, order: Order) -> Access:
    alloc = await allocate(session, location_id=order.location_id, carrier=order.carrier)
    if alloc is None:
        raise ProvisioningError("no free connection")
    conn_id, iproxy_conn_id = alloc
    duration = order.duration_minutes or 60

    access = Access(
        user_id=order.user_id,
        order_id=order.id,
        connection_id=conn_id,
        tariff_code=order.tariff_code,
        status="provisioning",
    )
    session.add(access)
    await session.flush()

    try:
        issued = await get_provisioner().issue(
            iproxy_connection_id=iproxy_conn_id, duration_minutes=duration
        )
    except ProvisioningError:
        # Release the connection: mark the half-created access as failed so the
        # unique "one live access per connection" index frees it for reuse.
        access.status = "failed"
        session.add(
            AccessEvent(access_id=access.id, type="provision_failed", actor="system")
        )
        raise
    now = _utcnow()
    access.iproxy_access_id = issued.iproxy_access_id
    access.credentials_enc = encrypt_credentials(issued.credentials)
    access.starts_at = now
    access.expires_at = now + timedelta(minutes=duration)
    access.status = "active"
    order.status = "completed"
    order.completed_at = now
    session.add(AccessEvent(access_id=access.id, type="issued", actor="system"))
    await enqueue(
        session,
        user_id=order.user_id,
        template_code="access_issued",
        payload={"access_public_id": str(access.public_id)},
    )
    return access


async def revoke_access(
    session: AsyncSession, *, access: Access, reason: str, actor: str = "system"
) -> None:
    if access.iproxy_access_id:
        conn = await session.get(Connection, access.connection_id)
        if conn is not None:
            with contextlib.suppress(Exception):  # 404 = already gone; best-effort
                await get_provisioner().revoke(
                    iproxy_connection_id=conn.iproxy_connection_id,
                    iproxy_access_id=access.iproxy_access_id,
                )
    now = _utcnow()
    access.status = "revoked"
    access.revoked_at = now
    access.revoke_reason = reason
    session.add(
        AccessEvent(access_id=access.id, type="revoked", actor=actor, meta={"reason": reason})
    )


async def extend_access(session: AsyncSession, *, access: Access, minutes: int) -> None:
    base = access.expires_at or _utcnow()
    if base < _utcnow():
        base = _utcnow()
    access.expires_at = base + timedelta(minutes=minutes)
    if access.status in ("expiring", "expired"):
        access.status = "active"
    session.add(AccessEvent(access_id=access.id, type="extended", actor="system",
                            meta={"minutes": minutes}))
    await enqueue(
        session,
        user_id=access.user_id,
        template_code="access_extended",
        payload={"access_public_id": str(access.public_id)},
    )


async def rotate_ip(session: AsyncSession, *, access: Access, actor: str = "user") -> None:
    conn = await session.get(Connection, access.connection_id)
    if conn is None:
        raise ProvisioningError("connection missing")
    await get_provisioner().rotate_ip(iproxy_connection_id=conn.iproxy_connection_id)
    access.rotations_count += 1
    access.last_rotation_at = _utcnow()
    session.add(AccessEvent(access_id=access.id, type="rotate_ip", actor=actor))


async def swap_access(
    session: AsyncSession, *, access: Access, location_id: int | None, carrier: str | None
) -> None:
    """Move an active access to a different connection, keeping expires_at (trial swap)."""
    alloc = await allocate(
        session, location_id=location_id, carrier=carrier, exclude_id=access.connection_id
    )
    if alloc is None:
        raise Conflict("no free connection for the requested selection")
    new_conn_id, new_iproxy_id = alloc

    old_conn = await session.get(Connection, access.connection_id)
    if access.iproxy_access_id and old_conn is not None:
        with contextlib.suppress(Exception):
            await get_provisioner().revoke(
                iproxy_connection_id=old_conn.iproxy_connection_id,
                iproxy_access_id=access.iproxy_access_id,
            )

    remaining = 60
    if access.expires_at is not None:
        remaining = max(1, int((access.expires_at - _utcnow()).total_seconds() // 60))
    issued = await get_provisioner().issue(
        iproxy_connection_id=new_iproxy_id, duration_minutes=remaining
    )
    access.connection_id = new_conn_id
    access.iproxy_access_id = issued.iproxy_access_id
    access.credentials_enc = encrypt_credentials(issued.credentials)
    access.swap_count += 1
    session.add(
        AccessEvent(
            access_id=access.id, type="reissued", actor="user", meta={"reason": "trial_swap"}
        )
    )
