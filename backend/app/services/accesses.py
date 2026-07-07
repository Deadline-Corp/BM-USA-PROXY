"""Read + user-facing actions for issued accesses (My Access screen)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, NotFound
from app.core.security import decrypt_credentials
from app.models import Access, Connection, Location, Tariff
from app.services.provisioning.registry import get_provisioner

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


async def _current_ip(conn: Connection | None) -> str | None:
    """Live exit IP from the provider; best-effort — a provider hiccup must not 500 the view."""
    if conn is None:
        return None
    try:
        return await get_provisioner().current_ip(iproxy_connection_id=conn.iproxy_connection_id)
    except Exception:  # noqa: BLE001
        return None


async def detail_for_user(session: AsyncSession, public_id: str, user_id: int) -> dict[str, Any]:
    access, conn, loc = await _load(session, public_id, user_id)
    creds = decrypt_credentials(access.credentials_enc) if access.credentials_enc else {}
    tariff = await session.scalar(select(Tariff).where(Tariff.code == access.tariff_code))
    max_swaps = tariff.max_user_swaps if tariff else 0
    current_ip = await _current_ip(conn) if access.status in ("active", "expiring") else None
    return {
        **_summary(access, conn, loc),
        "current_ip": current_ip,
        "credentials": {
            "host": creds.get("host"),
            "http_port": creds.get("http_port"),
            "socks5_port": creds.get("socks5_port"),
            "login": creds.get("login"),
            "password": creds.get("password"),
        },
        "swap_left": max(0, max_swaps - access.swap_count),
        "configs_available": ["ovpn", "wg"],
    }


async def get_owned(session: AsyncSession, public_id: str, user_id: int) -> Access:
    access, _, _ = await _load(session, public_id, user_id)
    return access
