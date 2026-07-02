"""Admin authentication: password check, lockout, token issuance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Unauthorized
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
)
from app.models import AdminUser

MAX_FAILED = 5
LOCK_MINUTES = 15


async def authenticate(session: AsyncSession, *, email: str, password: str) -> AdminUser:
    admin = await session.scalar(select(AdminUser).where(AdminUser.email == email))
    now = datetime.now(UTC)
    if admin is None:
        raise Unauthorized("invalid credentials")
    if admin.locked_until is not None and admin.locked_until > now:
        raise Unauthorized("account temporarily locked")
    if not admin.is_active:
        raise Unauthorized("account inactive")
    if not verify_password(password, admin.password_hash):
        admin.failed_logins += 1
        if admin.failed_logins >= MAX_FAILED:
            admin.locked_until = now + timedelta(minutes=LOCK_MINUTES)
        raise Unauthorized("invalid credentials")
    admin.failed_logins = 0
    admin.locked_until = None
    admin.last_login_at = now
    return admin


def issue_tokens(admin: AdminUser) -> tuple[str, str]:
    return create_access_token(admin.id, admin.role), create_refresh_token(admin.id)
