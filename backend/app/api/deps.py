"""Shared FastAPI dependencies: DB session, current TWA user, current admin."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionFactory
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token, is_blacklisted, parse_init_data
from app.models import AdminUser, User


async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(db_session)]


async def twa_identity(authorization: str | None = Header(default=None)) -> dict[str, object]:
    """Validate `Authorization: tma <initDataRaw>` and return the Telegram identity."""
    if not authorization:
        raise Unauthorized("missing tma credentials")
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "tma" or not raw:
        raise Unauthorized("missing tma credentials")
    return parse_init_data(raw)


async def get_current_user(
    session: DbSession, identity: Annotated[dict, Depends(twa_identity)]
) -> User:
    from app.services.users import upsert_from_telegram

    user = await upsert_from_telegram(session, identity)
    if user.status == "banned":
        raise Forbidden("account banned")
    # carry the start_param (deep-link payload) for referral/attribution binding
    user.__dict__["_start_param"] = identity.get("start_param")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def admin_claims(authorization: str | None = Header(default=None)) -> dict[str, object]:
    """Validate `Authorization: Bearer *** and return its claims."""
    if not authorization:
        raise Unauthorized("missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthorized("missing bearer token")
    claims = decode_token(token, expected_type="access")
    jti = claims.get("jti")
    if jti and await is_blacklisted(str(jti)):
        raise Unauthorized("token revoked")
    return claims


async def get_current_admin(
    session: DbSession, claims: Annotated[dict, Depends(admin_claims)]
) -> AdminUser:
    admin = await session.get(AdminUser, int(claims["sub"]))
    if admin is None or not admin.is_active:
        raise Forbidden("admin not found or inactive")
    return admin


CurrentAdmin = Annotated[AdminUser, Depends(get_current_admin)]


def require_owner(admin: CurrentAdmin) -> AdminUser:
    if admin.role != "owner":
        raise Forbidden("owner only")
    return admin


Owner = Annotated[AdminUser, Depends(require_owner)]
