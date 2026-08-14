"""Read + user-facing actions for issued accesses (My Access screen)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, NotFound
from app.core.security import decrypt_credentials
from app.models import Access, Connection, Location, Tariff
from app.services import vpn_configs
from app.services.carriers import carrier_from_ip
from app.services.provisioning.base import ExitIp
from app.services.provisioning.registry import get_provisioner
from app.services.provisioning.sync import _resolve_location

_ACTIVE = ("provisioning", "active", "expiring")


def _summary(access: Access, conn: Connection | None, loc: Location | None) -> dict[str, Any]:
    return {
        "public_id": str(access.public_id),
        "tariff_code": access.tariff_code,
        "status": access.status,
        "city": loc.city if loc else None,
        "state_code": loc.state_code if loc else None,
        "carrier": conn.carrier if conn else None,
        "expires_at": access.expires_at.isoformat() if access.expires_at else None,
        "rotations_count": access.rotations_count,
        # None = auto-rotation off. The interval doubles as the on/off state everywhere.
        "auto_rotate_minutes": access.auto_rotate_minutes,
    }


async def list_for_user(session: AsyncSession, user_id: int) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Access, Connection, Location)
            .join(Connection, Connection.id == Access.connection_id)
            .join(Location, Location.id == Connection.location_id, isouter=True)
            .where(Access.user_id == user_id)
            .order_by(Access.created_at.desc())
        )
    ).all()
    active: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for access, conn, loc in rows:
        (active if access.status in _ACTIVE else history).append(_summary(access, conn, loc))
    return {"active": active, "history": history}


async def _load(
    session: AsyncSession, public_id: str, user_id: int
) -> tuple[Access, Connection | None, Location | None]:
    row = (
        await session.execute(
            select(Access, Connection, Location)
            .join(Connection, Connection.id == Access.connection_id)
            .join(Location, Location.id == Connection.location_id, isouter=True)
            .where(Access.public_id == public_id)
        )
    ).first()
    if row is None:
        raise NotFound("access not found")
    access, conn, loc = row
    if access.user_id != user_id:
        raise Forbidden("not your access")
    return access, conn, loc


async def _exit_ip(conn: Connection | None) -> ExitIp:
    """Live exit IP + city from the provider; best-effort — a provider hiccup must not 500 the view."""
    if conn is None:
        return ExitIp(address=None, city=None)
    try:
        return await get_provisioner().current_exit_ip(
            iproxy_connection_id=conn.iproxy_connection_id
        )
    except Exception:  # noqa: BLE001
        return ExitIp(address=None, city=None)


async def detail_for_user(session: AsyncSession, public_id: str, user_id: int) -> dict[str, Any]:
    access, conn, loc = await _load(session, public_id, user_id)
    creds = decrypt_credentials(access.credentials_enc) if access.credentials_enc else {}
    tariff = await session.scalar(select(Tariff).where(Tariff.code == access.tariff_code))
    max_swaps = tariff.max_user_swaps if tariff else 0
    current_ip = None
    if access.status in ("active", "expiring"):
        exit_ip = await _exit_ip(conn)
        current_ip = exit_ip.address
        # rotate_ip already tries to refresh the city right after a rotation, but that
        # read can land ~10s too early — the phone is still rebooting onto its new IP.
        # This request already pays for the same provider round-trip to show current_ip,
        # so re-resolving the city here is free and catches whatever rotate_ip's early
        # attempt missed, without making the buyer wait for the next sync_pool pass (up
        # to a minute away). Same resolver sync_pool uses, so a location row is never
        # created twice under different rules.
        if conn is not None and exit_ip.city:
            new_loc_id = await _resolve_location(session, exit_ip.city)
            if new_loc_id is not None and new_loc_id != conn.location_id:
                conn.location_id = new_loc_id
                loc = await session.get(Location, new_loc_id)
    summary = _summary(access, conn, loc)
    # The buyer judges the carrier by looking up the address they were handed, so derive
    # it from that same live address whenever we have one. The stored value (last sync)
    # is the fallback for an access whose phone is not reporting an IP right now.
    summary["carrier"] = carrier_from_ip(current_ip) or summary["carrier"]
    return {
        **summary,
        "current_ip": current_ip,
        "credentials": {
            "host": creds.get("host"),
            "http_port": creds.get("http_port"),
            # http and socks5 are two iproxy accesses with their own ports AND their own
            # credentials, so both pairs travel to the client. `login`/`password` stay as
            # the http pair for accesses issued before the socks5 one existed.
            "http_login": creds.get("http_login") or creds.get("login"),
            "http_password": creds.get("http_password") or creds.get("password"),
            "socks5_port": creds.get("socks5_port"),
            "socks5_login": creds.get("socks5_login"),
            "socks5_password": creds.get("socks5_password"),
            "login": creds.get("login"),
            "password": creds.get("password"),
            "rotation_link": creds.get("rotation_link"),
        },
        "swap_left": max(0, max_swaps - access.swap_count),
        # Derived, not hardcoded. It was ["ovpn", "wg"] for every access in every state,
        # so a revoked or expired access still offered buttons for configs that can no
        # longer be issued — and, before 2026-08-12, for configs nothing issued at all.
        "configs_available": vpn_configs.available_kinds(access),
    }


async def get_owned(session: AsyncSession, public_id: str, user_id: int) -> Access:
    access, _, _ = await _load(session, public_id, user_id)
    return access
