"""Issue and revoke the VPN configs a customer downloads for their access.

The mini-app has shown "OpenVPN config" and "WireGuard config" buttons since launch. They
queued a notification that said the config was on its way and nothing ever sent one —
`configs_available` was hardcoded to both protocols and no code fetched a config at all.
This module is what makes those buttons true.

Two rules, both of which cost real money if they are only conventions:

* **One config per protocol per access.** iproxy caps configs at 20 per connection, so a
  customer tapping the button repeatedly could exhaust a phone and lock out every other
  buyer on it. The rule is a unique index, not an `if` — two taps arriving together
  cannot both win.
* **A config dies with the access it was bought for.** iproxy VPN accesses have no expiry
  of their own; nothing removes them when the month runs out. Revoking the proxy and
  leaving the tunnel would give the product away permanently, and quietly.
"""

from __future__ import annotations

import contextlib

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.core.logging import log
from app.models import Access, AccessVpnConfig, Connection
from app.services.provisioning.registry import get_provisioner

KINDS = ("ovpn", "wg")

# The states in which a config may be handed out. A revoked or expired access has no
# proxy behind it any more, so a config issued against it would be a tunnel the customer
# did not pay for — the same leak this module exists to prevent, entered from the front.
LIVE_STATUSES = ("active", "expiring")

_EXTENSION = {"ovpn": "ovpn", "wg": "conf"}


def available_kinds(access: Access) -> list[str]:
    """Protocols this access may be given a config for, right now."""
    return list(KINDS) if access.status in LIVE_STATUSES else []


def filename_for(access: Access, kind: str) -> str:
    """What the file is called when it lands in the customer's chat.

    The access id is in the name on purpose: a customer with two proxies gets two files,
    and "config.conf" twice is how the wrong one ends up imported.
    """
    return f"bmusa-{str(access.public_id)[:8]}-{kind}.{_EXTENSION[kind]}"


async def _connection_of(session: AsyncSession, access: Access) -> Connection:
    conn = await session.get(Connection, access.connection_id)
    if conn is None:  # pragma: no cover - FK guarantees it
        raise ValidationError("this access has no connection to build a config on")
    return conn


async def ensure_config(session: AsyncSession, access: Access, kind: str) -> bytes:
    """The config file for this access and protocol, creating it once if needed.

    Called from the notification worker rather than the request path: creating a VPN
    access is two iproxy round-trips, and doing them while the customer's tap is waiting
    turns a slow provider into a failed button. Here a failure is a retry.
    """
    if kind not in KINDS:
        raise ValidationError(f"unknown config type {kind!r}")
    if access.status not in LIVE_STATUSES:
        raise ValidationError("this access is no longer active")

    conn = await _connection_of(session, access)
    existing = await session.scalar(
        select(AccessVpnConfig).where(
            AccessVpnConfig.access_id == access.id, AccessVpnConfig.kind == kind
        )
    )
    if existing is not None:
        # Same file every time. Re-fetched rather than stored: the config carries a
        # private key, and a key we never write down is a key that cannot leak from our
        # database.
        return await get_provisioner().vpn_config(
            iproxy_connection_id=conn.iproxy_connection_id,
            kind=kind,
            vpn_access_id=existing.iproxy_vpn_access_id,
        )

    created = await get_provisioner().create_vpn_access(
        iproxy_connection_id=conn.iproxy_connection_id,
        kind=kind,
        name=f"bmusa-{str(access.public_id)[:8]}",
    )
    row = AccessVpnConfig(access_id=access.id, kind=kind, iproxy_vpn_access_id=created)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        # Two taps raced and the other one won. Ours is now an orphan on iproxy's side —
        # delete it, or it counts against the connection's 20 forever.
        await session.rollback()
        with contextlib.suppress(Exception):
            await get_provisioner().delete_vpn_access(
                iproxy_connection_id=conn.iproxy_connection_id,
                kind=kind,
                vpn_access_id=created,
            )
        winner = await session.scalar(
            select(AccessVpnConfig).where(
                AccessVpnConfig.access_id == access.id, AccessVpnConfig.kind == kind
            )
        )
        if winner is None:  # pragma: no cover - the constraint says otherwise
            raise
        return await get_provisioner().vpn_config(
            iproxy_connection_id=conn.iproxy_connection_id,
            kind=kind,
            vpn_access_id=winner.iproxy_vpn_access_id,
        )

    log.info("vpn.config_issued", access=str(access.public_id), kind=kind)
    return await get_provisioner().vpn_config(
        iproxy_connection_id=conn.iproxy_connection_id,
        kind=kind,
        vpn_access_id=created,
    )


async def revoke_all(session: AsyncSession, access: Access) -> int:
    """Tear down every VPN config issued for this access. Returns how many.

    Best-effort per config on purpose: one already gone on iproxy's side must not stop
    the others being removed, and revocation as a whole must not fail because a tunnel
    was deleted by hand. The row goes either way — a row we cannot delete remotely is a
    row that would otherwise be retried forever.
    """
    rows = list(
        (
            await session.execute(
                select(AccessVpnConfig).where(AccessVpnConfig.access_id == access.id)
            )
        ).scalars()
    )
    if not rows:
        return 0
    conn = await session.get(Connection, access.connection_id)
    for row in rows:
        if conn is not None:
            with contextlib.suppress(Exception):
                await get_provisioner().delete_vpn_access(
                    iproxy_connection_id=conn.iproxy_connection_id,
                    kind=row.kind,
                    vpn_access_id=row.iproxy_vpn_access_id,
                )
        await session.delete(row)
    log.info("vpn.configs_revoked", access=str(access.public_id), count=len(rows))
    return len(rows)
