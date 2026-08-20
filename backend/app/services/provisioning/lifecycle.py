"""Access lifecycle saga: provision, revoke, rotate, swap (trial), extend, reissue.

Stage 2 runs the mock provisioner synchronously (instant). Stage 3 moves the external
call to a worker job with retries/compensation and swaps in the real iproxy provisioner.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, ProvisioningError
from app.core.logging import log
from app.core.security import encrypt_credentials
from app.models import Access, AccessEvent, Connection, Order, Tariff
from app.services import vpn_configs
from app.services.notifications import enqueue
from app.services.provisioning.allocator import allocate
from app.services.provisioning.registry import get_provisioner
from app.services.provisioning.sync import resolve_sold_location


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def provision_access(
    session: AsyncSession, *, order: Order, notify: bool = True
) -> Access:
    """Issue one proxy against `order`.

    ``notify`` exists for multi-quantity orders: ten proxies issued one after another
    would otherwise send the buyer ten identical "your proxy is ready" messages. The
    caller doing the batch turns it off and sends one message naming the count.
    """
    # for_order_id hands back the phones this order reserved when its invoice was raised.
    # Without it a paid order would queue behind its own hold and be told the pool is empty.
    alloc = await allocate(
        session,
        location_id=order.location_id,
        carrier=order.carrier,
        for_order_id=order.id,
    )
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
    access.iproxy_socks5_access_id = issued.socks5_access_id
    access.iproxy_action_link_id = issued.action_link_id
    access.credentials_enc = encrypt_credentials(issued.credentials)
    access.starts_at = now
    access.expires_at = now + timedelta(minutes=duration)
    access.status = "active"
    order.status = "completed"
    order.completed_at = now
    session.add(AccessEvent(access_id=access.id, type="issued", actor="system"))
    if notify:
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
    # Revoking twice is not a harmless no-op: it appends a second `revoked` AccessEvent
    # describing a transition that never happened, and the event log is what anyone
    # reconstructing "what did we do to this customer" reads afterwards.
    if access.status == "revoked":
        raise Conflict("access is already revoked")
    if access.iproxy_access_id:
        conn = await session.get(Connection, access.connection_id)
        if conn is not None:
            with contextlib.suppress(Exception):  # 404 = already gone; best-effort
                await get_provisioner().revoke(
                    iproxy_connection_id=conn.iproxy_connection_id,
                    iproxy_access_id=access.iproxy_access_id,
                    socks5_access_id=access.iproxy_socks5_access_id,
                    action_link_id=access.iproxy_action_link_id,
                )
    # A VPN config is a separate iproxy resource with no expiry of its own. Leaving it
    # behind hands the customer a tunnel that outlives the month they paid for — the
    # proxy goes and the WireGuard keeps working, indefinitely and invisibly.
    await vpn_configs.revoke_all(session, access)
    now = _utcnow()
    access.status = "revoked"
    access.revoked_at = now
    access.revoke_reason = reason
    session.add(
        AccessEvent(access_id=access.id, type="revoked", actor=actor, meta={"reason": reason})
    )


async def extend_access(session: AsyncSession, *, access: Access, minutes: int) -> None:
    # `expired` is deliberately allowed — the branch below resurrects it. A revoked or
    # failed access is different: nothing here flips it back, so extending only pushed
    # out the expiry of something still unusable and told the customer, by notification,
    # that their access had been extended. Reissue is the action that revives one.
    if access.status in ("revoked", "cancelled", "failed"):
        raise Conflict(f"a {access.status} access cannot be extended — reissue it instead")
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
    # This rotates the *connection*, not the access — and revoking an access frees its
    # connection to be sold to somebody else. Rotating through a dead access would then
    # reach into a different customer's live proxy and change their IP under them. The
    # buyer's own app has always checked this; the admin console did not.
    if access.status not in ("active", "expiring"):
        raise Conflict("only a live access can have its IP rotated")
    conn = await session.get(Connection, access.connection_id)
    if conn is None:
        raise ProvisioningError("connection missing")
    await get_provisioner().rotate_ip(iproxy_connection_id=conn.iproxy_connection_id)
    now = _utcnow()
    conn.last_rotated_at = now
    access.rotations_count += 1
    access.last_rotation_at = now
    session.add(AccessEvent(access_id=access.id, type="rotate_ip", actor=actor))

    # Best-effort: rotation reboots the physical phone and its new exit IP can take on
    # the order of ten seconds to settle, so this read often still reports the city we
    # just left — that's fine, sync_pool re-resolves every connection's city on its own
    # next pass regardless, at most a minute away. This is only a chance to be right
    # sooner. The rotation above has already happened, so an iproxy hiccup on this
    # second, unrelated read must not turn into a failed rotation for the buyer.
    try:
        exit_ip = await get_provisioner().current_exit_ip(
            iproxy_connection_id=conn.iproxy_connection_id
        )
        if exit_ip.city:
            # Same rule as everywhere else: a mapped state in the phone's name wins over
            # whatever the fresh IP resolves to.
            new_loc_id = await resolve_sold_location(
                session, connection_name=conn.name, ip_city=exit_ip.city
            )
            if new_loc_id is not None and new_loc_id != conn.location_id:
                conn.location_id = new_loc_id
    except Exception as exc:  # noqa: BLE001 — the rotation itself already succeeded
        # Not fatal: sync_pool re-resolves every connection's city on its next pass, so a
        # miss here only delays the label. Logged because a persistent failure would keep
        # every rotated phone on a stale city and look, from outside, like the city simply
        # never updates.
        log.warning(
            "rotate.city_refresh_failed",
            connection=conn.iproxy_connection_id,
            error=str(exc),
        )


async def swap_access(
    session: AsyncSession,
    *,
    access: Access,
    location_id: int | None,
    carrier: str | None,
    duration_minutes: int | None = None,
) -> None:
    """Re-provision an access onto a fresh connection.

    Two modes, auto-detected from state:
    * **Swap** (access still live): keep the remaining time and force a *different*
      connection — the trial swap / bad-IP replacement path.
    * **Reactivate** (revoked/expired/no expiry — the admin "reissue" path): grant a
      fresh full tariff duration and flip the access back to ``active``. The old
      connection is already free, so it may be reused.
    """
    now = _utcnow()
    reactivating = (
        access.status in ("revoked", "expired")
        or access.expires_at is None
        or access.expires_at <= now
    )
    alloc = await allocate(
        session,
        location_id=location_id,
        carrier=carrier,
        exclude_id=None if reactivating else access.connection_id,
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
                socks5_access_id=access.iproxy_socks5_access_id,
                action_link_id=access.iproxy_action_link_id,
            )

    if reactivating:
        # An explicit duration wins: when a paid extension lands on an access that expired
        # while the invoice was open, the customer bought *that* plan's time, which is not
        # necessarily the plan the dead access was originally issued on.
        if duration_minutes:
            duration = duration_minutes
        else:
            tariff = await session.scalar(select(Tariff).where(Tariff.code == access.tariff_code))
            duration = tariff.duration_minutes if tariff and tariff.duration_minutes else 60
    else:
        duration = 60
        if access.expires_at is not None:
            duration = max(1, int((access.expires_at - now).total_seconds() // 60))

    issued = await get_provisioner().issue(
        iproxy_connection_id=new_iproxy_id, duration_minutes=duration
    )
    access.connection_id = new_conn_id
    access.iproxy_access_id = issued.iproxy_access_id
    access.iproxy_socks5_access_id = issued.socks5_access_id
    access.iproxy_action_link_id = issued.action_link_id
    access.credentials_enc = encrypt_credentials(issued.credentials)
    access.swap_count += 1
    if reactivating:
        access.status = "active"
        access.starts_at = now
        access.expires_at = now + timedelta(minutes=duration)
        access.revoked_at = None
        access.revoke_reason = None
        access.warned_1h_at = None
        access.warned_24h_at = None
    session.add(
        AccessEvent(
            access_id=access.id,
            type="reissued",
            actor="user",
            meta={"reason": "admin_reissue" if reactivating else "trial_swap"},
        )
    )
