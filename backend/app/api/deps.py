"""Shared FastAPI dependencies: DB session, current TWA user, current admin (Stage 2).

Stage 1 provides the session dependency and the auth building blocks; the concrete
`get_current_user` / `get_current_admin` resolvers land with the TWA/admin routers in Stage 2.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionFactory
from app.core.security import decode_token, parse_init_data


async def db_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def twa_identity(authorization: str = Header(...)) -> dict[str, object]:
    """Validate `Authorization: tma <initDataRaw>` and return the Telegram identity."""
    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != "tma" or not raw:
        from app.core.errors import Forbidden

        raise Forbidden("missing tma credentials")
    return parse_init_data(raw)


async def admin_claims(authorization: str = Header(...)) -> dict[str, object]:
    """Validate `Authorization: Bearer <accessJWT>` and return its claims."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        from app.core.errors import Forbidden

        raise Forbidden("missing bearer token")
    return decode_token(token, expected_type="access")
