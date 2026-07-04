"""Audit trail for admin write actions."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def write(
    session: AsyncSession,
    *,
    admin_id: int | None,
    action: str,
    entity: str,
    entity_id: Any,
    before: dict | None = None,
    after: dict | None = None,
    ip: str | None = None,
) -> None:
    # Fall back to the request IP bound by RequestIdMiddleware on the structlog
    # contextvars, so callers don't need to thread an `ip` argument through every
    # admin endpoint signature.
    if ip is None:
        ctx = structlog.contextvars.get_contextvars()
        ip = ctx.get("request_ip")
    session.add(
        AuditLog(
            admin_id=admin_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            before=before,
            after=after,
            ip=ip,
        )
    )
